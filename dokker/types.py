from typing import Callable, Union, AsyncIterator, Tuple, Awaitable
from pathlib import Path

ValidPath = Union[str, Path]
LogStream = AsyncIterator[Tuple[str, str]]
LogFunction = Union[Callable[[Tuple[str, str]], Awaitable[None]], Callable[[Tuple[str, str]], None]]
