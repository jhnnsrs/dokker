from pydantic import BaseModel, Field
from python_on_whales import DockerClient, docker
from typing import Optional, List, Protocol, runtime_checkable
from httpx import AsyncClient
import time
from koil.composition import KoiledModel
import asyncio
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from dokker.project import Project


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


class Setup(KoiledModel):
    project: Project = Field(default_factory=Project)
    services: Optional[List[str]] = None

    ht_checks: List[HealthCheck] = []
    pull_on_enter: bool = False
    down_on_exit: bool = False
    threadpool_workers: int = 1

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
            *[self.acheck_healthz(check) for check in self.ht_checks]
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

    async def aup(self):
        return await self.arun_in_threadpool(self.up)

    async def apull(self):
        return await self.arun_in_threadpool(self.pull)

    async def astop(self):
        return await self.arun_in_threadpool(self.stop)

    async def __aenter__(self):
        self._threadpool = ThreadPoolExecutor(max_workers=self.threadpool_workers)

        self._client = DockerClient(
            compose_files=[str(i) for i in self.project.compose_files],
        )

        if self.pull_on_enter:
            await self.project.abefore_pull()
            await self.apull()

        await self.project.abefore_up()
        await self.aup()

        if self.ht_checks:
            await self.await_for_healthz()

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.project.abefore_stop()
        await self.astop()

        if self.down_on_exit:
            await self.project.abefore_down()
            await self.adown()
        self._client = None

    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True
