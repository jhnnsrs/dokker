# Plan: Extensive edge-case tests for the new dokker lifecycle API (+ dedupe exit-hooks)

## Context

We just redesigned dokker's lifecycle: `__aenter__` does nothing, commands register their own
teardown on a LIFO cleanup stack (`up(down_on_exit=True)` / `stop_on_exit=True`), project
initialization auto-registers its `atear_down`, the `abefore_*` project hooks moved into
`apull`/`aup`/`astop`/`adown`, and `down` now removes orphans+volumes by default. The current
test suite is integration-heavy and exercises almost none of this new branching logic directly.

**Goal:** add a large, fast **unit** suite (fake `Project`/`CLI`, no docker) that pins every
lifecycle edge case, plus a **focused integration** set for the things only real docker proves
(volume removal, exception-still-tears-down, `mirror` full lifecycle). One behavioral fix falls
out of the edge-case hunt: a repeated `up(down_on_exit=True)` currently registers the teardown
twice — we'll **dedupe** so each exit-hook runs at most once.

Both seams are clean: `Project` and `Logger` are `@runtime_checkable` Protocols
(`dokker/project.py:5`, `dokker/deployment.py:92`), so a plain fake class validates as
`Deployment(project=Fake())`; a fake `Project.ainititialize()` returns a fake `CLI` that lands
in the unvalidated `_cli` private attr. `pyproject.toml` sets `asyncio_mode = "auto"` so async
tests need no marker, and `with deployment:` works synchronously via koil.

## 1. Code change — dedupe exit-hook registration (`dokker/deployment.py`)

`_register_cleanup` (added earlier, ~line 178) gains an optional `key`; a `_registered_keys`
private attr (a `set`, alongside `_cleanup_stack`/`_entered`, `PrivateAttr(default_factory=set)`)
tracks keys already registered and skips duplicates:

```python
def _register_cleanup(self, coro_factory, key=None):
    if key is not None:
        if key in self._registered_keys:
            return
        self._registered_keys.add(key)
    self._cleanup_stack.append(coro_factory)
```

- `aup`: register `self.adown` with `key="down"`, `self.astop` with `key="stop"`.
- `ainitialize`: register the project teardown with `key="project_teardown"`.
- `__aenter__`: also reset `self._registered_keys = set()`; the `finally` in `__aexit__` clears it
  alongside `_cleanup_stack`/`_entered`.

