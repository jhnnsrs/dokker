"""End-to-end integration tests against a lightweight, standard-image stack.

Unlike the mikro tests, these only use small public images
(``hashicorp/http-echo``, ``redis:7-alpine``, ``alpine``), so they can run on
any machine with a docker daemon. They exercise the full dokker surface:
lifecycle (up/down), config inspection, health checks, the log watcher, and
``run`` with its exit-code handling.

Run them with::

    pytest -m integration -k basic
"""

import subprocess
from typing import Generator

import pytest
import requests

from dokker import CommandError, Deployment, HealthCheck



pytestmark = pytest.mark.integration



def test_health_check_passes(basic_project: Deployment) -> None:
    """The echo service answers 200, so the health check should pass."""
    basic_project.check_health()


def test_inspect_exposes_published_port(basic_project: Deployment) -> None:
    """Inspecting the config resolves the published port for an internal one."""
    port = basic_project.spec.services["echo"].get_port_for_internal(5678)
    assert port.published == 5678


def test_inspect_finds_all_services(basic_project: Deployment) -> None:
    """All three declared services show up in the inspected spec."""
    services = basic_project.spec.services
    assert services is not None
    assert {"echo", "redis", "worker"}.issubset(services.keys())


def test_run_returns_stdout_and_zero_exit(basic_project: Deployment) -> None:
    """A successful command returns its stdout and a zero exit code."""
    logs = basic_project.run("worker", "echo hello world")
    assert "hello world" in logs.stdout
    assert logs.returncode == 0


def test_run_raises_on_nonzero_exit(basic_project: Deployment) -> None:
    """By default a non-zero exit raises a CommandError."""
    with pytest.raises(CommandError) as excinfo:
        basic_project.run("worker", "false")
    assert excinfo.value.returncode != 0


def test_run_can_suppress_raise(basic_project: Deployment) -> None:
    """With raise_on_error=False the exit code is reported, not raised."""
    logs = basic_project.run("worker", "false", raise_on_error=False)
    assert logs.returncode == 1


def test_run_accepts_expected_nonzero_exit(basic_project: Deployment) -> None:
    """A command expected to fail with a given code does not raise."""
    logs = basic_project.run("worker", "false", expected_exit_code=1)
    assert logs.returncode == 1


def test_run_raises_carries_exit_code_and_stderr(basic_project: Deployment) -> None:
    """A failing container surfaces its exact exit code and its stderr.

    This is the core failure-feedback contract: when a container inside the
    compose project dies, the raised ``CommandError`` must carry the structured
    information (exit code + the stderr the container emitted) so a caller can
    tell *why* it failed without scraping a single log blob.
    """
    with pytest.raises(CommandError) as excinfo:
        basic_project.run("worker", "sh -c 'echo boom >&2; exit 7'")

    error = excinfo.value
    assert error.returncode == 7
    assert any("boom" in line for line in error.stderr)


def test_run_failure_message_surfaces_stderr(basic_project: Deployment) -> None:
    """The human-readable error message mentions the code and the stderr text."""
    with pytest.raises(CommandError) as excinfo:
        basic_project.run("worker", "sh -c 'echo kaboom >&2; exit 5'")

    message = str(excinfo.value)
    assert "return code 5" in message
    assert "kaboom" in message


def test_run_wrong_exit_code_raises_with_expectation_note(
    basic_project: Deployment,
) -> None:
    """A non-matching exit code still raises and notes what was expected.

    Here the command exits 1 but the caller expected 2, so even though it
    failed, it did not fail the *expected* way and must be raised.
    """
    with pytest.raises(CommandError) as excinfo:
        basic_project.run("worker", "false", expected_exit_code=2)

    error = excinfo.value
    assert error.returncode == 1
    assert "Expected exit code 2" in str(error)




def test_log_watcher_collects_request_logs(basic_project: Deployment) -> None:
    """The watcher captures the echo server logging the request we make."""
    port = basic_project.spec.services["echo"].get_port_for_internal(5678).published

    watcher = basic_project.create_watcher("echo")
    with watcher:
        response = requests.get(f"http://localhost:{port}/")
        assert response.status_code == 200

    assert watcher.collected_logs, "Expected the watcher to collect logs"
    # The request we made should appear in the captured server logs.
    assert any("GET /" in line for _, line in watcher.collected_logs)


def _running_follow_log_processes() -> list[str]:
    """Return the command lines of any `docker compose ... logs --follow` procs.

    Used to assert the watcher does not leak its streaming subprocess.
    """
    out = subprocess.run(
        ["ps", "-eo", "args"], capture_output=True, text=True, check=False
    ).stdout
    return [line for line in out.splitlines() if "logs" in line and "--follow" in line]


def test_log_watcher_cleans_up_on_exception(basic_project: Deployment) -> None:
    """An exception through the `with watcher:` block must not leak the stream.

    Regression test: ``LogWatcher.__aexit__`` used to re-raise the augmented
    exception *before* cancelling the watch task, so any error (an assertion, a
    Ctrl-C, a request failure) left a ghost ``docker compose logs --follow``
    subprocess running. The teardown now happens in a ``finally`` so cancellation
    always runs.
    """

    class _Boom(Exception):
        pass

    before = _running_follow_log_processes()

    watcher = basic_project.create_watcher("echo")
    with pytest.raises(_Boom):
        with watcher:
            raise _Boom("failure inside the watcher body")

    # The watch task must have been cancelled and cleared...
    assert watcher._watch_task is None
    # ...and no new follow-stream subprocess may survive the failed block.
    after = _running_follow_log_processes()
    assert len(after) <= len(before), f"Leaked follow-log process: {after}"
