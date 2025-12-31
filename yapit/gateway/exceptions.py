from typing import Any


class APIError(Exception):
    """Base exception for all API errors."""

    status_code: int = 500

    def __init__(self, message: str):
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for JSON response."""
        return {"detail": str(self)}


class ValidationError(APIError):
    """Raised for semantically invalid request parameters - maps to HTTP 422."""

    status_code = 422


class ResourceNotFoundError(APIError):
    """Raised when a required resource is not found - maps to HTTP 404."""

    status_code = 404

    def __init__(self, resource_type: str, resource_id: Any, *, message: str | None = None):
        super().__init__(message or f"{resource_type} {resource_id!r} not found")
        self.resource_type = resource_type
        self.resource_id = resource_id

    def to_dict(self) -> dict[str, Any]:
        return {"detail": str(self), "resource_type": self.resource_type, "resource_id": str(self.resource_id)}


class UsageLimitExceededError(APIError):
    """Raised when user exceeds their subscription usage limit - maps to HTTP 402."""

    status_code = 402

    def __init__(
        self,
        usage_type: str,
        limit: int,
        current: int,
        requested: int,
        *,
        message: str | None = None,
    ):
        remaining = max(0, limit - current)
        super().__init__(
            message
            or f"Usage limit exceeded for {usage_type}: limit {limit}, used {current}, requested {requested}, remaining {remaining}"
        )
        self.usage_type = usage_type
        self.limit = limit
        self.current = current
        self.requested = requested

    def to_dict(self) -> dict[str, Any]:
        return {
            "detail": str(self),
            "usage_type": self.usage_type,
            "limit": self.limit,
            "current": self.current,
            "requested": self.requested,
            "remaining": max(0, self.limit - self.current),
        }
