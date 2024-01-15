from dokker import local, HealthCheck, Deployment 
import pytest
from dokker.projects.contrib.konstruktor import KonstruktorProject


project = KonstruktorProject()
deployment = Deployment(
    project=project,
)

project.overwrite_if_exists = True

deployment.pull_on_enter = False
deployment.down_on_exit = False
deployment.stop_on_exit = True
deployment.initialize_on_enter = True
deployment.up_on_enter = True
deployment.down_on_exit = False




with deployment:
    # do something with redis

    print("hello world")

    pass
