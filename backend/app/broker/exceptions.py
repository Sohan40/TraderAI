"""Broker authentication exceptions."""


class KiteAuthError(Exception):
    """Base exception for Kite auth failures."""


class KiteAuthDisabledError(KiteAuthError):
    """Raised when Kite auth is disabled by configuration."""


class KiteConfigError(KiteAuthError):
    """Raised when required Kite auth configuration is missing."""


class KiteStateError(KiteAuthError):
    """Raised when callback state is missing, invalid, or expired."""


class KiteSessionError(KiteAuthError):
    """Raised when a persisted Kite session cannot be used safely."""