This keeps LIFO order (first registration's position is retained) and makes a repeated
`up(down_on_exit=True)` tear down exactly once. (Manual `aremove()` runs immediately and is not
part of the stack, so it is unaffected — `CopyPathProject.atear_down` already guards on
`os.path.exists`, so a manual + auto teardown stays safely idempotent.)

## 2. Unit suite — `tests/test_lifecycle.py` (NEW, no docker)

Module-local fakes (mirroring the existing `_DummyBearer`/`_spec` local-helper style in
`tests/test_log_roll.py`/`tests/test_compose_spec.py`):

- `Recorder` — shared ordered event log (`events: list`).
- `RecordingCLI` — implements every `astream_*` invoked by `Deployment` (`astream_up/down/stop/
  pull/run/restart/docker_logs`) as async generators that record their name + kwargs into the
  Recorder (and `ainspect_config` returning `ComposeSpec(services={})`). Configurable hooks:
  `fail_on={"down"}` to raise a `CommandError(returncode=...)`, `sleep_on={"down": secs}` to
  exceed a `teardown_timeout`, and recorded `down` kwargs so volume/orphan/timeout assertions are
  possible. A factory returning a fresh `RecordingCLI` makes each `Deployment(project=...)` work.
- `RecordingProject` — implements the full `Project` protocol (all 7 methods incl. `abefore_enter`
  so `isinstance` passes), records each `abefore_*` and `atear_down` into the Recorder, and returns
  the `RecordingCLI`.

Cases (grouped):

- **Enter is inert:** entering records no project/CLI call; `_cli is None`, `_entered is True`,
  `_cleanup_stack == []` inside the block.
- **Registration + LIFO:** two manual `_register_cleanup`s run in reverse order on exit;
  `aup(down_on_exit=True)` tears down via `down` on exit; `aup(stop_on_exit=True)` via `stop`;
  bare `aup()` registers nothing. **Order edge:** inside a context, `aup(down_on_exit=True)`
  triggers lazy init (registers `project_teardown` first) then registers `down` — on exit `down`
  runs **before** `project_teardown` (containers down before temp dir removed).
- **Mutually-exclusive:** `aup(down_on_exit=True, stop_on_exit=True)` raises `ValueError` and does
  **not** up (no `astream_up` recorded); same for sync `up(...)`.
- **Dedupe:** `aup(down_on_exit=True)` twice → `down` recorded once on exit; `up()` sync path too.
- **Project teardown auto-register:** init inside context (via `aup`/`ainspect`/`aretrieve_cli`)
  → `atear_down` runs once on exit; init **outside** any context (`await d.ainitialize()` with no
  `with`) → `atear_down` never auto-runs and the stack stays empty.
- **before-hooks fire from methods:** `apull`→`abefore_pull`, `aup`→`abefore_up`,
  `astop`→`abefore_stop`, `adown`→`abefore_down`.
- **down default flags:** default `adown()` passes `volumes=True, remove_orphans=True` to the CLI;
  `adown(volumes=False, remove_orphans=False)` overrides; `Deployment(remove_volumes_on_down=False)`
  flows through.
- **timeout threading:** `Deployment(shutdown_timeout=7)` → `astream_down`/`astream_stop` receive
  `timeout=7`; explicit `adown(timeout=2)` overrides.
- **Exception handling:** body raises with `up(down_on_exit=True)` → teardown still runs and the
  body exception propagates; teardown `CommandError` on clean exit → raised; teardown `CommandError`
  while the body is already raising → body exception propagates and a warning is logged (assert via
  `caplog`); `teardown_timeout` exceeded (slow `astream_down`) → `TearDownError` on clean exit,
  warning-only when the body already raised.
- **State reset / re-entrancy:** after exit `_cli is None`, `_cleanup_stack == []`,
  `_registered_keys == set()`, `_entered is False`; re-entering the same deployment runs fresh and
  does not re-run the first run's cleanups.
- **auto_initialize=False:** entering then calling `aup()` without `ainitialize` →
  `NotInitializedError`.
- **`run()` exit-codes (deterministic via fake):** success → `returncode 0`; non-zero →
  `CommandError` carrying `returncode`/`stderr`; `raise_on_error=False` → no raise; matching
  `expected_exit_code` → no raise; mismatched → raises with the "Expected exit code" note.
- **Sync surface:** a plain `with Deployment(project=RecordingProject()) as d: d.up(down_on_exit=True)`
  tears down on exit (covers the `unkoil` + sync-context path).

If pydantic rejects a fake for the `project` field, fall back to `model_construct` or assign
`d.project = fake` after construction — but the `@runtime_checkable` Protocol should validate a
fully-implemented fake directly.

## 3. Integration suite — `tests/test_teardown_integration.py` (NEW, `pytest.mark.integration`)

New fixtures:
- `tests/configs/volume-compose.yaml` — one `alpine` `sleep infinity` service mounting a **named
  volume** (`data:/data`) plus a top-level `volumes: { data: }`.
- `tests/configs/mirror-src/docker-compose.yml` — note the **`.yml`** name `CopyPathProject`
  requires (`dokker/projects/copy.py:43`); a single lightweight `alpine` service.

Tests (each uses a unique `project_name`, e.g. via `testing(...)`'s random name or an explicit
`f"...-{uuid4().hex[:8]}"`, and a small `subprocess.run(["docker", ...])` helper like the
`ps`-based one already in `tests/test_basic_integration.py:130`):

- **Volume removed by default:** `up(down_on_exit=True)` then exit → `docker volume ls` shows no
  `<project>_data`. Companion: `testing(..., remove_volumes=False)` (set
  `remove_volumes_on_down=False`) leaves the volume, then explicit `down(volumes=True)` removes it
  (so the test cleans up after itself).
- **Exception still tears down:** raise inside the `with testing(...) as d:` body after
  `up(down_on_exit=True)` → `pytest.raises`, and `docker ps -a` shows no containers for that
  project.
- **`mirror` full lifecycle:** `with mirror("tests/configs/mirror-src", project_name=unique):`
  `up(down_on_exit=True)`; on exit assert the `.dokker/<name>` copy is gone **and** no containers
  remain for the project (extends the temp-dir smoke check into a real test).

## Verification

1. `uv run pytest -m "not integration" -q` — the new `tests/test_lifecycle.py` plus existing unit
   tests pass with no docker daemon.
2. `uv run pytest -m integration -q` — teardown/volume/mirror integration tests pass on a docker host.
3. `uv run pytest -q` — full suite green.
4. Leak check after the integration run: `docker ps -a` and `docker volume ls` show nothing for the
   test projects, and `.dokker/` holds no leftover mirror copy.
