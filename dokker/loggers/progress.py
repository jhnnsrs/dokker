"""A single self-updating terminal line showing a stack coming up.

Starting a compose stack is the slowest thing dokker does, and with the default
`VoidLogger` it is entirely silent -- a blank screen for a minute with no clue
which service is holding things up. `PrintLogger` is the other extreme: it dumps
every raw ``('STDERR', 'Container x  Started')`` tuple and buries the output it
is mixed into.

This sits in between. It parses compose's own progress lines into per-resource
state and paints one line, in place, that looks like::

    ⠹ dokker-test-a1b2 · up [1/2] · echo Waiting, redis Started · 4.2s

Nothing is scrolled: the line is redrawn with ``\\r`` and erased on `stop`, so
the surrounding test output is left unmarked.

Two design constraints are worth knowing before editing this module.

*No third-party dependencies.* dokker is registered as a ``pytest11`` entry
point, so this module is imported by every pytest run of every project that
depends on dokker. A rich/colorama import here would be inflicted on all of
them, so the rendering is hand-rolled ANSI.

*A background thread owns every write.* The `Logger` callbacks fire on koil's
event-loop thread while the main thread is blocked inside `Deployment.up()`, so
they only mutate state under a lock. The ticker thread does all the drawing --
which also keeps the spinner and the elapsed timer moving during the phases that
emit no output at all (`inspect`, and the readiness checks in `check_health`).
"""

import re
import shutil
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, TextIO, Tuple

LogTuple = Tuple[str, str]

#: The resource kinds compose prefixes its progress lines with. Anything else in
#: leading position is a layer id (`17a39c0ba978 Downloading 48.48kB`), which is
#: deliberately *not* tracked as state -- a big pull emits hundreds of them and
#: they would swamp the service rows.
RESOURCE_TYPES = frozenset({"Image", "Container", "Network", "Volume"})

#: Which resource kind is the meaningful unit of work for a given phase. During
#: a pull there are no containers yet, so images are what there is to count.
TRACKED_TYPE: Dict[str, str] = {
    "pull": "Image",
    "build": "Image",
}
DEFAULT_TRACKED_TYPE = "Container"

#: Per-phase terminal statuses, used for the ``[done/total]`` fraction. Only the
#: end state of *that* operation counts: `Created` means nothing during `up`,
#: where the container still has to start and possibly pass a healthcheck.
TERMINAL_STATUSES: Dict[str, frozenset[str]] = {
    "pull": frozenset({"Pulled", "Error", "Skipped", "Warning"}),
    "build": frozenset({"Built", "Error", "Skipped", "Warning"}),
    "up": frozenset({"Healthy", "Running", "Started", "Error", "Skipped"}),
    "stop": frozenset({"Stopped", "Exited", "Error"}),
    "down": frozenset({"Removed", "Error"}),
}

BRAILLE_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
ASCII_FRAMES = "|/-\\"

# Matches CSI sequences. Compose writes plain text to a pipe, but FORCE_COLOR /
# CLICOLOR_FORCE in the environment overrides that, and `command.py` only strips
# surrounding whitespace -- so escapes can reach us and would corrupt the line.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

#: Shortest layer id compose prints. Used to tell `17a39c0ba978 Downloading 4kB`
#: apart from prose that merely happens to have two tokens.
_MIN_LAYER_ID = 8


class ProgressEvent:
    """One parsed compose progress line.

    `resource_type` is None for image-layer lines, which carry no kind prefix.
    """

    __slots__ = ("resource_type", "name", "status")

    def __init__(self, resource_type: Optional[str], name: str, status: str) -> None:
        """Store the three parsed fields."""
        self.resource_type = resource_type
        self.name = name
        self.status = status

    def __eq__(self, other: object) -> bool:
        """Compare by field, so tests can assert against a literal."""
        if not isinstance(other, ProgressEvent):
            return NotImplemented
        return (self.resource_type, self.name, self.status) == (other.resource_type, other.name, other.status)

    def __repr__(self) -> str:
        """Render as a constructor call, for readable test failures."""
        return f"ProgressEvent({self.resource_type!r}, {self.name!r}, {self.status!r})"


def strip_ansi(line: str) -> str:
    """Remove CSI escape sequences from a line."""
    return _ANSI_RE.sub("", line)


