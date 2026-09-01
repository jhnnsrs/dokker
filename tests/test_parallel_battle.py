"""Adversarial tests for running competing deployments at the same time.

``test_parallel_integration`` proves the happy path: two ``testing()``
deployments of one ephemeral-port compose file get different host ports. This
module attacks the same promise from the angles that file does not cover --
builders that do *not* mint a project name, compose files that pin a host port,
genuinely concurrent ``up``, interleaved teardown, and the ``.dokker`` scratch
directory that ``mirror()`` writes to.

Run with::

    pytest -m integration -k battle

Ordering matters here: the fixed-port test runs last, because a stack it
stranded on that port would make every earlier test fail for the wrong reason.
"""

import asyncio
import os
import shutil
import urllib.error
import urllib.request
import uuid

import pytest

from dokker import DokkerError, ProjectError, TcpCheck, local, mirror, testing

pytestmark = pytest.mark.integration

BATTLE_DIR = "tests/configs/battle"
A_COMPOSE = f"{BATTLE_DIR}/a-compose.yaml"
B_COMPOSE = f"{BATTLE_DIR}/b-compose.yaml"
FIXED_PORT_COMPOSE = f"{BATTLE_DIR}/fixed-port-compose.yaml"
PARALLEL_COMPOSE = "tests/configs/parallel-compose.yaml"
MIRROR_SRC = "tests/configs/mirror-src"


def _get(url: str, timeout: float = 10) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode()


def _echo_check() -> TcpCheck:
    return TcpCheck(service="echo", port=5678)


def _force_down(deployment) -> None:
    """Tear a deployment all the way down, ignoring anything that goes wrong.

    Used in ``finally`` blocks. ``local()``'s policy only *stops* containers on
    exit and keeps volumes, so its containers would otherwise survive the test
    still holding the project name -- and poison the next run.
    """
    try:
        deployment.down(volumes=True, remove_orphans=True)
    except Exception:  # noqa: BLE001 - best effort cleanup, never mask the real failure
        pass


def test_two_local_deployments_in_one_directory_do_not_merge():
    """``local()`` deployments of sibling compose files must stay separate.

    ``local()`` leaves ``project_name`` unset, so dokker emits no
    ``--project-name`` and compose falls back to the compose file's *parent
    directory* -- identical for both files here. If that is all the isolation
    there is, the two deployments are one compose project: the second ``up()``
    recreates the shared ``echo`` service rather than adding its own, and both
    deployments end up pointing at a single container.

    The shared service name is what makes that observable. Sibling files with
    *different* service names would co-exist inside one project quite happily
    and this test would pass while the merge went unnoticed.
    """
    first = local(A_COMPOSE, health_checks=[_echo_check()])
    second = local(B_COMPOSE, health_checks=[_echo_check()])

    try:
        with first, second:
            first.up()
            second.up()

            first_port = first.get_port("echo", 5678)
            second_port = second.get_port("echo", 5678)

            assert first_port != second_port, "both deployments resolved to the same container -- the compose projects merged"

            assert "hello from stack A" in _get(f"http://localhost:{first_port}")
            assert "hello from stack B" in _get(f"http://localhost:{second_port}")
    finally:
        _force_down(first)
        _force_down(second)


async def test_five_stacks_come_up_concurrently_on_distinct_ports():
    """Five identical stacks brought up in one ``gather`` must not overlap.

    The sequential case is already covered; this is the one where a port
    allocator racing with itself would show up. Dokker has no allocator -- it
    asks docker after the fact -- so the expectation is that all five land on
    different ports.
    """
    deployments = [testing(PARALLEL_COMPOSE, health_checks=[_echo_check()]) for _ in range(5)]

    async with deployments[0], deployments[1], deployments[2], deployments[3], deployments[4]:
        await asyncio.gather(*(d.aup() for d in deployments))
        await asyncio.gather(*(d.acheck_health() for d in deployments))

        ports = await asyncio.gather(*(d.aget_port("echo", 5678) for d in deployments))

        assert len(set(ports)) == len(ports), f"concurrent stacks shared a host port: {ports}"

        bodies = await asyncio.gather(*(asyncio.to_thread(_get, await d.aget_url("echo", 5678)) for d in deployments))
        assert all("hello from dokker" in body for body in bodies)


