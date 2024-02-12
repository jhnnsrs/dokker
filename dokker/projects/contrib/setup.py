import asyncio
import json
import os
import shutil
import ssl
from enum import Enum
from shutil import copytree, ignore_patterns
from ssl import SSLContext
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

import aiohttp
import certifi
import jinja2
import yaml
from aioconsole import ainput
from pydantic import BaseModel, Field, validator

from dokker.cli import CLI, LogStream
from dokker.command import astream_command
from dokker.errors import DokkerError
from dokker.projects.base import BaseProject
from dokker.types import LogHelper
from typing import Type, TypeVar, Callable, Awaitable
from dokker.errors import DokkerError
from jinja2 import StrictUndefined


class RenderError(DokkerError):
    """An error that occurs when rendering a template."""
    pass

T = TypeVar("T", bound="BaseModel")


async def class_initializer(cls):
    return cls()


class SetupProject(BaseProject):
    """A project that is generated from a cookiecutter template.

    This project is a project that is generated from a cookiecutter template.
    It can be used to run a docker-compose file locally, copying the template
    to the .dokker directory, and running the docker-compose file from there.
    """
    setup_class: Type[T]
    defaults: Dict[str, Any] = Field(default_factory=dict)
    template_dir: str
    project_name: str


    base_dir: str = Field(default_factory=lambda: os.path.join(os.getcwd(), ".dokker"))
    compose_file: str = Field(default="docker-compose.yaml")
    setup_file: str = Field(default= "__setup__.yaml")
    _template_dir: str
    _project_dir: Optional[str] = None
    _outs: Optional[Dict[str, Any]] = None

    _setup: Optional[T] = None

    
    def render_template(self, setup: T, src: str, dest: str, overwrite: bool = False):
        with open(src, "r") as f:
            template_content = f.read()

        try:
            template = jinja2.Template(template_content, undefined=StrictUndefined)
            rendered_content = template.render(setup=setup)
        except Exception as e:
            print(f"Error in {src}")
            raise RenderError(f"Error rendering template {src}: {e}") from e 

        with open(dest, "w") as f:
            f.write(rendered_content)


    async def aget_cli(self, log: LogHelper) -> CLI:
        self._project_dir = os.path.join(self.base_dir, self.project_name)
        compose_file = os.path.join(self._project_dir, "docker-compose.yaml")
        if os.path.exists(compose_file):
            return CLI(
                compose_files=[compose_file],
            )
        else:
            raise DokkerError(f"Project `{self.project_name}` does not exist in {self.base_dir}. Call init first")

    async def aget_config(self, log: LogHelper) -> T:
        self._project_dir = os.path.join(self.base_dir, self.project_name)
        setup_file = os.path.join(self._project_dir, self.setup_file)
        if os.path.exists(setup_file):
            with open(setup_file, "r") as f:
                kwargs = yaml.safe_load(f)
            
            return self.setup_class(kwargs)
        else:
            raise DokkerError(f"Project `{self.project_name}` does not exist in {self.base_dir}. Call init first")  



    async def ainititialize(self) -> CLI:
        """A setup method for the project.

        Returns
        -------
        CLI
            The CLI to use for the project.
        """

        os.makedirs(self.base_dir, exist_ok=True)
        self._project_dir = os.path.join(self.base_dir, self.project_name)
        if os.path.exists(self._project_dir):
            raise DokkerError(f"Project `{self.project_name}` already exists in {self.base_dir}")
        

        self._setup = self.setup_class()
        



        os.makedirs(self.base_dir, exist_ok=True)
        os.makedirs(self._project_dir, exist_ok=True)

        # Copy the directory structure without files
        copytree(self.template_dir, self._project_dir, ignore=ignore_patterns("*.*"), dirs_exist_ok=True)

        for root, _, files in os.walk(self.template_dir):
            for file in files:
                if file.endswith(".yaml"):
                    src_path = os.path.join(root, file)

                    # Determine the destination path
                    relative_path = os.path.relpath(src_path, self.template_dir)
                    dest_path = os.path.join(self._project_dir, relative_path)

                    # Replace the following dictionary
                    try:
                        self.render_template(
                            self._setup, src_path, dest_path, not file.endswith("generic.yaml")
                        )
                    except Exception as e:
                        print(f"Error in {dest_path}")
                        raise e
                    
        setup_file = os.path.join(self._project_dir, self.setup_file)
        with open(setup_file, "w+") as f:
            yaml.dump(self._setup.dict(), f)

        compose_file = os.path.join(self._project_dir, "docker-compose.yaml")
        return CLI(
            compose_files=[compose_file],
        )
    
    async def atear_down(self) -> None:
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
            raise DokkerError(
                "SetupModel project not installed. Did you call initialize?"
            )

        if os.path.exists(self._project_dir):
            shutil.rmtree(self._project_dir)



    async def __aenter__(self):
        await self.ainitialize()


        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.atear_down()

        pass