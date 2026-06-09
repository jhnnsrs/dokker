"""Unit tests for the ``CLI`` command builder.

These cover the construction of docker-compose argument lists and the
up-front validation that gives early, clear feedback (missing compose files,
contradictory flags) before any container is ever started.
"""

import pytest

from dokker.cli import CLI

COMPOSE_FILE = "tests/configs/basic-compose.yaml"


def test_docker_cmd_includes_compose_file():
    cli = CLI(compose_files=[COMPOSE_FILE])
    cmd = cli.docker_cmd
    assert cmd[:2] == ["docker", "compose"]
    assert "--file" in cmd
    assert COMPOSE_FILE in cmd


def test_docker_cmd_includes_optional_flags():
    cli = CLI(compose_files=[COMPOSE_FILE], host="tcp://localhost:2375", debug=True, log_level="DEBUG")
    cmd = cli.docker_cmd
    assert "--host" in cmd and "tcp://localhost:2375" in cmd
    assert "--debug" in cmd
    assert "--log-level" in cmd and "DEBUG" in cmd


def test_missing_compose_file_raises_with_path():
    with pytest.raises(ValueError) as excinfo:
        CLI(compose_files=["nope/does-not-exist.yaml"])
    # The message must name the offending file, not the whole list.
    assert "nope/does-not-exist.yaml" in str(excinfo.value)


async def test_up_rejects_quiet_with_stream_logs():
    cli = CLI(compose_files=[COMPOSE_FILE])
    with pytest.raises(ValueError):
        async for _ in cli.astream_up(quiet=True, stream_logs=True):
            pass


async def test_run_rejects_empty_command():
    cli = CLI(compose_files=[COMPOSE_FILE])
    with pytest.raises(ValueError):
        async for _ in cli.astream_run(service="web", command=[]):
            pass
