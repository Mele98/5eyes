"""2026-07-24 (Generalaudit): create_client()'s Pre-Check auf doppelte
client_number ist TOCTOU-racy -- zwei parallele Requests (z.B. Doppelklick)
koennen beide den Check passieren, bevor einer committet. Der UNIQUE-
Constraint (models/clients.py) verhindert zuverlaessig ein persistiertes
Duplikat, gab dem verlierenden Request aber einen 500 (unbehandelter
IntegrityError) statt eines klaren 409. Kein Datenintegritaets-Bug --
reiner Statuscode-/UX-Fix.

Die exakte Race-Timing wird hier nicht Bit-fuer-Bit nachgebaut (dafuer
braeuchte es echte Threads); stattdessen wird der Fehlerpfad direkt
erzwungen: Session.commit() wirft eine IntegrityError, exakt das, was
ein realer Constraint-Verstoss zur Laufzeit auch tun wuerde.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.clients import Client
from test_data_classification_gate import (  # noqa: F401
    _client_payload,
    advisor_user,
    auth_client,
    session_factory,
)


def test_integrity_error_on_commit_returns_409_not_500(auth_client, session_factory, monkeypatch):
    """Simuliert den Race-Verlust: der Pre-Check hat (noch) nichts gefunden,
    aber db.commit() schlaegt fehl, weil zwischenzeitlich (in Produktion:
    ein paralleler Request) derselbe client_number bereits committet wurde."""
    from sqlalchemy.orm import Session as OrmSession

    original_commit = OrmSession.commit
    call_count = {"n": 0}

    def _commit_raises_once(self, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise IntegrityError("UNIQUE constraint failed", {}, Exception("simuliert"))
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(OrmSession, "commit", _commit_raises_once)

    response = auth_client.post("/clients", json=_client_payload("RACE-1", "synthetic"))
    assert response.status_code == 409, response.text
    assert "bereits vergeben" in response.json()["detail"]


def test_no_duplicate_persisted_after_race(auth_client, session_factory, monkeypatch):
    """Nach dem 409 darf KEIN halb-persistierter Client in der DB liegen --
    das rollback() im except-Zweig muss die Session bereinigen."""
    from sqlalchemy.orm import Session as OrmSession

    original_commit = OrmSession.commit
    call_count = {"n": 0}

    def _commit_raises_once(self, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise IntegrityError("UNIQUE constraint failed", {}, Exception("simuliert"))
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(OrmSession, "commit", _commit_raises_once)

    auth_client.post("/clients", json=_client_payload("RACE-2", "synthetic"))

    with session_factory() as s:
        assert s.query(Client).filter(Client.client_number == "RACE-2").count() == 0


def test_normal_create_unaffected_no_race(auth_client):
    """Regressionsschutz: der Normalfall (kein Commit-Fehler) bleibt 201."""
    response = auth_client.post("/clients", json=_client_payload("NORMAL-1", "synthetic"))
    assert response.status_code == 201, response.text


def test_genuine_pre_check_duplicate_still_returns_409(auth_client):
    """Der bestehende Pre-Check-Pfad (kein Race, echtes Duplikat schon vorher
    committet) muss weiterhin 409 liefern -- unveraendertes Verhalten."""
    first = auth_client.post("/clients", json=_client_payload("DUP-1", "synthetic"))
    assert first.status_code == 201, first.text
    second = auth_client.post("/clients", json=_client_payload("DUP-1", "synthetic"))
    assert second.status_code == 409, second.text
