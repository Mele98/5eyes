"""Test-session isolation from the live database (Incident 2026-10-15).

Many tests start the FastAPI app via ``TestClient(app)``; its lifespan calls
``init_db()`` on ``settings.db_path``, whose default is the LIVE desktop
database ``~/5eyes/5eyes.db``. Parallel test runs therefore executed startup
migrations against real client data and left an interrupted table rebuild
(ANSWERS-MIGRATION-IDEMPOTENT-001).

This conftest is imported by pytest before any test module, i.e. before
``config`` builds its settings: every session gets its own throwaway DB path.
If the live path is reached anyway, the session aborts instead of touching it.

The live path is NOT a literal here: it comes from
``core.db_location.default_db_path()`` -- the same function that supplies the
``config`` default -- and is compared via ``core.db_location.is_live_db_path``
(resolve + normcase + samefile, i.e. symlinks, junctions, hardlinks and
Windows case variants are caught as well). A later rename of the data path
therefore cannot silently disarm this guard.

Parallel runs (pytest-xdist): the controller imports this conftest first and
its ``DB_PATH`` is inherited by every worker process. Without the worker
branch below all workers would share ONE SQLite file and run ``init_db()``
on it concurrently (lock conflicts, migration races). Each worker
(``PYTEST_XDIST_WORKER`` = ``gw0``, ``gw1`` ...) therefore gets its own fresh
temporary directory and DB file. A caller-provided (non-live) ``DB_PATH`` only
decides where those directories are created. A serial run never takes the
worker branch and behaves exactly as before.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from core.db_location import default_db_path, is_live_db_path, sqlite_url_file  # noqa: E402

_XDIST_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "")


def _worker_db_path(worker: str, inherited: str | None) -> str:
    """Fresh, worker-private throwaway DB path (never the live DB)."""
    base_dir = None
    if inherited and not is_live_db_path(inherited):
        parent = Path(inherited).expanduser().resolve().parent
        if parent.is_dir():
            base_dir = str(parent)
    worker_dir = tempfile.mkdtemp(prefix=f"tests-{worker}-", dir=base_dir)
    return str(Path(worker_dir) / "test.db")


if _XDIST_WORKER:
    os.environ["DB_PATH"] = _worker_db_path(_XDIST_WORKER, os.environ.get("DB_PATH"))
elif not os.environ.get("DB_PATH") or is_live_db_path(os.environ["DB_PATH"]):
    _session_dir = tempfile.mkdtemp(prefix="5eyes-tests-")
    os.environ["DB_PATH"] = str(Path(_session_dir) / "5eyes-test.db")


def live_db_violation(db_path, database_url=None):
    """Name of the setting that points at the live DB, else ``None``."""
    if is_live_db_path(db_path):
        return "DB_PATH"
    url_file = sqlite_url_file(database_url)
    if url_file is not None and is_live_db_path(url_file):
        return "DATABASE_URL"
    return None


def _register_all_orm_models() -> None:
    """Import every module of the ``models`` package once per test process.

    ``Base.metadata`` only knows the tables of model modules that happen to be
    imported. Test files that call ``Base.metadata.create_all()`` without
    importing e.g. ``models.tenant`` were green only when an earlier file in
    the same process had imported it (``NoReferencedTableError`` on
    ``tenants`` when run alone, under sharding or with ``--dist loadfile``).
    Registering all models up front makes every file independent of the
    collection order. Test-only; the application import path is unchanged.
    """
    import importlib
    import pkgutil

    import models

    for module_info in sorted(pkgutil.iter_modules(models.__path__), key=lambda m: m.name):
        importlib.import_module(f"{models.__name__}.{module_info.name}")


def pytest_sessionstart(session):  # noqa: D103
    from config import settings

    violation = live_db_violation(settings.db_path, getattr(settings, "database_url", None))
    if violation:
        import pytest

        pytest.exit(
            f"Test-Session wuerde die LIVE-Datenbank {default_db_path()} verwenden "
            f"({violation}) -- abgebrochen.",
            returncode=3,
        )

    _register_all_orm_models()


# --- Hintergrund-Ressourcen-Guard (Teardown-Hang-Befund 2026-10-20) --------
# Siehe tests/_session_leak_guard.py. Meldet nach dem Lauf noch laufende
# nicht-daemonische Threads und Produkt-Scheduler; ARES_STRICT_LEAK_GUARD=1
# macht daraus einen roten Lauf. Ein Exit-Watchdog dumpt alle Thread-Stacks,
# falls der Prozess pytest um ARES_PYTEST_EXIT_WATCHDOG_S (Default 60 s)
# ueberlebt.
import pytest as _pytest

_LEAK_REPORT_KEY = _pytest.StashKey[object]()


_WORKER_LEAK_LINES_KEY = _pytest.StashKey[list]()
# Key in xdist's ``workeroutput`` channel (worker -> controller).
_WORKEROUTPUT_LEAK_KEY = "session_leak_guard_lines"


@_pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):  # noqa: D103
    import _session_leak_guard as guard

    report = guard.collect()
    session.config.stash[_LEAK_REPORT_KEY] = report
    workeroutput = getattr(session.config, "workeroutput", None)
    if workeroutput is not None:
        # xdist worker: the controller prints the summary and owns the exit
        # status, so the findings travel back over the workeroutput channel.
        workeroutput[_WORKEROUTPUT_LEAK_KEY] = report.lines()
    lines = report.lines() + session.config.stash.get(_WORKER_LEAK_LINES_KEY, [])
    if lines and guard.strict_enabled() and session.exitstatus == 0:
        session.exitstatus = _pytest.ExitCode.TESTS_FAILED


@_pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error):  # noqa: D103  (xdist controller only)
    worker_lines = getattr(node, "workeroutput", {}).get(_WORKEROUTPUT_LEAK_KEY) or []
    if not worker_lines:
        return
    worker_id = getattr(node, "gateway", None)
    worker_id = getattr(worker_id, "id", "worker")
    collected = node.config.stash.setdefault(_WORKER_LEAK_LINES_KEY, [])
    collected.extend(f"[{worker_id}] {line}" for line in worker_lines)


def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: D103
    import _session_leak_guard as guard

    report = config.stash.get(_LEAK_REPORT_KEY, None)
    lines = [] if report is None else report.lines()
    lines += config.stash.get(_WORKER_LEAK_LINES_KEY, [])
    if not lines:
        return
    terminalreporter.section("Hintergrund-Ressourcen nach Testende", sep="-", yellow=True)
    for line in lines:
        terminalreporter.line(line)
    hint = (
        f"{guard.STRICT_ENV}=1 aktiv: Lauf als fehlgeschlagen gewertet."
        if guard.strict_enabled()
        else "Diese Threads halten den Prozess am Ende am Leben (Interpreter joint sie)."
    )
    terminalreporter.line(hint)


@_pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):  # noqa: D103
    import _session_leak_guard as guard

    guard.arm_exit_watchdog()
