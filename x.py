from dokker import HealthCheck, testing

"""A pulled, started, and (on teardown) torn-down lightweight stack."""
COMPOSE_FILE = "tests/configs/basic-compose.yaml"


with testing(
    COMPOSE_FILE,
    health_checks=[
        HealthCheck(url="http://localhost:5678", service="echo"),
    ],
    shutdown_timeout=1,
) as deployment:
    deployment.pull()
    deployment.up()  # "testing" policy: downs on exit
    deployment.inspect()
    print(deployment.check_health())

    print(deployment.run("worker", "timeout 10 sleep 10", raise_on_error=False))
