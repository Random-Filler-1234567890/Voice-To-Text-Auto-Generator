class NoProviderConfiguredError(Exception):
    """Raised when a pipeline stage has no usable provider (no API keys set)."""


class AllProvidersFailedError(Exception):
    """Raised when every configured provider in the fallback chain failed."""
