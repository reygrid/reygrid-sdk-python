"""SSE (Server-Sent Events) stream parser for ReyGrid's chat streaming.

ReyGrid's streaming API emits data-only SSE messages using the ``data:` field
with no explicit event field.
"""

from __future__ import annotations

import json
from typing import AsyncIterator, Dict, List

from .exceptions import ReyGridStreamError
from .models import ChatDelta, ChatDeltaEvent, ChatDeltaReply


def _parse_delta(raw: Any) -> Optional[ChatDelta]:
    """Parse the nested ``delta`` payload of an SSE frame."""
    if not isinstance(raw, dict):
        return None
    reply_raw = raw.get("reply")
    return ChatDelta(
        reply=ChatDeltaReply(**reply_raw) if isinstance(reply_raw, dict) else None,
        finish_reason=raw.get("finish_reason"),
        tool_calls=raw.get("tool_calls"),
    )


async def parse_sse_stream(body: Any) -> AsyncIterator[ChatDeltaEvent]:
    """Parse an SSE ``Response`` body as async generator of ``ChatDeltaEvent``.

    Usage::

        async for event in parse_sse_stream(response):
            print(event.content or "")

    """
    buf = ""
    # Fast path: body is a streaming body
    async for chunk in _iter_chunks(body):
        buf += chunk
        done, events = _extract_events(buf)
        buf = done
        for raw in events:
            raw = raw.strip()
            if not raw:
                continue
            try:
                data: dict = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ReyGridStreamError(
                    f"Failed to parse SSE data frame: {raw[:120]}",
                ) from exc
            yield ChatDeltaEvent(
                success=data.get("success"),
                conversationId=data.get("conversationId"),
                messageId=data.get("messageId"),
                delta=_parse_delta(data.get("delta")),
                usage=data.get("usage"),
                raw=data,
            )


async def _iter_chunks(body: Any):
    """Yield text chunks from a streaming HTTP response body."""
    # httpx/httpx-sse
    if hasattr(body, "aiter_text"):
        async for chunk in body.aiter_text():
            yield chunk
    # raw aiter_bytes or iter_bytes
    elif hasattr(body, "aiter_bytes"):
        async for chunk in body.aiter_bytes():
            yield chunk.decode("utf-8", errors="replace")
    # requests + Response.iter_lines (sync — unlikely)
    elif hasattr(body, "iter_lines"):
        for line in body.iter_lines():
            if line:
                yield line + "\n"
        yield ""
    else:
        # Try the generic aiter protocol
        async for chunk in body.__aiter__():  # type: ignore[union-attr]
            if isinstance(chunk, bytes):
                yield chunk.decode("utf-8", errors="replace")
            else:
                yield chunk


def _extract_events(chunk: str) -> (str, List[str]):  # noqa: UP037
    """Split raw SSE text into completed data: frames.

    Returns ``(remainder, [completed_events])``.
    """
    lines = chunk.split("\n")
    complete: List[str] = []
    current: List[str] = []
    remainder = ""

    for line in lines:
        if line.startswith("data:"):
            current.append(line[5:].lstrip())
        elif line == "" and current:
            complete.append("\n".join(current))
            current = []
        elif line.startswith(":"):
            continue  # SSE comment

    if current:
        remainder = "\n".join(current)

    return remainder, complete