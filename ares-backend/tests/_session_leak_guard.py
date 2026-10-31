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
* an exit watchdog bounds the interpreter exit: if the process is still alive
  N seconds after pytest finished (``FIVEEYES_PYTEST_EXIT_WATCHDOG_S``,
  default 60, ``0`` disables) it dumps all thread stacks ONCE to stderr and
  terminates the process non-zero. The exit code keeps an already failed
  pytest status; a green run that hangs at exit ends with
  ``EXIT_WATCHDOG_CODE``. Phases before ``pytest_unconfigure`` (test body,
  fixture teardown, session finish) are bounded by the external supervisor
  ``scripts/pytest_supervisor.py`` (see ``tests/_session_supervision.py``).
"""
from __future__ import annotations

import faulthandler
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

STRICT_ENV = "FIVEEYES_STRICT_LEAK_GUARD"
WATCHDOG_ENV = "FIVEEYES_PYTEST_EXIT_WATCHDOG_S"
DEFAULT_WATCHDOG_SECONDS = 60.0
# Exit code of a run whose pytest status was green but whose interpreter exit
# hung past the watchdog deadline. Same value as the supervisor's
# ``interpreter_exit_timeout`` code (scripts/pytest_supervisor.py).
EXIT_WATCHDOG_CODE = 93
# Hard C-level backstop (faulthandler, needs no GIL) after the Python-level
# watchdog: covers a hang that holds the GIL. Exits with code 1.
_BACKSTOP_EXTRA_SECONDS = 5.0

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


def watchdog_exit_code(exit_status: object) -> int:
    """Non-zero exit code for a watchdog kill that keeps the first failure."""
    try:
        status = int(exit_status)  # pytest.ExitCode is an IntEnum
    except (TypeError, ValueError):
        status = 0
    return status if status != 0 else EXIT_WATCHDOG_CODE


def arm_exit_watchdog(
    exit_status: object = None,
    on_fire: Callable[[float, int], None] | None = None,
) -> bool:
    """Bound the interpreter exit: dump all stacks once, then exit non-zero.

    Armed after pytest finished. A daemon timer thread keeps running while
    ``threading._shutdown`` joins a leaked non-daemon thread; after N seconds
    it writes every thread's stack ONCE to stderr and ends the process with
    :func:`watchdog_exit_code` (never 0). A faulthandler timer a few seconds
    later is the backstop for a hang that holds the GIL. A process that exits
    normally never prints anything (both timers die with the interpreter).
    """
    seconds = watchdog_seconds()
    stream = sys.__stderr__
    if seconds <= 0 or stream is None:
        return False
    code = watchdog_exit_code(exit_status)

    def _fire() -> None:
        try:
            stream.write(
                f"\n[exit-watchdog] Prozess lebt {seconds:g} s nach pytest-Ende noch; "
                f"Thread-Stacks (einmalig), danach Exit {code}:\n"
            )
            stream.flush()
            faulthandler.dump_traceback(file=stream, all_threads=True)
            if on_fire is not None:
                on_fire(seconds, code)
        except Exception:  # noqa: BLE001 - the exit below must happen regardless
            pass
        finally:
            for handle in (sys.__stdout__, stream):
                try:
                    handle.flush()
                except Exception:  # noqa: BLE001
                    pass
            os._exit(code)

    timer = threading.Timer(seconds, _fire)
    timer.name = "pytest-exit-watchdog"
    timer.daemon = True
    try:
        timer.start()
    except RuntimeError:
        return False
    try:
        faulthandler.dump_traceback_later(
            seconds + _BACKSTOP_EXTRA_SECONDS, repeat=False, file=stream, exit=True
        )
    except (ValueError, OSError, RuntimeError):
        pass
    return True


def write_leak_report_json(
    path: Path,
    report: LeakReport,
    *,
    role: str,
    exit_status: object,
    worker_lines: list[str] | tuple[str, ...] = (),
) -> None:
    """Persist the leak inventory as JSON already in ``pytest_sessionfinish``.

    Written before the interpreter exit, so a later exit hang (or the
    watchdog kill) cannot lose the evidence.
    """
    try:
        status = int(exit_status)
    except (TypeError, ValueError):
        status = None
    payload = {
        "schema": "session-leak-report/v1",
        "role": role,
        "pid": os.getpid(),
        "written_at": time.time(),
        "strict": strict_enabled(),
        "exit_status": status,
        "threads": list(report.threads),
        "schedulers": list(report.schedulers),
        "worker_lines": list(worker_lines),
        "leak_detected": bool(not report.empty or worker_lines),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
