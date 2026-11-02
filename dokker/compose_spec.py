from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from typing import Annotated

from dokker.errors import LabelNotFoundError, PortNotFoundError, ServiceNotFoundError


class ServicePlacement(BaseModel):
    """Service placement constraints."""

    constraints: list[str] | None = None


class ResourcesLimits(BaseModel):
    """Resource limits for a service."""

    cpus: float | None = None
    memory: int | None = None


class ResourcesReservation(BaseModel):
    """Resource reservations for a service."""

    cpus: float | int | None = None
    memory: int | None = None


class ServiceResources(BaseModel):
    """Resource configuration for a service."""

    limits: ResourcesLimits | None = None
    reservations: ResourcesReservation | None = None


class ServiceDeployConfig(BaseModel):
    """Service deployment configuration."""

    labels: dict[str, str] | None = None
    resources: ServiceResources | None = None
    placement: ServicePlacement | None = None
    replicas: int | None = None


class DependencyCondition(BaseModel):
    """Dependency condition for a service."""

    condition: str | None = None


class ComposeServiceBuild(BaseModel):
    """Build configuration for a service."""

    context: Path | None = None
    dockerfile: Path | None = None
    args: dict[str, Any] | None = None
    labels: dict[str, Any] | None = None


class ComposeServicePort(BaseModel):
    """Port configuration for a service."""

    mode: str | None = None
    protocol: str | None = None
    published: int | None = None
    target: int | None = None


class ComposeServiceVolume(BaseModel):
    """Volume configuration for a service."""

    bind: dict[str, Any] | None = None
    source: str | None = None
    target: str | None = None
    type: str | None = None


class ComposeConfigService(BaseModel):
    """Service configuration for a Docker Compose file."""

    deploy: ServiceDeployConfig | None = None
    blkio_config: Any | None = None
    cpu_count: float | None = None
    cpu_percent: float | None = None
    cpu_shares: int | None = None
    cpuset: str | None = None
    build: ComposeServiceBuild | None = None
    cap_add: Annotated[list[str] | None, Field(default_factory=list)]
    cap_drop: Annotated[list[str] | None, Field(default_factory=list)]
    cgroup_parent: str | None = None
    command: list[str] | None = None
    configs: Any = None
    container_name: str | None = None
    depends_on: Annotated[dict[str, DependencyCondition], Field(default_factory=dict)]
    device_cgroup_rules: Annotated[list[str], Field(default_factory=list)]
    devices: Any = None
    environment: dict[str, str | None] | None = None
    entrypoint: list[str] | None = None
    image: str | None = None
    labels: Annotated[dict[str, str] | None, Field(default_factory=dict)]
    ports: list[ComposeServicePort] | None = None
    volumes: list[ComposeServiceVolume] | None = None

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

    driver: str | None = None
    name: str | None = None
    external: bool | None = False
    driver_opts: dict[str, Any] | None = None
    attachable: bool | None = None
    enable_ipv6: bool | None = None
    ipam: Any = None
    internal: bool | None = None
    labels: Annotated[dict[str, str], Field(default_factory=dict)]


class ComposeConfigVolume(BaseModel):
    """Volume configuration for a Docker Compose file."""

    driver: str | None = None
    driver_opts: dict[str, Any] | None = None
    external: bool | None = None
    labels: Annotated[dict[str, str] | None, Field(default_factory=dict)]
    name: str | None = None


class ContainerPublisher(BaseModel):
    """A published port of a running container, as reported by `compose ps`."""

    model_config = ConfigDict(populate_by_name=True)

    url: str | None = Field(default=None, alias="URL")
    target_port: int | None = Field(default=None, alias="TargetPort")
    published_port: int | None = Field(default=None, alias="PublishedPort")
    protocol: str | None = Field(default=None, alias="Protocol")


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
    exit_code: int | None = Field(default=None, alias="ExitCode")
    image: str | None = Field(default=None, alias="Image")
    publishers: list[ContainerPublisher] = Field(default_factory=list, alias="Publishers")

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

    services: dict[str, ComposeConfigService] | None = None
    networks: Annotated[dict[str, ComposeConfigNetwork] | None, Field(default_factory=dict)]
    volumes: Annotated[dict[str, ComposeConfigVolume] | None, Field(default_factory=dict)]
    configs: Any = None
    secrets: Any = None

    def find_service(self, name: str | None = None) -> ComposeConfigService:
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
