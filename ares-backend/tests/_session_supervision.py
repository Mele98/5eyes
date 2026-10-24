"""In-process side of the external pytest supervisor (TEST-TEARDOWN-HANG-001).

``scripts/pytest_supervisor.py`` starts pytest as a child process and bounds
every phase from OUTSIDE the pytest process: test body, fixture teardown,
session finish and interpreter exit get separate deadlines. It needs two
things from inside pytest, both provided here and wired in
``tests/conftest.py``:

* Phase events. The controller (or the single process of a serial run)
  appends one JSON object per line to ``<dir>/events.jsonl``. Under
  pytest-xdist the controller receives ``logstart``/``logreport``/``logfinish``
  for every test executed by any worker, so one file covers all workers.
  Workers never write events.
* Stack dumps on request, in EVERY pytest process (controller and workers):
  ``faulthandler`` writes all thread stacks to ``<dir>/stacks-<role>-<pid>.txt``
  on ``SIGUSR1`` (POSIX, works even while a thread holds the GIL) or, where
  that signal does not exist (Windows), when ``<dir>/dump-request`` appears
  (polled by a daemon thread).

Without ``ARES_SUPERVISOR_DIR`` everything here is a no-op, so a plain
local ``pytest`` run behaves as before.

The module also gates the supported Python runtimes (``SUPPORTED_PYTHON``,
same matrix as CI): an unsupported interpreter stops the session before
collection with a clear message instead of hanging later (a local Python
3.14 run blocked inside the AnyIO/Proactor socketpair setup of
``TestClient``). ``ARES_ALLOW_UNSUPPORTED_PYTHON=1`` overrides it.
"""
from __future__ import annotations

import faulthandler
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import IO

import pytest

SUPERVISOR_DIR_ENV = "ARES_SUPERVISOR_DIR"
ALLOW_UNSUPPORTED_PYTHON_ENV = "ARES_ALLOW_UNSUPPORTED_PYTHON"
EVENTS_FILE = "events.jsonl"
DUMP_REQUEST_FILE = "dump-request"
STACK_FILE_PREFIX = "stacks-"
LEAK_REPORT_PREFIX = "leak-report-"
EVENT_SCHEMA = "pytest-supervisor-event/v1"

# CI runs 3.12 (.github/workflows/test.yml); 3.13 is the verified local
# runtime. Anything else is rejected before collection.
SUPPORTED_PYTHON: tuple[tuple[int, int], ...] = ((3, 12), (3, 13))

_DUMP_POLL_SECONDS = 0.25
_stack_handle: IO[str] | None = None
_events_handle: IO[str] | None = None
_events_lock = threading.Lock()


def supervisor_dir() -> Path | None:
    raw = os.environ.get(SUPERVISOR_DIR_ENV, "").strip()
    return Path(raw) if raw else None


def process_role() -> str:
    return os.environ.get("PYTEST_XDIST_WORKER", "") or "main"


def is_xdist_worker() -> bool:
    return bool(os.environ.get("PYTEST_XDIST_WORKER", ""))


# --- Python support matrix --------------------------------------------------


def unsupported_python_message(version: tuple[int, int] | None = None) -> str | None:
    """``None`` when the interpreter is supported (or the override is set)."""
    current = tuple(version or sys.version_info[:2])
    if current in SUPPORTED_PYTHON:
        return None
    if os.environ.get(ALLOW_UNSUPPORTED_PYTHON_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        return None
    supported = ", ".join(f"{major}.{minor}" for major, minor in SUPPORTED_PYTHON)
    return (
        f"Python {current[0]}.{current[1]} wird von der Backend-Testsuite nicht unterstuetzt "
        f"(unterstuetzt: {supported}; CI: 3.12). Bitte eine unterstuetzte Runtime verwenden "
        f"oder bewusst {ALLOW_UNSUPPORTED_PYTHON_ENV}=1 setzen."
    )


# --- stack dumps on request -------------------------------------------------


def _poll_dump_request(directory: Path, handle: IO[str]) -> None:
    request = directory / DUMP_REQUEST_FILE
    while True:
        time.sleep(_DUMP_POLL_SECONDS)
        if request.exists():
            try:
                handle.write(f"[supervisor] stack dump on request, pid={os.getpid()}\n")
                handle.flush()
                faulthandler.dump_traceback(file=handle, all_threads=True)
                handle.flush()
            except Exception:  # noqa: BLE001 - diagnostics must never break the run
                pass
            return  # exactly one dump per process


def install_stack_dump_handler() -> Path | None:
    """Register the on-request stack dump for this process (idempotent)."""
    global _stack_handle
    directory = supervisor_dir()
    if directory is None or _stack_handle is not None:
        return None
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{STACK_FILE_PREFIX}{process_role()}-{os.getpid()}.txt"
    _stack_handle = open(path, "w", encoding="utf-8")  # noqa: SIM115 - kept open for faulthandler
    sigusr1 = getattr(signal, "SIGUSR1", None)
    if sigusr1 is not None:
        faulthandler.register(sigusr1, file=_stack_handle, all_threads=True, chain=False)
    else:
        threading.Thread(
            target=_poll_dump_request,
            args=(directory, _stack_handle),
            name="supervisor-dump-request-poller",
            daemon=True,
        ).start()
    return path


# --- phase events -----------------------------------------------------------


def emit(event: str, **fields: object) -> None:
    """Append one phase event (controller / serial process only)."""
    global _events_handle
    directory = supervisor_dir()
    if directory is None or is_xdist_worker():
        return
    record = {"schema": EVENT_SCHEMA, "event": event, "t": time.time(), "pid": os.getpid(), **fields}
    line = json.dumps(record, ensure_ascii=False, default=str)
    with _events_lock:
        try:
            if _events_handle is None:
                directory.mkdir(parents=True, exist_ok=True)
                _events_handle = open(directory / EVENTS_FILE, "a", encoding="utf-8")  # noqa: SIM115
            _events_handle.write(line + "\n")
            _events_handle.flush()
        except OSError:
            pass


def leak_report_path() -> Path | None:
    directory = supervisor_dir()
    if directory is None:
        return None
    return directory / f"{LEAK_REPORT_PREFIX}{process_role()}-{os.getpid()}.json"


def _worker_of(report: object) -> str:
    node = getattr(report, "node", None)
    gateway = getattr(node, "gateway", None)
    return getattr(gateway, "id", None) or "main"


class SupervisionPlugin:
    """Phase-event hooks; registered by ``tests/conftest.py::pytest_configure``."""

    def pytest_runtest_logstart(self, nodeid: str, location: object) -> None:
        emit("test_start", nodeid=nodeid)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        when = getattr(report, "when", None)
        worker = _worker_of(report)
        if when == "call" or (when == "setup" and not report.passed):
            emit("teardown_start", nodeid=report.nodeid, worker=worker)
        elif when not in ("setup", "call"):
            # "teardown" -- or an xdist crash report ("???") for a worker
            # that died mid-test: the test is over either way.
            emit("test_finish", nodeid=report.nodeid, worker=worker, outcome=report.outcome, when=when)

    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: object) -> None:
        emit("session_finish_start", exit_status=int(exitstatus))
