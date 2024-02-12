from pydantic import BaseModel, Field
import os
from dokker.cli import CLI, LogStream
from typing import Optional, List
from dokker.errors import DokkerError
import shutil
import asyncio
import ssl
import certifi
from ssl import SSLContext
import aiohttp
import json
import yaml
from typing import Dict, Any, Protocol, runtime_checkable
from aioconsole import ainput
from enum import Enum
from pydantic import validator
from dokker.command import astream_command


class InitError(DokkerError):
    """Raised when cookiecutter was instructed to tear down a project, but the project was not initialized."""

    pass


class BasicType(str, Enum):
    STR = "str"
    INT = "in self.t"
    FLOAT = "float"
    BOOL = "bool"
    LIST = "list"


def set_nested_key_in_dict(d, key, value):
    if "." not in key:
        d[key] = value
        return

    key, rest = key.split(".", 1)
    if key not in d:
        d[key] = {}
    set_nested_key_in_dict(d[key], rest, value)


def get_nested_key_in_dict(d, key):
    if "." not in key:
        return d.get(key, None)

    key, rest = key.split(".", 1)
    return get_nested_key_in_dict(d.get(key, {}), rest)


class BasicField(BaseModel):
    key: str
    label: str
    description: Optional[str] = ""
    type: BasicType = BasicType.STR
    required: bool = False
    child: Optional["BasicField"] = None
    choices: Optional[List[Any]] = None

    async def aprompt(self: "BasicField", default: Dict[str, Any]) -> Dict[str, Any]:
        if self.type == BasicType.LIST:
            if self.child is None:
                raise Exception("Child field is required for list type")

            default_values = default.get(self.key, [])
            if not isinstance(default_values, list):
                raise Exception("Default value must be a list")

            if len(default_values) > 0:
                print(f"Current values: {default_values}")
                if await ainput("Change values? [y/n]: ") != "y":
                    return default

            list_values = []

            while True:
                # Default values do not work for child fields
                list_values.append(await self.child.aprompt({}))
                if await ainput("Add another? [y/n]: ") != "y":
                    break

            new_defaults = {**default}
            set_nested_key_in_dict(new_defaults, self.key, list_values)
            return new_defaults

        default_value: str = get_nested_key_in_dict(default, self.key)

        prompt_string = f"{self.label}: {self.description} "
        if default_value is not None:
            prompt_string += f" [{default_value}] "

        value = await ainput(prompt_string)
        if value == "" and default_value is not None:
            value = default_value
        else:
            if self.type == BasicType.INT:
                value = int(value)
            elif self.type == BasicType.FLOAT:
                value = float(value)
            elif self.type == BasicType.BOOL:
                value = value.lower() == "true"
            elif self.type == BasicType.LIST:
                value = value.split(",")
            elif self.type == BasicType.STR:
                value = str(value)
            else:
                raise Exception("Unknown type")

        new_defaults = {**default}
        set_nested_key_in_dict(new_defaults, self.key, value)
        return new_defaults


class BasicForm(BaseModel):
    welcome_message: str = "Please fill out the following fields:"
    fields: List[BasicField] = Field(default_factory=lambda: [])

    async def aretrieve(self, default: Dict[str, Any]) -> Dict[str, Any]:
        print(self.welcome_message)

        for field in self.fields:
            default = await field.aprompt(default)

        return default


class Feature(BaseModel):
    name: str
    description: str
    default: bool = False


class Channel(BaseModel):
    name: str
    title: str
    experimental: bool = False
    logo: Optional[str] = None
    long: Optional[str] = None
    description: Optional[str] = None
    features: List[Feature] = []
    preview: bool = False
    builder: str
    forms: List[str] = []
    defaults: dict = {}
    wizard: List[BasicForm] = []
    basic_forms: List[BasicForm] = []


class RepoModel(BaseModel):
    repo: str
    channels: List["Channel"]


@runtime_checkable
class Form(Protocol):
    async def aretrieve(self, default: Dict[str, Any]) -> Dict[str, Any]:
        ...


class FormRegistry(BaseModel):
    registered_forms: Dict[str, Form] = {}

    def register(self, name: str, form: Form) -> None:
        self.registered_forms[name] = form

    def get(self, name: str) -> Optional[Form]:
        try:
            return self.registered_forms[name]
        except KeyError:
            return None

    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True


@runtime_checkable
class Repo(Protocol):
    async def aload(self) -> RepoModel:
        ...


