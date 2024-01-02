from koil.composition import KoiledModel
import asyncio
from typing import Optional, List, Callable, Union
from dokker.cli import CLI, CLIBearer


try:
    from rich import panel

    def format_log_watcher_message(watcher: "LogWatcher", exc_val, rich=True):
        extra_info = map(
            lambda x: x[1] if x[0] == "STDERR" or watcher.capture_stdout else "",
            watcher.collected_logs,
        )
        # Ensure compatibility with different exception types

        extra_info = "\n".join(extra_info)

        if not rich:
            return f"{str(exc_val)}\n\nDuring the execution Logwatcher captured these logs from the services {watcher.services}:\n{extra_info}"
        else:
            return f"{str(exc_val)}\n\nDuring the execution Logwatcher captured these logs from the services {watcher.services}:\n{extra_info}"

except ImportError:

    def format_log_watcher_message(watcher: "LogWatcher", exc_val, extra_info):
        extra_info = map(
            lambda x: x[1] if x[0] == "STDERR" or watcher.capture_stdout else "",
            watcher.collected_logs,
        )
        # Ensure compatibility with different exception types

        extra_info = "\n".join(extra_info)
        return f"{str(exc_val)}\n\nDuring the execution Logwatcher captured these logs from the services {watcher.services}:\n{extra_info}"


class LogWatcher(KoiledModel):
    cli_bearer: CLIBearer
    tail: Optional[str] = None
    follow: bool = True
    no_log_prefix: bool = False
    timestamps: bool = False
    since: Optional[str] = None
    until: Optional[str] = None
    stream: bool = True
    services: Union[str, List[str]] = ([],)
    wait_for_first_log: bool = True
    wait_for_logs: bool = False
    wait_for_logs_timeout: int = 10
    collected_logs: List[str] = []
    log_function: Optional[Callable] = None
    append_to_traceback: bool = True
    capture_stdout: bool = True
    rich_traceback: bool = True

    _watch_task: Optional[asyncio.Task] = None
    _just_one_log: Optional[asyncio.Future] = None

    async def aon_logs(self, log: str):
        if self.log_function:
            if asyncio.iscoroutinefunction(self.log_function):
                await self.log_function(log)
            else:
                self.log_function(log)

    async def awatch_logs(self):
        cli = await self.cli_bearer.aget_cli()
        async for log in cli.astream_docker_logs(
            tail=self.tail,
            follow=self.follow,
            no_log_prefix=self.no_log_prefix,
            timestamps=self.timestamps,
            since=self.since,
            until=self.until,
            services=self.services,
        ):
            if self._just_one_log is not None and not self._just_one_log.done():
                self._just_one_log.set_result(True)
            await self.aon_logs(log)
            self.collected_logs.append(log)

    def on_watch_task_done(self, task: asyncio.Task):
        if task.cancelled():
            return
        if task.exception():
            raise task.exception()
        if task.done():
            return

    async def __aenter__(self):
        self.collected_logs = []
        self._just_one_log = asyncio.Future()
        self._watch_task = asyncio.create_task(self.awatch_logs())
        self._watch_task.add_done_callback(self.on_watch_task_done)

        if self.wait_for_first_log:
            await self._just_one_log

        self._just_one_log = asyncio.Future()

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None and self.append_to_traceback:
            new_message = format_log_watcher_message(
                self, exc_val, rich=self.rich_traceback
            )
            try:
                new_exc = exc_type(new_message)
            except:
                new_exc = Exception(new_message)

            raise new_exc.with_traceback(exc_tb) from exc_val

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