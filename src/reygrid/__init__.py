"""
ReyGrid — powerful, typed Python client for the ReyGrid API.

Feed:  https://reygrid.com/api/v1

Usage::

    from reygrid import ReyGrid

    client = ReyGrid(api_key="your-key")
    reply = client.chat("agent-1", "Hello!")
    print(reply.output.reply.content)
"""

from __future__ import annotations

from .client import DEFAULT_BASE_URL, PaginatedResult, Paginator, ReyGrid, ReyGridConfig
from .exceptions import (
    ReyGridApiError,
    ReyGridAuthError,
    ReyGridConflictError,
    ReyGridError,
    ReyGridNetworkError,
    ReyGridNotFoundError,
    ReyGridStreamError,
    ReyGridValidationError,
)
from .models import (
    ApiError,
    AuthErrorResponse,
    CancelToolResponse,
    ChatDelta,
    ChatDeltaEvent,
    ChatDeltaReply,
    ChatOutput,
    ChatRequest,
    ChatResponse,
    ChatUsage,
    Conversation,
    ConversationsPagination,
    ConversationsResponse,
    DeleteMessagesResponse,
    DeletedMessages,
    ErrorResponse,
    FunctionDefinition,
    Message,
    MessagesPagination,
    MessagesResponse,
    MessageToolCall,
    Pagination,
    PingMetadata,
    PingResponse,
    Reply,
    ServiceStatus,
    Tool,
    ToolCallFunction,
    ToolResult,
    Usage,
    ValidateResponse,
)

__version__ = "1.0.2"

__all__ = [
    "ReyGrid",
    "ReyGridConfig",
    "ReyGridError",
    "ReyGridApiError",
    "ReyGridAuthError",
    "ReyGridValidationError",
    "ReyGridNotFoundError",
    "ReyGridConflictError",
    "ReyGridNetworkError",
    "ReyGridStreamError",
    "Paginator",
    "PaginatedResult",
    "DEFAULT_BASE_URL",
    "PingResponse",
    "PingMetadata",
    "ServiceStatus",
    "ValidateResponse",
    "Usage",
    "AuthErrorResponse",
    "ErrorResponse",
    "ApiError",
    "FunctionDefinition",
    "Tool",
    "ToolResult",
    "ChatRequest",
    "Reply",
    "ChatOutput",
    "ChatUsage",
    "ChatResponse",
    "Pagination",
    "Conversation",
    "ConversationsPagination",
    "ConversationsResponse",
    "ToolCallFunction",
    "MessageToolCall",
    "Message",
    "MessagesPagination",
    "MessagesResponse",
    "DeletedMessages",
    "DeleteMessagesResponse",
    "CancelToolResponse",
    "ChatDelta",
    "ChatDeltaEvent",
    "ChatDeltaReply",
]