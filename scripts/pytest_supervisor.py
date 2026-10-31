#!/usr/bin/env python
"""External supervisor for pytest runs: bounded phases, evidence, tree kill.

TEST-TEARDOWN-HANG-001: a pytest process that hangs (test body, fixture
teardown, session finish, interpreter exit) must not bind a CI runner until
the GitHub job timeout. This script runs pytest as a child process and owns
the process boundary from OUTSIDE:

* separate deadlines per phase, measured on the supervisor's clock from the
  phase events the child writes (``tests/_session_supervision.py``):
  ``--startup-timeout`` (start -> first test / session finish, i.e.
  collection), ``--test-timeout`` (per test: setup + call),
  ``--teardown-timeout`` (per test: teardown, incl. module/session fixtures
  finalized there), ``--session-timeout`` (session finish and idle gaps with
  no test in flight, e.g. xdist worker shutdown) and ``--exit-timeout``
  (after ``pytest_unconfigure`` until the process is gone);
* on a breach: ONE stack dump request to every pytest process of the tree
  (``SIGUSR1`` to the process group on POSIX, ``dump-request`` file on
  Windows), a short ``--grace`` period, then the whole process tree is
  killed (``killpg``/``taskkill /T``);
* the result is non-zero and keeps the FIRST failure: a pytest status that
  was already non-zero at session finish wins over the later timeout code;
* machine-readable evidence ``<evidence-dir>/supervisor-result.json`` with
  status classes ``passed``, ``tests_failed``, ``leak_detected``,
  ``startup_timeout``, ``test_timeout``, ``teardown_timeout``,
  ``session_timeout``, ``interpreter_exit_timeout``, ``runner_cancelled``
  (SIGTERM/SIGINT to the supervisor), the offending test/worker, the leak
  inventory and the collected stack dumps.

Works with pytest-xdist: workers inherit the evidence directory, register
their own stack-dump handler and live in the same process group/tree; test
events of all workers arrive through the xdist controller.

``verify`` checks the evidence of several runs (CI aggregate job).

Only the standard library is used.

Usage:
    python scripts/pytest_supervisor.py run --evidence-dir out/sup \\
        --test-timeout 900 --teardown-timeout 180 --session-timeout 180 \\
        --exit-timeout 90 --grace 10 -- python -m pytest tests/ -n auto
    python scripts/pytest_supervisor.py verify --evidence-root artifacts --expect 9
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

SUPERVISOR_DIR_ENV = "ARES_SUPERVISOR_DIR"
STRICT_ENV = "ARES_STRICT_LEAK_GUARD"
EVENTS_FILE = "events.jsonl"
DUMP_REQUEST_FILE = "dump-request"
STACK_FILE_PREFIX = "stacks-"
LEAK_REPORT_PREFIX = "leak-report-"
RESULT_FILE = "supervisor-result.json"
RESULT_SCHEMA = "pytest-supervisor-result/v1"

# Supervisor-owned exit codes (pytest itself uses 0..5).
TIMEOUT_EXIT_CODES = {
    "startup_timeout": 89,
    "test_timeout": 90,
    "teardown_timeout": 91,
    "session_timeout": 92,
    "interpreter_exit_timeout": 93,  # == tests/_session_leak_guard.EXIT_WATCHDOG_CODE
    "runner_cancelled": 94,
}
PYTEST_STATUS_NAMES = {
    1: "tests_failed",
    2: "interrupted",
    3: "internal_error",
    4: "usage_error",
    5: "no_tests_collected",
}
_STACK_EVIDENCE_LIMIT = 200_000


@dataclass
class Deadlines:
    startup: float
    test: float
    teardown: float
    session: float
    exit: float
    grace: float


@dataclass
class Breach:
    status: str
    phase: str
    elapsed_s: float
    limit_s: float
    nodeid: str | None = None
    worker: str | None = None


@dataclass
class PhaseTracker:
    """Phase state machine fed by the child's events (supervisor clock)."""

    started: float
    phase: str = "startup"
    phase_since: float = 0.0
    last_activity: float = 0.0
    inflight: dict[str, dict] = field(default_factory=dict)
    pytest_exit_status: int | None = None
    tests_failed: int | None = None
    leak_lines: list[str] = field(default_factory=list)
    strict: bool | None = None
    exit_watchdog_fired: bool = False
    events_seen: int = 0
    tests_started: int = 0
    tests_finished: int = 0

    def __post_init__(self) -> None:
        self.phase_since = self.started
        self.last_activity = self.started

    def apply(self, event: dict, now: float) -> None:
        self.events_seen += 1
        self.last_activity = now
        kind = event.get("event")
        nodeid = event.get("nodeid")
        if kind == "test_start" and nodeid:
            self._enter("running", now)
            self.tests_started += 1
            self.inflight[nodeid] = {"phase": "test", "since": now, "worker": event.get("worker")}
        elif kind == "teardown_start" and nodeid:
            entry = self.inflight.setdefault(nodeid, {"since": now})
            entry.update(phase="teardown", since=now, worker=event.get("worker") or entry.get("worker"))
        elif kind == "test_finish" and nodeid:
            self.tests_finished += 1
            self.inflight.pop(nodeid, None)
        elif kind == "session_finish_start":
            self._enter("session_finish", now, force=True)
            self.inflight.clear()
            self._record_status(event.get("exit_status"))
        elif kind == "session_finish_done":
            self._record_status(event.get("exit_status"))
            self.tests_failed = event.get("tests_failed")
            self.leak_lines = list(event.get("leak_lines") or [])
            self.strict = event.get("strict")
        elif kind == "unconfigure_done":
            self._enter("exit", now, force=True)
            self._record_status(event.get("exit_status"))
        elif kind == "exit_watchdog_fired":
            self.exit_watchdog_fired = True

    def _enter(self, phase: str, now: float, force: bool = False) -> None:
        if force or self.phase != phase:
            if self.phase != phase:
                self.phase_since = now
            self.phase = phase

    def _record_status(self, value: object) -> None:
        if isinstance(value, int):
            self.pytest_exit_status = value

    def check(self, now: float, limits: Deadlines) -> Breach | None:
        if self.phase == "startup":
            elapsed = now - self.started
            if elapsed > limits.startup:
                return Breach("startup_timeout", "startup", elapsed, limits.startup)
        elif self.phase == "running":
            for nodeid, entry in self.inflight.items():
                elapsed = now - entry["since"]
                if entry.get("phase") == "teardown":
                    if elapsed > limits.teardown:
                        return Breach("teardown_timeout", "teardown", elapsed, limits.teardown, nodeid, entry.get("worker"))
                elif elapsed > limits.test:
                    return Breach("test_timeout", "test", elapsed, limits.test, nodeid, entry.get("worker"))
            if not self.inflight:
                idle = now - self.last_activity
                if idle > limits.session:
                    return Breach("session_timeout", "between_tests", idle, limits.session)
        elif self.phase == "session_finish":
            elapsed = now - self.phase_since
            if elapsed > limits.session:
                return Breach("session_timeout", "session_finish", elapsed, limits.session)
        elif self.phase == "exit":
            elapsed = now - self.phase_since
            if elapsed > limits.exit:
                return Breach("interpreter_exit_timeout", "interpreter_exit", elapsed, limits.exit)
        return None


