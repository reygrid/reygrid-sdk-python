"""ReyGrid API — Python data models (typed dataclasses)."""

from __future__ import annotations

import dataclasses
import typing
from dataclasses import dataclass, field
from types import UnionType
from typing import Any, Dict, List, Literal, Optional


# ---------------------------------------------------------------------------
# Auth / health
# ---------------------------------------------------------------------------

@dataclass
class PingMetadata:
    uptime: Optional[int] = None
    timestamp: Optional[str] = None


ServiceStatus = Literal["UP", "DOWN"]


@dataclass
class PingResponse:
    success: bool
    status: ServiceStatus
    service: str
    version: str
    metadata: Optional[PingMetadata] = None


@dataclass
class Usage:
    total: int
    quotaLimit: int


@dataclass
class ValidateResponse:
    success: bool
    valid: bool
    usage: Usage


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

@dataclass
class AuthErrorResponse:
    error: str
    code: str


@dataclass
class ApiError:
    code: str
    message: str
    list: Optional[List[Dict[str, Any]]] = None


@dataclass
class ErrorResponse:
    success: bool
    error: ApiError
    output: Optional[Dict[str, Any]] = None
    usage: Optional["ChatUsage"] = None


# ---------------------------------------------------------------------------
# Chat / tools
# ---------------------------------------------------------------------------

@dataclass
class FunctionDefinition:
    name: str
    instructions: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    strict: Optional[bool] = None


@dataclass
class Tool:
    type: Literal["function"] = "function"
    function: Optional[FunctionDefinition] = None


@dataclass
class ToolResult:
    toolCallId: str
    output: str


@dataclass
class ChatRequest:
    message: str
    conversationId: Optional[str] = None
    userId: Optional[str] = None
    stream: bool = False
    tools: Optional[List[Tool]] = None
    results: Optional[List[ToolResult]] = None


@dataclass
class Reply:
    id: str
    content: str


@dataclass
class ChatOutput:
    reply: Reply
    finish_reason: str


@dataclass
class ChatUsage:
    credits: float


@dataclass
class ChatResponse:
    success: bool
    messageId: str
    output: ChatOutput
    usage: ChatUsage
    conversationId: Optional[str] = None
    userId: Optional[str] = None


# ---------------------------------------------------------------------------
# Conversations / messages
# ---------------------------------------------------------------------------

@dataclass
class Pagination:
    totalPages: int
    currentPage: int
    pagingCounter: int
    hasNextPage: bool


@dataclass
class Conversation:
    conversationId: Optional[str] = None
    userId: Optional[str] = None
    messagesCount: Optional[int] = None
    expiresAt: Optional[str] = None
    createdAt: Optional[str] = None


@dataclass
class ConversationsPagination(Pagination):
    totalConversations: int = 0


@dataclass
class ConversationsResponse:
    success: bool
    conversations: List[Conversation] = field(default_factory=list)
    pagination: Optional[ConversationsPagination] = None


@dataclass
class ToolCallFunction:
    name: str
    arguments: str


@dataclass
class MessageToolCall:
    id: str
    type: Literal["function"] = "function"
    function: Optional[ToolCallFunction] = None
    status: Optional[str] = None


@dataclass
class Message:
    id: str
    role: str
    createdAt: str
    content: Optional[str] = None
    tool_calls: Optional[List[MessageToolCall]] = None


@dataclass
class MessagesPagination(Pagination):
    totalMessages: int = 0


@dataclass
class MessagesResponse:
    success: bool
    messages: List[Message] = field(default_factory=list)
    pagination: Optional[MessagesPagination] = None
    userId: Optional[str] = None
    conversationId: Optional[str] = None


@dataclass
class DeletedMessages:
    count: int


@dataclass
class DeleteMessagesResponse:
    success: bool
    deletedMessages: Optional[DeletedMessages] = None


@dataclass
class CancelToolResponse:
    success: bool
    canceled: bool


# ---------------------------------------------------------------------------
# SSE event
# ---------------------------------------------------------------------------

@dataclass
class ChatDeltaReply:
    """The reply payload inside a streaming delta."""
    content: Optional[str] = None
    id: Optional[str] = None


@dataclass
class ChatDelta:
    """A single delta frame during a streaming chat."""
    reply: Optional[ChatDeltaReply] = None
    finish_reason: Optional[str] = None
    tool_calls: Optional[List[MessageToolCall]] = None


@dataclass
class ChatDeltaEvent:
    """A complete SSE frame received during streaming.

    Top-level wrapper received from the API.
    Access the text via ``event.delta.reply.content``.
    """

    success: Optional[bool] = None
    conversationId: Optional[str] = None
    messageId: Optional[str] = None
    delta: Optional[ChatDelta] = None
    usage: Optional[ChatUsage] = None
    raw: Optional[Dict[str, Any]] = None


def _parse_dataclass(cls, data: Optional[Dict[str, Any]]) -> Any:
    """Build a dataclass from raw API JSON, recursively parsing nested dataclasses."""
    if data is None:
        return None
    if not dataclasses.is_dataclass(cls) or not isinstance(data, dict):
        return data

    # Resolve string annotations (from __future__ import annotations) to real types
    try:
        hints = typing.get_type_hints(cls)
    except Exception:
        hints = {f.name: f.type for f in dataclasses.fields(cls)}

    kwargs: Dict[str, Any] = {}
    for field_def in dataclasses.fields(cls):
        name = field_def.name
        if name not in data:
            continue
        kwargs[name] = _coerce(hints.get(name), data[name])

    return cls(**kwargs)


def _coerce(annotation, value: Any) -> Any:
    """Coerce a raw JSON value to the annotated (possibly nested) type."""
    if annotation is None or value is None:
        return value

    origin = typing.get_origin(annotation)

    # list[T]
    if origin is list:
        args = typing.get_args(annotation)
        if isinstance(value, list):
            elem = args[0] if args else None
            return [_coerce(elem, v) for v in value]
        return value

    # Optional[X] / Union[X, None] — dig to first non-None type
    if origin in (typing.Union, UnionType):
        args = typing.get_args(annotation)
        for a in args:
            if a is type(None):
                continue
            return _coerce(a, value)
        return value

    # Nested dataclass
    if dataclasses.is_dataclass(annotation) and isinstance(value, dict):
        return _parse_dataclass(annotation, value)

    return value