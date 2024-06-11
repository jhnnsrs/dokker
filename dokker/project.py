from typing import Protocol, runtime_checkable, Dict, Any
from .cli import CLI


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

    async def ainititialize(self) -> CLI:
        """A setup method for the project.

        Returns
        -------
        CLI
            The CLI to use for the project.
        """
        ...

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
        """A setup method for the project.

        Returns:
            Optional[List[str]]: A list of logs from the setup process.
        """
        ...
