from pydantic import BaseModel, Field
from typing import List, Union
from pathlib import Path
from dokker.cli import CLI
import logging


logger = logging.getLogger(__name__)

ValidPath = Union[str, Path]


class LocalProject(BaseModel):
    """A project that is located on the local filesystem.

    This project is a project that is located on the local filesystem.
    It can be used to run a docker-compose file locally, without
    interfering with the docker project on tear-down.
    """

    compose_files: List[ValidPath] = Field(
        default_factory=lambda: ["docker-compose.yml"]
    )

    async def ainititialize(self) -> CLI:
        """A setup method for the project.

        Returns
        -------
        CLI
            The CLI to use for the project.
        """
        return CLI(compose_files=self.compose_files)

    async def atear_down(self, cli: CLI) -> None:
        """Tear down the project.

        A project can implement this method to tear down the project
        when the project is torn down. This can be used to remove
        temporary files, or to remove the project from the .dokker
        directory.

        Parameters
        ----------
        cli : CLI
            The CLI that was used to run the project.

        """
        logger.info("Tearing down project, is a void operation for a local project")
        return None

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
