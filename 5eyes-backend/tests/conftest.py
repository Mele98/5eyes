"""Test-session isolation from the live database (Incident 2026-10-15).

Many tests start the FastAPI app via ``TestClient(app)``; its lifespan calls
``init_db()`` on ``settings.db_path``, whose default is the LIVE desktop
database ``~/5eyes/5eyes.db``. Parallel test runs therefore executed startup
migrations against real client data and left an interrupted table rebuild
(ANSWERS-MIGRATION-IDEMPOTENT-001).

This conftest is imported by pytest before any test module, i.e. before
``config`` builds its settings: every session gets its own throwaway DB path.
If the live path is reached anyway, the session aborts instead of touching it.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_LIVE_DB = (Path.home() / "5eyes" / "5eyes.db").resolve()

if not os.environ.get("DB_PATH") or Path(os.environ["DB_PATH"]).expanduser().resolve() == _LIVE_DB:
    _session_dir = tempfile.mkdtemp(prefix="5eyes-tests-")
    os.environ["DB_PATH"] = str(Path(_session_dir) / "5eyes-test.db")


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

    if Path(settings.db_path).expanduser().resolve() == _LIVE_DB:
        import pytest

        pytest.exit(
            "Test-Session wuerde die LIVE-Datenbank ~/5eyes/5eyes.db verwenden -- abgebrochen.",
            returncode=3,
        )

    _register_all_orm_models()


# --- Hintergrund-Ressourcen-Guard (Teardown-Hang-Befund 2026-10-20) --------
# Siehe tests/_session_leak_guard.py. Meldet nach dem Lauf noch laufende
# nicht-daemonische Threads und Produkt-Scheduler; FIVEEYES_STRICT_LEAK_GUARD=1
# macht daraus einen roten Lauf. Ein Exit-Watchdog dumpt alle Thread-Stacks,
# falls der Prozess pytest um FIVEEYES_PYTEST_EXIT_WATCHDOG_S (Default 60 s)
# ueberlebt.
import pytest as _pytest

_LEAK_REPORT_KEY = _pytest.StashKey[object]()


@_pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):  # noqa: D103
    import _session_leak_guard as guard

    report = guard.collect()
    session.config.stash[_LEAK_REPORT_KEY] = report
    if not report.empty and guard.strict_enabled() and session.exitstatus == 0:
        session.exitstatus = _pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: D103
    import _session_leak_guard as guard

    report = config.stash.get(_LEAK_REPORT_KEY, None)
    if report is None or report.empty:
        return
    terminalreporter.section("Hintergrund-Ressourcen nach Testende", sep="-", yellow=True)
    for line in report.lines():
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
