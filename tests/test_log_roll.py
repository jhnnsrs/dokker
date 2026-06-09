"""Unit tests for ``LogRoll`` and the log-watcher message formatting.

``LogRoll`` is the object users inspect after running a command or watching a
service, so the stdout/stderr split has to be correct -- a container's error
output lives on stderr, and confusing the two hides failures.
"""

from dokker.cli import CLI
from dokker.log_watcher import LogRoll, LogWatcher, format_log_watcher_message


class _DummyBearer:
    """Minimal object satisfying the runtime-checkable ``CLIBearer`` protocol."""

    async def aget_cli(self) -> CLI:  # pragma: no cover - never invoked here
        raise NotImplementedError


def _sample_roll() -> LogRoll:
    roll = LogRoll()
    roll.append(("STDOUT", "starting up"))
    roll.append(("STDERR", "something broke"))
    roll.append(("STDOUT", "done"))
    return roll


def test_stdout_only_contains_stdout():
    roll = _sample_roll()
    assert roll.stdout_list == ["starting up", "done"]
    assert roll.stdout == "starting up\ndone"


def test_stderr_only_contains_stderr():
    roll = _sample_roll()
    # Regression test: stderr_gen used to filter on "STDOUT", so stderr
    # silently returned stdout and container errors were invisible.
    assert roll.stderr_list == ["something broke"]
    assert roll.stderr == "something broke"


def test_stdout_and_stderr_are_disjoint():
    roll = _sample_roll()
    assert set(roll.stdout_list).isdisjoint(roll.stderr_list)


def test_empty_roll():
    roll = LogRoll()
    assert roll.stdout == ""
    assert roll.stderr == ""
    assert roll.stdout_list == []
    assert roll.stderr_list == []


def test_format_log_watcher_message_includes_services_and_logs():
    watcher = LogWatcher(cli_bearer=_DummyBearer(), services=["mikro"], capture_stdout=True)
    watcher.collected_logs = _sample_roll()

    message = format_log_watcher_message(watcher, ValueError("request failed"))

    assert "request failed" in message
    assert "mikro" in message
    assert "something broke" in message


def test_format_log_watcher_message_respects_capture_stdout_false():
    watcher = LogWatcher(cli_bearer=_DummyBearer(), services=["mikro"], capture_stdout=False)
    watcher.collected_logs = _sample_roll()

    message = format_log_watcher_message(watcher, ValueError("request failed"))

    # With stdout capture disabled, only stderr lines should be carried over.
    assert "something broke" in message
    assert "starting up" not in message
