"""Unit tests for the readiness checks in ``dokker.checks``.

These use a fake CLI rather than docker, so they run anywhere. They cover the
non-HTTP readiness strategies -- the ones that let a deployment wait for a
database, which the HTTP-only ``HealthCheck`` cannot express.
"""

import pytest

from dokker.checks import Check, CheckContext, CommandCheck, ContainerCheck, LogCheck, TcpCheck
from dokker.cli import CLI
from dokker.command import CommandError
from dokker.compose_spec import ComposeSpec, ContainerStatus
from dokker.deployment import HealthCheck
from dokker.errors import HealthCheckError, PortNotFoundError

COMPOSE_FILE = "tests/configs/basic-compose.yaml"


class FakeCLI(CLI):
    """A CLI whose docker interactions are scripted."""

    model_config = {"extra": "allow"}

    async def aport(self, service, private_port, protocol="tcp", index=None):
        if getattr(self, "port_error", None):
            raise self.port_error
        return getattr(self, "port_result", ("0.0.0.0", 5555))

    async def aps(self, services=None, all=False):
        return getattr(self, "ps_result", [])

    async def astream_exec(self, service, command, **kwargs):
        if getattr(self, "exec_error", None):
            raise self.exec_error
        for line in getattr(self, "exec_lines", []):
            yield ("STDOUT", line)

    async def astream_docker_logs(self, **kwargs):
        for line in getattr(self, "log_lines", []):
            yield ("STDOUT", line)


def _ctx(**attrs):
    cli = FakeCLI(compose_files=[COMPOSE_FILE])
    for key, value in attrs.items():
        setattr(cli, key, value)
    return CheckContext(spec=ComposeSpec(), cli=cli)


def test_builtin_checks_satisfy_the_check_protocol():
    """Including the original HTTP check, which must keep working unchanged."""
    for check in (
        HealthCheck(url="http://x", service="web"),
        TcpCheck(service="db", port=5432),
        CommandCheck(service="db", command="pg_isready"),
        ContainerCheck(service="db"),
        LogCheck(service="db", pattern="ready"),
    ):
        assert isinstance(check, Check)


async def test_tcp_check_reports_the_resolved_host_port_on_failure():
    ctx = _ctx(port_error=PortNotFoundError("not published"))
    with pytest.raises(PortNotFoundError):
        await TcpCheck(service="db", port=5432).aperform(ctx)


async def test_tcp_check_fails_cleanly_when_nothing_is_listening():
    # Port 1 on loopback is not listening in any sane environment.
    ctx = _ctx(port_result=("0.0.0.0", 1))
    with pytest.raises(HealthCheckError) as excinfo:
        await TcpCheck(service="db", port=5432, connect_timeout=1.0).aperform(ctx)

    message = str(excinfo.value)
    assert "db" in message
    # 0.0.0.0 is not dialable everywhere, so the check must connect over loopback.
    assert "127.0.0.1" in message


async def test_command_check_passes_when_the_command_exits_zero():
    await CommandCheck(service="db", command="pg_isready").aperform(_ctx(exec_lines=["accepting connections"]))


async def test_command_check_surfaces_stderr_of_a_failing_command():
    error = CommandError("failed", command="pg_isready", returncode=1, stderr=["no response"])
    with pytest.raises(HealthCheckError) as excinfo:
        await CommandCheck(service="db", command="pg_isready").aperform(_ctx(exec_error=error))

    assert "no response" in str(excinfo.value)


async def test_container_check_passes_for_a_healthy_container():
    status = ContainerStatus(Name="p-db-1", Service="db", State="running", Health="healthy")
    await ContainerCheck(service="db").aperform(_ctx(ps_result=[status]))


async def test_container_check_accepts_a_running_container_without_a_healthcheck():
    status = ContainerStatus(Name="p-db-1", Service="db", State="running", Health="")
    await ContainerCheck(service="db").aperform(_ctx(ps_result=[status]))


async def test_container_check_rejects_an_unhealthy_container():
    status = ContainerStatus(Name="p-db-1", Service="db", State="running", Health="unhealthy")
    with pytest.raises(HealthCheckError) as excinfo:
        await ContainerCheck(service="db").aperform(_ctx(ps_result=[status]))
    assert "unhealthy" in str(excinfo.value)


async def test_container_check_reports_the_exit_code_of_a_crashed_container():
    status = ContainerStatus(Name="p-db-1", Service="db", State="exited", ExitCode=1)
    with pytest.raises(HealthCheckError) as excinfo:
        await ContainerCheck(service="db").aperform(_ctx(ps_result=[status]))

    message = str(excinfo.value)
    assert "exited" in message and "exit code 1" in message


async def test_container_check_explains_when_no_container_exists():
    with pytest.raises(HealthCheckError) as excinfo:
        await ContainerCheck(service="db").aperform(_ctx(ps_result=[]))
    assert "found no container" in str(excinfo.value)


async def test_log_check_matches_a_pattern():
    ctx = _ctx(log_lines=["starting", "database system is ready to accept connections"])
    await LogCheck(service="db", pattern="ready to accept connections").aperform(ctx)


async def test_log_check_shows_recent_lines_when_the_pattern_is_absent():
    ctx = _ctx(log_lines=["starting", "still starting"])
    with pytest.raises(HealthCheckError) as excinfo:
        await LogCheck(service="db", pattern="ready").aperform(ctx)

    message = str(excinfo.value)
    assert "still starting" in message
    assert "2 log line(s)" in message


def test_container_status_parses_compose_capitalised_keys():
    status = ContainerStatus(**{"Name": "p-web-1", "Service": "web", "State": "running", "Health": "healthy", "Unknown": "ignored"})
    assert status.service == "web"
    assert status.is_running and status.is_healthy