class EventReader:
    """Incremental reader of the JSON-lines event file (partial lines kept)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset = 0
        self.buffer = ""

    def read_new(self) -> list[dict]:
        try:
            with open(self.path, encoding="utf-8") as handle:
                handle.seek(self.offset)
                chunk = handle.read()
                self.offset = handle.tell()
        except FileNotFoundError:
            return []
        self.buffer += chunk
        *complete, self.buffer = self.buffer.split("\n")
        events = []
        for line in complete:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events


def _popen_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def request_stack_dump(child: subprocess.Popen, evidence_dir: Path) -> str:
    """Ask every pytest process of the tree for ONE stack dump."""
    if os.name == "nt":
        (evidence_dir / DUMP_REQUEST_FILE).write_text(str(time.time()), encoding="utf-8")
        return "dump-request-file"
    try:
        os.killpg(child.pid, signal.SIGUSR1)
    except (ProcessLookupError, PermissionError):
        return "process-group-gone"
    return "SIGUSR1-process-group"


def kill_process_tree(child: subprocess.Popen) -> str:
    if os.name == "nt":
        if child.poll() is None:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(child.pid)],
                capture_output=True,
                timeout=60,
                check=False,
            )
        return "taskkill-tree"
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return "process-group-gone"
    return "SIGKILL-process-group"


def _read_stack_dumps(evidence_dir: Path) -> list[dict]:
    dumps = []
    for path in sorted(evidence_dir.glob(f"{STACK_FILE_PREFIX}*.txt")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not text.strip():
            continue
        dumps.append({"file": path.name, "text": text[-_STACK_EVIDENCE_LIMIT:]})
    return dumps


def _read_leak_reports(evidence_dir: Path) -> list[dict]:
    reports = []
    for path in sorted(evidence_dir.glob(f"{LEAK_REPORT_PREFIX}*.json")):
        try:
            reports.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return reports


def classify(
    tracker: PhaseTracker,
    child_returncode: int | None,
    breach: Breach | None,
    killed_by_supervisor: bool,
) -> tuple[str, list[str], int]:
    """(primary status, all statuses, exit code); the first failure wins."""
    statuses: list[str] = []
    recorded = tracker.pytest_exit_status
    if recorded:
        name = PYTEST_STATUS_NAMES.get(recorded, f"pytest_exit_{recorded}")
        if recorded == 1 and tracker.leak_lines and not tracker.tests_failed:
            name = "leak_detected"
        statuses.append(name)
    if tracker.leak_lines and "leak_detected" not in statuses:
        statuses.append("leak_detected")
    if breach is not None:
        statuses.append(breach.status)
    elif tracker.exit_watchdog_fired:
        statuses.append("interpreter_exit_timeout")
    if (
        not killed_by_supervisor
        and child_returncode not in (None, 0)
        and not statuses
    ):
        statuses.append(PYTEST_STATUS_NAMES.get(child_returncode, f"process_exit_{child_returncode}"))

    exit_code = 0
    if recorded:
        exit_code = recorded
    elif breach is not None:
        exit_code = TIMEOUT_EXIT_CODES[breach.status]
    elif not killed_by_supervisor and child_returncode:
        exit_code = child_returncode
    elif tracker.exit_watchdog_fired:
        exit_code = TIMEOUT_EXIT_CODES["interpreter_exit_timeout"]
    if exit_code == 0 and statuses and statuses != ["leak_detected"]:
        exit_code = 1
    if exit_code == 0 and tracker.leak_lines and os.environ.get(STRICT_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        exit_code = 1
    primary = statuses[0] if statuses else "passed"
    return primary, statuses, exit_code


def run(args: argparse.Namespace) -> int:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("pytest_supervisor: no command given", file=sys.stderr)
        return 2
    evidence_dir = Path(args.evidence_dir).resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for stale in (EVENTS_FILE, DUMP_REQUEST_FILE, RESULT_FILE):
        (evidence_dir / stale).unlink(missing_ok=True)
    for pattern in (f"{STACK_FILE_PREFIX}*.txt", f"{LEAK_REPORT_PREFIX}*.json"):
        for stale in evidence_dir.glob(pattern):
            stale.unlink(missing_ok=True)

    limits = Deadlines(
        startup=args.startup_timeout,
        test=args.test_timeout,
        teardown=args.teardown_timeout,
        session=args.session_timeout,
        exit=args.exit_timeout,
        grace=args.grace,
    )
    env = dict(os.environ)
    env[SUPERVISOR_DIR_ENV] = str(evidence_dir)
    cancelled: list[str] = []

    def _cancel(signum, _frame):  # noqa: ANN001
        cancelled.append(signal.Signals(signum).name)

    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
        signum = getattr(signal, name, None)
        if signum is not None:
            try:
                signal.signal(signum, _cancel)
            except (OSError, ValueError):
                pass

    started_wall = time.time()
    started = time.monotonic()
    child = subprocess.Popen(command, env=env, **_popen_kwargs())
    tracker = PhaseTracker(started=started)
    reader = EventReader(evidence_dir / EVENTS_FILE)
    breach: Breach | None = None
    killed = False
    dump_mode = None
    kill_mode = None

    def _drain() -> None:
        for event in reader.read_new():
            tracker.apply(event, time.monotonic())

    while True:
        _drain()
        if child.poll() is not None:
            break
        now = time.monotonic()
        if cancelled:
            breach = Breach("runner_cancelled", tracker.phase, now - started, 0.0)
        else:
            breach = tracker.check(now, limits)
        if breach is not None:
            print(
                f"\n[pytest-supervisor] {breach.status} in phase {breach.phase}"
                f" nach {breach.elapsed_s:.1f} s (Frist {breach.limit_s:g} s)"
                + (f", Test {breach.nodeid}" if breach.nodeid else "")
                + (f", Worker {breach.worker}" if breach.worker else "")
                + "; Stackdump angefordert, danach Prozessbaum-Abbruch.",
                file=sys.stderr,
                flush=True,
            )
            dump_mode = request_stack_dump(child, evidence_dir)
            grace_end = time.monotonic() + limits.grace
            while time.monotonic() < grace_end and child.poll() is None:
                _drain()
                time.sleep(args.poll_interval)
            kill_mode = kill_process_tree(child)
            killed = True
            try:
                child.wait(timeout=60)
            except subprocess.TimeoutExpired:
                pass
            break
        time.sleep(args.poll_interval)

    _drain()
    if not killed and os.name != "nt":
        # Normal exit: reap orphaned processes left in the run's group.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    returncode = child.poll()
    primary, statuses, exit_code = classify(tracker, returncode, breach, killed)
    stacks = _read_stack_dumps(evidence_dir) if killed else []
    result = {
        "schema": RESULT_SCHEMA,
        "status": primary,
        "statuses": statuses,
        "exit_code": exit_code,
        "child_returncode": returncode,
        "pytest_exit_status": tracker.pytest_exit_status,
        "tests_failed": tracker.tests_failed,
        "killed_by_supervisor": killed,
        "cancel_signal": cancelled[0] if cancelled else None,
        "breach": None if breach is None else breach.__dict__,
        "phase_at_end": tracker.phase,
        "inflight_at_end": sorted(tracker.inflight),
        "tests_started": tracker.tests_started,
        "tests_finished": tracker.tests_finished,
        "events_seen": tracker.events_seen,
        "leak_lines": tracker.leak_lines,
        "leak_reports": _read_leak_reports(evidence_dir),
        "strict_leak_guard": tracker.strict,
        "exit_watchdog_fired": tracker.exit_watchdog_fired,
        "deadlines_s": limits.__dict__,
        "dump_request": dump_mode,
        "kill": kill_mode,
        "stack_dumps": stacks,
        "started_at": started_wall,
        "duration_s": round(time.monotonic() - started, 3),
        "python": sys.version.split()[0],
        "command": command,
    }
    (evidence_dir / RESULT_FILE).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if killed:
        for dump in stacks:
            print(f"\n[pytest-supervisor] {dump['file']}:\n{dump['text'][-20000:]}", file=sys.stderr)
    print(
        f"[pytest-supervisor] status={primary} statuses={statuses} exit_code={exit_code} "
        f"evidence={evidence_dir / RESULT_FILE}",
        file=sys.stderr,
        flush=True,
    )
    return exit_code


def verify(args: argparse.Namespace) -> int:
    """Every expected run left evidence, ended 0 and (strict) reported no leak."""
    root = Path(args.evidence_root)
    results = sorted(root.rglob(RESULT_FILE))
    strict = os.environ.get(STRICT_ENV, "").strip().lower() in {"1", "true", "yes", "on"}
    problems = []
    if len(results) < args.expect:
        problems.append(f"nur {len(results)} von {args.expect} Supervisor-Ergebnissen gefunden")
    for path in results:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{path}: unlesbar ({exc})")
            continue
        label = path.parent.name
        print(f"{label}: status={data.get('status')} exit_code={data.get('exit_code')} "
              f"tests={data.get('tests_finished')} leaks={len(data.get('leak_lines') or [])}")
        if data.get("exit_code") != 0 or data.get("status") not in ("passed", "leak_detected"):
            problems.append(f"{label}: status={data.get('status')} exit_code={data.get('exit_code')}")
        if strict and data.get("leak_lines"):
            problems.append(f"{label}: Leak trotz {STRICT_ENV}=1: {data['leak_lines']}")
    for problem in problems:
        print(f"FEHLER: {problem}", file=sys.stderr)
    return 1 if problems else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    run_p = sub.add_parser("run", help="pytest unter Aufsicht ausfuehren")
    run_p.add_argument("--evidence-dir", required=True)
    run_p.add_argument("--startup-timeout", type=float, default=600.0)
    run_p.add_argument("--test-timeout", type=float, default=900.0)
    run_p.add_argument("--teardown-timeout", type=float, default=180.0)
    run_p.add_argument("--session-timeout", type=float, default=180.0)
    run_p.add_argument("--exit-timeout", type=float, default=90.0)
    run_p.add_argument("--grace", type=float, default=10.0)
    run_p.add_argument("--poll-interval", type=float, default=0.2)
    run_p.add_argument("command", nargs=argparse.REMAINDER)
    verify_p = sub.add_parser("verify", help="Evidence mehrerer Laeufe pruefen")
    verify_p.add_argument("--evidence-root", required=True)
    verify_p.add_argument("--expect", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "run":
        return run(args)
    return verify(args)


if __name__ == "__main__":
    sys.exit(main())
