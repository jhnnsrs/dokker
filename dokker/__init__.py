"""Dokker

Dokker is a tool for building and managing docker-compose projects.
It is designed to tightly integrate in python projects and provide
sensible defaults for common docker-compose workflows.
"""

from .builders import (
    local,
    mirror,
    monitoring,
    testing,
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
from .cli import CLI, CLIError
from .command import CommandError
from .compose_spec import ComposeSpec, ContainerStatus
from .deployment import (
    TEARDOWN_POLICIES,
    Deployment,
    HealthCheck,
    Logger,
    PolicyName,
    TeardownPolicy,
)
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
from .log_watcher import LogRoll, LogWatcher
from .loggers.print import PrintLogger
from .loggers.progress import ProgressLogger
from .loggers.void import VoidLogger
from .ownership import areap_orphan_images, areap_stale, reap_orphan_images, reap_stale
from .project import (
    DownOptions,
    DownsItself,
    Project,
    PullOptions,
    PullsItself,
    StartsItself,
    StopsItself,
    UpOptions,
)
from .projects.copy import CopyPathProject
from .projects.errors import ProjectError
from .projects.local import LocalProject

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
