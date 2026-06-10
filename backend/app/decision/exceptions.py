"""Safe P07 decision errors."""


class DecisionError(RuntimeError):
    """Base decision service error."""


class DecisionDisabledError(DecisionError):
    """Raised when operator-triggered evaluation is disabled."""


class DecisionSignalNotFoundError(DecisionError):
    """Raised when a requested persisted signal does not exist."""


class DecisionSignalIneligibleError(DecisionError):
    """Raised when a persisted signal is not a P05 candidate."""


class DecisionConfigError(DecisionError):
    """Raised for unsupported or incomplete decision configuration."""


class DecisionAdapterError(DecisionError):
    """Adapter failure with a stable non-sensitive error code."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code
