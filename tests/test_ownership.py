"""Unit tests for the owner labels and the stale-stack decision — no docker.

The rule under test is "dokker reaps only what it would itself have torn down,
and only once the owner is provably gone". Everything here is about the
*decision*; the real removal is proved against docker in
``tests/test_ownership_integration.py``.
"""

import os
import socket
import subprocess
import sys

from dokker.ownership import (
    COMPOSE_PROJECT_LABEL,
    OWNER_HOST_LABEL,
    OWNER_PID_LABEL,
    OWNER_START_LABEL,
    is_owner_alive,
    owner_labels,
    process_start_marker,
    stale_projects,
    write_owner_override,
)


def _dead_pid() -> int:
    """A PID that certainly belonged to a process which has since exited."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_owner_labels_name_this_process():
    labels = owner_labels()
    assert labels[OWNER_PID_LABEL] == str(os.getpid())
    assert labels[OWNER_HOST_LABEL] == socket.gethostname()
    if sys.platform.startswith("linux"):
        # The start marker is what tells a recycled PID from the original owner.
        assert labels[OWNER_START_LABEL] == process_start_marker(os.getpid())


def test_live_owner_is_alive():
    assert is_owner_alive(owner_labels()) is True


def test_dead_owner_is_not_alive():
    assert is_owner_alive(owner_labels(pid=_dead_pid())) is False


def test_owner_on_another_host_is_left_alone():
    """A PID number means nothing across hosts, so a foreign stack is never stale."""
    assert is_owner_alive(owner_labels(pid=_dead_pid(), hostname="somewhere-else")) is True


def test_unparsable_or_missing_owner_is_left_alone():
    host = socket.gethostname()
    assert is_owner_alive({OWNER_HOST_LABEL: host}) is True
    assert is_owner_alive({OWNER_HOST_LABEL: host, OWNER_PID_LABEL: "not-a-pid"}) is True
    assert is_owner_alive({OWNER_HOST_LABEL: host, OWNER_PID_LABEL: "0"}) is True


def test_recycled_pid_counts_as_dead():
    """Same PID, different start marker: a younger process inherited the number."""
    if not sys.platform.startswith("linux"):
        return
    labels = owner_labels()
    labels[OWNER_START_LABEL] = "1"  # nobody alive today started at tick 1
    assert is_owner_alive(labels) is False


def test_stale_projects_requires_every_owner_dead():
    host = socket.gethostname()
    dead = {OWNER_HOST_LABEL: host, OWNER_PID_LABEL: str(_dead_pid())}
    live = {OWNER_HOST_LABEL: host, OWNER_PID_LABEL: str(os.getpid())}
    stacks = {
        "gone": [dead, dead],
        "mixed": [dead, live],
        "running": [live],
        "": [dead],  # no compose project label: nothing to `down`
    }
    assert stale_projects(stacks, hostname=host) == ["gone"]


def test_override_labels_exactly_the_given_services(tmp_path):
    labels = {OWNER_PID_LABEL: "4242", OWNER_HOST_LABEL: "box"}
    path = write_owner_override(["db", "1.0"], str(tmp_path), labels=labels)
    text = open(path, encoding="utf-8").read()
    assert text.count("labels:") == 2
    # Names and values are JSON-quoted so YAML cannot reinterpret them.
    assert '  "db":' in text
    assert '  "1.0":' in text
    assert '"dokker.owner.pid": "4242"' in text
    assert COMPOSE_PROJECT_LABEL not in text  # compose sets that one itself


def test_override_for_no_services_is_still_valid_yaml(tmp_path):
    path = write_owner_override([], str(tmp_path), labels={OWNER_PID_LABEL: "1", OWNER_HOST_LABEL: "box"})
    assert open(path, encoding="utf-8").read().rstrip().endswith("services:\n  {}")
