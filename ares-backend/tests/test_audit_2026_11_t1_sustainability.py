"""Audit 2026-11 / 05, Paket T1: Nachhaltigkeits- und Ausschlussnachweise.

Pflichtpfade (jeweils mit Gegenprobe):
- Selbstfreigabe -> 409; Freigabe durch andere Person -> 200.
- Tenant-Admin aendert Plattform-Nachweis (global) -> 403; super_admin darf.
- Abgelaufener Nachweis zaehlt nicht; am letzten Gueltigkeitstag schon.
- Seed-Werte am Produkt (sfdr_class, esg_rating, climate_benchmark,
  theme_tags) erfuellen nichts; erst ein freigegebener Nachweis.
- Schwellenvergleich an der Grenze (500 <= 500 erfuellt, 501 nicht).
Dazu Import (JSON/CSV) nur als Entwurf, Export, Hausstandard (T-E1-Defaults,
tenant-aenderbar, auditiert) und der Katalog-Sync Schema <-> Modell.

Isolation: eigene SQLite-Datei je Test (tmp_path) mit Fremdschluesseln an
wie in der App; keine Live-DB. Keine Engine-Wirkung in T1 (Golden
unveraendert).
"""
from __future__ import annotations

import io
import sys
import typing
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

import models.product_eligibility as catalog  # noqa: E402
import schemas.review as review_schemas  # noqa: E402
from database import Base, attach_sqlite_pragmas, get_db  # noqa: E402
from main import app  # noqa: E402
from models.product_eligibility import ProductSustainabilityAttribute  # noqa: E402
from models.review import AuditLog, Product  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import get_current_user  # noqa: E402
from services.product_eligibility_governance import (  # noqa: E402
    RuleApprovalConflict,
    approve_sustainability_attribute,
    default_evidence_valid_until,
    evaluate_criterion,
    is_criterion_satisfied,
)

NOW = "2026-11-04T10:00:00.000Z"
TODAY = date.today()
AS_OF = (TODAY - timedelta(days=30)).isoformat()


