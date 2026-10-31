"""Frische Installation fuer das Abnahmenetz (G4-G6).

Eine neue SQLite-Datei entsteht in einem eigenen Python-Prozess ueber den
echten Boot-Pfad (``init_db`` wie ``main.lifespan`` mit ``DB_PATH`` auf die
neue Datei) plus die Referenzdaten-Seeds, die beim Start bzw. beim ersten
CH-Engine-Lauf entstehen (Tax-Parameter, Policy/Hausmatrix/Bausteine/CMA,
CH-Produktkatalog). Der eigene Prozess ist noetig, weil einige
Migrationsschritte die beim Import gebundene Engine als Default-Argument
tragen; ein Umbiegen von ``database.engine`` im Testprozess wuerde sie an der
neuen Datei vorbeifuehren. Die Datei liegt im ``tmp_path`` des Tests.
"""
from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ADVISOR_ID = "acceptance-advisor"
FIXED_NOW = "2026-01-15T09:00:00.000Z"

_BOOT_SCRIPT = """
import main  # registriert alle ORM-Modelle
from database import SessionLocal, init_db
from models.users import User
from services.portfolio_engine import ensure_default_products, ensure_runtime_reference_data
from services.tax.parameters import seed_default_tax_parameter_sets

init_db()
with SessionLocal() as session:
    # Erster Berater der Installation; die Engine-Seeds tragen seine ID
    # (created_by), wie beim ersten echten CH-Lauf.
    session.add(User(
        id={advisor!r}, username={advisor!r}, password_hash="h",
        full_name="Berater Abnahme", role="advisor", is_active=1,
        tenant_id="main", created_at={now!r}, updated_at={now!r},
    ))
    session.commit()
with SessionLocal() as session:
    seed_default_tax_parameter_sets(session)
    session.commit()
with SessionLocal() as session:
    ensure_runtime_reference_data(session, {advisor!r}, "CH")
    session.commit()
with SessionLocal() as session:
    ensure_default_products(session, "CH")
    session.commit()
"""


def build_fresh_installation(db_file: Path) -> None:
    from core.db_location import is_live_db_path

    assert not is_live_db_path(db_file), "Abnahmenetz darf nie die Live-DB beschreiben"
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "PYTEST_XDIST_WORKER")}
    env["DB_PATH"] = str(db_file)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(BACKEND_ROOT), env.get("PYTHONPATH", "")]))
    proc = subprocess.run(
        [sys.executable, "-c", _BOOT_SCRIPT.format(advisor=ADVISOR_ID, now=FIXED_NOW)],
        cwd=str(BACKEND_ROOT), env=env, capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, proc.stderr[-4000:]


@contextmanager
def fresh_installation(db_file: Path) -> Iterator[tuple[Engine, sessionmaker]]:
    from database import attach_sqlite_pragmas

    build_fresh_installation(db_file)
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    attach_sqlite_pragmas(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    try:
        yield engine, factory
    finally:
        engine.dispose()


@contextmanager
def advisory_scenario(db_file: Path):
    """Frische Installation plus Berater, Kunde und drei Anlageberatungs-Mandate,
    angesprochen ueber die echte App (``TestClient``).

    Ein FZK-Mandat laesst sich in einer echten Installation nicht anlegen
    (CHECK-Constraint auf ``mandates.mandate_type``); der FZK-Deckel ist
    deshalb nur in der Scoring-Tabelle (G2) abgedeckt."""
    from contextlib import asynccontextmanager

    from fastapi.testclient import TestClient

    from database import get_db
    from main import app
    from models.users import User
    from services.auth import get_current_user

    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    with fresh_installation(db_file) as (engine, factory):
        with factory() as session:
            advisor = session.get(User, ADVISOR_ID)
            session.expunge(advisor)

        def override_db():
            with factory() as session:
                yield session

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(app.router, "lifespan_context", _noop_lifespan)
            app.dependency_overrides[get_db] = override_db
            app.dependency_overrides[get_current_user] = lambda: advisor
            try:
                with TestClient(app) as client:
                    created = client.post("/clients", json={
                        "client_number": "ABN-001", "first_name": "Erika",
                        "last_name": "Abnahme", "advisor_id": ADVISOR_ID,
                        "household_type": "Einzelperson",
                    })
                    assert created.status_code == 201, created.text
                    client_id = created.json()["id"]
                    mandates = {}
                    for key, number in (("advisory", "ABN-M-001"), ("aggressive", "ABN-M-002"), ("empty", "ABN-M-003")):
                        resp = client.post(f"/clients/{client_id}/mandates", json={
                            "mandate_number": number, "mandate_type": "Anlageberatung",
                        })
                        assert resp.status_code == 201, resp.text
                        mandates[key] = resp.json()["id"]
                    yield client, factory, {"client": client_id, **mandates}
            finally:
                app.dependency_overrides.clear()
