"""Bounded termination of pytest runs (TEST-TEARDOWN-HANG-001).

Contracts:

1. Every blocking CI job that executes the backend suite runs it under the
   external supervisor with ``ARES_STRICT_LEAK_GUARD=1``; the aggregate
   job re-checks the evidence strictly. The GitHub job timeout is only the
   emergency brake above the supervisor deadlines.
2. The in-process exit watchdog dumps ONCE and terminates a process stuck in
   interpreter shutdown non-zero, keeping an already failed pytest status.
3. The supervisor bounds test body, fixture teardown, ``pytest_sessionfinish``
   and interpreter exit separately -- serially and under pytest-xdist --,
   dumps stacks of the stuck process, kills the whole tree non-zero, writes
   JSON evidence and never overrides the first failure.
4. Unsupported Python runtimes are rejected before collection.

The first two tests are the audit reproducer of the PR #661 closure review,
adopted without ``xfail`` (backend/repo paths are located structurally; the
CI check follows the sharded job layout).

Each supervisor case starts a separate supervisor + pytest process on probe
files in ``tmp_path``; the probe conftest loads the real ``tests/conftest.py``
hooks. Hanging probes are always killed by the supervisor (and, as a last
resort, by the ``subprocess`` timeout of this test).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
import yaml

import _session_leak_guard as guard
import _session_supervision as supervision

_TESTS_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _TESTS_DIR.parent


def _repository_root() -> Path:
    """Nearest ancestor holding both the CI workflow and the supervisor script."""
    for candidate in _BACKEND_ROOT.parents:
        if (candidate / ".github" / "workflows" / "test.yml").is_file() and (
            candidate / "scripts" / "pytest_supervisor.py"
        ).is_file():
            return candidate
    raise AssertionError(f"repository root above {_BACKEND_ROOT} not found")


_REPO_ROOT = _repository_root()
_SUPERVISOR = _REPO_ROOT / "scripts" / "pytest_supervisor.py"
sys.path.insert(0, str(_SUPERVISOR.parent))
import pytest_supervisor as sup  # noqa: E402

sys.path.remove(str(_SUPERVISOR.parent))


# --- 1. CI contract -----------------------------------------------------------


def _workflow() -> dict:
    return yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8"))


def _workflow_text() -> str:
    return (_REPO_ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")


def _suite_steps(job: dict) -> list[str]:
    """``run`` scripts of a job that execute backend tests (not just collect)."""
    runs = []
    for step in job.get("steps", []):
        script = step.get("run") or ""
        if "pytest" in script and "tests/" in script and "--collect-only" not in script:
            runs.append(script)
    return runs


def test_blocking_backend_ci_enables_strict_leak_guard() -> None:
    """Detected live resources must make the blocking correctness job red."""
    # Original audit gate: the aggregate "Backend Tests" job section.
    workflow_text = _workflow_text()
    backend_job = workflow_text.split("\n  coverage:", 1)[0].split("\n  pytest:", 1)[1]
    assert "ARES_STRICT_LEAK_GUARD" in backend_job, (
        "the blocking pytest job never opts into the guard's failing mode"
    )

    # Sharded layout: every blocking job that runs the suite sets strict mode
    # and runs pytest under the external supervisor.
    jobs = _workflow()["jobs"]
    blocking_suite_jobs = {
        name: job
        for name, job in jobs.items()
        if _suite_steps(job) and not job.get("continue-on-error") and name not in {"postgres-rls"}
    }
    assert {"backend-test-shard", "backend-test-wallclock"} <= set(blocking_suite_jobs), blocking_suite_jobs.keys()
    for name, job in blocking_suite_jobs.items():
        assert str(job.get("env", {}).get(guard.STRICT_ENV)) == "1", name
        for script in _suite_steps(job):
            assert "pytest_supervisor.py run" in script, (name, script)
            assert "--evidence-dir" in script, (name, script)

    aggregate = jobs["pytest"]
    assert str(aggregate.get("env", {}).get(guard.STRICT_ENV)) == "1"
    verify_steps = [s for s in aggregate["steps"] if "pytest_supervisor.py verify" in (s.get("run") or "")]
    assert verify_steps and verify_steps[0].get("if") == "always()"


def test_github_job_timeout_is_only_the_emergency_brake() -> None:
    """Supervisor deadlines (sum of the worst phases) stay below the job timeout."""
    jobs = _workflow()["jobs"]
    for name in ("backend-test-shard", "backend-test-wallclock"):
        job = jobs[name]
        (script,) = _suite_steps(job)
        flags = dict(
            (key.lstrip("-"), float(value))
            for key, value in zip(script.split()[:-1], script.split()[1:])
            if key.startswith("--") and key.endswith("timeout") or key == "--grace"
        )
        worst_single_phase = max(flags[k] for k in flags if k.endswith("timeout")) + flags["grace"]
        assert worst_single_phase < job["timeout-minutes"] * 60, (name, flags)


# --- 2. in-process exit watchdog ---------------------------------------------


def _watchdog_child(exit_status: str = "None", seconds: str = "0.15") -> subprocess.CompletedProcess:
    code = textwrap.dedent(
        f"""
        import sys
        import threading
        sys.path.insert(0, {str(_TESTS_DIR)!r})
        import _session_leak_guard as guard
        blocker = threading.Event()
        threading.Thread(
            target=blocker.wait,
            name="audit-intentional-nondaemon",
            daemon=False,
        ).start()
        assert guard.arm_exit_watchdog(exit_status={exit_status})
        """
    )
    env = dict(os.environ)
    env[guard.WATCHDOG_ENV] = seconds
    child = subprocess.Popen(
        [sys.executable, "-B", "-c", code],
        cwd=_BACKEND_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = child.communicate(timeout=0.9 if seconds == "0.15" else 30)
        terminated = True
    except subprocess.TimeoutExpired:
        terminated = False
        child.kill()
        stdout, stderr = child.communicate(timeout=5)
    assert terminated, (
        "watchdog emitted diagnostics but left the process alive; "
        f"returncode={child.returncode}, stdout={stdout!r}, stderr={stderr[-1200:]!r}"
    )
    return subprocess.CompletedProcess(child.args, child.returncode, stdout, stderr)


def test_exit_watchdog_bounds_a_non_daemon_shutdown_hang() -> None:
    """A post-pytest hang must dump once and terminate non-zero in bounded time."""
    proc = _watchdog_child()
    assert proc.returncode not in (None, 0), (proc.stdout, proc.stderr)
    assert proc.returncode == guard.EXIT_WATCHDOG_CODE == sup.TIMEOUT_EXIT_CODES["interpreter_exit_timeout"]
    assert proc.stderr.count("[exit-watchdog]") == 1, proc.stderr
    assert "audit-intentional-nondaemon" in proc.stderr or "wait" in proc.stderr, proc.stderr


def test_exit_watchdog_keeps_an_already_failed_status() -> None:
    proc = _watchdog_child(exit_status="1")
    assert proc.returncode == 1, proc.stderr


def test_exit_watchdog_never_maps_to_zero() -> None:
    assert guard.watchdog_exit_code(0) == guard.EXIT_WATCHDOG_CODE
    assert guard.watchdog_exit_code(None) == guard.EXIT_WATCHDOG_CODE
    assert guard.watchdog_exit_code(pytest.ExitCode.TESTS_FAILED) == 1
    assert guard.watchdog_exit_code(3) == 3


# --- 3. external supervisor ----------------------------------------------------

_PROBE_CONFTEST = textwrap.dedent(
    f"""
    import importlib.util
    import sys

    for _p in ({str(_BACKEND_ROOT)!r}, {str(_TESTS_DIR)!r}):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    _spec = importlib.util.spec_from_file_location(
        "_probe_real_tests_conftest", {str(_TESTS_DIR / "conftest.py")!r}
    )
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    globals().update({{k: v for k, v in vars(_mod).items() if k.startswith("pytest_")}})
    """
)

# Generous deadlines for every phase a case does NOT target.
_RELAXED = {
    "--startup-timeout": "240",
    "--test-timeout": "240",
    "--teardown-timeout": "240",
    "--session-timeout": "240",
    "--exit-timeout": "240",
    "--grace": "3",
}


def _probe(tmp_path: Path, body: str, extra_files: dict[str, str] | None = None) -> Path:
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    (probe_dir / "conftest.py").write_text(_PROBE_CONFTEST, encoding="utf-8")
    (probe_dir / "test_probe.py").write_text(textwrap.dedent(body), encoding="utf-8")
    for name, text in (extra_files or {}).items():
        (probe_dir / name).write_text(textwrap.dedent(text), encoding="utf-8")
    return probe_dir


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PYTEST_XDIST")
        and key not in {"PYTEST_CURRENT_TEST", guard.STRICT_ENV, supervision.SUPERVISOR_DIR_ENV, "PYTEST_ADDOPTS"}
    }
    caller = tmp_path / "caller"
    caller.mkdir(exist_ok=True)
    env["DB_PATH"] = str(caller / "caller.db")
    env[guard.WATCHDOG_ENV] = "0"  # isolate the supervisor's own exit deadline
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path / "probe"), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    env.update(extra)
    return env


def _supervise(
    tmp_path: Path,
    probe_dir: Path,
    env: dict[str, str],
    *pytest_args: str,
    timeout: float = 240,
    **deadlines: str,
) -> tuple[subprocess.CompletedProcess, dict]:
    evidence = tmp_path / "evidence"
    limits = dict(_RELAXED)
    limits.update({f"--{k.replace('_', '-')}": v for k, v in deadlines.items()})
    cmd = [sys.executable, str(_SUPERVISOR), "run", "--evidence-dir", str(evidence), "--poll-interval", "0.1"]
    for key, value in limits.items():
        cmd += [key, value]
    cmd += ["--", sys.executable, "-m", "pytest", str(probe_dir), "-q", "-p", "no:cacheprovider", *pytest_args]
    proc = subprocess.run(cmd, cwd=probe_dir, env=env, capture_output=True, text=True, timeout=timeout)
    result_path = evidence / sup.RESULT_FILE
    assert result_path.is_file(), proc.stdout[-4000:] + proc.stderr[-4000:]
    return proc, json.loads(result_path.read_text(encoding="utf-8"))


def _diag(proc: subprocess.CompletedProcess, result: dict) -> str:
    slim = {k: v for k, v in result.items() if k != "stack_dumps"}
    return json.dumps(slim, indent=1)[-3000:] + "\n--stdout--\n" + proc.stdout[-3000:] + "\n--stderr--\n" + proc.stderr[-3000:]


def _all_stacks(result: dict) -> str:
    return "\n".join(d["text"] for d in result["stack_dumps"])


def test_short_green_run_terminates_without_dump_and_keeps_exit_code(tmp_path):
    probe_dir = _probe(tmp_path, "def test_ok():\n    assert True\n")
    proc, result = _supervise(tmp_path, probe_dir, _env(tmp_path), "-p", "no:xdist")
    assert proc.returncode == 0, _diag(proc, result)
    assert result["status"] == "passed" and result["statuses"] == []
    assert result["killed_by_supervisor"] is False and result["stack_dumps"] == []
    assert result["tests_started"] == result["tests_finished"] == 1
    assert result["pytest_exit_status"] == 0 and result["phase_at_end"] == "exit"


def test_failed_run_keeps_pytest_status(tmp_path):
    probe_dir = _probe(tmp_path, "def test_bad():\n    assert False\n")
    proc, result = _supervise(tmp_path, probe_dir, _env(tmp_path), "-p", "no:xdist")
    assert proc.returncode == 1, _diag(proc, result)
    assert result["status"] == "tests_failed" and result["killed_by_supervisor"] is False


_HANGING_BODY = """
import threading


