"""Contracts of ``tests/conftest.py`` for parallel runs (pytest-xdist).

1. Every xdist worker gets its own throwaway SQLite file. Before, all workers
   inherited the controller's ``DB_PATH`` and ran ``init_db()`` on ONE file.
2. The background-resource guard keeps working under xdist: findings of a
   worker reach the controller's summary, and strict mode turns them into a
   failed run (the worker's own exit status is not what the controller reports).
3. A serial run keeps the caller-provided ``DB_PATH`` unchanged.

Each case starts a separate pytest process on generated probe files in
``tmp_path``; the probe conftest loads the real ``tests/conftest.py`` hooks.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import _session_leak_guard as guard

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = _BACKEND_ROOT / "tests"

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


def _clean_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PYTEST_XDIST") and key not in {"PYTEST_CURRENT_TEST", guard.STRICT_ENV}
    }
    env["DB_PATH"] = str(tmp_path / "caller" / "caller.db")
    (tmp_path / "caller").mkdir(exist_ok=True)
    env[guard.WATCHDOG_ENV] = "0"
    env.update(extra)
    return env


def _write_probe(tmp_path: Path, body: str) -> Path:
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    (probe_dir / "conftest.py").write_text(_PROBE_CONFTEST, encoding="utf-8")
    (probe_dir / "test_probe.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return probe_dir


def _run(probe_dir: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(probe_dir), "-q", "-p", "no:cacheprovider", *args],
        cwd=probe_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _db_probe_body(out_file: Path) -> str:
    return f"""
    import os
    import time

    import pytest


    @pytest.mark.parametrize("i", range(6))
    def test_record_db_path(i):
        from config import settings

        time.sleep(0.2)  # give every worker a share of the items
        with open({str(out_file)!r}, "a", encoding="utf-8") as fh:
            fh.write(os.environ.get("PYTEST_XDIST_WORKER", "-") + "|" + settings.db_path + "\\n")
    """


def test_each_xdist_worker_uses_its_own_db_file(tmp_path):
    pytest.importorskip("xdist")
    out_file = tmp_path / "db_paths.txt"
    probe_dir = _write_probe(tmp_path, _db_probe_body(out_file))
    env = _clean_env(tmp_path)

    proc = _run(probe_dir, env, "-p", "xdist", "-n", "2", "--dist", "load")

    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
    rows = {tuple(line.split("|", 1)) for line in out_file.read_text(encoding="utf-8").splitlines()}
    by_worker: dict[str, set[str]] = {}
    for worker, db_path in rows:
        by_worker.setdefault(worker, set()).add(db_path)
    assert set(by_worker) == {"gw0", "gw1"}, by_worker
    paths = [next(iter(v)) for v in by_worker.values()]
    assert all(len(v) == 1 for v in by_worker.values()), by_worker
    assert len(set(paths)) == 2, "workers share one DB file"
    caller_db = Path(env["DB_PATH"]).resolve()
    for raw in paths:
        resolved = Path(raw).resolve()
        assert resolved != caller_db
        assert resolved.parent.parent == caller_db.parent  # created next to the caller's throwaway path
        assert resolved != (Path.home() / "ares" / "ares.db").resolve()


def test_serial_run_keeps_the_callers_db_path(tmp_path):
    out_file = tmp_path / "db_paths.txt"
    probe_dir = _write_probe(tmp_path, _db_probe_body(out_file))
    env = _clean_env(tmp_path)

    proc = _run(probe_dir, env, "-p", "no:xdist")

    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
    rows = set(out_file.read_text(encoding="utf-8").splitlines())
    assert rows == {f"-|{env['DB_PATH']}"}


_LEAK_PROBE = """
import threading
import time


def test_leaves_a_non_daemon_thread_behind():
    threading.Thread(target=time.sleep, args=(3,), name="probe-leak", daemon=False).start()
"""


def test_worker_leak_findings_reach_the_controller_and_fail_strict_runs(tmp_path):
    pytest.importorskip("xdist")
    probe_dir = _write_probe(tmp_path, _LEAK_PROBE)

    relaxed = _run(probe_dir, _clean_env(tmp_path), "-p", "xdist", "-n", "1")
    assert relaxed.returncode == 0, relaxed.stdout[-4000:] + relaxed.stderr[-2000:]
    assert "[gw0]" in relaxed.stdout and "probe-leak" in relaxed.stdout, relaxed.stdout[-4000:]

    strict = _run(probe_dir, _clean_env(tmp_path, **{guard.STRICT_ENV: "1"}), "-p", "xdist", "-n", "1")
    assert strict.returncode == 1, strict.stdout[-4000:] + strict.stderr[-2000:]
    assert "probe-leak" in strict.stdout
