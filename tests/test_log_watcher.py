"""Unit tests for ``LogWatcher``'s async behavior.

These use a fake CLI bearer rather than docker, so they run anywhere. The
module had no unit tests at all, which is why the enter-path hang below went
unnoticed: only the docker-backed integration tests exercised the watcher, and
they always watched services that happened to log promptly.
"""

import asyncio

import pytest

from dokker.command import CommandError
from dokker.errors import LogWatcherTimeoutError
from dokker.log_watcher import LogWatcher


class FakeCLI:
    """A CLI stand-in whose log stream is scripted by the test."""

    def __init__(self, lines=(), error=None, hang=False):
        self._lines = list(lines)
        self._error = error
        self._hang = hang

    async def astream_docker_logs(self, **kwargs):
        if self._error is not None:
            raise self._error
        for line in self._lines:
            yield ("STDOUT", line)
        if self._hang:
            # Emulate `--follow` against a live service: never ends on its own.
            await asyncio.Event().wait()


class FakeBearer:
    def __init__(self, cli):
        self._cli = cli

    async def aget_cli(self):
        return self._cli


def _watcher(cli, **kwargs):
    return LogWatcher(cli_bearer=FakeBearer(cli), **kwargs)


async def test_collects_logs_while_inside_the_block():
    watcher = _watcher(FakeCLI(["first", "second"], hang=True))

    async with watcher:
        # Give the background task a moment to drain the scripted lines.
        await watcher.aawait_log("second", timeout=5)

    assert ("STDOUT", "first") in watcher.collected_logs


async def test_enter_raises_instead_of_hanging_when_the_stream_fails():
    """A failing stream must surface, not deadlock the caller.

    ``__aenter__`` waits on a future that only ``awatch_logs`` resolves. When
    the watch task died first -- a typo'd service name, a dead daemon -- nothing
    ever resolved it and the wait blocked forever, taking the whole test session
    with it and printing nothing.
    """
    watcher = _watcher(FakeCLI(error=CommandError("no such service")))

    with pytest.raises(CommandError):
        async with watcher:
            pytest.fail("should not have entered")  # pragma: no cover


async def test_enter_times_out_on_a_service_that_never_logs():
    """A quiet service must time out with a directed message, not hang."""
    watcher = _watcher(FakeCLI(hang=True), wait_for_first_log_timeout=0.2)

    with pytest.raises(LogWatcherTimeoutError) as excinfo:
        async with watcher:
            pytest.fail("should not have entered")  # pragma: no cover

    assert "wait_for_first_log=False" in str(excinfo.value)


async def test_enter_returns_when_a_finite_stream_produces_nothing():
    """A non-following stream that ends empty releases the waiter."""
    watcher = _watcher(FakeCLI([]), wait_for_first_log_timeout=5)

    async with watcher:
        pass

    assert list(watcher.collected_logs) == []


async def test_await_log_matches_a_pattern():
    watcher = _watcher(FakeCLI(["starting up", "database system is ready"], hang=True))

    async with watcher:
        line = await watcher.aawait_log(r"ready", timeout=5)

    assert line == "database system is ready"


async def test_await_log_matches_lines_captured_before_the_call():
    """No race between the event happening and the wait being started."""
    watcher = _watcher(FakeCLI(["already here"], hang=True))

    async with watcher:
        await asyncio.sleep(0.05)
        assert await watcher.aawait_log("already here", timeout=5) == "already here"


async def test_await_log_times_out_with_a_useful_message():
    watcher = _watcher(FakeCLI(["nothing relevant"], hang=True))

    async with watcher:
        with pytest.raises(LogWatcherTimeoutError) as excinfo:
            await watcher.aawait_log("never appears", timeout=0.2)

    assert "never appears" in str(excinfo.value)


async def test_watch_task_is_cancelled_on_exit_even_when_the_body_raises():
    watcher = _watcher(FakeCLI(["a line"], hang=True), append_to_traceback=False)

    with pytest.raises(RuntimeError):
        async with watcher:
            raise RuntimeError("boom")

    # No ghost task left streaming in the background.
    assert watcher._watch_task is None
