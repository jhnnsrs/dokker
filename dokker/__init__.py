""" Dokker

Dokker is a tool for building and managing docker-compose projects.
It is designed to tightly integrate in python projects and provide
sensible defaults for common docker-compose workflows.
"""

from .deployment import Deployment, HealthCheck, Logger
from .builders import (
    mirror,
    testing,
    monitoring,
    local,
)
from .project import Project
from .projects.local import LocalProject
from .log_watcher import LogRoll, LogWatcher
from .command import CommandError
from .cli import CLI, CLIError
from .errors import (
    DokkerError,
    HealthCheckError,
    LabelNotFoundError,
    NotInitializedError,
    NotInspectableError,
    NotInspectedError,
    PortNotFoundError,
    ServiceNotFoundError,
    TearDownError,
)

__all__ = [
    "Deployment",
    "HealthCheck",
    "Logger",
    "mirror",
    "testing",
    "monitoring",
    "local",
    "Project",
    "LocalProject",
    "LogRoll",
    "LogWatcher",
    "CLI",
    "CLIError",
    "CommandError",
    "DokkerError",
    "HealthCheckError",
    "LabelNotFoundError",
    "NotInitializedError",
    "NotInspectableError",
    "NotInspectedError",
    "PortNotFoundError",
    "ServiceNotFoundError",
    "TearDownError",
]
