"""Docker-backed tests for the things only real docker can prove about teardown.

The fast, branch-level lifecycle logic is covered without docker in
``tests/test_lifecycle.py``. Here we assert the real-world effects: that a
default ``down`` actually removes named volumes, that a failing body still tears
the stack down, and that ``mirror`` removes both its containers and its temp-dir
copy on exit.

Run with::

    pytest -m integration -k teardown
"""

import os
import subprocess
import uuid

import pytest

# ``testing`` is imported under an alias so pytest does not collect the builder
# itself as a test (its name matches the default ``test*`` collection pattern).
from dokker import mirror
from dokker import testing as make_testing

pytestmark = pytest.mark.integration

VOLUME_COMPOSE = "tests/configs/volume-compose.yaml"
MIRROR_SRC = "tests/configs/mirror-src"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _volumes_for(project: str) -> list[str]:
    """Names of docker volumes belonging to ``project`` (``<project>_<vol>``)."""
    out = subprocess.run(
        ["docker", "volume", "ls", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [line for line in out.splitlines() if line.startswith(project)]


def _containers_for(project: str) -> list[str]:
    """Names of containers (any state) belonging to ``project``."""
    out = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name={project}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def test_down_removes_named_volume_by_default():
    """A default ``down`` (down_on_exit) removes the project's named volume."""
    project = _unique("dokker-vol")
    # bare up() under the default "testing" policy must down + remove volumes on exit
    with make_testing(VOLUME_COMPOSE, project_name=project, shutdown_timeout=1) as deployment:
        deployment.up()
        assert _volumes_for(project), "the named volume should exist while the stack is up"

    assert not _volumes_for(project), "the named volume should be gone after a default down"
    assert not _containers_for(project), "no containers should survive teardown"


def test_down_keeps_volume_when_disabled():
    """With ``remove_volumes=False`` the volume survives the on-exit down."""
    project = _unique("dokker-vol")
    try:
        with make_testing(
            VOLUME_COMPOSE,
            project_name=project,
            shutdown_timeout=1,
            remove_volumes=False,
        ) as deployment:
            deployment.up(down_on_exit=True)

        survivors = _volumes_for(project)
        assert survivors, "the volume should survive a down when remove_volumes=False"
    finally:
        # Clean up the surviving volume so the test leaves nothing behind.
        for name in _volumes_for(project):
            subprocess.run(["docker", "volume", "rm", "-f", name], check=False)


def test_body_exception_still_tears_down_containers():
    """An error inside the block must not leak containers."""

    class _Boom(Exception):
        pass

    project = _unique("dokker-exc")
    with pytest.raises(_Boom):
        with make_testing(VOLUME_COMPOSE, project_name=project, shutdown_timeout=1) as deployment:
            deployment.up(down_on_exit=True)
            raise _Boom("failure inside the deployment body")

    assert not _containers_for(project), "teardown must run even when the body raises"
    assert not _volumes_for(project)


def test_mirror_full_lifecycle_cleans_up():
    """``mirror`` removes both its containers and its temp-dir copy on exit."""
    project = _unique("dokker-mirror")
    copied = os.path.join(os.getcwd(), ".dokker", project)
    try:
        with mirror(MIRROR_SRC, project_name=project) as deployment:
            deployment.up()  # mirror's default "testing" policy downs + removes the copy
            assert os.path.isdir(copied), "mirror should copy the source into .dokker/<project>"

        assert not os.path.isdir(copied), "the temp-dir copy must be removed on exit"
        assert not _containers_for(project), "no containers should survive teardown"
    finally:
        # Defensive: if an assertion failed mid-block, don't leave a copy behind.
        if os.path.isdir(copied):
            import shutil

            shutil.rmtree(copied, ignore_errors=True)
