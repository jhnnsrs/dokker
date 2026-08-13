"""Manual smoke script: drives a real stack through the main API surface.

Run with `uv run python x.py` against a working docker daemon. Unlike the test
suite this prints as it goes, so it is handy for eyeballing behavior changes.
"""

from dokker import CommandCheck, ContainerCheck, HealthCheck, testing

COMPOSE_FILE = "tests/configs/basic-compose.yaml"


with testing(
    COMPOSE_FILE,
    health_checks=[
        HealthCheck(url="http://localhost:5678", service="echo"),
        # Readiness for services that speak no HTTP.
        CommandCheck(service="redis", command="redis-cli ping"),
        ContainerCheck(service="worker"),
    ],
    shutdown_timeout=1,
) as deployment:
    deployment.pull()
    deployment.up()  # "testing" policy: downs on exit
    deployment.inspect()
    deployment.check_health()
    print("all checks passed")

    # Runtime container state.
    for container in deployment.ps():
        print(f"  {container.service:8} {container.state:10} health={container.health or '-'}")

    # Runtime port resolution, and the URL built from it.
    print("echo url:", deployment.get_url("echo", 5678))

    # `exec` acts on the running container; `run` creates a throwaway one.
    deployment.exec("redis", "redis-cli set greeting hello")
    print("redis get:", deployment.exec("redis", "redis-cli get greeting").stdout.strip())

    # Exit codes are reported, not swallowed.
    result = deployment.run("worker", "sh -c 'echo to-stderr >&2; exit 3'", raise_on_error=False)
    print(f"run exit code: {result.returncode}, stderr: {result.stderr.strip()!r}")

    # Wait for a specific log line instead of sleeping.
    with deployment.create_watcher("redis") as watcher:
        print("awaited log:", watcher.await_log(r"Ready to accept connections", timeout=30))
