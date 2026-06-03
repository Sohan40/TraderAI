"""Scanner safe errors."""


class ScannerError(Exception):
    """Base scanner error."""


class ScannerDisabledError(ScannerError):
    """Raised when scanner execution is disabled."""


class ScannerConfigError(ScannerError):
    """Raised for unsafe or unsupported scanner configuration."""


class ScannerInputError(ScannerError):
    """Raised for unsupported scanner input."""
