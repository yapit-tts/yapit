"""Custom exceptions for the gateway API."""


class ValidationError(ValueError):
    """Raised for invalid request parameters - maps to HTTP 400."""

    pass


class ResourceNotFoundError(ValueError):
    """Raised when a required resource is not found - maps to HTTP 404."""

    pass


class InsufficientCreditsError(ValueError):
    """Raised when user has insufficient credits - maps to HTTP 402."""

    pass
