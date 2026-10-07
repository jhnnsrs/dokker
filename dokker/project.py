from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Protocol, Union, runtime_checkable
from .cli import CLI
from .types import LogStream


@runtime_checkable
class Project(Protocol):
    """Where a deployment's compose project comes from.

    A project prepares the stack before anything is run -- by pointing at a
    compose file, copying a directory, generating one -- and hands back the
    ``CLI`` that addresses it. It can also run code before the compose commands
    of the same name.

    A project that has to start or stop its stack some other way than
    ``docker compose`` does additionally implements ``StartsItself``,
    ``StopsItself``, ``DownsItself`` or ``PullsItself``.
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
        """Run before the deployment's ``pull``."""
        ...

    async def abefore_up(self) -> None:
        """Run before the deployment's ``up``."""
        ...

    async def abefore_enter(self) -> None:
        """Run before the deployment is entered. Kept for projects that define it; a deployment does not call it."""
        ...

    async def abefore_down(self) -> None:
        """Run before the deployment's ``down``."""
        ...

    async def abefore_stop(self) -> None:
        """Run before the deployment's ``stop``."""
        ...


@dataclass(frozen=True)
class UpOptions:
    """What a deployment's ``up`` was asked for, handed to a project that starts itself."""

    detach: bool = True
    services: Union[List[str], str, None] = None
    build: bool = False
    wait: bool = False
    wait_timeout: Optional[int] = None
    force_recreate: bool = False
    no_recreate: bool = False
    no_build: bool = False
    remove_orphans: bool = False
    renew_anon_volumes: bool = False
    pull: Optional[Literal["always", "missing", "never"]] = None
    scales: Dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class DownOptions:
    """What a deployment's ``down`` resolved to, handed to a project that downs itself.

    Every value has already fallen back to the deployment's own setting
    (``shutdown_timeout``, ``remove_volumes_on_down``, ...), so none of them
    says whether the caller asked for it.
    """

    timeout: Optional[int] = None
    volumes: bool = False
    remove_orphans: bool = False
    remove_images: Optional[Literal["local", "all"]] = None


@dataclass(frozen=True)
class PullOptions:
    """What a deployment's ``pull`` was asked for, handed to a project that pulls itself."""

    services: Union[List[str], str, None] = None
    ignore_pull_failures: bool = False
    include_deps: bool = False
    quiet: bool = False


@runtime_checkable
class StartsItself(Protocol):
    """A project that brings its own stack up.

    The deployment runs this instead of ``docker compose up``. Everything
    around it stays the deployment's: the ``abefore_up`` hook, the logger, the
    teardown registered for exit. Only the owner labels are left out -- they
    are stamped through a compose override this ``up`` would never read -- so
    such a project removes the strays of dead processes itself.

    Raise ``ProjectError`` for an option that cannot be honoured.
    """

    def astream_up(self, cli: CLI, options: UpOptions) -> LogStream:
        """Start the stack, yielding ``(stream, line)`` as it goes."""
        ...


@runtime_checkable
class StopsItself(Protocol):
    """A project that stops its own stack, instead of ``docker compose stop``."""

    def astream_stop(self, cli: CLI, timeout: Optional[int]) -> LogStream:
        """Stop the stack, yielding ``(stream, line)`` as it goes."""
        ...


@runtime_checkable
class DownsItself(Protocol):
    """A project that takes its own stack down, instead of ``docker compose down``."""

    def astream_down(self, cli: CLI, options: DownOptions) -> LogStream:
        """Remove the stack, yielding ``(stream, line)`` as it goes."""
        ...


@runtime_checkable
class PullsItself(Protocol):
    """A project that pulls its own images, instead of ``docker compose pull``."""

    def astream_pull(self, cli: CLI, options: PullOptions) -> LogStream:
        """Pull the images, yielding ``(stream, line)`` as it goes."""
        ...
