import asyncio
import os
import shlex
import shutil
import signal
from typing import Dict, List, Optional, Union
from dokker.types import LogStream
from dokker.errors import DockerNotAvailableError, DokkerError

# Safety net for reaping a subprocess we have asked to die. After killing the
# process group `proc.wait()` should resolve almost immediately; this bounds it
# so a teardown can never block forever if the process is not reaped.
KILL_TIMEOUT = 5.0

# How long to wait for `docker version` when checking that the daemon is alive.
PREFLIGHT_TIMEOUT = 20.0

# Cached preflight result. Checking costs a subprocess round-trip, and the
# answer does not change within a test session.
_docker_available: Optional[bool] = None


async def acheck_docker_available(client_call: Optional[List[str]] = None) -> None:
    """Verify that the docker CLI exists and its daemon is reachable.

    Without this, the two most likely first failures of any dokker run -- docker
    not installed, or the daemon not running -- surface as a shell exit code 127
    or an unlabelled stderr blob wrapped in a generic ``CommandError``. Raising
    early says which of the two it is.

    The result is cached for the process, so this is cheap to call on every
    command.

    Raises
    ------
    DockerNotAvailableError
        If the docker binary is missing, the daemon is unreachable, or the
        version probe times out.
    """
    global _docker_available
    if _docker_available:
        return

    binary = (client_call or ["docker"])[0]
    if shutil.which(binary) is None:
        raise DockerNotAvailableError(f"The `{binary}` executable was not found on your PATH. Install Docker (https://docs.docker.com/get-docker/) and make sure `{binary}` is runnable.")

    try:
        proc = await asyncio.create_subprocess_exec(
            binary,
            "version",
            "--format",
            "{{.Server.Version}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        raise DockerNotAvailableError(f"Could not execute `{binary}`: {e}") from e

    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=PREFLIGHT_TIMEOUT)
    except asyncio.TimeoutError:
        _kill_process_group(proc)
        raise DockerNotAvailableError(f"`{binary} version` did not respond within {PREFLIGHT_TIMEOUT}s. The Docker daemon appears to be unresponsive.") from None

    if proc.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise DockerNotAvailableError(f"The `{binary}` CLI is installed but the Docker daemon is not reachable. Start Docker and try again.\n\n{detail}" if detail else f"The `{binary}` CLI is installed but the Docker daemon is not reachable. Start Docker and try again.")

    _docker_available = True


async def ais_docker_available(client_call: Optional[List[str]] = None) -> bool:
    """Return whether docker is installed and its daemon reachable.

    The non-raising counterpart of :func:`acheck_docker_available`, for callers
    that want to skip rather than fail (e.g. the pytest plugin).
    """
    try:
        await acheck_docker_available(client_call)
    except DockerNotAvailableError:
        return False
    return True


class CommandError(DokkerError):
    """An error raised when a command fails to execute.

    The error carries structured information about the failed command so that
    callers can give precise feedback about what went wrong, instead of having
    to parse a single concatenated log string. The ``stdout`` and ``stderr``
    streams are kept separate, which is what makes container failures legible:
    the actual error a container emits almost always lands on ``stderr``.
    """

    def __init__(
        self,
        message: str,
        command: Optional[str] = None,
        returncode: Optional[int] = None,
        stdout: Optional[List[str]] = None,
        stderr: Optional[List[str]] = None,
    ) -> None:
        """Create a CommandError carrying the failed command's streams."""
        self.command = command
        self.returncode = returncode
        self.stdout: List[str] = stdout if stdout is not None else []
        self.stderr: List[str] = stderr if stderr is not None else []
        super().__init__(message)


def _format_command_error(
    command: str,
    returncode: Optional[int],
    stdout: List[str],
    stderr: List[str],
) -> str:
    """Build a human readable error message for a failed command.

    Stderr is shown first and labelled, because that is where containers and
    the docker CLI report what actually went wrong.
    """
    sections = [f"Command `{command}` failed with return code {returncode}."]
    if stderr:
        sections.append("STDERR:\n" + "\n".join(stderr))
    if stdout:
        sections.append("STDOUT:\n" + "\n".join(stdout))
    if not stderr and not stdout:
        sections.append("No output was captured.")
    return "\n\n".join(sections)


