from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import Annotated

from dokker.errors import LabelNotFoundError, PortNotFoundError, ServiceNotFoundError


class ServicePlacement(BaseModel):
    """Service placement constraints."""

    constraints: Optional[List[str]] = None


class ResourcesLimits(BaseModel):
    """Resource limits for a service."""

    cpus: Optional[float] = None
    memory: Optional[int] = None


class ResourcesReservation(BaseModel):
    """Resource reservations for a service."""

    cpus: Union[float, int, None] = None
    memory: Optional[int] = None


class ServiceResources(BaseModel):
    """Resource configuration for a service."""

    limits: Optional[ResourcesLimits] = None
    reservations: Optional[ResourcesReservation] = None


class ServiceDeployConfig(BaseModel):
    """Service deployment configuration."""

    labels: Optional[Dict[str, str]] = None
    resources: Optional[ServiceResources] = None
    placement: Optional[ServicePlacement] = None
    replicas: Optional[int] = None


class DependencyCondition(BaseModel):
    """Dependency condition for a service."""

    condition: Optional[str] = None


class ComposeServiceBuild(BaseModel):
    """Build configuration for a service."""

    context: Optional[Path] = None
    dockerfile: Optional[Path] = None
    args: Optional[Dict[str, Any]] = None
    labels: Optional[Dict[str, Any]] = None


class ComposeServicePort(BaseModel):
    """Port configuration for a service."""

    mode: Optional[str] = None
    protocol: Optional[str] = None
    published: Optional[int] = None
    target: Optional[int] = None


class ComposeServiceVolume(BaseModel):
    """Volume configuration for a service."""

    bind: Optional[dict[str, Any]] = None
    source: Optional[str] = None
    target: Optional[str] = None
    type: Optional[str] = None


class ComposeConfigService(BaseModel):
    """Service configuration for a Docker Compose file."""

    deploy: Optional[ServiceDeployConfig] = None
    blkio_config: Optional[Any] = None
    cpu_count: Optional[float] = None
    cpu_percent: Optional[float] = None
    cpu_shares: Optional[int] = None
    cpuset: Optional[str] = None
    build: Optional[ComposeServiceBuild] = None
    cap_add: Annotated[Optional[List[str]], Field(default_factory=list)]
    cap_drop: Annotated[Optional[List[str]], Field(default_factory=list)]
    cgroup_parent: Optional[str] = None
    command: Optional[List[str]] = None
    configs: Any = None
    container_name: Optional[str] = None
    depends_on: Annotated[Dict[str, DependencyCondition], Field(default_factory=dict)]
    device_cgroup_rules: Annotated[List[str], Field(default_factory=list)]
    devices: Any = None
    environment: Optional[Dict[str, Optional[str]]] = None
    entrypoint: Optional[List[str]] = None
    image: Optional[str] = None
    labels: Annotated[Optional[Dict[str, str]], Field(default_factory=dict)]
    ports: Optional[List[ComposeServicePort]] = None
    volumes: Optional[List[ComposeServiceVolume]] = None

    def get_label(self, label: str) -> str:
        """Get the label of the service.

        Returns
        -------
        str
            The label of the service.
        """
        if not self.labels:
            raise LabelNotFoundError("No labels found in the service. Please check the service configuration.")

        rlabel = self.labels.get(label)
        if not rlabel:
            raise LabelNotFoundError(f"Label {label} not found in the service. Available labels: {sorted(self.labels)}")

        return rlabel

    def get_port_for_internal(self, port: int) -> "ComposeServicePort":
        """Get the published port mapping for an internal (target) port.

        Note this reads the *declared* compose configuration, so it only knows
        ports that were pinned in the compose file. A service declaring
        ``ports: ["5678"]`` lets docker pick a free host port at runtime, which
        does not appear here at all -- use ``Deployment.get_port()`` for that.

        Raises
        ------
        PortNotFoundError
            If the service exposes no ports, none of them map the given internal
            port, or the mapping has no statically declared host port.
        """
        if not self.ports:
            raise PortNotFoundError("No ports found in the service. Please check the service configuration.")

        for i in self.ports:
            if i.target == port:
                if i.published is None:
                    # Returning the mapping here would hand back published=None,
                    # which silently formats into URLs as "http://localhost:None".
                    raise PortNotFoundError(f"Internal port {port} is published on a dynamically assigned host port, which the compose config does not contain. Use `deployment.get_port('<service>', {port})` to resolve the actual host port of the running container.")
                return i

        available = sorted(p.target for p in self.ports if p.target is not None)
        raise PortNotFoundError(f"No published port found for internal port {port}. Mapped internal ports: {available}")


