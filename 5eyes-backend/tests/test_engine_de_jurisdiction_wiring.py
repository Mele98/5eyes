"""WP2 (Engine-Wiring Jurisdiktion, 2026-07-31): Tests fuer den Nicht-CH-Pfad
in services/portfolio_engine.py (_build_sub_allocations, ensure_runtime_
reference_data, _asset_class_expected_metrics, ensure_default_products,
Produktfilter-Jurisdiktionskontext, RecommendationRun.provisional_data_warning).

Verifiziert (Gegenstueck zu tests/test_golden_snapshot_ch_regression.py, das
den CH-Pfad einfriert):
  - Ein DE-Mandat (jurisdiction="DE") mit einer IC-freigegebenen
    ("committee_approved") DE-CapitalMarketAssumption-Zeile + DE-BuildingBlock-
    Zeilen produziert DE-Sub-Allocation-Labels (z.B. "Aktien Deutschland")
    und KEINE CH-Labels ("Schweiz").
  - generate_recommendation_run() fuer dasselbe Mandat waehlt Produkte mit
    DE-Sub-Asset-Class-Labels, keine CH-Labels, und provisional_data_warning
    bleibt NULL (weil die CMA-Zeile committee_approved ist).
  - Ein DE-Mandat OHNE committee_approved-CMA (status="data_derived") bekommt
    provisional_data_warning gesetzt (JSON mit jurisdiction/cma_status/
    message) -- Design-Entscheidung dieses Arbeitspakets (siehe Aufgabe 6):
    NICHT hart blockieren (require_committee_approved=False bleibt in
    ensure_runtime_reference_data()), sondern sichtbar auf dem Run markieren.
    Das harte Blockieren fuer finale Kundendokumente (PDF) ist Teil eines
    spaeteren, noch nicht gebauten Arbeitspakets (siehe
    services/jurisdiction/provisional_gate.py::assert_jurisdiction_ready()).
  - ensure_runtime_reference_data() seedet fuer DE KEINEN CH-Fondskatalog.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from sqlalchemy.orm import configure_mappers

from database import Base
from models import (  # noqa: F401
    allocation, clients, jurisdiction, mandates, profiling, review, snapshots, tenant, users, wealth,
)
configure_mappers()
from models.allocation import BuildingBlock, CapitalMarketAssumption, OptimizerPolicy
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment, RiskAssessmentAnswer
from models.review import Product
from models.tenant import Tenant
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.jurisdiction.de_seed import DE_CODE, ensure_de_jurisdiction_seed
from services.jurisdiction.exceptions import JurisdictionReferenceDataMissingError
from services.portfolio_engine import (
    _building_block_risky_map,
    _building_block_rows_for_policy,
    ensure_default_products,
    ensure_runtime_reference_data,
    generate_recommendation_run,
    generate_target_allocation,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'de_jurisdiction_wiring.db'}",
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield testing_session_local
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# ---------------------------------------------------------------------------
# DE-Sub-Asset-Class-Labels, die fuer die Ausgewogen-Default-Praeferenzen
# (equitiesGeo="Deutschland Fokus", bondsDuration="Langfristig",
# realestateMarket="Deutschland") und die generischen Alternativen-/
# Liquiditaets-Defaults tatsaechlich in sub_allocations auftauchen koennen
# (siehe services/jurisdiction/de_seed.py DE_HOME_BIAS_DEFAULTS).
# ---------------------------------------------------------------------------
_DE_PRODUCT_DEFAULTS = [
    # (product_name, provider, product_type, asset_class, sub_asset_class, currency, ter_bps)
    ("DE-Aktien-ETF", "Test-Provider", "ETF", "Aktien", "Aktien Deutschland", "EUR", 15),
    ("Global-Aktien-ETF", "Test-Provider", "ETF", "Aktien", "Aktien Global", "USD", 20),
    ("Europa-Aktien-ETF", "Test-Provider", "ETF", "Aktien", "Aktien Europa", "EUR", 12),
    ("EM-Aktien-ETF", "Test-Provider", "ETF", "Aktien", "Aktien Schwellenlaender", "USD", 18),
    ("EUR-IG-Bond-Fonds", "Test-Provider", "Fonds", "Obligationen", "Obligationen EUR IG", "EUR", 30),
    ("Global-Hedged-Bond-ETF", "Test-Provider", "ETF", "Obligationen", "Obligationen Global EUR-Hedged", "EUR", 15),
    ("HY-Bond-Fonds", "Test-Provider", "Fonds", "Obligationen", "Obligationen High Yield", "EUR", 55),
    ("EM-Bond-Fonds", "Test-Provider", "Fonds", "Obligationen", "Obligationen Emerging", "USD", 60),
    ("DE-Immobilienfonds", "Test-Provider", "Immobilienfonds", "Immobilien", "Immobilien Deutschland", "EUR", 50),
    ("Global-Immobilien-ETF", "Test-Provider", "ETF", "Immobilien", "Immobilien Global", "USD", 38),
    ("Gold-ETF", "Test-Provider", "ETF", "Alternative", "Gold / Rohstoffe", "EUR", 40),
    ("EUR-Geldmarktfonds", "Test-Provider", "Fonds", "Liquiditaet", "Geldmarktfonds", "EUR", 8),
]


def _seed_de_products(s) -> None:
    now = _now()
    for name, provider, product_type, asset_class, sub_asset_class, currency, ter_bps in _DE_PRODUCT_DEFAULTS:
        s.add(Product(
            id=f"de-product-{sub_asset_class}", product_name=name, provider=provider,
            product_type=product_type, asset_class=asset_class, sub_asset_class=sub_asset_class,
            currency=currency, ter_bps=ter_bps, is_active=1, created_at=now, updated_at=now,
        ))


def _seed_de_building_blocks(s, policy_id: str) -> None:
    """DE-BuildingBlock-Zeilen (zusaetzlich zu den CH-Zeilen aus dem globalen
    Policy-Bootstrap). Nur die tatsaechlich DE-spezifischen Heimmarkt-Labels
    (die es unter CH-Namen nicht gibt) bekommen jurisdiction="DE" -- die
    generischen, jurisdiktionsunabhaengigen Labels (Aktien Global/Europa/
    Schwellenlaender, Obligationen High Yield/Emerging, Immobilien Global,
    Gold / Rohstoffe, Geldmarktfonds) existieren bereits aus dem CH-Bootstrap
    (jurisdiction IS NULL) und werden hier nicht dupliziert."""
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


def _seed_de_mandate(session_factory, *, suffix: str, cma_status: str) -> tuple[str, str, str]:
    """Seedet ein DE-Mandat (tenant_id gesetzt, jurisdiction="DE",
    base_currency="EUR") + eine firmenweite (tenant_id=NULL) DE-CMA-Zeile mit
    dem gegebenen Status. Bootstrapt zuerst per ensure_runtime_reference_data()
    (CH-Default) die globale OptimizerPolicy/House-Matrix (jurisdiktions-
    unabhaengig, siehe WP2-Doku) -- KEIN CH-Fondskatalog wird dabei fuer das
    DE-Mandat verwendet (ensure_default_products() wird separat mit
    jurisdiction="DE" aufgerufen und seedet bewusst nichts)."""
    advisor_id = f"de-adv-{suffix}"
    tenant_id = f"de-tenant-{suffix}"
    cid = f"de-client-{suffix}"
    mid = f"de-mandate-{suffix}"
    aid = f"de-assessment-{suffix}"
    gid_pension = f"de-goal-pension-{suffix}"
    gid_wealth = f"de-goal-wealth-{suffix}"
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
        # Jurisdiktionsunabhaengiger Bootstrap (Policy/House-Matrix/CH-BBs/CH-CMA) --
        # siehe WP2-Doku: policy bleibt die globale OptimizerPolicy.
        policy, _ch_cma = ensure_runtime_reference_data(s, advisor_id)
        ensure_de_jurisdiction_seed(s)
        s.add(CapitalMarketAssumption(
            id=f"de-cma-{suffix}", assumption_set_name=f"DE-Test-{suffix}", version=1,
            valid_from=today.isoformat(), is_current=1, jurisdiction=DE_CODE, tenant_id=None,
            status=cma_status,
            equity_home_return_bps=650, equity_home_vol_bps=1500,
            bonds_home_ig_return_bps=200, bonds_home_ig_vol_bps=380,
            real_estate_home_return_bps=420, real_estate_home_vol_bps=800,
            alternatives_gold_return_bps=120, alternatives_gold_vol_bps=1200,
            liquidity_return_bps=80, liquidity_vol_bps=15,
            source="Test-Fixture (IC-Freigabe simuliert)",
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
        _seed_de_products(s)
        s.commit()
    return advisor_id, mid, tenant_id


def _sub_asset_class_labels(sub_allocations: list[dict]) -> set[str]:
    return {str(item["sub_asset_class"]) for item in sub_allocations}


def test_de_mandate_target_allocation_uses_de_labels_no_ch_labels(session_factory):
    advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix="target-approved", cma_status="committee_approved",
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)

    labels = _sub_asset_class_labels(result["sub_allocations"])
    assert labels, "DE-Mandat lieferte keine sub_allocations"
    assert any("Deutschland" in label for label in labels), (
        f"Erwartet mindestens ein 'Deutschland'-Label in {labels}"
    )
    assert not any("Schweiz" in label for label in labels), (
        f"CH-Label ('Schweiz') in DE-Sub-Allocation gefunden: {labels}"
    )
    assert not any("CHF" in label for label in labels)


def test_de_mandate_recommendation_run_uses_de_products_and_no_provisional_warning(session_factory):
    advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix="run-approved", cma_status="committee_approved",
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_recommendation_run(s, mandate, advisor_id, preferences=None)

    position_labels = {str(p["sub_asset_class"]) for p in result["positions"]}
    assert position_labels, "DE-Recommendation-Run lieferte keine Positionen"
    assert not any("Schweiz" in label for label in position_labels), (
        f"CH-Label in DE-Recommendation-Positionen gefunden: {position_labels}"
    )
    run = result["run"]
    assert run.provisional_data_warning is None, (
        "committee_approved-CMA darf KEINEN provisional_data_warning setzen"
    )


def test_de_mandate_without_committee_approval_sets_provisional_warning(session_factory):
    advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix="run-provisional", cma_status="data_derived",
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_recommendation_run(s, mandate, advisor_id, preferences=None)

    run = result["run"]
    assert run.provisional_data_warning is not None, (
        "DE-CMA ohne committee_approved-Status muss provisional_data_warning setzen"
    )
    payload = json.loads(run.provisional_data_warning)
    assert payload["jurisdiction"] == "DE"
    assert payload["cma_status"] == "data_derived"
    assert "PROVISORISCH" in payload["message"]


def test_ensure_default_products_seeds_nothing_for_non_ch_jurisdiction(session_factory):
    with session_factory() as s:
        ensure_default_products(s, jurisdiction="DE")
        count = s.query(Product).filter(Product.is_active == 1, Product.deleted_at.is_(None)).count()
        assert count == 0, "ensure_default_products() darf fuer DE keinen CH-Fondskatalog seeden"


def test_ensure_default_products_still_seeds_ch_when_only_de_products_exist(session_factory):
    """2026-08-01 (Cross-Jurisdiktions-Leck-Fix): der Idempotenz-Guard war
    urspruenglich 'gibt es irgendein aktives Produkt' -- das haette den
    CH-Katalog NIE geseedet, sobald zuvor bereits (jurisdiction-getaggte)
    Nicht-CH-Produkte angelegt wurden, und ein CH-Mandat haette danach gar
    keine Produkte mehr gefunden (per Integrationstest gefunden). Der Guard
    muss CH-spezifisch sein (Product.jurisdiction in (None, "CH"))."""
    now = _now()
    with session_factory() as s:
        s.add(Product(
            id="de-only-product", product_name="DE Fonds", asset_class="Aktien",
            product_type="ETF", currency="EUR", is_active=1, jurisdiction="DE",
            created_at=now, updated_at=now,
        ))
        s.commit()

        ensure_default_products(s, jurisdiction="CH")
        ch_count = s.query(Product).filter(
            Product.is_active == 1, Product.deleted_at.is_(None),
            (Product.jurisdiction.is_(None)) | (Product.jurisdiction == "CH"),
        ).count()
        assert ch_count > 0, (
            "ensure_default_products() hat den CH-Katalog nicht geseedet, obwohl "
            "nur Nicht-CH-Produkte vorhanden waren -- CH-Mandate faenden keine Produkte"
        )


def test_ensure_default_products_ch_idempotent_when_ch_products_already_exist(session_factory):
    now = _now()
    with session_factory() as s:
        ensure_default_products(s, jurisdiction="CH")
        first_count = s.query(Product).filter(Product.is_active == 1, Product.deleted_at.is_(None)).count()
        assert first_count > 0

        ensure_default_products(s, jurisdiction="CH")
        second_count = s.query(Product).filter(Product.is_active == 1, Product.deleted_at.is_(None)).count()
        assert second_count == first_count, "Zweiter Aufruf darf den CH-Katalog nicht duplizieren"


# ---------------------------------------------------------------------------
# WP-A (2026-08-01): BuildingBlock-Risky-Fraction-Gewichtung wird
# jurisdiktions-bewusst. Vorher lasen _building_block_rows_for_policy()/
# _building_block_risky_map() IMMER den gesamten (CH+DE gemischten)
# BuildingBlock-Bestand einer policy_id, unabhaengig von der Jurisdiktion
# des Mandats -- resolve_building_blocks_for_jurisdiction() wurde in
# ensure_runtime_reference_data() nur als isolierte Fail-Fast-Validierung
# aufgerufen, ihr Rueckgabewert floss aber NIE in die tatsaechliche
# Risky-Fraction-Berechnung ein.
# ---------------------------------------------------------------------------

def test_building_block_risky_map_de_jurisdiction_excludes_colliding_ch_row(session_factory):
    """Direkter Unit-Beweis auf den beiden eigentlichen Konsumenten: ein
    CH-Bestand (jurisdiction IS NULL) und eine DE-Zeile fuer denselben
    policy_id + denselben (asset_class, sub_asset_class)-Schluessel, aber mit
    stark abweichendem risky_fraction_bps. jurisdiction='DE' darf NUR den
    DE-Wert liefern, nicht den kollidierenden CH-Wert (egal in welcher
    Reihenfolge die Zeilen aus der DB kommen)."""
    now = _now()
    with session_factory() as s:
        policy, _cma = ensure_runtime_reference_data(s, "unit-advisor")
        s.add(BuildingBlock(
            id="unit-ch-collision", policy_id=policy.id,
            asset_class="Aktien", sub_asset_class="Aktien Deutschland",
            universe="Standard", advisory=1, risky_fraction_bps=111,
            is_active=1, jurisdiction=None,
            created_at=now, updated_at=now,
        ))
        s.add(BuildingBlock(
            id="unit-de-row", policy_id=policy.id,
            asset_class="Aktien", sub_asset_class="Aktien Deutschland",
            universe="Standard", advisory=1, risky_fraction_bps=7000,
            is_active=1, jurisdiction=DE_CODE,
            created_at=now, updated_at=now,
        ))
        s.commit()

        de_rows = _building_block_rows_for_policy(s, policy.id, None, "DE")
        assert de_rows, "resolve_building_blocks_for_jurisdiction lieferte keine DE-Zeilen"
        assert all(row.jurisdiction == DE_CODE for row in de_rows), (
            "DE-Filter liess eine CH-Zeile (jurisdiction IS NULL) durch"
        )

        de_risky_map = _building_block_risky_map(s, policy.id, None, "DE")
        assert de_risky_map[("Aktien", "Aktien Deutschland")] == 7000, (
            f"DE-Risky-Map uebernahm den kollidierenden CH-Wert statt 7000: {de_risky_map}"
        )

        # CH-Pfad bleibt unveraendert (Constraint 1): KEIN Jurisdiktionsfilter,
        # sieht also weiterhin auch die DE-Zeile (Bestandsverhalten).
        ch_rows = _building_block_rows_for_policy(s, policy.id, None, "CH")
        assert any(row.id == "unit-ch-collision" for row in ch_rows)
        assert any(row.id == "unit-de-row" for row in ch_rows)


def test_de_mandate_target_allocation_risky_fraction_uses_only_de_rows(session_factory):
    """End-to-End-Bug-Beweis (Aufgabe 6 der WP-A-Spec): fuer dieselbe
    policy_id existieren GLEICHZEITIG eine CH-Zeile (jurisdiction IS NULL)
    und die DE-spezifische Zeile aus _seed_de_building_blocks() mit demselben
    sub_asset_class-Label ("Aktien Deutschland"), aber unterschiedlichem
    risky_fraction_bps. generate_target_allocation() fuer das DE-Mandat darf
    in den enrichten sub_allocations NUR den DE-Wert (7000) zeigen, nicht den
    kollidierenden CH-Wert (111) aus dem gemischten Bestand."""
    advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix="mixed-risky", cma_status="committee_approved",
    )
    with session_factory() as s:
        policy = s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
        now = _now()
        s.add(BuildingBlock(
            id="ch-collision-aktien-deutschland", policy_id=policy.id,
            asset_class="Aktien", sub_asset_class="Aktien Deutschland",
            universe="Standard", advisory=1, risky_fraction_bps=111,
            is_active=1, jurisdiction=None,
            created_at=now, updated_at=now,
        ))
        s.commit()

        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)

    de_subs = [
        item for item in result["sub_allocations"]
        if item.get("sub_asset_class") == "Aktien Deutschland"
    ]
    assert de_subs, "Erwartet eine 'Aktien Deutschland'-Sub-Allocation im DE-Ergebnis"
    for item in de_subs:
        assert item["risky_fraction_bps"] == 7000, (
            "DE-Mandat uebernahm den kollidierenden CH-Wert (111) statt des "
            f"DE-spezifischen Werts (7000) aus dem gemischten CH+DE-Bestand: {item}"
        )


def test_de_mandate_without_de_building_blocks_fails_fast(session_factory):
    """Aufgabe 4 der WP-A-Spec: ein DE-Mandat mit einer gueltigen
    (committee_approved) DE-CMA, aber OHNE eigene DE-BuildingBlock-Zeilen
    (nur der CH-Bootstrap-Bestand der globalen Policy existiert noch), muss
    beim Generieren der Ziel-Allokation sauber mit
    JurisdictionReferenceDataMissingError scheitern -- NICHT stillschweigend
    mit 0 oder mit den falschen (CH-)Gewichten weiterrechnen."""
    advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix="missing-de-bb", cma_status="committee_approved",
    )
    with session_factory() as s:
        de_rows = s.query(BuildingBlock).filter(BuildingBlock.jurisdiction == DE_CODE).all()
        assert de_rows, "Fixture-Vorbedingung verletzt: DE-BuildingBlocks muessen zuerst existieren"
        for row in de_rows:
            row.is_active = 0
        s.commit()

        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        with pytest.raises(JurisdictionReferenceDataMissingError):
            generate_target_allocation(s, mandate, advisor_id, preferences=None)
