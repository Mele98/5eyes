"""KN3-B / E2E3-08: Depot ohne Aufteilung -- verstaendliche Ablehnung, keine Annahme.

Befund (Dok. 118): «+ Position › Depot» mit der vorbelegten Aufteilung 0/0/0/0/0
scheiterte mit «Value error, Depot Allokation muss 10000 BP ergeben (aktuell:
0)», waehrend die Oberflaeche eine automatische Annahme (60 % Aktien / 25 %
Obligationen) versprach. CTO-Entscheid: keine Aufteilung erfinden. Der Server
lehnt mit einer deutschen Meldung ohne technisches Praefix und ohne Basispunkte
ab; das Versprechen in der Oberflaeche nimmt KN3-U zurueck.

Gegenprobe: alte ``ValueError``-Meldung bzw. "alle 0 erlaubt" beim Update
zuruecksetzen -> rot.
"""
from __future__ import annotations

import datetime as _dt

import pytest
from pydantic import ValidationError

DEPOT = {"label": "Depot (fiktiv)", "position_type": "Depot", "assignment": "Beratungsvermögen",
         "current_value_rappen": 400_000_00, "currency": "CHF", "data_classification": "synthetic"}
ZERO = {"alloc_equities_bps": 0, "alloc_bonds_bps": 0, "alloc_real_estate_bps": 0,
        "alloc_liquidity_bps": 0, "alloc_alternatives_bps": 0}


def _msg(payload):
    from schemas.wealth import WealthPositionCreate

    with pytest.raises(ValidationError) as exc:
        WealthPositionCreate(**payload)
    errors = exc.value.errors()
    assert len(errors) == 1, errors
    return errors[0]["msg"]


def test_depot_without_allocation_is_rejected_with_a_clear_german_message():
    msg = _msg({**DEPOT, **ZERO})
    assert msg == "Bitte die Aufteilung des Depots erfassen (Summe 100 %)."
    assert "Value error" not in msg and "BP" not in msg and "bps" not in msg


def test_incomplete_depot_allocation_names_the_captured_percentage():
    msg = _msg({**DEPOT, **ZERO, "alloc_equities_bps": 6000, "alloc_bonds_bps": 3000})
    assert msg == "Die Aufteilung des Depots muss zusammen 100 % ergeben (erfasst: 90 %)."


def test_complete_depot_allocation_is_accepted_unchanged():
    from schemas.wealth import WealthPositionCreate

    pos = WealthPositionCreate(**{**DEPOT, **ZERO, "alloc_equities_bps": 4000, "alloc_bonds_bps": 5000,
                                  "alloc_liquidity_bps": 1000})
    assert (pos.alloc_equities_bps, pos.alloc_bonds_bps, pos.alloc_liquidity_bps) == (4000, 5000, 1000)


def test_pension_allocation_message_is_readable_and_zero_stays_allowed():
    from schemas.wealth import WealthPositionCreate

    pension = {"label": "3a (fiktiv)", "position_type": "Vorsorge", "assignment": "Anderes Vermögen",
               "current_value_rappen": 50_000_00, "currency": "CHF", "pension_type": "Säule 3a"}
    WealthPositionCreate(**pension, **ZERO)  # 0 = Vorsorge ohne Aufteilung, wie bisher erlaubt
    msg = _msg({**pension, **ZERO, "alloc_bonds_bps": 5000})
    assert "BP" not in msg and "Value error" not in msg and "50 %" in msg


def test_api_rejects_zero_depot_on_create_and_update(tmp_path):
    """Echte Route: 422 mit genau dieser Meldung im ``msg`` (so zeigt sie die
    Oberflaeche an), auch beim Bearbeiten (kein Rueckfall auf "alle 0")."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database import Base, get_db
    from main import app
    from models.tenant import DEFAULT_TENANT_ID, Tenant

    engine = create_engine(f"sqlite:///{tmp_path / 'kn3_depot.db'}", connect_args={"check_same_thread": False})
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    now = _dt.datetime.now(_dt.UTC).isoformat().replace("+00:00", "Z")
    with sf() as s:
        s.add(Tenant(id=DEFAULT_TENANT_ID, display_name="Testfirma Fiktiv", slug="main", hosting_tier="tier1",
                     license_status="active", is_active=1, created_at=now, updated_at=now))
        s.commit()

    def override_db():
        with sf() as s:
            yield s

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as api:
            token = api.post("/auth/bootstrap-admin", json={
                "username": "kn3depot", "password": "StrongPass1234!", "full_name": "Erika Testberaterin",
            }).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            me = api.get("/auth/me", headers=headers).json()
            cid = api.post("/clients", headers=headers, json={
                "client_number": "KN3-D1", "first_name": "Anna", "last_name": "Testkundin-Fiktiv",
                "advisor_id": me["id"]}).json()["id"]
            resp = api.post(f"/clients/{cid}/wealth-positions", headers=headers, json={**DEPOT, **ZERO})
            assert resp.status_code == 422, resp.text
            assert [item["msg"] for item in resp.json()["detail"]] == [
                "Bitte die Aufteilung des Depots erfassen (Summe 100 %)."]
            ok = api.post(f"/clients/{cid}/wealth-positions", headers=headers, json={
                **DEPOT, **ZERO, "alloc_equities_bps": 4000, "alloc_bonds_bps": 5000, "alloc_liquidity_bps": 1000})
            assert ok.status_code in (200, 201), ok.text
            pid = ok.json()["id"]
            upd = api.put(f"/clients/{cid}/wealth-positions/{pid}", headers=headers, json=ZERO)
            assert upd.status_code == 422, upd.text
            assert upd.json()["detail"] == "Bitte die Aufteilung des Depots erfassen (Summe 100 %)."
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