def test_quick():
    assert True


def test_hangs_in_body():
    threading.Event().wait()
"""


@pytest.mark.parametrize("xdist_args", [("-p", "no:xdist"), ("-p", "xdist", "-n", "2")], ids=["serial", "xdist"])
def test_hang_in_test_body_is_bounded_with_stack_evidence(tmp_path, xdist_args):
    if "xdist" in xdist_args and "-n" in xdist_args:
        pytest.importorskip("xdist")
    probe_dir = _probe(tmp_path, _HANGING_BODY)
    started = time.monotonic()
    proc, result = _supervise(tmp_path, probe_dir, _env(tmp_path), *xdist_args, test_timeout="3", grace="3")
    elapsed = time.monotonic() - started
    assert proc.returncode == sup.TIMEOUT_EXIT_CODES["test_timeout"], _diag(proc, result)
    assert result["status"] == "test_timeout" and result["killed_by_supervisor"] is True
    assert result["breach"]["nodeid"].endswith("test_hangs_in_body"), _diag(proc, result)
    stacks = _all_stacks(result)
    assert "test_hangs_in_body" in stacks, _diag(proc, result)
    assert elapsed < 200, elapsed


def test_hang_in_fixture_teardown_is_a_separate_bounded_phase(tmp_path):
    body = """
    import threading
    import pytest


    @pytest.fixture
    def stuck_on_teardown():
        yield
        threading.Event().wait()


    def test_uses_fixture(stuck_on_teardown):
        assert True
    """
    probe_dir = _probe(tmp_path, body)
    proc, result = _supervise(tmp_path, probe_dir, _env(tmp_path), "-p", "xdist", "-n", "1", teardown_timeout="3")
    assert proc.returncode == sup.TIMEOUT_EXIT_CODES["teardown_timeout"], _diag(proc, result)
    assert result["status"] == "teardown_timeout"
    assert result["breach"]["phase"] == "teardown"
    assert "stuck_on_teardown" in _all_stacks(result), _diag(proc, result)


def test_hang_in_sessionfinish_is_bounded(tmp_path):
    plugin = """
    import threading
    import pytest


    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(session, exitstatus):
        threading.Event().wait()
    """
    probe_dir = _probe(tmp_path, "def test_ok():\n    assert True\n", {"probe_hang_plugin.py": plugin})
    proc, result = _supervise(
        tmp_path, probe_dir, _env(tmp_path), "-p", "no:xdist", "-p", "probe_hang_plugin", session_timeout="3"
    )
    assert proc.returncode == sup.TIMEOUT_EXIT_CODES["session_timeout"], _diag(proc, result)
    assert result["status"] == "session_timeout" and result["breach"]["phase"] == "session_finish"
    assert "pytest_sessionfinish" in _all_stacks(result), _diag(proc, result)


_EXIT_HANG_BODY = """
import threading

