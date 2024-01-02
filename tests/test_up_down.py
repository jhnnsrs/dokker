from dokker import easy, local_project, HealthCheck
import pytest


def test_up_down():
    with easy(
        local_project(
            "tests/configs/docker-compose.yaml",
            health_checks=[
                HealthCheck(url="http://localhost:8456/graphql", service="mikro")
            ],
        )
    ):
        # do something with redis

        print("hello world")

        pass


@pytest.mark.asyncio
async def atest_up_down():
    async with easy(
        local_project(
            "tests/configs/docker-compose.yaml",
            health_checks=[
                HealthCheck(url="http://localhost:8456/graphql", service="mikro")
            ],
        )
    ):
        # do something with redis

        print("hello world")

        pass
