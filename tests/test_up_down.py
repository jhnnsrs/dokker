import asyncio
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
        l.down()
        
        
        l.up()
        
        answer = l.run("mikro", "echo 'hello world'")
        assert "hello world" in answer.stdout, f"Expected 'hello world', got {answer}"

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
        await l.adown()
        
        await l.aup()
        
        await l.acheck_health()
        
        one_task = asyncio.create_task(l.arun("mikro", "echo 'hello world'"))
        two_task = asyncio.create_task(l.arun("mikro", "echo 'hello world'"))

        print("hello world")
        
        answers = await asyncio.gather(one_task, two_task)
        for answer in answers:
            assert "hello world" in answer.stdout, f"Expected 'hello world', got {answer}"
            

        pass
