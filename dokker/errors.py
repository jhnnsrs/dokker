class DokkerError(Exception):
    """Base class for all Dokker errors."""


class NotInitializedError(DokkerError):
    """Raised when Dokker is not initialized."""


class NotInspectedError(DokkerError):
    """Raised when an object is not inspected."""


class NotInspectableError(DokkerError):
    """Raised when an object is not inspectable."""


class HealthCheckError(DokkerError):
    """Raised when a health check fails."""


class TearDownError(DokkerError):
    """Raised when tearing a deployment down fails or times out.

    This is surfaced when the on-exit teardown (``stop``/``down``) could not
    complete cleanly, for example because ``docker compose`` did not finish
    within ``teardown_timeout``. It is only raised when the context is exiting
    normally; if another exception is already propagating, the teardown failure
    is logged instead so it does not mask the original error.
    """


class ServiceNotFoundError(DokkerError):
    """Raised when a requested service cannot be found in the compose spec."""


class PortNotFoundError(DokkerError):
    """Raised when a requested port cannot be found on a service."""


class LabelNotFoundError(DokkerError):
    """Raised when a requested label cannot be found on a service."""
