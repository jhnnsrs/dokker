"""Unit tests for ``dokker.command``.

These tests exercise the command-streaming layer directly with tiny shell
commands, so they need no docker images and run anywhere. They focus on the
failure-feedback path: when a command exits non-zero we want the resulting
``CommandError`` to carry structured, legible information about what went wrong.
"""

import pytest

from dokker.command import CommandError, astream_command


async def _collect(command):
    # ``astream_command`` executes an argument vector directly (no shell), so
    # anything needing shell syntax is spelled out as an explicit ``sh -c``.
    return [line async for line in astream_command(command)]


def _sh(script):
    """Wrap a shell snippet as an explicit argv, the way a caller must now."""
    return ["sh", "-c", script]


async def test_streams_stdout_and_stderr_with_source_tags():
    lines = await _collect(_sh("echo out; echo err >&2"))

    assert ("STDOUT", "out") in lines
    assert ("STDERR", "err") in lines


async def test_failing_command_raises_command_error_with_streams_separated():
    with pytest.raises(CommandError) as excinfo:
        await _collect(_sh("echo out; echo boom >&2; exit 3"))

    error = excinfo.value
    assert error.returncode == 3
    assert error.stdout == ["out"]
    assert error.stderr == ["boom"]
    # The command that was run is preserved for debugging.
    assert error.command is not None and "exit 3" in error.command


async def test_failing_command_message_surfaces_stderr():
    with pytest.raises(CommandError) as excinfo:
        await _collect(_sh("echo boom >&2; exit 1"))

    message = str(excinfo.value)
    # The human readable message must mention the failure and the stderr text,
    # since that is what tells the user *why* a container failed.
    assert "return code 1" in message
    assert "boom" in message
    assert "STDERR" in message


async def test_failing_command_without_output_reports_no_output():
    with pytest.raises(CommandError) as excinfo:
        await _collect(_sh("exit 2"))

    error = excinfo.value
    assert error.returncode == 2
    assert error.stdout == []
    assert error.stderr == []
    assert "No output was captured." in str(error)


async def test_successful_command_does_not_raise():
    lines = await _collect(["echo", "hello"])
    assert lines == [("STDOUT", "hello")]


async def test_arguments_containing_spaces_are_not_resplit():
    """An argument with a space must reach the program as ONE argument.

    This is the whole point of executing argv directly: under the previous
    shell-join a compose file path like ``/my projects/compose.yaml`` silently
    became two arguments.
    """
    lines = await _collect(["printf", "%s\n", "one two three"])
    assert ("STDOUT", "one two three") in lines


async def test_shell_metacharacters_are_not_interpreted_by_a_host_shell():
    """Metacharacters in an argument are data, not syntax.

    ``echo`` receives the literal text; nothing is redirected or chained on the
    host. Under a shell join this wrote a file and printed nothing.
    """
    lines = await _collect(["echo", "boom > /dev/null; echo pwned"])
    assert lines == [("STDOUT", "boom > /dev/null; echo pwned")]


async def test_env_is_merged_over_the_parent_environment():
    lines = await _collect_with_env(_sh("echo $DOKKER_TEST_VAR"), {"DOKKER_TEST_VAR": "set-by-test"})
    assert ("STDOUT", "set-by-test") in lines


async def _collect_with_env(command, env):
    return [line async for line in astream_command(command, env=env)]


async def test_missing_executable_reports_which_binary_was_missing():
    with pytest.raises(CommandError) as excinfo:
        await _collect(["dokker-definitely-not-a-real-binary"])

    assert "was not found on PATH" in str(excinfo.value)


def test_command_error_is_dokker_error():
    from dokker.errors import DokkerError

    assert issubclass(CommandError, DokkerError)
