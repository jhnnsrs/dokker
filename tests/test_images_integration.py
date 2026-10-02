"""Docker-backed tests for what happens to the images a testing stack builds.

A ``testing()`` stack has a random project name, and compose names what it
builds after the project. Nothing will ask for that tag again, so teardown
takes it along -- and only it: pulled images and the build cache stay.

Run with::

    pytest -m integration -k images
"""

import subprocess
import sys
import uuid

import pytest

from dokker import reap_orphan_images, reap_stale
from dokker import testing as make_testing

pytestmark = pytest.mark.integration

COMPOSE = "tests/configs/build-compose.yaml"

STRAND_SCRIPT = """
import os
from dokker import testing
d = testing({compose!r}, project_name={project!r}, reap_stale=False)
d.__enter__()
d.up()
os._exit(137)
"""


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _docker(*args: str) -> list[str]:
    out = subprocess.run(["docker", *args], capture_output=True, text=True, check=False).stdout
    return [line for line in out.splitlines() if line.strip()]


def _images_for(project: str) -> list[str]:
    return _docker("image", "ls", "--filter", f"reference={project}-*", "--format", "{{.Repository}}")


def _cleanup(project: str) -> None:
    subprocess.run(["docker", "compose", "-p", project, "down", "--volumes", "--remove-orphans"], capture_output=True, check=False)
    for image in _images_for(project):
        subprocess.run(["docker", "image", "rm", "--force", image], capture_output=True, check=False)


def test_down_removes_the_image_built_for_the_project_and_keeps_the_pulled_one():
    project = _unique("dokker-img")
    try:
        with make_testing(COMPOSE, project_name=project, shutdown_timeout=1) as d:
            d.up()
            assert _images_for(project) == [f"{project}-built"]
        assert _images_for(project) == []
        assert _docker("image", "ls", "--quiet", "alpine:3.20"), "a pulled image is not the project's to remove"
    finally:
        _cleanup(project)


def test_images_are_kept_when_asked():
    project = _unique("dokker-img")
    try:
        with make_testing(COMPOSE, project_name=project, shutdown_timeout=1, remove_images=None) as d:
            d.up()
        assert _images_for(project) == [f"{project}-built"]
    finally:
        _cleanup(project)


def test_a_stranded_stacks_image_is_reaped_with_it():
    project = _unique("dokker-img-stray")
    try:
        code = STRAND_SCRIPT.format(compose=COMPOSE, project=project)
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert proc.returncode == 137, proc.stderr
        assert _images_for(project) == [f"{project}-built"]

        assert project in reap_stale()
        assert _images_for(project) == []
    finally:
        _cleanup(project)


def test_images_earlier_testing_stacks_left_behind_are_swept():
    """What a run from before `down` removed images left: a tag with no stack behind it."""
    project = f"dokker-test-{uuid.uuid4().hex[:8]}"
    kept = _unique("dokker-img-other")
    try:
        with make_testing(COMPOSE, project_name=project, shutdown_timeout=1, remove_images=None) as d:
            d.up()
            # While the stack exists its image is in use, however old the tag.
            assert reap_orphan_images(grace=0, projects=[project]) == []
        with make_testing(COMPOSE, project_name=kept, shutdown_timeout=1, remove_images=None) as d:
            d.up()

        # Freshly tagged: it could be a run that is still building.
        assert reap_orphan_images(projects=[project]) == []
        assert _images_for(project) == [f"{project}-built"]

        assert reap_orphan_images(grace=0, projects=[project]) == [f"{project}-built:latest"]
        assert _images_for(project) == []
        # Only `testing()`'s own random names are swept: a project somebody named is theirs.
        assert reap_orphan_images(grace=0, projects=[kept]) == []
        assert _images_for(kept) == [f"{kept}-built"]
    finally:
        _cleanup(project)
        _cleanup(kept)
