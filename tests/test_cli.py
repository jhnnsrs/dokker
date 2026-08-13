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


def test_docker_cmd_includes_project_name():
    # An explicit project name must be emitted as ``--project-name`` so that
    # up/down/ps/logs all target the same, isolated Compose project. The CLI
    # flag wins over any ``name:`` declared inside the compose file.
    cli = CLI(compose_files=[COMPOSE_FILE], compose_project_name="my-proj")
    cmd = cli.docker_cmd
    assert "--project-name" in cmd
    assert cmd[cmd.index("--project-name") + 1] == "my-proj"


def test_docker_cmd_omits_project_name_when_unset():
    # Default behavior is preserved: no name => no flag, Compose derives it.
    cli = CLI(compose_files=[COMPOSE_FILE])
    assert "--project-name" not in cli.docker_cmd


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


def test_docker_cmd_is_stable_across_repeated_access():
    """Building the command must not mutate the CLI.

    ``docker_cmd`` used to bind to the ``client_call`` field and then ``+=``
    into it, so every access appended another full flag set -- permanently, to
    the model. A single lifecycle reads this once per pull/up/inspect/logs/down,
    so argv grew on every command.
    """
    cli = CLI(compose_files=[COMPOSE_FILE], compose_project_name="my-proj")

    first = cli.docker_cmd
    second = cli.docker_cmd
    third = cli.docker_cmd

    assert first == second == third
    assert cli.client_call == ["docker", "compose"]
    assert first.count("--file") == 1


def test_docker_cmd_emits_profiles_env_file_and_project_directory():
    """These fields existed but were never emitted, so they silently did nothing."""
    cli = CLI(
        compose_files=[COMPOSE_FILE],
        compose_profiles=["debug", "extras"],
        compose_env_file=COMPOSE_FILE,  # any existing file will do
        compose_project_directory="tests/configs",
        compose_compatibility=True,
    )
    cmd = cli.docker_cmd

    assert cmd.count("--profile") == 2
    assert "debug" in cmd and "extras" in cmd
    assert "--env-file" in cmd
    assert "--project-directory" in cmd and "tests/configs" in cmd
    assert "--compatibility" in cmd


def test_env_file_is_not_passed_unless_asked_for():
    """The old default of ``.env`` made compose fail on projects without one."""
    cli = CLI(compose_files=[COMPOSE_FILE])
    assert "--env-file" not in cli.docker_cmd


def _tokens_after(cmd, flag):
    return cmd[cmd.index(flag) + 1]


async def _argv_of(agen):
    """Capture the argv a CLI method builds, without running docker."""
    captured = {}

    async def fake_astream(self, full_cmd):
        captured["argv"] = full_cmd
        return
        yield  # pragma: no cover -- makes this an async generator

    from dokker.cli import CLI as _CLI

    original = _CLI._astream
    _CLI._astream = fake_astream
    try:
        async for _ in agen():
            pass
    finally:
        _CLI._astream = original
    return captured["argv"]


async def test_value_flags_are_separate_argv_tokens():
    """Flags and their values must be distinct argv entries.

    These were built as single strings like ``f"--timeout {t}"``, which only
    worked because the runner joined argv into a shell string. Executing argv
    directly, a combined token reaches docker as one unknown flag.
    """
    cli = CLI(compose_files=[COMPOSE_FILE])

    argv = await _argv_of(lambda: cli.astream_down(timeout=7, remove_images="all"))
    assert _tokens_after(argv, "--timeout") == "7"
    assert _tokens_after(argv, "--rmi") == "all"

    argv = await _argv_of(lambda: cli.astream_stop(timeout=3))
    assert _tokens_after(argv, "--timeout") == "3"

    argv = await _argv_of(lambda: cli.astream_up(scales={"worker": 3}, pull="always", no_attach_services=["db"], wait=True, wait_timeout=30))
    assert _tokens_after(argv, "--scale") == "worker=3"
    assert _tokens_after(argv, "--pull") == "always"
    assert _tokens_after(argv, "--no-attach") == "db"
    assert _tokens_after(argv, "--wait-timeout") == "30"


async def test_up_rejects_wait_timeout_without_wait():
    cli = CLI(compose_files=[COMPOSE_FILE])
    with pytest.raises(ValueError):
        async for _ in cli.astream_up(wait_timeout=5):
            pass


async def test_run_and_exec_split_string_commands_into_argv():
    """A string command is tokenized, keeping a quoted ``sh -c`` script intact."""
    cli = CLI(compose_files=[COMPOSE_FILE])

    argv = await _argv_of(lambda: cli.astream_run(service="web", command="sh -c 'echo boom >&2; exit 7'"))
    assert argv[-3:] == ["sh", "-c", "echo boom >&2; exit 7"]
    assert "--no-TTY" in argv and "--quiet-pull" in argv

    argv = await _argv_of(lambda: cli.astream_exec(service="web", command="redis-cli ping"))
    assert argv[-3:] == ["web", "redis-cli", "ping"]


async def test_exec_passes_env_and_workdir():
    cli = CLI(compose_files=[COMPOSE_FILE])
    argv = await _argv_of(lambda: cli.astream_exec(service="web", command=["ls"], env={"A": "1"}, workdir="/srv", user="root"))
    assert _tokens_after(argv, "--env") == "A=1"
    assert _tokens_after(argv, "--workdir") == "/srv"
    assert _tokens_after(argv, "--user") == "root"
