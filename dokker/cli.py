from typing import (
    Optional,
    List,
    Union,
    Protocol,
    runtime_checkable,
    Dict,
    Literal,
)
from pydantic import Field, field_validator
from koil.composition import KoiledModel
from datetime import timedelta
from .compose_spec import ComposeSpec
import json
import os
from dokker.errors import DokkerError
from dokker.types import ValidPath, LogStream
from dokker.command import astream_command


class CLIError(DokkerError):
    """An error that is raised when the CLI fails to run."""

    pass


@runtime_checkable
class CLIBearer(Protocol):
    """A CLIBearer is an object that has a CLI.

    This is a protocol that can be used to type hint objects that have a CLI.
    """

    async def aget_cli(self) -> "CLI":
        """Returns the CLI for the object."""
        ...


class CLI(KoiledModel):
    """A CLI object that represents the docker-compose CLI.

    This is a pydantic model that can be used to build the docker-compose CLI
    command. It also contains methods for running the CLI command
    asynchronously.

    """

    config: Optional[ValidPath] = None
    context: Optional[str] = None
    debug: Optional[bool] = None
    host: Optional[str] = None
    log_level: Optional[str] = None
    tls: Optional[bool] = None
    tlscacert: Optional[ValidPath] = None
    tlscert: Optional[ValidPath] = None
    tlskey: Optional[ValidPath] = None
    tlsverify: Optional[bool] = None
    compose_files: List[ValidPath] = Field(default_factory=lambda: ["docker-compose.yml"])
    compose_profiles: List[ValidPath] = Field(default_factory=list)
    compose_env_file: Optional[ValidPath] = Field(default=".env")
    compose_project_name: Optional[str] = None
    compose_project_directory: Optional[ValidPath] = None
    compose_compatibility: Optional[bool] = None
    client_call: List[str] = Field(default_factory=lambda: ["docker", "compose"])

    @field_validator("compose_files")
    def _validate_compose_files(cls, v: str) -> str:
        x = []
        for vo in v:
            if os.path.exists(vo):
                x.append(vo)
            else:
                raise ValueError(f"Compose File {v} does not exist.")

        return x

    @property
    def docker_cmd(self) -> List[str]:
        """Builds the docker command. This is the base prepended
        command that will be run by the CLI.
        """
        result = self.client_call

        if self.compose_files:
            for compose_file in self.compose_files:
                result += ["--file", str(compose_file)]

        if self.config is not None:
            result += ["--config", str(self.config)]

        if self.context is not None:
            result += ["--context", self.context]

        if self.debug:
            result.append("--debug")

        if self.host is not None:
            result += ["--host", self.host]

        if self.log_level is not None:
            result += ["--log-level", self.log_level]

        if self.tls:
            result.append("--tls")

        if self.tlscacert is not None:
            result += ["--tlscacert", str(self.tlscacert)]

        if self.tlscert is not None:
            result += ["--tlscert", str(self.tlscert)]

        if self.tlskey is not None:
            result += ["--tlskey", str(self.tlskey)]

        if self.tlsverify:
            result.append("--tlsverify")

        return result

    async def astream_docker_logs(
        self,
        tail: Optional[str] = None,
        follow: bool = False,
        no_log_prefix: bool = False,
        timestamps: bool = False,
        since: Optional[str] = None,
        until: Optional[str] = None,
        services: Union[str, List[str]] = [],
    ) -> LogStream:
        """Runs the docker logs command asynchronously."""
        full_cmd = self.docker_cmd + ["logs", "--no-color"]
        if tail is not None:
            full_cmd += ["--tail", tail]
        if follow:
            full_cmd.append("--follow")
        if no_log_prefix:
            full_cmd.append("--no-log-prefix")
        if timestamps:
            full_cmd.append("--timestamps")
        if since is not None:
            full_cmd += ["--since", since]
        if until is not None:
            full_cmd += ["--until", until]

        if services:
            if isinstance(services, str):
                services = [services]
            full_cmd += services

        async for line in astream_command(full_cmd):
            yield line

    async def astream_down(
        self,
        remove_orphans: bool = False,
        remove_images: Optional[str] = None,
        timeout: Optional[int] = None,
        volumes: bool = False,
    ) -> LogStream:
        """Runs the docker-compose down command asynchronously."""
        full_cmd = self.docker_cmd + ["down"]
        if remove_orphans:
            full_cmd.append("--remove-orphans")
        if remove_images is not None:
            full_cmd.append(f"--rmi {remove_images}")
        if timeout is not None:
            full_cmd.append(f"--timeout {timeout}")
        if volumes:
            full_cmd.append("--volumes")

        async for line in astream_command(full_cmd):
            yield line

    async def astream_pull(
        self,
        services: Union[List[str], str, None] = None,
        ignore_pull_failures: bool = False,
        include_deps: bool = False,
        quiet: bool = False,
    ) -> LogStream:
        """Runs the docker-compose pull command asynchronously."""
        full_cmd = self.docker_cmd + ["pull"]
        if ignore_pull_failures:
            full_cmd.append("--ignore-pull-failures")
        if include_deps:
            full_cmd.append("--include-deps")
        if quiet:
            full_cmd.append("--quiet")

        if services:
            if isinstance(services, str):
                services = [services]
            full_cmd += services

        async for line in astream_command(full_cmd):
            yield line

    async def astream_stop(
        self,
        services: Union[str, List[str], None] = None,
        timeout: Union[int, timedelta, None] = None,
    ) -> LogStream:
        """Runs the docker-compose stop command asynchronously."""
        full_cmd = self.docker_cmd + ["stop"]
        if timeout is not None:
            if isinstance(timeout, timedelta):
                timeout = int(timeout.total_seconds())

            full_cmd.append(f"--timeout {timeout}")

        if services:
            if isinstance(services, str):
                services = [services]
            full_cmd += services

        async for line in astream_command(full_cmd):
            yield line

    async def astream_restart(
        self,
        services: Union[str, List[str], None] = None,
    ) -> LogStream:
        """Runs the docker-compose restart command asynchronously."""
        full_cmd = self.docker_cmd + ["restart"]

        if services:
            if isinstance(services, str):
                services = [services]
            full_cmd += services

        async for line in astream_command(full_cmd):
            yield line

    async def astream_up(
        self,
        services: Union[List[str], str, None] = None,
        build: bool = False,
        detach: bool = False,
        abort_on_container_exit: bool = False,
        scales: Dict[str, int] = {},
        attach_dependencies: bool = False,
        force_recreate: bool = False,
        no_recreate: bool = False,
        no_build: bool = False,
        remove_orphans: bool = False,
        renew_anon_volumes: bool = False,
        no_color: bool = False,
        no_log_prefix: bool = False,
        no_start: bool = False,
        quiet: bool = False,
        wait: bool = False,
        no_attach_services: Union[List[str], str, None] = None,
        pull: Literal["always", "missing", "never", None] = None,
        stream_logs: bool = False,
    ) -> LogStream:
        """Runs the docker-compose up command asynchronously."""
        if quiet and stream_logs:
            raise ValueError("It's not possible to have stream_logs=True and quiet=True at the same time. Only one can be activated at a time.")
        full_cmd = self.docker_cmd + ["up"]
        if build:
            full_cmd.append("--build")
        if detach:
            full_cmd.append("--detach")
        if abort_on_container_exit:
            full_cmd.append("--abort-on-container-exit")
        for service, scale in scales.items():
            full_cmd.append(f"--scale {service}={scale}")
        if attach_dependencies:
            full_cmd.append("--attach-dependencies")
        if force_recreate:
            full_cmd.append("--force-recreate")
        if no_recreate:
            full_cmd.append("--no-recreate")
        if no_build:
            full_cmd.append("--no-build")
        if remove_orphans:
            full_cmd.append("--remove-orphans")
        if renew_anon_volumes:
            full_cmd.append("--renew-anon-volumes")
        if no_color:
            full_cmd.append("--no-color")
        if no_log_prefix:
            full_cmd.append("--no-log-prefix")
        if no_start:
            full_cmd.append("--no-start")
        if quiet:
            full_cmd.append("--quiet")
        if wait:
            full_cmd.append("--wait")
        if no_attach_services is not None:
            if isinstance(no_attach_services, str):
                no_attach_services = [no_attach_services]
            for service in no_attach_services:
                full_cmd.append(f"--no-attach {service}")
        if pull is not None:
            full_cmd.append(f"--pull {pull}")

        if services:
            if isinstance(services, str):
                services = [services]
            full_cmd += services

        async for line in astream_command(full_cmd):
            yield line

    async def ainspect_config(self) -> ComposeSpec:
        """Inspect the config of the docker-compose project.

        Returns
        -------
        ComposeSpec
            The compose spec of the project.

        Raises
        ------
        CLIError
            An error that is raised when the CLI fails to run.
        """
        full_cmd = self.docker_cmd + ["config", "--format", "json"]

        stdout_lines = []

        async for source, line in astream_command(full_cmd):
            if source == "STDERR":
                continue
            elif source == "STDOUT":
                stdout_lines.append(line)
            else:
                raise ValueError(f"Unknown source: {source}")

        result = "\n".join(stdout_lines)

        try:
            return ComposeSpec(**json.loads(result))
        except Exception as e:
            raise CLIError(f"Could not inspect! Error while parsing the json: {result}") from e
