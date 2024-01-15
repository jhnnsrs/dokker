import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union
from dokker.types import LogStream


class CommandError(Exception):
    pass


async def _aread_stream(
    stream: asyncio.StreamReader,
    queue: asyncio.Queue,
    name: str,
) -> None:
    async for line in stream:
        await queue.put((name, line.decode("utf-8").strip()))

    await queue.put(None)


async def astream_command(command: List[str]) -> LogStream:
    # Create the subprocess using asyncio's subprocess

    full_cmd = " ".join(map(str, command))

    proc = await asyncio.create_subprocess_shell(
        full_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    if proc.stdout is None or proc.stderr is None:
        raise CommandError("Could not create the subprocess.")

    queue = asyncio.Queue()  # type: asyncio.Queue[tuple[str, str]]

    # cannot use type annotation because of python 3.8
    # Create and start tasks for reading each stream

    try:
        collected_logs = []
        readers = [
            asyncio.create_task(_aread_stream(proc.stdout, queue, "STDOUT")),
            asyncio.create_task(_aread_stream(proc.stderr, queue, "STDERR")),
        ]

        # Track the number of readers that are finished
        finished_readers = 0
        while finished_readers < len(readers):
            line = await queue.get()
            if line is None:
                finished_readers += 1  # One reader has finished
                continue
            collected_logs.append(line[1])
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
            logs = "\n".join(collected_logs) if collected_logs else "No Logs"

            raise CommandError(
                f"Command {full_cmd} failed with return code {proc.returncode}: \n{logs}"
            )

    except asyncio.CancelledError:
        # Handle cancellation request
        proc.kill()
        await proc.wait()  # Wait for the subprocess to exit after receiving SIGINT

        # Cleanup: cancel any remaining reader tasks
        for reader in readers:
            reader.cancel()
            try:
                await reader
            except asyncio.CancelledError:
                pass

        raise

    except Exception as e:
        raise e
