""" Dokker

Dokker is a tool for building and managing docker-compose projects.
It is designed to tightly integrate in python projects and provide
sensible defaults for common docker-compose workflows.
"""

from .deployment import (
    Deployment,
    HealthCheck,
    Logger,
    PolicyName,
    TeardownPolicy,
    TEARDOWN_POLICIES,
)
from .builders import (
    mirror,
    testing,
    monitoring,
    local,
)
from .checks import (
    BaseCheck,
    Check,
    CheckContext,
    CommandCheck,
    ContainerCheck,
    LogCheck,
    TcpCheck,
)
from .project import DownOptions, DownsItself, Project, PullOptions, PullsItself, StartsItself, StopsItself, UpOptions
from .projects.copy import CopyPathProject
from .projects.local import LocalProject
from .log_watcher import LogRoll, LogWatcher
from .loggers.print import PrintLogger
from .loggers.progress import ProgressLogger
from .loggers.void import VoidLogger
from .command import CommandError
from .ownership import areap_orphan_images, areap_stale, reap_orphan_images, reap_stale
from .cli import CLI, CLIError
from .compose_spec import ComposeSpec, ContainerStatus
from .errors import (
    DockerNotAvailableError,
    DokkerError,
    HealthCheckError,
    LabelNotFoundError,
    LogWatcherTimeoutError,
    NotInitializedError,
    NotInspectableError,
    NotInspectedError,
    PortNotFoundError,
    ServiceNotFoundError,
    TearDownError,
)
from .projects.errors import ProjectError

__all__ = [
    "Deployment",
    "HealthCheck",
    "Logger",
    "PolicyName",
    "TeardownPolicy",
    "TEARDOWN_POLICIES",
    "mirror",
    "testing",
    "monitoring",
    "local",
    "Project",
    "StartsItself",
    "StopsItself",
    "DownsItself",
    "PullsItself",
    "UpOptions",
    "DownOptions",
    "PullOptions",
    "LocalProject",
    "CopyPathProject",
    "LogRoll",
    "LogWatcher",
    "PrintLogger",
    "ProgressLogger",
    "VoidLogger",
    "CLI",
    "CLIError",
    "CommandError",
    "areap_orphan_images",
    "areap_stale",
    "reap_orphan_images",
    "reap_stale",
    "ComposeSpec",
    "ContainerStatus",
    # Readiness checks
    "Check",
    "CheckContext",
    "BaseCheck",
    "TcpCheck",
    "CommandCheck",
    "ContainerCheck",
    "LogCheck",
    # Errors
    "DockerNotAvailableError",
    "DokkerError",
    "HealthCheckError",
    "LabelNotFoundError",
    "LogWatcherTimeoutError",
    "NotInitializedError",
    "NotInspectableError",
    "NotInspectedError",
    "PortNotFoundError",
    "ProjectError",
    "ServiceNotFoundError",
    "TearDownError",
]
