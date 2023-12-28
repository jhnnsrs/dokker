from cookiecutter.main import cookiecutter
from dokker.project import Project
from pydantic import BaseModel, Field
import os
from typing import List, Optional, Dict, Protocol, runtime_checkable, Any
import shutil


class CopyPathProject(BaseModel):
    project_path: str
    project_name: Optional[str]
    base_dir: str = Field(default_factory=lambda: os.path.join(os.getcwd(), ".dokker"))
    overwrite: bool = False

    async def aget_client_params(self) -> Dict[str, Any]:
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
