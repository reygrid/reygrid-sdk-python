"""ReyGrid API — exception hierarchy."""

from __future__ import annotations

from typing import Any, Dict, Optional


class ReyGridError(Exception):
    """Base error for all ReyGrid API failures."""

    def __init__(self, message: str, *, cause: Optional[BaseException] = None) -> None:
        super().__init__(message)
        self.cause = cause


class ReyGridApiError(ReyGridError):
    """Thrown when the API returns an error response (4xx / 5xx).

    Attributes:
        status_code: HTTP status code.
        code: Machine-readable error code (e.g. "AUTH_REQUIRED").
        details: Parsed API error payload when available.
    """

    def __init__(
        self,
        status_code: int,
        body: Optional[Dict[str, Any]] = None,
        *,
        message: Optional[str] = None,
        code: Optional[str] = None,
    ) -> None:
        if isinstance(body, dict):
            code = code or body.get("code")
            message = message or body.get("message")
        self.status_code = status_code
        self.code = code or "UNKNOWN"
        self.details = body
        super().__init__(message or f"HTTP {status_code} ({self.code})")


class ReyGridAuthError(ReyGridApiError):
    """Thrown when authentication fails (401)."""

    def __init__(self, body: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(401, body, code="AUTH_REQUIRED")


class ReyGridValidationError(ReyGridApiError):
    """Thrown when the request body is invalid (400)."""

    def __init__(self, body: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(400, body)


class ReyGridNotFoundError(ReyGridApiError):
    """Thrown when the resource is not found (404)."""

    def __init__(self, body: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(404, body)


class ReyGridConflictError(ReyGridApiError):
    """Thrown when a tool call cannot be canceled due to state (409)."""

    def __init__(self, body: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(409, body)


class ReyGridPermissionError(ReyGridApiError):
    """Thrown when the request isn't allowed (403): plan limit reached, model not
    on your plan, or an API key restricted to other agents or IP addresses."""

    def __init__(self, body: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(403, body)


class ReyGridRateLimitError(ReyGridApiError):
    """Thrown when you're rate limited or the key's quota is used up (429)."""

    def __init__(self, body: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(429, body)


class ReyGridNetworkError(ReyGridError):
    """Thrown on network-level failures (timeout, DNS, connection refused)."""


class ReyGridStreamError(ReyGridError):
    """Thrown when SSE parsing encounters a malformed event stream."""


def map_api_error(status: int, body: Any) -> ReyGridApiError:
    """Map an HTTP status code and parsed body to the correct error type."""
    # Most errors are {"success": false, "error": {"code", "message"}}; 401s are {"error", "code"}.
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        body = body["error"]
    elif isinstance(body, dict) and isinstance(body.get("error"), str):
        body = {"message": body["error"], **body}
    if status == 401:
        return ReyGridAuthError(body)
    if status == 400:
        return ReyGridValidationError(body)
    if status == 404:
        return ReyGridNotFoundError(body)
    if status == 409:
        return ReyGridConflictError(body)
    if status == 403:
        return ReyGridPermissionError(body)
    if status == 429:
        return ReyGridRateLimitError(body)
    return ReyGridApiError(status, body)