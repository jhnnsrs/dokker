# Dokker

### Development

This is an open source project, and contributions are welcome! The api is only partially stable, so feel free to suggest changes or improvements.

## Inspiration

This package is designed to manage docker compose projects programmatically via python.

It provides a simple way to create, start, stop, and remove docker compose projects, as well as 
a way to interact with the containers and services within the project ( like running commands,).

While other packages exist that provide similar functionality (e.g. python-on-whales, testcontainers, etc.),
dokker focusses on interacting with the docker compose project **asyncronously** (using asyncio, but with sync apis).

This allows for patterns like inspecting the logs of a container while your python code is interacting with it.

The primary use case for this package is to create integration tests for docker compose projects.
It easily integrates with pytest.


## Installation

```bash
pip install dokker
```

## Sync Usage

Imaging you have a docker-compose.yaml file that looks like this:

```yaml
version: "3.4"

services:
  echo_service:
    image: hashicorp/http-echo
    command: ["-text", "Hello from HashiCorp!"]
    ports:
      - "5678:5678"
```

To utilize this project in python, you can use the `local` function to create a project from the docker-compose.yaml file.
(you can also use other builder functions to create projects from other sources, e.g. a cookiecutter template)

```python
from dokker import local, HealthCheck
import requests

# create a project from a docker-compose.yaml file
deployment = local(
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

watcher = deployment.logswatcher(
    "echo_service", wait_for_logs=True, 
)  # Creates a watcher for the echo_service service, a watcher
# will asynchronously collect the logs of the service and make them available

with deployment:
    # interact with the project

    deployment.up()  # start the project

    deployment.check_health()  # check the health of the project


    with watcher:

        # interact with the project
        print(requests.get("http://localhost:5678"))

        # as we set wait_for_logs=True, the watcher will block until the logs are collected

    print(watcher.collected_logs)
    # interact with the project


```

## Async Usage

```python
from dokker import local

# create a project from a docker-compose.yaml file
deployment = local("docker-compose.yaml")
deployment.up_on_enter = False # optional: do not start the project on enter

# start the project ()
async def main()
    async with deployment:
        # interact with the project
        await deployment.aup() # start the project (and detach)


        async with deployment.logwatcher("service_to_log", log=print):
            await deployment.arestart("service_to_log") # restart the service

        

asyncio.run(main())
```

## Pytest Usage

```python
import pytest
from dokker import local

@pytest.fixture(scope="session")
def deployment():
    deployment = local("docker-compose.yaml")
    deployment.health_on_enter = True
    with project:
        yield project


