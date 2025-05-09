from dokker import local, HealthCheck
import pytest


def test_up_down():
    with local(
        "tests/configs/docker-compose.yaml",
        health_checks=[
            HealthCheck(url="http://localhost:6888/graphql", service="mikro")
        ],
    ) as l:
        # do something with redis
        
        l.up()

        print("hello world")

        pass


@pytest.mark.asyncio
async def test_up_down_async():
    async with local(
        "tests/configs/docker-compose.yaml",
        health_checks=[
            HealthCheck(url="http://localhost:6888/graphql", service="mikro")
        ],
    ) as l:
        # do something with redis
        
        await l.aup()
        
        await l.acheck_health()

        print("hello world")

        pass
