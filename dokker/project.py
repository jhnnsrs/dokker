from typing import Protocol, runtime_checkable, Dict, Any, List
from .cli import CLI
from dokker.types import LogHelper
from dokker.types import HealthCheck


@runtime_checkable
class Project(Protocol):
    """A Projectaget_values, it can decide to setup the project asy
    nchronousl, e.g by cloning a git repository, or copiying a
    directory into the .dokker directory. The project can also
    implement methods that will be run before and after certain
    docker-compose commands are run. For example, a project can
    implement a method that will be run before the docker-compose
    up command is run.
    """
    async def aget_config(self, helper: LogHelper) -> Dict[str, Any]:
        """A setup method for the project.

        Returns
        -------
        Dict[str, Any]
            The configuration for the project.
        """
        ...


    async def ainititialize(self, helper: LogHelper) -> CLI:
        """A setup method for the project.

        Returns
        -------
        CLI
            The CLI to use for the project.
        """
        ...

    async def aget_cli(self, helper: LogHelper) -> CLI:
        """A setup method for the project.

        Returns
        -------
        bool
            Whether the project is valid.
        """
        ...

    async def aget_health_checks(self, helper: LogHelper) -> List[HealthCheck]:
        """A setup method for the project.

        Returns
        -------
        bool
            Whether the project is valid.
        """
        ...



    async def atear_down(self, helper: LogHelper) -> None:
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
        ...



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
        """A selisttup method for the project.

        Returns:
            Optional[List[str]]: A list of logs from the setup process.
        """
        ...
