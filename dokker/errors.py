class DokkerError(Exception):
    """Base class for all Dokker errors."""


class NotInitializedError(DokkerError):
    """Raised when Dokker is not initialized."""


class NotInspectedError(DokkerError):
    """Raised when an object is not inspected."""


class NotInspectableError(DokkerError):
    """Raised when an object is not inspectable."""
