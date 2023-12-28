# Dokker

### Development

This is a development version of the package. Its API is not stable and
might change at any time.

## Inspiration

This package is designed to manage docker compose projects programmatically via python.

It provides a simple way to create, start, stop, and remove docker compose projects, as well as 
a way to interact with the containers and services within the project ( like running commands,).

While other packages exist that provide similar functionality (e.g. python-on-whales, testcontainers, etc.),
dokker focusses on interacting with the docker compose project **asyncronously** (using asyncio).

This allows for patterns like inspecting the logs of a container while your python code is interacting with it.


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
    "echo_service", wait_for_logs=True, 
)  # Creates a watcher for the echo_service service, a watcher
# will asynchronously collect the logs of the service and make them available

# start the project (), will block until all health checks are successful
with project:
    # interact with the project

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
project = local("docker-compose.yaml")
project.up_on_enter = False # optional: do not start the project on enter

# start the project ()
async def main()
    async with project:
        # interact with the project
        await project.aup() # start the project (and detach)

        await asyncio.await_for_healtzh() # wait for the health checks to be successful

        async with project.logwatcher("service_to_log", log=print):
            await project.arestart("service_to_log") # restart the service

        

asyncio.run(main())
```
