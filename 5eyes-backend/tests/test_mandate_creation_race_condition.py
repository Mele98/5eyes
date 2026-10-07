"""RACE-01 (Audit-Finding, 2026-10-07): create_mandate()'s Pre-Check auf
doppelte mandate_number ist -- wie zuvor bei create_client() (siehe
test_client_creation_race_condition.py) -- TOCTOU-racy: zwei parallele
Requests (z.B. Doppelklick) koennen beide den Check passieren, bevor einer
committet. Der UNIQUE-Constraint auf mandate_number (models/mandates.py)
verhindert zuverlaessig ein persistiertes Duplikat, gab dem verlierenden
Request aber einen 500 (unbehandelter IntegrityError) statt eines klaren
409. Kein Datenintegritaets-Bug -- reiner Statuscode-/UX-Fix.

Identisches Test-Timing-Muster wie test_client_creation_race_condition.py:
die exakte Race wird nicht Bit-fuer-Bit nachgebaut (dafuer braeuchte es
echte Threads); stattdessen wird der Fehlerpfad direkt erzwungen --
Session.commit() wirft beim ersten Aufruf eine IntegrityError, exakt das,
was ein realer Constraint-Verstoss zur Laufzeit auch tun wuerde.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.mandates import Mandate
from test_data_classification_gate import (  # noqa: F401
    _create_synthetic_client,
    advisor_user,
    auth_client,
    session_factory,
)


def _mandate_payload(number: str) -> dict:
    return {"mandate_number": number}


def test_integrity_error_on_commit_returns_409_not_500(auth_client, session_factory, monkeypatch):
    """Simuliert den Race-Verlust: der Pre-Check hat (noch) nichts gefunden,
    aber db.commit() schlaegt fehl, weil zwischenzeitlich (in Produktion:
    ein paralleler Request) dieselbe mandate_number bereits committet wurde."""
    from sqlalchemy.orm import Session as OrmSession

    client_id = _create_synthetic_client(auth_client, "RACE-MND-CLIENT-1")

    original_commit = OrmSession.commit
    call_count = {"n": 0}

    def _commit_raises_once(self, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise IntegrityError("UNIQUE constraint failed", {}, Exception("simuliert"))
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(OrmSession, "commit", _commit_raises_once)

    response = auth_client.post(
        f"/clients/{client_id}/mandates", json=_mandate_payload("RACE-M-1")
    )
    assert response.status_code == 409, response.text
    assert "bereits vergeben" in response.json()["detail"]


def test_no_duplicate_persisted_after_race(auth_client, session_factory, monkeypatch):
    """Nach dem 409 darf KEIN halb-persistiertes Mandat in der DB liegen --
    das rollback() im except-Zweig muss die Session bereinigen."""
    from sqlalchemy.orm import Session as OrmSession

    client_id = _create_synthetic_client(auth_client, "RACE-MND-CLIENT-2")

    original_commit = OrmSession.commit
    call_count = {"n": 0}

    def _commit_raises_once(self, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise IntegrityError("UNIQUE constraint failed", {}, Exception("simuliert"))
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(OrmSession, "commit", _commit_raises_once)

    auth_client.post(f"/clients/{client_id}/mandates", json=_mandate_payload("RACE-M-2"))

    with session_factory() as s:
        assert s.query(Mandate).filter(Mandate.mandate_number == "RACE-M-2").count() == 0


def test_normal_create_unaffected_no_race(auth_client):
    """Regressionsschutz: der Normalfall (kein Commit-Fehler) bleibt 201."""
    client_id = _create_synthetic_client(auth_client, "RACE-MND-CLIENT-3")
    response = auth_client.post(
        f"/clients/{client_id}/mandates", json=_mandate_payload("NORMAL-M-1")
    )
    assert response.status_code == 201, response.text


def test_genuine_pre_check_duplicate_still_returns_409(auth_client):
    """Der bestehende Pre-Check-Pfad (kein Race, echtes Duplikat schon vorher
    committet) muss weiterhin 409 liefern -- unveraendertes Verhalten."""
    client_id = _create_synthetic_client(auth_client, "RACE-MND-CLIENT-4")
    first = auth_client.post(
        f"/clients/{client_id}/mandates", json=_mandate_payload("DUP-M-1")
    )
    assert first.status_code == 201, first.text
    second = auth_client.post(
        f"/clients/{client_id}/mandates", json=_mandate_payload("DUP-M-1")
    )
    assert second.status_code == 409, second.text