class RemoteRepo(BaseModel):
    url: str
    ssl_context: SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where()),
        description="SSL Context to use for the request",
    )
    headers: Optional[dict] = Field(
        default_factory=lambda: {"Content-Type": "application/json"}
    )

    async def aload(self) -> RepoModel:
        async with aiohttp.ClientSession(
            headers=self.headers,
            connector=aiohttp.TCPConnector(ssl=self.ssl_context),
        ) as session:
            # get json from endpoint
            async with session.get(self.url) as resp:
                assert resp.status == 200

                raw_json = await resp.text()
                json_data = json.loads(raw_json)
                return RepoModel(**json_data)

    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True


class ModelRepo(BaseModel):
    model: RepoModel

    async def aload(self) -> RepoModel:
        return self.model


class KonstruktorProject(BaseModel):
    """A project that is generated from a cookiecutter template.

    This project is a project that is generated from a cookiecutter template.
    It can be used to run a docker-compose file locally, copying the template
    to the .dokker directory, and running the docker-compose file from there.
    """

    channel: str = "paper"
    repo: Repo
    base_dir: str = Field(default_factory=lambda: os.path.join(os.getcwd(), ".dokker"))
    compose_files: list = Field(default_factory=lambda: ["docker-compose.yml"])
    extra_context: dict = Field(default_factory=lambda: {})
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
    form_registry: FormRegistry = Field(default_factory=lambda: FormRegistry())

    _project_dir: Optional[str] = None
    _outs: Optional[Dict[str, Any]] = None

    @validator("repo", pre=True)
    def validate_repo(cls, v) -> Repo:
        """Validate the repo type."""

        if isinstance(v, RepoModel):
            return ModelRepo(model=v)
        elif isinstance(v, str):
            return RemoteRepo(url=v)
        elif isinstance(v, Repo):
            return v
        else:
            raise ValueError("Invalid repo type")

    async def fetch_image(self, image: str) -> List[str]:
        logs: List[str] = []

        async for type, log in astream_command(["docker", "pull", image]):
            logs.append(log)

        return logs

    async def arun_form(self, form: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
        form = self.form_registry.get(form)
        if form is None:
            return defaults
        return await form.aretrieve(defaults)

    async def ainititialize(self) -> CLI:
        """A setup method for the project.

        Returns
        -------
        CLI
            The CLI to use for the project.
        """

        repo = await self.repo.aload()

        try:
            channel = next(filter(lambda x: x.name == self.channel, repo.channels))
        except StopIteration:
            raise InitError(
                f"Channel {self.channel} not found in repo. Available are {', '.join(map(lambda x: x.name, repo.channels))}"
            )

        os.makedirs(self.base_dir, exist_ok=True)

        project_name = self.name or channel.name
        self._project_dir = os.path.join(self.base_dir, project_name)

        if os.path.exists(self._project_dir):
            if self.error_if_exists and not self.reinit_if_exists:
                raise InitError("Project already exists.")

            if not self.reinit_if_exists:
                print("Project already exists. Skipping initialization.")
                compose_file = os.path.join(self._project_dir, "docker-compose.yaml")
                if not os.path.exists(compose_file):
                    raise Exception(
                        "No docker-compose.yml found in the template. It appears that the template is not a valid dokker template. User overwrite_if_exists to overwrite the project."
                    )

                return CLI(
                    compose_files=[compose_file],
                )
            else:
                print("Project already exists. Overwriting.")
                shutil.rmtree(self._project_dir)

        setup_dict = {**channel.defaults, **self.extra_context}

        if not self.skip_forms:
            for form in channel.forms:
                setup_dict = await self.arun_form(form, setup_dict)

            for basic_form in channel.basic_forms:
                setup_dict = await basic_form.aretrieve(setup_dict)

        print("Fetching builder image...")
        logs = await self.fetch_image(channel.builder)

        os.makedirs(self._project_dir, exist_ok=True)
        # create setup.yaml
        setup_yaml = os.path.join(self._project_dir, "setup.yaml")

        with open(setup_yaml, "w") as f:
            yaml.dump(setup_dict, f)

        logs = []

        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{self._project_dir}:/app/init",
        ]

        if os.name == "posix":
            cmd += ["--user", f"{os.getuid()}:{os.getgid()}"]

        cmd += [channel.builder]

        async for type, log in astream_command(cmd):
            logs.append(log)

        compose_file = os.path.join(self._project_dir, "docker-compose.yaml")
        if not os.path.exists(compose_file):
            raise Exception(
                "No docker-compose.yml found in the template. It appears that the template is not a valid dokker template."
            )

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
