from pydantic import BaseModel, Field
from typing import Optional, List, Protocol, runtime_checkable
from koil.composition import KoiledModel
import asyncio
from pathlib import Path
from dokker.compose_spec import ComposeSpec
from dokker.project import Project
from typing import Union
from koil import unkoil
from dokker.cli import CLI
from dokker.loggers.void import VoidLogger
from .log_watcher import LogWatcher
import aiohttp
import certifi
from ssl import SSLContext
import ssl
from dokker.errors import NotInitializedError, NotInspectedError


ValidPath = Union[str, Path]


class HealthError(Exception):
    pass


class HealthCheck(BaseModel):
    url: str
    service: str
    max_retries: int = 3
    timeout: int = 10
    error_with_logs: bool = True
    headers: Optional[dict] = Field(default_factory=lambda: {"Content-Type": "application/json"})
    ssl_context: SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where()),
        description="SSL Context to use for the request",
    )

    async def acheck(self):
        async with aiohttp.ClientSession(
                headers=self.headers,
                connector=aiohttp.TCPConnector(ssl=self.ssl_context),
            ) as session:
                # get json from endpoint
                async with session.get(self.url) as resp:
                    assert resp.status == 200
                    return await resp.text()
                
    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True
                

@runtime_checkable
class Logger(Protocol):
    def on_pull(self, log: str):
        ...

    def on_up(self, log: str):
        ...

    def on_stop(self, log: str):
        ...

    def on_logs(self, log: str):
        ...

    def on_down(self, log: str):
        ...




class Deployment(KoiledModel):
    """A deployment is a set of services that are deployed together."""

    project: Project = Field(default_factory=Project)
    services: Optional[List[str]] = None

    health_checks: List[HealthCheck] = Field(default_factory=list)
    initialize_on_enter: bool = True
    inspect_on_enter: bool = True
    pull_on_enter: bool = False
    up_on_enter: bool = True
    health_on_enter: bool = False
    down_on_exit: bool = False
    stop_on_exit: bool = True
    tear_down_on_exit: bool = False
    threadpool_workers: int = 3

    pull_logs: Optional[List[str]] = None
    up_logs: Optional[List[str]] = None
    stop_logs: Optional[List[str]] = None

    auto_initialize: bool = True

    logger: Logger = Field(default_factory=VoidLogger)

    _spec: ComposeSpec
    _cli: CLI
    

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
            raise NotInspectedError(
                "Deployment not inspected. Call await deployment.ainspect() first."
            )
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
        if self._cli is None:
            if self.auto_initialize:
                await self.ainititialize()
            else:
                raise NotInitializedError(
                    "Deployment not initialized and auto_initialize is False. Call await deployment.ainitialize() first."
                )

        self._spec = await self._cli.ainspect_config()
        return self._spec

    def add_health_check(
        self,
        url: str,
        service: str,
        max_retries: int = 3,
        timeout: int = 10,
        error_with_logs: bool = True,
    ) -> "HealthCheck":
        """Add a health check to the deployment.

        Parameters
        ----------
        url : str
            The url to check.
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


    async def acheck_healthz(self, check: HealthCheck, retry: int = 0):

        try:
            await check.acheck()
        except Exception as e:
            if retry < check.max_retries:
                await asyncio.sleep(check.timeout)
                await self.acheck_healthz(check, retry=retry + 1)
            else:
                if not check.error_with_logs:
                    raise HealthError(
                        f"Health check failed after {check.max_retries} retries. Logs are disabled."
                    ) from e

                logs = []
                
                async for std, i in  self._cli.astream_docker_logs(check.service):
                    logs.append(i)

                raise HealthError(
                    f"Health check failed after {check.max_retries} retries. Logs:\n"
                    + "\n".join(logs)
                ) from e

    async def await_for_healthz(
        self, timeout: int = 3, retry: int = 0, services: Optional[List[str]] = None
    ):
        if services is None:
            services = [
                check.service for check in self.health_checks
            ]  # we check all services

        return await asyncio.gather(
            *[
                self.acheck_healthz(check)
                for check in self.health_checks
                if check.service in services
            ]
        )

    def logswatcher(self, service_names: Union[List[str], str], **kwargs):
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
        if isinstance(service_names, str):
            service_names = [service_names]

        return LogWatcher(cli_bearer=self, services=service_names, tail=1, **kwargs)

    async def aup(self, detach=True):
        """Up the deployment.

        Will call docker-compose up on the deployment.
        This method is called automatically when using the deployment as a context manager and
        if up_on_enter is True.

        Returns
        -------
        List[str]
            The logs of the up command.
        """

        logs = []
        async for type, log in self._cli.astream_up(detach=detach):
            logs.append(log)
            self.logger.on_stop(log)

        return logs

    async def arestart(
        self, services: Union[List[str], str], await_health: bool =True, await_health_timeout: int =3
    ):
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
        List[str]
            The logs of the restart command.
        """

        if isinstance(services, str):
            services = [services]

        logs = []
        async for type, log in self._cli.astream_restart(services=services):
            logs.append(log)

        if await_health:
            await asyncio.sleep(await_health_timeout)
            await self.await_for_healthz(services=services)

        return logs

    def restart(
        self, services: Union[List[str], str], await_health: bool =True, await_health_timeout: int =3
    ):
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

    async def apull(self):
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
        if self._cli is None:
            raise NotInitializedError(
                "Deployment not initialized. Call await deployment.ainitialize() first."
            )
        

        logs = []
        async for type, log in self._cli.astream_pull(stream_logs=True, detach=True):
            logs.append(log)
            self.logger.on_pull(log)

        return logs

    async def adown(self) -> List[str]:
        """Down the deployment.
        
        Will call docker-compose down on the deployment.
        This method is called automatically when using the deployment as a context manager and
        if down_on_exit is True.

        Returns
        -------
        List[str]
            The logs of the down command.
        """
        if self._cli is None:
            raise NotInitializedError(
                "Deployment not initialized. Call await deployment.ainitialize() first."
            )

        logs = []
        async for type, log in self._cli.astream_down():
            logs.append(log)
            self.logger.on_down(log)

        return logs

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
        if self._cli is None:
            raise NotInitializedError(
                "Deployment not initialized. Call await deployment.ainitialize() first."
            )

        logs = []
        async for type, log in self._cli.astream_stop():
            logs.append(log)
            self.logger.on_stop(log)

        return logs

    async def aget_cli(self):
        """Get the CLI object of the deployment.

        THis is the defining method of a CLI bearer, and will
        be called by any method that needs the CLI object.
        This is an async method because initializing the CLI object
        is an async operation (as it might incure network calls).
        """
        assert (
            self._cli is not None
        ), "Deployment not initialized. Call await deployment.ainitialize() first."
        return self._cli

    async def __aenter__(self) -> "Deployment":
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

    async def __aexit__(self, exc_type, exc_val, exc_tb):
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

    class Config:
        """ Pydantic configuration for the deployment."""
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True
