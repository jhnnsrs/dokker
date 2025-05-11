from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field
from typing_extensions import Annotated


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
            raise ValueError("No labels found in the service. Please check the service configuration.")

        rlabel = self.labels.get(label)
        if not rlabel:
            raise ValueError(f"Label {label} not found in the service.")

        return rlabel

    def get_port_for_internal(self, port: int) -> "ComposeServicePort":
        """Get the port for the internal port."""

        if not self.ports:
            raise ValueError("No ports found in the service. Please check the service configuration.")

        for i in self.ports:
            if i.target == port:
                return i

        raise Exception(f"No published port found for Port: {port}")


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
            raise Exception("No services found in the compose spec.")
        if name:
            service = self.services.get(name)
            if not service:
                raise Exception(f"No service found with name {name}.")
            return service

        return self.services[list(self.services.keys())[0]]
