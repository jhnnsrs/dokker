from types import TracebackType
import aiohttp.client_exceptions
import aiohttp.http_exceptions
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr
from typing import Awaitable, Dict, Literal, Optional, List, Protocol, Self, Type, runtime_checkable
from koil.composition import KoiledModel
from dataclasses import dataclass
import asyncio
from pathlib import Path
from dokker.compose_spec import ComposeSpec
from dokker.project import Project
from typing import Union
from koil import unkoil
from dokker.cli import CLI
from dokker.loggers.void import VoidLogger
from dokker.types import LogFunction
from .log_watcher import LogRoll, LogWatcher
import aiohttp
import certifi
from ssl import SSLContext
import ssl
from typing import Callable
from dokker.errors import NotInitializedError, NotInspectedError, HealthCheckError, TearDownError
from dokker.command import CommandError
import logging


logger = logging.getLogger(__name__)

ValidPath = Union[str, Path]


PolicyName = Literal["testing", "local", "monitoring", "manual"]
"""The name of a teardown policy. See ``TEARDOWN_POLICIES``."""


@dataclass(frozen=True)
class TeardownPolicy:
    """What a deployment does on context-manager exit, by default.

    A policy is the *global* default for ``up()``: when ``up()`` is called
    without an explicit ``down_on_exit``/``stop_on_exit``, the deployment's
    policy decides what teardown gets registered. Per-call arguments always
    locally override the policy.

    Attributes
    ----------
    exit_action:
        ``"down"`` to remove the stack on exit, ``"stop"`` to only stop it
        (containers and volumes kept), or ``None`` for no automatic teardown.
    tear_down_project:
        Whether to also tear the project down on exit (e.g. remove a
        ``mirror`` temp-dir copy). No-op for projects that create nothing.
    """

    exit_action: Optional[Literal["down", "stop"]] = None
    tear_down_project: bool = False


TEARDOWN_POLICIES: Dict[str, TeardownPolicy] = {
    # Full integration cleanup: down (which, with the deployment's default
    # remove_*_on_down flags, also drops volumes + orphans) and tear the
    # project down (removes a mirror temp-dir copy).
    "testing": TeardownPolicy(exit_action="down", tear_down_project=True),
    # A stack you drive yourself: stop on exit, keep the containers and any
    # data volumes so you can bring it back up.
    "local": TeardownPolicy(exit_action="stop", tear_down_project=False),
    # Observe a stack you do not own: never change it on exit.
    "monitoring": TeardownPolicy(exit_action=None, tear_down_project=False),
    # Bare deployment: you are responsible for teardown.
    "manual": TeardownPolicy(exit_action=None, tear_down_project=False),
}


