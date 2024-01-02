from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Protocol, runtime_checkable, Any
from pathlib import Path
from .compose_spec import ComposeSpec
from .cli import CLI


@runtime_checkable
class Project(Protocol):
    """A Project

    Projects are the core representation of the organization of a
    project that can be run with the docker CLI. When a project is
    setup by the Setup class, it can decide to setup the project asy
    nchronousl, e.g by cloning a git repository, or copiying a
    directory into the .dokker directory. The project can also
    implement methods that will be run before and after certain
    docker-compose commands are run. For example, a project can
    implement a method that will be run before the docker-compose
    up command is run.
    """

    async def ainititialize(self) -> CLI:
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
