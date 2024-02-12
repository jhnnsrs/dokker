import asyncio
import json
import os
import shutil
import ssl
from enum import Enum
from ssl import SSLContext
from typing import (
    Any,
    Dict,
    Generic,
    List,
    Optional,
    Protocol,
    TypeVar,
    runtime_checkable,
)

import aiohttp
import certifi
import yaml
from aioconsole import ainput
from pydantic import BaseModel, Field, validator

from dokker.cli import CLI, LogStream
from dokker.command import astream_command
from dokker.errors import DokkerError

T = TypeVar("T", bound=BaseModel)

class JinjaProject(BaseModel, Generic[T]):
    """A project that is generated from a cookiecutter template.

    This project is a project that is generated from a cookiecutter template.
    It can be used to run a docker-compose file locally, copying the template
    to the .dokker directory, and running the docker-compose file from there.
    """
    setup: T
    template_dir: str 
    base_dir: str = Field(default_factory=lambda: os.path.join(os.getcwd(), ".dokker"))
    compose_files: list = Field(default_factory=lambda: ["docker-compose.yml"])
    error_if_exists: bool = False
    reinit_if_exists: bool = False
    ssl_context: SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where()),
        description="SSL Context to use for the request",
    )
    headers: Optional[dict] = Field(
        default_factory=lambda: {"Content-Type": "application/json"}
    )
    name: Optional[str] = None
    skip_forms: bool = False

    _project_dir: Optional[str] = None
    _outs: Optional[Dict[str, Any]] = None


    async def ainititialize(self) -> CLI:
        """A setup method for the project.

        Returns
        -------
        CLI
            The CLI to use for the project.
        """

        import jinja2

        if self._project_dir:
            pass

        

        return CLI(
            compose_files=[compose_file],
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
        try:
            await cli.adown()
        except Exception as e:
            print(e)
            pass

        if not self._project_dir:
            raise InitError(
                "Cookiecutter project not installed. Did you call initialize?"
            )

        print("Removing project directory...")
        if os.path.exists(self._project_dir):
            shutil.rmtree(self._project_dir)

        print("Removed project directory.")

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
        extra = "forbid"
