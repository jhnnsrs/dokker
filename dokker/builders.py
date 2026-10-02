import os
import re
import uuid
from .checks import Check
from .deployment import Deployment, PolicyName
from typing import List, Literal, Optional, Union
from dokker.projects.copy import CopyPathProject
from dokker.projects.local import LocalProject
from dokker.types import ValidPath

# The file names compose looks for on its own when given no `--file`. A local()
# of one of these keeps compose's default project name (the directory basename),
# so dokker and a hand-typed `docker compose up` in that directory agree on the
# project -- and existing stacks/volumes keep their names.
COMPOSE_DEFAULT_FILENAMES = frozenset({"compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"})


def _normalize_project_name(name: str) -> str:
    """Coerce *name* into what compose accepts: lowercase ``[a-z0-9_-]``, starting with a letter or digit."""
    name = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-_")
    return name or "dokker"


def derive_project_name(compose_files: List[ValidPath]) -> str:
    """Derive a stable compose project name for *compose_files*.

    Compose's own default is the parent directory's basename, which means two
    sibling compose files in one directory silently share a project: the second
    ``up()`` recreates the first's services instead of adding its own. For the
    default file names (``compose.yaml``, ``docker-compose.yaml``, ...) that
    convention is kept, because it is the name a hand-typed ``docker compose up``
    in the same directory would use and existing stacks depend on it. Any other
    file gets ``<directory>-<file stem>`` (e.g. ``battle-a-compose``), so
    siblings stay apart while the name remains deterministic across sessions --
    a ``local()`` stack must find its own stopped containers again next time.

    Like compose, the first file decides.
    """
    first = os.path.abspath(str(compose_files[0]))
    directory = os.path.basename(os.path.dirname(first)) or "root"
    filename = os.path.basename(first)
    if filename in COMPOSE_DEFAULT_FILENAMES:
        return _normalize_project_name(directory)
    stem = filename.rsplit(".", 1)[0]
    return _normalize_project_name(f"{directory}-{stem}")


def mirror(
    local_path: ValidPath,
    health_checks: Optional[List[Check]] = None,
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
    health_checks : Optional[List[Check]], optional
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
    health_checks: Optional[List[Check]] = None,
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
        Compose project name (``-p``). Defaults to ``derive_project_name``: the
        compose file's directory basename for the standard file names
        (``compose.yaml``, ``docker-compose.yaml``, ...), exactly as compose
        itself would pick, and ``<directory>-<file stem>`` for any other file so
        that sibling compose files in one directory do not merge into a single
        project. Deterministic, so the stack is found again next session.
    policy : PolicyName, optional
        Teardown policy, ``"local"`` by default (stop on exit, keep containers and
        volumes). Override per-deployment, or per call via ``up(down_on_exit=...)``.
    """
    if not isinstance(docker_compose_file, list):
        docker_compose_file = [docker_compose_file]

    if health_checks is None:
        health_checks = []

    if project_name is None:
        project_name = derive_project_name(docker_compose_file)

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
    health_checks: Optional[List[Check]] = None,
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
    health_checks : Optional[List[Check]], optional
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
    health_checks: Optional[List[Check]] = None,
    shutdown_timeout: Optional[int] = 4,
    teardown_timeout: Optional[float] = 10.0,
    project_name: Optional[str] = None,
    remove_orphans: bool = True,
    remove_volumes: bool = True,
    policy: PolicyName = "testing",
    reap_stale: bool = True,
    remove_images: Optional[Literal["local", "all"]] = "local",
) -> Deployment:
    """Generates a testing deployment.

    A testing deployment runs a docker-compose file locally with sensible defaults
    for integration tests: a unique project name, bounded teardown timeouts, and
    removal of orphans, volumes and the images built for the project on ``down``. Nothing happens on enter; from inside the
    context manager call ``pull()``, ``up()``, ``inspect()`` and ``check_health()``.
    Under the default ``"testing"`` policy a bare ``up()`` brings the stack down
    (removing volumes and orphans) and tears the project down on exit.

    Because that promise dies with the process (a SIGKILLed or interrupted test
    run never reaches its teardown), ``up()`` also labels the stack with the
    owning PID and first removes the stacks earlier, now-dead dokker processes
    left behind on this host. Do not clean strays with a ``docker ps | grep
    dokker-test | xargs docker rm -f`` sweep: it cannot tell a stray from a
    stack a live run in another terminal is using, and removing that one turns
    a green suite into hundreds of "database vanished" errors. Use
    ``dokker.reap_stale()`` instead.

    Parameters
    ----------
    docker_compose_file : Union[ValidPath, List[ValidPath]]
        The docker-compose file to run.
    health_checks : Optional[List[Check]], optional
        The health checks to run, by default None
    shutdown_timeout : Optional[int], optional
        Grace period in seconds (docker's `-t`) passed to ``stop``/``down`` on
        teardown. Lower it (e.g. ``1``) when your services ignore SIGTERM so the
        teardown does not wait the full default grace period. None uses docker's
        default (10s).
    teardown_timeout : Optional[float], optional
        Overall wall-clock guard in seconds for the on-exit teardown, 10s by
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
    reap_stale : bool, optional
        Remove, before ``up()``, the stacks left behind by dead dokker processes
        on this host (see ``dokker.reap_stale``), by default True. Only stacks
        that were themselves going to be downed on exit are candidates; kept
        (``down_on_exit=False``) and ``local()`` stacks are never touched.
    remove_images : Optional[Literal["local", "all"]], optional
        Which images ``down`` removes at teardown, ``"local"`` by default: the
        images compose built for this project and named after it
        (``<project>-<service>``, for a service with ``build:`` and no
        ``image:``). With a random project name every run tags a new pair that
        nothing will use again; left alone they pile up, each holding on to the
        layers of the sources it was built from. The build cache is not touched,
        so the next run still builds from cache. Images a service names itself
        (``image:``) and pulled images are kept. ``"all"`` removes those too;
        None keeps everything.

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
        reap_stale=reap_stale,
    )

    deployment.remove_orphans_on_down = remove_orphans
    deployment.remove_volumes_on_down = remove_volumes
    deployment.remove_images_on_down = remove_images

    return deployment


# Its name starts with "test", so pytest would otherwise try to *collect* this
# builder as a test case in any module that imports it -- reporting a confusing
# "fixture 'docker_compose_file' not found" error for a function that is not a
# test at all. Importing `testing` into a test module is the documented usage,
# so opt it out of collection.
testing.__test__ = False  # type: ignore[attr-defined]