def _kill_process_group(proc: "asyncio.subprocess.Process") -> None:
    """Forcibly kill *proc* and any children it spawned.

    A streamed command such as ``docker compose logs --follow`` runs under a
    shell wrapper and spawns further children; killing only the shell leaves the
    real, never-ending process alive (reparented to init). Because the process
    is started with ``start_new_session=True`` it is the leader of its own
    process group, so we can take the whole tree down with a single ``killpg``.

    Falls back to killing just the process on platforms without ``killpg``
    (e.g. Windows); the bounded wait in the caller covers that path.
    """
    if proc.returncode is not None:
        return
    try:
        if hasattr(os, "killpg"):
            # start_new_session=True guarantees pgid == proc.pid, so this only
            # ever targets the command's own group, never python's.
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError):
        # Already gone, or we are not allowed to signal it -- nothing to do.
        pass


async def _aread_stream(
    stream: asyncio.StreamReader,
    queue: asyncio.Queue[Union[tuple[str, str], None]],
    name: str,
) -> None:
    """Asynchronously read a stream and put lines into a queue."""
    async for line in stream:
        await queue.put((name, line.decode("utf-8").strip()))

    await queue.put(None)


async def astream_command(command: List[str], env: Optional[Dict[str, str]] = None) -> LogStream:
    """Asynchronously stream the output of a command.

    The command is executed directly, not through a shell. Joining an argument
    vector into a shell string is lossy in both directions: a compose file path
    containing a space would split into two arguments, and a command already
    tokenized by `shlex.split` would be re-split differently by the shell, so
    `sh -c 'echo boom >&2'` would arrive at the container as three unrelated
    words. Passing argv straight through is the only form that survives both.

    Parameters
    ----------
    command : List[str]
        The command to run, as an argument vector.
    env : Optional[Dict[str, str]]
        Extra environment variables for the subprocess, merged over the parent
        environment. None inherits the parent environment unchanged.
    """
    # Convert command items to strings
    str_command = [str(c) for c in command]
    # For display only -- error messages quote this so it can be pasted back
    # into a shell, but it is never what we execute.
    full_cmd = shlex.join(str_command)

    if not str_command:
        raise CommandError("Cannot run an empty command.")

    subprocess_env = {**os.environ, **env} if env else None

    try:
        proc = await asyncio.create_subprocess_exec(
            *str_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=subprocess_env,
            # Run in its own session/process group so a follow-stream and any
            # children it spawns can be torn down as a group on cancellation.
            start_new_session=True,
        )
    except FileNotFoundError as e:
        raise CommandError(f"Failed to start command `{full_cmd}`: {str_command[0]!r} was not found on PATH.") from e
    except Exception as e:
        raise CommandError(f"Failed to start command `{full_cmd}`: {e}") from e

    # Use a queue to stream both stdout and stderr sequentially
    queue: asyncio.Queue[Union[tuple[str, str], None]] = asyncio.Queue()

    if proc.stdout is None or proc.stderr is None:
        raise CommandError(f"Failed to get stdout or stderr from subprocess {command}")

    # Create tasks to read from stdout and stderr asynchronously
    readers: list[asyncio.Task[None]] = [
        asyncio.create_task(_aread_stream(proc.stdout, queue, "STDOUT")),
        asyncio.create_task(_aread_stream(proc.stderr, queue, "STDERR")),
    ]

    try:
        stdout_logs: list[str] = []
        stderr_logs: list[str] = []

        # Track the number of readers that are finished
        finished_readers = 0
        while finished_readers < len(readers):
            line = await queue.get()
            if line is None:
                finished_readers += 1  # One reader has finished
                continue
            source, text = line
            if source == "STDERR":
                stderr_logs.append(text)
            else:
                stdout_logs.append(text)
            yield line

        # Cleanup: cancel any remaining reader tasks
        for reader in readers:
            reader.cancel()
            try:
                await reader
            except asyncio.CancelledError:
                pass

        await proc.wait()

        if proc.returncode != 0:
            # When the command fails, surface the streams separately so callers
            # can tell apart the diagnostic output (stderr) from regular output.
            raise CommandError(
                _format_command_error(full_cmd, proc.returncode, stdout_logs, stderr_logs),
                command=full_cmd,
                returncode=proc.returncode,
                stdout=stdout_logs,
                stderr=stderr_logs,
            )

    except asyncio.CancelledError:
        # A follow-stream (e.g. `docker compose logs --follow`) only ends via
        # cancellation. Stop the reader tasks first so nothing is left blocked
        # on the pipes, kill the whole process group (killing only the shell
        # wrapper leaves the real, never-ending child alive), then reap it under
        # a bounded wait so teardown can never hang waiting on `proc.wait()`.
        for reader in readers:
            reader.cancel()
        for reader in readers:
            try:
                await reader
            except asyncio.CancelledError:
                pass

        _kill_process_group(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=KILL_TIMEOUT)
        except asyncio.TimeoutError:
            pass

        raise

    except Exception as e:
        raise e
