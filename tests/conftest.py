from typing import Generator
from dokker import testing, HealthCheck, Deployment
import pytest

@pytest.fixture(scope="session")
def composed_project() -> Generator[Deployment, None, None]:
    with testing(
        "tests/configs/docker-compose.yaml",
        health_checks=[
            HealthCheck(url="http://localhost:6888/graphql", service="mikro")
        ],
    ) as l:

        yield l