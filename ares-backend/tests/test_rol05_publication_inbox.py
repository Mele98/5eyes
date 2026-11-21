"""ROL-05 (CTO-Entscheid H-180): Freigabe-Inbox fuer die Vier-Augen-Publikation.

Die Zweitperson (Firmen-Admin oder benannte externe Pruefperson) sieht NUR die
zur Freigabe vorgelegten Akten ihrer Firma (versiegelt, noch nicht publiziert),
datenminimiert, und gibt genau den geprueften Stand frei -- ohne volle
Kundensicht. Echte HTTP-Aufrufe mit echten Tokens (Rollen-, Staff- und
Pruefpersonen-Allowlist laufen mit). Alle Namen/Werte sind fiktive Testwerte.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.test_ccx_p4_allocation_publish import (  # noqa: F401
    _finalizable_run,
    _finalized,
    _mandate,
    session_factory,
)

NOW = "2026-11-21T09:00:00.000Z"
ITEM_KEYS = {
    "mandate_id", "mandate_number", "mandate_type", "prepared_by", "prepared_by_name", "sealed_at",
    "target_allocation_id", "validation_hash", "can_publish", "blocker_codes", "targets_bps", "bands_bps",
}


def _user(session_factory, template_id, *, role, tenant_id=None, **extra):
    from models.users import User

    with session_factory() as db:
        template = db.query(User).filter(User.id == template_id).one()
        uid = f"rol05-{role}-{uuid.uuid4().hex[:8]}"
        clone = {c.name: getattr(template, c.name) for c in User.__table__.columns}
        clone.update(id=uid, username=uid, email=f"{uid}@example.invalid", full_name=f"Testperson {role}",
                     role=role, must_change_password=0, totp_enabled=0, **extra)
        if tenant_id is not None:
            clone["tenant_id"] = tenant_id
        db.add(User(**clone))
        db.commit()
    return uid


def _user_ready(session_factory, template_id, extra):
    from models.users import User

    uid = _user(session_factory, template_id, role="compliance_reviewer",
                **{k: v for k, v in extra.items() if k != "totp_enabled"})
    with session_factory() as db:
        db.query(User).filter(User.id == uid).update({"totp_enabled": 1})
        db.commit()
    return uid


@pytest.fixture()
def api(session_factory):
    from database import get_db
    from main import app

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _h(session_factory, uid):
    from models.users import User
    from services.auth import create_access_token

    with session_factory() as db:
        user = db.query(User).filter(User.id == uid).one()
        claims = {"sub": uid}
        if user.tenant_id:
            claims["tid"] = user.tenant_id
    return {"Authorization": "Bearer " + create_access_token(claims)}


def _other_firm_admin(session_factory, template_id):
    from models.tenant import Tenant

    tid = f"rol05-firm-{uuid.uuid4().hex[:6]}"
    with session_factory() as db:
        db.add(Tenant(id=tid, display_name="Testfirma B Fiktiv", slug=tid, max_users=10,
                      created_at=NOW, updated_at=NOW))
        db.commit()
    return _user(session_factory, template_id, role="admin", tenant_id=tid)


def test_admin_sees_only_presented_file_minimal_and_publishes_four_eyes(session_factory, api):
    advisor_id, mid, _aid, _run = _finalized(session_factory, "rol05a")
    # Nicht vorgelegt (nur berechnet, nicht finalisiert): erscheint nie.
    _adv2, draft_mid, _a2, _r2 = _finalizable_run(session_factory, "rol05draft")
    admin = _user(session_factory, advisor_id, role="admin")

    listed = api.get("/publication-inbox", headers=_h(session_factory, admin))
    assert listed.status_code == 200, listed.text
    items = {item["mandate_id"]: item for item in listed.json()}
    assert mid in items and draft_mid not in items
    item = items[mid]
    # Datenminimiert: genau diese Felder, keine Personalien/Vermoegenswerte.
    assert set(item) == ITEM_KEYS
    assert item["prepared_by"] == advisor_id and item["can_publish"] is True
    assert sum(item["targets_bps"].values()) == 10_000

    # Nicht vorgelegte Akte ist ueber die Inbox nicht freigebbar (keine Auskunft).
    denied = api.post(f"/publication-inbox/{draft_mid}/approve", headers=_h(session_factory, admin),
                      json={"target_allocation_id": "x", "validation_hash": "0" * 64})
    assert denied.status_code == 404

    resp = api.post(f"/publication-inbox/{mid}/approve", headers=_h(session_factory, admin),
                    json={"target_allocation_id": item["target_allocation_id"],
                          "validation_hash": item["validation_hash"]})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["approval_mode"] == "four_eyes" and body["approved_by"] == admin
    # Danach ist die Akte nicht mehr vorgelegt.
    again = api.get("/publication-inbox", headers=_h(session_factory, admin)).json()
    assert mid not in {i["mandate_id"] for i in again}


def test_external_reviewer_sees_inbox_without_client_access_and_approves(session_factory, api):
    advisor_id, mid, _aid, _run = _finalized(session_factory, "rol05b")
    reviewer = _user_ready(session_factory, advisor_id, dict(
        invited_by=advisor_id, invited_at=NOW, activated_at=NOW, credentials_set_by="self",
        totp_set_by="self", reviewer_organisation="TEST-ROL05 Org", reviewer_reference="TEST-ROL05 Mandat"))
    headers = _h(session_factory, reviewer)
    with session_factory() as db:
        client_id = _mandate(db, mid).client_id
    # Keine volle Kundensicht: Mandat, Kunde, PDF bleiben gesperrt.
    for path in (f"/mandates/{mid}", f"/clients/{client_id}", f"/mandates/{mid}/reports/risikoprofil.pdf",
                 "/clients"):
        assert api.get(path, headers=headers).status_code == 403, path
    listed = api.get("/publication-inbox", headers=headers)
    assert listed.status_code == 200, listed.text
    item = next(i for i in listed.json() if i["mandate_id"] == mid)
    resp = api.post(f"/publication-inbox/{mid}/approve", headers=headers,
                    json={"target_allocation_id": item["target_allocation_id"],
                          "validation_hash": item["validation_hash"]})
    assert resp.status_code == 201, resp.text
    assert resp.json()["approval_mode"] == "four_eyes"


def test_reviewer_without_own_2fa_cannot_approve(session_factory, api):
    advisor_id, mid, _aid, _run = _finalized(session_factory, "rol05c")
    reviewer = _user(session_factory, advisor_id, role="compliance_reviewer", invited_by=advisor_id,
                     invited_at=NOW, activated_at=NOW, credentials_set_by="self")
    headers = _h(session_factory, reviewer)
    item = next(i for i in api.get("/publication-inbox", headers=headers).json() if i["mandate_id"] == mid)
    resp = api.post(f"/publication-inbox/{mid}/approve", headers=headers,
                    json={"target_allocation_id": item["target_allocation_id"],
                          "validation_hash": item["validation_hash"]})
    assert resp.status_code == 403
    with session_factory() as db:
        assert db.execute(text("SELECT count(*) FROM allocation_active_publications WHERE mandate_id = :m"),
                          {"m": mid}).scalar() == 0


def test_inbox_roles_and_firm_separation(session_factory, api):
    advisor_id, mid, _aid, _run = _finalized(session_factory, "rol05d")
    # Der Berater (Vorbereiter) und andere Rollen haben keine Inbox: Berater
    # publizieren nicht allein, readonly/PM/Kunde ohnehin nicht.
    for role in ("advisor", "readonly", "portfolio_management", "client"):
        uid = advisor_id if role == "advisor" else _user(session_factory, advisor_id, role=role)
        assert api.get("/publication-inbox", headers=_h(session_factory, uid)).status_code == 403, role
    # Admin einer anderen Firma: leere Inbox, Freigabe -> 404, kein Entscheid.
    foreign = _other_firm_admin(session_factory, advisor_id)
    assert mid not in {i["mandate_id"] for i in api.get(
        "/publication-inbox", headers=_h(session_factory, foreign)).json()}
    resp = api.post(f"/publication-inbox/{mid}/approve", headers=_h(session_factory, foreign),
                    json={"target_allocation_id": "x", "validation_hash": "0" * 64})
    assert resp.status_code == 404
    with session_factory() as db:
        assert db.execute(text("SELECT count(*) FROM allocation_publication_decisions WHERE mandate_id = :m"),
                          {"m": mid}).scalar() == 0


def test_preparer_never_sees_own_file_even_as_admin(session_factory, api):
    """Vier Augen: wer den Entscheid versiegelt hat, sieht ihn nicht in der Inbox."""
    from models.users import User

    advisor_id, mid, _aid, _run = _finalized(session_factory, "rol05e")
    with session_factory() as db:
        db.query(User).filter(User.id == advisor_id).update({"role": "admin"})
        db.commit()
    listed = api.get("/publication-inbox", headers=_h(session_factory, advisor_id))
    assert listed.status_code == 200
    assert mid not in {i["mandate_id"] for i in listed.json()}
