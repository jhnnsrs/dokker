import asyncio
from dokker import local, HealthCheck
import pytest

COMPOSE_FILE = "tests/configs/lifecycle-compose.yaml"


@pytest.mark.integration
def test_up_down():
    with local(
        COMPOSE_FILE,
        health_checks=[
            HealthCheck(url="http://localhost:5679", service="echo")
        ],
    ) as l:
        l.down()

        l.up(down_on_exit=True)

        answer = l.run("worker", "echo 'hello world'")
        assert "hello world" in answer.stdout, f"Expected 'hello world', got {answer}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_up_down_async():
    async with local(
        COMPOSE_FILE,
        health_checks=[
            HealthCheck(url="http://localhost:5679", service="echo")
        ],
        shutdown_timeout=1,
    ) as l:
        await l.adown()

        await l.aup(down_on_exit=True)

        await l.acheck_health()

        one_task = asyncio.create_task(l.arun("worker", "echo 'hello world'"))
        two_task = asyncio.create_task(l.arun("worker", "echo 'hello world'"))

        answers = await asyncio.gather(one_task, two_task)
        for answer in answers:
            assert "hello world" in answer.stdout, f"Expected 'hello world', got {answer}"
