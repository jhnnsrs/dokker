"""Docker-backed tests for owner labels and stale-stack reaping.

The scenario these protect against is real: a ``testing()`` run in one
terminal is SIGKILLed and leaves its ``dokker-test-*`` stack behind; somebody
cleans the strays with a name-pattern sweep and, with it, kills the stack a
*live* run in another terminal is using. The fix is that dokker removes its
own strays -- and only those -- before the next ``up``.

Run with::

    pytest -m integration -k ownership
"""

import os
import subprocess
import sys
import uuid

import pytest

from dokker import reap_stale
from dokker import testing as make_testing
from dokker.ownership import OWNER_PID_LABEL

pytestmark = pytest.mark.integration

# A stack with no published ports, so several copies can run side by side.
COMPOSE = "tests/configs/volume-compose.yaml"

# Runs `up()` under the testing policy and dies without ever reaching the
# teardown -- exactly what a SIGKILLed or interrupted test run does.
STRAND_SCRIPT = """
import os, sys
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


def _containers_for(project: str) -> list[str]:
    return _docker("ps", "-a", "--filter", f"label=com.docker.compose.project={project}", "--format", "{{.Names}}")


def _volumes_for(project: str) -> list[str]:
    return _docker("volume", "ls", "--filter", f"label=com.docker.compose.project={project}", "--format", "{{.Name}}")


def _owner_pid(container: str) -> str:
    lines = _docker("inspect", "--format", f'{{{{index .Config.Labels "{OWNER_PID_LABEL}"}}}}', container)
    return lines[0] if lines else ""


def _force_down(project: str) -> None:
    subprocess.run(["docker", "compose", "-p", project, "down", "--volumes", "--remove-orphans"], capture_output=True, check=False)


def _strand(project: str) -> int:
    """Start ``project`` from a child process that dies without teardown; return its PID."""
    code = STRAND_SCRIPT.format(compose=COMPOSE, project=project)
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _, stderr = proc.communicate()
    assert proc.returncode == 137, stderr
    assert _containers_for(project), "the stranded stack should still be up"
    return proc.pid


def test_a_testing_stack_carries_its_owners_pid():
    project = _unique("dokker-own")
    try:
        with make_testing(COMPOSE, project_name=project, shutdown_timeout=1) as d:
            d.up()
            names = _containers_for(project)
            assert names
            assert all(_owner_pid(n) == str(os.getpid()) for n in names)
        assert _containers_for(project) == []
    finally:
        _force_down(project)


def test_a_kept_stack_carries_no_owner_label():
    """``down_on_exit=False`` (what ``--dokker-keep`` passes) opts out of reaping entirely."""
    project = _unique("dokker-keep")
    try:
        with make_testing(COMPOSE, project_name=project, shutdown_timeout=1) as d:
            d.up(down_on_exit=False)
            names = _containers_for(project)
            assert names
            assert all(_owner_pid(n) == "" for n in names)
        # Still up after exit, and a reap does not touch it.
        assert _containers_for(project)
        assert project not in reap_stale()
        assert _containers_for(project)
    finally:
        _force_down(project)


def test_stranded_stack_is_reaped_by_the_next_up():
    stranded = _unique("dokker-stray")
    live = _unique("dokker-live")
    try:
        dead_pid = _strand(stranded)
        assert all(_owner_pid(n) == str(dead_pid) for n in _containers_for(stranded))

        with make_testing(COMPOSE, project_name=live, shutdown_timeout=1) as d:
            d.up()
            # The stray -- containers *and* its named volume -- is gone, the new stack is up.
            assert _containers_for(stranded) == []
            assert _volumes_for(stranded) == []
            assert _containers_for(live)
    finally:
        _force_down(stranded)
        _force_down(live)


def test_a_live_owners_stack_survives_another_up_and_an_explicit_reap():
    first = _unique("dokker-first")
    second = _unique("dokker-second")
    try:
        with make_testing(COMPOSE, project_name=first, shutdown_timeout=1) as a:
            a.up()
            with make_testing(COMPOSE, project_name=second, shutdown_timeout=1) as b:
                b.up()
                assert _containers_for(first), "a live stack must never be reaped by a sibling's up()"
                assert first not in reap_stale()
                assert _containers_for(first)
    finally:
        _force_down(first)
        _force_down(second)


def test_reap_stale_returns_the_projects_it_removed():
    stranded = _unique("dokker-stray")
    try:
        _strand(stranded)
        assert stranded in reap_stale()
        assert _containers_for(stranded) == []
        assert reap_stale() == [] or stranded not in reap_stale()
    finally:
        _force_down(stranded)


def test_reap_stale_false_leaves_strays_alone():
    stranded = _unique("dokker-stray")
    live = _unique("dokker-live")
    try:
        _strand(stranded)
        with make_testing(COMPOSE, project_name=live, shutdown_timeout=1, reap_stale=False) as d:
            d.up()
            assert _containers_for(stranded)
    finally:
        _force_down(stranded)
        _force_down(live)
