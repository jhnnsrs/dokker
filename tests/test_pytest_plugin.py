"""Tests for dokker's shipped pytest plugin. No docker required.

The `pytester` tests run a real inner pytest, which picks dokker's plugin up
through its ``pytest11`` entry point exactly as a downstream project would --
so they verify registration, not just that the functions exist.
"""

import io

import pytest

from dokker.pytest_plugin import _progress_enabled, _supports_ansi


class FakeConfig:
    """Just enough of `pytest.Config` for the option-resolution helpers."""

    def __init__(self, **options):
        self._options = {"--dokker-progress": "auto", "--dokker-log": False, **options}

    def getoption(self, name, default=None):
        return self._options.get(name, default)


class Tty(io.StringIO):
    def isatty(self):
        return True


class NotTty(io.StringIO):
    def isatty(self):
        return False


# ------------------------------------------------------------------ ansi


def test_a_pipe_gets_no_progress_line():
    """Carriage returns written into a pipe are litter, not a display."""
    assert _supports_ansi(NotTty()) is False


def test_a_terminal_gets_a_progress_line(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delenv("TERM", raising=False)
    assert _supports_ansi(Tty()) is True


def test_dumb_terminals_are_excluded(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("TERM", "dumb")
    assert _supports_ansi(Tty()) is False


def test_a_stream_without_isatty_is_not_a_terminal():
    class Bare:
        pass

    assert _supports_ansi(Bare()) is False


def test_legacy_windows_console_is_excluded(monkeypatch):
    """`cmd.exe` claims isatty() but renders \\x1b[K as literal garbage."""
    monkeypatch.setattr("sys.platform", "win32")
    for var in ("WT_SESSION", "ANSICON", "TERM"):
        monkeypatch.delenv(var, raising=False)
    assert _supports_ansi(Tty()) is False

    monkeypatch.setenv("WT_SESSION", "1")
    assert _supports_ansi(Tty()) is True


# ------------------------------------------------------------------ resolution


def test_off_disables_progress_even_on_a_terminal(monkeypatch):
    monkeypatch.setattr("sys.stdout", Tty())
    assert _progress_enabled(FakeConfig(**{"--dokker-progress": "off"})) is False


def test_on_forces_progress_even_when_piped(monkeypatch):
    monkeypatch.setattr("sys.stdout", NotTty())
    assert _progress_enabled(FakeConfig(**{"--dokker-progress": "on"})) is True


def test_auto_follows_the_terminal(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delenv("TERM", raising=False)

    monkeypatch.setattr("sys.stdout", NotTty())
    assert _progress_enabled(FakeConfig()) is False

    monkeypatch.setattr("sys.stdout", Tty())
    assert _progress_enabled(FakeConfig()) is True


def test_dokker_log_wins_over_progress(monkeypatch):
    """Raw log output would scroll a self-erasing line away every frame."""
    monkeypatch.setattr("sys.stdout", Tty())
    config = FakeConfig(**{"--dokker-progress": "on", "--dokker-log": True})
    assert _progress_enabled(config) is False


# ------------------------------------------------------------------ registration


def test_flag_is_registered_via_the_entry_point(pytester: pytest.Pytester):
    """A downstream project gets the flag purely by installing dokker."""
    pytester.makepyfile(
        """
        def test_option(request):
            assert request.config.getoption("--dokker-progress") == "off"
        """
    )
    result = pytester.runpytest_subprocess("--dokker-progress=off")
    result.assert_outcomes(passed=1)


def test_progress_defaults_to_auto(pytester: pytest.Pytester):
    pytester.makepyfile(
        """
        def test_option(request):
            assert request.config.getoption("--dokker-progress") == "auto"
        """
    )
    result = pytester.runpytest_subprocess()
    result.assert_outcomes(passed=1)


def test_invalid_progress_value_is_rejected(pytester: pytest.Pytester):
    pytester.makepyfile("def test_noop(): pass")
    result = pytester.runpytest_subprocess("--dokker-progress=maybe")
    assert result.ret != 0


def test_help_lists_the_dokker_group(pytester: pytest.Pytester):
    result = pytester.runpytest_subprocess("--help")
    result.stdout.fnmatch_lines(["*--dokker-progress*"])
