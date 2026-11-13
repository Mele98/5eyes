"""RC-CH-1-F1 / N-903-05: ``services.onsite_signature.service._commit``.

Bisher wurde JEDER Integritaetsfehler beim Commit eines Signaturschritts als
409 ``ONSITE_SIGNATURE_CONCURRENT_TRANSITION`` gemeldet -- auch ein CHECK-
Verstoss. Jetzt: CHECK -> zentraler Handler (422
``DB_CHECK_CONSTRAINT_VIOLATION``, ohne Werte), UNIQUE (echte Nebenlaeufigkeit)
-> unveraendert 409 ``ONSITE_SIGNATURE_CONCURRENT_TRANSITION``.

Echte SQLite-Constraints auf einer eigenen Probe-Tabelle; der Endpoint ruft
``_commit`` genau wie die Signatur-Endpunkte, die Abbildung uebernehmen die
zentralen Handler (``install_exception_handlers``).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.middleware import install_exception_handlers  # noqa: E402
from services.onsite_signature import service as onsite  # noqa: E402

ProbeBase = declarative_base()


class Probe(ProbeBase):
    __tablename__ = "onsite_probe"
    id = Column(Integer, primary_key=True)
    state = Column(String, nullable=False)
    note = Column(String)
    __table_args__ = (CheckConstraint("state IN ('OPEN','DONE')", name="ck_onsite_probe_state"),)


SECRET = "geheime-signaturdaten"


@pytest.fixture()
def api(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'onsite_probe.db'}", connect_args={"check_same_thread": False})
    ProbeBase.metadata.create_all(engine)
    sf = sessionmaker(bind=engine, expire_on_commit=False)
    with sf() as db:
        db.add(Probe(id=1, state="OPEN"))
        db.commit()
    app = FastAPI()
    install_exception_handlers(app)

    @app.post("/step/{row_id}/{state}")
    def step(row_id: int, state: str):
        with sf() as db:
            onsite._commit(db, Probe(id=row_id, state=state, note=SECRET))
        return {"ok": True}

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    engine.dispose()


def test_check_violation_in_commit_is_422_not_concurrent_transition(api):
    r = api.post("/step/2/BOGUS")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["reason_code"] == "DB_CHECK_CONSTRAINT_VIOLATION"
    assert SECRET not in r.text and "BOGUS" not in r.text


def test_unique_violation_in_commit_stays_409_concurrent_transition(api):
    r = api.post("/step/1/DONE")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["reason_code"] == onsite.CONCURRENT_TRANSITION


def test_valid_step_commits(api):
    assert api.post("/step/3/DONE").status_code == 200
