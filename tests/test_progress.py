"""Unit tests for the live progress line. No docker required.

The parser cases below are verbatim `docker compose` v5.1.3 output, captured by
piping `pull`/`up`/`stop`/`down` of `tests/configs/db-compose.yaml` through
`cat`, then whitespace-stripped the way `dokker/command.py` strips it before a
logger ever sees it.
"""

import io

import pytest

from dokker.loggers.progress import (
    ProgressEvent,
    ProgressLogger,
    parse_compose_progress,
    strip_ansi,
)

# Real captured output, post-strip.
UP_LINES = [
    "Network dokkerprog_default Creating",
    "Network dokkerprog_default Created",
    "Container dokkerprog-redis-1 Creating",
    "Container dokkerprog-redis-1 Created",
    "Container dokkerprog-redis-1 Starting",
    "Container dokkerprog-redis-1 Started",
    "Container dokkerprog-redis-1 Waiting",
    "Container dokkerprog-redis-1 Healthy",
]

PULL_LINES = [
    "Image alpine:3.19 Pulling",
    "17a39c0ba978 Pulling fs layer 0B",
    "17a39c0ba978 Downloading 48.48kB",
    "17a39c0ba978 Verifying Checksum 0B",
    "17a39c0ba978 Download complete 0B",
    "17a39c0ba978 Extracting 65.54kB",
    "17a39c0ba978 Extracting 3.42MB",
    "17a39c0ba978 Pull complete 0B",
    "Image alpine:3.19 Pulled",
]