_blocker = threading.Event()


def test_leaks_non_daemon_thread():
    threading.Thread(target=_blocker.wait, name="probe-exit-blocker", daemon=False).start()
{extra}
"""


def test_interpreter_exit_hang_is_bounded_non_zero(tmp_path):
    probe_dir = _probe(tmp_path, _EXIT_HANG_BODY.format(extra=""))
    proc, result = _supervise(tmp_path, probe_dir, _env(tmp_path), "-p", "no:xdist", exit_timeout="3")
    assert proc.returncode == sup.TIMEOUT_EXIT_CODES["interpreter_exit_timeout"], _diag(proc, result)
    assert result["statuses"][-1] == "interpreter_exit_timeout"
    assert "probe-exit-blocker" in " ".join(result["leak_lines"]), _diag(proc, result)
    # The leak inventory was persisted at sessionfinish, before the hang.
    assert any("probe-exit-blocker" in " ".join(r["threads"]) for r in result["leak_reports"])


def test_failed_run_with_exit_hang_stays_failed(tmp_path):
    probe_dir = _probe(tmp_path, _EXIT_HANG_BODY.format(extra="\n\ndef test_bad():\n    assert False\n"))
    proc, result = _supervise(tmp_path, probe_dir, _env(tmp_path), "-p", "no:xdist", exit_timeout="3")
    assert proc.returncode == 1, _diag(proc, result)
    assert result["status"] == "tests_failed"
    assert "interpreter_exit_timeout" in result["statuses"]


def test_in_process_watchdog_reports_through_supervisor(tmp_path):
    probe_dir = _probe(tmp_path, _EXIT_HANG_BODY.format(extra=""))
    env = _env(tmp_path, **{guard.WATCHDOG_ENV: "2"})
    proc, result = _supervise(tmp_path, probe_dir, env, "-p", "no:xdist", exit_timeout="120")
    assert proc.returncode == guard.EXIT_WATCHDOG_CODE, _diag(proc, result)
    assert result["exit_watchdog_fired"] is True and result["killed_by_supervisor"] is False
    assert proc.stderr.count("[exit-watchdog]") == 1, proc.stderr[-3000:]


def test_strict_leaks_give_machine_readable_evidence_and_red_status(tmp_path):
    body = """
    import threading
    import time


    def test_leaks_two_threads():
        for name in ("probe-leak-a", "probe-leak-b"):
            threading.Thread(target=time.sleep, args=(2,), name=name, daemon=False).start()
    """
    probe_dir = _probe(tmp_path, body)
    env = _env(tmp_path, **{guard.STRICT_ENV: "1"})
    proc, result = _supervise(tmp_path, probe_dir, env, "-p", "xdist", "-n", "1")
    assert proc.returncode == 1, _diag(proc, result)
    assert result["status"] == "leak_detected", _diag(proc, result)
    joined = " ".join(result["leak_lines"])
    assert "probe-leak-a" in joined and "probe-leak-b" in joined
    assert result["strict_leak_guard"] is True
    assert result["leak_reports"] and any(r["leak_detected"] for r in result["leak_reports"])
    assert result["stack_dumps"] == []  # no timeout -> no dump flood


@pytest.mark.skipif(os.name == "nt", reason="SIGTERM to a process group is POSIX-only (CI runs Linux)")
def test_cancelled_runner_kills_tree_and_reports_cancel(tmp_path):
    probe_dir = _probe(tmp_path, _HANGING_BODY)
    evidence = tmp_path / "evidence"
    cmd = [sys.executable, str(_SUPERVISOR), "run", "--evidence-dir", str(evidence), "--grace", "2", "--",
           sys.executable, "-m", "pytest", str(probe_dir), "-q", "-p", "no:cacheprovider", "-p", "no:xdist"]
    proc = subprocess.Popen(cmd, cwd=probe_dir, env=_env(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 120
        events = evidence / sup.EVENTS_FILE
        while time.monotonic() < deadline:
            if events.is_file() and "test_hangs_in_body" in events.read_text(encoding="utf-8"):
                break
            time.sleep(0.2)
        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    result = json.loads((evidence / sup.RESULT_FILE).read_text(encoding="utf-8"))
    assert proc.returncode == sup.TIMEOUT_EXIT_CODES["runner_cancelled"], result
    assert result["status"] == "runner_cancelled" and result["cancel_signal"] == "SIGTERM"


def test_classification_keeps_the_first_failure():
    tracker = sup.PhaseTracker(started=0.0)
    tracker.apply({"event": "session_finish_done", "exit_status": 1, "tests_failed": 2, "leak_lines": []}, 1.0)
    breach = sup.Breach("interpreter_exit_timeout", "interpreter_exit", 5.0, 3.0)
    assert sup.classify(tracker, -9, breach, True) == ("tests_failed", ["tests_failed", "interpreter_exit_timeout"], 1)

    green = sup.PhaseTracker(started=0.0)
    green.apply({"event": "session_finish_done", "exit_status": 0, "tests_failed": 0, "leak_lines": []}, 1.0)
    assert sup.classify(green, -9, breach, True) == ("interpreter_exit_timeout", ["interpreter_exit_timeout"], 93)
    assert sup.classify(green, 0, None, False) == ("passed", [], 0)


def test_verify_requires_all_evidence_green(tmp_path, monkeypatch):
    monkeypatch.setenv(guard.STRICT_ENV, "1")
    for name, payload in {
        "a": {"status": "passed", "exit_code": 0, "leak_lines": []},
        "b": {"status": "passed", "exit_code": 0, "leak_lines": []},
    }.items():
        (tmp_path / name).mkdir()
        (tmp_path / name / sup.RESULT_FILE).write_text(json.dumps(payload), encoding="utf-8")
    assert sup.main(["verify", "--evidence-root", str(tmp_path), "--expect", "2"]) == 0
    assert sup.main(["verify", "--evidence-root", str(tmp_path), "--expect", "3"]) == 1
    (tmp_path / "b" / sup.RESULT_FILE).write_text(
        json.dumps({"status": "leak_detected", "exit_code": 1, "leak_lines": ["x"]}), encoding="utf-8"
    )
    assert sup.main(["verify", "--evidence-root", str(tmp_path), "--expect", "2"]) == 1


# --- 4. Python support matrix ------------------------------------------------


def test_python_support_matrix_matches_ci_and_rejects_others(monkeypatch):
    monkeypatch.delenv(supervision.ALLOW_UNSUPPORTED_PYTHON_ENV, raising=False)
    ci_versions = {
        str(v)
        for job in _workflow()["jobs"].values()
        for step in job.get("steps", [])
        for v in [(step.get("with") or {}).get("python-version")]
        if v and "matrix" not in str(v)
    }
    ci_versions |= {str(v) for v in _workflow()["jobs"]["pytest"]["strategy"]["matrix"]["python-version"]}
    for version in ci_versions:
        major, minor = (int(x) for x in version.split("."))
        assert supervision.unsupported_python_message((major, minor)) is None, version
    message = supervision.unsupported_python_message((3, 14))
    assert message and "3.14" in message and "3.12" in message
    monkeypatch.setenv(supervision.ALLOW_UNSUPPORTED_PYTHON_ENV, "1")
    assert supervision.unsupported_python_message((3, 14)) is None


def test_supervisor_switch_names_use_product_prefix_and_agree() -> None:
    """Supervisor und Prozess-Seite lesen dieselben ARES_*-Schalter."""
    assert sup.STRICT_ENV == guard.STRICT_ENV == "ARES_STRICT_LEAK_GUARD"
    assert sup.SUPERVISOR_DIR_ENV == supervision.SUPERVISOR_DIR_ENV == "ARES_SUPERVISOR_DIR"
    assert supervision.ALLOW_UNSUPPORTED_PYTHON_ENV == "ARES_ALLOW_UNSUPPORTED_PYTHON"
    for job_name, job in _workflow()["jobs"].items():
        for key in (job.get("env") or {}):
            assert not key.endswith("_STRICT_LEAK_GUARD") or key == sup.STRICT_ENV, (job_name, key)
