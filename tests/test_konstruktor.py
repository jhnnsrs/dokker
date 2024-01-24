from dokker import local, HealthCheck, Deployment 
import pytest
from dokker.projects.contrib.konstruktor import KonstruktorProject, RepoModel
from .utils import build_relative
import json

async def test_konstruktor():


    project = KonstruktorProject(
        channel="paper",
        repo="https://raw.githubusercontent.com/jhnnsrs/konstruktor/master/repo/channels.json"
    )

    await project.ainititialize()

@pytest.mark.validate
def test_validate_konstruktor():

    x = build_relative("repos", "konstruktor.json")

    with open(x, "r") as f:
        data = json.load(f)

    RepoModel(**data)






