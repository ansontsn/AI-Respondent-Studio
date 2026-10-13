class AppError(Exception):
    """An understandable error safe to display without exposing API bodies."""


class ProviderError(AppError):
    pass


class AutomationError(AppError):
    pass
