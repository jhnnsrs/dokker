from cookiecutter.main import cookiecutter
from dokker.project import Project
from pydantic import BaseModel, Field
import os
from typing import List, Optional, Dict, Protocol, runtime_checkable, Any


class CookieCutterProject(BaseModel):
    repo_url: str
    base_dir: str = Field(default_factory=lambda: os.path.join(os.getcwd(), ".dokker"))
    compose_files: list = Field(default_factory=lambda: ["docker-compose.yml"])
    extra_context: dict = Field(default_factory=lambda: {})
    overwrite_if_exists: bool = False

    async def aget_client_params(self) -> Dict[str, Any]:
        os.makedirs(self.base_dir, exist_ok=True)

        project_dir = cookiecutter(
            self.repo_url,
            no_input=True,
            output_dir=self.base_dir,
            extra_context=self.extra_context,
            overwrite_if_exists=self.overwrite_if_exists,
        )

        compose_file = os.path.join(project_dir, "docker-compose.yml")
        if not os.path.exists(compose_file):
            raise Exception(
                "No docker-compose.yml found in the template. It appears that the template is not a valid dokker template."
            )

        return {
            "compose_files": [compose_file],
        }

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
