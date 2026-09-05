"""REF-READ-001 + REF-BASIS-001 (Codex-Audit 2026-09-05): Regressionstests fuer
routers/allocation.py::

  GET /house-matrix/{score}
  GET /optimizer-policies/current
  GET /building-blocks/current
  GET /capital-market-assumptions/current

Vorher haengten alle vier Endpoints an plain get_current_user OHNE
Rollen-Check -- ein role='client'-Login konnte interne Berater-/IC-Notizen,
den vollen Produktkatalog und die konfidenzielle Protokollformulierung lesen.
Der GET-Endpoint fuer Kapitalmarktannahmen nahm zusaetzlich einen frei
waehlbaren tenant_id-Query-Parameter OHNE Ownership-Check entgegen -- jeder
authentifizierte User konnte per tenant_id=<fremde-firma> deren private
CMA-Tenant-Override-Zeile lesen.

Deckt ab:
1. Rot->Gruen: role='client' wird jetzt auf allen vier Endpoints mit 403
   abgewiesen (vorher 200).
2. Regression: der legitime Berater-/Admin-Lesepfad bleibt unveraendert (200).
3. get_current_cma: cross-tenant tenant_id-Lesezugriff ist in Tier-1 (kein
   strict_tenant_isolation) weiterhin erlaubt (Backwards-Compat, identisches
   Prinzip zu AUTH-TEN-04), wird aber unter strict_tenant_isolation auf
   Super-Admin/Portfolio Management beschraenkt.
4. get_current_building_blocks (REF-BASIS-001): jurisdiction-Query-Parameter
   filtert jetzt jurisdiktions-bewusst (mirror der echten Solver-Aufloesung
   in services/jurisdiction/resolve.py::resolve_building_blocks_for_jurisdiction)
   und exponiert das jurisdiction-Feld in der Response.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models.allocation import BuildingBlock, CapitalMarketAssumption, HouseMatrix, OptimizerPolicy
from models.tenant import Tenant
from models.users import User
from services.auth import get_current_user


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ref_read_001.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(session_factory):
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login_as(user_id: str, role: str, tenant_id: str | None = "main"):
    user = User(
        id=user_id, username=user_id, password_hash="h", full_name=user_id,
        role=role, is_active=1, tenant_id=tenant_id,
    )
    app.dependency_overrides[get_current_user] = lambda: user


def _logout():
    app.dependency_overrides.pop(get_current_user, None)


def _seed_reference_data(session_factory, *, cma_jurisdiction=None, cma_tenant_id=None,
                          extra_cma_rows=None, building_block_rows=None):
    now = _now()
    with session_factory() as s:
        s.add(Tenant(
            id="main", display_name="main", slug="main",
            hosting_tier="tier1", license_status="active",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Tenant(
            id="firm-b", display_name="firm-b", slug="firm-b",
            hosting_tier="tier2", license_status="active",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(User(
            id="seed-user", username="seed-user", password_hash="h", full_name="Seed",
            role="admin", is_active=1, tenant_id="main", created_at=now, updated_at=now,
        ))
        s.commit()
        policy = OptimizerPolicy(
            id="policy-1", policy_name="Standard", version=1, is_current=1,
            valid_from="2026-01-01", optimizer_engine="goal_based_v1",
            max_real_estate_bps=2000, max_alternatives_bps=1000, min_liquidity_bps=0,
            created_by="seed-user", created_at=now, updated_at=now,
        )
        s.add(policy)
        s.add(HouseMatrix(
            id="hm-1", policy_id="policy-1", score_from=1, score_to=10,
            profile_name="Balanced",
            liq_min_bps=0, liq_target_bps=500, liq_max_bps=1000,
            bonds_min_bps=1000, bonds_target_bps=3000, bonds_max_bps=5000,
            equity_min_bps=1000, equity_target_bps=3000, equity_max_bps=5000,
            real_estate_min_bps=0, real_estate_target_bps=1000, real_estate_max_bps=2000,
            alt_min_bps=0, alt_target_bps=500, alt_max_bps=1000,
            equity_minimum_bps=0, max_risky_fraction_bps=8000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(CapitalMarketAssumption(
            id="cma-ch-1", assumption_set_name="Standard", version=1,
            valid_from="2026-01-01", is_current=1, jurisdiction=cma_jurisdiction,
            tenant_id=cma_tenant_id, status="committee_approved",
            equity_ch_return_bps=650,
            created_by="seed-user", created_at=now, updated_at=now,
        ))
        for row in (extra_cma_rows or []):
            s.add(row)
        s.add(BuildingBlock(
            id="bb-ch-1", policy_id="policy-1", asset_class="Aktien",
            sub_asset_class="Aktien Schweiz", universe="Standard",
            advisory=1, risky_fraction_bps=10000, is_active=1,
            created_at=now, updated_at=now,
        ))
        for row in (building_block_rows or []):
            s.add(row)
        s.commit()


REFERENCE_ENDPOINTS = [
    ("/house-matrix/5", {}),
    ("/optimizer-policies/current", {}),
    ("/building-blocks/current", {}),
    ("/capital-market-assumptions/current", {}),
]


@pytest.mark.parametrize("path,params", REFERENCE_ENDPOINTS)
def test_role_client_forbidden_on_reference_endpoints(client, session_factory, path, params):
    """Rot->Gruen: role='client' durfte diese vier Endpoints vorher lesen
    (plain get_current_user, kein Rollen-Check) -- jetzt 403."""
    _seed_reference_data(session_factory)
    _login_as("client-1", "client")
    try:
        resp = client.get(path, params=params)
        assert resp.status_code == 403
    finally:
        _logout()


@pytest.mark.parametrize("role", ["admin", "advisor", "super_admin", "portfolio_management"])
@pytest.mark.parametrize("path,params", REFERENCE_ENDPOINTS)
def test_internal_roles_still_allowed_regression(client, session_factory, path, params, role):
    """Regression: der legitime interne Lesepfad (Berater/Admin/Platform-
    Rollen) bleibt unveraendert erlaubt."""
    _seed_reference_data(session_factory)
    _login_as("staff-1", role)
    try:
        resp = client.get(path, params=params)
        assert resp.status_code == 200, resp.text
    finally:
        _logout()


def test_cma_cross_tenant_tenant_id_allowed_in_tier1_default(client, session_factory):
    """Tier-1 (kein strict_tenant_isolation): ein admin darf weiterhin per
    tenant_id-Query-Parameter eine andere Tenant-CMA-Zeile lesen -- exakt das
    heutige, dokumentierte Bestandsverhalten (siehe
    test_cma_jurisdiction_query_param.py::
    test_get_current_cma_de_tenant_override_takes_precedence), NICHT von
    dieser Haertung betroffen."""
    de_tenant_row = CapitalMarketAssumption(
        id="cma-de-tenant", assumption_set_name="DE-Tenant", version=1,
        valid_from="2026-01-01", is_current=1, jurisdiction="DE", tenant_id="firm-b",
        status="committee_approved", created_by="seed-user", created_at=_now(), updated_at=_now(),
    )
    _seed_reference_data(session_factory, extra_cma_rows=[de_tenant_row])
    _login_as("admin-a", "admin", tenant_id="main")
    try:
        resp = client.get(
            "/capital-market-assumptions/current",
            params={"jurisdiction": "DE", "tenant_id": "firm-b"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == "cma-de-tenant"
    finally:
        _logout()


def test_cma_cross_tenant_tenant_id_blocked_under_strict_isolation(client, session_factory, monkeypatch):
    """Echte Multi-Tenant-Installation (strict_tenant_isolation=True): ein
    firmengebundener admin/advisor darf NICHT mehr per tenant_id-Parameter
    die private CMA-Zeile einer anderen Firma lesen -- braucht Super-Admin
    oder Portfolio Management (identisches Prinzip zu AUTH-TEN-04/06)."""
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    de_tenant_row = CapitalMarketAssumption(
        id="cma-de-tenant", assumption_set_name="DE-Tenant", version=1,
        valid_from="2026-01-01", is_current=1, jurisdiction="DE", tenant_id="firm-b",
        status="committee_approved", created_by="seed-user", created_at=_now(), updated_at=_now(),
    )
    _seed_reference_data(session_factory, extra_cma_rows=[de_tenant_row])

    _login_as("admin-a", "admin", tenant_id="main")
    try:
        forbidden = client.get(
            "/capital-market-assumptions/current",
            params={"jurisdiction": "DE", "tenant_id": "firm-b"},
        )
        assert forbidden.status_code == 403
    finally:
        _logout()

    _login_as("super-a", "super_admin", tenant_id=None)
    try:
        allowed = client.get(
            "/capital-market-assumptions/current",
            params={"jurisdiction": "DE", "tenant_id": "firm-b"},
        )
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["id"] == "cma-de-tenant"
    finally:
        _logout()

    # Der eigene Tenant bleibt auch unter strict_tenant_isolation erlaubt --
    # kein Cross-Tenant-Zugriff, wenn tenant_id == eigener Tenant.
    _login_as("admin-main", "admin", tenant_id="main")
    try:
        own_tenant = client.get(
            "/capital-market-assumptions/current",
            params={"jurisdiction": "CH", "tenant_id": "main"},
        )
        assert own_tenant.status_code == 200, own_tenant.text
    finally:
        _logout()


def test_building_blocks_jurisdiction_filter_and_dedup(client, session_factory):
    """REF-BASIS-001: der Endpoint filtert jetzt jurisdiktions-bewusst (mirror
    services/jurisdiction/resolve.py::resolve_building_blocks_for_jurisdiction,
    genutzt vom echten Solver-Pfad ueber
    services/portfolio_engine_house_matrix.py::_building_block_rows_for_policy)
    statt vorher ALLE aktiven Zeilen der Policy ungefiltert ueber jede
    Jurisdiktion hinweg zurueckzugeben. Deckt ab:
      - eine FR-exklusive Zeile taucht WEDER im CH-Default NOCH im DE-Filter
        auf (echte Jurisdiktions-Scoping, nicht nur "irgendein Filter"),
      - eine geteilte (jurisdiction=None) Zeile ist im CH-Default sichtbar,
        wird aber fuer DE durch eine exakte DE-Zeile mit identischer
        asset/sub-asset/universe-Kombination ersetzt (Override-Dedup,
        keine doppelte Cash-Zeile),
      - eine DE-exklusive Zeile taucht nur im DE-Filter auf,
      - die Response exponiert das jurisdiction-Feld.
    """
    shared_cash = BuildingBlock(
        id="bb-shared-cash", policy_id="policy-1", asset_class="Liquiditaet",
        sub_asset_class="Cash", universe="Standard", advisory=1,
        risky_fraction_bps=0, is_active=1, jurisdiction=None,
        created_at=_now(), updated_at=_now(),
    )
    de_override_cash = BuildingBlock(
        id="bb-de-cash-override", policy_id="policy-1", asset_class="Liquiditaet",
        sub_asset_class="Cash", universe="Standard", advisory=1,
        risky_fraction_bps=500, is_active=1, jurisdiction="DE",
        created_at=_now(), updated_at=_now(),
    )
    de_specific_aktien = BuildingBlock(
        id="bb-de-aktien", policy_id="policy-1", asset_class="Aktien",
        sub_asset_class="Aktien Deutschland", universe="Standard", advisory=1,
        risky_fraction_bps=10000, is_active=1, jurisdiction="DE",
        created_at=_now(), updated_at=_now(),
    )
    fr_specific_aktien = BuildingBlock(
        id="bb-fr-aktien", policy_id="policy-1", asset_class="Aktien",
        sub_asset_class="Aktien Frankreich", universe="Standard", advisory=1,
        risky_fraction_bps=10000, is_active=1, jurisdiction="FR",
        created_at=_now(), updated_at=_now(),
    )
    _seed_reference_data(session_factory, building_block_rows=[
        shared_cash, de_override_cash, de_specific_aktien, fr_specific_aktien,
    ])
    _login_as("admin-a", "admin")
    try:
        default_resp = client.get("/building-blocks/current")
        assert default_resp.status_code == 200
        default_ids = {row["id"] for row in default_resp.json()}
        # CH-Default (kein jurisdiction-Query-Param): CH-eigene + geteilte
        # Zeilen sichtbar, DE- und FR-exklusive Zeilen NICHT. Vor dem Fix
        # war der Endpoint ungefiltert -- alle vier DE/FR-Zeilen waeren auch
        # hier aufgetaucht.
        assert "bb-ch-1" in default_ids
        assert "bb-shared-cash" in default_ids
        assert "bb-de-cash-override" not in default_ids
        assert "bb-de-aktien" not in default_ids
        assert "bb-fr-aktien" not in default_ids

        de_resp = client.get("/building-blocks/current", params={"jurisdiction": "DE"})
        assert de_resp.status_code == 200, de_resp.text
        de_rows = {row["id"]: row for row in de_resp.json()}
        # DE-exklusive Zeile sichtbar, FR-exklusive Zeile NICHT (echtes
        # Jurisdiktions-Scoping).
        assert "bb-de-aktien" in de_rows
        assert "bb-fr-aktien" not in de_rows
        # Override-Dedup: die DE-spezifische Cash-Zeile ersetzt die geteilte
        # Cash-Zeile fuer denselben asset/sub-asset/universe-Schluessel --
        # keine doppelte Cash-Zeile in der Antwort.
        assert "bb-de-cash-override" in de_rows
        assert "bb-shared-cash" not in de_rows
        assert de_rows["bb-de-aktien"]["jurisdiction"] == "DE"
        assert de_rows["bb-de-cash-override"]["jurisdiction"] == "DE"
    finally:
        _logout()


def test_building_blocks_unsupported_jurisdiction_404(client, session_factory):
    _seed_reference_data(session_factory)
    _login_as("admin-a", "admin")
    try:
        resp = client.get("/building-blocks/current", params={"jurisdiction": "FR"})
        assert resp.status_code == 404
    finally:
        _logout()
