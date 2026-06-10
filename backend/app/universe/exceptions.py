"""Universe-selection domain errors."""


class UniverseSelectionError(RuntimeError):
    """Base universe-selection error."""


class UniverseSelectionDisabledError(UniverseSelectionError):
    """Raised when selection is disabled."""


class UniverseInputError(UniverseSelectionError):
    """Raised for invalid selection input."""


class SelectedUniverseMissingError(UniverseSelectionError):
    """Raised when scanner integration asks for a missing selection."""
