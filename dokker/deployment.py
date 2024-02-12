from pydantic import BaseModel, Field
from typing import Dict, Optional, List, Protocol, runtime_checkable
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
from typing import Any, Optional, List, Union
from dokker.errors import NotInitializedError, NotInspectedError
from pydantic import validator
from dokker.loggers.logging import LoggingLogger
from dokker.types import ValidPath, LogHelper, Logger
from typing import TypeVar, Generic

class HealthError(Exception):
    pass




T = TypeVar("T", bound="BaseModel")



class Deployment(KoiledModel, Generic[T]):
    """A deployment is a set of services that are deployed together."""

    project: Project = Field(default_factory=Project)
    services: Optional[List[str]] = None

    initialize_on_enter: bool = False
    inspect_on_enter: bool = False
    pull_on_enter: bool = False
    up_on_enter: bool = False
    health_on_enter: bool = False
    down_on_exit: bool = False
    stop_on_exit: bool = False
    tear_down_on_exit: bool = False

    pull_logs: Optional[List[str]] = None
    up_logs: Optional[List[str]] = None
    stop_logs: Optional[List[str]] = None

    auto_initialize: bool = True

    logger: Logger = Field(default_factory=LoggingLogger)
    log_to_stdout: bool = False

    

    _spec: ComposeSpec = None
    _cli: CLI = None



    async def ainitialize(self, **kwargs) -> "CLI":
        """Initialize the deployment.

        Will initialize the deployment through its project and return the CLI object.
        This method is called automatically when using the deployment as a context manager.

        Returns
        -------
        CLI
           The CLI object.
        """
        async with self.logger.status("Initializing") as helper:
            self._cli = await self.project.ainititialize(helper,  **kwargs)
        return self._cli

    async def aget_config(self) -> T:
        return await self.project.aget_config(self.logger)
    
    def get_config(self) -> T:
        return unkoil(self.aget_config)
    
    def initialize(self,  **kwargs) -> "CLI":
        return unkoil(self.ainitialize,  **kwargs)

    async def aretrieve_cli(self):
        return await self.project.aget_cli(self.logger)

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
        return unkoil(self.ainspect)


    async def acheck_health(self, services: Optional[List[str]] = None):
        
        async with self.logger.status("Health checks") as helper:
            health_checks = await self.project.aget_health_checks()

            if services is not None:
                health_checks = [
                    check for check in health_checks if check.service in services
                ]  # we check all services

            return await asyncio.gather(
                *[
                    check.acheck(helper)
                    for check in health_checks
                ]
            )

    def check_health(self, services: Optional[List[str]] = None):
        return unkoil(self.acheck_health, services=services)

    def watch_logs(self, service_names: Union[List[str], str], **kwargs):
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
        cli = await self.aretrieve_cli()
        logs = []
        async with self.logger.status("Up") as helper:
            async for type, log in cli.astream_up(detach=detach):
                logs.append(log)
                await helper.alog(log)

        return logs

    def up(self, detach=True):
        """Up the deployment.

        Will call docker-compose up on the deployment.
        This method is called automatically when using the deployment as a context manager and
        if up_on_enter is True.

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
        cli = await self.aretrieve_cli()
        if isinstance(services, str):
            services = [services]

        logs = []
        async with self.logger.status("Restarting") as helper:
            async for type, log in cli.astream_restart(services=services):
                await helper.alog(log)

        if await_health:
            await asyncio.sleep(await_health_timeout)
            await self.await_for_healthz(services=services)

        return logs

    def restart(
        self,
        services: Union[List[str], str],
        await_health: bool = True,
        await_health_timeout: int = 3,
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
        cli = await self.aretrieve_cli()

        logs = []
        async with self.logger.status("Pulling") as helper:
            async for type, log in cli.astream_pull():
                logs.append(log)
                await helper.alog(log)

        return logs
    
    def pull(self):
        unkoil(self.apull)

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
        cli = await self.aretrieve_cli()

        logs = []
        async with self.logger.status("Down") as helper:
            async for type, log in cli.astream_down():
                logs.append(log)
                await helper.alog(log)

        return logs

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

    async def aremove(self, down_before_remove: bool=True) -> None:
        """Down the deployment.

        Will remove the deployment.

        Parameters
        ----------
        down_before_remove : bool, optional
            Should we call down before removing the deployment, by default True
            If set to false, the deployment will be removed without calling down.
            Which could lead to orphaned containers, networks, etc. Only deactivate this
            if you know what you are doing.

        Returns
        -------
        List[str]
            The logs of the down command.
        """

        if down_before_remove:
            try:
                await self.adown()
            except Exception as e:
                pass



        async with self.logger.status("Removing") as helper:
            return await self.project.atear_down(helper)

    def remove(self, down_before_remove: bool = True) -> None:
        """Remove the project

        Will remove the deployment.

        Parameters
        ----------
        down_before_remove : bool, optional
            Should we call down before removing the deployment, by default True
            If set to false, the deployment will be removed without calling down.
            Which could lead to orphaned containers, networks, etc. Only deactivate this
            if you know what you are doing.

        Returns
        -------
        List[str]
            The logs of the down command.
        """



        return unkoil(self.aremove, down_before_remove=down_before_remove)

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

        logs = []
        async with self.logger.status("Stop") as helper:
            async for type, log in cli.astream_stop():
                logs.append(log)
                await helper.alog(log)

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

    async def aget_cli(self):
        """Get the CLI object of the deployment.

        THis is the defining method of a CLI bearer, and will
        be called by any method that needs the CLI object.
        This is an async method because initializing the CLI object
        is an async operation (as it might incure network calls).
        """
        return await self.aretrieve_cli()

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
        """Pydantic configuration for the deployment."""

        arbitrary_types_allowed = True
        underscore_attrs_are_private = True
