"""Pytest integration for dokker.

Registered automatically via a ``pytest11`` entry point, so simply installing
dokker makes the fixtures and flags below available -- no ``conftest.py`` import
required.

What this adds over writing the fixture by hand:

- ``--dokker-keep`` leaves the stack running after the session, so a failed test
  can be debugged against the containers that actually failed. Hand-written
  fixtures usually have no way to do this without editing code.
- Docker-dependent tests skip cleanly instead of failing when no daemon is
  reachable, which is what makes a single ``pytest`` invocation safe in CI
  matrices that include machines without docker.
- ``dokker_deployment`` is a *factory*, so a test module can define its own
  session-scoped stack in a couple of lines while keeping the flags above.
- A live progress line (see ``dokker.loggers.progress``) replaces the silent wait
  while a stack pulls, starts and passes its readiness checks. It is on by
  default only on a real terminal, so piped and CI output is unchanged.
"""

import contextlib
import os
import sys
from typing import TYPE_CHECKING, Any, Callable, Generator, Iterator, List, Optional

import pytest

from dokker.builders import testing
from dokker.deployment import Deployment
from dokker.loggers.print import PrintLogger
from dokker.loggers.progress import ProgressLogger
from dokker.types import ValidPath

if TYPE_CHECKING:
    from dokker.checks import Check


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register dokker's command line flags."""
    group = parser.getgroup("dokker", "docker compose stacks")
    group.addoption(
        "--dokker-keep",
        action="store_true",
        default=False,
        help="Leave stacks started by dokker running after the session, for post-mortem debugging.",
    )
    group.addoption(
        "--dokker-no-pull",
        action="store_true",
        default=False,
        help="Skip `docker compose pull` when starting a dokker stack (use the local images).",
    )
    group.addoption(
        "--dokker-log",
        action="store_true",
        default=False,
        help="Print docker compose output while stacks start and stop.",
    )
    group.addoption(
        "--dokker-progress",
        action="store",
        default="auto",
        choices=("auto", "on", "off"),
        help="Show a live one-line progress display while a stack starts. `auto` (the default) enables it only on a terminal, so piped and CI output is unaffected.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the markers this plugin owns.

    Only ``requires_docker`` -- a dokker-specific name. This plugin loads in
    every pytest run of every project that depends on dokker, so it must not
    claim a generic name like ``integration``, which most projects already use
    to mean "slow / talks to a real service" rather than "needs docker".
    """
    config.addinivalue_line("markers", "requires_docker: marks tests that need a running docker daemon; skipped automatically when none is reachable")


def _probe_docker() -> bool:
    """Probe once whether a usable docker daemon is reachable."""
    import asyncio

    from dokker.command import ais_docker_available

    return asyncio.run(ais_docker_available())


DOKKER_FIXTURES = frozenset({"dokker_deployment", "docker_available", "dokker_keep"})


def _supports_ansi(stream: Any) -> bool:
    """Whether in-place redrawing will actually look like anything on `stream`.

    A pipe or a file gets no progress line: the carriage returns would be
    written into it verbatim. Bare ``cmd.exe`` reports ``isatty()`` while
    rendering ``\\x1b[K`` as literal garbage, so Windows requires a positive
    signal that VT sequences are processed.
    """
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False

    if os.environ.get("TERM") == "dumb":
        return False

    if sys.platform == "win32":
        # Windows Terminal and ANSICON set these; the legacy console does not.
        return bool(os.environ.get("WT_SESSION") or os.environ.get("ANSICON") or os.environ.get("TERM"))

    return True


def _progress_enabled(config: pytest.Config) -> bool:
    """Resolve ``--dokker-progress`` against the current output stream.

    Must be called with pytest's capture *suspended*. Under the default
    file-descriptor capture, ``sys.stdout`` points at a temp file while capture
    is active, so ``auto`` would resolve to False in every run -- including on a
    real terminal.
    """
    mode = str(config.getoption("--dokker-progress"))
    if mode == "off":
        return False
    # Raw log output and a self-erasing status line cannot share a terminal:
    # every compose line would scroll the progress line away. Explicit wins.
    if config.getoption("--dokker-log"):
        return False
    if mode == "on":
        return True
    return _supports_ansi(sys.stdout)


def _noop_phase(name: str) -> None:
    """Discard a phase label when nothing is being rendered."""


@contextlib.contextmanager
def _capture_disabled(config: pytest.Config) -> Generator[bool, None, None]:
    """Suspend pytest's global output capture for the duration of the block.

    Yields whether suspension actually succeeded. pytest captures at the file
    descriptor level by default, so without this every frame is swallowed and
    then replayed later as carriage-return litter.

    ``CaptureManager`` is private API, hence the defensive lookup. When it
    cannot be suspended the caller renders only if capture is off anyway
    (``-s``); otherwise it renders nothing, rather than writing frames into a
    buffer that pytest will replay verbatim on the next failure.
    """
    capman = config.pluginmanager.getplugin("capturemanager")
    disabled = getattr(capman, "global_and_fixture_disabled", None)
    if disabled is None:
        yield getattr(config.option, "capture", None) == "no"
        return
    with disabled():
        yield True


@contextlib.contextmanager
def dokker_progress(config: pytest.Config, deployment: Deployment) -> Generator[Callable[[str], None], None, None]:
    """Render a live progress line for `deployment` for the duration of the block.

    Yields a ``phase(name)`` callable to label each step. It is always safe to
    call: when progress is disabled -- piped output, ``--dokker-progress=off``,
    ``--dokker-log``, unsuspendable capture -- the renderer is never created and
    ``phase`` does nothing.

    Public because the fixture below is not the only way stacks get built. Most
    projects (this repo included) hand-roll a session fixture around
    :func:`dokker.testing`, and this is what makes the progress line available
    there in three lines::

        @pytest.fixture(scope="session")
        def stack(request):
            with testing("docker-compose.yaml") as deployment:
                with dokker_progress(request.config, deployment) as phase:
                    phase("up")
                    deployment.up()
                yield deployment
    """
    # Short-circuit the cases that need no terminal probe, so capture is never
    # lifted for a run that was not going to render anything. Suspending it
    # regardless would let unrelated output (the stdlib `logger.warning` calls in
    # `deployment.py`, a check that prints) escape pytest's capture, and would
    # quietly turn `--dokker-log` from captured into live output.
    mode = str(config.getoption("--dokker-progress"))
    if mode == "off" or config.getoption("--dokker-log"):
        yield _noop_phase
        return

    # `auto` has no such shortcut: probing `sys.stdout.isatty()` is only truthful
    # once capture is lifted, so suspension has to come first.
    with _capture_disabled(config) as suspended:
        renderer: Optional[ProgressLogger] = None
        if _progress_enabled(config) and suspended:
            renderer = ProgressLogger(label=getattr(deployment.project, "project_name", None) or "dokker")
            deployment.logger = renderer
            renderer.start()
        try:
            yield renderer.phase if renderer is not None else _noop_phase
        finally:
            if renderer is not None:
                # Stop and erase *inside* the capture-suspension block: a frame
                # written after capture resumes would be replayed later as
                # carriage-return litter in some unrelated test's output.
                renderer.stop()


def _needs_docker(item: pytest.Item) -> bool:
    """Whether this test can only run with a docker daemon.

    Deliberately narrow: a test qualifies by opting in with dokker's own
    ``requires_docker`` marker, or by requesting one of dokker's fixtures. It is
    *not* enough to be marked ``integration`` -- that name belongs to the project
    under test, not to dokker, and in most projects it means "slow" rather than
    "needs docker".
    """
    if item.get_closest_marker("requires_docker") is not None:
        return True
    return bool(DOKKER_FIXTURES & set(getattr(item, "fixturenames", ())))


def pytest_collection_modifyitems(config: pytest.Config, items: List[pytest.Item]) -> None:
    """Skip docker-dependent tests when no daemon is reachable.

    Done at collection rather than in an autouse fixture, because a
    session-scoped stack fixture is set up *before* any function-scoped fixture
    of the tests that use it -- so an autouse skip would fire only after the
    stack had already tried, and failed, to start.

    Without this, a CI leg on a machine with no docker daemon reports errors for
    tests that were never runnable there. Skipping is the honest outcome: the
    test did not run, and did not pass.
    """
    candidates = [item for item in items if _needs_docker(item)]
    if not candidates:
        return

    if _probe_docker():
        return

    skip = pytest.mark.skip(reason="no reachable docker daemon; skipping docker-dependent test")
    for item in candidates:
        item.add_marker(skip)


@pytest.fixture(scope="session")
def docker_available() -> bool:
    """Whether a usable docker daemon is reachable.

    Probed once per session. Use it to skip or branch in tests that are not
    marked ``integration``.
    """
    return _probe_docker()


@pytest.fixture(scope="session")
def dokker_keep(request: pytest.FixtureRequest) -> bool:
    """Whether ``--dokker-keep`` was passed."""
    return bool(request.config.getoption("--dokker-keep"))


@pytest.fixture(scope="session")
def dokker_deployment(request: pytest.FixtureRequest) -> Iterator[Callable[..., Deployment]]:
    """A factory for compose stacks that respects dokker's pytest flags.

    Returns a callable with the same signature as :func:`dokker.testing`, plus
    ``health_checks``. Each stack it creates is pulled, brought up, inspected and
    health-checked, and is torn down when the session ends -- unless
    ``--dokker-keep`` was passed.

    Examples
    --------
    ::

        @pytest.fixture(scope="session")
        def stack(dokker_deployment):
            return dokker_deployment(
                "docker-compose.yaml",
                health_checks=[TcpCheck(service="db", port=5432)],
            )

        def test_it(stack):
            assert requests.get(stack.get_url("web", 8000)).ok
    """
    config = request.config
    keep = bool(config.getoption("--dokker-keep"))
    no_pull = bool(config.getoption("--dokker-no-pull"))
    log = bool(config.getoption("--dokker-log"))

    started: List[Deployment] = []

    def _factory(
        compose_file: ValidPath,
        health_checks: Optional[List["Check"]] = None,
        wait: bool = False,
        **kwargs: Any,
    ) -> Deployment:
        deployment = testing(compose_file, health_checks=health_checks, **kwargs)
        if log:
            deployment.logger = PrintLogger()

        deployment.enter()
        started.append(deployment)

        with dokker_progress(config, deployment) as phase:
            # Every step is labelled, including the two that emit no output at
            # all: `inspect` is quick, but `check_health` can be the longest wait
            # in the whole session and would otherwise look like a hang.
            if not no_pull:
                phase("pull")
                deployment.pull()
            phase("up")
            # `--dokker-keep` means: do not tear this down at the end of the session.
            deployment.up(wait=wait, down_on_exit=False if keep else None)
            phase("inspect")
            deployment.inspect()
            if health_checks:
                phase("health")
                deployment.check_health()

        return deployment

    yield _factory

    for deployment in reversed(started):
        deployment.exit()

    if keep and started:
        print("\n--dokker-keep: stacks left running. Remove them with `docker compose ls` + `docker compose -p <name> down -v`.")
