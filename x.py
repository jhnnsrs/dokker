from dokker import local, HealthCheck
from rich.traceback import install

install(show_locals=False)
# create a project from a docker-compose.yaml file
setup = local(
    "docker-compose.yaml",
    health_checks=[HealthCheck(service="echo_service", url="http://localhost:5678")],
)


health_check = setup.add_health_check(
    service="echo_service",
    url=lambda spec: f"http://localhost:{spec.services['echo_service'].get_port_for_internal(5678).published}",
)  # Creates a health check

watcher = setup.create_watcher(
    "echo_service", wait_for_logs=True
)  # Creates a watcher for the echo_service service

# start the project (), will block until all health checks are successful
with setup:

    # interact with the project

    setup.inspect()

    with watcher:
        setup.restart("echo_service")

        setup.check_health()

    print(watcher.collected_logs.stdout)

    # interact with the project
