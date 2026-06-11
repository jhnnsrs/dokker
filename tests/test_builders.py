"""Unit tests for the builder functions' project-name threading.

These assert that a ``project_name`` set on a builder reaches the docker-compose
command as ``--project-name`` (the ``-p`` flag), which isolates a deployment from
sibling stacks that would otherwise share Compose's default (directory-basename)
project name. No containers are started: ``LocalProject.ainititialize`` only
constructs a ``CLI``.
"""

# ``testing`` is imported under an alias so pytest does not collect the builder
# itself as a test (its name matches the default ``test*`` collection pattern).
from dokker import local, monitoring
from dokker import testing as make_testing

COMPOSE_FILE = "tests/configs/basic-compose.yaml"


async def test_local_threads_project_name():
    deployment = local(COMPOSE_FILE, project_name="explicit-name")
    cli = await deployment.project.ainititialize()
    assert "--project-name" in cli.docker_cmd
    assert cli.docker_cmd[cli.docker_cmd.index("--project-name") + 1] == "explicit-name"


async def test_local_without_project_name_omits_flag():
    deployment = local(COMPOSE_FILE)
    cli = await deployment.project.ainititialize()
    assert "--project-name" not in cli.docker_cmd


async def test_monitoring_threads_project_name():
    deployment = monitoring(COMPOSE_FILE, project_name="mon-name")
    cli = await deployment.project.ainititialize()
    assert cli.docker_cmd[cli.docker_cmd.index("--project-name") + 1] == "mon-name"


async def test_testing_defaults_to_unique_random_project_name():
    # Each ``testing`` deployment gets its own random name so identical compose
    # copies in sibling dirs never tear down each other's containers.
    a = make_testing(COMPOSE_FILE)
    b = make_testing(COMPOSE_FILE)
    cli_a = await a.project.ainititialize()
    cli_b = await b.project.ainititialize()
    name_a = cli_a.docker_cmd[cli_a.docker_cmd.index("--project-name") + 1]
    name_b = cli_b.docker_cmd[cli_b.docker_cmd.index("--project-name") + 1]
    assert name_a.startswith("dokker-test-")
    assert name_a != name_b


async def test_testing_respects_explicit_project_name():
    deployment = make_testing(COMPOSE_FILE, project_name="pinned")
    cli = await deployment.project.ainititialize()
    assert cli.docker_cmd[cli.docker_cmd.index("--project-name") + 1] == "pinned"


def test_testing_orphan_and_volume_removal_configurable():
    default = make_testing(COMPOSE_FILE)
    assert default.remove_orphans_on_down is True
    assert default.remove_volumes_on_down is True

    off = make_testing(COMPOSE_FILE, remove_orphans=False, remove_volumes=False)
    assert off.remove_orphans_on_down is False
    assert off.remove_volumes_on_down is False
