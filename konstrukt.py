from dokker.projects.contrib.konstruktor import KonstruktorProject, RepoModel
from tests.utils import build_relative
import json
import asyncio


x = build_relative("repos", "konstruktor.json")

with open(x, "r") as f:
    data = json.load(f)


project = KonstruktorProject(
    channel="beta",
    repo=RepoModel(**data),
    reinit_if_exists=True
)

asyncio.run(project.ainititialize())