@pytest.fixture()
def SF(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 't1.db'}", connect_args={"check_same_thread": False})
    attach_sqlite_pragmas(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    with factory() as s:
        for tid in ("main", "firm-a", "firm-b"):
            s.add(Tenant(id=tid, display_name=tid, slug=tid, hosting_tier="tier2",
                         license_status="active", is_active=1, created_at=NOW, updated_at=NOW))
        s.flush()
        for uid, role, tid in (
            ("admin-a1", "admin", "firm-a"), ("admin-a2", "admin", "firm-a"),
            ("admin-b", "admin", "firm-b"), ("root", "super_admin", None),
            ("root2", "super_admin", None),
        ):
            s.add(User(id=uid, username=uid, password_hash="h", full_name=uid, role=role,
                       is_active=1, tenant_id=tid, created_at=NOW, updated_at=NOW))
        s.add(Product(id="g1", product_name="Globaler Welt-ETF", asset_class="Aktien", product_type="ETF",
                      sub_asset_class="Aktien Global", currency="CHF", ter_bps=20, is_active=1,
                      sfdr_class="8", esg_rating="AAA", esg_score_x10=800, climate_benchmark="PAB",
                      theme_tags='["tobacco"]', created_at=NOW, updated_at=NOW, isin="IE00B4L5Y983"))
        s.add(Product(id="own-a", product_name="Eigener Fonds A", asset_class="Aktien", product_type="Fonds",
                      currency="CHF", ter_bps=30, is_active=1, tenant_id="firm-a",
                      created_at=NOW, updated_at=NOW))
        s.commit()
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture()
def client(SF):
    def override_db():
        with SF() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _as(user_id, role, tenant_id):
    u = User(id=user_id, username=user_id, password_hash="h", full_name=user_id,
             role=role, is_active=1, tenant_id=tenant_id)
    app.dependency_overrides[get_current_user] = lambda: u


def _strict(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)


def _attr(SF, *, id, product_id="g1", tenant_id=None, category="tobacco", kind="exclusion_policy",
          revenue=500, measured=None, value=None, as_of=AS_OF, valid_until=None, status="approved",
          created_by="root", approved_by="root2"):
    with SF() as s:
        s.add(ProductSustainabilityAttribute(
            id=id, product_id=product_id, tenant_id=tenant_id, category=category, kind=kind,
            revenue_threshold_bps=revenue, measured_exposure_bps=measured, value=value,
            source_type="fund_contract", source_reference="Fondsvertrag Anhang 2", as_of=as_of,
            valid_until=valid_until or default_evidence_valid_until(date.fromisoformat(as_of)).isoformat(),
            status=status, created_by=created_by, created_at=NOW,
            approved_by=approved_by if status == "approved" else None,
            approval_mode="four_eyes" if status == "approved" else None, updated_at=NOW,
        ))
        s.commit()


def _product(SF, pid="g1"):
    with SF() as s:
        return s.get(Product, pid)


def _payload(**over):
    body = {"category": "tobacco", "kind": "exclusion_policy", "revenue_threshold_bps": 500,
            "source_type": "fund_contract", "source_reference": "Fondsvertrag Anhang 2, S. 14", "as_of": AS_OF}
    body.update(over)
    return body


# ---------------------------------------------------------------------------
# is_criterion_satisfied (Service, T3 verdrahtet)
# ---------------------------------------------------------------------------


def test_threshold_boundary_is_inclusive(SF):
    _attr(SF, id="a500", revenue=500)
    with SF() as s:
        p = s.get(Product, "g1")
        assert is_criterion_satisfied(s, p, "tobacco", 500, TODAY)
        # Gegenprobe: Hausschwelle strenger als die Produktschwelle
        assert not is_criterion_satisfied(s, p, "tobacco", 499, TODAY)
        assert evaluate_criterion(s, p, "tobacco", 499, TODAY).reason == "threshold_exceeded"


def test_threshold_one_bps_above_house_standard_fails(SF):
    _attr(SF, id="a501", revenue=501)
    with SF() as s:
        p = s.get(Product, "g1")
        assert not is_criterion_satisfied(s, p, "tobacco", 500, TODAY)
        assert is_criterion_satisfied(s, p, "tobacco", 501, TODAY)


def test_measured_exposure_requires_zero_above_cutoff(SF):
    _attr(SF, id="m0", kind="measured_exposure", revenue=500, measured=0)
    _attr(SF, id="m1", category="alcohol", kind="measured_exposure", revenue=500, measured=1)
    with SF() as s:
        p = s.get(Product, "g1")
        assert is_criterion_satisfied(s, p, "tobacco", 500, TODAY)
        assert not is_criterion_satisfied(s, p, "tobacco", 400, TODAY), "Messgrenze lockerer als Hausschwelle"
        assert evaluate_criterion(s, p, "alcohol", 500, TODAY).reason == "exposure_present"
        # Messgrenze strenger als die Hausschwelle: Exposure > 0 ist nicht schluessig
        assert evaluate_criterion(s, p, "alcohol", 1000, TODAY).reason == "inconclusive_measurement"


def test_expired_evidence_counts_as_not_satisfied(SF):
    as_of = (TODAY - timedelta(days=400)).isoformat()
    _attr(SF, id="old", as_of=as_of, valid_until=default_evidence_valid_until(date.fromisoformat(as_of)).isoformat())
    with SF() as s:
        p = s.get(Product, "g1")
        result = evaluate_criterion(s, p, "tobacco", 500, TODAY)
        assert not result.satisfied and result.reason == "expired"
        # Gegenprobe: am letzten Gueltigkeitstag zaehlt derselbe Nachweis
        last_day = default_evidence_valid_until(date.fromisoformat(as_of))
        assert is_criterion_satisfied(s, p, "tobacco", 500, last_day)
        assert not is_criterion_satisfied(s, p, "tobacco", 500, last_day + timedelta(days=1))
        assert not is_criterion_satisfied(s, p, "tobacco", 500, date.fromisoformat(as_of) - timedelta(days=1))


def test_seed_values_on_product_satisfy_nothing(SF):
    product = _product(SF)
    assert (product.sfdr_class, product.esg_rating, product.climate_benchmark) == ("8", "AAA", "PAB")
    with SF() as s:
        p = s.get(Product, "g1")
        for category, threshold in (("sfdr_classification", 8), ("tobacco", 500), ("ungc_violation", None),
                                    ("impact_theme", None), ("controversial_weapons", 0)):
            result = evaluate_criterion(s, p, category, threshold, TODAY, expected_value="Klima")
            assert not result.satisfied and result.reason == "no_evidence", category
    # Gegenprobe: erst ein freigegebener Klassifikationsnachweis erfuellt SFDR 8
    _attr(SF, id="sfdr", category="sfdr_classification", kind="classification", revenue=None, value="8")
    with SF() as s:
        p = s.get(Product, "g1")
        assert is_criterion_satisfied(s, p, "sfdr_classification", 8, TODAY)
        assert not is_criterion_satisfied(s, p, "sfdr_classification", 9, TODAY)


def test_draft_and_retired_evidence_never_satisfy(SF):
    _attr(SF, id="d1", status="draft")
    _attr(SF, id="r1", status="retired", as_of=(TODAY - timedelta(days=60)).isoformat())
    with SF() as s:
        p = s.get(Product, "g1")
        result = evaluate_criterion(s, p, "tobacco", 500, TODAY)
        assert not result.satisfied and result.reason == "not_approved"


def test_tenant_overlay_is_only_visible_to_its_tenant(SF):
    _attr(SF, id="ta", tenant_id="firm-a", created_by="admin-a1", approved_by="admin-a2")
    with SF() as s:
        p = s.get(Product, "g1")
        assert is_criterion_satisfied(s, p, "tobacco", 500, TODAY, tenant_id="firm-a")
        assert not is_criterion_satisfied(s, p, "tobacco", 500, TODAY, tenant_id="firm-b")
        assert not is_criterion_satisfied(s, p, "tobacco", 500, TODAY)


def test_fail_closed_on_unknown_category_or_missing_threshold(SF):
    _attr(SF, id="a1")
    with SF() as s:
        p = s.get(Product, "g1")
        assert evaluate_criterion(s, p, "sharia", 0, TODAY).reason == "unknown_category"
        assert evaluate_criterion(s, p, "tobacco", None, TODAY).reason == "no_threshold"
        assert is_criterion_satisfied(s, p, "tobacco", 500, TODAY)


def test_ungc_exclusion_policy_without_threshold(SF):
    _attr(SF, id="u1", category="ungc_violation", revenue=None)
    with SF() as s:
        assert is_criterion_satisfied(s, s.get(Product, "g1"), "ungc_violation", None, TODAY)


def test_service_self_approval_conflict(SF):
    _attr(SF, id="d1", status="draft", created_by="root")
    with SF() as s:
        with pytest.raises(RuleApprovalConflict):
            approve_sustainability_attribute(s, attribute_id="d1", approver_id="root", tenant_id=None, now=NOW)
        attribute, previous = approve_sustainability_attribute(
            s, attribute_id="d1", approver_id="root2", tenant_id=None, now=NOW,
        )
        assert attribute.status == "approved" and attribute.approval_mode == "four_eyes" and previous == []


# ---------------------------------------------------------------------------
# API: Vier-Augen-Freigabe
# ---------------------------------------------------------------------------


def test_api_self_approval_is_409_other_admin_approves(SF, client):
    _as("admin-a1", "admin", "firm-a")
    created = client.post("/products/own-a/sustainability-attributes", json=_payload())
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "draft" and body["evidence_status"] == "draft" and body["scope"] == "tenant"
    assert body["valid_until"] == default_evidence_valid_until(date.fromisoformat(AS_OF)).isoformat()
    attr_id = body["id"]
    own = client.post(f"/products/sustainability/attributes/{attr_id}/approve")
    assert own.status_code == 409, own.text
    assert "Vier-Augen" in own.json()["detail"]
    with SF() as s:
        assert s.get(ProductSustainabilityAttribute, attr_id).status == "draft"
        assert not is_criterion_satisfied(s, s.get(Product, "own-a"), "tobacco", 500, TODAY, tenant_id="firm-a")
    # Gegenprobe: zweite Person derselben Verwaltung
    _as("admin-a2", "admin", "firm-a")
    other = client.post(f"/products/sustainability/attributes/{attr_id}/approve")
    assert other.status_code == 200, other.text
    assert other.json()["approval_mode"] == "four_eyes"
    with SF() as s:
        row = s.get(ProductSustainabilityAttribute, attr_id)
        assert (row.status, row.created_by, row.approved_by) == ("approved", "admin-a1", "admin-a2")
        assert is_criterion_satisfied(s, s.get(Product, "own-a"), "tobacco", 500, TODAY, tenant_id="firm-a")
        logs = s.query(AuditLog).filter(AuditLog.record_id == attr_id).all()
    assert {log.action for log in logs} >= {"CREATE", "UPDATE"}


def test_api_batch_approval_is_all_or_nothing(SF, client):
    _as("admin-a1", "admin", "firm-a")
    first = client.post("/products/own-a/sustainability-attributes", json=_payload()).json()["id"]
    _as("admin-a2", "admin", "firm-a")
    second = client.post("/products/own-a/sustainability-attributes",
                         json=_payload(category="alcohol", revenue_threshold_bps=1000)).json()["id"]
    r = client.post("/products/sustainability/attributes/approve", json={"attribute_ids": [first, second]})
    assert r.status_code == 409, r.text
    with SF() as s:
        assert s.get(ProductSustainabilityAttribute, first).status == "draft"


def test_api_approval_supersedes_previous_and_retire(SF, client):
    _attr(SF, id="old", product_id="own-a", tenant_id="firm-a", created_by="admin-a1", approved_by="admin-a2",
          as_of=(TODAY - timedelta(days=90)).isoformat())
    _as("admin-a1", "admin", "firm-a")
    new_id = client.post("/products/own-a/sustainability-attributes", json=_payload(revenue_threshold_bps=0)).json()["id"]
    _as("admin-a2", "admin", "firm-a")
    r = client.post(f"/products/sustainability/attributes/{new_id}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["retired_ids"] == ["old"]
    retire = client.post(f"/products/sustainability/attributes/{new_id}/retire", json={"reason": "Fonds geaendert"})
    assert retire.status_code == 200 and retire.json()["status"] == "retired"
    with SF() as s:
        assert not is_criterion_satisfied(s, s.get(Product, "own-a"), "tobacco", 500, TODAY, tenant_id="firm-a")


def test_api_draft_edit_only_by_author_and_approved_is_immutable(SF, client):
    _as("admin-a1", "admin", "firm-a")
    attr_id = client.post("/products/own-a/sustainability-attributes", json=_payload()).json()["id"]
    assert client.patch(f"/products/sustainability/attributes/{attr_id}", json={"revenue_threshold_bps": 400}).status_code == 200
    _as("admin-a2", "admin", "firm-a")
    assert client.patch(f"/products/sustainability/attributes/{attr_id}", json={"revenue_threshold_bps": 0}).status_code == 409
    assert client.post(f"/products/sustainability/attributes/{attr_id}/approve").status_code == 200
    _as("admin-a1", "admin", "firm-a")
    assert client.patch(f"/products/sustainability/attributes/{attr_id}", json={"note": "x"}).status_code == 409
    assert client.delete(f"/products/sustainability/attributes/{attr_id}").status_code == 409


# ---------------------------------------------------------------------------
# API: R3 -- Plattform-Nachweise nur super_admin (Multi-Tenant)
# ---------------------------------------------------------------------------


def test_api_tenant_admin_cannot_change_global_evidence(SF, client, monkeypatch):
    _strict(monkeypatch)
    _attr(SF, id="glob-draft", status="draft", created_by="root")
    _attr(SF, id="glob-ok", category="alcohol", revenue=1000)
    _as("admin-a1", "admin", "firm-a")
    create = client.post("/products/g1/sustainability-attributes", json=_payload(scope="global"))
    approve = client.post("/products/sustainability/attributes/glob-draft/approve")
    patch = client.patch("/products/sustainability/attributes/glob-draft", json={"note": "x"})
    retire = client.post("/products/sustainability/attributes/glob-ok/retire")
    delete = client.delete("/products/sustainability/attributes/glob-draft")
    for response in (create, approve, patch, retire, delete):
        assert response.status_code == 403, response.text
    with SF() as s:
        assert s.get(ProductSustainabilityAttribute, "glob-draft").status == "draft"
        assert s.get(ProductSustainabilityAttribute, "glob-ok").status == "approved"
        assert s.query(ProductSustainabilityAttribute).count() == 2
    # Tenant-Overlay auf dem globalen Fonds bleibt erlaubt
    overlay = client.post("/products/g1/sustainability-attributes", json=_payload())
    assert overlay.status_code == 201 and overlay.json()["tenant_id"] == "firm-a"
    # Gegenprobe: super_admin darf Plattform-Nachweise pflegen
    _as("root2", "super_admin", None)
    assert client.post("/products/sustainability/attributes/glob-draft/approve").status_code == 200
    assert client.post("/products/g1/sustainability-attributes",
                       json=_payload(scope="global", category="gambling")).status_code == 201


def test_api_tenant_evidence_isolated_between_tenants(SF, client, monkeypatch):
    _strict(monkeypatch)
    _as("admin-a1", "admin", "firm-a")
    attr_id = client.post("/products/g1/sustainability-attributes", json=_payload()).json()["id"]
    _as("admin-b", "admin", "firm-b")
    assert attr_id not in {row["id"] for row in client.get("/products/g1/sustainability-attributes").json()}
    assert client.post(f"/products/sustainability/attributes/{attr_id}/approve").status_code == 404
    assert client.post("/products/own-a/sustainability-attributes", json=_payload()).status_code == 404


def test_api_global_scope_rejected_for_tenant_product(SF, client):
    _as("root", "super_admin", None)
    r = client.post("/products/own-a/sustainability-attributes", json=_payload(scope="global"))
    assert r.status_code in (404, 422), r.text


# ---------------------------------------------------------------------------
# API: Validierung, Import, Export
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("override", [
    {"source_type": "seed"},
    {"source_reference": ""},
    {"category": "sharia"},
    {"kind": "classification"},
    {"revenue_threshold_bps": None},
    {"revenue_threshold_bps": 10001},
    {"as_of": (TODAY + timedelta(days=1)).isoformat()},
    {"valid_until": (date.fromisoformat(AS_OF) + timedelta(days=400)).isoformat()},
    {"source_type": "data_vendor"},
    {"kind": "measured_exposure"},
])
def test_api_rejects_invalid_or_unsourced_evidence(SF, client, override):
    _as("admin-a1", "admin", "firm-a")
    r = client.post("/products/own-a/sustainability-attributes", json=_payload(**override))
    assert r.status_code == 422, r.text


def test_api_data_vendor_requires_provider_and_retrieval_date(SF, client):
    _as("admin-a1", "admin", "firm-a")
    r = client.post("/products/own-a/sustainability-attributes", json=_payload(
        source_type="data_vendor", source_provider="Anbieter X", source_retrieved_on=AS_OF,
        source_reference="Export 2026-10"))
    assert r.status_code == 201, r.text


def test_api_json_import_creates_drafts_only_and_reports_rows(SF, client):
    _as("admin-a1", "admin", "firm-a")
    r = client.post("/products/sustainability/attributes/import", json={"attributes": [
        dict(_payload(), product_id="own-a"),
        dict(_payload(category="controversial_weapons", revenue_threshold_bps=0), isin="IE00B4L5Y983"),
        dict(_payload(category="alcohol", revenue_threshold_bps=None), product_id="own-a"),
        dict(_payload(), product_id="does-not-exist"),
    ]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["processed"], body["created"], body["failed"]) == (4, 2, 2)
    with SF() as s:
        rows = s.query(ProductSustainabilityAttribute).all()
        assert len(rows) == 2 and {row.status for row in rows} == {"draft"}
        assert {row.created_by for row in rows} == {"admin-a1"}
        assert not any(is_criterion_satisfied(s, s.get(Product, row.product_id), row.category,
                                              row.revenue_threshold_bps, TODAY, tenant_id="firm-a") for row in rows)


def test_api_json_import_rejects_seed_source_type(SF, client):
    _as("admin-a1", "admin", "firm-a")
    r = client.post("/products/sustainability/attributes/import", json={"attributes": [
        dict(_payload(source_type="seed"), product_id="own-a"),
    ]})
    assert r.status_code == 422


def test_api_csv_import_and_export_roundtrip(SF, client):
    _as("admin-a1", "admin", "firm-a")
    csv_text = (
        "product_id;category;kind;revenue_threshold_bps;source_type;source_reference;as_of\n"
        f"own-a;tobacco;exclusion_policy;500;kid;KID Abschnitt 3;{AS_OF}\n"
        f"own-a;gambling;exclusion_policy;;kid;KID Abschnitt 3;{AS_OF}\n"
        f"own-a;sfdr_classification;classification;;kid;KID S. 1;{AS_OF}\n"
    )
    r = client.post("/products/sustainability/attributes/import/csv",
                    files={"file": ("n.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")})
    assert r.status_code == 201, r.text
    assert (r.json()["created"], r.json()["failed"]) == (1, 2)
    export = client.get("/products/sustainability/attributes/export")
    assert export.status_code == 200
    lines = export.text.strip().splitlines()
    assert lines[0].startswith("product_id,isin,scope,category,kind")
    assert len(lines) == 2 and ",tobacco,exclusion_policy,500," in lines[1] and ",draft," in lines[1]
    as_json = client.get("/products/sustainability/attributes/export?format=json").json()
    assert as_json["attributes"][0]["status"] == "draft"
    queue = client.get("/products/sustainability/attributes?status=draft").json()
    assert len(queue) == 1


# ---------------------------------------------------------------------------
# Hausstandard je Tenant (T-E1)
# ---------------------------------------------------------------------------


T_E1 = {
    "controversial_weapons": 0, "conventional_weapons": 1000, "weapons": 1000, "tobacco": 500, "thermal_coal": 1000,
    "gambling": 500, "adult_entertainment": 500, "alcohol": 1000, "ungc_violation": None,
    "nuclear_power": 1000, "animal_testing": 1000, "fossil_fuels": 1000,
}


def test_house_standard_defaults_follow_t_e1_and_are_tenant_changeable(SF, client):
    _as("admin-a1", "admin", "firm-a")
    items = {i["category"]: i for i in client.get("/products/sustainability/standards").json()["items"]}
    assert {c: i["effective_threshold_bps"] for c, i in items.items()} == T_E1
    r = client.put("/products/sustainability/standards/tobacco", json={"max_revenue_threshold_bps": 0, "note": "streng"})
    assert r.status_code == 200, r.text
    after = {i["category"]: i for i in r.json()["items"]}
    assert after["tobacco"]["effective_threshold_bps"] == 0 and after["tobacco"]["is_overridden"]
    _as("admin-b", "admin", "firm-b")
    other = {i["category"]: i for i in client.get("/products/sustainability/standards").json()["items"]}
    assert other["tobacco"]["effective_threshold_bps"] == 500, "andere Verwaltung unveraendert"
    with SF() as s:
        audit = s.query(AuditLog).filter(AuditLog.table_name == "sustainability_exclusion_standards").all()
    assert len(audit) == 1 and audit[0].old_value == "default:500" and audit[0].new_value == "tenant:0;mode=tightening"
    _as("admin-a1", "admin", "firm-a")
    # Reset nach Verschaerfung ist eine Lockerung (N-863-5): Entwurf, zweite Person gibt frei
    reset = client.delete("/products/sustainability/standards/tobacco")
    assert {i["category"]: i["effective_threshold_bps"] for i in reset.json()["items"]}["tobacco"] == 0
    _as("admin-a2", "admin", "firm-a")
    approved = client.post("/products/sustainability/standards/tobacco/approve")
    assert {i["category"]: i["effective_threshold_bps"] for i in approved.json()["items"]}["tobacco"] == 500


@pytest.mark.parametrize("category,body", [
    ("ungc_violation", {"max_revenue_threshold_bps": 100}),
    ("tobacco", {"max_revenue_threshold_bps": None}),
    ("sfdr_classification", {"max_revenue_threshold_bps": 1}),
    ("tobacco", {"max_revenue_threshold_bps": 10001}),
])
def test_house_standard_validation(SF, client, category, body):
    _as("admin-a1", "admin", "firm-a")
    assert client.put(f"/products/sustainability/standards/{category}", json=body).status_code == 422


def test_house_standard_requires_admin(SF, client):
    _as("adv-a", "advisor", "firm-a")
    assert client.put("/products/sustainability/standards/tobacco", json={"max_revenue_threshold_bps": 0}).status_code == 403
    assert client.get("/products/sustainability/standards").status_code == 200


# ---------------------------------------------------------------------------
# Katalog-Sync Schema (OpenAPI) <-> Modell
# ---------------------------------------------------------------------------


def test_catalog_literals_match_model_constants(client):
    assert typing.get_args(review_schemas.SustainabilityCategory) == catalog.SUSTAINABILITY_CATEGORIES
    assert typing.get_args(review_schemas.SustainabilityKind) == catalog.SUSTAINABILITY_KINDS
    assert typing.get_args(review_schemas.SustainabilitySourceType) == catalog.SUSTAINABILITY_SOURCE_TYPES
    assert typing.get_args(review_schemas.SustainabilityStatus) == catalog.SUSTAINABILITY_STATUSES
    assert set(catalog.SUSTAINABILITY_KINDS_BY_CATEGORY) == set(catalog.SUSTAINABILITY_CATEGORIES)
    assert "seed" not in catalog.SUSTAINABILITY_SOURCE_TYPES
    _as("admin-a1", "admin", "firm-a")
    cat = client.get("/products/sustainability/catalog").json()
    assert [c["category"] for c in cat["categories"]] == list(catalog.SUSTAINABILITY_CATEGORIES)
    assert cat["evidence_validity_months"] == 12


def test_api_csv_export_neutralises_formula_cells(SF, client):
    _as("admin-a1", "admin", "firm-a")
    for idx, ref in enumerate(("=HYPERLINK(\"http://x\")", "+SUM(A1)", "@cmd", "-1+1")):
        body = _payload(category=("tobacco", "alcohol", "gambling", "thermal_coal")[idx], source_reference=ref)
        assert client.post("/products/own-a/sustainability-attributes", json=body).status_code == 201
    text = client.get("/products/sustainability/attributes/export").text
    for ref in ("'=HYPERLINK", "'+SUM(A1)", "'@cmd", "'-1+1"):
        assert ref in text, ref
    for raw in (",=HYPERLINK", ",+SUM", ",@cmd", ",-1+1"):
        assert raw not in text, raw


def test_api_409_never_leaks_other_tenant_evidence(SF, client, monkeypatch):
    _strict(monkeypatch)
    _as("admin-b", "admin", "firm-b")
    foreign = client.post("/products/g1/sustainability-attributes",
                          json=_payload(source_reference="Geheimes Dokument Firma B", note="nur B"))
    assert foreign.status_code == 201
    foreign_id = foreign.json()["id"]
    _as("admin-a1", "admin", "firm-a")
    # Gleicher Schluessel wie der Nachweis von Firma B: kein Konflikt (eigener Scope)
    first = client.post("/products/g1/sustainability-attributes", json=_payload())
    assert first.status_code == 201, first.text
    dup = client.post("/products/g1/sustainability-attributes", json=_payload())
    assert dup.status_code == 409
    detail = dup.text
    for secret in (foreign_id, "Geheimes Dokument", "nur B", "firm-b", "admin-b"):
        assert secret not in detail, secret
    # Freigabe-Konflikt eines fremden Nachweises: 404 statt 409, ohne Inhalte
    r = client.post(f"/products/sustainability/attributes/{foreign_id}/approve")
    assert r.status_code == 404 and "Geheimes" not in r.text
    # Import-Konflikt meldet ebenfalls nichts aus Firma B
    imp = client.post("/products/sustainability/attributes/import",
                      json={"attributes": [dict(_payload(), product_id="g1")]}).json()
    assert imp["failed"] == 1 and foreign_id not in str(imp) and "Geheimes" not in str(imp)


# ---------------------------------------------------------------------------
# N-863-1: Widerspruechliche Nachweise -- eine belegte Exposure blockiert immer
# ---------------------------------------------------------------------------


def _negative_measurement(SF, *, id, tenant_id=None, created_by="root", approved_by="root2"):
    _attr(SF, id=id, tenant_id=tenant_id, kind="measured_exposure", revenue=500, measured=300,
          created_by=created_by, approved_by=approved_by)


def test_n863_1_p1_same_scope_policy_and_negative_measurement(SF):
    _attr(SF, id="policy")
    with SF() as s:
        assert is_criterion_satisfied(s, s.get(Product, "g1"), "tobacco", 500, TODAY)  # Gegenprobe ohne Messung
    _negative_measurement(SF, id="meas")
    with SF() as s:
        result = evaluate_criterion(s, s.get(Product, "g1"), "tobacco", 500, TODAY)
    assert not result.satisfied and result.reason == "conflicting_evidence"


def test_n863_1_p2_global_policy_tenant_negative_measurement(SF):
    _attr(SF, id="policy")
    _negative_measurement(SF, id="meas-a", tenant_id="firm-a", created_by="admin-a1", approved_by="admin-a2")
    with SF() as s:
        p = s.get(Product, "g1")
        assert evaluate_criterion(s, p, "tobacco", 500, TODAY, tenant_id="firm-a").reason == "conflicting_evidence"
        # Gegenprobe: fuer einen anderen Tenant ist die Messung unsichtbar
        assert is_criterion_satisfied(s, p, "tobacco", 500, TODAY, tenant_id="firm-b")


def test_n863_1_p3_global_negative_measurement_tenant_policy(SF):
    _negative_measurement(SF, id="meas")
    _attr(SF, id="policy-a", tenant_id="firm-a", created_by="admin-a1", approved_by="admin-a2")
    with SF() as s:
        p = s.get(Product, "g1")
        assert evaluate_criterion(s, p, "tobacco", 500, TODAY, tenant_id="firm-a").reason == "conflicting_evidence"
        assert evaluate_criterion(s, p, "tobacco", 500, TODAY, tenant_id="firm-b").reason == "exposure_present"


def test_n863_1_only_valid_approved_measurement_blocks(SF):
    _attr(SF, id="policy")
    _attr(SF, id="draft-meas", kind="measured_exposure", revenue=500, measured=300, status="draft")
    old = (TODAY - timedelta(days=400)).isoformat()
    _attr(SF, id="old-meas", kind="measured_exposure", revenue=500, measured=300, as_of=old)
    _attr(SF, id="loose-meas", kind="measured_exposure", revenue=100, measured=300,
          as_of=(TODAY - timedelta(days=10)).isoformat())
    with SF() as s:
        result = evaluate_criterion(s, s.get(Product, "g1"), "tobacco", 500, TODAY)
    assert result.satisfied, result


def test_n863_1_conduct_measurement_blocks_policy(SF):
    _attr(SF, id="ungc-policy", category="ungc_violation", revenue=None)
    _attr(SF, id="ungc-meas", category="ungc_violation", kind="measured_exposure", revenue=None, measured=50)
    with SF() as s:
        assert evaluate_criterion(s, s.get(Product, "g1"), "ungc_violation", None, TODAY).reason == "conflicting_evidence"


# ---------------------------------------------------------------------------
# N-863-2: impact_theme nur mit Sollthema
# ---------------------------------------------------------------------------


def test_n863_2_impact_theme_requires_expected_theme(SF):
    _attr(SF, id="theme", category="impact_theme", kind="classification", revenue=None, value="Wasser")
    with SF() as s:
        p = s.get(Product, "g1")
        assert evaluate_criterion(s, p, "impact_theme", None, TODAY).reason == "no_expected_value"
        assert evaluate_criterion(s, p, "impact_theme", None, TODAY, expected_value="Klima").reason == "value_mismatch"
        # Gegenprobe: passendes Thema (normalisiert) erfuellt
        assert is_criterion_satisfied(s, p, "impact_theme", None, TODAY, expected_value="  wasser ")


# ---------------------------------------------------------------------------
# H-4: Kategorie-Hierarchie -- "Waffen" deckt "kontroverse Waffen", nicht umgekehrt
# ---------------------------------------------------------------------------


def test_h4_weapons_policy_covers_controversial_and_conventional(SF):
    _attr(SF, id="weapons", category="weapons", revenue=0)
    with SF() as s:
        p = s.get(Product, "g1")
        assert is_criterion_satisfied(s, p, "controversial_weapons", 0, TODAY)
        assert is_criterion_satisfied(s, p, "conventional_weapons", 1000, TODAY)
        assert is_criterion_satisfied(s, p, "weapons", 1000, TODAY)


def test_h4_parent_policy_still_needs_child_threshold(SF):
    _attr(SF, id="weapons", category="weapons", revenue=500)
    with SF() as s:
        p = s.get(Product, "g1")
        assert not is_criterion_satisfied(s, p, "controversial_weapons", 0, TODAY)
        assert is_criterion_satisfied(s, p, "conventional_weapons", 1000, TODAY)


def test_h4_child_does_not_cover_parent(SF):
    _attr(SF, id="contro", category="controversial_weapons", revenue=0)
    with SF() as s:
        p = s.get(Product, "g1")
        assert is_criterion_satisfied(s, p, "controversial_weapons", 0, TODAY)
        assert not is_criterion_satisfied(s, p, "weapons", 1000, TODAY)
        assert not is_criterion_satisfied(s, p, "conventional_weapons", 1000, TODAY)


def test_h4_child_measurement_still_blocks_parent_policy(SF):
    _attr(SF, id="weapons", category="weapons", revenue=0)
    _attr(SF, id="contro-meas", category="controversial_weapons", kind="measured_exposure", revenue=0, measured=20)
    with SF() as s:
        assert evaluate_criterion(s, s.get(Product, "g1"), "controversial_weapons", 0, TODAY).reason == "conflicting_evidence"


def test_h4_hierarchy_constant_is_consistent():
    for child, parents in catalog.SUSTAINABILITY_CATEGORY_COVERED_BY.items():
        assert child in catalog.SUSTAINABILITY_CATEGORIES
        for parent in parents:
            assert parent in catalog.SUSTAINABILITY_REVENUE_CATEGORIES and parent != child
            assert child not in catalog.SUSTAINABILITY_CATEGORY_COVERED_BY.get(parent, ())


# ---------------------------------------------------------------------------
# H-1: Lockerung des Hausstandards unter T-E1 nur mit Vier-Augen-Freigabe
# ---------------------------------------------------------------------------


def _std(client):
    return {i["category"]: i for i in client.get("/products/sustainability/standards").json()["items"]}


def test_h1_loosening_needs_four_eyes_and_tightening_is_immediate(SF, client):
    from services.product_eligibility_governance import effective_sustainability_standard

    _as("admin-a1", "admin", "firm-a")
    r = client.put("/products/sustainability/standards/tobacco", json={"max_revenue_threshold_bps": 1000})
    assert r.status_code == 200, r.text
    item = {i["category"]: i for i in r.json()["items"]}["tobacco"]
    assert item["effective_threshold_bps"] == 500 and item["pending"]["max_revenue_threshold_bps"] == 1000
    own = client.post("/products/sustainability/standards/tobacco/approve")
    assert own.status_code == 409 and "Vier-Augen" in own.json()["detail"]
    assert _std(client)["tobacco"]["effective_threshold_bps"] == 500
    with SF() as s:
        before_approval = NOW_TS()
    _as("admin-a2", "admin", "firm-a")
    ok = client.post("/products/sustainability/standards/tobacco/approve")
    assert ok.status_code == 200, ok.text
    tob = {i["category"]: i for i in ok.json()["items"]}["tobacco"]
    assert tob["effective_threshold_bps"] == 1000 and tob["approval_mode"] == "four_eyes"
    assert tob["approved_by"] == "admin-a2" and tob["valid_from"] and tob["pending"] is None
    with SF() as s:
        past = effective_sustainability_standard(s, "firm-a", "tobacco", as_of=before_approval)
        assert past["effective_threshold_bps"] == 500, "Point-in-Time vor der Freigabe = Default"
    # Verschaerfung wirkt sofort, ohne zweite Person
    _as("admin-a1", "admin", "firm-a")
    tight = client.put("/products/sustainability/standards/tobacco", json={"max_revenue_threshold_bps": 0})
    tob = {i["category"]: i for i in tight.json()["items"]}["tobacco"]
    assert tob["effective_threshold_bps"] == 0 and tob["approval_mode"] == "immediate_tightening"
    # Gleich dem Default ist keine Lockerung
    same = client.put("/products/sustainability/standards/alcohol", json={"max_revenue_threshold_bps": 1000})
    assert {i["category"]: i for i in same.json()["items"]}["alcohol"]["pending"] is None


def test_h1_disabling_a_category_is_a_loosening(SF, client):
    _as("admin-a1", "admin", "firm-a")
    r = client.put("/products/sustainability/standards/controversial_weapons", json={"is_disabled": True})
    item = {i["category"]: i for i in r.json()["items"]}["controversial_weapons"]
    assert not item["is_disabled"] and item["effective_threshold_bps"] == 0 and item["pending"]["is_disabled"]
    r = client.put("/products/sustainability/standards/ungc_violation", json={"is_disabled": True})
    assert {i["category"]: i for i in r.json()["items"]}["ungc_violation"]["pending"]["is_disabled"]
    _as("admin-a2", "admin", "firm-a")
    approved = _std_after(client, "controversial_weapons")
    assert approved["is_disabled"] and approved["effective_threshold_bps"] is None
    # verwerfen statt freigeben
    discarded = client.delete("/products/sustainability/standards/ungc_violation/pending")
    assert {i["category"]: i for i in discarded.json()["items"]}["ungc_violation"]["pending"] is None


def _std_after(client, category):
    r = client.post(f"/products/sustainability/standards/{category}/approve")
    assert r.status_code == 200, r.text
    return {i["category"]: i for i in r.json()["items"]}[category]


def test_h1_approve_without_pending_is_409(SF, client):
    _as("admin-a1", "admin", "firm-a")
    assert client.post("/products/sustainability/standards/tobacco/approve").status_code == 409


def NOW_TS():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ---------------------------------------------------------------------------
# FINMA-Kundenanzeige: Dokumentidentitaet und neutrale Quellbezeichnung
# ---------------------------------------------------------------------------


def test_finma_document_identity_and_neutral_client_label(SF, client):
    _as("admin-a1", "admin", "firm-a")
    r = client.post("/products/own-a/sustainability-attributes", json=_payload(
        source_document_title="Fondsvertrag Teilvermoegen A", source_document_version="2026-06",
        source_document_date=AS_OF, source_document_sha256="AB" * 32))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["client_source_label"] == "Fondsvertrag", "Default aus dem Quellentyp"
    assert body["source_document_sha256"] == "ab" * 32 and body["source_document_version"] == "2026-06"
    # Quellentyp geaendert -> abgeleitete Bezeichnung folgt
    p = client.patch(f"/products/sustainability/attributes/{body['id']}", json={"source_type": "kid"})
    assert p.status_code == 200 and p.json()["client_source_label"] == "Basisinformationsblatt"
    export = client.get("/products/sustainability/attributes/export").text.splitlines()[0]
    assert "client_source_label" in export and "source_document_sha256" in export


@pytest.mark.parametrize("override", [
    {"source_document_sha256": "zz" * 32},
    {"source_document_sha256": "ab"},
    {"source_document_date": (TODAY + timedelta(days=1)).isoformat()},
    {"source_type": "data_vendor", "source_provider": "Anbieter X", "source_retrieved_on": AS_OF,
     "client_source_label": "Daten von Anbieter X"},
])
def test_finma_fields_validation(SF, client, override):
    _as("admin-a1", "admin", "firm-a")
    assert client.post("/products/own-a/sustainability-attributes", json=_payload(**override)).status_code == 422


def test_finma_custom_neutral_label_kept(SF, client):
    _as("admin-a1", "admin", "firm-a")
    r = client.post("/products/own-a/sustainability-attributes", json=_payload(
        source_type="data_vendor", source_provider="Anbieter X", source_retrieved_on=AS_OF,
        client_source_label="Externer Datenanbieter, Stand Q2"))
    assert r.status_code == 201 and r.json()["client_source_label"] == "Externer Datenanbieter, Stand Q2"


def test_csv_reimport_of_own_export_removes_guard_apostrophe(SF, client):
    _as("admin-a1", "admin", "firm-a")
    created = client.post("/products/own-a/sustainability-attributes",
                          json=_payload(source_reference="=HYPERLINK(1)", note="@intern"))
    assert created.status_code == 201
    exported = client.get("/products/sustainability/attributes/export").text
    assert "'=HYPERLINK(1)" in exported
    # Retire-frei: Entwurf loeschen, dann eigenen Export wieder einlesen
    assert client.delete(f"/products/sustainability/attributes/{created.json()['id']}").status_code == 204
    r = client.post("/products/sustainability/attributes/import/csv",
                    files={"file": ("x.csv", io.BytesIO(exported.encode("utf-8")), "text/csv")})
    assert r.status_code == 201 and r.json()["created"] == 1, r.text
    with SF() as s:
        row = s.query(ProductSustainabilityAttribute).one()
    assert row.source_reference == "=HYPERLINK(1)" and row.note == "@intern"


# ---------------------------------------------------------------------------
# N-863-3: Audit-Hash-Kette bleibt nach Einzel- und Sammelfreigabe mit Abloesung intakt
# ---------------------------------------------------------------------------


def test_n863_3_audit_chain_intact_after_approvals_with_supersession(SF, client):
    from services.audit import verify_audit_chain

    _attr(SF, id="old-tob", product_id="own-a", tenant_id="firm-a", created_by="admin-a1", approved_by="admin-a2",
          as_of=(TODAY - timedelta(days=90)).isoformat())
    _attr(SF, id="old-alc", product_id="own-a", tenant_id="firm-a", category="alcohol", revenue=1000,
          created_by="admin-a1", approved_by="admin-a2", as_of=(TODAY - timedelta(days=90)).isoformat())
    _attr(SF, id="old-gam", product_id="own-a", tenant_id="firm-a", category="gambling", revenue=500,
          created_by="admin-a1", approved_by="admin-a2", as_of=(TODAY - timedelta(days=90)).isoformat())
    _as("admin-a1", "admin", "firm-a")
    single = client.post("/products/own-a/sustainability-attributes", json=_payload(revenue_threshold_bps=0)).json()["id"]
    batch = [
        client.post("/products/own-a/sustainability-attributes",
                    json=_payload(category=cat, revenue_threshold_bps=0)).json()["id"]
        for cat in ("alcohol", "gambling")
    ]
    _as("admin-a2", "admin", "firm-a")
    one = client.post(f"/products/sustainability/attributes/{single}/approve")
    assert one.status_code == 200 and one.json()["retired_ids"] == ["old-tob"]
    many = client.post("/products/sustainability/attributes/approve", json={"attribute_ids": batch})
    assert many.status_code == 200 and sorted(many.json()["retired_ids"]) == ["old-alc", "old-gam"]
    with SF() as s:
        result = verify_audit_chain(s)
    assert result["ok"], result


# ---------------------------------------------------------------------------
# N-863-4: Grenzen-Regel -- Messung (c_m, Exposure > 0) widerlegt jeden Nachweis mit Grenze <= c_m
# ---------------------------------------------------------------------------


def test_n863_4_p5_zero_policy_refuted_by_measurement_above_one_percent(SF):
    _attr(SF, id="policy0", revenue=0)
    with SF() as s:
        assert is_criterion_satisfied(s, s.get(Product, "g1"), "tobacco", 500, TODAY)  # Gegenprobe ohne Messung
    _attr(SF, id="meas1", kind="measured_exposure", revenue=100, measured=300)
    with SF() as s:
        result = evaluate_criterion(s, s.get(Product, "g1"), "tobacco", 500, TODAY)
    assert not result.satisfied and result.reason == "conflicting_evidence"


def test_n863_4_p6_two_measurements_same_cutoff_contradict(SF):
    _attr(SF, id="meas-zero", kind="measured_exposure", revenue=100, measured=0)
    with SF() as s:
        assert is_criterion_satisfied(s, s.get(Product, "g1"), "tobacco", 500, TODAY, tenant_id="firm-a")
    _attr(SF, id="meas-pos", tenant_id="firm-a", kind="measured_exposure", revenue=100, measured=300,
          created_by="admin-a1", approved_by="admin-a2")
    with SF() as s:
        p = s.get(Product, "g1")
        assert evaluate_criterion(s, p, "tobacco", 500, TODAY, tenant_id="firm-a").reason == "conflicting_evidence"
        assert is_criterion_satisfied(s, p, "tobacco", 500, TODAY, tenant_id="firm-b")


def test_n863_4_p4_stricter_cutoff_measurement_is_only_a_hint(SF):
    _attr(SF, id="policy5", revenue=500)
    _attr(SF, id="meas-any", kind="measured_exposure", revenue=0, measured=300)
    with SF() as s:
        result = evaluate_criterion(s, s.get(Product, "g1"), "tobacco", 500, TODAY)
    assert result.satisfied and result.attribute_id == "policy5"
    assert "inconclusive_measurement" in result.candidate_reasons


def test_n863_4_parent_policy_refuted_by_child_measurement_at_its_cutoff(SF):
    _attr(SF, id="weapons0", category="weapons", revenue=0)
    _attr(SF, id="contro-meas", category="controversial_weapons", kind="measured_exposure", revenue=100, measured=20)
    with SF() as s:
        result = evaluate_criterion(s, s.get(Product, "g1"), "controversial_weapons", 500, TODAY)
    assert not result.satisfied and result.reason == "conflicting_evidence"


# ---------------------------------------------------------------------------
# N-863-5: Lockerung relativ zur GELTENDEN Version, Audit wahrheitsgemaess
# ---------------------------------------------------------------------------


def _std_audit(SF):
    with SF() as s:
        rows = s.query(AuditLog).filter(AuditLog.table_name == "sustainability_exclusion_standards").all()
    return sorted((r.created_at, r.new_value) for r in rows)


def test_n863_5_relaxation_back_to_default_after_tightening_needs_four_eyes(SF, client):
    _as("admin-a1", "admin", "firm-a")
    client.put("/products/sustainability/standards/tobacco", json={"max_revenue_threshold_bps": 300})
    assert _std(client)["tobacco"]["effective_threshold_bps"] == 300
    back = client.put("/products/sustainability/standards/tobacco", json={"max_revenue_threshold_bps": 500})
    item = {i["category"]: i for i in back.json()["items"]}["tobacco"]
    assert item["effective_threshold_bps"] == 300, "Lockerung gegenueber 3 % wirkt nicht sofort"
    assert item["pending"]["max_revenue_threshold_bps"] == 500
    assert client.post("/products/sustainability/standards/tobacco/approve").status_code == 409
    modes = [v for _t, v in _std_audit(SF)]
    assert modes[0] == "tenant:300;mode=tightening"
    assert modes[1].startswith("pending:tenant:500;mode=relaxation_draft")
    _as("admin-a2", "admin", "firm-a")
    ok = client.post("/products/sustainability/standards/tobacco/approve")
    assert {i["category"]: i for i in ok.json()["items"]}["tobacco"]["effective_threshold_bps"] == 500
    assert "mode=relaxation_approved" in _std_audit(SF)[-1][1]


def test_n863_5_delete_after_tightening_is_a_draft(SF, client):
    _as("admin-a1", "admin", "firm-a")
    client.put("/products/sustainability/standards/tobacco", json={"max_revenue_threshold_bps": 300})
    reset = client.delete("/products/sustainability/standards/tobacco")
    item = {i["category"]: i for i in reset.json()["items"]}["tobacco"]
    assert item["effective_threshold_bps"] == 300 and item["pending"]["max_revenue_threshold_bps"] == 500
    assert "mode=relaxation_draft" in _std_audit(SF)[-1][1]
    # Gegenprobe: Reset einer gelockerten Version ist eine Verschaerfung und wirkt sofort
    _as("admin-a2", "admin", "firm-a")
    client.post("/products/sustainability/standards/tobacco/approve")
    client.put("/products/sustainability/standards/tobacco", json={"max_revenue_threshold_bps": 800})
    _as("admin-a1", "admin", "firm-a")
    client.post("/products/sustainability/standards/tobacco/approve")
    assert _std(client)["tobacco"]["effective_threshold_bps"] == 800
    reset = client.delete("/products/sustainability/standards/tobacco")
    assert {i["category"]: i for i in reset.json()["items"]}["tobacco"]["effective_threshold_bps"] == 500
    assert "mode=tightening" in _std_audit(SF)[-1][1]


def test_n863_5_unchanged_value_creates_no_version(SF, client):
    _as("admin-a1", "admin", "firm-a")
    client.put("/products/sustainability/standards/tobacco", json={"max_revenue_threshold_bps": 300})
    client.put("/products/sustainability/standards/tobacco", json={"max_revenue_threshold_bps": 300})
    assert len(_std_audit(SF)) == 1
