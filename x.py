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
    print(setup.spec)
    # interact with the project

    try:
        with watcher:
            # interact with the project
            print(requests.get("http://localhost:5678"))
            raise TException("Something went wrong")
    except TException:
        print("Exception caught")
        raise

    # interact with the project
