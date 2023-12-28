from dokker import local, HealthCheck
import requests

# create a project from a docker-compose.yaml file
project = local(
    "docker-compose.yaml",
    health_checks=[
        HealthCheck(
            service="echo_service",
            url="http://localhost:5678",
            max_retries=2,
            timeout=5,
        )
    ],
)

watcher = project.logswatcher(
    "echo_service", wait_for_logs=True
)  # Creates a watcher for the echo_service service

# start the project (), will block until all health checks are successful
with project:
    # interact with the project

    with watcher:
        # interact with the project
        print(requests.get("http://localhost:5678"))

    print(watcher.collected_logs)
    # interact with the project
