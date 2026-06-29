import uuid
from .deployment import Deployment, HealthCheck, PolicyName
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
    policy: PolicyName = "testing",
) -> Deployment:
    """Creates a Mirror Deployment

    A mirror deployment copies a local path to a temporary directory and runs it
    from there. This is useful for testing projects that live in production
    environments but should be tested locally and isolated from the source
    directory.

    Nothing happens on enter; drive the lifecycle from inside the context manager
    (``up()``, ``check_health()``, ...). Under the default ``"testing"`` policy a
    bare ``up()`` downs the stack and the temporary copy is removed on exit.

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
    policy : PolicyName, optional
        Teardown policy, ``"testing"`` by default (down + remove the temp-dir copy
        on exit). Override to e.g. ``"manual"`` to drive teardown yourself.

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
        policy=policy,
    )

    return deployment


def local(
    docker_compose_file: Union[ValidPath, List[ValidPath]],
    health_checks: Optional[List[HealthCheck]] = None,
    shutdown_timeout: Optional[int] = 4,
    project_name: Optional[str] = None,
    policy: PolicyName = "local",
) -> Deployment:
    """Creates a local deployment.

    A local deployment runs a docker-compose file locally. Nothing happens on
    enter; you drive the lifecycle from inside the context manager. Under the
    default ``"local"`` policy a bare ``up()`` stops the stack on exit but keeps
    the containers and any data volumes; pass ``up(down_on_exit=True)`` for a
    full removal.

    Parameters
    ----------
    project_name : Optional[str], optional
        Optional Compose project name (``-p``); set a unique value to isolate this
        deployment from sibling stacks sharing the same compose directory. By default
        Compose derives it from the compose file's directory basename.
    policy : PolicyName, optional
        Teardown policy, ``"local"`` by default (stop on exit, keep containers and
        volumes). Override per-deployment, or per call via ``up(down_on_exit=...)``.
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
        policy=policy,
        # A local stack is yours to keep: don't wipe data volumes/orphans even
        # when you explicitly down it.
        remove_orphans_on_down=False,
        remove_volumes_on_down=False,
    )

    return deployment


def monitoring(
    docker_compose_file: Union[ValidPath, List[ValidPath]],
    health_checks: Optional[List[HealthCheck]] = None,
    project_name: Optional[str] = None,
    policy: PolicyName = "monitoring",
) -> Deployment:
    """Generates a monitoring deployment.

    A monitoring deployment never changes the stack via the docker-compose CLI.
    This is useful for inspecting / monitoring a deployment that is already
    running in production. Nothing happens on enter or exit (the ``"monitoring"``
    policy); from inside the context manager call ``inspect()`` and
    ``check_health()`` to observe it.

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
    policy : PolicyName, optional
        Teardown policy, ``"monitoring"`` by default (never changes the stack on exit).

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
        policy=policy,
    )

    return deployment


def testing(
    docker_compose_file: Union[ValidPath, List[ValidPath]],
    health_checks: Optional[List[HealthCheck]] = None,
    shutdown_timeout: Optional[int] = 4,
    teardown_timeout: Optional[float] = 10.0,
    project_name: Optional[str] = None,
    remove_orphans: bool = True,
    remove_volumes: bool = True,
    policy: PolicyName = "testing",
) -> Deployment:
    """Generates a testing deployment.

    A testing deployment runs a docker-compose file locally with sensible defaults
    for integration tests: a unique project name, bounded teardown timeouts, and
    orphan/volume removal on ``down``. Nothing happens on enter; from inside the
    context manager call ``pull()``, ``up()``, ``inspect()`` and ``check_health()``.
    Under the default ``"testing"`` policy a bare ``up()`` brings the stack down
    (removing volumes and orphans) and tears the project down on exit.

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
    policy : PolicyName, optional
        Teardown policy, ``"testing"`` by default (down + remove volumes/orphans +
        tear the project down on exit).

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
        policy=policy,
    )

    deployment.remove_orphans_on_down = remove_orphans
    deployment.remove_volumes_on_down = remove_volumes

    return deployment