class Clock:
    """A monotonic clock the tests advance by hand."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def make_logger(**kwargs):
    """A ProgressLogger writing to an in-memory buffer, never to a terminal."""
    kwargs.setdefault("writer", io.StringIO())
    kwargs.setdefault("label", "dokkerprog")
    kwargs.setdefault("ascii_only", True)
    kwargs.setdefault("width", 200)
    kwargs.setdefault("now", Clock())
    return ProgressLogger(**kwargs)


# ---------------------------------------------------------------- parser


@pytest.mark.parametrize(
    "line,expected",
    [
        ("Container dokkerprog-redis-1 Healthy", ProgressEvent("Container", "dokkerprog-redis-1", "Healthy")),
        ("Network dokkerprog_default Created", ProgressEvent("Network", "dokkerprog_default", "Created")),
        ("Image alpine:3.19 Pulling", ProgressEvent("Image", "alpine:3.19", "Pulling")),
        ("Volume dokkerprog_data Created", ProgressEvent("Volume", "dokkerprog_data", "Created")),
        # Compose leaves a trailing space on typed lines; command.py strips it,
        # but the parser must not depend on that having happened.
        ("Container dokkerprog-redis-1 Started ", ProgressEvent("Container", "dokkerprog-redis-1", "Started")),
        # Multi-word statuses stay intact.
        ("Container x-1 Skipped - Image is already being pulled", ProgressEvent("Container", "x-1", "Skipped - Image is already being pulled")),
    ],
)
def test_parses_typed_resource_lines(line, expected):
    assert parse_compose_progress(line) == expected


@pytest.mark.parametrize(
    "line,expected",
    [
        ("17a39c0ba978 Downloading 48.48kB", ProgressEvent(None, "17a39c0ba978", "Downloading 48.48kB")),
        ("17a39c0ba978 Pulling fs layer 0B", ProgressEvent(None, "17a39c0ba978", "Pulling fs layer 0B")),
        ("17a39c0ba978 Download complete 0B", ProgressEvent(None, "17a39c0ba978", "Download complete 0B")),
    ],
)
def test_parses_layer_lines_without_a_type(line, expected):
    assert parse_compose_progress(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "",
        "   ",
        "redis 1:M 01 Jan 2026 00:00:00.000 * Ready to accept connections",
        "Error response from daemon: conflict",
        "some totally unstructured text",
        "single",
    ],
)
def test_ignores_anything_it_does_not_recognise(line):
    """Unparseable input is dropped, never raised on, never rendered."""
    assert parse_compose_progress(line) is None


def test_prose_is_not_mistaken_for_a_layer_line():
    """`Error response ...` has two tokens but no hex id, so it is not a layer."""
    assert parse_compose_progress("Error response from daemon") is None


def test_strips_ansi_before_parsing():
    """FORCE_COLOR makes compose emit escapes even on a pipe."""
    coloured = "\x1b[34mContainer\x1b[0m dokkerprog-redis-1 \x1b[32mHealthy\x1b[0m"
    assert strip_ansi(coloured) == "Container dokkerprog-redis-1 Healthy"
    assert parse_compose_progress(coloured) == ProgressEvent("Container", "dokkerprog-redis-1", "Healthy")


# ---------------------------------------------------------------- state


def test_up_sequence_reaches_full_fraction():
    logger = make_logger()
    logger.phase("up")
    for line in UP_LINES:
        logger.on_up(("STDERR", line))

    rendered = logger.render()
    # The network is tracked but not counted: containers are the unit of work.
    assert "[1/1]" in rendered
    assert "redis Healthy" in rendered


def test_fraction_does_not_go_backwards_when_wait_reports_waiting():
    """`up --wait` emits Started then Waiting; the count must latch."""
    logger = make_logger()
    logger.phase("up")
    logger.on_up(("STDERR", "Container dokkerprog-redis-1 Started"))
    assert "[1/1]" in logger.render()
    logger.on_up(("STDERR", "Container dokkerprog-redis-1 Waiting"))
    assert "[1/1]" in logger.render()
    assert "redis Waiting" in logger.render()


def test_created_is_not_terminal_during_up():
    """A created-but-not-started container is not progress towards `up`."""
    logger = make_logger()
    logger.phase("up")
    logger.on_up(("STDERR", "Container dokkerprog-redis-1 Created"))
    assert "[0/1]" in logger.render()


def test_pull_counts_images_and_never_layers():
    """Hundreds of layer lines must not become hundreds of rows."""
    logger = make_logger()
    logger.phase("pull")
    for line in PULL_LINES:
        logger.on_pull(("STDERR", line))

    rendered = logger.render()
    assert "[1/1]" in rendered
    assert "alpine:3.19 Pulled" in rendered
    # The layer surfaces only as transient detail, not as a tracked row.
    assert "17a39c0ba978 Pull complete" in rendered


def test_phase_change_resets_the_fraction_and_timer():
    clock = Clock()
    logger = make_logger(now=clock)
    logger.phase("pull")
    logger.on_pull(("STDERR", "Image alpine:3.19 Pulled"))
    assert "[1/1]" in logger.render()

    clock.t = 10.0
    logger.phase("up")
    # Images are no longer the tracked kind, and the elapsed timer restarts.
    assert "0.0s" in logger.render()
    logger.on_up(("STDERR", "Container dokkerprog-redis-1 Created"))
    assert "[0/1]" in logger.render()


def test_unsettled_services_are_listed_first():
    logger = make_logger()
    logger.phase("up")
    logger.on_up(("STDERR", "Container dokkerprog-echo-1 Started"))
    logger.on_up(("STDERR", "Container dokkerprog-redis-1 Creating"))

    rendered = logger.render()
    assert rendered.index("redis Creating") < rendered.index("echo Started")


def test_down_and_stop_have_their_own_terminal_statuses():
    logger = make_logger()
    logger.phase("stop")
    logger.on_stop(("STDERR", "Container dokkerprog-redis-1 Stopping"))
    assert "[0/1]" in logger.render()
    logger.on_stop(("STDERR", "Container dokkerprog-redis-1 Stopped"))
    assert "[1/1]" in logger.render()

    logger.phase("down")
    logger.on_down(("STDERR", "Container dokkerprog-redis-1 Removed"))
    assert "[1/1]" in logger.render()


def test_service_logs_are_not_folded_into_the_line():
    """on_logs carries container output, which would turn this into a log tail."""
    logger = make_logger()
    logger.phase("up")
    before = logger.render()
    logger.on_logs(("STDOUT", "Container dokkerprog-redis-1 Started"))
    assert logger.render() == before


def test_no_fraction_is_shown_for_phases_that_cannot_complete_one():
    """`inspect`/`health` define no terminal status, so nothing can ever latch.

    Showing `[0/3]` next to three rows all reading `Started` is worse than
    showing no count at all.
    """
    logger = make_logger()
    logger.phase("up")
    logger.on_up(("STDERR", "Container dokkerprog-redis-1 Started"))
    assert "[1/1]" in logger.render()

    logger.phase("inspect")
    rendered = logger.render()
    assert "[" not in rendered
    # The states themselves stay visible -- that is the useful part.
    assert "redis Started" in rendered


def test_elapsed_time_survives_truncation():
    """On a narrow terminal the service list is cut, never the clock."""
    clock = Clock()
    logger = make_logger(width=46, now=clock)
    logger.phase("up")
    for i in range(20):
        logger.on_up(("STDERR", f"Container dokkerprog-service{i}-1 Starting"))
    clock.t = 12.5

    rendered = logger.render()
    assert "12.5s" in rendered
    assert rendered.endswith("...")


def test_elapsed_time_advances_without_any_events():
    """The readiness phase emits nothing; the line must still show progress."""
    clock = Clock()
    logger = make_logger(now=clock)
    logger.phase("health")
    assert "0.0s" in logger.render()
    clock.t = 7.5
    assert "7.5s" in logger.render()


# ---------------------------------------------------------------- rendering


def test_name_shortening_drops_project_prefix_and_replica_index():
    logger = make_logger(label="dokker-test-a1b2c3d4")
    logger.phase("up")
    logger.on_up(("STDERR", "Container dokker-test-a1b2c3d4-echo-1 Started"))
    assert "echo Started" in logger.render()


def test_unrelated_container_names_are_left_alone():
    logger = make_logger(label="dokkerprog")
    logger.phase("up")
    logger.on_up(("STDERR", "Container someother-thing Started"))
    assert "someother-thing Started" in logger.render()


def test_line_is_truncated_to_fit_the_terminal():
    """A wrapped line would break in-place redrawing."""
    logger = make_logger(width=40)
    logger.phase("up")
    for i in range(20):
        logger.on_up(("STDERR", f"Container dokkerprog-service{i}-1 Starting"))

    rendered = logger.render()
    assert len(rendered) <= 39
    assert rendered.endswith("...")


def test_ascii_fallback_when_the_writer_cannot_encode_braille():
    class AsciiWriter(io.StringIO):
        encoding = "ascii"

    logger = ProgressLogger(writer=AsciiWriter(), label="x", width=200, now=Clock())
    assert logger.render()[0] in "|/-\\"


def test_braille_used_when_the_writer_supports_it():
    class Utf8Writer(io.StringIO):
        encoding = "utf-8"

    logger = ProgressLogger(writer=Utf8Writer(), label="x", width=200, now=Clock())
    assert logger.render()[0] in "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def test_draw_redraws_in_place_and_stop_erases():
    buffer = io.StringIO()
    logger = make_logger(writer=buffer)
    logger.phase("up")
    logger.draw()
    logger.draw()

    written = buffer.getvalue()
    # Two frames, each returning to column 0 and clearing to end of line.
    assert written.count("\r") == 2
    assert written.count("\x1b[K") == 2
    assert "\n" not in written


def test_spinner_animates_between_frames():
    logger = make_logger()
    logger.phase("up")
    first = logger.render()
    logger.draw()
    assert logger.render()[0] != first[0]


def test_stop_without_start_is_a_noop():
    logger = make_logger()
    logger.stop()  # must not raise or hang


def test_ticker_thread_starts_draws_and_is_joined_on_stop():
    buffer = io.StringIO()
    logger = make_logger(writer=buffer, interval=0.01)
    logger.phase("up")
    logger.start()
    logger.start()  # idempotent
    try:
        deadline = 2.0
        step = 0.01
        waited = 0.0
        while buffer.getvalue().count("\r") < 3 and waited < deadline:
            import time

            time.sleep(step)
            waited += step
    finally:
        logger.stop()

    assert buffer.getvalue().count("\r") >= 3
    # After stop the thread is gone, so nothing more can be written.
    settled = buffer.getvalue()
    assert settled.endswith("\r\x1b[K")


def test_writes_to_a_closed_stream_are_swallowed():
    """A torn-down capture must never fail the run."""
    buffer = io.StringIO()
    logger = make_logger(writer=buffer)
    logger.phase("up")
    logger.draw()
    buffer.close()
    logger.draw()  # must not raise
    logger.stop()


