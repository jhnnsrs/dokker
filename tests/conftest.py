from dokker import local, HealthCheck, Deployment
import pytest

@pytest.fixture(scope="session")
def composed_project() -> Deployment:
    
    
    with local(
        "tests/configs/docker-compose.yaml",
        health_checks=[
            HealthCheck(url="http://localhost:6888/graphql", service="mikro")
        ],
    ) as l:
        # do something with redis
        
        l.up()

        yield l