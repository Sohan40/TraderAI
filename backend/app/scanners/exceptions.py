"""Scanner safe errors."""


class ScannerError(Exception):
    """Base scanner error."""


class ScannerDisabledError(ScannerError):
    """Raised when scanner execution is disabled."""


class ScannerConfigError(ScannerError):
    """Raised for unsafe or unsupported scanner configuration."""


class ScannerInputError(ScannerError):
    """Raised for unsupported scanner input."""


class ScannerAutoLoopDisabledError(ScannerError):
    """Raised when the scanner auto-loop is disabled."""


class ScannerAutoLoopRunningError(ScannerError):
    """Raised when attempting to start an already running auto-loop."""


class ScannerAutoLoopBusyError(ScannerError):
    """Raised when an auto-loop scan is already in progress."""
