from pydantic import BaseModel, ConfigDict, Field
from typing import Union
from pathlib import Path
from dokker.cli import CLI
from typing import Dict, Any, Optional
import logging
import os
from dokker.projects.errors import ProjectError

logger = logging.getLogger(__name__)

ValidPath = Union[str, Path]


class DokkerProjectError(ProjectError):
    """An error raised when a local project is not initialized."""

    pass


class DokkerProject(BaseModel):
    """A project that is located on the local filesystem.

    This project is a project that is located on the local filesystem.
    It can be used to run a docker-compose file locally, without
    interfering with the docker project on tear-down.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)
    base_dir: ValidPath = Field(default_factory=lambda: os.path.join(os.getcwd(), ".dokker"))
    name: str
    _outs: Optional[Dict[str, Any]] = None
    _project_dir: Optional[ValidPath] = None

    async def ainititialize(self) -> CLI:
        """A setup method for the project.

        Returns
        -------
        CLI
            The CLI to use for the project.
        """
        os.makedirs(self.base_dir, exist_ok=True)

        self._project_dir = os.path.join(self.base_dir, self.name)
        if not os.path.exists(self._project_dir):
            raise DokkerProjectError(f"No project found with the name {self.name} in {self.base_dir}. Available projects: {os.listdir(self.base_dir)}")

        compose_file = os.path.join(self._project_dir, "docker-compose.yaml")
        if not os.path.exists(compose_file):
            raise Exception("No docker-compose.yml found in the template. It appears that the template is not a valid dokker template.")

        return CLI(
            compose_files=[compose_file],
        )

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
