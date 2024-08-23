from pydantic import BaseModel, Field
import os
from typing import Optional
import shutil
from dokker.cli import CLI
from dokker.types import ValidPath


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
        os.makedirs(self.base_dir, exist_ok=True)

        if self.project_name is None:
            self.project_name = os.path.basename(self.project_path)

        project_dir = os.path.join(self.base_dir, self.project_name)
        if os.path.exists(project_dir) and not self.overwrite:
            raise Exception(
                f"Project {self.project_name} already exists in {self.base_dir}. Set overwrite to overwrite."
            )

        shutil.copytree(self.project_path, project_dir, dirs_exist_ok=self.overwrite)

        compose_file = os.path.join(project_dir, "docker-compose.yml")
        if not os.path.exists(compose_file):
            raise Exception(
                "No docker-compose.yml found in the template. It appears that the template is not a valid dokker template."
            )

        return CLI(compose_files=[compose_file])

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
            self.project_name = os.path.basename(self.project_path)

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
