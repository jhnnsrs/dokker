from pydantic import BaseModel, Field
import os
from typing import Optional
import shutil
from dokker.cli import CLI
from dokker.projects.errors import ProjectError
from dokker.types import ValidPath

# Compose accepts either spelling, so a mirrored project may legitimately use
# either. Checking only one of them rejects valid projects.
COMPOSE_FILE_NAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")


class CopyPathProject(BaseModel):
    """A copy path Project.

    This project is a project that will mirror a path to a temporary
    directory and run it from there. This is useful for testing projects that
    are in production environments btu should be tested locally.
    """

    project_path: ValidPath
    project_name: Optional[str] = None
    base_dir: str = Field(default_factory=lambda: os.path.join(os.getcwd(), ".dokker"))
    overwrite: bool = False

    async def ainititialize(self) -> CLI:
        """A setup method for the project.

        Returns
        -------
        CLI
            The CLI to use for the project.
        """
        if not os.path.isdir(self.project_path):
            raise ProjectError(f"Cannot mirror `{self.project_path}`: no such directory (resolved relative to {os.getcwd()}).")

        os.makedirs(self.base_dir, exist_ok=True)

        if self.project_name is None:
            self.project_name = os.path.basename(os.path.normpath(str(self.project_path)))

        project_dir = os.path.join(self.base_dir, self.project_name)
        if os.path.exists(project_dir) and not self.overwrite:
            raise ProjectError(f"Project `{self.project_name}` already exists in {self.base_dir}. Pass overwrite=True to replace it, or choose a different project_name.")

        shutil.copytree(self.project_path, project_dir, dirs_exist_ok=self.overwrite)

        compose_file = next(
            (os.path.join(project_dir, name) for name in COMPOSE_FILE_NAMES if os.path.exists(os.path.join(project_dir, name))),
            None,
        )
        if compose_file is None:
            raise ProjectError(f"No compose file found in `{self.project_path}`. Expected one of: {', '.join(COMPOSE_FILE_NAMES)}.")

        return CLI(
            compose_files=[compose_file],
            compose_project_name=self.project_name,
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

        if self.project_name is None:
            self.project_name = os.path.basename(os.path.normpath(str(self.project_path)))

        project_dir = os.path.join(self.base_dir, self.project_name)
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)

    async def abefore_pull(self) -> None:
        """A setup method for the project.

        Returns:
            Optional[List[str]]: A list of logs from the setup process.
        """
        ...

    async def abefore_up(self) -> None:
        """A setup method for the project.

        Returns:
            Optional[List[str]]: A list of logs from the setup process.
        """
        ...

    async def abefore_enter(self) -> None:
        """A setup method for the project.

        Returns:
            Optional[List[str]]: A list of logs from the setup process.
        """
        ...

    async def abefore_down(self) -> None:
        """A setup method for the project.

        Returns:
            Optional[List[str]]: A list of logs from the setup process.
        """
        ...

    async def abefore_stop(self) -> None:
        """A setup method for the project.

        Returns:
            Optional[List[str]]: A list of logs from the setup process.
        """
        ...
