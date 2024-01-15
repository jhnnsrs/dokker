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


class InitError(DokkerError):
    """Raised when cookiecutter was instructed to tear down a project, but the project was not initialized."""

    pass


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


class Repo(BaseModel):
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


class GPUForm(BaseModel):
    async def aretrieve(self, default: Dict[str, Any]) -> Dict[str, Any]:
        key = "gpu"
        value = await ainput(f"Should we use the gpu?: {key}\n")
        default[key] = value
        return default


default_registry = FormRegistry()
default_registry.register("check_gpu", GPUForm())


class KonstruktorProject(BaseModel):
    """A project that is generated from a cookiecutter template.

    This project is a project that is generated from a cookiecutter template.
    It can be used to run a docker-compose file locally, copying the template
    to the .dokker directory, and running the docker-compose file from there.
    """

    channel: str = "paper"
    repo_url: str = "https://raw.githubusercontent.com/jhnnsrs/konstruktor/master/repo/channels.json"
    base_dir: str = Field(default_factory=lambda: os.path.join(os.getcwd(), ".dokker"))
    compose_files: list = Field(default_factory=lambda: ["docker-compose.yml"])
    extra_context: dict = Field(default_factory=lambda: {})
    overwrite_if_exists: bool = False
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
    form_registry: FormRegistry = Field(default_factory=lambda: default_registry)

    async def _astread_stream(
        self,
        stream: asyncio.StreamReader,
        queue: asyncio.Queue,
        name: str,
    ) -> None:
        async for line in stream:
            await queue.put((name, line.decode("utf-8").strip()))

        await queue.put(None)

    async def astream_command(self, command: List[str]) -> LogStream:
        # Create the subprocess using asyncio's subprocess

        full_cmd = " ".join(map(str, command))

        proc = await asyncio.create_subprocess_shell(
            full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        if proc.stdout is None or proc.stderr is None:
            raise InitError("Could not create the subprocess.")

        queue = (
            asyncio.Queue()
        )  # type: asyncio.Queue[tuple[str, str]] # cannot use type annotation because of python 3.8
        # Create and start tasks for reading each stream

        try:
            readers = [
                asyncio.create_task(self._astread_stream(proc.stdout, queue, "STDOUT")),
                asyncio.create_task(self._astread_stream(proc.stderr, queue, "STDERR")),
            ]

            # Track the number of readers that are finished
            finished_readers = 0
            while finished_readers < len(readers):
                line = await queue.get()
                if line is None:
                    finished_readers += 1  # One reader has finished
                    continue
                yield line

            # Cleanup: cancel any remaining reader tasks
            for reader in readers:
                reader.cancel()
                try:
                    await reader
                except asyncio.CancelledError:
                    pass

        except asyncio.CancelledError:
            # Handle cancellation request
            proc.kill()
            await proc.wait()  # Wait for the subprocess to exit after receiving SIGINT

            # Cleanup: cancel any remaining reader tasks
            for reader in readers:
                reader.cancel()
                try:
                    await reader
                except asyncio.CancelledError:
                    pass

            raise

        except Exception as e:
            raise e

    async def afetch_repo(self) -> Repo:
        async with aiohttp.ClientSession(
            headers=self.headers,
            connector=aiohttp.TCPConnector(ssl=self.ssl_context),
        ) as session:
            # get json from endpoint
            async with session.get(self.repo_url) as resp:
                assert resp.status == 200

                raw_json = await resp.text()
                json_data = json.loads(raw_json)
                return Repo(**json_data)

    async def fetch_image(self, image: str) -> List[str]:
        logs: List[str] = []

        async for type, log in self.astream_command(["docker", "pull", image]):
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

        repo = await self.afetch_repo()

        try:
            channel = next(filter(lambda x: x.name == self.channel, repo.channels))
        except StopIteration:
            raise InitError(f"Channel {self.channel} not found in repo.")

        os.makedirs(self.base_dir, exist_ok=True)

        project_name = self.name or channel.name
        self._project_dir = os.path.join(self.base_dir, project_name)

        if os.path.exists(self._project_dir):
            print("Project already exists.")
            if self.overwrite_if_exists:
                print("Overwriting project.")
                shutil.rmtree(self._project_dir)

            else:
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
            # fetch builder

            logs = await self.fetch_image(channel.builder)

            setup_dict = {**channel.defaults, **self.extra_context}

            if not self.skip_forms:
                for form in channel.forms:
                    setup_dict = await self.arun_form(form, setup_dict)

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

            async for type, log in self.astream_command(cmd):
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

        if os.path.exists(self._project_dir):
            shutil.rmtree(self._project_dir)

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