class ComposeConfigNetwork(BaseModel):
    """Network configuration for a Docker Compose file."""

    driver: Optional[str] = None
    name: Optional[str] = None
    external: Optional[bool] = False
    driver_opts: Optional[Dict[str, Any]] = None
    attachable: Optional[bool] = None
    enable_ipv6: Optional[bool] = None
    ipam: Any = None
    internal: Optional[bool] = None
    labels: Annotated[Dict[str, str], Field(default_factory=dict)]


class ComposeConfigVolume(BaseModel):
    """Volume configuration for a Docker Compose file."""

    driver: Optional[str] = None
    driver_opts: Optional[Dict[str, Any]] = None
    external: Optional[bool] = None
    labels: Annotated[Optional[Dict[str, str]], Field(default_factory=dict)]
    name: Optional[str] = None


class ContainerPublisher(BaseModel):
    """A published port of a running container, as reported by `compose ps`."""

    model_config = ConfigDict(populate_by_name=True)

    url: Optional[str] = Field(default=None, alias="URL")
    target_port: Optional[int] = Field(default=None, alias="TargetPort")
    published_port: Optional[int] = Field(default=None, alias="PublishedPort")
    protocol: Optional[str] = Field(default=None, alias="Protocol")


class ContainerStatus(BaseModel):
    """The runtime state of one container, as reported by `docker compose ps`.

    This is the counterpart to `ComposeConfigService`: that describes what the
    compose file *declares*, this describes what is actually running -- state,
    health, and the host ports docker really assigned.

    Compose emits these with capitalised keys, hence the aliases; extra keys are
    ignored so that new compose versions adding fields do not break parsing.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str = Field(alias="Name")
    service: str = Field(alias="Service")
    state: str = Field(default="", alias="State", description="e.g. `running`, `exited`, `created`.")
    health: str = Field(default="", alias="Health", description="Docker's healthcheck verdict: `healthy`, `unhealthy`, `starting`, or empty when the service declares no healthcheck.")
    exit_code: Optional[int] = Field(default=None, alias="ExitCode")
    image: Optional[str] = Field(default=None, alias="Image")
    publishers: List[ContainerPublisher] = Field(default_factory=list, alias="Publishers")

    @property
    def is_running(self) -> bool:
        """Whether the container is currently running."""
        return self.state == "running"

    @property
    def is_healthy(self) -> bool:
        """Whether docker considers the container healthy.

        A container that declares no healthcheck reports an empty health string;
        for those, running is the best available answer.
        """
        if not self.health:
            return self.is_running
        return self.health == "healthy"


class ComposeSpec(BaseModel):
    """Docker Compose specification."""

    services: Optional[Dict[str, ComposeConfigService]] = None
    networks: Annotated[Optional[Dict[str, ComposeConfigNetwork]], Field(default_factory=dict)]
    volumes: Annotated[Optional[Dict[str, ComposeConfigVolume]], Field(default_factory=dict)]
    configs: Any = None
    secrets: Any = None

    def find_service(self, name: Optional[str] = None) -> ComposeConfigService:
        """Find a service by name.

        Parameters
        ----------
        name : str
            The name of the service to find.

        Returns
        -------
        ComposeConfigService
            The service.
        """
        if not self.services:
            raise ServiceNotFoundError("No services found in the compose spec.")
        if name:
            service = self.services.get(name)
            if not service:
                raise ServiceNotFoundError(f"No service found with name {name}. Available services: {sorted(self.services)}")
            return service

        return self.services[list(self.services.keys())[0]]
