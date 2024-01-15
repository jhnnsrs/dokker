from typing import Union, AsyncIterator, Tuple
from pathlib import Path

ValidPath = Union[str, Path]
LogStream = AsyncIterator[Tuple[str, str]]
