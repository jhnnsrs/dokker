import uuid
from .deployment import Deployment, HealthCheck
from typing import List, Optional, TYPE_CHECKING, Union
from dokker.projects.copy import CopyPathProject
from dokker.projects.local import LocalProject
from dokker.types import ValidPath

if TYPE_CHECKING:
    pass


def mirror(
    local_path: ValidPath,
    health_checks: Optional[List[HealthCheck]] = None,
    project_name: Optional[str] = None,
) -> Deployment:
    """Creates a Mirro Deployment

    A mirror deployment is a deployment that copies a local path to a temporary
    directory and runs it from there. This is useful for testing projects that
    are in production environments but should be tested locally and isolated
    from the source directory.

    Parameters
    ----------
    local_path : ValidPath
        The path to the project (will be copyied and on tear down deleted)
    health_checks : Optional[List[HealthCheck]], optional
        A list of health checks, by default None
    project_name : Optional[str], optional
        Optional Compose project name (``-p``); set a unique value to isolate this
        deployment from sibling stacks sharing the same compose directory. Defaults
        to the basename of the copied path.

    Returns
    -------
    Deployment
        The deployment
    """
    if health_checks is None:
        health_checks = []

    project = CopyPathProject(project_path=local_path, project_name=project_name)
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
    shutdown_timeout: Optional[int] = 4,
    project_name: Optional[str] = None,
) -> Deployment:
    """Creates a local deployment.

    A local deployment is a deployment that runs a docker-compose file
    locally. This is useful for testing a deployment that we do not want to
    control (e.g. calling down) on exit. It will stop the deployment
    on exit, but not tear it down nor call down

    Parameters
    ----------
    project_name : Optional[str], optional
        Optional Compose project name (``-p``); set a unique value to isolate this
        deployment from sibling stacks sharing the same compose directory. By default
        Compose derives it from the compose file's directory basename.
    """
    if not isinstance(docker_compose_file, list):
        docker_compose_file = [docker_compose_file]

    if health_checks is None:
        health_checks = []

    project = LocalProject(
        compose_files=docker_compose_file,
        project_name=project_name,
    )
    deployment = Deployment(
        project=project,
        health_checks=health_checks,
        shutdown_timeout=shutdown_timeout,
    )

    deployment.pull_on_enter = False
    deployment.down_on_exit = False
    deployment.stop_on_exit = True
    deployment.initialize_on_enter = True
    deployment.inspect_on_enter = True
    deployment.up_on_enter = False
    deployment.down_on_exit = False
    return deployment


def monitoring(
    docker_compose_file: Union[ValidPath, List[ValidPath]],
    health_checks: Optional[List[HealthCheck]] = None,
    project_name: Optional[str] = None,
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
    project_name : Optional[str], optional
        Optional Compose project name (``-p``); set a unique value to isolate this
        deployment from sibling stacks sharing the same compose directory. By default
        Compose derives it from the compose file's directory basename.

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
        project_name=project_name,
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
    shutdown_timeout: Optional[int] = 4,
    teardown_timeout: Optional[float] = 10.0,
    project_name: Optional[str] = None,
    remove_orphans: bool = True,
    remove_volumes: bool = True,
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
    shutdown_timeout : Optional[int], optional
        Grace period in seconds (docker's `-t`) passed to ``stop``/``down`` on
        teardown. Lower it (e.g. ``1``) when your services ignore SIGTERM so the
        teardown does not wait the full default grace period. None uses docker's
        default (10s).
    teardown_timeout : Optional[float], optional
        Overall wall-clock guard in seconds for the on-exit teardown, 60s by
        default, so a stuck ``docker compose down`` cannot block the test session
        forever. Pass None to disable.
    project_name : Optional[str], optional
        Compose project name (``-p``). Defaults to a unique random name so the
        deployment never collides with sibling stacks that share the same compose
        directory basename (which is Compose's default project name). Pass an
        explicit value to pin it.
    remove_orphans : bool, optional
        Remove orphan containers on ``down`` at teardown, by default True.
    remove_volumes : bool, optional
        Remove named volumes on ``down`` at teardown, by default True.

    Returns
    -------
    Deployment
        The deployment
    """
    if not isinstance(docker_compose_file, list):
        docker_compose_file = [docker_compose_file]
    if health_checks is None:
        health_checks = []
    if project_name is None:
        project_name = f"dokker-test-{uuid.uuid4().hex[:8]}"
    project = LocalProject(
        compose_files=docker_compose_file,
        project_name=project_name,
    )
    deployment = Deployment(
        project=project,
        health_checks=health_checks,
        shutdown_timeout=shutdown_timeout,
        teardown_timeout=teardown_timeout,
    )

    deployment.pull_on_enter = True
    deployment.initialize_on_enter = True
    deployment.inspect_on_enter = True
    deployment.health_on_enter = True
    deployment.up_on_enter = True
    deployment.down_on_exit = True
    deployment.stop_on_exit = True
    deployment.tear_down_on_exit = True
    deployment.remove_orphans_on_down = remove_orphans
    deployment.remove_volumes_on_down = remove_volumes

    return deployment
