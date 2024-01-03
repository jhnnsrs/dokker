from cookiecutter.main import cookiecutter
from pydantic import BaseModel, Field
import os
from dokker.cli import CLI
from typing import Optional
from dokker.errors import DokkerError
import shutil


class CookieNotInstalled(DokkerError):
    """Raised when cookiecutter was instructed to tear down a project, but the project was not initialized."""
    pass


class CookieCutterProject(BaseModel):
    """A project that is generated from a cookiecutter template.

    This project is a project that is generated from a cookiecutter template.
    It can be used to run a docker-compose file locally, copying the template
    to the .dokker directory, and running the docker-compose file from there.
    """

    repo_url: str
    base_dir: str = Field(default_factory=lambda: os.path.join(os.getcwd(), ".dokker"))
    compose_files: list = Field(default_factory=lambda: ["docker-compose.yml"])
    extra_context: dict = Field(default_factory=lambda: {})
    overwrite_if_exists: bool = False

    _project_dir: Optional[str] = None

    async def ainititialize(self) -> CLI:
        """A setup method for the project.

        Returns
        -------
        CLI
            The CLI to use for the project.
        """
        os.makedirs(self.base_dir, exist_ok=True)

        self._project_dir = cookiecutter(
            self.repo_url,
            no_input=True,
            output_dir=self.base_dir,
            extra_context=self.extra_context,
            overwrite_if_exists=self.overwrite_if_exists,
        )
        assert isinstance(self._project_dir, str), "cookiecutter should return a string"

        compose_file = os.path.join(self._project_dir, "docker-compose.yml")
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
        if not self._project_dir:
            raise CookieNotInstalled("Cookiecutter project not installed. Did you call initialize?")
        
        if os.path.exists(self._project_dir):
            shutil.rmtree(self._project_dir)

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

    class Config:
        """pydantic config class for CookieCutterProject"""
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True