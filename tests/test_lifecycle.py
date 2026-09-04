"""Unit tests for the ``Deployment`` lifecycle — no docker required.

These drive the context-manager / cleanup-registration logic with a fake
``Project`` + ``CLI`` (both protocols are ``@runtime_checkable``, so a plain
recording class validates as ``Deployment(project=...)``). They pin the
branching of the redesigned lifecycle:

* entering does nothing on its own,
* commands register their own LIFO teardown (``up(down_on_exit=...)`` etc),
* project initialization auto-registers its ``atear_down`` inside a context,
* the ``abefore_*`` hooks fire from the methods that perform the action,
* ``down`` removes orphans/volumes by default,
* teardown is bounded and never masks a propagating exception.

Real up/down, volume removal and ``mirror`` temp dirs are covered by the
``integration``-marked suites instead.
"""

import asyncio
import io
import logging
import os

import pytest

from dokker import CommandError, Deployment
from dokker.compose_spec import ComposeSpec
from dokker.errors import NotInitializedError, TearDownError
from dokker.loggers.progress import ProgressLogger


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class Recorder:
    """Ordered log of lifecycle events shared by the fake project and CLI."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.kwargs: dict[str, dict] = {}

    def add(self, name: str, **kw) -> None:
        self.events.append(name)
        if kw:
            self.kwargs[name] = kw

    def count(self, name: str) -> int:
        return self.events.count(name)


class RecordingCLI:
    """A fake CLI whose ``astream_*`` methods record their calls.

    ``fail_on`` makes the named stream raise a ``CommandError`` after yielding;
    ``sleep_on`` makes it sleep (to exceed a ``teardown_timeout``); the
    ``run_*`` config drives ``astream_run`` for exit-code tests.
    """

    def __init__(
        self,
        rec: Recorder,
        *,
        fail_on=None,
        sleep_on=None,
        run_returncode: int = 0,
        run_stdout=("hello world",),
        run_stderr=(),
        up_lines=("up line",),
        pull_lines=("pull line",),
    ) -> None:
        self.rec = rec
        self.fail_on = set(fail_on or ())
        self.sleep_on = dict(sleep_on or {})
        self.run_returncode = run_returncode
        self.run_stdout = tuple(run_stdout)
        self.run_stderr = tuple(run_stderr)
        # Overridable so a test can feed real `docker compose` progress output
        # through the logger hooks.
        self.up_lines = tuple(up_lines)
        self.pull_lines = tuple(pull_lines)
        # Owner labelling appends an override file here (see ``_aensure_owner_labels``).
        self.compose_files: list = ["docker-compose.yaml"]

    async def _maybe(self, name: str) -> None:
        sleep = self.sleep_on.get(name)
        if sleep:
            await asyncio.sleep(sleep)

    def _maybe_fail(self, name: str) -> None:
        if name in self.fail_on:
            raise CommandError(f"{name} failed", command=name, returncode=1, stdout=[], stderr=[f"{name} boom"])

    async def astream_up(self, detach: bool = True, **kw):
        self.rec.add("astream_up", detach=detach)
        await self._maybe("astream_up")
        for line in self.up_lines:
            yield ("STDERR", line)
        self._maybe_fail("astream_up")

    async def astream_down(self, remove_orphans: bool = False, remove_images=None, timeout=None, volumes: bool = False, **kw):
        self.rec.add("astream_down", remove_orphans=remove_orphans, timeout=timeout, volumes=volumes)
        await self._maybe("astream_down")
        yield ("STDOUT", "down line")
        self._maybe_fail("astream_down")

    async def astream_stop(self, services=None, timeout=None, **kw):
        self.rec.add("astream_stop", timeout=timeout)
        await self._maybe("astream_stop")
        yield ("STDOUT", "stop line")
        self._maybe_fail("astream_stop")

    async def astream_pull(self, **kw):
        self.rec.add("astream_pull")
        for line in self.pull_lines:
            yield ("STDERR", line)

    async def astream_restart(self, services=None, **kw):
        self.rec.add("astream_restart")
        yield ("STDOUT", "restart line")

    async def astream_docker_logs(self, **kw):
        self.rec.add("astream_docker_logs")
        yield ("STDOUT", "logs line")

    async def astream_run(self, service: str, command, remove: bool = True, **kw):
        self.rec.add("astream_run", service=service)
        for line in self.run_stdout:
            yield ("STDOUT", line)
        for line in self.run_stderr:
            yield ("STDERR", line)
        if self.run_returncode not in (0, None):
            raise CommandError(
                f"run failed in {service}",
                command=str(command),
                returncode=self.run_returncode,
                stdout=list(self.run_stdout),
                stderr=list(self.run_stderr),
            )

    async def ainspect_config(self) -> ComposeSpec:
        self.rec.add("ainspect_config")
        return ComposeSpec(services={})

    async def aconfig_services(self) -> list[str]:
        self.rec.add("aconfig_services")
        self._maybe_fail("aconfig_services")
        return ["echo", "worker"]

    async def areap_stale(self) -> list[str]:
        self.rec.add("areap_stale")
        return []


class RecordingProject:
    """A fake Project implementing the full protocol, recording every hook."""

    def __init__(self, rec: Recorder, **cli_kwargs) -> None:
        self.rec = rec
        self._cli_kwargs = cli_kwargs

    async def ainititialize(self) -> RecordingCLI:
        self.rec.add("ainititialize")
        return RecordingCLI(self.rec, **self._cli_kwargs)

    async def atear_down(self, cli) -> None:
        self.rec.add("atear_down")

    async def abefore_pull(self) -> None:
        self.rec.add("abefore_pull")

    async def abefore_up(self) -> None:
        self.rec.add("abefore_up")

    async def abefore_enter(self) -> None:
        self.rec.add("abefore_enter")

    async def abefore_down(self) -> None:
        self.rec.add("abefore_down")

    async def abefore_stop(self) -> None:
        self.rec.add("abefore_stop")


def make_deployment(rec: Recorder, *, fail_on=None, sleep_on=None, run_returncode=0, run_stdout=("hello world",), run_stderr=(), **deployment_kwargs) -> Deployment:
    project = RecordingProject(
        rec,
        fail_on=fail_on,
        sleep_on=sleep_on,
        run_returncode=run_returncode,
        run_stdout=run_stdout,
        run_stderr=run_stderr,
    )
    return Deployment(project=project, **deployment_kwargs)


def _appender(target: list, value: str):
    """Return a zero-arg cleanup coroutine factory that appends ``value``."""

    async def _cleanup() -> None:
        target.append(value)

    return _cleanup


# --------------------------------------------------------------------------- #
# Enter is inert
# --------------------------------------------------------------------------- #
async def test_enter_does_nothing():
    rec = Recorder()
    d = make_deployment(rec)
    async with d:
        assert d._cli is None
        assert d._entered is True
        assert d._cleanup_stack == []
        assert rec.events == []
    # and it cleaned its state back up
    assert rec.events == []


# --------------------------------------------------------------------------- #
# Cleanup registration + LIFO
# --------------------------------------------------------------------------- #
async def test_manual_cleanups_run_in_lifo_order():
    rec = Recorder()
    order: list[str] = []
    async with make_deployment(rec) as d:
        d._register_cleanup(_appender(order, "first"))
        d._register_cleanup(_appender(order, "second"))
    assert order == ["second", "first"]


async def test_up_down_on_exit_downs_on_exit():
    rec = Recorder()
    async with make_deployment(rec) as d:
        await d.aup(down_on_exit=True)
        assert "astream_down" not in rec.events  # not yet
    assert rec.count("astream_down") == 1
    assert "astream_stop" not in rec.events


async def test_up_stop_on_exit_stops_not_downs():
    rec = Recorder()
    async with make_deployment(rec) as d:
        await d.aup(stop_on_exit=True)
    assert rec.count("astream_stop") == 1
    assert "astream_down" not in rec.events


# --------------------------------------------------------------------------- #
# Owner labels / stale reaping follow the `down` promise and nothing else
# --------------------------------------------------------------------------- #
async def test_up_with_down_reaps_then_labels_then_downs_with_override_still_listed():
    rec = Recorder()
    async with make_deployment(rec) as d:
        await d.aup(down_on_exit=True)
        cli = d._cli
        assert rec.events.index("areap_stale") < rec.events.index("aconfig_services") < rec.events.index("astream_up")
        override = [f for f in cli.compose_files if str(f).endswith("dokker-owner.override.yaml")]
        assert len(override) == 1
        assert os.path.exists(override[0])
        # The override stamps exactly the resolved services.
        text = open(override[0], encoding="utf-8").read()
        assert '"echo":' in text and '"worker":' in text
        assert f'"dokker.owner.pid": "{os.getpid()}"' in text
        # Register a probe *after* up so, in LIFO order, it runs before the down.
        seen: dict = {}
        async def probe() -> None:
            seen["files_at_down"] = list(cli.compose_files)
        d._register_cleanup(probe)
    # `down` ran while the override was still part of the --file list...
    assert any(str(f).endswith("dokker-owner.override.yaml") for f in seen["files_at_down"])
    assert rec.count("astream_down") == 1
    # ...and the file and its directory are gone afterwards.
    assert not os.path.exists(override[0])
    assert cli.compose_files == ["docker-compose.yaml"]


async def test_up_twice_labels_once():
    rec = Recorder()
    async with make_deployment(rec) as d:
        await d.aup(down_on_exit=True)
        await d.aup(down_on_exit=True)
        assert rec.count("aconfig_services") == 1
        assert sum(1 for f in d._cli.compose_files if "dokker-owner" in str(f)) == 1


async def test_up_with_stop_or_nothing_neither_reaps_nor_labels():
    """A stack dokker will not remove is never a reaping candidate, so it gets no owner label."""
    for kwargs in ({"stop_on_exit": True}, {}, {"down_on_exit": False}):
        rec = Recorder()
        async with make_deployment(rec) as d:
            await d.aup(**kwargs)
            assert "areap_stale" not in rec.events, kwargs
            assert "aconfig_services" not in rec.events, kwargs
            assert d._cli.compose_files == ["docker-compose.yaml"], kwargs


async def test_reap_stale_false_still_labels():
    rec = Recorder()
    async with make_deployment(rec, reap_stale=False) as d:
        await d.aup(down_on_exit=True)
        assert "areap_stale" not in rec.events
        assert rec.count("aconfig_services") == 1


async def test_labelling_failure_only_warns_and_up_proceeds(caplog):
    rec = Recorder()
    with caplog.at_level(logging.WARNING, logger="dokker.deployment"):
        async with make_deployment(rec, fail_on={"aconfig_services"}) as d:
            await d.aup(down_on_exit=True)
            assert d._cli.compose_files == ["docker-compose.yaml"]
    assert rec.count("astream_up") == 1
    assert rec.count("astream_down") == 1
    assert "will not be reaped automatically" in caplog.text


async def test_bare_up_registers_no_teardown():
    rec = Recorder()
    async with make_deployment(rec) as d:
        await d.aup()
    assert "astream_down" not in rec.events
    assert "astream_stop" not in rec.events


async def test_down_runs_before_project_teardown():
    """Containers must come down before the project (temp dir) is removed."""
    rec = Recorder()
    async with make_deployment(rec, policy="testing") as d:
        await d.aup(down_on_exit=True)  # init registers atear_down, then down
    assert "astream_down" in rec.events and "atear_down" in rec.events
    assert rec.events.index("astream_down") < rec.events.index("atear_down")


# --------------------------------------------------------------------------- #
# Mutually exclusive exit hooks
# --------------------------------------------------------------------------- #
async def test_up_both_hooks_raises_and_does_not_up():
    rec = Recorder()
    async with make_deployment(rec) as d:
        with pytest.raises(ValueError):
            await d.aup(down_on_exit=True, stop_on_exit=True)
    assert "astream_up" not in rec.events


def test_sync_up_both_hooks_raises():
    rec = Recorder()
    with make_deployment(rec) as d:
        with pytest.raises(ValueError):
            d.up(down_on_exit=True, stop_on_exit=True)


# --------------------------------------------------------------------------- #
# Dedupe
# --------------------------------------------------------------------------- #
async def test_double_down_on_exit_downs_once():
    rec = Recorder()
    async with make_deployment(rec) as d:
        await d.aup(down_on_exit=True)
        await d.aup(down_on_exit=True)
    assert rec.count("astream_down") == 1


# --------------------------------------------------------------------------- #
# Policy drives the default exit action; per-call args override
# --------------------------------------------------------------------------- #
async def test_policy_testing_bare_up_downs_on_exit():
    rec = Recorder()
    async with make_deployment(rec, policy="testing") as d:
        await d.aup()
    assert rec.count("astream_down") == 1
    assert "astream_stop" not in rec.events


async def test_policy_local_bare_up_stops_on_exit():
    rec = Recorder()
    async with make_deployment(rec, policy="local") as d:
        await d.aup()
    assert rec.count("astream_stop") == 1
    assert "astream_down" not in rec.events


@pytest.mark.parametrize("policy", ["monitoring", "manual"])
async def test_policy_no_teardown_bare_up_registers_nothing(policy):
    rec = Recorder()
    async with make_deployment(rec, policy=policy) as d:
        await d.aup()
    assert "astream_down" not in rec.events
    assert "astream_stop" not in rec.events


async def test_bare_deployment_defaults_to_manual_policy():
    rec = Recorder()
    async with make_deployment(rec) as d:  # no policy given
        await d.aup()
    assert "astream_down" not in rec.events
    assert "astream_stop" not in rec.events


async def test_local_override_stop_beats_testing_policy():
    rec = Recorder()
    async with make_deployment(rec, policy="testing") as d:
        await d.aup(stop_on_exit=True)
    assert rec.count("astream_stop") == 1
    assert "astream_down" not in rec.events


async def test_local_override_disables_teardown_under_testing_policy():
    rec = Recorder()
    async with make_deployment(rec, policy="testing") as d:
        await d.aup(down_on_exit=False)
    assert "astream_down" not in rec.events
    assert "astream_stop" not in rec.events


async def test_local_override_down_beats_local_policy():
    rec = Recorder()
    async with make_deployment(rec, policy="local") as d:
        await d.aup(down_on_exit=True)
    assert rec.count("astream_down") == 1
    assert "astream_stop" not in rec.events


# --------------------------------------------------------------------------- #
# Project teardown auto-registration
# --------------------------------------------------------------------------- #
async def test_init_inside_context_auto_registers_teardown():
    rec = Recorder()
    async with make_deployment(rec, policy="testing") as d:
        await d.ainspect()  # triggers init inside the context
    assert rec.count("atear_down") == 1


async def test_init_inside_context_does_not_teardown_under_manual_policy():
    rec = Recorder()
    async with make_deployment(rec, policy="manual") as d:
        await d.ainspect()  # init happens, but the policy does not tear down
    assert "atear_down" not in rec.events


async def test_init_outside_context_does_not_auto_teardown():
    rec = Recorder()
    d = make_deployment(rec, policy="testing")
    await d.ainitialize()  # no `with` — not entered
    assert "atear_down" not in rec.events
    assert d._cleanup_stack == []


async def test_project_teardown_registered_once_per_context():
    rec = Recorder()
    async with make_deployment(rec, policy="testing") as d:
        await d.ainitialize()
        await d.ainitialize()  # explicit re-init must not double-register
    assert rec.count("atear_down") == 1


# --------------------------------------------------------------------------- #
# before-hooks fire from the methods
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "method, hook",
    [
        ("apull", "abefore_pull"),
        ("aup", "abefore_up"),
        ("astop", "abefore_stop"),
        ("adown", "abefore_down"),
    ],
)
async def test_before_hook_fires_from_method(method, hook):
    rec = Recorder()
    d = make_deployment(rec)
    await getattr(d, method)()
    assert hook in rec.events


# --------------------------------------------------------------------------- #
# down default flags (orphans / volumes) and timeout threading
# --------------------------------------------------------------------------- #
async def test_down_removes_orphans_and_volumes_by_default():
    rec = Recorder()
    await make_deployment(rec).adown()
    assert rec.kwargs["astream_down"]["volumes"] is True
    assert rec.kwargs["astream_down"]["remove_orphans"] is True


async def test_down_flags_can_be_overridden_per_call():
    rec = Recorder()
    await make_deployment(rec).adown(volumes=False, remove_orphans=False)
    assert rec.kwargs["astream_down"]["volumes"] is False
    assert rec.kwargs["astream_down"]["remove_orphans"] is False


async def test_down_flags_respect_deployment_config():
    rec = Recorder()
    await make_deployment(rec, remove_volumes_on_down=False, remove_orphans_on_down=False).adown()
    assert rec.kwargs["astream_down"]["volumes"] is False
    assert rec.kwargs["astream_down"]["remove_orphans"] is False


async def test_shutdown_timeout_threads_into_stop_and_down():
    rec = Recorder()
    d = make_deployment(rec, shutdown_timeout=7)
    await d.adown()
    assert rec.kwargs["astream_down"]["timeout"] == 7
    await d.astop()
    assert rec.kwargs["astream_stop"]["timeout"] == 7


async def test_explicit_timeout_overrides_shutdown_timeout():
    rec = Recorder()
    await make_deployment(rec, shutdown_timeout=7).adown(timeout=2)
    assert rec.kwargs["astream_down"]["timeout"] == 2


# --------------------------------------------------------------------------- #
# Exception handling on exit
# --------------------------------------------------------------------------- #
class _Boom(Exception):
    pass


async def test_body_exception_still_tears_down_and_propagates():
    rec = Recorder()
    with pytest.raises(_Boom):
        async with make_deployment(rec) as d:
            await d.aup(down_on_exit=True)
            raise _Boom()
    assert "astream_down" in rec.events


async def test_teardown_error_raises_on_clean_exit():
    rec = Recorder()
    with pytest.raises(CommandError):
        async with make_deployment(rec, fail_on={"astream_down"}) as d:
            await d.aup(down_on_exit=True)


async def test_teardown_error_suppressed_while_body_raises(caplog):
    rec = Recorder()
    with caplog.at_level(logging.WARNING):
        with pytest.raises(_Boom):
            async with make_deployment(rec, fail_on={"astream_down"}) as d:
                await d.aup(down_on_exit=True)
                raise _Boom()
    assert any("teardown failed" in r.getMessage().lower() for r in caplog.records)


async def test_teardown_timeout_raises_on_clean_exit():
    rec = Recorder()
    with pytest.raises(TearDownError):
        async with make_deployment(rec, sleep_on={"astream_down": 0.5}, teardown_timeout=0.05) as d:
            await d.aup(down_on_exit=True)


async def test_teardown_timeout_suppressed_while_body_raises(caplog):
    rec = Recorder()
    with caplog.at_level(logging.WARNING):
        with pytest.raises(_Boom):
            async with make_deployment(rec, sleep_on={"astream_down": 0.5}, teardown_timeout=0.05) as d:
                await d.aup(down_on_exit=True)
                raise _Boom()
    assert any("timed out" in r.getMessage().lower() for r in caplog.records)


# --------------------------------------------------------------------------- #
# State reset / re-entrancy
# --------------------------------------------------------------------------- #
async def test_state_reset_and_reentrancy():
    rec = Recorder()
    d = make_deployment(rec)
    async with d:
        await d.aup(down_on_exit=True)
    assert d._cli is None
    assert d._cleanup_stack == []
    assert d._registered_keys == set()
    assert d._entered is False

    rec.events.clear()
    async with d:
        await d.aup(stop_on_exit=True)
    # the first run's down must not re-run; only this run's stop
    assert "astream_down" not in rec.events
    assert rec.count("astream_stop") == 1


# --------------------------------------------------------------------------- #
# auto_initialize=False
# --------------------------------------------------------------------------- #
async def test_auto_initialize_false_raises_without_init():
    rec = Recorder()
    async with make_deployment(rec, auto_initialize=False) as d:
        with pytest.raises(NotInitializedError):
            await d.aup()


# --------------------------------------------------------------------------- #
# run() exit-code handling (deterministic, no docker)
# --------------------------------------------------------------------------- #
async def test_run_success_returns_stdout_and_zero():
    rec = Recorder()
    logs = await make_deployment(rec, run_returncode=0, run_stdout=("hello world",)).arun("worker", "echo hi")
    assert logs.returncode == 0
    assert "hello world" in logs.stdout


async def test_run_nonzero_raises_with_code_and_stderr():
    rec = Recorder()
    with pytest.raises(CommandError) as excinfo:
        await make_deployment(rec, run_returncode=7, run_stderr=("boom",)).arun("worker", "false")
    assert excinfo.value.returncode == 7
    assert any("boom" in line for line in excinfo.value.stderr)


async def test_run_suppress_raise_reports_code():
    rec = Recorder()
    logs = await make_deployment(rec, run_returncode=7).arun("worker", "false", raise_on_error=False)
    assert logs.returncode == 7


async def test_run_expected_nonzero_does_not_raise():
    rec = Recorder()
    logs = await make_deployment(rec, run_returncode=1).arun("worker", "false", expected_exit_code=1)
    assert logs.returncode == 1


async def test_run_wrong_exit_code_raises_with_expectation_note():
    rec = Recorder()
    with pytest.raises(CommandError) as excinfo:
        await make_deployment(rec, run_returncode=1).arun("worker", "false", expected_exit_code=2)
    assert "Expected exit code 2" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Sync surface
# --------------------------------------------------------------------------- #
def test_sync_context_registers_and_tears_down():
    rec = Recorder()
    with make_deployment(rec) as d:
        d.up(down_on_exit=True)
    assert rec.count("astream_down") == 1


# --------------------------------------------------------------------------- #
# Progress logger
# --------------------------------------------------------------------------- #
UP_PROGRESS = [
    "Network dokkerfake_default Creating",
    "Network dokkerfake_default Created",
    "Container dokkerfake-echo-1 Creating",
    "Container dokkerfake-echo-1 Created",
    "Container dokkerfake-echo-1 Starting",
    "Container dokkerfake-echo-1 Started",
]


def _progress_deployment(rec: Recorder, writer, **kw):
    """A Deployment whose logger is a ProgressLogger drawing into ``writer``.

    Passing the logger to the constructor (rather than assigning it) is
    deliberate: pydantic validates it by isinstance against the
    ``runtime_checkable`` ``Logger`` protocol, so this also pins that
    ``ProgressLogger`` implements every hook.
    """
    project = RecordingProject(rec, up_lines=UP_PROGRESS, pull_lines=["Image alpine:3.19 Pulled"])
    logger = ProgressLogger(writer=writer, label="dokkerfake", ascii_only=True, width=200, **kw)
    return Deployment(project=project, logger=logger), logger


def test_progress_logger_satisfies_the_logger_protocol():
    """A partial implementation would be rejected here."""
    rec = Recorder()
    deployment, logger = _progress_deployment(rec, io.StringIO())
    assert deployment.logger is logger


async def test_progress_logger_tracks_a_full_lifecycle():
    rec = Recorder()
    deployment, logger = _progress_deployment(rec, io.StringIO())

    async with deployment:
        logger.phase("pull")
        await deployment.apull()
        assert "[1/1]" in logger.render()
        assert "alpine:3.19 Pulled" in logger.render()

        logger.phase("up")
        await deployment.aup(down_on_exit=False)

    rendered = logger.render()
    assert "[1/1]" in rendered
    assert "echo Started" in rendered


async def test_progress_logger_draws_in_place_during_up():
    """The whole point: one line, redrawn, never scrolled."""
    rec = Recorder()
    buffer = io.StringIO()
    deployment, logger = _progress_deployment(rec, buffer)

    async with deployment:
        logger.phase("up")
        logger.start()
        try:
            await deployment.aup(down_on_exit=False)
        finally:
            logger.stop()

    written = buffer.getvalue()
    assert "\n" not in written
    assert written.endswith("\r\x1b[K")


async def test_unparseable_stream_lines_are_survivable():
    """The default fake yields prose, not compose progress. It must not crash."""
    rec = Recorder()
    buffer = io.StringIO()
    project = RecordingProject(rec)  # yields "up line" / "pull line"
    logger = ProgressLogger(writer=buffer, label="x", ascii_only=True, width=200)
    deployment = Deployment(project=project, logger=logger)

    async with deployment:
        logger.phase("up")
        await deployment.aup(down_on_exit=False)

    # Nothing recognised, so nothing counted -- and no exception.
    assert "[" not in logger.render()


async def test_progress_line_is_erased_when_up_fails():
    """The failure path is what this feature exists for.

    A raised `CommandError` must still leave the terminal at column 0 with the
    line cleared, so pytest's error report is not painted over a half-written
    status line.
    """
    rec = Recorder()
    buffer = io.StringIO()
    project = RecordingProject(rec, up_lines=UP_PROGRESS, fail_on={"astream_up"})
    logger = ProgressLogger(writer=buffer, label="dokkerfake", ascii_only=True, width=200)
    deployment = Deployment(project=project, logger=logger)

    async with deployment:
        logger.phase("up")
        logger.start()
        try:
            with pytest.raises(CommandError):
                await deployment.aup(down_on_exit=False)
        finally:
            logger.stop()

    written = buffer.getvalue()
    assert written.endswith("\r\x1b[K")
    assert "\n" not in written


async def test_stop_is_idempotent_after_a_failure():
    """A second stop (e.g. from a nested finally) must not re-erase or hang."""
    rec = Recorder()
    buffer = io.StringIO()
    project = RecordingProject(rec, up_lines=UP_PROGRESS, fail_on={"astream_up"})
    logger = ProgressLogger(writer=buffer, label="dokkerfake", ascii_only=True, width=200)
    deployment = Deployment(project=project, logger=logger)

    async with deployment:
        logger.phase("up")
        logger.start()
        with pytest.raises(CommandError):
            await deployment.aup(down_on_exit=False)
        logger.stop()
        logger.stop()

    assert buffer.getvalue().count("\r\x1b[K") == 1
