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

if not os.environ.get("DB_PATH") or is_live_db_path(os.environ["DB_PATH"]):
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
