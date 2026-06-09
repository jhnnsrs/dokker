from typing import Generator
from dokker import testing, HealthCheck, Deployment
import pytest
        
    
@pytest.fixture(scope="session")
def basic_project() -> Generator[Deployment, None, None]:
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
        yield deployment
