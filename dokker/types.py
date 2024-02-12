from typing import Union, AsyncIterator, Tuple, Protocol, runtime_checkable
from pathlib import Path

ValidPath = Union[str, Path]
LogStream = AsyncIterator[Tuple[str, str]]


@runtime_checkable
class LogHelper(Protocol):
    async def alog(self, log: str):
        ...

    async def ainfo(self, log: str):
        ...

    async def aerror(self, log: str):
        ...

    async def awarning(self, log: str):
        ...

    async def adebug(self, log: str):
        ...

    async def __aenter__(self):
        ...

    async def __aexit__ (self, *args, **kwargs):
        ...


@runtime_checkable
class Logger(Protocol):
    def status(self, log: str) -> LogHelper:
        ...


@runtime_checkable
class HealthCheck(Protocol):
    name: str
    service: str
    


    async def acheck(self, log: LogHelper) -> bool:
        ...