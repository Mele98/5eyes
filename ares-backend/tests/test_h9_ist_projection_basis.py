"""H9 Nachtrag 2 -- eine CMA-Quelle fuer die IST-Vermoegensprojektion.

Entscheid (Owner-Vertretung 2026-11-12): Die IST-Projektion nutzt immer dieselbe
serverseitige, wirksame CMA-Version wie der Allokationspfad -- unabhaengig vom
Strategie-Zustand. Fehlt eine wirksame CMA: keine Projektion (fail-closed,
Reason-Code), kein Fallback auf Client-Konstanten.

Backend: ``GET /mandates/{id}/ist-projection-basis`` (Tenant-/Besitz-Pruefung,
Reason-Code, Validierung). Frontend: ``wealthProjectionInputs`` liest nur noch
diese Basis; IST-Kachel und IST-Punkte sind mit und ohne Strategie identisch.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401  (Mapper registrieren)
from core.reason_codes import ReasonCode
from database import Base
from models.clients import Client
from models.mandates import Mandate
from models.users import User
from models.wealth import Cashflow, WealthPosition
from tests.livetest_monolith_js import extract_function, html, run_js
from tests.monolith_source import FRONTEND_DIR

NOW = datetime.now(timezone.utc).isoformat()
CHF = 100


@pytest.fixture()
def session_factory(tmp_path):
    import main  # noqa: F401  (alle Mapper inkl. Querverweise registrieren)

    engine = create_engine(f"sqlite:///{tmp_path / 'ist_basis.db'}", connect_args={"check_same_thread": False})
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _user(uid, role="advisor", tenant_id=None):
    return User(id=uid, username=uid, password_hash="hash", full_name=uid, role=role, is_active=1,
                tenant_id=tenant_id, created_at=NOW, updated_at=NOW)


def _seed(session):
    owner = _user("adv-owner")
    session.add_all([owner, _user("adv-other")])
    session.add(Client(
        id="cl-ist", client_number="C-IST", first_name="Max", last_name="Muster",
        country_of_residence="CH", language="DE", household_type="Einzelperson",
        client_classification="Privatkunde", is_professional_opt_out=0,
        is_qualified_investor=0, advisor_id=owner.id, created_at=NOW, updated_at=NOW,
    ))
    session.add(Mandate(
        id="m-ist", client_id="cl-ist", mandate_number="M-IST", mandate_type="Anlageberatung",
        status="Aktiv", base_currency="CHF", advisory_language="DE", opened_at="2026-01-01",
        created_at=NOW, updated_at=NOW,
    ))
    session.add(WealthPosition(
        id="wp-depot", client_id="cl-ist", label="Depot", position_type="Depot",
        assignment="Beratungsvermögen", current_value_rappen=500_000 * CHF, currency="CHF",
        alloc_equities_bps=5000, alloc_bonds_bps=3000, alloc_liquidity_bps=2000,
        created_at=NOW, updated_at=NOW,
    ))
    session.add(Cashflow(
        id="cf-lohn", client_id="cl-ist", cashflow_type="Income", label="Lohn",
        amount_rappen=30_000 * CHF, currency="CHF", frequency="jährlich", nature="wiederkehrend",
        created_at=NOW, updated_at=NOW,
    ))
    session.commit()
    return owner


def _get(session, user, **kw):
    from routers.allocation import get_ist_projection_basis

    return get_ist_projection_basis("m-ist", db=session, current_user=user, **kw)


def test_basis_uses_effective_cma_of_the_allocation_path(session_factory):
    from jurisdictions.resolve import resolve_pack
    from services.portfolio_engine import ensure_runtime_reference_data
    from services.portfolio_engine_cma import _asset_class_expected_metrics

    with session_factory() as session:
        owner = _seed(session)
        out = _get(session, owner)
        mandate = session.get(Mandate, "m-ist")
        _policy, cma = ensure_runtime_reference_data(session, owner.id, jurisdiction=resolve_pack(mandate).code)
        returns, _ = _asset_class_expected_metrics(cma)
    assert out["cma"]["id"] == cma.id and out["cma"]["version"] == int(cma.version or 1)
    assert out["expected_return_bps"] == {k: int(returns.get(k, 0)) for k in
                                          ("equities", "bonds", "real_estate", "alternatives", "liquidity")}
    assert out["total_base_rappen"] == 500_000 * CHF
    assert out["projection_basis"]["start_rappen"] == 500_000 * CHF
    assert out["projection_basis"]["schema"] == "total-wealth-projection-basis/v1"


def test_basis_is_independent_of_the_strategy_state():
    """Der Lesepfad beruehrt keine Soll-Allokation, kein Risikoprofil und keine
    Sub-Allokation (sonst waere die Basis wieder strategieabhaengig)."""
    import inspect

    from routers import allocation

    src = inspect.getsource(allocation.get_ist_projection_basis)
    for needle in ("TargetAllocation", "target_allocation", "_weighted_bucket_metrics",
                   "sub_allocations", "require_strategy_ready_assessment", "risk_assessment"):
        assert needle not in src, needle
    assert "_asset_class_expected_metrics(cma)" in src
    assert "ensure_runtime_reference_data(" in src


def test_other_advisor_cannot_read_foreign_mandate_basis(session_factory):
    with session_factory() as session:
        _seed(session)
        other = session.get(User, "adv-other")
        with pytest.raises(HTTPException) as exc:
            _get(session, other)
    assert exc.value.status_code == 404


def test_user_of_other_tenant_cannot_read_basis(session_factory):
    with session_factory() as session:
        _seed(session)
        session.get(Mandate, "m-ist").tenant_id = "tenant-a"
        foreign_admin = _user("adm-foreign", role="admin", tenant_id="tenant-foreign")
        own_admin = _user("adm-own", role="admin", tenant_id="tenant-a")
        session.add_all([foreign_admin, own_admin])
        session.commit()
        with pytest.raises(HTTPException) as exc:
            _get(session, foreign_admin)
        assert _get(session, own_admin)["mandate_id"] == "m-ist"  # Positivkontrolle
    assert exc.value.status_code == 404


def test_missing_effective_cma_is_fail_closed_with_reason_code(session_factory, monkeypatch):
    import routers.allocation as allocation_router

    def _missing(*_a, **_k):
        raise ValueError("keine CMA")

    monkeypatch.setattr(allocation_router, "ensure_runtime_reference_data", _missing)
    with session_factory() as session:
        owner = _seed(session)
        with pytest.raises(HTTPException) as exc:
            _get(session, owner)
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == ReasonCode.IST_PROJECTION_BASIS_UNAVAILABLE.value


def test_horizon_is_validated(session_factory):
    with session_factory() as session:
        owner = _seed(session)
        with pytest.raises(HTTPException) as exc:
            _get(session, owner, horizon_years=0)
        assert exc.value.status_code == 422
        out = _get(session, owner, horizon_years=12)
    assert len(out["projection_basis"]["liability_series_rappen"]) in (0, 13)


def test_route_is_published_with_response_model():
    from main import app

    routes = {getattr(r, "path", ""): r for r in app.routes}
    route = routes["/mandates/{mandate_id}/ist-projection-basis"]
    assert "GET" in route.methods
    assert route.response_model.__name__ == "IstProjectionBasisResponse"


# ---------------------------------------------------------------------------
# Frontend: keine Client-Konstanten, eine Quelle, identisch mit/ohne Strategie
# ---------------------------------------------------------------------------

def test_wealth_projection_inputs_have_no_client_cma_constants_and_no_strategy_source():
    body = extract_function(html(), "wealthProjectionInputs")
    assert "ADMIN_CMA_DEFAULTS" not in body
    assert "asset_class_assumptions" not in body
    assert "strategyState" not in body
    assert "istProjectionServerBasisFor()" in body


PRELUDE = r"""
var MID='m-A', BASIS=null;
function getActiveMandateId(){return MID;}
function istProjectionServerBasisFor(){return BASIS;}
var currentClientId='c-A';
var POS=[{id:'d',position_type:'Depot',assignment:'Beratungsvermögen',current_value_rappen:50000000,currency:'CHF'}];
function wealthScopePositions(){return POS;}
function activeClientWealthPositions(){return POS;}
function activeClientCashflowSummary(){return {};}
function summaryRecurringNetCashflowRappen(){return 0;}
function summaryCapitalNetCashflowRappen(){return 0;}
function summaryTotalNetCashflowRappen(){return 0;}
function isExternalPensionPosition(){return false;}
function pensionProjectionRateBps(){return null;}
function inferPositionBucketMixBps(){return {equities:6000,bonds:4000,realEstate:0,liquidity:0,alternatives:0};}
function loadIstHorizonOverride(){return null;}
function activeClientCashflowProjection(){return {years:[1,2,3,4,5]};}
function currentMandateHorizonRange(){return null;}
function simulationPayload(r){return r&&r.simulation||null;}
function currentCashflowProjectionComponentSeries(years){var a=[];for(var i=0;i<years;i++)a.push({recurringNetRappen:0,capitalNetRappen:0,netCashflowRappen:0});return a;}
function projectionSeriesCagrBps(){return 0;}
var strategyState=null;
var SRV={mandate_id:'m-A',cma:{id:'cma-1',version:3},expected_return_bps:{equities:600,bonds:200,real_estate:400,alternatives:300,liquidity:50},
  total_base_rappen:50000000,foundation_in_net_wealth_rappen:0,projection_basis:{}};
