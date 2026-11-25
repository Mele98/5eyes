"""ROL-b (CTO-Entscheide H-187 / H-187-pruefung Nachtrag 3, H-190 Punkt 3).

1. Die externe Pruefperson (``compliance_reviewer``) gibt Produkt-Eignungsregeln
   als zweite Person frei, erfasst sie aber nie (analog KYC-Policy und
   Owner-Inhalte). Vier Augen: zweite Person, gleiche Firma, andere
   Postfach-Identitaet. Die Einzelfreigabe des Admins bleibt bestehen.
2. ``readonly`` ("Lesend"): der Abruf eines Kunden-PDFs wird auditiert, erzeugt
   aber nie ein finales Archiv (contract_documents unveraendert); das PDF ist
   als Ansicht gekennzeichnet ("Ansicht – nicht abgegeben").
3. Die Freigabe-Inbox zeigt Mandatsnummer UND Kundenname (sonst datenminimiert).
4. N-935R-02/-03: Backtest-Endpunkt mit app_env=production ohne freigegebene
   Jahresrenditen -> 409 REFERENCE_DATA_PACKAGE_MISSING; Jahresrenditen mit
   ``source='seed'`` zaehlen in Produktion/EXE nie, im Quellbetrieb unveraendert.

Echte HTTP-Aufrufe (TestClient, Wegwerf-SQLite). Alle Namen/Werte sind
fiktive Testwerte.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for _path in (BACKEND_ROOT, TESTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.product_eligibility import ProductEligibilityRule  # noqa: E402
from models.review import AuditLog, ContractDocument  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import compliance_reviewer_may_call, create_access_token, hash_password  # noqa: E402

NOW = "2026-11-21T09:00:00.000Z"
PW = "Testpasswort-ROLb-1"
REVIEWER_READY = dict(invited_by="rolb-adm", invited_at=NOW, activated_at=NOW, credentials_set_by="self",
                      totp_enabled=1, totp_set_by="self", reviewer_organisation="TEST-ROLb Org",
                      reviewer_reference="TEST-ROLb Mandat")
# key -> (id, rolle, firma, e-mail, extra)
USERS = {
    "admin": ("rolb-adm", "admin", "f-a", "inhaber@firma-a.invalid", {}),
    "advisor": ("rolb-adv", "advisor", "f-a", "berater@firma-a.invalid", {}),
    "reviewer": ("rolb-rev", "compliance_reviewer", "f-a", "pruefung@extern.invalid", REVIEWER_READY),
    # Zweites Konto derselben Person wie der Admin (Postfach mit +Alias).
    "reviewer_same_box": ("rolb-rev-box", "compliance_reviewer", "f-a", "Inhaber+pruefung@Firma-A.invalid",
                          REVIEWER_READY),
    # Eingeladen, aber 2FA nicht selbst eingerichtet.
    "reviewer_unready": ("rolb-rev-nr", "compliance_reviewer", "f-a", "neu@extern.invalid",
                         {**REVIEWER_READY, "totp_enabled": 0, "totp_set_by": None}),
    "admin_b": ("rolb-adm-b", "admin", "f-b", "inhaber@firma-b.invalid", {}),
    "reviewer_b": ("rolb-rev-b", "compliance_reviewer", "f-b", "pruefung-b@extern.invalid", REVIEWER_READY),
}


@pytest.fixture()
def elig(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rolb.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    with factory() as db:
        for tid in ("f-a", "f-b"):
            db.add(Tenant(id=tid, display_name=f"Testfirma {tid} Fiktiv", slug=tid, max_users=50,
                          hosting_tier="tier2", license_status="active", is_active=1,
                          created_at=NOW, updated_at=NOW))
        for uid, role, tid, email, extra in USERS.values():
            db.add(User(id=uid, username=uid, email=email, password_hash=hash_password(PW),
                        full_name=f"Testperson {uid}", role=role, is_active=1, tenant_id=tid,
                        must_change_password=0, created_at=NOW, updated_at=NOW, **extra))
        db.commit()

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_db
    try:
        yield factory, TestClient(app)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _h(key: str) -> dict:
    uid, _role, tid, _email, _extra = USERS[key]
    return {"Authorization": "Bearer " + create_access_token({"sub": uid, "tid": tid})}


def _fund(api) -> str:
    created = api.post("/products", headers=_h("admin"), json={
        "product_name": "Hausfonds ROLb Fiktiv", "product_type": "Fonds",
        "asset_class": "Aktien", "currency": "CHF",
        "suitability_profile_from": 2, "suitability_profile_to": 7,
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _rule(factory, pid) -> ProductEligibilityRule:
    with factory() as db:
        return db.query(ProductEligibilityRule).filter_by(product_id=pid).one()


def _seen(api, pid, key="reviewer") -> dict:
    """Body mit genau der angezeigten Fassung (H-193 N-939-02)."""
    drafts = api.get("/products/eligibility-drafts", headers=_h(key)).json()["drafts"]
    return {"seen_rules": [{"rule_id": r["rule_id"], "rule_hash": r["rule_hash"]}
                           for d in drafts if d["product_id"] == pid for r in d["rules"]]}


def _approve(api, key, pid, body=None):
    return api.post(f"/products/{pid}/eligibility-rule/approve", headers=_h(key), json=body or {})


def test_reviewer_sees_open_rule_and_approves_as_second_person(elig):
    factory, api = elig
    pid = _fund(api)
    listed = api.get("/products/eligibility-drafts", headers=_h("reviewer"))
    assert listed.status_code == 200, listed.text
    item = next(d for d in listed.json()["drafts"] if d["product_id"] == pid)
    # Was freigegeben wird, ist ohne Fondsuniversum erkennbar (keine Kundendaten).
    assert item["product_name"] == "Hausfonds ROLb Fiktiv" and item["asset_class"] == "Aktien"
    assert item["authored_by_names"] == ["Testperson rolb-adm"]
    assert item["authored_by_current_user"] is False
    rule = item["rules"][0]
    assert (rule["profile_from"], rule["profile_to"]) == (2, 7) and rule["rule_hash"]

    resp = _approve(api, "reviewer", pid, _seen(api, pid))
    assert resp.status_code == 200, resp.text
    assert resp.json()["approval_mode"] == "four_eyes"
    row = _rule(factory, pid)
    assert (row.status, row.approved_by, row.created_by) == ("approved", "rolb-rev", "rolb-adm")
    assert api.get("/products/eligibility-drafts", headers=_h("reviewer")).json()["drafts"] == []
    with factory() as db:
        audit = [a.new_value for a in db.query(AuditLog).filter_by(
            table_name="product_eligibility_rules", record_id=pid, user_id="rolb-rev").all()]
    assert any("approval_mode=four_eyes" in (v or "") for v in audit), audit


def test_reviewer_cannot_capture_or_change_products(elig):
    factory, api = elig
    pid = _fund(api)
    for method, path, body in (
        ("POST", "/products", {"product_name": "X", "product_type": "Fonds", "asset_class": "Aktien",
                               "currency": "CHF", "suitability_profile_from": 1, "suitability_profile_to": 10}),
        ("PUT", f"/products/{pid}", {"product_name": "Geaendert"}),
        ("GET", "/products", None),
    ):
        resp = api.request(method, path, headers=_h("reviewer"), **({"json": body} if body is not None else {}))
        assert resp.status_code == 403 and "COMPLIANCE_REVIEWER_SCOPE" in resp.text, (method, path, resp.text)
    assert _rule(factory, pid).status == "draft"


def test_foreign_firm_gets_404_and_does_not_see_the_draft(elig):
    factory, api = elig
    pid = _fund(api)
    for key in ("reviewer_b", "admin_b"):
        drafts = api.get("/products/eligibility-drafts", headers=_h(key)).json()["drafts"]
        assert pid not in {d["product_id"] for d in drafts}, key
        assert _approve(api, key, pid).status_code == 404, key
    assert _rule(factory, pid).status == "draft"


def test_same_mailbox_self_and_unready_reviewer_are_blocked(elig):
    factory, api = elig
    pid = _fund(api)
    # Zweites Konto derselben Person (gleiche Postfach-Identitaet) -> Vier Augen verletzt.
    same_box = _approve(api, "reviewer_same_box", pid, _seen(api, pid))
    assert same_box.status_code == 409 and "Vier-Augen" in same_box.text, same_box.text
    # Ohne selbst eingerichtete 2FA keine Freigabe.
    unready = _approve(api, "reviewer_unready", pid, _seen(api, pid))
    assert unready.status_code == 403 and "COMPLIANCE_REVIEWER_2FA_REQUIRED" in unready.text, unready.text
    assert _rule(factory, pid).status == "draft"
    # Selbstfreigabe: eine (hier direkt gesetzte) eigene Regel gibt die Pruefperson
    # nie frei -- auch nicht mit Einzelfreigabe-Bestaetigung.
    with factory() as db:
        db.query(ProductEligibilityRule).filter_by(product_id=pid).update({"created_by": "rolb-rev"})
        db.commit()
    own = _approve(api, "reviewer", pid, {**_seen(api, pid), "single_approver_attestation": True,
                                          "attestation_reason": "Einzelfreigabe durch die Pruefperson (Test)"})
    assert own.status_code == 409 and "Vier-Augen" in own.text, own.text
    assert _rule(factory, pid).status == "draft"


def test_admin_single_approval_stays_available_with_a_reviewer(elig):
    """Die Pruefperson zaehlt nicht als freigabeberechtigter Admin: die
    begruendete Einzelfreigabe des einzigen Admins bleibt moeglich."""
    factory, api = elig
    pid = _fund(api)
    plain = _approve(api, "admin", pid)
    assert plain.status_code == 409  # eigene Regel ohne Bestaetigung: Vier Augen
    attested = _approve(api, "admin", pid, {
        "single_approver_attestation": True,
        "attestation_reason": "Einzelfirma, Pruefperson nicht verfuegbar (Testwert).",
    })
    assert attested.status_code == 200, attested.text
    assert attested.json()["approval_mode"] == "single_approver_attested"


def test_advisor_and_readonly_cannot_approve_rules(elig):
    factory, api = elig
    pid = _fund(api)
    assert _approve(api, "advisor", pid).status_code == 403
    assert api.get("/products/eligibility-drafts", headers=_h("advisor")).status_code == 403
    assert _rule(factory, pid).status == "draft"


def test_reviewer_allowlist_covers_eligibility_approval_only():
    assert compliance_reviewer_may_call("GET", "/products/eligibility-drafts")
    assert compliance_reviewer_may_call("POST", "/products/p-1/eligibility-rule/approve")
    for method, path in (("POST", "/products"), ("GET", "/products"), ("PUT", "/products/p-1"),
                         ("GET", "/products/p-1/eligibility-rule/approve"),
                         ("POST", "/products/p-1/eligibility-rule/approve/x"),
                         ("POST", "/products/p-1/eligibility-rule"),
                         ("POST", "/products/import"), ("DELETE", "/products/p-1"),
                         ("POST", "/products/eligibility-drafts")):
        assert not compliance_reviewer_may_call(method, path), (method, path)


# ---------------------------------------------------------------------------
# 2. readonly: Ansicht statt Archiv
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def pdf_env(tmp_path):
    from test_document_archive import _seed_minimal_mandate

    from services.auth import get_current_user

    engine = create_engine(f"sqlite:///{tmp_path / 'rolb-pdf.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    advisor = User(id="rolb-pdf-adv", username="rolb-pdf-adv", password_hash="h", full_name="Test Berater ROLb",
                   role="advisor", is_active=1, created_at=_now(), updated_at=_now())
    readonly = User(id="rolb-pdf-ro", username="rolb-pdf-ro", password_hash="h", full_name="Test Lesend ROLb",
                    role="readonly", is_active=1, created_at=_now(), updated_at=_now())
    mid = _seed_minimal_mandate(factory, advisor, mandate_id="mdt-rolb")
    with factory() as db:
        db.add(User(**{c.name: getattr(readonly, c.name) for c in User.__table__.columns}))
        db.commit()
    current = {"user": readonly}

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    try:
        with TestClient(app) as api:
            yield factory, api, mid, current, advisor, readonly
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _docs(factory, mid, document_type=None) -> list:
    with factory() as db:
        q = db.query(ContractDocument).filter(ContractDocument.mandate_id == mid)
        if document_type:
            q = q.filter(ContractDocument.document_type == document_type)
        return q.all()


def _pdf_text(content: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join((page.extract_text() or "") for page in PdfReader(BytesIO(content)).pages)


def _views(factory, mid) -> list[str]:
    with factory() as db:
        return [a.new_value for a in db.query(AuditLog).filter_by(
            field_name="client_pdf_readonly_view", user_id="rolb-pdf-ro").all()]


def test_readonly_pdf_is_an_audited_view_never_archived_and_writer_archives(pdf_env):
    factory, api, mid, current, advisor, _readonly = pdf_env
    before = len(_docs(factory, mid))
    resp = api.get(f"/mandates/{mid}/reports/risikoprofil.pdf")
    assert resp.status_code == 200, resp.text
    assert "Ansicht – nicht abgegeben" in _pdf_text(resp.content)
    assert len(_docs(factory, mid)) == before  # kein contract_documents-Eintrag
    assert _views(factory, mid) == ["Risikoprofil"]
    # Gegenprobe: ein Mitarbeiter mit Schreibrecht gibt das Dokument ab (Archiv).
    current["user"] = advisor
    final = api.get(f"/mandates/{mid}/reports/risikoprofil.pdf")
    assert final.status_code == 200, final.text
    assert "Ansicht – nicht abgegeben" not in _pdf_text(final.content)
    assert len(_docs(factory, mid, "Risikoprofilierung")) == 1


def test_readonly_client_information_is_a_view_not_the_archive_copy(pdf_env):
    factory, api, mid, _current, _advisor, _readonly = pdf_env
    archived_before = [(d.id, d.version) for d in _docs(factory, mid, "Kundeninformation")]
    resp = api.get(f"/mandates/{mid}/reports/kundeninformation.pdf")
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("X-Ares-Draft") == "ansicht"
    assert "X-Client-Information-Document-Id" not in resp.headers
    assert "Ansicht – nicht abgegeben" in _pdf_text(resp.content)
    assert [(d.id, d.version) for d in _docs(factory, mid, "Kundeninformation")] == archived_before
    assert _views(factory, mid) == ["Kundeninformation"]


def test_readonly_archive_copy_is_audited_and_unchanged(pdf_env):
    factory, api, mid, current, advisor, readonly = pdf_env
    current["user"] = advisor
    original = api.get(f"/mandates/{mid}/reports/risikoprofil.pdf")
    doc = _docs(factory, mid, "Risikoprofilierung")[0]
    current["user"] = readonly
    copy = api.get(f"/mandates/{mid}/documents/{doc.id}/pdf")
    assert copy.status_code == 200 and copy.content == original.content
    with factory() as db:
        rows = db.query(AuditLog).filter_by(field_name="client_pdf_readonly_view", record_id=doc.id).all()
    assert len(rows) == 1 and rows[0].action == "EXPORT"
    assert len(_docs(factory, mid, "Risikoprofilierung")) == 1


def test_archive_service_refuses_readonly_as_last_barrier(pdf_env):
    from services.document_archive import archive_generated_pdf

    factory, _api, mid, _current, _advisor, readonly = pdf_env
    with factory() as db, pytest.raises(PermissionError):
        archive_generated_pdf(db, mandate_id=mid, document_type="Risikoprofilierung", title="x",
                              pdf_bytes=b"%PDF-1.4", content_hash="0" * 64, current_user=readonly)


def test_every_pdf_route_names_its_document_for_the_readonly_audit():
    import re

    source = (BACKEND_ROOT / "routers" / "pdf_reports.py").read_text(encoding="utf-8")
    calls = re.findall(r"_build_pdf_context\(mandate, current_user, db[^)]*\)", source)
    assert calls and all("document=" in call for call in calls), calls


# ---------------------------------------------------------------------------
# 3. Freigabe-Inbox: Mandatsnummer und Kundenname
# ---------------------------------------------------------------------------
from tests.test_ccx_p4_allocation_publish import (  # noqa: E402,F401
    _finalized,
    _mandate,
    session_factory,
)


def _clone_user(factory, template_id, role):
    with factory() as db:
        template = db.query(User).filter(User.id == template_id).one()
        uid = f"rolb-{role}-{uuid.uuid4().hex[:8]}"
        clone = {c.name: getattr(template, c.name) for c in User.__table__.columns}
        clone.update(id=uid, username=uid, email=f"{uid}@example.invalid", full_name=f"Testperson {role}",
                     role=role, must_change_password=0, totp_enabled=0)
        db.add(User(**clone))
        db.commit()
    return uid


def _token(factory, uid):
    with factory() as db:
        user = db.query(User).filter(User.id == uid).one()
        claims = {"sub": uid, **({"tid": user.tenant_id} if user.tenant_id else {})}
    return {"Authorization": "Bearer " + create_access_token(claims)}


@pytest.fixture()
def inbox_api(session_factory):
    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_inbox_item_names_mandate_number_and_client(session_factory, inbox_api):
    advisor_id, mid, _aid, _run = _finalized(session_factory, "rolbinbox")
    admin = _clone_user(session_factory, advisor_id, "admin")
    items = inbox_api.get("/publication-inbox", headers=_token(session_factory, admin)).json()
    item = next(i for i in items if i["mandate_id"] == mid)
    with session_factory() as db:
        mandate = _mandate(db, mid)
        expected = f"{mandate.client.first_name} {mandate.client.last_name}".strip()
        number = mandate.mandate_number
    assert item["client_name"] == expected and expected
    assert item["mandate_number"] == number
    # Sonst weiterhin datenminimiert: keine weiteren Personalien/Vermoegenswerte.
    for forbidden in ("client_id", "birth_date", "email", "total_wealth", "address", "client_number"):
        assert forbidden not in item


# ---------------------------------------------------------------------------
# 4. N-935R-02 / N-935R-03: Backtest in Produktion
# ---------------------------------------------------------------------------
_BUCKETS_DE = ("Aktien", "Obligationen", "Immobilien", "Alternative", "Liquiditaet")


def _annual_returns(factory, year, source):
    from models.snapshots import AssetClassAnnualReturn

    with factory() as db:
        for ac in _BUCKETS_DE:
            db.add(AssetClassAnnualReturn(id=str(uuid.uuid4()), year=year, asset_class=ac, return_bps=300,
                                          source=source, created_at=NOW, updated_at=NOW))
        db.commit()


def _clear_annual_returns(factory):
    from models.snapshots import AssetClassAnnualReturn

    with factory() as db:
        db.query(AssetClassAnnualReturn).delete()
        db.commit()


def test_backtest_endpoint_in_production_refuses_without_released_returns_and_ignores_seed(
        session_factory, inbox_api, monkeypatch):
    import config

    advisor_id, mid, _aid, _run = _finalized(session_factory, "rolbbt")
    headers = _token(session_factory, advisor_id)
    _clear_annual_returns(session_factory)
    for year in (2019, 2020, 2021):
        _annual_returns(session_factory, year, "seed")  # wie aus einer uebernommenen Bestands-DB

    # Quellbetrieb unveraendert: die Seed-Jahre werden genutzt.
    monkeypatch.setattr(config.settings, "app_env", "development")
    source_mode = inbox_api.get(f"/mandates/{mid}/backtest/strategy", headers=headers)
    assert source_mode.status_code == 200, source_mode.text
    assert source_mode.json()["available_years"] == [2019, 2020, 2021]

    # N-935R-02 + -03: Produktion -- nur Seed-Zeilen = keine freigegebenen Daten -> 409.
    monkeypatch.setattr(config.settings, "app_env", "production")
    refused = inbox_api.get(f"/mandates/{mid}/backtest/strategy", headers=headers)
    assert refused.status_code == 409, refused.text
    assert "REFERENCE_DATA_PACKAGE_MISSING" in refused.text

    # Freigegebene (nicht geseedete) Jahre zaehlen, die Seed-Jahre nie.
    _annual_returns(session_factory, 2022, "test-freigabe")
    released = inbox_api.get(f"/mandates/{mid}/backtest/strategy", headers=headers)
    assert released.status_code == 200, released.text
    assert released.json()["available_years"] == [2022]


def test_backtest_endpoint_in_production_without_any_returns_is_409(session_factory, inbox_api, monkeypatch):
    import config

    advisor_id, mid, _aid, _run = _finalized(session_factory, "rolbbt0")
    _clear_annual_returns(session_factory)
    monkeypatch.setattr(config.settings, "app_env", "production")
    resp = inbox_api.get(f"/mandates/{mid}/backtest/strategy", headers=_token(session_factory, advisor_id))
    assert resp.status_code == 409, resp.text
    assert "REFERENCE_DATA_PACKAGE_MISSING" in resp.text
