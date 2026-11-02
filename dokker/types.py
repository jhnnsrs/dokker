from collections.abc import Callable, AsyncIterator, Awaitable
from pathlib import Path

ValidPath = str | Path
LogStream = AsyncIterator[tuple[str, str]]
LogFunction = Callable[[tuple[str, str]], Awaitable[None]] | Callable[[tuple[str, str]], None]
