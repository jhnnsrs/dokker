from .deployment import Deployment, HealthCheck
from typing import List, Optional, TYPE_CHECKING, Union
from dokker.projects.copy import CopyPathProject
from dokker.projects.local import LocalProject
from dokker.types import ValidPath

if TYPE_CHECKING:
    pass


def mirror(
    local_path: ValidPath, health_checks: Optional[List[HealthCheck]] = None
) -> Deployment:
    """Creates a Mirro Deployment

    A mirror deployment is a deployment that copies a local path to a temporary
    directory and runs it from there. This is useful for testing projects that
    are in production environments but should be tested locally.

    Parameters
    ----------
    local_path : ValidPath
        The path to the project (will be copyied and on tear down deleted)
    health_checks : Optional[List[HealthCheck]], optional
        _description_, by default None

    Returns
    -------
    Deployment
        The deployment
    """
    if health_checks is None:
        health_checks = []

    project = CopyPathProject(project_path=local_path)
    deployment = Deployment(
        project=project,
        health_checks=health_checks,
    )

    deployment.pull_on_enter = False
    deployment.down_on_exit = False
    deployment.stop_on_exit = False

    return deployment


def local(
    docker_compose_file: Union[ValidPath, List[ValidPath]],
    health_checks: Optional[List[HealthCheck]] = None,
) -> Deployment:
    """Creates a local deployment.

    A local deployment is a deployment that runs a docker-compose file
    locally. This is useful for testing a deployment that we do not want to
    control (e.g. calling down) on exit.
    """
    if not isinstance(docker_compose_file, list):
        docker_compose_file = [docker_compose_file]

    if health_checks is None:
        health_checks = []

    project = LocalProject(
        compose_files=docker_compose_file,
    )
    deployment = Deployment(
        project=project,
        health_checks=health_checks,
    )

    deployment.pull_on_enter = False
    deployment.down_on_exit = False
    deployment.stop_on_exit = True
    deployment.initialize_on_enter = True
    deployment.up_on_enter = True
    deployment.down_on_exit = False
    return deployment


def monitoring(
    docker_compose_file: Union[ValidPath, List[ValidPath]],
    health_checks: Optional[List[HealthCheck]] = None,
) -> Deployment:
    """Generates a monitoring deployment.

    A monitoring deployment is a deployment that never directly interacts with the
    docker-compose CLI. This is useful for inspect / monitoring a deployment
    that is running in production.

    Parameters
    ----------
    docker_compose_file : Union[ValidPath, List[ValidPath]]
        The docker-compose file to run.
    health_checks : Optional[List[HealthCheck]], optional
        The health checks to run, by default None

    Returns
    -------
    Deployment
        The deployment
    """
    if not isinstance(docker_compose_file, list):
        docker_compose_file = [docker_compose_file]
    if health_checks is None:
        health_checks = []
    project = LocalProject(
        compose_files=docker_compose_file,
    )
    deployment = Deployment(
        project=project,
        health_checks=health_checks,
    )

    deployment.pull_on_enter = False
    deployment.down_on_exit = False
    deployment.stop_on_exit = False
    deployment.health_on_enter = True
    deployment.up_on_enter = False

    return deployment


def testing(
    docker_compose_file: Union[ValidPath, List[ValidPath]],
    health_checks: Optional[List[HealthCheck]] = None,
) -> Deployment:
    """Generates a testing deployment.

    A testing deployment is a deployment that runs a docker-compose file, locally
    and takes care of pulling, initializing, and tearing down the deployment.

    Parameters
    ----------
    docker_compose_file : Union[ValidPath, List[ValidPath]]
        The docker-compose file to run.
    health_checks : Optional[List[HealthCheck]], optional
        The health checks to run, by default None

    Returns
    -------
    Deployment
        The deployment
    """
    if not isinstance(docker_compose_file, list):
        docker_compose_file = [docker_compose_file]
    if health_checks is None:
        health_checks = []
    project = LocalProject(
        compose_files=docker_compose_file,
    )
    deployment = Deployment(
        project=project,
        health_checks=health_checks,
    )

    deployment.pull_on_enter = True
    deployment.initialize_on_enter = True
    deployment.up_on_enter = True
    deployment.down_on_exit = True
    deployment.stop_on_exit = True
    deployment.tear_down_on_exit = True

    return deployment