"""

NEEDED = ("wealthProjectionInputs", "mortgageLiabilityAndPledgedSeriesRappen", "buildCurrentWealthProjection",
          "projectionHorizonYears", "projectionYearLabels", "buildBaselineProjectionFromComponentSeries")


def _js(scenario: str):
    return run_js(NEEDED, scenario, prelude=PRELUDE, optional=("buildBaselineProjectionFromInputs",))


def test_same_client_identical_ist_points_and_tile_with_and_without_strategy():
    out = _js(
        "BASIS=SRV;strategyState={allocation:null};var a=buildCurrentWealthProjection('total',null,null);"
        "strategyState={allocation:{asset_class_assumptions:[{asset_class:'Aktien',expected_return_bps:900}],"
        "total_allocation:{total_base_rappen:1,foundation_in_net_wealth_rappen:0},simulation:{year_labels:[2026,2027]}}};"
        "var b=buildCurrentWealthProjection('total',null,null);"
        "return {a:a.seriesK,b:b.seriesK,ta:a.projectedRappen,tb:b.projectedRappen,ret:a.expectedReturnBps,cma:a.cmaReference};"
    )
    assert out["a"] == out["b"] and len(out["a"]) == 6
    assert out["ta"] == out["tb"]
    assert out["ret"] == 440  # 60 % x 600 + 40 % x 200, Liquiditaet bleibt 0 (Fachentscheid)
    assert out["cma"] == {"id": "cma-1", "version": 3}


def test_without_server_basis_no_projection_is_invented():
    out = _js(
        "BASIS=null;var p=buildCurrentWealthProjection('total',null,null);"
        "return {u:!!p.unavailable,s:p.seriesK,t:p.projectedRappen};"
    )
    assert out == {"u": True, "s": [], "t": 0}


def test_basis_module_is_mandate_scoped_and_fail_closed():
    module = (FRONTEND_DIR / "ist-projection-basis.js").read_text(encoding="utf-8")
    assert "'/mandates/'+mid+'/ist-projection-basis'" in module
    assert "if(st.mid!==mid)st.data=null;" in module
    assert "IST_PROJECTION_BASIS_UNAVAILABLE" in module
    out = run_js((), (
        "var r1=istProjectionServerBasisFor();"
        "istProjectionBasisState={mid:'m-A',key:'k',data:{x:1},status:'ok',reason:'',seq:1};var r2=istProjectionServerBasisFor();"
        "MID='m-B';var r3=istProjectionServerBasisFor();"
        "return {r1:r1,r2:r2,r3:r3};"
    ), prelude="var MID='m-A';function getActiveMandateId(){return MID;}\n" + module)
    assert out == {"r1": None, "r2": {"x": 1}, "r3": None}


# ---------------------------------------------------------------------------
# Entscheid 2: eine Horizont-Beschriftung ("Ende JJJJ") fuer AA-Seite und
# Vermoegensentwicklung, gleiche Hilfsfunktion
# ---------------------------------------------------------------------------

def test_one_end_of_year_helper_for_aa_page_and_wealth_projection():
    src = html()
    assert src.count("function projectionEndOfYearText(") == 1
    users = {
        "projectionHorizonYearLabel": "projectionEndOfYearText(last)",
        "renderAaProjectionEndValues": "projectionEndOfYearText(year)",
        "projectionRunwayLabel": "projectionEndOfYearText(labels[labels.length-1])",
        "renderCurrentWealthOnlyProjectionSummary": "projectionEndOfYearText(",
        "renderIstStrategyOverview": "projectionEndOfYearText(",
    }
    for name, needle in users.items():
        if "function " + name + "(" in src:
            assert needle in extract_function(src, name), name
    # keine zweite, abweichende Jahresbeschriftung mehr im IST-Teil
    assert "istProjectionEndYearLabel" not in src


def test_end_of_year_text_matches_horizon_display_semantics():
    out = run_js(("projectionEndOfYearText", "simulationPayload", "projectionHorizonYearLabel"),
                 "return [projectionEndOfYearText('2061'),projectionEndOfYearText(''),"
                 "projectionHorizonYearLabel({simulation:{target_mix_series_rappen:[1],year_labels:[2026,2036]}})];")
    # Override 10 Jahre ("= bis 2035 (10 J.)"): letzter Punkt 2036 = Ende 2035.
    assert out == ["Ende 2060", "", "Ende 2035"]
