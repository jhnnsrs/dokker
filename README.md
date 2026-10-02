# Dokker

**Manage Docker Compose projects programmatically from Python — async-first, with synchronous APIs.**

Dokker lets you drive a `docker compose` project from Python: pull, start, inspect, health-check, run commands inside services, stream logs, and tear everything down again. It is built around `asyncio` but exposes a fully synchronous API as well, so it fits equally well in async applications and in plain pytest test suites.

Its primary use case is **writing integration tests for Docker Compose stacks**, where you want to spin up a real set of containers, wait until they are healthy, exercise them, assert on their logs and exit codes, and have them reliably torn down afterwards.

---

## Why dokker?

Other tools cover similar ground (e.g. [python-on-whales](https://github.com/gabrieldemarmiesse/python-on-whales), [testcontainers](https://github.com/testcontainers/testcontainers-python)). Dokker's distinguishing focus is **asynchronous interaction with a running compose project**:

- **Watch logs while you act.** A `LogWatcher` collects a service's logs in the background while your code makes requests against it — so you can assert that an HTTP call actually produced the log line you expected, or block until it does with `await_log()`.
- **Structured failure feedback.** When a command in a container exits non-zero, dokker raises a `CommandError` that carries the exact exit code and the container's `stdout`/`stderr` separately, so you can tell *why* it failed instead of scraping one concatenated blob.
- **Truly parallel-safe stacks.** `get_port()` resolves the *runtime* host port, so your compose file can leave the host port to docker and several copies of the same stack can run at once without colliding.
- **Readiness for services that don't speak HTTP.** Databases and brokers get `TcpCheck`, `CommandCheck`, `ContainerCheck` and `LogCheck` alongside the HTTP `HealthCheck` — or defer to compose itself with `up(wait=True)`.
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
| `"testing"` | `down` — removes containers, networks, **volumes, orphans & the images built for the project**, and tears the project down (e.g. a `mirror` temp dir) |
| `"local"` | `stop` — stops containers but keeps them and any data volumes |
| `"monitoring"` | nothing — never changes the stack |
| `"manual"` | nothing — you tear it down yourself (the default for a hand-built `Deployment`) |

Per-call **local overrides** always win: `up(down_on_exit=True)` forces a down, `up(stop_on_exit=True)` forces a stop, and `up(down_on_exit=False)` opts out entirely — regardless of the policy.

### Builders

You rarely construct a `Deployment` by hand. Instead you pick a **builder** that presets a policy plus sensible config (project, timeouts, `down` options). Builders do **not** act on enter — you call the lifecycle methods you need inside the block, and the policy handles exit:

| Builder | Use case | Policy | Typical body |
|---|---|---|---|
| `local(...)` | Drive a stack you start/stop yourself during a session. | `local` | `up()` (stops on exit, keeps data) |
| `testing(...)` | Full integration test: bring everything up, wait for health, clean up completely. | `testing` | `pull()`, `up()`, `inspect()`, `check_health()` (downs + removes volumes/orphans/built images on exit) |
| `monitoring(...)` | Observe/inspect a stack already running in production; never changes it via the compose CLI. | `monitoring` | `inspect()`, `check_health()` |
| `mirror(...)` | Copy a local project into a temp dir and run it there, isolated from the source. | `testing` | `up()`; downs and removes the temp copy on exit |

All builders accept a compose file path (or list of paths), an optional list of `HealthCheck`s, and an optional `policy=` to override the default.

### Project isolation (`project_name`)

By default Docker Compose derives the **project name** from the compose file's directory basename, so two deployments whose compose files live in the same (or a same-named) directory share a project — and one's `up()` recreates the other's services while its `down()` tears down the other's containers. Every builder accepts an optional `project_name` to set Compose's `-p`/`--project-name` flag and keep deployments isolated:

```python
deployment = local("docker-compose.yaml", project_name="my-service")
```

`local(...)` derives a stable default when you pass none: the directory basename for the standard file names (`compose.yaml`, `docker-compose.yaml`, …) — exactly what a hand-typed `docker compose up` there would use, so existing stacks keep their names — and `<directory>-<file stem>` for any other file (`stacks/a-compose.yaml` → `stacks-a-compose`), so sibling compose files in one directory never merge. `monitoring(...)` leaves the name to compose, since it observes stacks it did not start.

`testing(...)` is the exception: it defaults `project_name` to a unique random value (`dokker-test-<id>`) so parallel/identical test stacks get their own containers and networks. Pass an explicit `project_name` to pin it. `testing` also exposes `remove_orphans` and `remove_volumes` (both `True` by default) and `remove_images` (`"local"` by default) to control what `down` cleans up on teardown.

Because the project name is random, compose tags everything it builds for the stack as `dokker-test-<id>-<service>`, a name no later run will ask for. `remove_images="local"` removes exactly those on `down`; images a service names itself (`image:`), pulled images and the build cache stay, so the next run still builds from cache and pulls nothing again. `"all"` removes every image the services use, `None` keeps them. `reap_stale()` also removes the images of the stacks it reaps, and sweeps the `dokker-test-*` images that no stack uses any more and that were tagged over an hour ago (`dokker.reap_orphan_images()` does only that).

### Stray stacks: dokker cleans up after its own dead processes

A `down` on exit is a promise the *process* keeps, and a SIGKILLed test run, a closed terminal or a stopped debugger never reaches it. The stack it started stays up under a `dokker-test-<id>` name nobody recognises. **Do not clean these with a name sweep** such as `docker ps -a | grep dokker-test | xargs docker rm -f`: a sweep cannot tell a stray from the stack a live run in another terminal is using right now, and killing that one turns a green suite into hundreds of "database vanished" errors with no local cause.

Instead, every `up()` that registers a `down` on exit:

1. labels the stack's containers with the owning process (`dokker.owner.pid`, `dokker.owner.host`, `dokker.owner.start`), and
2. first removes the stacks whose owner is provably gone — same host, PID no longer running (or recycled) — containers, networks and volumes.

The rule is that dokker reaps only what it would itself have torn down: a kept stack (`up(down_on_exit=False)`, `--dokker-keep`), a `local()` stack (policy `stop`), a stack recorded by another host, or anything not started by dokker carries no owner label and is never touched. Nor is a stack whose owner is still alive. Opt out with `testing(..., reap_stale=False)` / `Deployment(reap_stale=False)`, or clean a machine by hand with:

```python
import dokker
dokker.reap_stale()   # -> ["dokker-test-3f9a12c0", ...]; the project names it removed
```

### Ports: `get_port()` and `get_url()`

A unique project name isolates containers and networks — but **not host ports**. Two stacks that both declare `ports: ["5678:5678"]` still fight over host port 5678. To run identical stacks in parallel, leave the host port out and let docker assign one:

```yaml
services:
  echo:
    image: hashicorp/http-echo
    ports:
      - "5678"        # container port only; docker picks the host port
```

That port is decided at runtime, so it does not appear in `docker compose config` (and therefore not in `deployment.spec`). Resolve it from the running stack instead:

```python
port = deployment.get_port("echo", 5678)              # e.g. 32768
url  = deployment.get_url("echo", 5678, path="/health")
```

`deployment.ps()` returns the runtime state of each container — `state`, `health`, `exit_code` and published ports — which is usually what you want when something has crashed.

### Readiness checks

A check answers "is this service ready yet?". `deployment.check_health()` runs them all concurrently, retrying each according to its own `max_retries`/`timeout`.

| Check | Ready when | Use for |
|---|---|---|
| `HealthCheck(url=..., service=...)` | An HTTP GET returns an expected status | Web services |
| `TcpCheck(service=..., port=...)` | A TCP connection to the resolved host port succeeds | Anything that listens on a socket |
| `CommandCheck(service=..., command=...)` | A command run *inside* the container exits `0` | `pg_isready`, `redis-cli ping` |
| `ContainerCheck(service=...)` | Docker reports the container running (and `healthy`, if it declares a healthcheck) | Any service with a compose `healthcheck:` |
| `LogCheck(service=..., pattern=...)` | A log line matches a regex | `"database system is ready to accept connections"` |

`HealthCheck.timeout` is the sleep *between* retries; `request_timeout` bounds a single HTTP request.

If your compose file already declares `healthcheck:` for its services, you may not need checks at all — `deployment.up(wait=True)` uses compose's own readiness mechanism:

```python
deployment.up(wait=True, wait_timeout=60)   # returns once everything is healthy
```

### `run()`, `exec()` and exit codes

Both run a command in a service and return a `LogRoll` with `.returncode`, `.stdout` and `.stderr`. The difference is *where*:

- **`deployment.exec(service, command)`** runs in the **already-running** container (`docker compose exec`). Use it when the command must see live state — querying the running database, reading a file the service wrote.
- **`deployment.run(service, command)`** creates a **fresh throwaway** container (`docker compose run`). Use it for one-off jobs that don't need the running instance.

For both, a non-zero exit raises a `CommandError` by default; opt out with `raise_on_error=False`, or declare an expected failure code with `expected_exit_code=...`.

Commands may be given as a string or a list:

```python
deployment.exec("redis", "redis-cli ping")            # tokenized shell-style
deployment.exec("redis", ["redis-cli", "ping"])       # already an argument vector
deployment.run("worker", "sh -c 'echo hi; exit 1'")   # quoted script stays one argument
```

Commands are executed directly rather than through a host shell, so shell syntax must go to a shell you name yourself (`sh -c '...'`, as above). A list is passed through untouched, one element per argument — so write `["redis-cli", "ping"]`, not `["redis-cli ping"]`.

### Other operations

`pull()`, `build()`, `stop()`, `kill()`, `restart()`, `down()`, `logs()` (one-shot), `ps()` and `cp()` are all available, each with an `a`-prefixed async twin. `up()` forwards the compose options you'd expect: `services`, `build`, `wait`, `force_recreate`, `pull`, `scales`, `remove_orphans`.

### `LogWatcher`

`deployment.create_watcher(service)` returns a context manager that streams a service's logs in the background. Inside the `with` block you interact with the service; afterwards `watcher.collected_logs` holds the captured `(source, line)` pairs. The watcher always cleans up its streaming subprocess, even if the block raises.

`await_log(pattern, timeout=...)` blocks until a captured line matches — a synchronisation primitive rather than a sleep. Lines captured since the watcher was entered count, so there is no race between the event happening and the wait starting:

```python
with deployment.create_watcher("worker") as watcher:
    trigger_the_job()
    watcher.await_log(r"job \d+ finished", timeout=30)
```

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

Installing dokker registers a pytest plugin, so the fixtures and flags below need no `conftest.py` wiring.

The `dokker_deployment` fixture is a factory: give it a compose file and your checks, and it pulls, starts, inspects and health-checks the stack, then tears it down when the session ends.

```python
import pytest
import requests
from dokker import TcpCheck, Deployment


@pytest.fixture(scope="session")
def stack(dokker_deployment):
    return dokker_deployment(
        "docker-compose.yaml",
        health_checks=[TcpCheck(service="echo", port=5678)],
    )


def test_echo_responds(stack: Deployment):
    assert requests.get(stack.get_url("echo", 5678)).status_code == 200
```

While the stack comes up you get a single self-updating status line, so a slow pull or a container stuck on its healthcheck is visible instead of looking like a hang:

```
⠹ dokker-test-a1b2c3d4 · up [1/3] · 4.2s · redis Waiting, echo Started, worker Started
```

It redraws in place and erases itself when the stack is ready, leaving your test output untouched. It is enabled only on a real terminal, so piped and CI output is unaffected — use `--dokker-progress=on` to force it, or `off` to disable it.

Flags:

| Flag | Effect |
|---|---|
| `--dokker-keep` | Leave stacks running after the session, so you can debug the containers that actually failed |
| `--dokker-no-pull` | Skip `pull` and use local images |
| `--dokker-log` | Print compose output while stacks start and stop (takes precedence over the progress line) |
| `--dokker-progress` | `auto` (default, on when attached to a terminal), `on`, or `off` |

Tests marked `@pytest.mark.integration` are **skipped automatically** when no docker daemon is reachable, so one `pytest` invocation is safe on CI machines without docker. A `docker_available` fixture exposes the same probe.

If you prefer to drive the lifecycle yourself, the builder works directly — a bare `up()` registers the `down` that runs when the `with` block exits:

```python
from dokker import testing, HealthCheck

@pytest.fixture(scope="session")
def deployment():
    with testing(
        "docker-compose.yaml",
        health_checks=[HealthCheck(service="echo", url="http://localhost:5678")],
        shutdown_timeout=1,  # SIGKILL containers that ignore SIGTERM after 1s
    ) as deployment:
        deployment.pull()
        deployment.up()
        deployment.inspect()
        deployment.check_health()
        yield deployment
```

A hand-rolled fixture like that gets the progress line too — wrap the lifecycle in `dokker_progress` and label each step. It honours the same flags, and `phase` is always safe to call, so nothing needs guarding when progress is off:

```python
from dokker.pytest_plugin import dokker_progress

@pytest.fixture(scope="session")
def deployment(request):
    with testing("docker-compose.yaml") as deployment:
        with dokker_progress(request.config, deployment) as phase:
            phase("pull")
            deployment.pull()
            phase("up")
            deployment.up()
            phase("health")
            deployment.check_health()
        yield deployment
```

Outside pytest entirely, `ProgressLogger` is a plain `Logger` you can attach to any deployment — `deployment.logger = ProgressLogger(label="my-stack")`, then `start()` / `phase(...)` / `stop()`.

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

# `exec` runs in the container that is already up, so it sees live state
deployment.exec("redis", "redis-cli set greeting hello")
assert "hello" in deployment.exec("redis", "redis-cli get greeting").stdout
```

## Errors

All of dokker's exceptions derive from `DokkerError`, so `except DokkerError` catches everything the library raises.

| Error | Raised when |
|---|---|
| `DockerNotAvailableError` | The `docker` binary is missing or the daemon is unreachable — checked *before* any command runs |
| `CommandError` | A docker command exited non-zero; carries `.returncode`, `.stdout`, `.stderr` |
| `HealthCheckError` | A readiness check failed after its retries, or `check_health()` named a service with no check |
| `PortNotFoundError` | A port is not published, or the container is not running |
| `LogWatcherTimeoutError` | A watcher waited for a log line that never arrived |
| `TearDownError` | The on-exit teardown failed or exceeded `teardown_timeout` |
| `ServiceNotFoundError`, `LabelNotFoundError` | A service or label is absent from the compose spec |
| `ProjectError` | A project could not be set up (e.g. `mirror` found no compose file) |

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
uv sync                            # install dependencies
uv run pytest                      # everything (integration tests skip without docker)
uv run pytest -m "not integration" # unit tests only
uv run pytest -m integration       # the docker-backed integration tests
uv run ruff check dokker           # lint
uv run mypy dokker                 # type check
```

Integration tests require a running Docker daemon and use small public images (`hashicorp/http-echo`, `redis:7-alpine`, `alpine`) so they run anywhere. Without a daemon they skip rather than fail.
