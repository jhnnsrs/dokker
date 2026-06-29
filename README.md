# Dokker

**Manage Docker Compose projects programmatically from Python — async-first, with synchronous APIs.**

Dokker lets you drive a `docker compose` project from Python: pull, start, inspect, health-check, run commands inside services, stream logs, and tear everything down again. It is built around `asyncio` but exposes a fully synchronous API as well, so it fits equally well in async applications and in plain pytest test suites.

Its primary use case is **writing integration tests for Docker Compose stacks**, where you want to spin up a real set of containers, wait until they are healthy, exercise them, assert on their logs and exit codes, and have them reliably torn down afterwards.

---

## Why dokker?

Other tools cover similar ground (e.g. [python-on-whales](https://github.com/gabrieldemarmiesse/python-on-whales), [testcontainers](https://github.com/testcontainers/testcontainers-python)). Dokker's distinguishing focus is **asynchronous interaction with a running compose project**:

- **Watch logs while you act.** A `LogWatcher` collects a service's logs in the background while your code makes requests against it — so you can assert that an HTTP call actually produced the log line you expected.
- **Structured failure feedback.** When a command in a container exits non-zero, dokker raises a `CommandError` that carries the exact exit code and the container's `stdout`/`stderr` separately, so you can tell *why* it failed instead of scraping one concatenated blob.
- **Reliable, bounded teardown.** You drive the lifecycle with explicit calls; a per-deployment **policy** (`testing`/`local`/`monitoring`/`manual`) decides what `up()` cleans up on exit (overridable per call), with grace-period and wall-clock timeouts so an unresponsive container can't hang your test session.
- **Async core, sync surface.** Every operation has both an `await deployment.aup()` form and a blocking `deployment.up()` form (powered by [koil](https://github.com/jhnnsrs/koil)).

---

## Installation

```bash
pip install dokker
```

Dokker requires Python ≥ 3.11 and a working `docker compose` CLI on your `PATH`.

---

## Core concepts

### `Deployment`

The central object. A `Deployment` wraps a compose project and is used as a (sync or async) context manager. **Entering does nothing on its own** — you drive the lifecycle from inside the block by calling `up()`, `down()`, `stop()`, `restart()`, `pull()`, `inspect()`, `check_health()`, `run()` and `create_watcher()`. What happens on exit is governed by the deployment's **teardown policy** (see below): a bare `up()` registers whatever the policy says (down, stop, or nothing), and any temp dir a project copied at initialize time is removed on exit when the policy tears the project down. This keeps containers (and temp dirs) from hanging around — without you having to remember a cleanup call.

### Teardown policy

The `policy` decides what `up()` schedules for context-manager exit. It is set globally on the deployment (each builder picks a sensible default) and overridden per call:

| `policy` | a bare `up()` on exit |
|---|---|
| `"testing"` | `down` — removes containers, networks, **volumes & orphans**, and tears the project down (e.g. a `mirror` temp dir) |
| `"local"` | `stop` — stops containers but keeps them and any data volumes |
| `"monitoring"` | nothing — never changes the stack |
| `"manual"` | nothing — you tear it down yourself (the default for a hand-built `Deployment`) |

Per-call **local overrides** always win: `up(down_on_exit=True)` forces a down, `up(stop_on_exit=True)` forces a stop, and `up(down_on_exit=False)` opts out entirely — regardless of the policy.

### Builders

You rarely construct a `Deployment` by hand. Instead you pick a **builder** that presets a policy plus sensible config (project, timeouts, `down` options). Builders do **not** act on enter — you call the lifecycle methods you need inside the block, and the policy handles exit:

| Builder | Use case | Policy | Typical body |
|---|---|---|---|
| `local(...)` | Drive a stack you start/stop yourself during a session. | `local` | `up()` (stops on exit, keeps data) |
| `testing(...)` | Full integration test: bring everything up, wait for health, clean up completely. | `testing` | `pull()`, `up()`, `inspect()`, `check_health()` (downs + removes volumes/orphans on exit) |
| `monitoring(...)` | Observe/inspect a stack already running in production; never changes it via the compose CLI. | `monitoring` | `inspect()`, `check_health()` |
| `mirror(...)` | Copy a local project into a temp dir and run it there, isolated from the source. | `testing` | `up()`; downs and removes the temp copy on exit |

All builders accept a compose file path (or list of paths), an optional list of `HealthCheck`s, and an optional `policy=` to override the default.

### Project isolation (`project_name`)

By default Docker Compose derives the **project name** from the compose file's directory basename, so two deployments whose compose files live in same-named directories share a project — and one's `down()` tears down the other's containers. Every builder accepts an optional `project_name` to set Compose's `-p`/`--project-name` flag and keep deployments isolated:

```python
deployment = local("docker-compose.yaml", project_name="my-service")
```

`testing(...)` is the exception: it defaults `project_name` to a unique random value (`dokker-test-<id>`) so parallel/identical test stacks never collide. Pass an explicit `project_name` to pin it. `testing` also exposes `remove_orphans` and `remove_volumes` (both `True` by default) to control what `down` cleans up on teardown.

### `HealthCheck`

Describes how to know a service is ready — typically an HTTP URL that should return `200`, with retries and a timeout. Run them on demand via `deployment.check_health()` inside the block.

### `run()` and exit codes

`deployment.run(service, command)` runs a one-off command in a service (`docker compose run`) and returns a `LogRoll` with `.returncode`, `.stdout` and `.stderr`. By default a non-zero exit raises a `CommandError`; you can opt out with `raise_on_error=False`, or declare an expected failure code with `expected_exit_code=...`.

### `LogWatcher`

`deployment.create_watcher(service)` returns a context manager that streams a service's logs in the background. Inside the `with` block you interact with the service; afterwards `watcher.collected_logs` holds the captured `(source, line)` pairs. The watcher always cleans up its streaming subprocess, even if the block raises.

---

## Quickstart (sync)

Given a `docker-compose.yaml`:

```yaml
services:
  echo:
    image: hashicorp/http-echo
    command: ["-text", "Hello from dokker!"]
    ports:
      - "5678:5678"
```

```python
import requests
from dokker import local, HealthCheck

deployment = local(
    "docker-compose.yaml",
    health_checks=[
        HealthCheck(service="echo", url="http://localhost:5678", max_retries=5, timeout=2),
    ],
)

with deployment:
    deployment.up()             # start the stack
    deployment.check_health()   # block until the echo service answers 200

    # Watch the echo service's logs while we hit it
    watcher = deployment.create_watcher("echo")
    with watcher:
        print(requests.get("http://localhost:5678").text)

    print(watcher.collected_logs)
    # -> the captured server logs, including the request we just made

# on exit, `local`'s policy stops the stack for you (containers + data kept)
```

## Integration tests with pytest

The `testing` builder presets the `testing` policy and sensible defaults (unique project name, bounded teardown timeouts, orphan/volume removal on `down`). In the fixture body you pull, bring the stack up, inspect, and wait for health; because the policy is `testing`, a bare `up()` registers the `down` that runs when the fixture's `with` block exits.

```python
import pytest
import requests
from dokker import testing, HealthCheck, Deployment


@pytest.fixture(scope="session")
def deployment():
    with testing(
        "docker-compose.yaml",
        health_checks=[HealthCheck(service="echo", url="http://localhost:5678")],
        shutdown_timeout=1,  # SIGKILL containers that ignore SIGTERM after 1s
    ) as deployment:
        deployment.pull()
        deployment.up()           # testing policy -> fully torn down when the fixture exits
        deployment.inspect()      # populate deployment.spec
        deployment.check_health() # block until echo answers 200
        yield deployment


def test_echo_responds(deployment: Deployment):
    port = deployment.spec.services["echo"].get_port_for_internal(5678).published
    assert requests.get(f"http://localhost:{port}").status_code == 200
```

## Running commands and asserting on exit codes

```python
from dokker import CommandError

# A successful command returns its output and a zero exit code
logs = deployment.run("worker", "echo hello")
assert "hello" in logs.stdout
assert logs.returncode == 0

# A non-zero exit raises a CommandError carrying the code and the container's stderr
try:
    deployment.run("worker", "sh -c 'echo boom >&2; exit 7'")
except CommandError as error:
    assert error.returncode == 7
    assert any("boom" in line for line in error.stderr)

# Inspect the failure without raising...
logs = deployment.run("worker", "false", raise_on_error=False)
assert logs.returncode == 1

# ...or declare that a non-zero exit is the expected outcome
logs = deployment.run("worker", "false", expected_exit_code=1)
```

## Async usage

Every method has an `a`-prefixed async counterpart, and the deployment is also an async context manager:

```python
import asyncio
from dokker import local

async def main():
    deployment = local("docker-compose.yaml")

    async with deployment:
        await deployment.aup()                    # start (detached); local policy stops on exit

        async with deployment.create_watcher("echo"):
            await deployment.arestart("echo")     # restart while watching its logs

asyncio.run(main())
```

---

## Development

This is an open-source project and contributions are welcome. The API is only partially stable, so feel free to suggest changes or improvements.

```bash
uv sync                       # install dependencies
uv run pytest                 # run the unit tests
uv run pytest -m integration  # run the docker-backed integration tests
```

Integration tests require a running Docker daemon and use small public images (`hashicorp/http-echo`, `redis:7-alpine`, `alpine`) so they run anywhere.
