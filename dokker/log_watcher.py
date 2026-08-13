import inspect
import re
from types import TracebackType
from koil import unkoil
from koil.composition import KoiledModel
import asyncio
from typing import Optional, List, Self, Tuple, Type, Union, Generator
from dokker.cli import CLIBearer
from pydantic import Field

from dokker.errors import LogWatcherTimeoutError
from dokker.types import LogFunction


def format_log_watcher_message(watcher: "LogWatcher", exc_val: Optional[BaseException], rich: bool = True) -> str:
    """Formats the log watcher message for the exception."""
    extra_info = map(
        lambda x: x[1] if x[0] == "STDERR" or watcher.capture_stdout else "",
        watcher.collected_logs,
    )
    # Ensure compatibility with different exception types

    extra_info_str = "\n".join(extra_info)
    return f"{str(exc_val)}\n\nDuring the execution Logwatcher captured these logs from the services {watcher.services}:\n{extra_info_str}"


class LogRoll(list[tuple[str, str]]):
    """A class to roll logs from the log watcher.

    Besides the collected ``(source, text)`` log lines, a ``LogRoll`` returned
    by ``Deployment.run`` / ``arun`` carries the ``returncode`` of the command
    that produced it, so callers can inspect the exit code even when they chose
    not to raise on a non-zero result.
    """

    returncode: Optional[int] = None

    @property
    def stdout_gen(self) -> Generator[str, None, None]:
        """Generator for stdout logs."""
        for log, x in self:
            if log == "STDOUT":
                yield x

    @property
    def stderr_gen(self) -> Generator[str, None, None]:
        """Generator for stderr logs."""
        for log, x in self:
            if log == "STDERR":
                yield x

    @property
    def stderr_list(self) -> List[str]:
        """List of stderr logs."""
        return list(self.stderr_gen)

    @property
    def stdout_list(self) -> List[str]:
        """List of stdout logs."""
        return list(self.stdout_gen)

    @property
    def stdout(self) -> str:
        """String of stdout logs joined by new lines."""
        return "\n".join(self.stdout_gen)

    @property
    def stderr(self) -> str:
        """String of stderr logs joined by new lines."""
        return "\n".join(self.stderr_gen)

    def __str__(self) -> str:
        """String representation of the log roll."""
        return "\n".join(f"{log}: {text}" for log, text in self)


