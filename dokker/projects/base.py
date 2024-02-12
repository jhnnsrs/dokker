from dokker.cli import CLI
from pydantic import BaseModel
from dokker.types import LogHelper

class BaseProject(BaseModel):
    """ THe base class for all pydantic based Projects"""


    async def ainititialize(self, log: LogHelper,  **kwargs) -> CLI:
        """A setup method for the project.

        Returns
        -------
        CLI
            The CLI to use for the project.
        """

        raise NotImplementedError("Please implement this method.")
    
    async def adoes_exist(self, log: LogHelper) -> bool:
        """A setup method for the project.

        Returns
        -------
        CLI
            The CLI to use for the project.
        """

        raise NotImplementedError("Please implement this method.")
    

    async def aget_health_checks(self, log: LogHelper) -> list:
        """A setup method for the project.

        Returns
        -------
        CLI
            The CLI to use for the project.
        """

        raise NotImplementedError("Please implement this method.")

    async def atear_down(self, cli: CLI, log: LogHelper) -> None:
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
        raise NotImplementedError("Please implement this method.")

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

    class Config:
        """pydantic config class for CookieCutterProject"""

        arbitrary_types_allowed = True
        underscore_attrs_are_private = True
        extra = "forbid"
