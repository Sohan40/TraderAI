"""Paper engine safe errors."""


class PaperError(Exception):
    """Base paper engine error."""


class PaperConfigError(PaperError):
    """Raised for unsupported paper configuration."""


class PaperDisabledError(PaperError):
    """Raised when paper execution is disabled by configuration."""


class PaperModeDisabledError(PaperError):
    """Raised when the selected paper mode does not permit fills."""


class LiveModeNotImplementedError(PaperError):
    """Raised when LIVE is requested; P06 never supports live execution."""