def parse_compose_progress(line: str) -> Optional[ProgressEvent]:
    """Parse one line of compose progress output.

    Handles the two shapes compose emits::

        Container dokker-test-a1b2-redis-1 Healthy   -> ('Container', ..., 'Healthy')
        17a39c0ba978 Extracting 3.42MB               -> (None, '17a39c0ba978', 'Extracting 3.42MB')

    Returns None for anything else -- warnings, blank lines, service log output
    that happened to be interleaved. Never raises: an unrecognised line is
    ignored, not rendered.
    """
    text = strip_ansi(line).strip()
    head, _, rest = text.partition(" ")
    rest = rest.strip()
    if not head or not rest:
        return None

    if head in RESOURCE_TYPES:
        name, _, status = rest.partition(" ")
        status = status.strip()
        if not status:
            return None
        return ProgressEvent(head, name, status)

    # No kind prefix: an image layer, whose id is the first token. Only accept it
    # when the id actually looks like one, so ordinary prose ("Error response
    # from daemon: ...") cannot masquerade as progress.
    if len(head) >= _MIN_LAYER_ID and all(c in "0123456789abcdef" for c in head):
        return ProgressEvent(None, head, rest)

    return None


class ProgressLogger:
    """A `Logger` that paints stack startup as one self-updating line.

    Implements every method of the `Logger` protocol -- pydantic validates
    `Deployment.logger` by isinstance against a `runtime_checkable` protocol, so
    a partial implementation is rejected at construction time.

    Examples
    --------
    ::

        with testing("docker-compose.yaml") as deployment:
            progress = ProgressLogger(label="my-stack")
            deployment.logger = progress
            progress.start()
            try:
                progress.phase("pull")
                deployment.pull()
                progress.phase("up")
                deployment.up()
            finally:
                progress.stop()
    """

    def __init__(
        self,
        *,
        writer: Optional[TextIO] = None,
        label: str = "dokker",
        interval: float = 0.1,
        ascii_only: bool = False,
        now: Callable[[], float] = time.monotonic,
        width: Optional[int] = None,
    ) -> None:
        """Configure the renderer.

        Parameters
        ----------
        writer:
            Where to draw. Defaults to `sys.stdout`, looked up at draw time so
            that pytest's capture suspension is picked up correctly.
        label:
            Shown at the head of the line, and stripped from container names.
            The compose project name is the useful value.
        interval:
            Seconds between redraws.
        ascii_only:
            Force the ASCII spinner. Otherwise braille is used when the writer's
            encoding can represent it.
        now:
            Monotonic clock, injectable so tests can render deterministic frames.
        width:
            Fixed terminal width. Defaults to querying the terminal per draw.
        """
        self._writer = writer
        self._label = label
        self._interval = interval
        self._ascii_only = ascii_only
        self._now = now
        self._width = width

        self._lock = threading.Lock()
        self._state: Dict[Tuple[Optional[str], str], str] = {}
        self._settled: set[Tuple[Optional[str], str]] = set()
        self._detail: Optional[str] = None
        self._phase: str = ""
        self._phase_started: float = now()
        self._tick = 0
        self._drawn = False

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin redrawing on a daemon thread. Idempotent."""
        if self._thread is not None:
            return
        self._stop_event = threading.Event()
        self._phase_started = self._now()
        self._thread = threading.Thread(target=self._run, name="dokker-progress", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop redrawing and erase the line. Idempotent.

        The order here is load-bearing: the ticker is joined *before* the line is
        erased, and both happen before the caller resumes pytest's output
        capture. A frame written after capture resumes would be replayed later as
        carriage-return litter in some unrelated test's captured output.
        """
        thread = self._thread
        if thread is None:
            return
        self._stop_event.set()
        thread.join(timeout=2.0)
        self._thread = None
        self._erase()

    def phase(self, name: str) -> None:
        """Name the operation now in progress, and restart the elapsed timer.

        Callers drive this because two of the slowest steps -- `inspect()` and
        the readiness checks in `check_health()` -- never call the logger at all.
        Without it the line would sit frozen through exactly the wait a user most
        wants feedback on.
        """
        with self._lock:
            if name != self._phase:
                self._phase = name
                self._phase_started = self._now()
                self._settled.clear()
                self._detail = None

    # ------------------------------------------------------------------
    # Logger protocol
    # ------------------------------------------------------------------

    def on_pull(self, log: LogTuple) -> None:
        """Record a line from `docker compose pull`."""
        self._ingest(log)

    def on_up(self, log: LogTuple) -> None:
        """Record a line from `docker compose up` (or `build`)."""
        self._ingest(log)

    def on_stop(self, log: LogTuple) -> None:
        """Record a line from `docker compose stop`/`kill`."""
        self._ingest(log)

    def on_down(self, log: LogTuple) -> None:
        """Record a line from `docker compose down`."""
        self._ingest(log)

    def on_logs(self, log: LogTuple) -> None:
        """Ignore service log output.

        `alogs`/`arun`/`aexec` route container output through this hook. It is
        not progress, and folding it into the line would turn the status display
        into a log tail.
        """

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _ingest(self, log: LogTuple) -> None:
        """Parse one log tuple and fold it into the rendered state."""
        event = parse_compose_progress(log[1])
        if event is None:
            return

        with self._lock:
            if event.resource_type is None:
                # An image layer. Shown as transient detail so a long pull looks
                # alive, but never kept as a row -- there can be hundreds.
                self._detail = f"{event.name[:12]} {event.status}"
                return

            key = (event.resource_type, event.name)
            self._state[key] = event.status
            if event.status in TERMINAL_STATUSES.get(self._phase, frozenset()):
                # Latched, so the fraction only ever climbs within a phase. A
                # container that reports `Started` and then `Waiting` (which is
                # what `up --wait` does) must not make the count go backwards.
                self._settled.add(key)

    def _tracked_type(self) -> str:
        """The resource kind that counts as a unit of work in this phase."""
        return TRACKED_TYPE.get(self._phase, DEFAULT_TRACKED_TYPE)

    def _rows(self) -> List[Tuple[str, str, bool]]:
        """Tracked resources as `(name, status, settled)`, unsettled first.

        Caller must hold the lock.
        """
        tracked = self._tracked_type()
        rows = [(name, status, (kind, name) in self._settled) for (kind, name), status in self._state.items() if kind == tracked]
        # Stable sort: what is still in flight is what the user is waiting on.
        rows.sort(key=lambda row: row[2])
        return rows

    def _short_name(self, name: str) -> str:
        """Drop the compose project prefix and replica suffix from a container name.

        `dokker-test-a1b2c3d4-redis-1` is mostly noise next to a label that
        already says `dokker-test-a1b2c3d4`; `redis` is the part that identifies
        the service.
        """
        short = name
        prefix = f"{self._label}-"
        if short.startswith(prefix):
            short = short[len(prefix) :]
        head, _, tail = short.rpartition("-")
        if head and tail.isdigit():
            short = head
        return short or name

    def _frames(self) -> str:
        """The spinner frames this writer can actually display."""
        if self._ascii_only:
            return ASCII_FRAMES
        encoding = getattr(self._out(), "encoding", None)
        if not encoding:
            return ASCII_FRAMES
        try:
            BRAILLE_FRAMES.encode(encoding)
        except (LookupError, UnicodeEncodeError):
            return ASCII_FRAMES
        return BRAILLE_FRAMES

    def _out(self) -> TextIO:
        """The stream to draw on, resolved late so capture suspension is honoured."""
        return self._writer if self._writer is not None else sys.stdout

    def render(self) -> str:
        """Build the current status line, without drawing it.

        Public so it can be asserted on directly in tests.
        """
        with self._lock:
            phase = self._phase or "starting"
            elapsed = self._now() - self._phase_started
            rows = self._rows()
            detail = self._detail
            done = sum(1 for row in rows if row[2])

        frames = self._frames()
        spinner = frames[self._tick % len(frames)]

        # `inspect` and `health` define no terminal status, so nothing can latch
        # and the fraction would sit at [0/n] while every row reads `Started`.
        # Drop it rather than show a count that contradicts the states beside it.
        countable = self._phase in TERMINAL_STATUSES

        parts = [f"{spinner} {self._label}"]
        parts.append(f"{phase} [{done}/{len(rows)}]" if rows and countable else phase)
        # Elapsed goes before the per-service detail: on a narrow terminal the
        # detail is what should be cut, not the clock telling you it is alive.
        parts.append(f"{elapsed:.1f}s")
        if rows:
            parts.append(", ".join(f"{self._short_name(name)} {status}" for name, status, _ in rows))
        if detail:
            parts.append(detail)

        return _truncate(" · ".join(parts), self._terminal_width(), ascii_only=frames == ASCII_FRAMES)

    def _terminal_width(self) -> int:
        """Usable columns, leaving one spare so the line cannot wrap.

        A wrapped line breaks in-place redrawing: `\\r` returns to the start of
        the last screen row, not of the logical line.
        """
        if self._width is not None:
            return max(self._width - 1, 10)
        return max(shutil.get_terminal_size((80, 24)).columns - 1, 10)

    def draw(self) -> None:
        """Paint one frame in place."""
        line = self.render()
        stream = self._out()
        try:
            stream.write("\r" + line + "\x1b[K")
            stream.flush()
        except (ValueError, OSError):
            # The stream was closed underneath us (a torn-down capture, a closed
            # pipe). Losing a progress frame must never fail the run.
            return
        self._drawn = True
        self._tick += 1

    def _erase(self) -> None:
        """Clear the line, if anything was ever drawn on it."""
        if not self._drawn:
            return
        stream = self._out()
        try:
            stream.write("\r\x1b[K")
            stream.flush()
        except (ValueError, OSError):
            return
        self._drawn = False

    def _run(self) -> None:
        """Ticker body: draw immediately, then until stopped."""
        self.draw()
        while not self._stop_event.wait(self._interval):
            self.draw()


def _truncate(line: str, width: int, *, ascii_only: bool = False) -> str:
    """Shorten a line to `width`, marking that it was cut."""
    if len(line) <= width:
        return line
    marker = "..." if ascii_only else "…"
    return line[: max(width - len(marker), 0)] + marker
