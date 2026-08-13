"""Readiness checks for a deployment.

A *check* answers "is this service ready to be used yet?". The original (and
still default) answer was an HTTP GET, which cannot express readiness for the
services integration tests most often depend on -- postgres, redis, kafka speak
no HTTP at all.

This module generalises the idea. Any object satisfying the `Check` protocol can
go in `Deployment.health_checks`, and `Deployment.acheck_health` retries it the
same way. The existing `HealthCheck` satisfies the protocol, so nothing about
the HTTP path changes.

The checks are deliberately built on top of primitives the deployment already
has -- `CLI.aport`, `CLI.aps`, `CLI.astream_exec` -- rather than reimplementing
container introspection.
"""

import asyncio
import re
from typing import List, Optional, Protocol, Union, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from dokker.cli import CLI
from dokker.compose_spec import ComposeSpec
from dokker.errors import HealthCheckError


class CheckContext(BaseModel):
    """What a check is allowed to see.

    Carries both the static compose spec and the live CLI, because readiness
    generally needs the running stack (a resolved host port, a container's
    health status) and not just the declared configuration.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    spec: ComposeSpec
    cli: CLI


@runtime_checkable
class Check(Protocol):
    """Something that can decide whether a service is ready.

    Implementations raise `HealthCheckError` (or any exception) to signal "not
    ready"; returning normally means ready. Retrying and back-off are the
    deployment's job, driven by `max_retries` and `timeout`.
    """

    service: str
    max_retries: int
    timeout: int

    async def aperform(self, ctx: CheckContext) -> None:
        """Raise if the service is not ready yet."""
        ...


class BaseCheck(BaseModel):
    """Shared fields for the built-in non-HTTP checks."""

    service: str = Field(description="The service this check applies to.")
    max_retries: int = Field(default=3, description="The maximum number of retries before failing.")
    timeout: int = Field(default=10, description="Seconds to sleep between retries.")


class TcpCheck(BaseCheck):
    """Ready when a TCP connection to the service's published port succeeds.

    The cheapest useful readiness signal for anything that listens on a socket
    but does not speak HTTP. The port given is the *container* port; it is
    resolved to the real published host port at check time, so this works with
    ephemeral port mappings.
    """

    port: int = Field(description="The container-internal port to connect to.")
    connect_timeout: float = Field(default=5.0, description="Seconds to wait for the TCP connection.")

    async def aperform(self, ctx: CheckContext) -> None:
        """Attempt a TCP connection to the resolved host port."""
        host, published = await ctx.cli.aport(self.service, self.port)
        # Compose reports 0.0.0.0 / :: for "all interfaces"; neither is dialable
        # on every platform, so connect over loopback instead.
        if host in ("0.0.0.0", "::", ""):
            host = "127.0.0.1"

        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, published),
                timeout=self.connect_timeout,
            )
        except (OSError, asyncio.TimeoutError) as e:
            raise HealthCheckError(f"TCP check for service `{self.service}` could not connect to {host}:{published} (container port {self.port}): {e}") from e

        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            # The peer may reset an unused connection; that is not a failure of
            # the check itself -- we already proved something is listening.
            pass


class CommandCheck(BaseCheck):
    """Ready when a command run *inside* the running container exits zero.

    This is the general answer for services with their own readiness tooling:
    `pg_isready -U postgres`, `redis-cli ping`, `mysqladmin ping`. It uses
    `docker compose exec`, so it runs in the already-running container rather
    than a throwaway one.
    """

    command: Union[str, List[str]] = Field(description="The command to run inside the container.")

    async def aperform(self, ctx: CheckContext) -> None:
        """Run the command in the container and raise unless it exits zero."""
        from dokker.command import CommandError

        try:
            async for _ in ctx.cli.astream_exec(self.service, self.command):
                pass
        except CommandError as e:
            raise HealthCheckError(f"Command check for service `{self.service}` failed: `{e.command}` exited with {e.returncode}." + (f"\n\nSTDERR:\n{chr(10).join(e.stderr)}" if e.stderr else "")) from e


class ContainerCheck(BaseCheck):
    """Ready when the service's container is running (and healthy, if declared).

    Reads container state from `docker compose ps`. When the compose file
    declares a `healthcheck:` for the service, this defers to docker's own
    verdict -- which is usually the most accurate signal available, since it is
    the service author's own definition of ready.
    """

    require_healthy: bool = Field(
        default=True,
        description="Require health status `healthy` when the container declares a healthcheck. When it declares none, running is enough.",
    )

    async def aperform(self, ctx: CheckContext) -> None:
        """Inspect container state and raise unless it is running/healthy."""
        containers = await ctx.cli.aps(services=[self.service], all=True)
        if not containers:
            raise HealthCheckError(f"Container check for service `{self.service}` found no container. Is the service part of this compose project, and has it been started?")

        for container in containers:
            if container.state != "running":
                raise HealthCheckError(f"Container check for service `{self.service}` failed: container `{container.name}` is `{container.state}`" + (f" (exit code {container.exit_code})" if container.exit_code else "") + ".")
            if self.require_healthy and container.health and container.health not in ("healthy", "none", ""):
                raise HealthCheckError(f"Container check for service `{self.service}` failed: container `{container.name}` reports health `{container.health}`.")


class LogCheck(BaseCheck):
    """Ready when a service's logs match a pattern.

    For services whose only reliable readiness signal is what they print --
    postgres' "database system is ready to accept connections" being the classic
    case.
    """

    pattern: str = Field(description="Regular expression searched for in the service's logs.")
    tail: Optional[int] = Field(default=None, description="Only search the last N lines. None searches all available logs.")

    async def aperform(self, ctx: CheckContext) -> None:
        """Fetch the service's logs and raise unless the pattern is present."""
        regex = re.compile(self.pattern)
        lines: List[str] = []

        async for _, line in ctx.cli.astream_docker_logs(
            tail=str(self.tail) if self.tail else None,
            follow=False,
            services=[self.service],
        ):
            if regex.search(line):
                return
            lines.append(line)

        raise HealthCheckError(f"Log check for service `{self.service}` did not find /{self.pattern}/ in {len(lines)} log line(s)." + ("\n\nLast lines:\n" + "\n".join(lines[-10:]) if lines else " The service has logged nothing yet."))
