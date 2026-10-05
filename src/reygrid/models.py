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
    feedback: Optional["Feedback"] = None


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


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

SourceType = Literal["text", "qa", "file", "website"]


@dataclass
class Agent:
    id: str
    name: str
    model: str
    instructions: str
    usage: float = 0
    """Credits spent by the agent so far."""
    createdAt: Optional[str] = None


@dataclass
class AgentStorage:
    used: int
    """Characters of text plus bytes of files."""
    limit: int


@dataclass
class AgentDetail(Agent):
    sources: Dict[str, int] = field(default_factory=dict)
    """Number of sources per type: text, qa, file, website."""
    storage: Optional[AgentStorage] = None


@dataclass
class AgentsResponse:
    success: bool
    agents: List[Agent] = field(default_factory=list)


@dataclass
class AgentResponse:
    success: bool
    agent: Optional[Agent] = None


@dataclass
class AgentDetailResponse:
    success: bool
    agent: Optional[AgentDetail] = None


# ---------------------------------------------------------------------------
# Knowledge sources
# ---------------------------------------------------------------------------

@dataclass
class Source:
    id: str
    type: SourceType
    title: str
    """The title, question, file name or page URL."""
    content: Optional[str] = None
    """Text or answer. Only for text and qa sources."""
    size: Optional[int] = None
    """File size in bytes. Only for file sources."""
    createdAt: Optional[str] = None


@dataclass
class SourcesPagination(Pagination):
    totalSources: int = 0


@dataclass
class SourcesResponse:
    success: bool
    sources: List[Source] = field(default_factory=list)
    pagination: Optional[SourcesPagination] = None


@dataclass
class CreatedSource:
    id: str
    type: SourceType
    title: str
    size: Optional[int] = None


@dataclass
class SourceCreatedResponse:
    success: bool
    source: Optional[CreatedSource] = None


@dataclass
class CrawledPage:
    id: str
    path: str


@dataclass
class CrawlResponse:
    success: bool
    pagesCrawled: int = 0
    pages: List[CrawledPage] = field(default_factory=list)


@dataclass
class DeleteSourceResponse:
    success: bool
    deleted: bool = False


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@dataclass
class SearchSource:
    id: str
    type: SourceType
    title: str


@dataclass
class SearchResult:
    score: float
    """Similarity between 0 and 1. Higher is closer."""
    content: str
    source: Optional[SearchSource] = None


@dataclass
class SearchResponse:
    success: bool
    results: List[SearchResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

FeedbackRating = Literal["up", "down"]


@dataclass
class Feedback:
    rating: FeedbackRating
    comment: Optional[str] = None
    createdAt: Optional[str] = None


@dataclass
class FeedbackResponse:
    success: bool
    feedback: Optional[Feedback] = None


# ---------------------------------------------------------------------------
# Models & usage
# ---------------------------------------------------------------------------

@dataclass
class Model:
    id: str
    name: str
    provider: str
    pricing: float
    """Credits per message."""
    available: bool
    """Whether your plan can use the model."""


@dataclass
class ModelsResponse:
    success: bool
    models: List[Model] = field(default_factory=list)


@dataclass
class UsageBalance:
    credits: float
    plan: str
    renewsAt: Optional[str] = None


@dataclass
class UsagePeriod:
    days: int
    to: str
    from_: Optional[str] = None


@dataclass
class UsageTotals:
    requests: int = 0
    failed: int = 0
    credits: float = 0


@dataclass
class UsageDay(UsageTotals):
    date: str = ""


@dataclass
class UsageAgent:
    id: str
    requests: int
    credits: float
    name: Optional[str] = None
    """None when the agent was deleted."""


@dataclass
class UsageReport:
    success: bool
    balance: Optional[UsageBalance] = None
    period: Optional[UsagePeriod] = None
    totals: Optional[UsageTotals] = None
    daily: List[UsageDay] = field(default_factory=list)
    agents: List[UsageAgent] = field(default_factory=list)


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