def test_downing_one_stack_leaves_its_neighbour_serving():
    """Tearing down one deployment must not disturb a sibling.

    Shared networks and the log watcher are both process-wide enough to get
    this wrong: a ``down`` that removes a network the neighbour is attached to,
    or that reaps a container it does not own, shows up here and nowhere else.
    """
    first = testing(PARALLEL_COMPOSE, health_checks=[_echo_check()])
    second = testing(PARALLEL_COMPOSE, health_checks=[_echo_check()])

    with first, second:
        first.up()
        second.up()

        second_port = second.get_port("echo", 5678)
        assert "hello from dokker" in _get(f"http://localhost:{second_port}")

        first.down()

        # The survivor keeps both its port and its ability to answer on it.
        assert second.get_port("echo", 5678) == second_port
        second.check_health()
        assert "hello from dokker" in _get(f"http://localhost:{second_port}")


async def test_two_mirrors_of_one_source_refuse_to_share_a_project_dir():
    """``mirror()`` must not let a second deployment adopt the first's copy.

    ``CopyPathProject`` copies the source into ``.dokker/<project_name>``, and
    ``project_name`` defaults to the source's basename -- so two mirrors of one
    source target the same directory. The second must refuse, with a message
    that names the project and the way out, rather than silently sharing (or
    overwriting) a directory the first deployment is live on.
    """
    project_name = f"battle-mirror-{uuid.uuid4().hex[:8]}"
    project_dir = os.path.join(os.getcwd(), ".dokker", project_name)

    first = mirror(MIRROR_SRC, project_name=project_name)
    second = mirror(MIRROR_SRC, project_name=project_name)

    try:
        async with first:
            await first.ainitialize()
            assert os.path.isdir(project_dir)

            async with second:
                with pytest.raises(ProjectError) as excinfo:
                    await second.ainitialize()

            message = str(excinfo.value)
            assert project_name in message
            assert "overwrite" in message or "project_name" in message

            # The refusal must leave the first deployment's copy intact.
            assert os.path.isdir(project_dir)
    finally:
        # Only ever remove the uniquely-named directory this test created --
        # `.dokker/echo` and `.dokker/paper` are tracked in git.
        shutil.rmtree(project_dir, ignore_errors=True)


def test_fixed_host_port_collision_reports_a_legible_error():
    """A pinned host port must fail loudly, naming the port that is taken.

    This is the one case dokker genuinely cannot isolate: if the compose file
    says ``54321:5678``, two copies cannot both bind it. That is fine -- what
    matters is that the second ``up()`` raises a ``DokkerError`` mentioning the
    port, instead of hanging, exiting zero, or surfacing an unlabelled blob.

    Runs last on purpose: a stack stranded on the pinned port would make the
    rest of this module fail for reasons that have nothing to do with it.
    """
    first = testing(FIXED_PORT_COMPOSE, health_checks=[_echo_check()])
    second = testing(FIXED_PORT_COMPOSE, health_checks=[_echo_check()])

    try:
        with first:
            first.up()
            assert "hello from the fixed-port stack" in _get("http://localhost:54321")

            with second:
                with pytest.raises(DokkerError) as excinfo:
                    second.up()

            message = str(excinfo.value)
            assert "54321" in message, f"the error never names the port that is taken:\n{message}"

            # The stack that got there first is untouched by the loser's failure.
            assert "hello from the fixed-port stack" in _get("http://localhost:54321")
    finally:
        _force_down(second)
        _force_down(first)
