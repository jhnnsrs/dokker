import asyncio
import signal
from python_on_whales.client_config import ClientConfig, to_list
from typing import Any, Coroutine, Optional, List, Protocol, runtime_checkable, Union


async def aread_stream(
    stream: asyncio.StreamReader,
    queue: asyncio.Queue,
    name: str,
):
    async for line in stream:
        await queue.put((name, line.decode("utf-8").strip()))

    await queue.put(None)


async def ayield_docker_logs(
    client_config: ClientConfig,
    tail: Optional[str] = None,
    follow: bool = False,
    no_log_prefix: bool = False,
    timestamps: bool = False,
    since: Optional[str] = None,
    until: Optional[str] = None,
    services: Union[str, List[str]] = [],
):
    # Create the subprocess using asyncio's subprocess
    full_cmd = client_config.docker_compose_cmd + ["logs", "--no-color"]
    full_cmd.add_simple_arg("--tail", tail)
    full_cmd.add_flag("--follow", follow)
    full_cmd.add_flag("--no-log-prefix", no_log_prefix)
    full_cmd.add_flag("--timestamps", timestamps)
    full_cmd.add_simple_arg("--since", since)
    full_cmd.add_simple_arg("--until", until)
    full_cmd += to_list(services)

    full_cmd = " ".join(map(str, full_cmd))

    proc = await asyncio.create_subprocess_shell(
        full_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    queue = asyncio.Queue()
    # Create and start tasks for reading each stream

    try:
        readers = [
            asyncio.create_task(aread_stream(proc.stdout, queue, "STDOUT")),
            asyncio.create_task(aread_stream(proc.stderr, queue, "STDERR")),
        ]

        # Track the number of readers that are finished
        finished_readers = 0
        while finished_readers < len(readers):
            line = await queue.get()
            if line is None:
                finished_readers += 1  # One reader has finished
                continue
            yield line

        # Cleanup: cancel any remaining reader tasks
        for reader in readers:
            reader.cancel()
            try:
                await reader
            except asyncio.CancelledError:
                pass

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
