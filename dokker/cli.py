from typing import (
    Any,
    cast,
    Optional,
    List,
    Tuple,
    Union,
    Protocol,
    runtime_checkable,
    Dict,
    Literal,
)
from pydantic import Field, field_validator
from koil.composition import KoiledModel
from datetime import timedelta
from .compose_spec import ComposeSpec, ContainerStatus
import json
import os
import shlex
from dokker.errors import DokkerError, PortNotFoundError
from dokker.types import ValidPath, LogStream
from dokker.command import acheck_docker_available, astream_command


class CLIError(DokkerError):
    """An error that is raised when the CLI fails to run."""

    pass


def _split_command(command: str) -> List[str]:
    """Split a command string into argv, POSIX-shell style.

    Commands are passed to docker as an argument vector, so a string has to be
    tokenized. `shlex` is what makes the documented shell form keep working:
    `"sh -c 'echo boom >&2; exit 7'"` splits into three tokens with the quoted
    script preserved as one, so the redirect is interpreted by the container's
    `sh` -- which is what the caller meant -- rather than by a host shell.
    """
    return shlex.split(command)


def _parse_compose_json_list(payload: str) -> List[Dict[str, Any]]:
    """Parse `docker compose ps --format json` output into a list of dicts.

    Compose has emitted two different shapes for this across versions: a single
    JSON array, and newline-delimited JSON with one object per line. Both are
    still in the wild depending on the installed compose version, so accept
    either rather than pinning users to one.
    """
    payload = payload.strip()
    if not payload:
        return []

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        # Not a single document -- try newline-delimited JSON.
        entries: List[Dict[str, Any]] = []
        for line in payload.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise CLIError(f"Could not parse `docker compose ps` output as JSON, neither as an array nor line-by-line. Offending line: {line!r}") from e
        return entries

    if isinstance(parsed, list):
        return parsed
    return [parsed]


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
    compose_files: List[ValidPath] = Field(default_factory=lambda: cast(List[ValidPath], ["docker-compose.yml"]))
    compose_profiles: List[str] = Field(default_factory=lambda: [], description="Compose profiles to activate (`--profile`).")
    # No default: passing `--env-file .env` unconditionally makes compose fail on
    # every project that does not happen to ship one.
    compose_env_file: Optional[ValidPath] = Field(default=None, description="Path to an env file to pass as `--env-file`.")
    compose_project_name: Optional[str] = None
    compose_project_directory: Optional[ValidPath] = None
    compose_compatibility: Optional[bool] = None
    client_call: List[str] = Field(default_factory=lambda: ["docker", "compose"])
    env: Optional[Dict[str, str]] = Field(
        default=None,
        description="Extra environment variables for every docker command, merged over the parent environment. Compose interpolates these into the compose file, so this is how you parameterise a stack (image tags, ports, credentials) per deployment.",
    )

    @field_validator("compose_files")
    def _validate_compose_files(cls, v: List[ValidPath]) -> List[ValidPath]:
        x: list[ValidPath] = []
        for vo in v:
            if os.path.exists(vo):
                x.append(vo)
            else:
                # Relative paths resolve against the CWD at construction time,
                # so say which directory we actually looked in.
                raise ValueError(f"Compose file {vo} does not exist (resolved relative to {os.getcwd()}).")

        return x

    @property
    def docker_cmd(self) -> List[str]:
        """Builds the docker command. This is the base prepended
        command that will be run by the CLI.
        """
        # Copy: `result += [...]` extends in place, so binding straight to the
        # field would append a full flag set to `client_call` on every access.
        result = list(self.client_call)

        if self.compose_files:
            for compose_file in self.compose_files:
                result += ["--file", str(compose_file)]

        if self.compose_project_name is not None:
            result += ["--project-name", str(self.compose_project_name)]

        for profile in self.compose_profiles:
            result += ["--profile", str(profile)]

        if self.compose_env_file is not None:
            result += ["--env-file", str(self.compose_env_file)]

        if self.compose_project_directory is not None:
            result += ["--project-directory", str(self.compose_project_directory)]

        if self.compose_compatibility:
            result.append("--compatibility")

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

    async def _astream(self, full_cmd: List[str]) -> LogStream:
        """Run a docker command, preflighting that docker is actually usable.

        Every `astream_*` method goes through here so that "docker is not
        installed" and "the daemon is not running" are reported as
        `DockerNotAvailableError` before we spawn anything -- rather than as an
        exit code 127 or a raw stderr blob inside a generic `CommandError`. The
        preflight result is cached process-wide, so this costs one subprocess per
        session, not per command.
        """
        await acheck_docker_available(list(self.client_call))
        async for line in astream_command(full_cmd, env=self.env):
            yield line

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

        async for line in self._astream(full_cmd):
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
            full_cmd += ["--rmi", remove_images]
        if timeout is not None:
            full_cmd += ["--timeout", str(timeout)]
        if volumes:
            full_cmd.append("--volumes")

        async for line in self._astream(full_cmd):
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

        async for line in self._astream(full_cmd):
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

            full_cmd += ["--timeout", str(timeout)]

        if services:
            if isinstance(services, str):
                services = [services]
            full_cmd += services

        async for line in self._astream(full_cmd):
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

        async for line in self._astream(full_cmd):
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
        wait_timeout: Optional[int] = None,
        no_attach_services: Union[List[str], str, None] = None,
        pull: Literal["always", "missing", "never", None] = None,
        stream_logs: bool = False,
    ) -> LogStream:
        """Runs the docker-compose up command asynchronously."""
        if quiet and stream_logs:
            raise ValueError("It's not possible to have stream_logs=True and quiet=True at the same time. Only one can be activated at a time.")
        if wait_timeout is not None and not wait:
            raise ValueError("`wait_timeout` only applies together with `wait=True`.")
        full_cmd = self.docker_cmd + ["up"]
        if build:
            full_cmd.append("--build")
        if detach:
            full_cmd.append("--detach")
        if abort_on_container_exit:
            full_cmd.append("--abort-on-container-exit")
        for service, scale in scales.items():
            full_cmd += ["--scale", f"{service}={scale}"]
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
        if wait_timeout is not None:
            full_cmd += ["--wait-timeout", str(wait_timeout)]
        if no_attach_services is not None:
            if isinstance(no_attach_services, str):
                no_attach_services = [no_attach_services]
            for service in no_attach_services:
                full_cmd += ["--no-attach", service]
        if pull is not None:
            full_cmd += ["--pull", pull]

        if services:
            if isinstance(services, str):
                services = [services]
            full_cmd += services

        async for line in self._astream(full_cmd):
            yield line

    async def astream_run(
        self,
        service: str,
        command: List[str] | str,
        remove: bool = True,
        no_deps: bool = False,
        env: Optional[Dict[str, str]] = None,
        workdir: Optional[ValidPath] = None,
        user: Optional[str] = None,
        entrypoint: Optional[str] = None,
        tty: bool = False,
        quiet_pull: bool = True,
    ) -> LogStream:
        """Runs the docker-compose run command asynchronously.

        Creates a *new* container for the command. To run something in the
        already-running container, use `astream_exec`.

        Parameters
        ----------
        tty : bool
            Allocate a TTY. False by default (`-T`): with a TTY, docker merges
            stdout and stderr and injects control characters, which corrupts
            programmatic capture of the two streams.
        quiet_pull : bool
            Suppress image-pull progress. True by default, so pull chatter does
            not end up interleaved with the command's own output in the returned
            logs.
        """
        full_cmd = self.docker_cmd + ["run"]
        if isinstance(command, str):
            command = _split_command(command)
        if not command:
            raise ValueError("Command must be a non-empty list or string.")

        if remove:
            full_cmd.append("--rm")
        if not tty:
            full_cmd.append("--no-TTY")
        if quiet_pull:
            full_cmd.append("--quiet-pull")
        if no_deps:
            full_cmd.append("--no-deps")
        for key, value in (env or {}).items():
            full_cmd += ["--env", f"{key}={value}"]
        if workdir is not None:
            full_cmd += ["--workdir", str(workdir)]
        if user is not None:
            full_cmd += ["--user", user]
        if entrypoint is not None:
            full_cmd += ["--entrypoint", entrypoint]

        full_cmd.append(service)
        full_cmd += command

        async for line in self._astream(full_cmd):
            yield line

    async def astream_exec(
        self,
        service: str,
        command: List[str] | str,
        env: Optional[Dict[str, str]] = None,
        workdir: Optional[ValidPath] = None,
        user: Optional[str] = None,
        privileged: bool = False,
        index: Optional[int] = None,
        tty: bool = False,
    ) -> LogStream:
        """Runs a command inside an already-running container (`compose exec`).

        The counterpart to `astream_run`: `run` starts a fresh throwaway
        container, `exec` acts on the container that is already up. That
        distinction matters whenever the command has to see the running
        service's state -- querying a live database, checking readiness with
        `pg_isready`, inspecting files a service wrote.
        """
        full_cmd = self.docker_cmd + ["exec"]
        if isinstance(command, str):
            command = _split_command(command)
        if not command:
            raise ValueError("Command must be a non-empty list or string.")

        if not tty:
            full_cmd.append("--no-TTY")
        if privileged:
            full_cmd.append("--privileged")
        for key, value in (env or {}).items():
            full_cmd += ["--env", f"{key}={value}"]
        if workdir is not None:
            full_cmd += ["--workdir", str(workdir)]
        if user is not None:
            full_cmd += ["--user", user]
        if index is not None:
            full_cmd += ["--index", str(index)]

        full_cmd.append(service)
        full_cmd += command

        async for line in self._astream(full_cmd):
            yield line

    async def astream_build(
        self,
        services: Union[List[str], str, None] = None,
        no_cache: bool = False,
        pull: bool = False,
        quiet: bool = False,
        build_args: Optional[Dict[str, str]] = None,
    ) -> LogStream:
        """Runs the docker-compose build command asynchronously."""
        full_cmd = self.docker_cmd + ["build"]
        if no_cache:
            full_cmd.append("--no-cache")
        if pull:
            full_cmd.append("--pull")
        if quiet:
            full_cmd.append("--quiet")
        for key, value in (build_args or {}).items():
            full_cmd += ["--build-arg", f"{key}={value}"]

        if services:
            if isinstance(services, str):
                services = [services]
            full_cmd += services

        async for line in self._astream(full_cmd):
            yield line

    async def astream_kill(
        self,
        services: Union[List[str], str, None] = None,
        signal: Optional[str] = None,
    ) -> LogStream:
        """Runs the docker-compose kill command asynchronously.

        Unlike `stop`, this does not wait out a grace period -- useful for
        services that ignore SIGTERM.
        """
        full_cmd = self.docker_cmd + ["kill"]
        if signal is not None:
            full_cmd += ["--signal", signal]

        if services:
            if isinstance(services, str):
                services = [services]
            full_cmd += services

        async for line in self._astream(full_cmd):
            yield line

    async def astream_cp(self, source: str, destination: str) -> LogStream:
        """Copies files between the host and a service's container.

        Paths referring to a container are written `service:/path/in/container`;
        plain paths refer to the host. Copies in either direction.
        """
        full_cmd = self.docker_cmd + ["cp", source, destination]
        async for line in self._astream(full_cmd):
            yield line

    async def _acollect_stdout(self, full_cmd: List[str]) -> str:
        """Run a command and return its stdout, discarding stderr."""
        stdout_lines: list[str] = []
        async for source, line in self._astream(full_cmd):
            if source == "STDOUT":
                stdout_lines.append(line)
        return "\n".join(stdout_lines)

    async def aport(
        self,
        service: str,
        private_port: int,
        protocol: str = "tcp",
        index: Optional[int] = None,
    ) -> Tuple[str, int]:
        """Resolve the host address a service's container port is published on.

        This asks the *running* stack, which is the only way to learn a
        dynamically assigned host port. A compose file that declares
        ``ports: ["5678"]`` lets docker pick a free port at runtime -- the
        mechanism that lets several copies of the same stack run side by side --
        and that port appears nowhere in ``docker compose config``.

        Parameters
        ----------
        service : str
            The service whose container port to resolve.
        private_port : int
            The container-internal port.
        protocol : str
            ``tcp`` (default) or ``udp``.
        index : Optional[int]
            Which replica to ask, when the service is scaled.

        Returns
        -------
        Tuple[str, int]
            The published ``(host, port)`` pair.

        Raises
        ------
        PortNotFoundError
            If the port is not published, or the container is not running --
            compose prints nothing in both cases.
        """
        full_cmd = self.docker_cmd + ["port"]
        if protocol != "tcp":
            full_cmd += ["--protocol", protocol]
        if index is not None:
            full_cmd += ["--index", str(index)]
        full_cmd += [service, str(private_port)]

        result = (await self._acollect_stdout(full_cmd)).strip()

        if not result:
            raise PortNotFoundError(f"Port {private_port}/{protocol} of service `{service}` is not published on the host. Either the service is not running, or its compose configuration does not map that port (a `ports:` entry is required -- `expose:` alone is not published).")

        # Compose prints `host:port`. IPv6 hosts come bracketed, e.g. `[::]:32768`.
        host, _, port = result.rpartition(":")
        try:
            return host.strip("[]"), int(port)
        except ValueError as e:
            raise PortNotFoundError(f"Could not parse the published port for `{service}:{private_port}` from docker's output: {result!r}") from e

    async def aps(
        self,
        services: Optional[List[str]] = None,
        all: bool = False,
    ) -> List[ContainerStatus]:
        """List the project's containers and their runtime state.

        Parameters
        ----------
        services : Optional[List[str]]
            Restrict to these services. None lists the whole project.
        all : bool
            Include stopped containers. By default compose lists only running
            ones, which hides exactly the containers you want to inspect when
            something has crashed.

        Returns
        -------
        List[ContainerStatus]
            One entry per container.
        """
        full_cmd = self.docker_cmd + ["ps", "--format", "json"]
        if all:
            full_cmd.append("--all")
        if services:
            full_cmd += services

        result = (await self._acollect_stdout(full_cmd)).strip()
        if not result:
            return []

        try:
            return [ContainerStatus(**entry) for entry in _parse_compose_json_list(result)]
        except CLIError:
            raise
        except Exception as e:
            raise CLIError(f"Could not parse the output of `docker compose ps`: {result}") from e

    async def areap_stale(self) -> List[str]:
        """Remove the stacks left behind by dead dokker processes on this host.

        Delegates to :func:`dokker.ownership.areap_stale` with this CLI's
        docker invocation and environment, so a custom ``client_call`` or a
        remote ``DOCKER_HOST`` in ``env`` is honoured.

        Returns
        -------
        List[str]
            The compose project names that were removed.
        """
        from dokker.ownership import areap_stale

        return await areap_stale(client_call=list(self.client_call), env=self.env)

    async def aconfig_services(self) -> List[str]:
        """List the service names the compose files resolve to.

        This is `docker compose config --services`: the merged view of all
        compose files, honouring the active profiles. Cheaper than a full
        `ainspect_config` when only the names are needed, e.g. to write an
        override that must mention exactly the existing services.

        Returns
        -------
        List[str]
            The resolved service names, in compose's order.
        """
        result = await self._acollect_stdout(self.docker_cmd + ["config", "--services"])
        return [line.strip() for line in result.splitlines() if line.strip()]

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

        stdout_lines: list[str] = []

        async for source, line in self._astream(full_cmd):
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
