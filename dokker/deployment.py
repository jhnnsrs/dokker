from types import TracebackType
import aiohttp.client_exceptions
import aiohttp.http_exceptions
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Protocol, Self, Type, runtime_checkable
from koil.composition import KoiledModel
import asyncio
from pathlib import Path
from dokker.compose_spec import ComposeSpec
from dokker.project import Project
from typing import Union
from koil import unkoil
from dokker.cli import CLI
from dokker.loggers.void import VoidLogger
from .log_watcher import LogRoll, LogWatcher
import aiohttp
import certifi
from ssl import SSLContext
import ssl
from typing import Any, Optional, List, Union, Callable
from dokker.errors import NotInitializedError, NotInspectedError, HealthCheckError


ValidPath = Union[str, Path]


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
    error_with_logs: bool = Field(default=True, description="Should we error with the logs of the service (will inspect container logs of the service).")
    headers: Optional[dict] = Field(default_factory=lambda: {"Content-Type": "application/json"}, description="Headers to use for the request")
    ssl_context: SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where()),
        description="SSL Context to use for the request",
    )
    valid_statuses: list[int] = Field(default_factory=lambda: [200], description="The valid statuses for the health check. Defaults to 200.")

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

    health_checks: List[HealthCheck] = Field(default_factory=list, description="A list of health checks to run on the deployment. These are run when the deployment is up and running.")
    initialize_on_enter: bool = Field(default=False, description="Should we initialize the deployment when entering the context manager.")
    inspect_on_enter: bool = Field(default=False, description="Should we inspect the deployment when entering the context manager.")
    pull_on_enter: bool = Field(default=False, description="Should we pull the deployment when entering the context manager.")
    up_on_enter: bool = Field(default=False, description="Should we up the deployment when entering the context manager.")
    health_on_enter: bool = Field(default=False, description="Should we check the health of the deployment when entering the context manager.")
    down_on_exit: bool = Field(default=False, description="Should we down the deployment when exiting the context manager.")
    stop_on_exit: bool = Field(default=False, description="Should we stop the deployment when exiting the context manager.")
    tear_down_on_exit: bool = Field(default=False, description="Should we tear down the deployment when exiting the context manager.")
    threadpool_workers: int = Field(default=10, description="The number of workers to use for the threadpool. This is used for the health checks and the log watcher.")

    pull_logs: Optional[List[str]] = Field(default=None, description="The logs of the pull command. Will be set when the deployment is pulled.")
    up_logs: Optional[List[str]] = Field(default=None, description="The logs of the up command. Will be set when the deployment is up.")
    stop_logs: Optional[List[str]] = Field(default=None, description="The logs of the stop command. Will be set when the deployment is stopped.")

    auto_initialize: bool = Field(default=True, description="Should we automatically initialize the deployment when using it as a context manager.")

    logger: Logger = Field(default_factory=VoidLogger)

    _spec: Optional[ComposeSpec] = None
    _cli: Optional[CLI] = None

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
        This method is called automatically when using the deployment as a context manager.

        Returns
        -------
        CLI
           The CLI object.
        """
        self._cli = await self.project.ainititialize()
        return self._cli

    async def aretrieve_cli(self):
        if self._cli is None:
            if self.auto_initialize:
                await self.ainitialize()
            else:
                raise NotInitializedError("Deployment not initialized and auto_initialize is False. Call await deployment.ainitialize() first.")

        return self._cli

    async def ainspect(self) -> ComposeSpec:
        """Inspect the deployment.

        Will inspect the deployment through its project and return the compose spec, which
        can be used to retrieve information about the deployment.
        This method is called automatically when using the deployment as a context manager and
        if inspect_on_enter is True.
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
        This method is called automatically when using the deployment as a context manager and
        if inspect_on_enter is True.

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
            await self.ainspect()

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

                raise HealthCheckError(f"Health check failed after {check.max_retries} retries. Logs:\n" + "\n".join(i for x, i in logs)) from e

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
        log_function: Optional[Callable] = None,
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

    async def aup(self, detach: bool = True) -> LogRoll:
        """Up the deployment.

        Will call docker-compose up on the deployment.
        This method is called automatically when using the deployment as a context manager and
        if up_on_enter is True.

        Parameters
        ----------
        detach : bool, optional
            Should we run the up command in detached mode, by default True (otherwise you need to
            call it as a task yourself)

        Returns
        -------
        List[str]
            The logs of the up command.
        """
        cli = await self.aretrieve_cli()
        logs = LogRoll()
        async for log in cli.astream_up(detach=detach):
            logs.append(log)
            self.logger.on_up(log)

        return logs

    def up(self, detach: bool = True) -> LogRoll:
        """Up the deployment.

        Will call docker-compose up on the deployment.
        This method is called automatically when using the deployment as a context manager and
        if up_on_enter is True.

        Parameters
        ----------
        detach : bool, optional
            Should we run the up command in detached mode, by default True (otherwise you need to
            call it as a task yourself, which is not recommended in sync code)

        Returns
        -------
        List[str]
            The logs of the up command.
        """

        return unkoil(self.aup, detach=detach)

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
            await self.await_for_healthz(services=services)

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
        This method is called automatically when using the deployment as a context manager and
        if pull_on_enter is True.

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

        logs = LogRoll()
        async for log in cli.astream_pull():
            logs.append(log)

        return logs

    def pull(self) -> LogRoll:
        """Pull the deployment.

        Will call docker-compose pull on the deployment.
        This method is called automatically when using the deployment as a context manager and
        if pull_on_enter is True.
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

    async def adown(self) -> LogRoll:
        """Down the deployment.

        Will call docker-compose down on the deployment.
        This method is called automatically when using the deployment as a context manager and
        if down_on_exit is True.

        Returns
        -------
        List[str]
            The logs of the down command.
        """
        cli = await self.aretrieve_cli()

        logs = LogRoll()
        async for log in cli.astream_down():
            logs.append(log)

        return logs

    async def aremove(self) -> None:
        """Down the deployment.

        Will call docker-compose down on the deployment.
        This method is called automatically when using the deployment as a context manager and
        if down_on_exit is True.

        Returns
        -------
        List[str]
            The logs of the down command.
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

    def down(self) -> List[str]:
        """Down the deployment.

        Will call docker-compose down on the deployment.
        This method is called automatically when using the deployment as a context manager and
        if down_on_exit is True.

        Returns
        -------
        List[str]
            The logs of the down command.
        """
        return unkoil(self.adown)

    async def astop(self) -> List[str]:
        """Stop the deployment.

        Will call docker-compose stop on the deployment.
        This method is called automatically when using the deployment as a context manager and
        if stop_on_exit is True.

        Returns
        -------
        List[str]
            The logs of the stop command.
        """
        cli = await self.aretrieve_cli()

        logs = LogRoll()
        async for log in cli.astream_stop():
            logs.append(log)

        return logs

    def stop(self) -> List[str]:
        """Stop the deployment.

        Will call docker-compose stop on the deployment.
        This method is called automatically when using the deployment as a context manager and
        if stop_on_exit is True.

        Returns
        -------
        List[str]
            The logs of the stop command.
        """
        return unkoil(self.astop)

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

        Will initialize the project, if auto_initialize is True.
        Will inspect the deployment, if inspect_on_enter is True.
        Will call docker-compose up and pull on the deployment, if
        up_on_enter and pull_on_enter are True respectively.

        """
        if self.initialize_on_enter:
            await self.ainitialize()

        if self.inspect_on_enter:
            await self.ainspect()

        if self.pull_on_enter:
            await self.project.abefore_pull()
            await self.apull()

        if self.up_on_enter:
            await self.project.abefore_up()
            await self.aup()

        if self.health_on_enter:
            if self.health_checks:
                await self.await_for_healthz()

        return self

    async def __aexit__(self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], traceback: Optional[TracebackType]) -> None:
        """Async exit method for the deployment.

        Will call docker-compose down and stop on the deployment, if
        down_on_exit and stop_on_exit are True respectively.
        """
        if self.stop_on_exit:
            await self.project.abefore_stop()
            await self.astop()

        if self.down_on_exit:
            await self.project.abefore_down()
            await self.adown()

        if self.tear_down_on_exit:
            await self.project.atear_down(self._cli)

        self._cli = None
