from typing import Generator, List
from dokker import testing, HealthCheck, Deployment
from dokker.pytest_plugin import dokker_progress
import pytest

# Needed to test dokker's own pytest plugin; the repo uses pytester nowhere else.
pytest_plugins = ["pytester"]


def pytest_collection_modifyitems(items: List[pytest.Item]) -> None:
    """In *this* repo, `integration` does mean "needs docker".

    dokker's own pytest plugin deliberately only skips tests marked
    `requires_docker` (or requesting a dokker fixture), because `integration` is
    a generic name owned by whichever project is being tested. Here the two
    coincide, so opt our integration suites in explicitly rather than making the
    shipped plugin assume it everywhere.
    """
    for item in items:
        if item.get_closest_marker("integration") is not None:
            item.add_marker(pytest.mark.requires_docker)



@pytest.fixture(scope="session")
def basic_project(request: pytest.FixtureRequest) -> Generator[Deployment, None, None]:
    """A pulled, started, and (on teardown) torn-down lightweight stack."""
    COMPOSE_FILE = "tests/configs/basic-compose.yaml"
    

    with testing(
        COMPOSE_FILE,
        health_checks=[
            HealthCheck(url="http://localhost:5678", service="echo"),
        ],
        # The worker/redis containers ignore SIGTERM, so a short grace period
        # keeps teardown from blocking the full default 10s per container.
        shutdown_timeout=1,
    ) as deployment:
        # Nothing happens on enter; drive the lifecycle explicitly. Under the
        # `testing` policy a bare `up()` registers the on-exit `down` (which runs
        # when this `with` block exits, after the test session). `inspect()`
        # populates `deployment.spec`.
        #
        # `dokker_progress` paints the live status line while that happens. This
        # fixture is hand-rolled rather than built on the `dokker_deployment`
        # factory, which is exactly the common case the helper exists for -- and
        # it is how the feature can be eyeballed in this repo, with
        # `pytest -m integration` in a terminal.
        with dokker_progress(request.config, deployment) as phase:
            phase("pull")
            deployment.pull()
            phase("up")
            deployment.up()
            phase("inspect")
            deployment.inspect()
            phase("health")
            deployment.check_health()
        yield deployment
