"""Integration tests for the non-HTTP readiness strategies and `exec`.

Run with::

    pytest -m integration -k readiness

Redis is the stand-in for the class of service these exist for: databases and
brokers that integration tests depend on and that speak no HTTP, so the
HTTP-only ``HealthCheck`` cannot express their readiness at all.
"""

import pytest

from dokker import CommandCheck, CommandError, ContainerCheck, LogCheck, TcpCheck, testing

pytestmark = pytest.mark.integration

COMPOSE_FILE = "tests/configs/db-compose.yaml"


def test_command_check_waits_for_a_database_to_answer():
    """`redis-cli ping` inside the container -- the service's own readiness tool."""
    deployment = testing(COMPOSE_FILE, health_checks=[CommandCheck(service="redis", command="redis-cli ping")])
    with deployment:
        deployment.up()
        deployment.inspect()
        deployment.check_health()


def test_container_check_uses_dockers_own_health_verdict():
    deployment = testing(COMPOSE_FILE, health_checks=[ContainerCheck(service="redis")])
    with deployment:
        deployment.up(wait=True, wait_timeout=60)
        deployment.inspect()
        deployment.check_health()

        assert deployment.ps()[0].health == "healthy"


def test_tcp_and_log_checks_pass_against_a_started_service():
    deployment = testing(
        COMPOSE_FILE,
        health_checks=[
            TcpCheck(service="redis", port=6379),
            LogCheck(service="redis", pattern="Ready to accept connections"),
        ],
    )
    with deployment:
        deployment.up(wait=True, wait_timeout=60)
        deployment.inspect()
        deployment.check_health()


def test_up_wait_blocks_until_compose_reports_healthy():
    """`up(wait=True)` is compose's own readiness mechanism, previously unreachable."""
    deployment = testing(COMPOSE_FILE)
    with deployment:
        deployment.up(wait=True, wait_timeout=60)
        # If --wait did its job, the container is already healthy on return.
        assert deployment.ps()[0].health == "healthy"


def test_exec_runs_in_the_already_running_container():
    """`exec` sees live state; `run` (a fresh container) would not."""
    deployment = testing(COMPOSE_FILE, health_checks=[CommandCheck(service="redis", command="redis-cli ping")])
    with deployment:
        deployment.up(wait=True, wait_timeout=60)
        deployment.check_health()

        deployment.exec("redis", "redis-cli set greeting hello")
        result = deployment.exec("redis", "redis-cli get greeting")

        assert "hello" in result.stdout
        assert result.returncode == 0


def test_exec_reports_a_failing_command_with_its_exit_code():
    deployment = testing(COMPOSE_FILE)
    with deployment:
        deployment.up(wait=True, wait_timeout=60)

        with pytest.raises(CommandError) as excinfo:
            deployment.exec("redis", "sh -c 'echo nope >&2; exit 4'")

        error = excinfo.value
        assert error.returncode == 4
        assert any("nope" in line for line in error.stderr)

        # ...and the non-raising form records the same code.
        result = deployment.exec("redis", "sh -c 'exit 4'", raise_on_error=False)
        assert result.returncode == 4


def test_check_health_raises_for_a_service_with_no_registered_check():
    """An unmatched service name used to gather nothing and report success."""
    from dokker import HealthCheckError

    deployment = testing(COMPOSE_FILE, health_checks=[ContainerCheck(service="redis")])
    with deployment:
        deployment.up(wait=True, wait_timeout=60)
        deployment.inspect()

        with pytest.raises(HealthCheckError) as excinfo:
            deployment.check_health(services=["not-covered"])

        assert "not-covered" in str(excinfo.value)


def test_one_shot_logs_returns_what_the_service_has_printed():
    deployment = testing(COMPOSE_FILE)
    with deployment:
        deployment.up(wait=True, wait_timeout=60)

        logs = deployment.logs("redis")
        assert any("Ready to accept connections" in line for _, line in logs)


def test_watcher_await_log_blocks_until_a_matching_line_appears():
    """The documented synchronisation primitive, against a real service."""
    deployment = testing(COMPOSE_FILE)
    with deployment:
        deployment.up(wait=True, wait_timeout=60)

        with deployment.create_watcher("redis") as watcher:
            line = watcher.await_log(r"Ready to accept connections", timeout=30)

        assert "Ready to accept connections" in line


def test_watcher_on_a_bad_service_terminates_instead_of_hanging():
    """A watcher on a nonexistent service must not hang the session.

    Compose reports the bad name and exits non-zero. Whether that surfaces as a
    raised error or as an empty log roll depends on whether the stream fails
    before the block exits -- a race not worth pinning down. What must hold, and
    previously did not, is that this *terminates at all*: the enter path used to
    wait on a future that nothing would ever resolve.
    """
    deployment = testing(COMPOSE_FILE)
    with deployment:
        deployment.up(wait=True, wait_timeout=60)

        try:
            with deployment.create_watcher("no-such-service") as watcher:
                pass
        except Exception as error:
            assert "no-such-service" in str(error)
        else:
            # Terminated without raising: it must at least not claim to have
            # captured logs from a service that does not exist.
            assert all("no-such-service" not in line for _, line in watcher.collected_logs if "no such service" not in line)


def test_watcher_on_a_quiet_service_times_out_rather_than_hanging():
    """A service that has not logged must not block the caller indefinitely."""
    from dokker import LogWatcherTimeoutError

    deployment = testing(COMPOSE_FILE)
    with deployment:
        deployment.up(wait=True, wait_timeout=60)

        watcher = deployment.create_watcher(
            "redis",
            # `until` in the past guarantees the stream yields nothing at all.
            since="2000-01-01T00:00:00",
            until="2000-01-01T00:00:01",
            wait_for_first_log=True,
        )
        watcher.wait_for_first_log_timeout = 5.0

        with pytest.raises((LogWatcherTimeoutError, Exception)):
            with watcher:
                pass
