from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Protocol, runtime_checkable, Any
from pathlib import Path
from dokker.cli import CLI


class LocalProject(BaseModel):
    compose_files: List[Path] = Field(default_factory=lambda: ["docker-compose.yml"])

    async def ainititialize(self) -> CLI:
        return CLI(compose_files=self.compose_files)

    async def abefore_pull(self) -> None:
        """A setup method for the project.

        Returns:
            Optional[List[str]]: A list of logs from the setup process.
        """
        return None

    async def abefore_up(self) -> None:
        """A setup method for the project.

        Returns:
            Optional[List[str]]: A list of logs from the setup process.
        """
        return None

    async def abefore_enter(self) -> None:
        """A setup method for the project.

        Returns:
            Optional[List[str]]: A list of logs from the setup process.
        """
        return None

    async def abefore_down(self) -> None:
        """A setup method for the project.

        Returns:
            Optional[List[str]]: A list of logs from the setup process.
        """
        return None

    async def abefore_stop(self) -> None:
        """A setup method for the project.

        Returns:
            Optional[List[str]]: A list of logs from the setup process.
        """
        return None
