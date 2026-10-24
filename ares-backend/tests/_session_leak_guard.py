"""Session-end guard against background resources that outlive a test run.

Codex reported (2026-10-20, PR #653/#657 closure reviews) that focused pytest
runs printed all dots but the process did not terminate for 60-180+ s. A
Python process waits at interpreter exit for every *non-daemon* thread
(including ``concurrent.futures`` workers, which APScheduler uses to run its
jobs), so such a thread is the classic cause of "green but never exits".

This module only *observes*; ``tests/conftest.py`` wires it into
``pytest_sessionfinish`` / ``pytest_terminal_summary`` / ``pytest_unconfigure``:

* non-daemon, non-main threads still alive after the run are reported
  (``FIVEEYES_STRICT_LEAK_GUARD=1`` turns the report into a failed session);
* APScheduler instances of ``price_updater`` / ``backup_scheduler`` that are
  still running after the run are reported (their threads are daemon threads,
  but a running backup scheduler would write into the real backup directory);
* an exit watchdog dumps all thread stacks to stderr if the process is still
  alive N seconds after pytest finished (``FIVEEYES_PYTEST_EXIT_WATCHDOG_S``,
  default 60, ``0`` disables), so the next hang names its culprit instead of
  just "no output".
"""
from __future__ import annotations

import faulthandler
import os
import sys
import threading
from dataclasses import dataclass

STRICT_ENV = "FIVEEYES_STRICT_LEAK_GUARD"
WATCHDOG_ENV = "FIVEEYES_PYTEST_EXIT_WATCHDOG_S"
DEFAULT_WATCHDOG_SECONDS = 60.0

# (module name, attribute holding the scheduler instance)
_SCHEDULER_SLOTS = (
    ("price_updater", "scheduler"),
    ("backup_scheduler", "_scheduler"),
)


@dataclass(frozen=True)
class LeakReport:
    threads: tuple[str, ...]
    schedulers: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return not self.threads and not self.schedulers

    def lines(self) -> list[str]:
        out = [f"nicht-daemonischer Thread laeuft noch: {t}" for t in self.threads]
        out += [f"Scheduler laeuft noch: {s}" for s in self.schedulers]
        return out


def find_leaked_threads() -> tuple[str, ...]:
    """Alive non-daemon threads other than the main and the calling thread.

    These are exactly the threads ``threading._shutdown`` joins at interpreter
    exit, i.e. the ones that keep the process alive after the last test.
    """
    main = threading.main_thread()
    current = threading.current_thread()
    leaked = []
    for thread in threading.enumerate():
        if thread is main or thread is current or thread.daemon or not thread.is_alive():
            continue
        target = getattr(thread, "_target", None)
        target_name = getattr(target, "__qualname__", None) or type(thread).__name__
        leaked.append(f"{thread.name} ({target_name})")
    return tuple(sorted(leaked))


def find_running_schedulers() -> tuple[str, ...]:
    """Product schedulers that were started (e.g. via TestClient lifespan) and never stopped."""
    running = []
    for module_name, attr in _SCHEDULER_SLOTS:
        module = sys.modules.get(module_name)
        scheduler = getattr(module, attr, None) if module is not None else None
        if scheduler is not None and getattr(scheduler, "running", False):
            running.append(f"{module_name}.{attr}")
    return tuple(running)


def collect() -> LeakReport:
    return LeakReport(threads=find_leaked_threads(), schedulers=find_running_schedulers())


def strict_enabled() -> bool:
    return os.environ.get(STRICT_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def watchdog_seconds() -> float:
    raw = os.environ.get(WATCHDOG_ENV, "").strip()
    if not raw:
        return DEFAULT_WATCHDOG_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_WATCHDOG_SECONDS


def arm_exit_watchdog() -> bool:
    """Dump every thread's stack to stderr if the process outlives pytest by N s.

    The timer is cancelled automatically when the interpreter finalizes, so a
    process that exits normally never prints anything.
    """
    seconds = watchdog_seconds()
    stream = sys.__stderr__
    if seconds <= 0 or stream is None:
        return False
    try:
        faulthandler.dump_traceback_later(seconds, repeat=True, file=stream, exit=False)
    except (ValueError, OSError, RuntimeError):
        return False
    return True
