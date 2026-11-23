# CHANGELOG


## v2.10.1 (2026-11-23)

### Bug Fixes

- Every argument and return annotated, no Any; bugbear and async findings fixed
  ([`1b918d6`](https://github.com/jhnnsrs/dokker/commit/1b918d6be98ee72517054dfb56791460040adfcc))

The rest of the arkitekt standard by hand. The package needed little: Self becomes a TypeVar bound
  to Deployment / LogWatcher, _supports_ansi takes object (it is written to survive anything, and
  says so where it calls isatty), zip() over the owner labels is strict (the length is checked just
  above) and over image tags is explicitly not. The mutable defaults of
  CLI.astream_docker_logs(services=) and astream_up(scales=) are public and only read, so they stay
  with a noqa. Projects do their one-off local filesystem work inline in their async setup/teardown:
  ruff.toml ignores ASYNC240 for dokker/projects.

Tests: the fake CLIs and projects carry the signatures of what they stand in for, fixtures and
  parametrized arguments are typed, and the few asserts on files the code under test wrote keep a
  noqa. No behaviour change, no public API change: the suite passes (250 passed, docker integration
  tests included).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>

### Build System

- **deps**: Lock koil 3.4.1
  ([`af477ca`](https://github.com/jhnnsrs/dokker/commit/af477caa90952f9da6e974f7862805bcdcdd6473))

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>

### Code Style

- Adopt the arkitekt Python standard (ruff format, safe fixes)
  ([`7e40538`](https://github.com/jhnnsrs/dokker/commit/7e405384e8e6e1b75b43bf7dab8d40da81aed470))

ruff.shared.toml / pyright.shared.json synced from arkitektio/.github; the repo's own settings move
  to ruff.toml / pyrightconfig.json (the old [tool.ruff] section is gone, and with it the exclusion
  of tests/); the dev dependencies move from [tool.uv] to the dev group, where ruff and basedpyright
  are pinned; a new quality.yaml calls the shared python-quality workflow, which replaces the ruff
  and mypy steps of tests.yaml (mypy leaves the dev group). The code is reformatted (line length 88,
  as Black) and ruff's safe fixes applied (import order, modern annotations). No behaviour change:
  the suite passes as before (250 passed, docker integration tests included).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>

### Continuous Integration

- Publish only when a release was cut, lint clean, pydantic with Python 3.14 wheels
  ([`4549ee2`](https://github.com/jhnnsrs/dokker/commit/4549ee2edc8554be79e4b03b13f8132ff9d7ae94))

- release.yaml: uv publish ran on every push and failed whenever the commit cut no release; both
  publish steps are now guarded on dist/ having files - drop an unused import ruff rejected - lock
  pydantic 2.14 / pydantic-core 2.50: the locked pydantic-core 2.27 has no wheel for Python 3.14 and
  cannot be built there

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>

- The shared quality workflow, required, with a type-check baseline
  ([`310b7bb`](https://github.com/jhnnsrs/dokker/commit/310b7bb014dbeb3c3f20213e5d17ab084e38b6bc))

.basedpyright/baseline.json holds the 46 errors the repo had when it adopted the standard (all in
  tests; 45 before it, plus a test fake bearer whose declared FakeCLI is not the CLI the protocol
  names): CI fails on any other. .git-blame-ignore-revs lists the formatting-only commit; the
  README's development section describes the standard instead of ruff + mypy.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>

### Refactoring

- Adopt Python 3.11 typing (X | None, builtin generics, collections.abc)
  ([`f8e037f`](https://github.com/jhnnsrs/dokker/commit/f8e037f0736906f81ab7b17cfc57f5ee717ced89))

Rewrite Optional[X]/Union[A, B] to X | None / A | B, List/Dict/Tuple/Type/Set to builtins,
  typing.Callable & co. to collections.abc, and other pyupgrade rewrites for the >=3.11 floor.
  Enforce it with ruff's UP rules (UP037, UP038 and UP042 ignored; generated api/schema.py keeps
  typing imports).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>


## v2.10.0 (2026-10-07)

### Features

- A project may start, stop, down and pull its own stack
  ([`659e1b4`](https://github.com/jhnnsrs/dokker/commit/659e1b452bf64a495e7ffedaba6fea641f56b2ca))

A deployment's up/down/stop/pull were docker compose's alone. A stack that a generator has to
  prepare before its containers exist cannot be started that way, so a project can now keep those
  verbs: StartsItself, StopsItself, DownsItself and PullsItself are asked instead of compose, one
  verb at a time, with the options as UpOptions/DownOptions/PullOptions. Hooks, loggers and the
  teardown registered for exit stay the deployment's. Owner labels ride on a compose override such a
  project's up never reads, so they are left out for it.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>


## v2.9.0 (2026-10-02)

### Bug Fixes

- Images are reaped where compose does not label what it builds
  ([`214a2bc`](https://github.com/jhnnsrs/dokker/commit/214a2bcb5310f4d03bb3387fbad5feb9750b6d6d))

Compose 2.38 (what GitHub's runners carry) puts no project label on the images it builds, and both
  reapers found a project's images by that label alone: a stranded stack's image stayed behind, and
  the sweep of earlier testing stacks' images removed nothing.

- A stranded stack's images are also what its containers run and name after the project, so they are
  asked before the project is downed. - The sweep goes by the tag: a `dokker-test-<hex>-` name is
  `testing()`'s own. A label that names another project still keeps the image.

The tag time is read before the label, which can be empty: the line was stripped and the time then
  read as the label.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>

### Features

- A testing stack's down removes the images built for it
  ([`fa400f1`](https://github.com/jhnnsrs/dokker/commit/fa400f136edaaf4ba9d4e96239251cdc814d4904))

`testing()` gives every run a random project name, and compose tags what it builds after the project
  (`dokker-test-<id>-<service>`). No later run asks for that tag again, so each run left a pair
  behind, each holding on to the layers of the sources it was built from.

`down` now passes `--rmi local` for testing stacks (`remove_images`, `"local"` by default;
  `Deployment.remove_images_on_down`): the images compose built and named after the project go with
  it. Images a service names itself, pulled images and the build cache stay, so nothing is pulled
  again and the next run builds from cache. `local()` keeps its images.

`reap_stale()` removes the images of the stacks it reaps, and sweeps the `dokker-test-*` images no
  stack uses any more (`reap_orphan_images()`): those of runs from before this change, and of runs
  that died between building and creating their containers. An image tagged within the last hour is
  left alone, since a run that is still building has an image and no container yet.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>

### Testing

- An image test that fails says what docker knows about the image
  ([`65a599c`](https://github.com/jhnnsrs/dokker/commit/65a599cf6403e449061d940567aadecabfa5d9e3))

The two reaping tests pass locally and fail on the runner, with nothing to tell why: the assertion
  only shows the tag. They now name the engine, compose, the image store, and the image's labels and
  tag time.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>


## v2.8.0 (2026-09-05)

### Bug Fixes

- Give local() a stable project name so sibling compose files do not merge
  ([`c4ff9b4`](https://github.com/jhnnsrs/dokker/commit/c4ff9b44fd1bcadfe57c1b71d3a0b74b7665a6ea))

`local()` left `--project-name` unset, so compose fell back to the compose file's directory basename
  and two sibling files in one directory became a single project: the second `up()` recreated the
  first's services and both deployments pointed at one container (the `battle` test committed red on
  2026-09-01, which has blocked every release since).

`derive_project_name()` keeps compose's own convention for the standard file names (`compose.yaml`,
  `docker-compose.yaml`, ...), so a hand-typed `docker compose up` and dokker still agree and
  existing stacks keep their names; any other file gets `<directory>-<stem>`. Deterministic, so a
  `local()` stack finds its own stopped containers again next session. `monitoring()` is unchanged:
  it observes stacks it did not start.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01UyygY5tfNueycZRm9y7ZWP

### Chores

- With some more parllel integration tests
  ([`1169bf0`](https://github.com/jhnnsrs/dokker/commit/1169bf02eddee90592aec945ffca0f7ecbd2becd))

### Features

- Label testing stacks with their owner and reap the ones whose owner died
  ([`c23c959`](https://github.com/jhnnsrs/dokker/commit/c23c959a7f596958c34511c6df325072a6dbecf1))

A `testing()` deployment promises to `down` its stack on exit, but a SIGKILLed or interrupted run
  never reaches that teardown and leaves an anonymous `dokker-test-<hex>` stack behind. People then
  clean those with a name sweep (`docker ps | grep dokker-test | xargs docker rm -f`), which cannot
  tell a stray from the stack a live run in another terminal is using -- and removing that one turns
  a green suite into hundreds of "database vanished" errors.

Every `up()` that registers a `down` now stamps `dokker.owner.pid/.host/.start` labels onto its
  services (via a temp compose override) and first runs `reap_stale()`, which downs only the
  labelled stacks whose owner PID is dead on this host (recycled PIDs are told apart by the process
  start marker). Kept stacks (`down_on_exit=False`, `--dokker-keep`), `local()` stacks, other hosts'
  stacks and anything not started by dokker carry no label and are never touched; any doubt counts
  as alive.

- `dokker.reap_stale()` / `areap_stale()` exported for cleaning a machine by hand - `testing(...,
  reap_stale=)` and `Deployment.reap_stale` to opt out - `CLI.areap_stale()`,
  `CLI.aconfig_services()`, `astream_command(cwd=)` - also fixes an `await` inside a generator
  expression that broke `test_five_stacks_come_up_concurrently_on_distinct_ports`

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01UyygY5tfNueycZRm9y7ZWP


## v2.7.0 (2026-08-13)

### Features

- With some pytest11 plugin
  ([`304f589`](https://github.com/jhnnsrs/dokker/commit/304f5893110311aa102dfd157d035bb43ae6167d))


## v2.6.0 (2026-06-29)

### Chores

- Update readme and pyproject
  ([`755c498`](https://github.com/jhnnsrs/dokker/commit/755c498b451253d037a492a71c403392cae9e9be))

### Features

- Policy based
  ([`e12dfcb`](https://github.com/jhnnsrs/dokker/commit/e12dfcb65e642a81d2665464b77e1a9039f136d9))


## v2.5.0 (2026-06-11)

### Features

- Fix isolating
  ([`89b9803`](https://github.com/jhnnsrs/dokker/commit/89b980320aa4f8fc48a19504fce845bf24530534))


## v2.4.0 (2026-06-09)

### Bug Fixes

- Add coverage
  ([`18efa2a`](https://github.com/jhnnsrs/dokker/commit/18efa2a70a493b5f41377b592f545a8e9402d756))

### Features

- Fix major async sync bugs fixed with koil
  ([`07fbff6`](https://github.com/jhnnsrs/dokker/commit/07fbff6913d7da8d8527d33b0914e17f142bcede))


## v2.3.0 (2025-07-24)

### Features

- Change again some settings
  ([`4d19fa1`](https://github.com/jhnnsrs/dokker/commit/4d19fa1ea2419acd46e609b27897e12e65f1e497))

- Provide more verbose settings
  ([`3239888`](https://github.com/jhnnsrs/dokker/commit/32398889103650fb92193d532e541a4e3e4d04fe))


## v2.2.0 (2025-07-20)

### Features

- Add run comman
  ([`69527c9`](https://github.com/jhnnsrs/dokker/commit/69527c96653b2842d812ae748cb1dd35fdd70280))


## v2.1.2 (2025-05-12)

### Bug Fixes

- Loosen certify restriction
  ([`1cb1aa1`](https://github.com/jhnnsrs/dokker/commit/1cb1aa1f17c0cba82a5d3eb24e13b6b05cdc02ee))


## v2.1.1 (2025-05-11)


## v2.1.0 (2025-05-11)

### Bug Fixes

- More type support
  ([`e045cc1`](https://github.com/jhnnsrs/dokker/commit/e045cc101931ae95412e26c16b577ed55509c0ec))


## v2.0.0 (2025-05-09)

### Features

- Add types everywhere
  ([`75fc6ba`](https://github.com/jhnnsrs/dokker/commit/75fc6ba6889e045b752815c8eb9691993219fef4))


## v1.0.0 (2025-05-09)

### Features

- Update README to clarify project status and contribution guidelines
  ([`5f81747`](https://github.com/jhnnsrs/dokker/commit/5f81747ddb0e9831672b24b231337579070e45b9))


## v0.2.0 (2025-05-09)

### Features

- Major update
  ([`cef22b3`](https://github.com/jhnnsrs/dokker/commit/cef22b3226b2e104e30bbdec89d4dfac2b6eb7f6))


## v0.1.0 (2025-05-09)

### Features

- Massiv update
  ([`1ff5b49`](https://github.com/jhnnsrs/dokker/commit/1ff5b49a42cb8a8a3622ab820a314dbef3883e8e))

- Remove headless display setup from workflows
  ([`fb8df36`](https://github.com/jhnnsrs/dokker/commit/fb8df36fe687c7b56f572992be846432c00b30a1))
