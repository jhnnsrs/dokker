"""Unit tests for ``dokker.command``.

These tests exercise the command-streaming layer directly with tiny shell
commands, so they need no docker images and run anywhere. They focus on the
failure-feedback path: when a command exits non-zero we want the resulting
``CommandError`` to carry structured, legible information about what went wrong.
"""

import pytest

from dokker.command import CommandError, astream_command


async def _collect(command):
    # ``astream_command`` joins the list with spaces and runs it through a
    # shell, so the test commands are written as a single shell snippet.
    return [line async for line in astream_command(command)]


async def test_streams_stdout_and_stderr_with_source_tags():
    lines = await _collect(["echo out; echo err >&2"])

    assert ("STDOUT", "out") in lines
    assert ("STDERR", "err") in lines


async def test_failing_command_raises_command_error_with_streams_separated():
    with pytest.raises(CommandError) as excinfo:
        await _collect(["echo out; echo boom >&2; exit 3"])

    error = excinfo.value
    assert error.returncode == 3
    assert error.stdout == ["out"]
    assert error.stderr == ["boom"]
    # The command that was run is preserved for debugging.
    assert error.command is not None and "exit 3" in error.command


async def test_failing_command_message_surfaces_stderr():
    with pytest.raises(CommandError) as excinfo:
        await _collect(["echo boom >&2; exit 1"])

    message = str(excinfo.value)
    # The human readable message must mention the failure and the stderr text,
    # since that is what tells the user *why* a container failed.
    assert "return code 1" in message
    assert "boom" in message
    assert "STDERR" in message


async def test_failing_command_without_output_reports_no_output():
    with pytest.raises(CommandError) as excinfo:
        await _collect(["exit 2"])

    error = excinfo.value
    assert error.returncode == 2
    assert error.stdout == []
    assert error.stderr == []
    assert "No output was captured." in str(error)


async def test_successful_command_does_not_raise():
    lines = await _collect(["echo hello"])
    assert lines == [("STDOUT", "hello")]


def test_command_error_is_dokker_error():
    from dokker.errors import DokkerError

    assert issubclass(CommandError, DokkerError)
