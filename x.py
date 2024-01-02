from dokker import local, HealthCheck
import requests
from rich.traceback import install

install(show_locals=False)
# create a project from a docker-compose.yaml file
setup = local(
    "docker-compose.yaml",
    health_checks=[HealthCheck(service="echo_service", url="http://localhost:5678")],
)


class TException(Exception):
    pass


health_check = setup.add_health_check(
    service="echo_service", url="http://localhost:5678"
)  # Creates a health check

watcher = setup.logswatcher(
    "echo_service", wait_for_logs=True
)  # Creates a watcher for the echo_service service

# start the project (), will block until all health checks are successful
with setup:
    print(setup.spec.services.get("echo_service").ports)
    # interact with the project

    with watcher:
        # interact with the project
        print(setup.restart("echo_service"))

    with watcher:
        setup.restart("echo_service")

    print(watcher.collected_logs)

    # interact with the project
