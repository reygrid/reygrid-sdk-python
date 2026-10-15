"""
ReyGrid API client — synchronous and asynchronous.

Built on httpx, with full control over the base URL, authentication,
SSE streaming, and typed responses.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, BinaryIO, Dict, Iterator, List, Optional, TypeVar, Union

import httpx

from .exceptions import (
    ReyGridApiError,
    ReyGridNetworkError,
    ReyGridStreamError,
    map_api_error,
)
from .models import (
    AgentDetailResponse,
    AgentResponse,
    AgentsResponse,
    CancelToolResponse,
    CrawlResponse,
    DeleteSourceResponse,
    FeedbackRating,
    FeedbackResponse,
    ModelsResponse,
    SearchResponse,
    SourceCreatedResponse,
    SourcesResponse,
    SourceType,
    UsageReport,
    ChatDeltaEvent,
    ChatRequest,
    ChatResponse,
    ChatUsage,
    Conversation,
    ConversationsResponse,
    DeleteMessagesResponse,
    Message,
    MessagesResponse,
    PingResponse,
    Tool,
    Usage,
    ValidateResponse,
    _parse_dataclass,
)
from .sse import _extract_events, _parse_delta, parse_sse_stream

log = logging.getLogger("reygrid")

DEFAULT_BASE_URL = "https://reygrid.com/api/v1"
LONG_TIMEOUT = 600.0
"""File uploads and website crawls are indexed before the API responds."""
T = TypeVar("T")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

@dataclass
class PaginatedResult:
    """A single page of paginated results."""

    data: List[Any]
    pagination: "Pagination"

    def __post_init__(self):
        from .models import Pagination

        if not isinstance(self.pagination, Pagination):
            self.pagination = Pagination(**self.pagination)  # type: ignore


class Paginator:
    """Iterate over paginated endpoints.

    Works as a sync or async context / iterator.

    Usage::

        paginator = reygrid_conversations.paginate_conversations("agent-1")
        for page in paginator:
            for convo in page.data:
                print(convo.conversationId)
    """

    def __init__(
        self,
        fetcher,
        page_size: int = 20,
    ) -> None:
        self._fetcher = fetcher
        self._page_size = min(max(1, page_size), 100)
        self._page = 1
        self._done = False

    def reset(self) -> None:
        self._page = 1
        self._done = False

    def __iter__(self) -> Iterator[PaginatedResult]:
        return self._sync_gen()

    def _sync_gen(self) -> Iterator[PaginatedResult]:
        self.reset()
        while not self._done:
            result = self._fetcher(self._page, self._page_size)
            if not result.pagination.hasNextPage:
                self._done = True
            self._page += 1
            yield result

    def __aiter__(self) -> AsyncIterator[PaginatedResult]:
        return self._async_gen()

    async def _async_gen(self) -> AsyncIterator[PaginatedResult]:
        self.reset()
        while not self._done:
            result = await self._fetcher(self._page, self._page_size)
            if not result.pagination.hasNextPage:
                self._done = True
            self._page += 1
            yield result

    def all(self) -> List[Any]:
        """Fetch every page and return all items (sync, use with caution)."""
        items = []
        for page in self:
            items.extend(page.data)
        return items


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

@dataclass
class ReyGridConfig:
    """Configuration for the ReyGrid client."""

    api_key: Optional[str] = None
    """ReyGrid API key sent as ``Authorization: Bearer <key>``."""

    base_url: str = DEFAULT_BASE_URL
    """API base URL. Override to point at a custom/local/proxy deployment."""

    headers: Optional[Dict[str, str]] = None
    """Additional default headers sent with every request."""

    timeout: float = 60.0
    """Request timeout in seconds (default 60)."""

    httpx_client: Optional[httpx.Client] = None
    """Optional pre-configured httpx sync client (shared connections, proxy)."""

    httpx_async_client: Optional[httpx.AsyncClient] = None
    """Optional pre-configured httpx async client."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class ReyGrid:
    """ReyGrid API client with both sync and async methods.

    Usage::

        # Sync
        client = ReyGrid(api_key="...")
        ping = client.ping()
        chat = client.chat("agent-1", "Hello!")

        # Async
        async with ReyGrid(api_key="...", ...) as client:
            ping = await client.async_ping()
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        # Merge dict config + kwargs
        merged: Dict[str, Any] = {}
        if config:
            merged.update(config)
        merged.update(kwargs)

        self.base_url = merged.get("base_url", DEFAULT_BASE_URL)
        if self.base_url.endswith("/"):
            self.base_url = self.base_url.rstrip("/")

        self.api_key: Optional[str] = merged.get("api_key")
        self.headers: Dict[str, str] = dict(merged.get("headers") or {})
        self.timeout: float = merged.get("timeout", 60.0)

        client = merged.get("httpx_client")
        async_client = merged.get("httpx_async_client")

        self._client: httpx.Client = client or httpx.Client(
            headers=self._default_headers(),
            timeout=httpx.Timeout(self.timeout),
        )
        self._async_client: httpx.AsyncClient = async_client or httpx.AsyncClient(
            headers=self._default_headers(),
            timeout=httpx.Timeout(self.timeout),
        )

    def _default_headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {"Accept": "application/json"}
        h.update(self.headers)
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def set_api_key(self, key: Optional[str]) -> None:
        """Set (or clear) the API key at runtime."""
        self.api_key = key
        self._client.headers["Authorization"] = f"Bearer {key}" if key else ""
        self._async_client.headers["Authorization"] = f"Bearer {key}" if key else ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying httpx clients."""
        self._client.close()

    async def aclose(self) -> None:
        """Close the underlying async httpx client."""
        await self._async_client.aclose()

    def __enter__(self) -> ReyGrid:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    async def __aenter__(self) -> ReyGrid:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Internal request helpers
    # ------------------------------------------------------------------

    def _build_url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _check_response(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            body = {"message": response.text or f"HTTP {response.status_code}"}
        raise map_api_error(response.status_code, body)

    def _request_sync(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        url = self._build_url(path)
        try:
            res = self._client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise ReyGridNetworkError(
                f"Timeout calling {method} {url}", cause=exc,
            ) from exc
        except httpx.TransportError as exc:
            raise ReyGridNetworkError(
                f"Network error calling {method} {url}: {exc}", cause=exc,
            ) from exc
        self._check_response(res)
        return res

    async def _request_async(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        url = self._build_url(path)
        try:
            res = await self._async_client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise ReyGridNetworkError(
                f"Timeout calling {method} {url}", cause=exc,
            ) from exc
        except httpx.TransportError as exc:
            raise ReyGridNetworkError(
                f"Network error calling {method} {url}: {exc}", cause=exc,
            ) from exc
        self._check_response(res)
        return res

    # ------------------------------------------------------------------
    # Ping / Validate
    # ------------------------------------------------------------------

    def ping(self) -> PingResponse:
        """Health check — is the API operational? (sync)"""
        res = self._request_sync("GET", "/ping")
        data = res.json()
        return _parse_dataclass(PingResponse, data)

    async def async_ping(self) -> PingResponse:
        """Health check (async)."""
        res = await self._request_async("GET", "/ping")
        data = res.json()
        return _parse_dataclass(PingResponse, data)

    def validate(self) -> ValidateResponse:
        """Validate API key and return usage info (sync)."""
        res = self._request_sync("GET", "/validate")
        data = res.json()
        return _parse_dataclass(ValidateResponse, data)

    async def async_validate(self) -> ValidateResponse:
        """Validate API key (async)."""
        res = await self._request_async("GET", "/validate")
        data = res.json()
        return _parse_dataclass(ValidateResponse, data)

    def get_usage(self) -> Usage:
        """Convenience: usage/quota of this API key (sync). For account usage see get_usage_report()."""
        return self.validate().usage

    async def async_get_usage(self) -> Usage:
        """Convenience: resolve the current usage/quota (async)."""
        v = await self.async_validate()
        return v.usage

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def _chat_params(
        self,
        message: str,
        *,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream: bool = False,
        tools: Optional[List[Tool]] = None,
        results: Optional[List[dict]] = None,
    ) -> dict:
        body: Dict[str, Any] = {"message": message}
        if conversation_id is not None:
            body["conversationId"] = conversation_id
        if user_id is not None:
            body["userId"] = user_id
        if stream:
            body["stream"] = True
        if tools:
            body["tools"] = [t if isinstance(t, dict) else t.__dict__ for t in tools]
        if results:
            body["results"] = results
        return body

    def chat(
        self,
        agent_id: str,
        message: str,
        *,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tools: Optional[List[Tool]] = None,
        results: Optional[List[dict]] = None,
    ) -> ChatResponse:
        """Send a message to an agent (sync, non-streaming)."""
        body = self._chat_params(message, conversation_id=conversation_id, user_id=user_id, tools=tools, results=results)
        res = self._request_sync("POST", f"/agents/{_esc(agent_id)}/chat", json=body)
        data = res.json()
        return _parse_dataclass(ChatResponse, data)

    async def async_chat(
        self,
        agent_id: str,
        message: str,
        *,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tools: Optional[List[Tool]] = None,
        results: Optional[List[dict]] = None,
    ) -> ChatResponse:
        """Send a message to an agent (async, non-streaming)."""
        body = self._chat_params(message, conversation_id=conversation_id, user_id=user_id, tools=tools, results=results)
        res = await self._request_async("POST", f"/agents/{_esc(agent_id)}/chat", json=body)
        data = res.json()
        return _parse_dataclass(ChatResponse, data)

    # ------------------------------------------------------------------
    # Streaming chat (SSE)
    # ------------------------------------------------------------------

    def stream_chat(
        self,
        agent_id: str,
        message: str,
        *,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tools: Optional[List[Tool]] = None,
        results: Optional[List[dict]] = None,
    ) -> Iterator[ChatDeltaEvent]:
        """Stream a chat response via SSE (sync generator).

        Usage::

            for delta in client.stream_chat("agent-1", "Hello!"):
                print(delta.content or "", end="")
        """
        body = self._chat_params(message, conversation_id=conversation_id, user_id=user_id, stream=True, tools=tools, results=results)
        url = self._build_url(f"/agents/{_esc(agent_id)}/chat")

        try:
            with self._client.stream("POST", url, json=body) as res:
                if res.status_code >= 400:
                    try:
                        err_body = res.json()
                    except (json.JSONDecodeError, ValueError):
                        err_body = {"message": f"HTTP {res.status_code}"}
                    raise map_api_error(res.status_code, err_body)
                buf = ""
                for chunk in res.iter_text():
                    buf += chunk
                    remaining, events = _extract_events(buf)
                    buf = remaining
                    for raw in events:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            data: dict = json.loads(raw)
                        except json.JSONDecodeError as exc:
                            raise ReyGridStreamError(
                                f"Failed to parse SSE frame: {raw[:120]}"
                            ) from exc
                        yield ChatDeltaEvent(
                            success=data.get("success"),
                            conversationId=data.get("conversationId"),
                            messageId=data.get("messageId"),
                            delta=_parse_delta(data.get("delta")),
                            usage=data.get("usage"),
                            raw=data,
                        )
        except httpx.TimeoutException as exc:
            raise ReyGridNetworkError(f"Timeout streaming chat: {exc}", cause=exc) from exc
        except httpx.TransportError as exc:
            raise ReyGridNetworkError(f"Network error streaming chat: {exc}", cause=exc) from exc

    async def async_stream_chat(
        self,
        agent_id: str,
        message: str,
        *,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tools: Optional[List[Tool]] = None,
        results: Optional[List[dict]] = None,
    ) -> AsyncIterator[ChatDeltaEvent]:
        """Stream a chat response via SSE (async generator)."""
        body = self._chat_params(message, conversation_id=conversation_id, user_id=user_id, stream=True, tools=tools, results=results)
        url = self._build_url(f"/agents/{_esc(agent_id)}/chat")

        try:
            async with self._async_client.stream("POST", url, json=body) as res:
                self._check_response(res)
                async for event in parse_sse_stream(res):
                    yield event
        except httpx.TimeoutException as exc:
            raise ReyGridNetworkError(f"Timeout streaming chat: {exc}", cause=exc) from exc
        except httpx.TransportError as exc:
            raise ReyGridNetworkError(f"Network error streaming chat: {exc}", cause=exc) from exc

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    def list_conversations(
        self,
        agent_id: str,
        page: int = 1,
        size: int = 20,
    ) -> ConversationsResponse:
        """List conversations belonging to an agent (sync)."""
        params = {"page": page, "size": min(size, 100)}
        res = self._request_sync("GET", f"/agents/{_esc(agent_id)}/conversations", params=params)
        data = res.json()
        return _parse_dataclass(ConversationsResponse, data)

    async def async_list_conversations(
        self,
        agent_id: str,
        page: int = 1,
        size: int = 20,
    ) -> ConversationsResponse:
        """List conversations (async)."""
        params = {"page": page, "size": min(size, 100)}
        res = await self._request_async("GET", f"/agents/{_esc(agent_id)}/conversations", params=params)
        data = res.json()
        return _parse_dataclass(ConversationsResponse, data)

    def paginate_conversations(self, agent_id: str, size: int = 20) -> Paginator:
        """Paginate through all of an agent's conversations (sync/async iterator)."""
        def _fetcher(p: int, s: int) -> PaginatedResult:
            resp = self.list_conversations(agent_id, page=p, size=s)
            return PaginatedResult(data=resp.conversations, pagination=resp.pagination)

        return Paginator(_fetcher, size)

    def async_paginate_conversations(self, agent_id: str, size: int = 20) -> Paginator:
        """Paginate through all conversations (async iterator)."""

        async def _fetcher(p: int, s: int) -> PaginatedResult:
            resp = await self.async_list_conversations(agent_id, page=p, size=s)
            return PaginatedResult(data=resp.conversations, pagination=resp.pagination)

        return Paginator(_fetcher, size)

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def list_messages(
        self,
        agent_id: str,
        conversation_ref: str,
        page: int = 1,
        size: int = 20,
    ) -> MessagesResponse:
        """List messages (sync). ``conversation_ref`` can be a conversationId or userId."""
        params = {"page": page, "size": min(size, 100)}
        res = self._request_sync(
            "GET",
            f"/agents/{_esc(agent_id)}/conversations/{_esc(conversation_ref)}/messages",
            params=params,
        )
        data = res.json()
        return _parse_dataclass(MessagesResponse, data)

    async def async_list_messages(
        self,
        agent_id: str,
        conversation_ref: str,
        page: int = 1,
        size: int = 20,
    ) -> MessagesResponse:
        """List messages (async)."""
        params = {"page": page, "size": min(size, 100)}
        res = await self._request_async(
            "GET",
            f"/agents/{_esc(agent_id)}/conversations/{_esc(conversation_ref)}/messages",
            params=params,
        )
        data = res.json()
        return _parse_dataclass(MessagesResponse, data)

    def paginate_messages(self, agent_id: str, conversation_ref: str, size: int = 20) -> Paginator:
        """Paginate through all messages of a conversation (sync/async iterator)."""
        def _fetcher(p: int, s: int) -> PaginatedResult:
            resp = self.list_messages(agent_id, conversation_ref, page=p, size=s)
            return PaginatedResult(data=resp.messages, pagination=resp.pagination)

        return Paginator(_fetcher, size)

    def async_paginate_messages(self, agent_id: str, conversation_ref: str, size: int = 20) -> Paginator:
        """Paginate through all messages (async iterator)."""

        async def _fetcher(p: int, s: int) -> PaginatedResult:
            resp = await self.async_list_messages(agent_id, conversation_ref, page=p, size=s)
            return PaginatedResult(data=resp.messages, pagination=resp.pagination)

        return Paginator(_fetcher, size)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_conversation(self, agent_id: str, conversation_ref: str) -> DeleteMessagesResponse:
        """Delete an entire conversation (sync)."""
        res = self._request_sync("DELETE", f"/agents/{_esc(agent_id)}/conversations/{_esc(conversation_ref)}")
        data = res.json()
        return _parse_dataclass(DeleteMessagesResponse, data)

    async def async_delete_conversation(self, agent_id: str, conversation_ref: str) -> DeleteMessagesResponse:
        """Delete an entire conversation (async)."""
        res = await self._request_async("DELETE", f"/agents/{_esc(agent_id)}/conversations/{_esc(conversation_ref)}")
        data = res.json()
        return _parse_dataclass(DeleteMessagesResponse, data)

    def delete_message(
        self,
        agent_id: str,
        conversation_ref: str,
        message_id: str,
        cascade: bool = False,
    ) -> DeleteMessagesResponse:
        """Delete a specific message (sync).

        Args:
            cascade: When True, also deletes the message immediately following.
        """
        params = {"cascade": "true"} if cascade else None
        res = self._request_sync(
            "DELETE",
            f"/agents/{_esc(agent_id)}/conversations/{_esc(conversation_ref)}/messages/{_esc(message_id)}",
            params=params,
        )
        data = res.json()
        return _parse_dataclass(DeleteMessagesResponse, data)

    async def async_delete_message(
        self,
        agent_id: str,
        conversation_ref: str,
        message_id: str,
        cascade: bool = False,
    ) -> DeleteMessagesResponse:
        """Delete a specific message (async)."""
        params = {"cascade": "true"} if cascade else None
        res = await self._request_async(
            "DELETE",
            f"/agents/{_esc(agent_id)}/conversations/{_esc(conversation_ref)}/messages/{_esc(message_id)}",
            params=params,
        )
        data = res.json()
        return _parse_dataclass(DeleteMessagesResponse, data)

    # ------------------------------------------------------------------
    # Tool call cancel
    # ------------------------------------------------------------------

    def cancel_tool_call(
        self,
        agent_id: str,
        conversation_ref: str,
        tool_call_id: str,
    ) -> CancelToolResponse:
        """Cancel an in-flight tool call (sync)."""
        res = self._request_sync(
            "POST",
            f"/agents/{_esc(agent_id)}/conversations/{_esc(conversation_ref)}/tool/cancel/{_esc(tool_call_id)}",
        )
        data = res.json()
        return _parse_dataclass(CancelToolResponse, data)

    async def async_cancel_tool_call(
        self,
        agent_id: str,
        conversation_ref: str,
        tool_call_id: str,
    ) -> CancelToolResponse:
        """Cancel an in-flight tool call (async)."""
        res = await self._request_async(
            "POST",
            f"/agents/{_esc(agent_id)}/conversations/{_esc(conversation_ref)}/tool/cancel/{_esc(tool_call_id)}",
        )
        data = res.json()
        return _parse_dataclass(CancelToolResponse, data)

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    def list_agents(self) -> AgentsResponse:
        """List the agents this API key can use (sync)."""
        return _parse_dataclass(AgentsResponse, self._request_sync("GET", "/agents").json())

    async def async_list_agents(self) -> AgentsResponse:
        """List the agents this API key can use (async)."""
        res = await self._request_async("GET", "/agents")
        return _parse_dataclass(AgentsResponse, res.json())

    def get_agent(self, agent_id: str) -> AgentDetailResponse:
        """Get an agent with its source counts and storage usage (sync)."""
        res = self._request_sync("GET", f"/agents/{_esc(agent_id)}")
        return _parse_dataclass(AgentDetailResponse, res.json())

    async def async_get_agent(self, agent_id: str) -> AgentDetailResponse:
        """Get an agent (async)."""
        res = await self._request_async("GET", f"/agents/{_esc(agent_id)}")
        return _parse_dataclass(AgentDetailResponse, res.json())

    def update_agent(
        self,
        agent_id: str,
        *,
        name: Optional[str] = None,
        instructions: Optional[str] = None,
        model: Optional[str] = None,
    ) -> AgentResponse:
        """Update an agent's name, instructions or model (sync)."""
        body = _without_none(name=name, instructions=instructions, model=model)
        res = self._request_sync("PATCH", f"/agents/{_esc(agent_id)}", json=body)
        return _parse_dataclass(AgentResponse, res.json())

    async def async_update_agent(
        self,
        agent_id: str,
        *,
        name: Optional[str] = None,
        instructions: Optional[str] = None,
        model: Optional[str] = None,
    ) -> AgentResponse:
        """Update an agent (async)."""
        body = _without_none(name=name, instructions=instructions, model=model)
        res = await self._request_async("PATCH", f"/agents/{_esc(agent_id)}", json=body)
        return _parse_dataclass(AgentResponse, res.json())

    # ------------------------------------------------------------------
    # Knowledge sources
    # ------------------------------------------------------------------

    def list_sources(
        self,
        agent_id: str,
        *,
        type: Optional[SourceType] = None,
        search: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> SourcesResponse:
        """List an agent's knowledge sources, newest first (sync)."""
        params = _without_none(type=type, search=search, page=page, size=min(size, 100))
        res = self._request_sync("GET", f"/agents/{_esc(agent_id)}/sources", params=params)
        return _parse_dataclass(SourcesResponse, res.json())

    async def async_list_sources(
        self,
        agent_id: str,
        *,
        type: Optional[SourceType] = None,
        search: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> SourcesResponse:
        """List an agent's knowledge sources (async)."""
        params = _without_none(type=type, search=search, page=page, size=min(size, 100))
        res = await self._request_async("GET", f"/agents/{_esc(agent_id)}/sources", params=params)
        return _parse_dataclass(SourcesResponse, res.json())

    def paginate_sources(
        self,
        agent_id: str,
        *,
        type: Optional[SourceType] = None,
        search: Optional[str] = None,
        size: int = 20,
    ) -> Paginator:
        """Iterate over all of an agent's sources, page by page (sync)."""

        def _fetcher(p: int, s: int) -> PaginatedResult:
            resp = self.list_sources(agent_id, type=type, search=search, page=p, size=s)
            return PaginatedResult(data=resp.sources, pagination=resp.pagination)

        return Paginator(_fetcher, size)

    def async_paginate_sources(
        self,
        agent_id: str,
        *,
        type: Optional[SourceType] = None,
        search: Optional[str] = None,
        size: int = 20,
    ) -> Paginator:
        """Iterate over all of an agent's sources (async)."""

        async def _fetcher(p: int, s: int) -> PaginatedResult:
            resp = await self.async_list_sources(agent_id, type=type, search=search, page=p, size=s)
            return PaginatedResult(data=resp.sources, pagination=resp.pagination)

        return Paginator(_fetcher, size)

    def add_text_source(self, agent_id: str, title: str, content: str) -> SourceCreatedResponse:
        """Add a titled piece of text (sync)."""
        res = self._request_sync(
            "POST", f"/agents/{_esc(agent_id)}/sources/text", json={"title": title, "content": content}
        )
        return _parse_dataclass(SourceCreatedResponse, res.json())

    async def async_add_text_source(self, agent_id: str, title: str, content: str) -> SourceCreatedResponse:
        """Add a titled piece of text (async)."""
        res = await self._request_async(
            "POST", f"/agents/{_esc(agent_id)}/sources/text", json={"title": title, "content": content}
        )
        return _parse_dataclass(SourceCreatedResponse, res.json())

    def add_qa_source(self, agent_id: str, question: str, answer: str) -> SourceCreatedResponse:
        """Add a question and its exact answer (sync)."""
        res = self._request_sync(
            "POST", f"/agents/{_esc(agent_id)}/sources/qa", json={"question": question, "answer": answer}
        )
        return _parse_dataclass(SourceCreatedResponse, res.json())

    async def async_add_qa_source(self, agent_id: str, question: str, answer: str) -> SourceCreatedResponse:
        """Add a question and its exact answer (async)."""
        res = await self._request_async(
            "POST", f"/agents/{_esc(agent_id)}/sources/qa", json={"question": question, "answer": answer}
        )
        return _parse_dataclass(SourceCreatedResponse, res.json())

    def upload_file(
        self,
        agent_id: str,
        file: Union[str, "os.PathLike[str]", bytes, BinaryIO],
        filename: Optional[str] = None,
        *,
        content_type: Optional[str] = None,
        timeout: float = LONG_TIMEOUT,
    ) -> SourceCreatedResponse:
        """Upload a PDF, DOC, DOCX or TXT file (sync).

        ``file`` is a path, raw bytes or an open binary file.
        """
        with _file_part(file, filename, content_type) as part:
            res = self._request_sync(
                "POST", f"/agents/{_esc(agent_id)}/sources/files", files={"file": part}, timeout=timeout
            )
        return _parse_dataclass(SourceCreatedResponse, res.json())

    async def async_upload_file(
        self,
        agent_id: str,
        file: Union[str, "os.PathLike[str]", bytes, BinaryIO],
        filename: Optional[str] = None,
        *,
        content_type: Optional[str] = None,
        timeout: float = LONG_TIMEOUT,
    ) -> SourceCreatedResponse:
        """Upload a file (async)."""
        with _file_part(file, filename, content_type) as part:
            res = await self._request_async(
                "POST", f"/agents/{_esc(agent_id)}/sources/files", files={"file": part}, timeout=timeout
            )
        return _parse_dataclass(SourceCreatedResponse, res.json())

    def crawl_website(self, agent_id: str, url: str, *, timeout: float = LONG_TIMEOUT) -> CrawlResponse:
        """Crawl a website and index its pages. Returns when the crawl is done (sync)."""
        res = self._request_sync(
            "POST", f"/agents/{_esc(agent_id)}/sources/website", json={"url": url}, timeout=timeout
        )
        return _parse_dataclass(CrawlResponse, res.json())

    async def async_crawl_website(self, agent_id: str, url: str, *, timeout: float = LONG_TIMEOUT) -> CrawlResponse:
        """Crawl a website (async)."""
        res = await self._request_async(
            "POST", f"/agents/{_esc(agent_id)}/sources/website", json={"url": url}, timeout=timeout
        )
        return _parse_dataclass(CrawlResponse, res.json())

    def delete_source(self, agent_id: str, source_id: str) -> DeleteSourceResponse:
        """Delete a source and everything indexed from it (sync)."""
        res = self._request_sync("DELETE", f"/agents/{_esc(agent_id)}/sources/{_esc(source_id)}")
        return _parse_dataclass(DeleteSourceResponse, res.json())

    async def async_delete_source(self, agent_id: str, source_id: str) -> DeleteSourceResponse:
        """Delete a source (async)."""
        res = await self._request_async("DELETE", f"/agents/{_esc(agent_id)}/sources/{_esc(source_id)}")
        return _parse_dataclass(DeleteSourceResponse, res.json())

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, agent_id: str, query: str, *, limit: int = 5) -> SearchResponse:
        """The knowledge passages closest to ``query``, without generating an answer (sync)."""
        res = self._request_sync(
            "POST", f"/agents/{_esc(agent_id)}/search", json={"query": query, "limit": limit}
        )
        return _parse_dataclass(SearchResponse, res.json())

    async def async_search(self, agent_id: str, query: str, *, limit: int = 5) -> SearchResponse:
        """Search an agent's knowledge (async)."""
        res = await self._request_async(
            "POST", f"/agents/{_esc(agent_id)}/search", json={"query": query, "limit": limit}
        )
        return _parse_dataclass(SearchResponse, res.json())

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    def rate_message(
        self,
        agent_id: str,
        conversation_ref: str,
        message_id: str,
        rating: FeedbackRating,
        comment: Optional[str] = None,
    ) -> FeedbackResponse:
        """Rate an assistant reply ``"up"`` or ``"down"`` (sync). Replaces any previous rating."""
        res = self._request_sync(
            "POST",
            f"/agents/{_esc(agent_id)}/conversations/{_esc(conversation_ref)}/messages/{_esc(message_id)}/feedback",
            json=_without_none(rating=rating, comment=comment),
        )
        return _parse_dataclass(FeedbackResponse, res.json())

    async def async_rate_message(
        self,
        agent_id: str,
        conversation_ref: str,
        message_id: str,
        rating: FeedbackRating,
        comment: Optional[str] = None,
    ) -> FeedbackResponse:
        """Rate an assistant reply (async)."""
        res = await self._request_async(
            "POST",
            f"/agents/{_esc(agent_id)}/conversations/{_esc(conversation_ref)}/messages/{_esc(message_id)}/feedback",
            json=_without_none(rating=rating, comment=comment),
        )
        return _parse_dataclass(FeedbackResponse, res.json())

    # ------------------------------------------------------------------
    # Models & usage
    # ------------------------------------------------------------------

    def list_models(self) -> ModelsResponse:
        """Every model, its price per message and whether your plan can use it (sync)."""
        return _parse_dataclass(ModelsResponse, self._request_sync("GET", "/models").json())

    async def async_list_models(self) -> ModelsResponse:
        """List models (async)."""
        res = await self._request_async("GET", "/models")
        return _parse_dataclass(ModelsResponse, res.json())

    def get_usage_report(self, days: int = 30) -> UsageReport:
        """Credit balance and API usage over the last ``days`` days, 1-90 (sync)."""
        res = self._request_sync("GET", "/usage", params={"days": days})
        return _parse_usage(res.json())

    async def async_get_usage_report(self, days: int = 30) -> UsageReport:
        """Credit balance and API usage (async)."""
        res = await self._request_async("GET", "/usage", params={"days": days})
        return _parse_usage(res.json())


def _without_none(**values: Any) -> Dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def _parse_usage(data: Dict[str, Any]) -> UsageReport:
    # "from" is a Python keyword: exposed as ``period.from_``.
    period = data.get("period")
    if isinstance(period, dict) and "from" in period:
        data = {**data, "period": {**{k: v for k, v in period.items() if k != "from"}, "from_": period["from"]}}
    return _parse_dataclass(UsageReport, data)


_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@contextmanager
def _file_part(
    file: Union[str, "os.PathLike[str]", bytes, BinaryIO],
    filename: Optional[str],
    content_type: Optional[str],
):
    """A ``(filename, file, content_type)`` tuple for httpx; opens paths for the upload."""
    opened = None
    if isinstance(file, (str, os.PathLike)):
        path = os.fspath(file)
        filename = filename or os.path.basename(path)
        opened = open(path, "rb")
        content = opened
    else:
        content = file
        filename = filename or os.path.basename(getattr(file, "name", "") or "") or None
    if not filename:
        if opened:
            opened.close()
        raise ValueError("filename is required when uploading bytes or a stream")

    ext = os.path.splitext(filename)[1].lower()
    try:
        yield (filename, content, content_type or _CONTENT_TYPES.get(ext, "application/octet-stream"))
    finally:
        if opened:
            opened.close()


def _esc(s: str) -> str:
    """URL-encode a path segment."""
    import urllib.parse
    return urllib.parse.quote(s, safe="")