class HealthCheck(BaseModel):
    """A health check for a service.

    This class is used to check the health of a service by making a request to a given URL.
    The URL can be a string or a callable that takes the compose spec as an argument and returns a string.
    The health check will be retried a given number of times with a given timeout between retries.
    If the health check fails, an error will be raised.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)
    url: Union[str, Callable[[ComposeSpec], str]] = Field(description="The url to check. Can be a string or a callable that takes the compose spec as an argument and returns a string.")
    service: str = Field(description="The service to check.")
    max_retries: int = Field(default=3, description="The maximum number of retries before failing.")
    timeout: int = Field(default=10, description="The timeout between retries.")
    error_with_logs: bool = Field(
        default=True,
        description="Should we error with the logs of the service (will inspect container logs of the service).",
    )
    headers: Optional[Dict[str, str]] = Field(
        default_factory=lambda: {"Content-Type": "application/json"},
        description="Headers to use for the request",
    )
    ssl_context: SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where()),
        description="SSL Context to use for the request",
    )
    valid_statuses: list[int] = Field(
        default_factory=lambda: [200],
        description="The valid statuses for the health check. Defaults to 200.",
    )

    async def acheck(self, spec: ComposeSpec) -> str:
        """Check the health of the service.

        This method will make a request to the given URL and check the response status.
        If the status is not in the valid statuses, an error will be raised.
        Parameters
        ----------
        spec : ComposeSpec
            The compose spec to use for the health check.
        """
        async with aiohttp.ClientSession(
            headers=self.headers,
            connector=aiohttp.TCPConnector(ssl=self.ssl_context),
        ) as session:
            # get json from endpoint
            url = self.url if isinstance(self.url, str) else self.url(spec)

            try:
                async with session.get(url) as resp:
                    if resp.status not in self.valid_statuses:
                        raise HealthCheckError(f"Status is not in valid statuses. Got {resp.status}, wants on of {self.valid_statuses} ")
                    return await resp.text()
            except aiohttp.http_exceptions.BadHttpMessage as e:
                raise HealthCheckError("Health test Failed") from e
            except aiohttp.client_exceptions.ClientError as e:
                raise HealthCheckError("Health test failed") from e


@runtime_checkable
class Logger(Protocol):
    """A logger for the deployment."""

    def on_pull(self, log: tuple[str, str]) -> None:
        """When the deployment is pulled, this method is called."""
        ...

    def on_up(self, log: tuple[str, str]) -> None:
        """When the deployment is up, this method is called."""
        ...

    def on_stop(self, log: tuple[str, str]) -> None:
        """When the deployment is stopped, this method is called."""
        ...

    def on_logs(self, log: tuple[str, str]) -> None:
        """When the deployment is logging, this method is called."""
        ...

    def on_down(self, log: tuple[str, str]) -> None:
        """When the deployment is down, this method is called."""
        ...


class Deployment(KoiledModel):
    """A deployment is a set of services that are deployed together."""

    project: Project = Field(default_factory=Project)

    health_checks: List[HealthCheck] = Field(
        default_factory=lambda: [],
        description="A list of health checks to run on the deployment. These are run when the deployment is up and running.",
    )
    policy: PolicyName = Field(
        default="manual",
        description=(
            "The teardown policy: the global default for what `up()` registers on "
            "context-manager exit when no explicit `down_on_exit`/`stop_on_exit` is "
            "given. `testing` downs (and tears the project down), `local` stops, "
            "`monitoring`/`manual` do nothing. Per-call `up(...)` arguments override "
            "it locally. See `TEARDOWN_POLICIES`."
        ),
    )
    remove_orphans_on_down: bool = Field(
        default=True,
        description="Should we remove orphan containers when downing the deployment (`--remove-orphans`). Defaults to True so a `down` leaves nothing dangling; set False to keep orphans.",
    )
    remove_volumes_on_down: bool = Field(
        default=True,
        description="Should we remove named/anonymous volumes when downing the deployment (`--volumes`). Defaults to True so a `down` does not leak volumes; set False to preserve data (e.g. a local dev database).",
    )
    shutdown_timeout: Optional[int] = Field(
        default=None,
        description=("Grace period in seconds passed to `docker compose stop`/`down` as `-t`. A container that ignores SIGTERM is SIGKILLed after this many seconds, which bounds how long stopping a single container can block teardown. None (the default) uses docker's own default (10s)."),
    )
    teardown_timeout: Optional[float] = Field(
        default=None,
        description=(
            "Overall wall-clock timeout in seconds for the on-exit teardown (stop/down/tear "
            "down). If docker compose has not finished within this window, dokker stops "
            "waiting and raises a TearDownError. Note that the docker daemon keeps running "
            "the operation in the background; prefer `shutdown_timeout` to make individual "
            "containers stop faster. None (the default) disables this guard."
        ),
    )
    threadpool_workers: int = Field(
        default=10,
        description="The number of workers to use for the threadpool. This is used for the health checks and the log watcher.",
    )

    pull_logs: Optional[List[str]] = Field(
        default=None,
        description="The logs of the pull command. Will be set when the deployment is pulled.",
    )
    up_logs: Optional[List[str]] = Field(
        default=None,
        description="The logs of the up command. Will be set when the deployment is up.",
    )
    stop_logs: Optional[List[str]] = Field(
        default=None,
        description="The logs of the stop command. Will be set when the deployment is stopped.",
    )

    auto_initialize: bool = Field(
        default=True,
        description="Should we automatically initialize the deployment when using it as a context manager.",
    )

    logger: Logger = Field(default_factory=VoidLogger)

    _spec: Optional[ComposeSpec] = None
    _cli: Optional[CLI] = None
    _cleanup_stack: List[Callable[[], Awaitable[None]]] = PrivateAttr(default_factory=list)
    _registered_keys: set[str] = PrivateAttr(default_factory=set)
    _entered: bool = PrivateAttr(default=False)

    def _register_cleanup(self, coro_factory: Callable[[], Awaitable[None]], key: Optional[str] = None) -> None:
        """Register an on-exit teardown.

        ``coro_factory`` is a zero-argument callable returning a coroutine. It is
        run when the deployment leaves its context manager, in LIFO order (so the
        last resource created is the first torn down). Commands that create
        resources (e.g. ``aup``, project initialization) use this so exit always
        cleans up exactly what the body started.

        ``key`` deduplicates: a teardown registered with a key already seen on this
        deployment is skipped, so calling e.g. ``up(down_on_exit=True)`` twice still
        downs only once. The first registration keeps its position in the stack.
        """
        if key is not None:
            if key in self._registered_keys:
                return
            self._registered_keys.add(key)
        self._cleanup_stack.append(coro_factory)

    @property
    def spec(self) -> ComposeSpec:
        """A property that returns the compose spec of the deployment.

        THis compose spec can be used to retrieve information about the deployment.
        by inspecting the containers, networks, volumes, etc.

        In the future, this spec will be used to
        retrieve information about the deployment.

        Returns
        -------
        ComposeSpec
            The compose spec.

        Raises
        ------
        NotInspectedError
            If the deployment has not been inspected.
        """
        if self._spec is None:
            raise NotInspectedError("Deployment not inspected. Call await deployment.ainspect() first.")
        return self._spec

    async def ainitialize(self) -> "CLI":
        """Initialize the deployment.

        Will initialize the deployment through its project and return the CLI object.
        This is called lazily on first CLI access (when ``auto_initialize`` is True),
        so you rarely call it directly.

        Returns
        -------
        CLI
           The CLI object.
        """
        self._cli = await self.project.ainititialize()
        # If we are inside a context manager and the policy tears the project
        # down, make sure whatever the project created at initialize time (e.g. a
        # CopyPathProject temp-dir copy) is removed on exit. ``atear_down`` is a
        # no-op for projects that create nothing (LocalProject/DokkerProject).
        if self._entered and TEARDOWN_POLICIES[self.policy].tear_down_project:
            cli = self._cli
            self._register_cleanup(lambda: self.project.atear_down(cli), key="project_teardown")
        return self._cli

    async def aretrieve_cli(self) -> "CLI":
        """Retrieve the CLI object of the deployment."""
        if self._cli is None:
            if self.auto_initialize:
                self._cli = await self.ainitialize()
            else:
                raise NotInitializedError("Deployment not initialized and auto_initialize is False. Call await deployment.ainitialize() first.")

        return self._cli

    async def arun(
        self,
        service: str,
        command: List[str] | str,
        raise_on_error: bool = True,
        expected_exit_code: int = 0,
    ) -> LogRoll:
        """Run a command in a service.

        Will run the given command in the given service and return the logs.
        The exit code of the command is available on the returned
        ``LogRoll.returncode``.

        Parameters
        ----------
        service : str
            The name of the service to run the command in.
        command : List[str]
            The command to run as a list of strings.
        raise_on_error : bool, optional
            If True (the default), a ``CommandError`` is raised when the command
            exits with a code different from ``expected_exit_code``. If False,
            the logs are returned regardless and the exit code can be inspected
            on ``LogRoll.returncode``.
        expected_exit_code : int, optional
            The exit code that is considered a success, by default 0. Useful for
            commands that are expected to fail (e.g. asserting a non-zero exit).

        Returns
        -------
        LogRoll
            The logs of the command, with ``returncode`` set to the exit code.

        Raises
        ------
        CommandError
            If ``raise_on_error`` is True and the command exits with a code
            different from ``expected_exit_code``.
        """
        cli = await self.aretrieve_cli()
        logs = LogRoll()
        error: Optional[CommandError] = None
        try:
            async for log in cli.astream_run(service=service, command=command):
                logs.append(log)
                self.logger.on_logs(log)
        except CommandError as e:
            # A failure that is not about the exit code (e.g. the subprocess
            # could not be spawned) carries no return code and must always raise.
            if e.returncode is None:
                raise
            error = e

        returncode = error.returncode if error is not None else 0
        logs.returncode = returncode

        if returncode != expected_exit_code and raise_on_error:
            if error is not None:
                # Re-raise the rich error from the command layer, but make clear
                # that a specific exit code was expected when that is the case.
                if expected_exit_code != 0:
                    error.args = (f"{error.args[0]}\n\nExpected exit code {expected_exit_code}, got {returncode}.",)
                raise error
            raise CommandError(
                f"Command in service `{service}` exited with code {returncode}, expected {expected_exit_code}.\n\n" + ("STDOUT:\n" + logs.stdout if logs.stdout else "No output was captured."),
                command=command if isinstance(command, str) else " ".join(command),
                returncode=returncode,
                stdout=logs.stdout_list,
                stderr=logs.stderr_list,
            )

        return logs

    def run(
        self,
        service: str,
        command: List[str] | str,
        raise_on_error: bool = True,
        expected_exit_code: int = 0,
    ) -> LogRoll:
        """Run a command in a service. (sync)

        Will run the given command in the given service and return the logs.
        The exit code of the command is available on the returned
        ``LogRoll.returncode``.

        Parameters
        ----------
        service : str
            The name of the service to run the command in.
        command : List[str]
            The command to run as a list of strings.
        raise_on_error : bool, optional
            If True (the default), a ``CommandError`` is raised when the command
            exits with a code different from ``expected_exit_code``. If False,
            the logs are returned regardless and the exit code can be inspected
            on ``LogRoll.returncode``.
        expected_exit_code : int, optional
            The exit code that is considered a success, by default 0. Useful for
            commands that are expected to fail (e.g. asserting a non-zero exit).

        Returns
        -------
        LogRoll
            The logs of the command, with ``returncode`` set to the exit code.

        Raises
        ------
        CommandError
            If ``raise_on_error`` is True and the command exits with a code
            different from ``expected_exit_code``.
        """
        return unkoil(
            self.arun,
            service=service,
            command=command,
            raise_on_error=raise_on_error,
            expected_exit_code=expected_exit_code,
        )

    async def ainspect(self) -> ComposeSpec:
        """Inspect the deployment.

        Will inspect the deployment through its project and return the compose spec, which
        can be used to retrieve information about the deployment.
        Call this from inside the context manager before reading ``deployment.spec``.
        Returns
        -------
        ComposeSpec
            The compose spec.

        Raises
        ------
        NotInitializedError
            If the deployment has not been initialized.
        """
        cli = await self.aretrieve_cli()
        self._spec = await cli.ainspect_config()
        return self._spec

    def inspect(self) -> ComposeSpec:
        """Inspect the deployment.

        Will inspect the deployment through its project and return the compose spec, which
        can be used to retrieve information about the deployment.
        Call this from inside the context manager before reading ``deployment.spec``.

        Returns
        -------
        ComposeSpec
            The compose spec.
        Raises
        ------
        NotInitializedError
            If the deployment has not been initialized.
        """
        return unkoil(self.ainspect)

    def add_health_check(
        self,
        url: Union[str, Callable[[ComposeSpec], str]],
        service: str,
        max_retries: int = 3,
        timeout: int = 10,
        error_with_logs: bool = True,
    ) -> "HealthCheck":
        """Add a health check to the deployment.

        Parameters
        ----------
        url : Union[str, Callable[[ComposeSpec], str]]
            The url to check. Also accepts a function that uses the introspected compose spec to build an url
        service : str
            The service this health check is for.
        max_retries : int, optional
            The maximum retries before the healtch checks fails, by default 3
        timeout : int, optional
            The timeout between retries, by default 10
        error_with_logs : bool, optional
            Should we error with the logs of the service (will inspect container logs of the service), by default True

        Returns
        -------
        HealthCheck
            The health check object.
        """

        check = HealthCheck(
            url=url,
            service=service,
            max_retries=max_retries,
            timeout=timeout,
            error_with_logs=error_with_logs,
        )

        self.health_checks.append(check)
        return check

    async def arun_check(self, check: HealthCheck, retry: int = 0) -> None:
        """Run a health check.

        This method will make a request to the given URL and check the response status.
        If the status is not in the valid statuses, an error will be raised.
        Parameters
        ----------
        check : HealthCheck
            The health check to run.
        retry : int
            The number of retries already done.
        """

        if not self._spec:
            self._spec = await self.ainspect()

        if not self._cli:
            self._cli = await self.ainitialize()

        try:
            await check.acheck(self._spec)
        except HealthCheckError as e:
            if retry < check.max_retries:
                await asyncio.sleep(check.timeout)
                await self.arun_check(check, retry=retry + 1)
            else:
                if not check.error_with_logs:
                    raise HealthCheckError(f"Health check failed after {check.max_retries} retries. Logs are disabled.") from e

                logs = LogRoll()

                async for log in self._cli.astream_docker_logs(services=[check.service]):
                    logs.append(log)

                raise HealthCheckError(f"Health check failed after {check.max_retries} retries. Logs:\n" + "\n".join(i for _, i in logs)) from e

    async def acheck_health(self, timeout: int = 3, retry: int = 0, services: Optional[List[str]] = None) -> None:
        """Check the health of the deployment.

        This method will make a request to all the health checks and check the response status
        concurrently.

        If the status is not in the valid statuses, an error will be raised.

        Parameters
        ----------
        timeout : int
            The timeout between retries.
        retry : int
            The number of retries already done.
        services : Optional[List[str]]
            The list of services to check. If None, all services will be checked.
        """

        if services is None:
            services = [check.service for check in self.health_checks]  # we check all services

        await asyncio.gather(*[self.arun_check(check) for check in self.health_checks if check.service in services])

    def check_health(
        self,
    ) -> None:
        """Check the health of the deployment.

        This method will make a request to all the health checks and check the response status
        concurrently.
        If the status is not in the valid statuses, an error will be raised.
        """
        return unkoil(self.acheck_health)

    def create_watcher(
        self,
        services: Union[List[str], str],
        tail: Optional[int] = None,
        follow: bool = True,
        no_log_prefix: bool = False,
        timestamps: bool = False,
        since: Optional[str] = None,
        until: Optional[str] = None,
        stream: bool = True,
        wait_for_first_log: bool = True,
        wait_for_logs: bool = False,
        wait_for_logs_timeout: int = 10,
        log_function: Optional[LogFunction] = None,
        append_to_traceback: bool = True,
        capture_stdout: bool = True,
        rich_traceback: bool = True,
    ) -> LogWatcher:
        """Get a logswatcher for a service.

        A logswatcher is an object that can be used to watch the logs of a service, as
        they are being streamed. It is an (async) context manager that should be used
        to enclose any code that needs to watch the logs of a service.

        ```python
         with deployment.logswatcher("service"):
            # do something with service logs
            print(requests.get("http://service").text

        ```

        If you want to watch the logs of multiple services, you can pass a list of service names.

            ```python

            watcher = deployment.logswatcher(["service1", "service2"])
            with watcher:
                # do something with service logs
                print(requests.get("http://service1").text
                print(requests.get("http://service2").text

            print(watcher.collected_logs)

            ```

        Parameters
        ----------
        service_name : Union[List[str], str]
            The name of the service(s) to watch the logs for.

        Returns
        -------
        LogWatcher
            The log watcher object.
        """
        if isinstance(services, str):
            services = [services]

        return LogWatcher(
            cli_bearer=self,
            services=services,
            tail=tail,
            follow=follow,
            no_log_prefix=no_log_prefix,
            timestamps=timestamps,
            since=since,
            until=until,
            stream=stream,
            wait_for_first_log=wait_for_first_log,
            wait_for_logs=wait_for_logs,
            wait_for_logs_timeout=wait_for_logs_timeout,
            log_function=log_function,
            append_to_traceback=append_to_traceback,
            capture_stdout=capture_stdout,
            rich_traceback=rich_traceback,
        )

    def _resolve_exit_action(
        self,
        down_on_exit: Optional[bool],
        stop_on_exit: Optional[bool],
    ) -> Optional[str]:
        """Decide what teardown ``up`` registers: ``"down"``, ``"stop"`` or None.

        When neither argument is given (both ``None``), the deployment's
        ``policy`` decides. An explicit argument is a local override. Passing
        both as True is contradictory and raises.
        """
        if down_on_exit and stop_on_exit:
            raise ValueError("Pass either down_on_exit or stop_on_exit, not both (down already stops the containers).")
        if down_on_exit is None and stop_on_exit is None:
            return TEARDOWN_POLICIES[self.policy].exit_action
        if down_on_exit:
            return "down"
        if stop_on_exit:
            return "stop"
        return None

    async def aup(
        self,
        detach: bool = True,
        down_on_exit: Optional[bool] = None,
        stop_on_exit: Optional[bool] = None,
    ) -> LogRoll:
        """Up the deployment.

        Will call docker-compose up on the deployment.

        Parameters
        ----------
        detach : bool, optional
            Should we run the up command in detached mode, by default True (otherwise you need to
            call it as a task yourself)
        down_on_exit : Optional[bool], optional
            Local override for the teardown registered on context-manager exit.
            ``True`` registers a ``down`` (the stack is fully removed on exit),
            ``False`` registers nothing. ``None`` (the default) follows the
            deployment's ``policy``. Mutually exclusive with ``stop_on_exit``.
        stop_on_exit : Optional[bool], optional
            Local override: ``True`` registers a ``stop`` (containers stopped but
            not removed) on exit. ``None`` (the default) follows the ``policy``.
            Mutually exclusive with ``down_on_exit`` (down already stops them).

        Returns
        -------
        List[str]
            The logs of the up command.
        """
        action = self._resolve_exit_action(down_on_exit, stop_on_exit)

        cli = await self.aretrieve_cli()
        await self.project.abefore_up()
        logs = LogRoll()
        async for log in cli.astream_up(detach=detach):
            logs.append(log)
            self.logger.on_up(log)

        if action == "down":
            self._register_cleanup(self.adown, key="down")
        elif action == "stop":
            self._register_cleanup(self.astop, key="stop")

        return logs

    def up(
        self,
        detach: bool = True,
        down_on_exit: Optional[bool] = None,
        stop_on_exit: Optional[bool] = None,
    ) -> LogRoll:
        """Up the deployment.

        Will call docker-compose up on the deployment.

        Parameters
        ----------
        detach : bool, optional
            Should we run the up command in detached mode, by default True (otherwise you need to
            call it as a task yourself, which is not recommended in sync code)
        down_on_exit : Optional[bool], optional
            Local override for the on-exit teardown: ``True`` downs, ``False``
            does nothing, ``None`` (default) follows the deployment's ``policy``.
            Mutually exclusive with ``stop_on_exit``.
        stop_on_exit : Optional[bool], optional
            Local override: ``True`` stops on exit, ``None`` (default) follows the
            ``policy``. Mutually exclusive with ``down_on_exit``.

        Returns
        -------
        List[str]
            The logs of the up command.
        """

        return unkoil(self.aup, detach=detach, down_on_exit=down_on_exit, stop_on_exit=stop_on_exit)

    async def arestart(
        self,
        services: Union[List[str], str],
        await_health: bool = True,
        await_health_timeout: int = 3,
    ) -> LogRoll:
        """Restarts a service.

        Will call docker-compose restart on the list of services.
        If await_health is True, will await for the health checks of these services to pass.

        Parameters
        ----------
        services : Union[List[str], str], optional
            The list of services to restart, by default None
        await_health : bool, optional
            Should we await for the health checks to pass, by default True
        await_health_timeout : int, optional
            The time to wait for  before checking the health checks (allows the container to
            shutdown), by default 3, is void if await_health is False

        Returns
        -------
        LogRoll
            The logs of the restart command.
        """
        cli = await self.aretrieve_cli()
        if isinstance(services, str):
            services = [services]

        logs = LogRoll()
        async for log in cli.astream_restart(services=services):
            logs.append(log)

        if await_health:
            await asyncio.sleep(await_health_timeout)
            await self.acheck_health(services=services)

        return logs

    def restart(
        self,
        services: Union[List[str], str],
        await_health: bool = True,
        await_health_timeout: int = 3,
    ) -> LogRoll:
        """Restarts a service. (sync)

        Will call docker-compose restart on the list of services.
        If await_health is True, will await for the health checks of these services to pass.

        Parameters
        ----------
        services : Union[List[str], str], optional
            The list of services to restart, by default None
        await_health : bool, optional
            Should we await for the health checks to pass, by default True
        await_health_timeout : int, optional
            The time to wait for  before checking the health checks (allows the container to
            shutdown), by default 3, is void if await_health is False

        Returns
        -------
        List[str]
            The logs of the restart command.
        """
        return unkoil(
            self.arestart,
            services=services,
            await_health=await_health,
            await_health_timeout=await_health_timeout,
        )

    async def apull(self) -> LogRoll:
        """Pull the deployment.

        Will call docker-compose pull on the deployment.

        Returns
        -------
        List[str]
            The logs of the pull command.

        Raises
        ------
        NotInitializedError
            If the deployment has not been initialized.
        """
        cli = await self.aretrieve_cli()
        await self.project.abefore_pull()

        logs = LogRoll()
        async for log in cli.astream_pull():
            logs.append(log)

        return logs

    def pull(self) -> LogRoll:
        """Pull the deployment.

        Will call docker-compose pull on the deployment.
        Returns
        -------
        List[str]
            The logs of the pull command.
        Raises
        ------
        NotInitializedError
            If the deployment has not been initialized.
        """
        return unkoil(self.apull)

    async def adown(
        self,
        timeout: Optional[int] = None,
        volumes: Optional[bool] = None,
        remove_orphans: Optional[bool] = None,
    ) -> LogRoll:
        """Down the deployment.

        Will call docker-compose down on the deployment.
        This runs automatically on context exit if you started the stack with
        ``up(down_on_exit=True)``.

        Parameters
        ----------
        timeout : Optional[int], optional
            Grace period in seconds (docker's `-t`) before unresponsive containers are
            SIGKILLed. Defaults to the deployment's ``shutdown_timeout`` when not given.
        volumes : Optional[bool], optional
            Should we remove volumes. Defaults to ``remove_volumes_on_down``.
        remove_orphans : Optional[bool], optional
            Should we remove orphans. Defaults to ``remove_orphans_on_down``.

        Returns
        -------
        List[str]
            The logs of the down command.
        """
        cli = await self.aretrieve_cli()
        await self.project.abefore_down()
        if timeout is None:
            timeout = self.shutdown_timeout
        if volumes is None:
            volumes = self.remove_volumes_on_down
        if remove_orphans is None:
            remove_orphans = self.remove_orphans_on_down

        logs = LogRoll()
        async for log in cli.astream_down(timeout=timeout, volumes=volumes, remove_orphans=remove_orphans):
            logs.append(log)
            self.logger.on_down(log)

        return logs

    async def aremove(self) -> None:
        """Tear down the project.

        Calls the project's ``atear_down`` (e.g. removing a CopyPathProject temp
        dir). This also runs automatically on context exit for any project that
        was initialized inside the block, so you only need to call it for manual,
        out-of-context teardown.
        """
        cli = await self.aretrieve_cli()

        return await self.project.atear_down(cli)

    def remove(self) -> None:
        """Remove the project

        Returns
        -------
        List[str]
            The logs of the down command.
        """
        return unkoil(self.aremove)

    def down(
        self,
        timeout: Optional[int] = None,
        volumes: Optional[bool] = None,
        remove_orphans: Optional[bool] = None,
    ) -> LogRoll:
        """Down the deployment.

        Will call docker-compose down on the deployment.
        This runs automatically on context exit if you started the stack with
        ``up(down_on_exit=True)``.

        Parameters
        ----------
        timeout : Optional[int], optional
            Grace period in seconds (docker's `-t`) before unresponsive containers are
            SIGKILLed. Defaults to the deployment's ``shutdown_timeout`` when not given.
        volumes : Optional[bool], optional
            Should we remove volumes. Defaults to ``remove_volumes_on_down``.
        remove_orphans : Optional[bool], optional
            Should we remove orphans. Defaults to ``remove_orphans_on_down``.

        Returns
        -------
        List[str]
            The logs of the down command.
        """
        return unkoil(self.adown, timeout=timeout, volumes=volumes, remove_orphans=remove_orphans)

    async def astop(self, timeout: Optional[int] = None) -> LogRoll:
        """Stop the deployment.

        Will call docker-compose stop on the deployment.
        This runs automatically on context exit if you started the stack with
        ``up(stop_on_exit=True)``.

        Parameters
        ----------
        timeout : Optional[int], optional
            Grace period in seconds (docker's `-t`) before unresponsive containers are
            SIGKILLed. Defaults to the deployment's ``shutdown_timeout`` when not given.

        Returns
        -------
        List[str]
            The logs of the stop command.
        """
        cli = await self.aretrieve_cli()
        await self.project.abefore_stop()
        if timeout is None:
            timeout = self.shutdown_timeout

        logs = LogRoll()
        async for log in cli.astream_stop(timeout=timeout):
            logs.append(log)
            self.logger.on_stop(log)

        return logs

    def stop(self, timeout: Optional[int] = None) -> LogRoll:
        """Stop the deployment.

        Will call docker-compose stop on the deployment.
        This runs automatically on context exit if you started the stack with
        ``up(stop_on_exit=True)``.

        Parameters
        ----------
        timeout : Optional[int], optional
            Grace period in seconds (docker's `-t`) before unresponsive containers are
            SIGKILLed. Defaults to the deployment's ``shutdown_timeout`` when not given.

        Returns
        -------
        List[str]
            The logs of the stop command.
        """
        return unkoil(self.astop, timeout=timeout)

    async def aget_cli(self) -> CLI:
        """Get the CLI object of the deployment.

        THis is the defining method of a CLI bearer, and will
        be called by any method that needs the CLI object.
        This is an async method because initializing the CLI object
        is an async operation (as it might incure network calls).
        """
        return await self.aretrieve_cli()

    async def __aenter__(self) -> Self:
        """Async enter method for the deployment.

        Entering does nothing on its own: no initialize, inspect, pull, up or
        health-check happens here. You drive the lifecycle from inside the block
        by calling the methods you need (``pull``, ``up``, ``inspect``,
        ``check_health``, ...). Commands that create resources register their own
        teardown (e.g. ``up(down_on_exit=True)``, or project initialization which
        auto-registers a tear-down of any temp dir it created), so exit cleans up
        exactly what the body started.
        """
        self._entered = True
        self._cleanup_stack = []
        self._registered_keys = set()
        return self

    async def _arun_teardown(self) -> None:
        """Run the registered on-exit teardown steps.

        Cleanups registered by the body (``up(down_on_exit=True)``, project
        initialization, ...) are run in LIFO order, so the last resource created
        is the first torn down. Factored out of ``__aexit__`` so it can be
        wrapped in an overall ``teardown_timeout`` guard.
        """
        while self._cleanup_stack:
            cleanup = self._cleanup_stack.pop()
            await cleanup()

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Async exit method for the deployment.

        Will run every teardown the body registered (``up(down_on_exit=True)``,
        project initialization, ...) in LIFO order.

        Teardown is bounded: every ``stop``/``down`` carries the
        ``shutdown_timeout`` grace period, and the whole sequence is wrapped in
        an optional ``teardown_timeout`` wall-clock guard so an unresponsive
        container cannot block the context exit forever. A teardown failure is
        raised as a ``TearDownError``/``CommandError`` when the block is exiting
        cleanly, but only logged (never raised) when another exception is
        already propagating, so it cannot mask the original error.
        """
        try:
            if self.teardown_timeout is not None:
                await asyncio.wait_for(self._arun_teardown(), timeout=self.teardown_timeout)
            else:
                await self._arun_teardown()
        except asyncio.TimeoutError as e:
            message = f"Tearing the deployment down timed out after {self.teardown_timeout}s. docker compose did not finish in time and the docker daemon may still be completing the operation in the background. Consider lowering `shutdown_timeout` so unresponsive containers are killed sooner."
            if exc_type is not None:
                logger.warning("%s (while another error was propagating, not raising)", message)
            else:
                raise TearDownError(message) from e
        except CommandError as e:
            if exc_type is not None:
                logger.warning("Deployment teardown failed (while another error was propagating, not raising): %s", e)
            else:
                raise
        finally:
            self._cleanup_stack = []
            self._registered_keys = set()
            self._entered = False
            self._cli = None
