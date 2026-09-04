"""Ownership labels and the stale-stack reaper.

A ``testing()`` deployment promises to ``down`` its stack when its context
manager exits. That promise is only as good as the process keeping it: a test
run that is SIGKILLed, a session that is closed, or a debugger that is
stopped mid-test never reaches the teardown, and the stack it started stays
up forever with a random ``dokker-test-<hex>`` name nobody recognises.

Left alone these strays only waste memory. What actually breaks test suites
is the *reflex* they provoke: people clean them with a pattern sweep such as
``docker ps -a | grep dokker-test | xargs docker rm -f``, and a sweep cannot
tell a stray stack from one that a live run in another terminal is using at
that very moment. Killing that one turns a green suite into hundreds of
"database vanished" errors with no local cause.

This module makes strays self-identifying so dokker can remove exactly them
and nothing else:

* :func:`owner_labels` produces labels naming the process that promised the
  teardown (its PID, host and start marker). ``Deployment.aup`` stamps them
  onto every service -- but only when it registers a ``down``. A stack that
  dokker would *not* have removed at exit (``--dokker-keep``, ``local()``
  policy, ``down_on_exit=False``) carries no owner label and is never touched.
* :func:`areap_stale` downs the labelled stacks whose owner is provably gone:
  same host, PID no longer running (or reused by a younger process). It runs
  before every ``up`` that registers a ``down``, so a stray never outlives the
  next test run on the machine.

The rule is: dokker reaps only what it would itself have torn down, and only
once it is certain nobody is still keeping the promise.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import socket
import sys
import tempfile
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from koil import unkoil
from koil.errors import KoilError

from dokker.command import CommandError, acheck_docker_available, astream_command

logger = logging.getLogger(__name__)

OWNER_PID_LABEL = "dokker.owner.pid"
OWNER_HOST_LABEL = "dokker.owner.host"
OWNER_START_LABEL = "dokker.owner.start"
COMPOSE_PROJECT_LABEL = "com.docker.compose.project"

OWNER_LABELS = (OWNER_PID_LABEL, OWNER_HOST_LABEL, OWNER_START_LABEL)


def process_start_marker(pid: int) -> Optional[str]:
    """Return an opaque marker that changes whenever *pid* is reused.

    A PID alone is a weak identity: after the owner exits the kernel may hand
    the same number to an unrelated process, which would make a dead owner look
    alive and keep its stray stack around. On Linux the process start time
    (field 22 of ``/proc/<pid>/stat``, in clock ticks since boot) tells the two
    apart. Other platforms return None and fall back to the PID check alone.
    """
    if not sys.platform.startswith("linux"):
        return None
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="ascii", errors="replace") as f:
            content = f.read()
    except OSError:
        return None
    # The command name (field 2) is parenthesised and may contain spaces, so
    # split after the last ')' and count from field 3.
    try:
        fields = content.rsplit(")", 1)[1].split()
        return fields[22 - 3]
    except (IndexError, ValueError):
        return None


def owner_labels(pid: Optional[int] = None, hostname: Optional[str] = None) -> Dict[str, str]:
    """Labels that record which process promised to tear a stack down.

    ``pid`` and ``hostname`` default to the current process and host; tests
    pass them explicitly.
    """
    pid = os.getpid() if pid is None else pid
    labels = {
        OWNER_PID_LABEL: str(pid),
        OWNER_HOST_LABEL: hostname if hostname is not None else socket.gethostname(),
    }
    start = process_start_marker(pid)
    if start is not None:
        labels[OWNER_START_LABEL] = start
    return labels


def _pid_alive(pid: int) -> bool:
    """Whether a process with *pid* currently exists on this host.

    Errs on the side of "alive": anything we cannot determine keeps the stack.
    """
    if sys.platform == "win32":
        # os.kill(pid, 0) TERMINATES the target on Windows, so probe through
        # the win32 API instead.
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                # ERROR_INVALID_PARAMETER (87) means no such process; any other
                # failure (e.g. access denied) means it exists.
                return kernel32.GetLastError() != 87
            try:
                code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return True
                return code.value == STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return True

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists, owned by someone else.
        return True
    except OSError:
        return True
    return True


def is_owner_alive(labels: Mapping[str, str], hostname: Optional[str] = None) -> bool:
    """Decide from a container's labels whether its owning process still runs.

    Returns True whenever the answer is uncertain -- a stack recorded by another
    host, an unparsable PID, a missing label -- because the only safe mistake
    here is leaving a stray behind. Returns False only when the owner PID does
    not exist on *this* host, or exists but with a different start marker (the
    number was recycled by a younger process).
    """
    hostname = socket.gethostname() if hostname is None else hostname
    if labels.get(OWNER_HOST_LABEL) != hostname:
        return True
    try:
        pid = int(labels[OWNER_PID_LABEL])
    except (KeyError, ValueError):
        return True
    if pid <= 0:
        return True
    if not _pid_alive(pid):
        return False
    recorded = labels.get(OWNER_START_LABEL)
    current = process_start_marker(pid)
    if recorded is not None and current is not None and recorded != current:
        return False
    return True


def write_owner_override(services: Iterable[str], directory: str, labels: Optional[Mapping[str, str]] = None) -> str:
    """Write a compose override file that stamps *labels* onto *services*.

    Returns the path of the written file. The override is appended to the
    deployment's ``--file`` list, so the labels land on every container compose
    creates for the project, including one-offs from ``run``. Map-form labels
    merge cleanly with whatever the base file declares (list or map).

    Only the resolved services (``docker compose config --services``) may be
    listed: naming a service the base file lacks would define a new, imageless
    service and fail validation.
    """
    labels = owner_labels() if labels is None else labels
    services = list(services)
    lines = ["# Written by dokker. Records the process that promised to `down` this stack,", "# so `dokker.reap_stale()` can remove it if that process dies first.", "services:"]
    if not services:
        lines.append("  {}")
    for service in services:
        # JSON strings are valid YAML scalars, so this quotes names such as
        # `1.0` or `no` that YAML would otherwise read as numbers/booleans.
        lines.append(f"  {json.dumps(service)}:")
        lines.append("    labels:")
        for key, value in labels.items():
            lines.append(f"      {json.dumps(key)}: {json.dumps(str(value))}")
    path = os.path.join(directory, "dokker-owner.override.yaml")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


_PS_FORMAT = "\t".join(["{{.ID}}", f'{{{{.Label "{COMPOSE_PROJECT_LABEL}"}}}}', *(f'{{{{.Label "{label}"}}}}' for label in OWNER_LABELS)])


async def _acollect(command: List[str], env: Optional[Dict[str, str]] = None, cwd: Optional[str] = None) -> str:
    stdout: list[str] = []
    async for source, line in astream_command(command, env=env, cwd=cwd):
        if source == "STDOUT":
            stdout.append(line)
    return "\n".join(stdout)


async def alist_owned_stacks(client_call: Optional[List[str]] = None, env: Optional[Dict[str, str]] = None) -> Dict[str, List[Dict[str, str]]]:
    """List every container carrying an owner label, grouped by compose project.

    Each entry is the container's label mapping (owner labels plus the compose
    project). Containers without the owner label -- kept stacks, `local()`
    stacks, anything not started by dokker -- are never listed.
    """
    docker = (client_call or ["docker"])[0]
    output = await _acollect([docker, "ps", "--all", "--filter", f"label={OWNER_PID_LABEL}", "--format", _PS_FORMAT], env=env)
    stacks: Dict[str, List[Dict[str, str]]] = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 2 + len(OWNER_LABELS):
            continue
        container_id, project, *values = parts
        labels = {"id": container_id, COMPOSE_PROJECT_LABEL: project}
        for key, value in zip(OWNER_LABELS, values):
            if value:
                labels[key] = value
        stacks.setdefault(project, []).append(labels)
    return stacks


def stale_projects(stacks: Mapping[str, Sequence[Mapping[str, str]]], hostname: Optional[str] = None) -> List[str]:
    """Pick the projects from :func:`alist_owned_stacks` whose owners are all gone.

    A project is stale only if *every* one of its labelled containers has a
    dead owner; one live owner keeps the whole stack. Containers without a
    project label are skipped (nothing to `down`).
    """
    stale: List[str] = []
    for project, containers in stacks.items():
        if not project:
            continue
        if all(not is_owner_alive(labels, hostname=hostname) for labels in containers):
            stale.append(project)
    return sorted(stale)


async def _adown_project(project: str, client_call: List[str], env: Optional[Dict[str, str]]) -> None:
    """Remove *project* completely, by name alone.

    ``docker compose -p <name> down`` needs no compose file: it works from the
    daemon's project labels. It is run from an empty directory so a compose
    file lying in the caller's cwd cannot be picked up and mistaken for the
    project's definition. If compose refuses, fall back to removing the
    project's containers, networks and volumes by label.
    """
    workdir = tempfile.mkdtemp(prefix="dokker-reap-")
    try:
        try:
            await _acollect([*client_call, "--project-name", project, "down", "--volumes", "--remove-orphans"], env=env, cwd=workdir)
            return
        except CommandError as e:
            logger.warning("`docker compose down` of stale project %s failed, removing by label instead: %s", project, e)
        docker = client_call[0]
        selector = ["--filter", f"label={COMPOSE_PROJECT_LABEL}={project}"]
        containers = (await _acollect([docker, "ps", "--all", "--quiet", *selector], env=env)).split()
        if containers:
            await _acollect([docker, "rm", "--force", "--volumes", *containers], env=env)
        networks = (await _acollect([docker, "network", "ls", "--quiet", *selector], env=env)).split()
        if networks:
            await _acollect([docker, "network", "rm", *networks], env=env)
        volumes = (await _acollect([docker, "volume", "ls", "--quiet", *selector], env=env)).split()
        if volumes:
            await _acollect([docker, "volume", "rm", "--force", *volumes], env=env)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def areap_stale(client_call: Optional[List[str]] = None, env: Optional[Dict[str, str]] = None) -> List[str]:
    """Down every dokker-owned stack whose owning process no longer exists.

    Only stacks that dokker itself would have removed at exit are candidates:
    they carry the owner labels ``Deployment.aup`` stamps when it registers a
    ``down``. A stack is reaped when its recorded owner is on this host and
    that PID is gone (or has been reused). Stacks owned by live processes,
    recorded by other hosts, kept with ``--dokker-keep``/``down_on_exit=False``,
    or started outside dokker are left untouched.

    Runs automatically at the start of every ``up`` that registers a ``down``
    (``Deployment.reap_stale``, default True); call it directly to clean a
    machine by hand instead of sweeping ``docker ps | grep | xargs rm -f``,
    which cannot tell a stray from a stack another terminal is using.

    Parameters
    ----------
    client_call : Optional[List[str]]
        The compose invocation, e.g. ``["docker", "compose"]`` (the default).
    env : Optional[Dict[str, str]]
        Extra environment for the docker commands.

    Returns
    -------
    List[str]
        The compose project names that were removed.
    """
    client_call = list(client_call or ["docker", "compose"])
    await acheck_docker_available(client_call)
    try:
        stacks = await alist_owned_stacks(client_call, env=env)
    except CommandError as e:
        logger.warning("Could not list dokker-owned stacks, skipping stale reaping: %s", e)
        return []

    reaped: List[str] = []
    for project in stale_projects(stacks):
        owner = stacks[project][0].get(OWNER_PID_LABEL, "?")
        logger.info("Reaping stale stack %s: its owner (pid %s on this host) is gone.", project, owner)
        try:
            await _adown_project(project, client_call, env)
        except CommandError as e:
            logger.warning("Could not remove stale stack %s: %s", project, e)
            continue
        reaped.append(project)
    return reaped


def reap_stale(client_call: Optional[List[str]] = None, env: Optional[Dict[str, str]] = None) -> List[str]:
    """Synchronous form of :func:`areap_stale`.

    Works both inside a koil context (e.g. within a ``with testing(...)`` block)
    and from a plain script or REPL, where it runs its own event loop.
    """
    try:
        return unkoil(areap_stale, client_call=client_call, env=env)
    except KoilError:
        return asyncio.run(areap_stale(client_call=client_call, env=env))
