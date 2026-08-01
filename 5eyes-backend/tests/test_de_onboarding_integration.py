"""WP6 (2026-07-31): End-to-End-Integrationstests fuer die komplette
Deutschland-Anbindung.

Verifiziert die volle Kette (Resolver -> Engine-Wiring -> Router ->
Governance) in EINEM Testlauf, nicht nur die einzelnen Bausteine isoliert
(die bereits in tests/test_jurisdiction_resolvers.py,
tests/test_engine_de_jurisdiction_wiring.py, tests/test_jurisdiction_router.py,
tests/test_cma_approval_endpoint.py, tests/test_cma_jurisdiction_query_param.py
und tests/test_provisional_pdf_gate.py abgedeckt sind):

1. Kompletter DE-Mandats-Flow: Client+Mandat mit jurisdiction="DE",
   ProductUniverseEntry-Positivliste fuer DE, DE-CapitalMarketAssumption
   (erst status="data_derived", dann per Router-Approval-Endpoint auf
   "committee_approved" gehoben) + DE-BuildingBlock-Zeilen,
   generate_target_allocation + generate_recommendation_run End-to-End.
   Prueft: DE-Labels erscheinen, provisional_data_warning wird fuer
   "data_derived" gesetzt und NACH der Freigabe (gleiche CMA-Zeile) nicht
   mehr, und die ProductUniverseEntry-Positivliste wirkt tatsaechlich
   (ein guenstigerer, nicht gelisteter Fonds wird NICHT gewaehlt).
2. Router-Integrationstest: POST /jurisdictions/DE/cma/compute-candidate
   (gemockte Marktdaten-Pipeline) -> POST
   /capital-market-assumptions/{id}/approve -> GET
   /capital-market-assumptions/current?jurisdiction=DE liefert
   status="committee_approved".
3. Rollen-Test End-to-End: role="portfolio_management" darf den
   Approval-Endpoint aufrufen, role="advisor" bekommt 403 -- gegen eine im
   selben Testlauf per compute-candidate erzeugte echte Kandidaten-Zeile
   (nicht nur eine synthetisch eingefuegte Fixture-Zeile).
4. CH-Isolation: ein CH-Mandat (jurisdiction=NULL), das in DERSELBEN
   Test-Datenbank parallel zu allen DE-Fixtures existiert, bleibt in jeder
   Hinsicht unbeeinflusst (Labels, CMA-Zeile, Recommendation-Run) -- kein
   Cross-Talk zwischen den Jurisdiktionen.

Der Beweis, dass der CH-Pfad global (nicht nur in dieser Datei) unveraendert
bleibt, ist tests/test_golden_snapshot_ch_regression.py -- wird gemaess
Arbeitsauftrag separat, explizit ausgefuehrt und im Task-Report bestaetigt.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from sqlalchemy.orm import configure_mappers

from database import Base, get_db
from main import app
from models import (  # noqa: F401
    allocation, clients, jurisdiction, mandates, profiling, review, snapshots, tenant, users, wealth,
)
configure_mappers()
import routers.jurisdiction as jurisdiction_router_module
from models.allocation import BuildingBlock, CapitalMarketAssumption
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment, RiskAssessmentAnswer
from models.review import Product, ProductUniverseEntry
from models.tenant import Tenant
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.auth import get_current_user
from services.jurisdiction.de_seed import DE_CODE, ensure_de_jurisdiction_seed
from services.portfolio_engine import (
    ensure_runtime_reference_data,
    generate_recommendation_run,
    generate_target_allocation,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'de_onboarding_integration.db'}",
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


def _login_as(user_id: str, role: str, tenant_id: str = "main"):
    user = User(id=user_id, username=user_id, password_hash="h", full_name=user_id,
                role=role, is_active=1, tenant_id=tenant_id)
    app.dependency_overrides[get_current_user] = lambda: user


def _logout():
    app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# DE-Produktkatalog + Positivliste (ProductUniverseEntry) -- ein "verbotener",
# guenstigerer Duplikat-Fonds fuer "Aktien Deutschland" beweist, dass die
# Positivliste die Auswahl tatsaechlich veraendert (nicht nur passiv da ist):
# _product_score() zieht ter_bps direkt vom Score ab -- ohne Filter wuerde
# der guenstigere (nicht gelistete) Fonds gewinnen.
# ---------------------------------------------------------------------------
_DE_ALLOWED_PRODUCT_DEFAULTS = [
    # (id, product_name, provider, product_type, asset_class, sub_asset_class, currency, ter_bps)
    ("de-int-aktien-de", "DE-Aktien-ETF", "Test-Provider", "ETF", "Aktien", "Aktien Deutschland", "EUR", 15),
    ("de-int-aktien-global", "Global-Aktien-ETF", "Test-Provider", "ETF", "Aktien", "Aktien Global", "USD", 20),
    ("de-int-aktien-europa", "Europa-Aktien-ETF", "Test-Provider", "ETF", "Aktien", "Aktien Europa", "EUR", 12),
    ("de-int-aktien-em", "EM-Aktien-ETF", "Test-Provider", "ETF", "Aktien", "Aktien Schwellenlaender", "USD", 18),
    ("de-int-bond-eur-ig", "EUR-IG-Bond-Fonds", "Test-Provider", "Fonds", "Obligationen", "Obligationen EUR IG", "EUR", 30),
    ("de-int-bond-global-hedged", "Global-Hedged-Bond-ETF", "Test-Provider", "ETF", "Obligationen", "Obligationen Global EUR-Hedged", "EUR", 15),
    ("de-int-bond-hy", "HY-Bond-Fonds", "Test-Provider", "Fonds", "Obligationen", "Obligationen High Yield", "EUR", 55),
    ("de-int-bond-em", "EM-Bond-Fonds", "Test-Provider", "Fonds", "Obligationen", "Obligationen Emerging", "USD", 60),
    ("de-int-immo-de", "DE-Immobilienfonds", "Test-Provider", "Immobilienfonds", "Immobilien", "Immobilien Deutschland", "EUR", 50),
    ("de-int-immo-global", "Global-Immobilien-ETF", "Test-Provider", "ETF", "Immobilien", "Immobilien Global", "USD", 38),
    ("de-int-gold", "Gold-ETF", "Test-Provider", "ETF", "Alternative", "Gold / Rohstoffe", "EUR", 40),
    ("de-int-geldmarkt", "EUR-Geldmarktfonds", "Test-Provider", "Fonds", "Liquiditaet", "Geldmarktfonds", "EUR", 8),
]
# NICHT in der Positivliste enthalten -- guenstiger als "de-int-aktien-de"
# (ter_bps=15), muesste ohne den Universe-Filter wegen des hoeheren
# _product_score() gewinnen.
_DE_FORBIDDEN_CHEAP_PRODUCT_ID = "de-int-aktien-de-forbidden-cheap"


def _seed_de_products_and_universe(s, *, tenant_id: str) -> None:
    now = _now()
    for pid, name, provider, product_type, asset_class, sub_asset_class, currency, ter_bps in _DE_ALLOWED_PRODUCT_DEFAULTS:
        s.add(Product(
            id=pid, product_name=name, provider=provider,
            product_type=product_type, asset_class=asset_class, sub_asset_class=sub_asset_class,
            currency=currency, ter_bps=ter_bps, is_active=1, jurisdiction=DE_CODE,
            created_at=now, updated_at=now,
        ))
    # Verbotener, guenstigerer Duplikat-Fonds fuer denselben Sub-Asset-Class-Slot.
    s.add(Product(
        id=_DE_FORBIDDEN_CHEAP_PRODUCT_ID, product_name="DE-Aktien-ETF-Verboten-Guenstig",
        provider="Nicht-Gelistet", product_type="ETF", asset_class="Aktien",
        sub_asset_class="Aktien Deutschland", currency="EUR", ter_bps=1,
        is_active=1, jurisdiction=DE_CODE, created_at=now, updated_at=now,
    ))
    # Positivliste: NUR die _DE_ALLOWED_PRODUCT_DEFAULTS-IDs, NICHT der
    # verbotene guenstige Duplikat-Fonds.
    for pid, *_rest in _DE_ALLOWED_PRODUCT_DEFAULTS:
        s.add(ProductUniverseEntry(
            id=f"pue-{tenant_id}-{pid}", tenant_id=tenant_id, jurisdiction=DE_CODE,
            product_id=pid, created_by="system:test", created_at=now, updated_at=now,
        ))


def _seed_de_building_blocks(s, policy_id: str) -> None:
    now = _now()
    de_specific = [
        ("Aktien", "Aktien Deutschland", 7000),
        ("Obligationen", "Obligationen EUR IG", 2000),
        ("Obligationen", "Obligationen Global EUR-Hedged", 2500),
        ("Immobilien", "Immobilien Deutschland", 5000),
    ]
    for asset_class, sub_asset_class, risky_fraction in de_specific:
        s.add(BuildingBlock(
            id=f"de-bb-{sub_asset_class}", policy_id=policy_id, asset_class=asset_class,
            sub_asset_class=sub_asset_class, universe="Standard", advisory=1,
            risky_fraction_bps=risky_fraction, is_active=1, jurisdiction=DE_CODE,
            is_provisional=1, created_at=now, updated_at=now,
        ))


def _seed_de_mandate(session_factory, *, suffix: str, cma_status: str) -> dict:
    """Seedet ein vollstaendiges DE-Mandat inkl. Tenant/Users/Client/Goals/
    Risikoprofil + DE-CMA (firmenweit, tenant_id=NULL) + DE-BuildingBlocks +
    DE-Produktkatalog/Positivliste. Gibt alle fuer die weiteren Testschritte
    benoetigten IDs zurueck."""
    advisor_id = f"de-adv-{suffix}"
    tenant_id = f"de-tenant-{suffix}"
    cid = f"de-client-{suffix}"
    mid = f"de-mandate-{suffix}"
    aid = f"de-assessment-{suffix}"
    gid_pension = f"de-goal-pension-{suffix}"
    gid_wealth = f"de-goal-wealth-{suffix}"
    cma_id = f"de-cma-{suffix}"
    now = _now()
    today = date.today()
    pension_start = (today + timedelta(days=365 * 5)).isoformat()
    pension_end = (today + timedelta(days=365 * 30)).isoformat()
    wealth_target_date = (today + timedelta(days=365 * 10)).isoformat()

    with session_factory() as s:
        s.add(Tenant(
            id=tenant_id, display_name=f"DE-Test-Tenant-{suffix}", slug=f"de-test-{suffix}",
            hosting_tier="tier1", license_status="active", is_active=1,
            created_at=now, updated_at=now,
        ))
        s.add(User(
            id=advisor_id, username=f"de-adv-{suffix}", password_hash="h",
            full_name="DE Test Advisor", role="advisor", is_active=1,
            tenant_id=tenant_id, created_at=now, updated_at=now,
        ))
        s.commit()
        # Jurisdiktionsunabhaengiger Bootstrap (globale Policy/House-Matrix +
        # CH-Referenzdaten -- unveraendertes CH-Verhalten, siehe WP2-Doku).
        policy, _ch_cma = ensure_runtime_reference_data(s, advisor_id)
        ensure_de_jurisdiction_seed(s)
        s.add(CapitalMarketAssumption(
            id=cma_id, assumption_set_name=f"DE-Test-{suffix}", version=1,
            valid_from=today.isoformat(), is_current=1, jurisdiction=DE_CODE, tenant_id=None,
            status=cma_status,
            equity_home_return_bps=650, equity_home_vol_bps=1500,
            bonds_home_ig_return_bps=200, bonds_home_ig_vol_bps=380,
            real_estate_home_return_bps=420, real_estate_home_vol_bps=800,
            alternatives_gold_return_bps=120, alternatives_gold_vol_bps=1200,
            liquidity_return_bps=80, liquidity_vol_bps=15,
            source="Test-Fixture (WP6 Integrationstest)",
            created_by=advisor_id, created_at=now, updated_at=now,
        ))
        _seed_de_building_blocks(s, policy.id)
        s.add(Client(
            id=cid, client_number=f"C-DE-{suffix}", first_name="DE", last_name="Mandant",
            advisor_id=advisor_id, created_at=now, updated_at=now,
        ))
        s.add(Mandate(
            id=mid, client_id=cid, mandate_number=f"M-DE-{suffix}",
            mandate_type="Anlageberatung", opened_at=now, tenant_id=tenant_id,
            jurisdiction=DE_CODE, base_currency="EUR",
            created_at=now, updated_at=now,
        ))
        s.add(WealthPosition(
            id=f"de-pos-depot-{suffix}", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="EUR",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id=f"de-cf-savings-{suffix}", client_id=cid, label="Sparen",
            cashflow_type="Income", amount_rappen=20_000_00,
            currency="EUR", frequency="jährlich", nature="wiederkehrend",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Goal(
            id=gid_pension, mandate_id=mid, client_id=cid,
            goal_family="Lebenshaltung", goal_type="Pensionsausgabe",
            label="Pension", rank=1, weight_bps=5000,
            goal_scope="Beratungsvermögen", value_mode="real",
            target_amount_rappen=24_000_00, frequency="jährlich",
            start_date=pension_start, target_date=pension_end,
            is_ongoing=0, hardness="Hart",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Goal(
            id=gid_wealth, mandate_id=mid, client_id=cid,
            goal_family="Vermoegen", goal_type="Vermoegensziel",
            label="Eigenheim Anzahlung", rank=2, weight_bps=3000,
            goal_scope="Beratungsvermögen", value_mode="nominal",
            target_wealth_rappen=300_000_00,
            target_date=wealth_target_date,
            is_ongoing=0, hardness="Primaer",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
            q_income_points=2, q_obligations_points=3,
            q_savings_points=8, q_wealth_points=8,
            risk_capacity_total=21, risk_capacity_profile="DE-Test",
            risk_capacity_score_x10=50,
            investment_horizon_years=15, investment_horizon_label="12 bis 17 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=4, q_risk_behavior_points=3,
            risk_willingness_total=10, risk_willingness_profile="DE-Test",
            risk_willingness_score_x10=50,
            final_score_x10=50, final_profile="DE-Test",
            is_overridden=0,
            knowledge_services_json="{}",
            knowledge_instruments_json="{}",
            income_sources_json='["Berufliche Taetigkeit"]',
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        answers = [
            (1, "Finanzdienstleistungen: Beratung und Verwaltung", 0),
            (2, "Finanzinstrumente: Anlagefonds und ETFs", 0),
            (3, "CHF 12'000 bis 20'000", 3),
            (4, "Herkunft: Berufliche Taetigkeit", 0),
            (5, "CHF 3'000 bis 5'000", 3),
            (6, "CHF 1'000'000 bis 2'000'000", 9),
            (7, "25 bis 50 %", 9),
            (8, "Mehr als 12 Jahre - Matrix-Faktor", 0),
            (9, "Das investierte Kapital soll sich stetig vermehren.", 3),
            (10, "Ich strebe eine hoehere Rendite an und bin bereit, dafuer ein erhoehtes Risiko einzugehen.", 3),
            (11, "Ich kann den Verlust voruebergehend akzeptieren und halte an meinen Anlagen fest.", 3),
        ]
        for q, label, points in answers:
            s.add(RiskAssessmentAnswer(
                id=f"de-answer-{suffix}-{q}", assessment_id=aid,
                question_number=q, question_section="Risikoprofil",
                answer_label=label, answer_points=points,
                created_at=now,
            ))
        _seed_de_products_and_universe(s, tenant_id=tenant_id)
        s.commit()
    return {
        "advisor_id": advisor_id, "tenant_id": tenant_id, "mandate_id": mid, "cma_id": cma_id,
    }


def _seed_ch_mandate(session_factory, *, suffix: str) -> dict:
    """Seedet ein CH-Mandat (jurisdiction=NULL) OHNE eigenen Tenant/CMA/
    BuildingBlocks -- nutzt bewusst den bereits vorhandenen, jurisdiktions-
    unabhaengigen CH-Bootstrap (ensure_runtime_reference_data ohne
    jurisdiction-Argument), damit dieser Test echten Cross-Talk mit
    parallel existierenden DE-Fixtures in DERSELBEN DB aufdecken wuerde."""
    advisor_id = f"ch-adv-{suffix}"
    cid = f"ch-client-{suffix}"
    mid = f"ch-mandate-{suffix}"
    aid = f"ch-assessment-{suffix}"
    gid_pension = f"ch-goal-pension-{suffix}"
    gid_wealth = f"ch-goal-wealth-{suffix}"
    now = _now()
    today = date.today()
    pension_start = (today + timedelta(days=365 * 5)).isoformat()
    pension_end = (today + timedelta(days=365 * 30)).isoformat()
    wealth_target_date = (today + timedelta(days=365 * 10)).isoformat()

    with session_factory() as s:
        s.add(User(
            id=advisor_id, username=f"ch-adv-{suffix}", password_hash="h",
            full_name="CH Test Advisor", role="advisor", is_active=1,
            created_at=now, updated_at=now,
        ))
        s.add(Client(
            id=cid, client_number=f"C-CH-{suffix}", first_name="CH", last_name="Mandant",
            advisor_id=advisor_id, created_at=now, updated_at=now,
        ))
        s.add(Mandate(
            id=mid, client_id=cid, mandate_number=f"M-CH-{suffix}",
            mandate_type="Anlageberatung", opened_at=now,
            created_at=now, updated_at=now,
            # jurisdiction bewusst NICHT gesetzt (NULL) -- Bestandsverhalten.
        ))
        s.add(WealthPosition(
            id=f"ch-pos-depot-{suffix}", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id=f"ch-cf-savings-{suffix}", client_id=cid, label="Sparen",
            cashflow_type="Income", amount_rappen=20_000_00,
            currency="CHF", frequency="jährlich", nature="wiederkehrend",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Goal(
            id=gid_pension, mandate_id=mid, client_id=cid,
            goal_family="Lebenshaltung", goal_type="Pensionsausgabe",
            label="Pension", rank=1, weight_bps=5000,
            goal_scope="Beratungsvermögen", value_mode="real",
            target_amount_rappen=24_000_00, frequency="jährlich",
            start_date=pension_start, target_date=pension_end,
            is_ongoing=0, hardness="Hart",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Goal(
            id=gid_wealth, mandate_id=mid, client_id=cid,
            goal_family="Vermoegen", goal_type="Vermoegensziel",
            label="Eigenheim Anzahlung", rank=2, weight_bps=3000,
            goal_scope="Beratungsvermögen", value_mode="nominal",
            target_wealth_rappen=300_000_00,
            target_date=wealth_target_date,
            is_ongoing=0, hardness="Primaer",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
            q_income_points=2, q_obligations_points=3,
            q_savings_points=8, q_wealth_points=8,
            risk_capacity_total=21, risk_capacity_profile="CH-Test",
            risk_capacity_score_x10=50,
            investment_horizon_years=15, investment_horizon_label="12 bis 17 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=4, q_risk_behavior_points=3,
            risk_willingness_total=10, risk_willingness_profile="CH-Test",
            risk_willingness_score_x10=50,
            final_score_x10=50, final_profile="CH-Test",
            is_overridden=0,
            knowledge_services_json="{}",
            knowledge_instruments_json="{}",
            income_sources_json='["Berufliche Taetigkeit"]',
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        answers = [
            (1, "Finanzdienstleistungen: Beratung und Verwaltung", 0),
            (2, "Finanzinstrumente: Anlagefonds und ETFs", 0),
            (3, "CHF 12'000 bis 20'000", 3),
            (4, "Herkunft: Berufliche Taetigkeit", 0),
            (5, "CHF 3'000 bis 5'000", 3),
            (6, "CHF 1'000'000 bis 2'000'000", 9),
            (7, "25 bis 50 %", 9),
            (8, "Mehr als 12 Jahre - Matrix-Faktor", 0),
            (9, "Das investierte Kapital soll sich stetig vermehren.", 3),
            (10, "Ich strebe eine hoehere Rendite an und bin bereit, dafuer ein erhoehtes Risiko einzugehen.", 3),
            (11, "Ich kann den Verlust voruebergehend akzeptieren und halte an meinen Anlagen fest.", 3),
        ]
        for q, label, points in answers:
            s.add(RiskAssessmentAnswer(
                id=f"ch-answer-{suffix}-{q}", assessment_id=aid,
                question_number=q, question_section="Risikoprofil",
                answer_label=label, answer_points=points,
                created_at=now,
            ))
        s.commit()
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return {"advisor_id": advisor_id, "mandate_id": mid}


def _seed_pm_and_advisor_users(session_factory, *, tenant_id: str, suffix: str) -> dict:
    now = _now()
    pm_id = f"pm-{suffix}"
    advisor_id = f"advisor-role-{suffix}"
    with session_factory() as s:
        existing_tenant = s.query(Tenant).filter(Tenant.id == tenant_id).first()
        if existing_tenant is None:
            s.add(Tenant(
                id=tenant_id, display_name=tenant_id, slug=tenant_id,
                hosting_tier="tier1", license_status="active", is_active=1,
                created_at=now, updated_at=now,
            ))
        s.add(User(
            id=pm_id, username=pm_id, password_hash="h", full_name="Portfolio Management",
            role="portfolio_management", is_active=1, tenant_id=tenant_id,
            created_at=now, updated_at=now,
        ))
        s.add(User(
            id=advisor_id, username=advisor_id, password_hash="h", full_name="Advisor",
            role="advisor", is_active=1, tenant_id=tenant_id,
            created_at=now, updated_at=now,
        ))
        s.commit()
    return {"pm_id": pm_id, "advisor_id": advisor_id}


# ===========================================================================
# 1. Kompletter DE-Mandats-Flow (Engine-Ebene)
# ===========================================================================


def test_full_de_mandate_flow_data_derived_then_committee_approved_via_router(client, session_factory):
    seeded = _seed_de_mandate(session_factory, suffix="flow1", cma_status="data_derived")
    advisor_id, mid, cma_id = seeded["advisor_id"], seeded["mandate_id"], seeded["cma_id"]

    # --- Schritt A: Target-Allocation zeigt DE-Labels, keine CH-Labels. ---
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        target_result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
    sub_labels = {str(item["sub_asset_class"]) for item in target_result["sub_allocations"]}
    assert sub_labels, "DE-Mandat lieferte keine sub_allocations"
    assert any("Deutschland" in label for label in sub_labels), sub_labels
    assert not any("Schweiz" in label for label in sub_labels), sub_labels
    assert not any("CHF" in label for label in sub_labels)

    # --- Schritt B: Recommendation-Run mit "data_derived"-CMA -> Warnung. ---
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        run_result_before = generate_recommendation_run(s, mandate, advisor_id, preferences=None)
    run_before = run_result_before["run"]
    assert run_before.provisional_data_warning is not None
    warning_payload = json.loads(run_before.provisional_data_warning)
    assert warning_payload["jurisdiction"] == "DE"
    assert warning_payload["cma_status"] == "data_derived"
    assert "PROVISORISCH" in warning_payload["message"]

    # Positivliste greift: nur erlaubte Produkt-IDs, der guenstigere
    # verbotene Duplikat-Fonds fuer "Aktien Deutschland" wird NICHT gewaehlt.
    positions_before = run_result_before["positions"]
    used_ids = {str(p["product_id"]) for p in positions_before}
    assert _DE_FORBIDDEN_CHEAP_PRODUCT_ID not in used_ids, (
        "ProductUniverseEntry-Positivliste hat den nicht gelisteten, "
        "guenstigeren Fonds nicht ausgefiltert"
    )
    de_aktien_positions = [p for p in positions_before if p["sub_asset_class"] == "Aktien Deutschland"]
    assert de_aktien_positions, "Keine Position fuer 'Aktien Deutschland' im DE-Run gefunden"
    assert all(p["product_id"] == "de-int-aktien-de" for p in de_aktien_positions), (
        "Erwartet den gelisteten Fonds 'de-int-aktien-de' fuer 'Aktien Deutschland', "
        f"erhalten: {[p['product_id'] for p in de_aktien_positions]}"
    )
    position_labels = {str(p["sub_asset_class"]) for p in positions_before}
    assert not any("Schweiz" in label for label in position_labels), position_labels

    # --- Schritt C: Freigabe ueber den echten Router-Endpoint (kein
    # direkter ORM-Zugriff) -- Rollen-Gate: advisor -> 403 zuerst geprueft. ---
    roles = _seed_pm_and_advisor_users(session_factory, tenant_id=seeded["tenant_id"], suffix="flow1")
    _login_as(roles["advisor_id"], "advisor", tenant_id=seeded["tenant_id"])
    try:
        forbidden = client.post(f"/capital-market-assumptions/{cma_id}/approve")
        assert forbidden.status_code == 403
    finally:
        _logout()

    _login_as(roles["pm_id"], "portfolio_management", tenant_id=seeded["tenant_id"])
    try:
        approved = client.post(f"/capital-market-assumptions/{cma_id}/approve")
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "committee_approved"
        assert approved.json()["is_current"] == 1
    finally:
        _logout()

    # GET liefert jetzt committee_approved fuer DE (unabhaengiges Nachweis
    # ueber den bestehenden GET-Endpoint aus WP3).
    _login_as(roles["pm_id"], "portfolio_management", tenant_id=seeded["tenant_id"])
    try:
        got = client.get("/capital-market-assumptions/current", params={"jurisdiction": "DE"})
        assert got.status_code == 200
        assert got.json()["id"] == cma_id
        assert got.json()["status"] == "committee_approved"
    finally:
        _logout()

    # --- Schritt D: derselbe Mandats-Lauf NACH der Freigabe -> keine
    # Warnung mehr (dieselbe CMA-Zeile, nur ihr Status hat sich geaendert). ---
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        run_result_after = generate_recommendation_run(s, mandate, advisor_id, preferences=None)
    run_after = run_result_after["run"]
    assert run_after.provisional_data_warning is None, (
        "Nach IC-Freigabe (committee_approved) darf kein provisional_data_warning "
        "mehr gesetzt werden"
    )


# ===========================================================================
# 2. Router-Integrationstest: compute-candidate -> approve -> GET
# ===========================================================================


def test_router_compute_candidate_then_approve_then_get_current(client, session_factory):
    roles = _seed_pm_and_advisor_users(session_factory, tenant_id="main", suffix="router1")

    def _fake_compute(db, jurisdiction, as_of_date):
        now = _now()
        cma = CapitalMarketAssumption(
            id="cma-router-de-1", assumption_set_name="DE-router-test", version=1,
            valid_from=as_of_date, is_current=0, jurisdiction=jurisdiction, tenant_id=None,
            status="data_derived", bonds_home_ig_return_bps=210,
            source_detail=json.dumps({"source": "fake-yield-curve-for-test"}),
            created_by="system:cma_data_pipeline", created_at=now, updated_at=now,
        )
        db.add(cma)
        db.flush()
        return cma

    import routers.jurisdiction as jr_mod
    original = jr_mod.compute_cma_candidate_for_jurisdiction
    jr_mod.compute_cma_candidate_for_jurisdiction = _fake_compute
    try:
        _login_as(roles["pm_id"], "portfolio_management")
        try:
            computed = client.post("/jurisdictions/DE/cma/compute-candidate")
            assert computed.status_code == 200, computed.text
            body = computed.json()
            assert body["jurisdiction"] == "DE"
            assert body["status"] == "data_derived"
            assert body["is_current"] == 0
            cma_id = body["id"]
        finally:
            _logout()

        _login_as(roles["pm_id"], "portfolio_management")
        try:
            approved = client.post(f"/capital-market-assumptions/{cma_id}/approve")
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "committee_approved"
            assert approved.json()["is_current"] == 1
        finally:
            _logout()

        _login_as(roles["pm_id"], "portfolio_management")
        try:
            current = client.get("/capital-market-assumptions/current", params={"jurisdiction": "DE"})
            assert current.status_code == 200
            assert current.json()["id"] == cma_id
            assert current.json()["status"] == "committee_approved"
        finally:
            _logout()
    finally:
        jr_mod.compute_cma_candidate_for_jurisdiction = original


# ===========================================================================
# 3. Rollen-Test End-to-End gegen eine echte, per compute-candidate erzeugte
#    Kandidaten-Zeile.
# ===========================================================================


def test_role_gate_end_to_end_advisor_forbidden_pm_allowed(client, session_factory):
    roles = _seed_pm_and_advisor_users(session_factory, tenant_id="main", suffix="role1")

    def _fake_compute(db, jurisdiction, as_of_date):
        now = _now()
        cma = CapitalMarketAssumption(
            id="cma-role-de-1", assumption_set_name="DE-role-test", version=1,
            valid_from=as_of_date, is_current=0, jurisdiction=jurisdiction, tenant_id=None,
            status="data_derived", bonds_home_ig_return_bps=190,
            created_by="system:cma_data_pipeline", created_at=now, updated_at=now,
        )
        db.add(cma)
        db.flush()
        return cma

    import routers.jurisdiction as jr_mod
    original = jr_mod.compute_cma_candidate_for_jurisdiction
    jr_mod.compute_cma_candidate_for_jurisdiction = _fake_compute
    try:
        _login_as(roles["pm_id"], "portfolio_management")
        try:
            computed = client.post("/jurisdictions/DE/cma/compute-candidate")
            assert computed.status_code == 200, computed.text
            cma_id = computed.json()["id"]
        finally:
            _logout()
    finally:
        jr_mod.compute_cma_candidate_for_jurisdiction = original

    # advisor -> 403, Zeile bleibt data_derived.
    _login_as(roles["advisor_id"], "advisor")
    try:
        denied = client.post(f"/capital-market-assumptions/{cma_id}/approve")
        assert denied.status_code == 403
    finally:
        _logout()
    with session_factory() as s:
        row = s.query(CapitalMarketAssumption).filter(CapitalMarketAssumption.id == cma_id).first()
        assert row.status == "data_derived"

    # portfolio_management -> 200, Zeile wird committee_approved.
    _login_as(roles["pm_id"], "portfolio_management")
    try:
        allowed = client.post(f"/capital-market-assumptions/{cma_id}/approve")
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["status"] == "committee_approved"
    finally:
        _logout()


# ===========================================================================
# 4. CH-Isolation: DE- und CH-Mandat in DERSELBEN Test-DB, kein Cross-Talk.
# ===========================================================================


def test_ch_mandate_unaffected_by_coexisting_de_fixtures_in_same_db(client, session_factory):
    # DE-Fixtures zuerst anlegen (inkl. Positivliste, DE-CMA, DE-BuildingBlocks).
    de_seeded = _seed_de_mandate(session_factory, suffix="isolation", cma_status="committee_approved")
    # CH-Mandat in DERSELBEN DB.
    ch_seeded = _seed_ch_mandate(session_factory, suffix="isolation")

    with session_factory() as s:
        ch_mandate = s.query(Mandate).filter(Mandate.id == ch_seeded["mandate_id"]).first()
        assert ch_mandate.jurisdiction is None
        ch_target = generate_target_allocation(s, ch_mandate, ch_seeded["advisor_id"], preferences=None)
        ch_run_result = generate_recommendation_run(s, ch_mandate, ch_seeded["advisor_id"], preferences=None)

    ch_sub_labels = {str(item["sub_asset_class"]) for item in ch_target["sub_allocations"]}
    assert ch_sub_labels, "CH-Mandat lieferte keine sub_allocations"
    assert any("Schweiz" in label for label in ch_sub_labels), (
        f"CH-Mandat verlor sein 'Schweiz'-Heimmarkt-Label trotz koexistierender DE-Fixtures: {ch_sub_labels}"
    )
    assert not any("Deutschland" in label for label in ch_sub_labels), (
        f"CH-Mandat zeigt DE-Label -- Cross-Talk zwischen Jurisdiktionen: {ch_sub_labels}"
    )

    ch_run = ch_run_result["run"]
    assert ch_run.provisional_data_warning is None, (
        "CH-Recommendation-Run darf NIE einen provisional_data_warning setzen"
    )
    ch_position_labels = {str(p["sub_asset_class"]) for p in ch_run_result["positions"]}
    assert not any("Deutschland" in label for label in ch_position_labels), ch_position_labels
    # Der CH-Run darf keinen der DE-only Produkt-IDs (de-int-*) verwenden --
    # eigener, jurisdiktionsunabhaengiger CH-Fondskatalog (ensure_default_products).
    ch_used_ids = {str(p["product_id"]) for p in ch_run_result["positions"]}
    assert not any(pid.startswith("de-int-") for pid in ch_used_ids), ch_used_ids

    # CH-CMA-Zeile (jurisdiction IS NULL) bleibt von der DE-Freigabe unberuehrt.
    with session_factory() as s:
        ch_cma_rows = s.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.jurisdiction.is_(None),
        ).all()
        assert len(ch_cma_rows) == 1, "Es sollte genau eine CH-CMA-Zeile geben (jurisdiktionsunabhaengiger Bootstrap)"
        assert ch_cma_rows[0].is_current == 1

        de_cma_row = s.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id == de_seeded["cma_id"],
        ).first()
        assert de_cma_row.jurisdiction == "DE"
        assert de_cma_row.status == "committee_approved"
        assert de_cma_row.is_current == 1

    # GET-Endpoint: CH-Default (kein Query-Param) liefert weiterhin die
    # CH-Zeile, DE-Query liefert die separate DE-Zeile -- keine Vermischung.
    roles = _seed_pm_and_advisor_users(session_factory, tenant_id="main", suffix="isolation-get")
    _login_as(roles["pm_id"], "portfolio_management")
    try:
        ch_get = client.get("/capital-market-assumptions/current")
        assert ch_get.status_code == 200
        assert ch_get.json()["jurisdiction"] is None

        de_get = client.get("/capital-market-assumptions/current", params={"jurisdiction": "DE"})
        assert de_get.status_code == 200
        assert de_get.json()["id"] == de_seeded["cma_id"]
        assert de_get.json()["jurisdiction"] == "DE"
    finally:
        _logout()
