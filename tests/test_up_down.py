from dokker import base_setup, HealthCheck
import pytest


def test_up_down():
    with base_setup(
        "tests/configs/docker-compose.yaml",
        ht_checks=[HealthCheck(url="http://localhost:8456/graphql", service="mikro")],
    ):
        # do something with redis

        print("hello world")

        pass


@pytest.mark.asyncio
async def atest_up_down():
    async with base_setup(
        "tests/configs/docker-compose.yaml",
        ht_checks=[HealthCheck(url="http://localhost:8456/graphql", service="mikro")],
    ):
        # do something with redis

        print("hello world")

        pass
