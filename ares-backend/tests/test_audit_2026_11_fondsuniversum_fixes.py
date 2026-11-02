"""Audit 2026-11 / 03 (Fondsuniversum und Eingrenzung): Regressionstests.

Uebernimmt die Reproduzenten R1, R3, R5, R6 und R7 aus Anhang A des
Audit-Berichts als regulaere Tests, mit umgedrehten Erwartungen (der
Reproducer assertete den fehlerhaften Ist-Zustand). R2, R4, R8 und R9 sind
Owner-Entscheide und bewusst nicht Teil dieser Datei.

Isolation: jede Testfunktion hat eine eigene SQLite-Datei unter tmp_path
(session_factory aus test_rec001_cross_tenant_product_visibility); die
TestClient-Lifespan laeuft gegen die per conftest isolierte DB_PATH.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "tests"))

import test_rec001_cross_tenant_product_visibility as h  # noqa: E402
from database import get_db  # noqa: E402
from main import app  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.product_eligibility import ProductEligibilityRule  # noqa: E402
from models.review import AuditLog, Product, ProductUniverseEntry  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import get_current_user  # noqa: E402
from services.portfolio_engine import ensure_default_products, generate_recommendation_run  # noqa: E402
from services.portfolio_engine_payload import UNIVERSE_EMPTIED_WARNING  # noqa: E402

session_factory = h.session_factory  # fixture re-export

UNIVERSE_WARNING_MARKER = UNIVERSE_EMPTIED_WARNING.split("{jurisdiction}")[0]


def _gen(SF, mid, adv):
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        res = generate_recommendation_run(s, mandate, adv, preferences=None)
        s.commit()
    return res


@pytest.fixture()
def client(session_factory):
    def override_db():
        with session_factory() as s:
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


def _two_tenants_and_global_product(session_factory):
    now = h._now()
    with session_factory() as s:
        for tid in ("firm-a", "firm-b"):
            s.add(Tenant(id=tid, display_name=tid, slug=tid, hosting_tier="tier2",
                         license_status="active", is_active=1, created_at=now, updated_at=now))
        s.add(Product(id="g1", product_name="Globaler Fonds", asset_class="Aktien", product_type="ETF",
                      currency="CHF", ter_bps=20, is_active=1, created_at=now, updated_at=now))
        s.add(Product(id="own-a", product_name="Eigener Fonds A", asset_class="Aktien", product_type="Fonds",
                      currency="CHF", ter_bps=30, is_active=1, tenant_id="firm-a",
                      created_at=now, updated_at=now))
        s.commit()


# --- R1: Deaktivierter globaler Katalog wird nicht neu angelegt ------------
def test_r1_deactivated_global_catalog_is_not_reseeded(session_factory):
    m = h._seed_mandate(session_factory, suffix="r1", tenant_id="tenant-r1")
    _gen(session_factory, m["mandate_id"], m["advisor_id"])
    with session_factory() as s:
        global_ids_before = {p.id for p in s.query(Product).filter(Product.tenant_id.is_(None)).all()}
        for p in s.query(Product).filter(Product.tenant_id.is_(None)).all():
            p.is_active = 0
        s.commit()
    assert global_ids_before
    h._add_cheap_private_product(session_factory, product_id="own-r1", tenant_id="tenant-r1")
    try:
        _gen(session_factory, m["mandate_id"], m["advisor_id"])
    except Exception:  # noqa: BLE001 -- ein Abbruch mangels Produkten ist zulaessig, ein Reseed nicht
        pass
    with session_factory() as s:
        ensure_default_products(s, jurisdiction="CH")  # auch der direkte Startpfad seedet nicht
        s.commit()
        global_after = s.query(Product).filter(Product.tenant_id.is_(None)).all()
    assert {p.id for p in global_after} == global_ids_before, "kein Duplikat-Katalog, gleiche IDs"
    assert all(p.is_active == 0 for p in global_after), "deaktivierte Katalogfonds bleiben deaktiviert"


def test_r1_fresh_database_still_seeds_once(session_factory):
    with session_factory() as s:
        ensure_default_products(s, jurisdiction="CH")
        s.commit()
        first = s.query(Product).filter(Product.tenant_id.is_(None)).count()
        ensure_default_products(s, jurisdiction="CH")
        s.commit()
        second = s.query(Product).filter(Product.tenant_id.is_(None)).count()
    assert first > 0 and second == first


# --- R3: Tenant-Admin darf globale Produkte nicht aendern ------------------
def test_r3_tenant_admin_cannot_mutate_global_product(session_factory, client, monkeypatch):
    _strict(monkeypatch)
    _two_tenants_and_global_product(session_factory)
    _as("admin-a", "admin", "firm-a")
    r = client.put("/products/g1", json={"ter_bps": 999, "is_active": 0})
    r_override = client.put("/products/g1/market-override", json={"lookup_symbol_override": "X"})
    _as("adv-b", "advisor", "firm-b")
    seen_b = [p for p in client.get("/products").json() if p["id"] == "g1"]
    with session_factory() as s:
        g = s.get(Product, "g1")
        state = (g.ter_bps, g.is_active, g.lookup_symbol_override)
    assert r.status_code == 403, r.text
    assert "Globale Katalogfonds" in r.json()["detail"]
    assert r_override.status_code == 403, r_override.text
    assert state == (20, 1, None)
    assert seen_b, "firm-b sieht den globalen Fonds weiterhin"


def test_r3_tenant_admin_can_still_edit_own_product(session_factory, client, monkeypatch):
    _strict(monkeypatch)
    _two_tenants_and_global_product(session_factory)
    _as("admin-a", "admin", "firm-a")
    r = client.put("/products/own-a", json={"ter_bps": 25})
    assert r.status_code == 200, r.text
    assert r.json()["ter_bps"] == 25


def test_r3_super_admin_may_edit_global_product(session_factory, client, monkeypatch):
    _strict(monkeypatch)
    _two_tenants_and_global_product(session_factory)
    _as("root", "super_admin", None)
    r = client.put("/products/g1", json={"ter_bps": 22})
    assert r.status_code == 200, r.text
    with session_factory() as s:
        assert s.get(Product, "g1").ter_bps == 22


def test_r3_batch_write_pool_excludes_global_catalog_for_tenant_admin(session_factory, monkeypatch):
    _strict(monkeypatch)
    _two_tenants_and_global_product(session_factory)
    from routers.review import _writable_products_query
    admin_a = User(id="admin-a", username="admin-a", password_hash="h", full_name="a",
                   role="admin", is_active=1, tenant_id="firm-a")
    root = User(id="root", username="root", password_hash="h", full_name="r",
                role="super_admin", is_active=1, tenant_id=None)
    with session_factory() as s:
        assert {p.id for p in _writable_products_query(s, admin_a).all()} == {"own-a"}
        assert "g1" in {p.id for p in _writable_products_query(s, root).all()}


# --- R5: Jurisdiktion normalisiert, ungueltig = 422, geleerte Liste warnt ---
def _universe_product(session_factory, pid="g5"):
    now = h._now()
    with session_factory() as s:
        s.add(Product(id=pid, product_name="Fonds 5", asset_class="Aktien", product_type="ETF",
                      currency="CHF", is_active=1, created_at=now, updated_at=now))
        s.commit()


def test_r5_universe_jurisdiction_is_normalized(session_factory, client):
    _universe_product(session_factory)
    _as("admin-m", "admin", "main")
    r = client.post("/product-universe", json={"jurisdiction": " ch ", "product_id": "g5"})
    assert r.status_code == 201, r.text
    assert r.json()["jurisdiction"] == "CH"
    listed = client.get("/product-universe?jurisdiction=ch").json()
    assert [e["product_id"] for e in listed] == ["g5"]


@pytest.mark.parametrize("bad", ["XX", "Schweiz", "", "C H", "CHE"])
def test_r5_invalid_universe_jurisdiction_rejected(session_factory, client, bad):
    _universe_product(session_factory)
    _as("admin-m", "admin", "main")
    r = client.post("/product-universe", json={"jurisdiction": bad, "product_id": "g5"})
    assert r.status_code == 422, r.text
    with session_factory() as s:
        assert s.query(ProductUniverseEntry).count() == 0


def test_r5_iso_code_list_is_complete():
    """N-855-1: genau die 249 offiziellen Codes, keine verketteten Kunstcodes."""
    from schemas.review import ISO_3166_ALPHA2_CODES
    assert len(ISO_3166_ALPHA2_CODES) == 249
    assert all(len(code) == 2 and code.isascii() and code.isupper() for code in ISO_3166_ALPHA2_CODES)
    assert {"BE", "HU", "ID", "SI", "ME", "VN", "CH", "DE", "AT", "LI"} <= ISO_3166_ALPHA2_CODES


@pytest.mark.parametrize("code", ["be", " HU", "id", "SI", "me ", "vn"])
def test_r5_previously_dropped_iso_codes_accepted(session_factory, client, code):
    _universe_product(session_factory)
    _as("admin-m", "admin", "main")
    r = client.post("/product-universe", json={"jurisdiction": code, "product_id": "g5"})
    assert r.status_code == 201, r.text
    assert r.json()["jurisdiction"] == code.strip().upper()


def test_r5_emptied_universe_is_visible_not_silent(session_factory, client):
    m = h._seed_mandate(session_factory, suffix="r5", tenant_id="tenant-r5")
    first = _gen(session_factory, m["mandate_id"], m["advisor_id"])
    assert not [w for w in first["warnings"] if UNIVERSE_WARNING_MARKER in str(w)], (
        "nie gepflegte Liste = voller Katalog ohne Warnung (Bestandsverhalten)"
    )
    pid = first["positions"][0]["product_id"]
    _as("admin-r5", "admin", "tenant-r5")
    created = client.post("/product-universe", json={"jurisdiction": "CH", "product_id": pid})
    assert created.status_code == 201, created.text
    deleted = client.delete(f"/product-universe/{created.json()['id']}")
    assert deleted.status_code == 204, deleted.text
    with session_factory() as s:
        audit = s.query(AuditLog).filter(
            AuditLog.table_name == "product_universe_entries", AuditLog.field_name == "universe_scope",
        ).all()
    assert audit and "vollen Katalog" in (audit[0].new_value or "")
    second = _gen(session_factory, m["mandate_id"], m["advisor_id"])
    hits = [w for w in second["warnings"] if UNIVERSE_WARNING_MARKER in str(w)]
    assert hits, f"geleerte Positivliste muss sichtbar warnen: {second['warnings']}"


# --- R6: nicht editierbare Felder -> 422 statt still verworfen -------------
def _p6(session_factory):
    now = h._now()
    with session_factory() as s:
        s.add(Product(id="p6", product_name="Fonds 6", asset_class="Aktien", product_type="Fonds",
                      currency="CHF", isin="CH0000000BAD", symbol="BAD", is_active=1,
                      tenant_id="main", created_at=now, updated_at=now))
        s.commit()


def test_r6_changing_immutable_fields_is_rejected(session_factory, client):
    _p6(session_factory)
    _as("admin-m", "admin", "main")
    r = client.put("/products/p6", json={"isin": "CH0000000GUT", "symbol": "GUT", "product_type": "ETF",
                                         "product_name": "Fonds 6 korrigiert"})
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "isin" in detail and "symbol" in detail and "product_type" in detail
    with session_factory() as s:
        p = s.get(Product, "p6")
        assert (p.isin, p.symbol, p.product_type, p.product_name) == ("CH0000000BAD", "BAD", "Fonds", "Fonds 6")


def test_r6_unchanged_immutable_fields_are_accepted(session_factory, client):
    """Das Bearbeiten-Formular sendet isin/symbol/product_type immer mit."""
    _p6(session_factory)
    _as("admin-m", "admin", "main")
    r = client.put("/products/p6", json={"isin": "CH0000000BAD", "symbol": " BAD ", "product_type": "Fonds",
                                         "product_name": "Fonds 6 korrigiert"})
    assert r.status_code == 200, r.text
    assert r.json()["product_name"] == "Fonds 6 korrigiert"
    assert r.json()["isin"] == "CH0000000BAD"


# --- R7: Re-Import ueberschreibt nichts mit leer und meldet Eignung ---------
_R7_ROW = {"product_name": "Hausfonds 7", "product_type": "Fonds", "asset_class": "Aktien",
           "isin": "CH0000000R07", "sub_asset_class": "Aktien Schweiz", "ter_bps": 40,
           "suitability_profile_from": 3, "suitability_profile_to": 10}


def _r7_rules(session_factory, pid):
    with session_factory() as s:
        rules = s.query(ProductEligibilityRule).filter(ProductEligibilityRule.product_id == pid).all()
        return sorted((r.profile_from, r.profile_to, r.status) for r in rules), {r.id: r.supersedes_id for r in rules}


def _r7_create_and_maintain(client):
    r1 = client.post("/products/import", json={"products": [_R7_ROW]}).json()
    pid = r1["items"][0]["product_id"]
    client.put(f"/products/{pid}", json={"country_exposure_json": '{"CH": 10000}', "liquidity_tier": "daily",
                                         "credit_rating": "AA"})
    return pid


def test_r7_reimport_keeps_maintained_fields_and_reports_new_eligibility(session_factory, client):
    _as("admin-m", "admin", "main")
    pid = _r7_create_and_maintain(client)
    row2 = dict(_R7_ROW, ter_bps=35, suitability_profile_from=7)
    r2 = client.post("/products/import", json={"products": [row2]}).json()
    with session_factory() as s:
        p = s.get(Product, pid)
        state = (p.ter_bps, p.country_exposure_json, p.liquidity_tier, p.credit_rating)
    assert state == (35, '{"CH": 10000}', "daily", "AA")
    item = r2["items"][0]
    assert item["status"] == "updated"
    assert item["eligibility_note"] and "Freigabe" in item["eligibility_note"]
    bands, _ = _r7_rules(session_factory, pid)
    # Der nie freigegebene Erst-Entwurf wird zurueckgezogen, die neue Eignung ist der offene Entwurf.
    assert bands == [(3, 10, "retired"), (7, 10, "draft")]


def test_r7_csv_reimport_with_empty_cells_keeps_fields(session_factory, client):
    _as("admin-m", "admin", "main")
    pid = _r7_create_and_maintain(client)
    header = "product_name,product_type,asset_class,isin,ter_bps,liquidity_tier,suitability_profile_from,suitability_profile_to"
    body = header + "\nHausfonds 7,Fonds,Aktien,CH0000000R07,,,3,10\n"
    r = client.post("/products/import/csv", files={"file": ("f.csv", body.encode("utf-8"), "text/csv")})
    assert r.status_code == 201, r.text
    assert r.json()["items"][0]["eligibility_note"] is None
    with session_factory() as s:
        p = s.get(Product, pid)
        assert (p.ter_bps, p.liquidity_tier, p.credit_rating, p.sub_asset_class) == (40, "daily", "AA", "Aktien Schweiz")
    bands, _ = _r7_rules(session_factory, pid)
    assert bands == [(3, 10, "draft")], "unveraenderte Eignung erzeugt keinen neuen Entwurf"


def test_r7_changed_eligibility_supersedes_approved_rule_only_after_four_eyes(session_factory, client):
    from services.product_eligibility_governance import approve_rule

    _as("admin-m", "admin", "main")
    pid = _r7_create_and_maintain(client)
    with session_factory() as s:
        (rule,) = s.query(ProductEligibilityRule).filter(ProductEligibilityRule.product_id == pid).all()
        approve_rule(s, rule_id=rule.id, approver_id="zweite-person", tenant_id="main")
        s.commit()
        first_rule_id = rule.id
    r2 = client.post("/products/import", json={"products": [dict(_R7_ROW, suitability_profile_from=7)]}).json()
    assert r2["items"][0]["eligibility_note"]
    bands, supersedes = _r7_rules(session_factory, pid)
    assert bands == [(3, 10, "approved"), (7, 10, "draft")], "alte Regel gilt bis zur Freigabe"
    new_id = next(rid for rid, sup in supersedes.items() if sup == first_rule_id)
    with session_factory() as s:
        approve_rule(s, rule_id=new_id, approver_id="zweite-person", tenant_id="main")
        s.commit()
    bands, _ = _r7_rules(session_factory, pid)
    assert bands == [(3, 10, "retired"), (7, 10, "approved")]
    with session_factory() as s:
        from services.product_eligibility import resolve_active_rules_for_product
        active = resolve_active_rules_for_product(s, s.get(Product, pid), jurisdiction="CH", tenant_id="main")
        assert [(r.profile_from, r.profile_to) for r in active] == [(7, 10)]
        assert json.loads(active[0].service_modes_json) == ["investment_advice", "portfolio_management"]


def test_r7_supersession_is_point_in_time_correct(session_factory, client):
    """N-855-2: alte Regel gilt bis zur Freigabe, neue ab der Freigabe (nicht
    ab dem Import); rule_hash der alten Regel bleibt unveraendert."""
    from services.product_eligibility import resolve_active_rules_for_product
    from services.product_eligibility_governance import approve_rule

    _as("admin-m", "admin", "main")
    pid = _r7_create_and_maintain(client)
    with session_factory() as s:
        (rule,) = s.query(ProductEligibilityRule).filter(ProductEligibilityRule.product_id == pid).all()
        approve_rule(s, rule_id=rule.id, approver_id="zweite-person", tenant_id="main")
        s.commit()
        old_id, old_hash = rule.id, rule.rule_hash
    client.post("/products/import", json={"products": [dict(_R7_ROW, suitability_profile_from=7)]})
    approved_at = "2099-01-01T00:00:00.000Z"
    with session_factory() as s:
        new = s.query(ProductEligibilityRule).filter(ProductEligibilityRule.supersedes_id == old_id).one()
        approve_rule(s, rule_id=new.id, approver_id="zweite-person", tenant_id="main", now=approved_at)
        s.commit()
        old = s.get(ProductEligibilityRule, old_id)
        new = s.get(ProductEligibilityRule, new.id)
        assert old.valid_to == approved_at
        assert new.valid_from == approved_at
        assert old.rule_hash == old_hash
        product = s.get(Product, pid)
        # Zeitpunkt zwischen Import und Freigabe: bisherige Regel gilt (Statusfilter
        # beiseite: dieselbe Geltung ergibt sich aus valid_from/valid_to).
        before = [r for r in (old, new) if r.valid_from <= "2098-06-01" and (r.valid_to is None or r.valid_to > "2098-06-01")]
        after = [r for r in (old, new) if r.valid_from <= "2099-06-01" and (r.valid_to is None or r.valid_to > "2099-06-01")]
        assert [(r.profile_from, r.profile_to) for r in before] == [(3, 10)]
        assert [(r.profile_from, r.profile_to) for r in after] == [(7, 10)]
        active = resolve_active_rules_for_product(s, product, jurisdiction="CH", tenant_id="main",
                                                  as_of="2099-06-01T00:00:00.000Z")
        assert [(r.profile_from, r.profile_to) for r in active] == [(7, 10)]


# --- N-855-3: Tenant-Admin-UI nur mit strikter Mandantentrennung ------------
def test_n855_3_tenant_admin_ui_without_strict_isolation_rejected():
    from config import Settings
    with pytest.raises(ValueError, match="tenant_admin_ui_enabled=true erfordert strikte Mandantentrennung"):
        Settings(app_env="development", deployment_tier="tier1", tenancy_mode="single",
                 tenant_admin_ui_enabled=True, strict_tenant_isolation=False)


@pytest.mark.parametrize("overrides", [
    {"strict_tenant_isolation": True},
    {"deployment_tier": "tier2"},
    {"tenancy_mode": "multi"},
])
def test_n855_3_tenant_admin_ui_with_effective_strict_isolation_allowed(overrides):
    from config import Settings
    base = {"app_env": "development", "deployment_tier": "tier1", "tenancy_mode": "single",
            "tenant_admin_ui_enabled": True, "strict_tenant_isolation": False}
    cfg = Settings(**{**base, **overrides})
    assert cfg.tenant_admin_ui_enabled is True


def test_n855_3_tier1_default_without_admin_ui_unchanged():
    from config import Settings
    cfg = Settings(app_env="development", deployment_tier="tier1", tenancy_mode="single",
                   tenant_admin_ui_enabled=False, strict_tenant_isolation=False)
    assert cfg.tenant_admin_ui_enabled is False
