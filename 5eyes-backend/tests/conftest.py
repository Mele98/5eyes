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


def pytest_sessionstart(session):  # noqa: D103
    from config import settings

    if Path(settings.db_path).expanduser().resolve() == _LIVE_DB:
        import pytest

        pytest.exit(
            "Test-Session wuerde die LIVE-Datenbank ~/5eyes/5eyes.db verwenden -- abgebrochen.",
            returncode=3,
        )