class LogWatcher(KoiledModel):
    """A class to watch logs from a Docker container."""

    cli_bearer: CLIBearer
    tail: Optional[int] = None
    follow: bool = True
    no_log_prefix: bool = False
    timestamps: bool = False
    since: Optional[str] = None
    until: Optional[str] = None
    stream: bool = True
    services: Union[str, List[str]] = []
    wait_for_first_log: bool = True
    wait_for_first_log_timeout: float = 10.0
    wait_for_logs: bool = False
    wait_for_logs_timeout: int = 10
    collected_logs: LogRoll = Field(default_factory=LogRoll)
    log_function: Optional[LogFunction] = None
    append_to_traceback: bool = True
    capture_stdout: bool = True
    rich_traceback: bool = True

    _watch_task: Optional[asyncio.Task[None]] = None
    _just_one_log: Optional[asyncio.Future[bool]] = None

    async def aon_logs(self, log: Tuple[str, str]) -> None:
        """Asynchronous function to handle logs."""
        if self.log_function:
            if inspect.iscoroutinefunction(self.log_function):
                await self.log_function(log)
            else:
                self.log_function(log)

    async def awatch_logs(self) -> None:
        """Asynchronous function to watch logs.

        A failure here (a nonexistent service, an unreachable daemon) is handed
        to ``_just_one_log`` so that an ``__aenter__`` waiting on the first log
        fails with the real cause instead of waiting forever for a log line that
        can never arrive.
        """
        try:
            cli = await self.cli_bearer.aget_cli()
            async for logtuple in cli.astream_docker_logs(
                tail=str(self.tail) if self.tail else None,
                follow=self.follow,
                no_log_prefix=self.no_log_prefix,
                timestamps=self.timestamps,
                since=self.since,
                until=self.until,
                services=self.services,
            ):
                if self._just_one_log is not None and not self._just_one_log.done():
                    self._just_one_log.set_result(True)
                await self.aon_logs(logtuple)
                self.collected_logs.append(logtuple)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Wake whoever is waiting on the first log with the actual error.
            if self._just_one_log is not None and not self._just_one_log.done():
                self._just_one_log.set_exception(e)
            raise
        else:
            # The stream ended without producing anything (e.g. `follow=False`
            # against a service that has logged nothing). Release the waiter
            # rather than leaving it pending forever.
            if self._just_one_log is not None and not self._just_one_log.done():
                self._just_one_log.set_result(False)

    async def __aenter__(self) -> Self:
        """Asynchronous context manager to enter the log watcher.

        When ``wait_for_first_log`` is set, the wait is bounded by
        ``wait_for_first_log_timeout``. An unbounded wait here is a silent hang:
        the future is only ever resolved from ``awatch_logs``, so a service that
        never logs -- or a watcher pointed at a service name that does not exist
        -- would block the caller (typically a whole test session) with no
        output at all.
        """
        self.collected_logs = LogRoll()
        self._just_one_log = asyncio.Future()
        self._watch_task = asyncio.create_task(self.awatch_logs())

        if self.wait_for_first_log:
            try:
                await asyncio.wait_for(self._just_one_log, self.wait_for_first_log_timeout)
            except asyncio.TimeoutError:
                await self._acancel_watch_task()
                raise LogWatcherTimeoutError(f"No log line arrived from {self.services or 'any service'} within {self.wait_for_first_log_timeout}s. Pass `wait_for_first_log=False` if the service is expected to be quiet, or raise `wait_for_first_log_timeout`.") from None
            except BaseException:
                # The watch task failed (bad service name, daemon down). Reap it
                # so the error is not also reported as "never retrieved".
                await self._acancel_watch_task()
                raise

        self._just_one_log = asyncio.Future()

        return self

    def await_log(self, pattern: str, timeout: float = 30.0) -> str:
        """Block until a collected log line matches ``pattern``. See ``aawait_log``."""
        return unkoil(self.aawait_log, pattern, timeout=timeout)

    async def aawait_log(self, pattern: str, timeout: float = 30.0) -> str:
        """Block until a collected log line matches ``pattern``.

        Turns the watcher from "capture logs while I work" into a synchronisation
        primitive: wait for the line that means the thing you triggered has
        actually happened, instead of sleeping and hoping.

        Lines already captured since the watcher was entered count, so there is
        no race between the event happening and this call being made.

        Parameters
        ----------
        pattern : str
            Regular expression searched for in each log line.
        timeout : float
            Seconds to wait before giving up.

        Returns
        -------
        str
            The first matching log line.

        Raises
        ------
        LogWatcherTimeoutError
            If no line matches within ``timeout``.
        """
        regex = re.compile(pattern)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        seen = 0

        while True:
            # Re-scan only what is new since the last pass.
            for _, line in list(self.collected_logs)[seen:]:
                if regex.search(line):
                    return line
            seen = len(self.collected_logs)

            if self._watch_task is not None and self._watch_task.done():
                # Surface a stream failure rather than waiting out the timeout.
                exc = self._watch_task.exception()
                if exc is not None:
                    raise exc

            remaining = deadline - loop.time()
            if remaining <= 0:
                raise LogWatcherTimeoutError(f"No log line matching /{pattern}/ arrived from {self.services or 'any service'} within {timeout}s. Captured {len(self.collected_logs)} line(s).")

            await asyncio.sleep(min(0.05, remaining))

    async def _acancel_watch_task(self) -> Optional[BaseException]:
        """Cancel and reap the background watch task, if any.

        Returns the exception the task died of, if it failed on its own before
        being cancelled. A normal follow-stream only ever ends by cancellation,
        so anything else is a real failure the caller should hear about.
        """
        if self._watch_task is None:
            return None

        task, self._watch_task = self._watch_task, None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return None
        except Exception as e:
            return e
        return None

    async def __aexit__(self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]) -> None:
        """Asynchronous context manager to exit the log watcher.

        The watch task (and its ``docker compose logs --follow`` subprocess) is
        always cancelled on the way out, even when an exception is propagating
        through the ``with`` block -- a Ctrl-C, a failed assertion, a request
        error. Doing the teardown in a ``finally`` is what stops those cases
        from leaking a ghost streaming task and an orphaned follow process.

        If the stream itself failed (most commonly: the watched service does not
        exist), that failure is raised here -- but only when the block completed
        normally, so it can never mask an exception the body was already
        propagating. Swallowing it would leave the watcher silently collecting
        nothing, which looks like a passing test.
        """
        watch_error: Optional[BaseException] = None
        try:
            if exc_type is not None and self.append_to_traceback:
                new_message = format_log_watcher_message(self, exc_val, rich=self.rich_traceback)
                try:
                    new_exc = exc_type(new_message)
                except:  # noqa: E722
                    new_exc = Exception(new_message)

                raise new_exc.with_traceback(exc_tb) from exc_val

            if self.wait_for_logs:
                if self._just_one_log is not None:
                    await asyncio.wait_for(self._just_one_log, self.wait_for_logs_timeout)
        finally:
            watch_error = await self._acancel_watch_task()

        if watch_error is not None and exc_type is None:
            raise watch_error
