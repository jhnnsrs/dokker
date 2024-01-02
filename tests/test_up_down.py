from dokker import local, local_project, HealthCheck
import pytest


def test_up_down():
    with local(
        "tests/configs/docker-compose.yaml",
        health_checks=[
            HealthCheck(url="http://localhost:8456/graphql", service="mikro")
        ],
    ):
        # do something with redis

        print("hello world")

        pass


@pytest.mark.asyncio
async def atest_up_down():
    async with local(
        "tests/configs/docker-compose.yaml",
        health_checks=[
            HealthCheck(url="http://localhost:8456/graphql", service="mikro")
        ],
    ):
        # do something with redis

        print("hello world")

        pass
