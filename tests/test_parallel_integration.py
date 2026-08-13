"""Integration tests for runtime port resolution and parallel isolation.

Run with::

    pytest -m integration -k parallel

The promise under test: two deployments of the *same* compose file can run at
the same time. A unique project name alone does not achieve that -- it isolates
containers and networks, but both stacks still bind the same host port. Only
ephemeral ports plus runtime resolution make it true.
"""

import urllib.request

import pytest

from dokker import PortNotFoundError, TcpCheck, testing

pytestmark = pytest.mark.integration

COMPOSE_FILE = "tests/configs/parallel-compose.yaml"


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.read().decode()


def test_two_identical_stacks_run_side_by_side_on_different_ports():
    """The core parallel-isolation promise, end to end."""
    first = testing(COMPOSE_FILE, health_checks=[TcpCheck(service="echo", port=5678)])
    second = testing(COMPOSE_FILE, health_checks=[TcpCheck(service="echo", port=5678)])

    with first, second:
        first.up()
        second.up()
        first.inspect()
        second.inspect()

        first_port = first.get_port("echo", 5678)
        second_port = second.get_port("echo", 5678)

        assert first_port != second_port, "both stacks were assigned the same host port"

        first.check_health()
        second.check_health()

        assert "hello from dokker" in _get(first.get_url("echo", 5678))
        assert "hello from dokker" in _get(second.get_url("echo", 5678))


def test_get_url_builds_a_working_url_with_a_path():
    deployment = testing(COMPOSE_FILE)
    with deployment:
        deployment.up()
        deployment.inspect()

        url = deployment.get_url("echo", 5678, path="anything")
        assert url.startswith("http://localhost:")
        assert url.endswith("/anything")
        assert "hello from dokker" in _get(url)


def test_static_spec_refuses_to_hand_back_an_unresolved_port():
    """An ephemeral port is absent from `compose config`, and must say so.

    Returning the mapping regardless yielded ``published=None``, which formats
    straight into a URL as ``http://localhost:None`` -- a failure that only
    shows up as a confusing connection error much later.
    """
    deployment = testing(COMPOSE_FILE)
    with deployment:
        deployment.up()
        spec = deployment.inspect()

        service = spec.find_service("echo")
        with pytest.raises(PortNotFoundError) as excinfo:
            service.get_port_for_internal(5678)

        # The error points at the API that can actually answer.
        assert "get_port" in str(excinfo.value)


def test_ps_reports_running_containers_and_published_ports():
    deployment = testing(COMPOSE_FILE)
    with deployment:
        deployment.up()

        containers = deployment.ps()
        assert [c.service for c in containers] == ["echo"]

        echo = containers[0]
        assert echo.is_running
        assert echo.is_healthy  # no healthcheck declared => running is enough
        assert any(p.published_port for p in echo.publishers)
