from pydantic import BaseModel, Field
from typing import Any, Coroutine, Optional, List, Protocol, runtime_checkable
import aiohttp
import time
from koil.composition import KoiledModel
import asyncio
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from dokker.compose_spec import ComposeSpec
from dokker.project import Project
from dokker.projects.local import LocalProject
from typing import Union, Callable
from koil import unkoil
from dokker.cli import CLI
import traceback
from dokker.loggers.print import PrintLogger
from dokker.loggers.void import VoidLogger
from .log_watcher import LogWatcher


ValidPath = Union[str, Path]


class HealthError(Exception):
    pass


class HealthCheck(BaseModel):
    url: Union[str, Callable[[ComposeSpec], str]]
    service: str
    max_retries: int = 3
    timeout: int = 10
    error_with_logs: bool = True


@runtime_checkable
class Logger(Protocol):
    def on_pull(self, log: str): ...

    def on_up(self, log: str): ...

    def on_stop(self, log: str): ...

    def on_logs(self, log: str): ...

    def on_down(self, log: str): ...


class Deployment(KoiledModel):
    """A deployment is a set of services that are deployed together."""

    project: Project = Field(default_factory=LocalProject)
    services: Optional[List[str]] = None

    health_checks: List[HealthCheck] = Field(default_factory=list)
    inspect_on_enter: bool = True
    pull_on_enter: bool = False
    up_on_enter: bool = True
    health_on_enter: bool = False
    down_on_exit: bool = False
    stop_on_exit: bool = True
    threadpool_workers: int = 3

    pull_logs: Optional[List[str]] = None
    up_logs: Optional[List[str]] = None
    stop_logs: Optional[List[str]] = None

    logger: Logger = Field(default_factory=PrintLogger)

    _spec: ComposeSpec
    _cli: CLI

    @property
    def spec(self) -> ComposeSpec:
        if self._spec is None:
            raise Exception(
                "Deployment not inspected and inspect_on_enter set to false. Call await deployment.ainspect() first or set inspect_on_enter to true"
            )
        return self._spec

    async def ainititialize(self) -> "CLI":
        self._cli = await self.project.ainititialize()
        return self._cli

    async def ainspect(self) -> ComposeSpec:
        if self._cli is None:
            await self.ainititialize()

        self._spec = await self._cli.ainspect_config()
        return self._spec

    def inspect(self) -> ComposeSpec:
        return unkoil(self.ainspect)

    def add_health_check(
        self,
        url: Union[str, Callable[[ComposeSpec], str]] = None,
        service: str = None,
        max_retries: int = 3,
        timeout: int = 10,
        error_with_logs: bool = True,
        check: HealthCheck = None,
    ) -> "HealthCheck":
        if check is None:
            check = HealthCheck(
                url=url,
                service=service,
                max_retries=max_retries,
                timeout=timeout,
                error_with_logs=error_with_logs,
            )

        self.health_checks.append(check)
        return check

    async def arequest(
        self, service_name: str, private_port: int = None, path: str = "/"
    ):
        async with aiohttp.AsyncClient() as client:
            try:
                response = await client.get(f"http://127.0.0.1:{private_port}{path}")
                assert response.status_code == 200
                return response
            except Exception as e:
                raise AssertionError(f"Health check failed: {e}")

    def request(self, service_name: str, private_port: int = None, path: str = ""):
        return unkoil(self.arequest, service_name, private_port=private_port, path=path)

    async def acheck_healthz(self, check: HealthCheck, retry: int = 0):

        if not self._spec:
            await self.ainspect()

        try:
            async with aiohttp.AsyncClient() as client:

                url = check.url if isinstance(check.url, str) else check.url(self._spec)

                try:
                    response = await client.get(url)
                    assert response.status_code == 200
                    return response
                except Exception as e:
                    raise AssertionError(f"Health check failed: {e}")
        except Exception as e:
            if retry < check.max_retries:
                await asyncio.sleep(check.timeout)
                await self.acheck_healthz(check, retry=retry + 1)
            else:
                raise HealthError(
                    f"Health check failed after {check.max_retries} retries. Logs are disabled."
                ) from e

    async def await_for_healthz(
        self, services: List[str] = None
    ) -> List[aiohttp.ClientResponse]:
        """Wait for all health checks to succeeed

        Args:
            services (List[str], optional): The services to filter by. Defaults to None.

        Returns:
            List[aiohttp.ClientResponse]: The reponses of all servics
        """
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

    def create_watcher(self, service_name: str, **kwargs):
        """Create a Log Watcher

        Creates a log watcher that is bound to this deployments project,
        a log watcher allows you to collect the logs of a service during
        its context:

        Usage:
         ```python

         deployment = Deployment(compose_file="docker_compose.yaml")

         watcher = deployment.create_watcher("the_service_to_watch")

         with deployment:

              with watcher:

                   # Do something interacting with the service
                   # requests.qt()

              print(watcher.collected_logs)


        Args:
            service_name (str): _description_

        Returns:
            _type_: _description_
        """
        return LogWatcher(cli_bearer=self, services=[service_name], tail=1, **kwargs)

    async def aup(self):
        logs = []
        async for type, log in self._cli.astream_up(stream_logs=True, detach=True):
            logs.append(log)
            self.logger.on_stop(log)

        return logs

    async def arestart(
        self, services: List[str] = None, await_health=True, await_health_timeout=3
    ):
        logs = []
        async for type, log in self._cli.astream_restart(services=services):
            logs.append(log)

        if await_health:
            await asyncio.sleep(await_health_timeout)
            await self.await_for_healthz(services=services)

        return logs

    def restart(
        self, services: List[str] = None, await_health=True, await_health_timeout=3
    ):
        return unkoil(
            self.arestart,
            services=services,
            await_health=await_health,
            await_health_timeout=await_health_timeout,
        )

    async def apull(self):
        logs = []
        async for type, log in self._cli.astream_pull(stream_logs=True, detach=True):
            logs.append(log)
            self.logger.on_pull(log)

        return logs

    async def adown(self):
        logs = []
        async for type, log in self._cli.astream_pull(stream_logs=True, detach=True):
            logs.append(log)
            self.logger.on_pull(log)

        return logs

    def up(self, *args, **kwargs):
        return unkoil(self, *args, **kwargs)

    async def astop(self):
        logs = []
        async for type, log in self._cli.astream_stop():
            logs.append(log)
            self.logger.on_stop(log)

        return logs

    async def aget_cli(self):
        assert (
            self._cli is not None
        ), "Deployment not initialized. Call await deployment.ainitialize() first."
        return self._cli

    async def __aenter__(self):

        await self.ainititialize()

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
        if self.stop_on_exit:
            await self.project.abefore_stop()
            await self.astop()

        if self.down_on_exit:
            await self.project.abefore_down()
            await self.adown()

        self._cli = None

    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True
