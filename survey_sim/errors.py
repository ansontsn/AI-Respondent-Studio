class AppError(Exception):
    """An understandable error safe to display without exposing API bodies."""


class ProviderError(AppError):
    """kind: "api" = service-wide (key, quota, model, connection; pauses a batch),
    "format" = repairable output, "truncated" = output hit the token limit (retrying
    with the same limit cannot help), "content" = this request only."""
    def __init__(self, message, *, kind="api"):
        super().__init__(message)
        self.kind = kind


class AutomationError(AppError):
    def __init__(self, message, *, retryable=False):
        super().__init__(message)
        self.retryable = retryable
