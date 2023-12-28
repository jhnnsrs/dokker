from pydantic import BaseModel, Field
from python_on_whales import DockerClient, docker
from typing import Any, Coroutine, Optional, List, Protocol, runtime_checkable
from httpx import AsyncClient
import time
from koil.composition import KoiledModel
import asyncio
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from python_on_whales.client_config import ClientConfig, to_list
from dokker.helpers import ayield_docker_logs
from dokker.project import Project
from typing import Union, Callable
from koil import unkoil


class HealthError(Exception):
    pass


class HealthCheck(BaseModel):
    url: str
    service: str
    max_retries: int = 3
    timeout: int = 10
    error_with_logs: bool = True


@runtime_checkable
class LogForward(Protocol):
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


class PrintLogger(LogForward):
    def on_pull(self, log: str):
        print(log)

    def on_up(self, log: str):
        print(log)

    def on_stop(self, log: str):
        print(log)

    def on_logs(self, log: str):
        print(log)

    def on_down(self, log: str):
        print(log)


class Logger(BaseModel):
    logger: logging.Logger = Field(default_factory=lambda: logging.getLogger(__name__))
    log_level: int = logging.INFO

    def on_pull(self, log: str):
        self.logger.log(self.log_level, log)

    def on_up(self, log: str):
        self.logger.log(self.log_level, log)

    def on_stop(self, log: str):
        self.logger.log(self.log_level, log)

    def on_logs(self, log: str):
        self.logger.log(self.log_level, log)

    def on_down(self, log: str):
        self.logger.log(self.log_level, log)

    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True


class LogWatcher(KoiledModel):
    tail: Optional[str] = None
    follow: bool = True
    no_log_prefix: bool = False
    timestamps: bool = False
    since: Optional[str] = None
    until: Optional[str] = None
    stream: bool = True
    services: Union[str, List[str]] = ([],)
    client: DockerClient
    wait_for_first_log: bool = True
    wait_for_logs: bool = False
    wait_for_logs_timeout: int = 10
    collected_logs: List[str] = []
    log_function: Optional[Callable] = print

    _watch_task: Optional[asyncio.Task] = None
    _just_one_log: Optional[asyncio.Future] = None

    async def aon_logs(self, log: str):
        if self.log_function:
            if asyncio.iscoroutinefunction(self.log_function):
                await self.log_function(log)
            else:
                self.log_function(log)

    async def awatch_logs(self):
        async for log in ayield_docker_logs(
            self.client.client_config,
            tail=self.tail,
            follow=self.follow,
            no_log_prefix=self.no_log_prefix,
            timestamps=self.timestamps,
            since=self.since,
            until=self.until,
            services=self.services,
        ):
            print(log)
            if self._just_one_log is not None and not self._just_one_log.done():
                self._just_one_log.set_result(True)
            await self.aon_logs(log)
            self.collected_logs.append(log)

    async def __aenter__(self):
        self.collected_logs = []
        self._just_one_log = asyncio.Future()
        self._watch_task = asyncio.create_task(self.awatch_logs())

        if self.wait_for_first_log:
            await self._just_one_log

        self._just_one_log = asyncio.Future()

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.wait_for_logs:
            if self._just_one_log is not None:
                await asyncio.wait_for(self._just_one_log, self.wait_for_logs_timeout)

        if self._watch_task is not None:
            self._watch_task.cancel()

            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass

        self._watch_task = None

    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True


class Service(BaseModel):
    name: str


class Setup(KoiledModel):
    project: Project = Field(default_factory=Project)
    services: Optional[List[str]] = None

    health_checks: List[HealthCheck] = []
    pull_on_enter: bool = False
    up_on_enter: bool = True
    health_on_enter: bool = False
    down_on_exit: bool = False
    stop_on_exit: bool = True
    threadpool_workers: int = 3

    pull_logs: Optional[List[str]] = None
    up_logs: Optional[List[str]] = None
    stop_logs: Optional[List[str]] = None

    logger: LogForward = Field(default_factory=Logger)

    _client: DockerClient
    _threadpool: Optional[ThreadPoolExecutor] = None

    def fetch_service_logs(self, name: str):
        logs = []
        for type, log in self._client.compose.logs(services=[name], stream=True):
            logs.append(log.decode("utf-8"))
            self.logger.on_logs(log.decode("utf-8"))

        return logs

    def afetch_service_logs(self, name: str):
        return self.arun_in_threadpool(self.fetch_service_logs, name)

    async def arequest(
        self, service_name: str, private_port: int = None, path: str = "/"
    ):
        async with AsyncClient() as client:
            try:
                response = await client.get(f"http://127.0.0.1:{private_port}{path}")
                assert response.status_code == 200
                return response
            except Exception as e:
                raise AssertionError(f"Health check failed: {e}")

    def request(self, service_name: str, private_port: int = None, path: str = ""):
        return unkoil(self.arequest, service_name, private_port=private_port, path=path)

    async def acheck_healthz(self, check: HealthCheck, retry: int = 0):
        try:
            async with AsyncClient() as client:
                try:
                    response = await client.get(check.url)
                    assert response.status_code == 200
                    return response
                except Exception as e:
                    raise AssertionError(f"Health check failed: {e}")
        except Exception as e:
            if retry < check.max_retries:
                await asyncio.sleep(check.timeout)
                await self.acheck_healthz(check, retry=retry + 1)
            else:
                if not check.error_with_logs:
                    raise HealthError(
                        f"Health check failed after {check.max_retries} retries. Logs are disabled."
                    ) from e

                logs = await self.afetch_service_logs(check.service)

                raise HealthError(
                    f"Health check failed after {check.max_retries} retries. Logs:\n"
                    + "".join(logs)
                ) from e

    async def await_for_healthz(self, timeout: int = 3, retry: int = 0):
        return await asyncio.gather(
            *[self.acheck_healthz(check) for check in self.health_checks]
        )

    async def arun_in_threadpool(self, func, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._threadpool, func, *args, **kwargs)

    def pull(self):
        logs = []
        for type, log in self._client.compose.pull(stream_logs=True):
            logs.append(log.decode("utf-8"))
            self.logger.on_pull(log.decode("utf-8"))

        return logs

    def up(self):
        logs = []
        for type, log in self._client.compose.up(stream_logs=True, detach=True):
            logs.append(log.decode("utf-8"))
            self.logger.on_up(log.decode("utf-8"))

        return logs

    def stop(self):
        logs = []
        for type, log in self._client.compose.stop(stream_logs=True):
            logs.append(log.decode("utf-8"))
            self.logger.on_stop(log.decode("utf-8"))

        return logs

    def get(self, service_name: str) -> Service:
        return self._client.compose.get(service_name)

    def logswatcher(self, service_name: str, **kwargs):
        return LogWatcher(
            client=self._client, services=[service_name], tail=1, **kwargs
        )

    async def aup(self):
        return await self.arun_in_threadpool(self.up)

    async def apull(self):
        return await self.arun_in_threadpool(self.pull)

    async def astop(self):
        return await self.arun_in_threadpool(self.stop)

    async def __aenter__(self):
        self._threadpool = ThreadPoolExecutor(max_workers=self.threadpool_workers)

        self._client = DockerClient(
            **await self.project.aget_client_params(),
        )

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
        self._client = None

    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True
