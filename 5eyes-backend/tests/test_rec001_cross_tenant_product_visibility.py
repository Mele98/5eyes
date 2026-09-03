"""REC-001 (Codex-Audit): generate_recommendation_run() lud den Produkt-
kandidaten-Pool bisher OHNE jeden Tenant-Filter
(services/portfolio_engine.py::generate_recommendation_run):

    products = db.query(Product).filter(Product.deleted_at.is_(None), Product.is_active == 1).all()

Ein privates Produkt eines FREMDEN Tenants (Product.tenant_id gesetzt, siehe
models/review.py::Product.tenant_id-Docstring: NULL=globaler/geteilter
Katalog, gesetzt=privat fuer GENAU diesen Tenant) konnte dadurch in die
Empfehlung eines Mandats einfliessen, das gar nicht zu diesem Tenant gehoert
-- insbesondere wenn dieses fremde private Produkt guenstiger (niedrigerer
ter_bps) als der globale Katalogeintrag fuer dieselbe Sub-Asset-Class war
(_product_score() zieht ter_bps direkt vom Score ab, siehe
services/portfolio_engine_payload.py::_product_score).

_filter_products_by_universe() (direkt im Anschluss aufgerufen) schuetzt
davor NICHT zuverlaessig: ohne kuratierte ProductUniverseEntry-Positivliste
(der Normalfall, u.a. Tier-1/Holger) filtert sie nur nach Jurisdiktion,
nicht nach Tenant -- siehe deren eigener Docstring.

Der Fix (_tenant_visible_products_query() in
services/portfolio_engine_payload.py) spiegelt exakt die Filterlogik von
routers/review.py::_active_products_query() (Product.tenant_id IS NULL ODER
== mandate.tenant_id), aufgeloest ueber das MANDAT (nicht den aufrufenden
User).

Diese Tests decken ab:
1. Kreuz-Mandanten-Leck: das private Produkt von Tenant A darf in einer
   Empfehlung fuer ein Mandat von Tenant B NICHT auftauchen, obwohl es
   guenstiger und damit ohne Filter der klare Gewinner waere (RED vor dem
   Fix, GRUEN danach).
2. Positivkontrolle: das EIGENE private Produkt eines Tenants bleibt in
   dessen eigenen Empfehlungen weiterhin waehlbar (der Fix ist kein
   Totalausschluss privater Produkte, nur eine Tenant-Grenze).
3. Tier-1-Regression: ein Mandat OHNE tenant_id (Bestandsverhalten, Holger)
   mit ausschliesslich globalem Katalog (Product.tenant_id IS NULL) bleibt
   unveraendert -- der neue Filter ist dort ein No-Op.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.profiling import RiskAssessment, RiskAssessmentAnswer  # noqa: E402
from models.review import Product  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.users import User  # noqa: E402
from models.wealth import Cashflow, Goal, WealthPosition  # noqa: E402
from services.portfolio_engine import (  # noqa: E402
    ensure_runtime_reference_data,
    generate_recommendation_run,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'rec001.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_mandate(session_factory, *, suffix: str, tenant_id: str | None) -> dict:
    """Seedet ein vollstaendiges, generierungsfaehiges CH-Mandat (Client +
    Wealth + Cashflow + Goals + aktuelles Risikoprofil), optional mit
    tenant_id. Analog zu _seed_ch_mandate in
    tests/test_de_onboarding_integration.py, hier bewusst minimal gehalten."""
    advisor_id = f"adv-{suffix}"
    cid = f"client-{suffix}"
    mid = f"mandate-{suffix}"
    aid = f"assessment-{suffix}"
    gid_pension = f"goal-pension-{suffix}"
    gid_wealth = f"goal-wealth-{suffix}"
    now = _now()
    today = date.today()
    pension_start = (today + timedelta(days=365 * 5)).isoformat()
    pension_end = (today + timedelta(days=365 * 30)).isoformat()
    wealth_target_date = (today + timedelta(days=365 * 10)).isoformat()

    with session_factory() as s:
        if tenant_id:
            existing = s.query(Tenant).filter(Tenant.id == tenant_id).first()
            if existing is None:
                s.add(Tenant(
                    id=tenant_id, display_name=tenant_id, slug=tenant_id,
                    hosting_tier="tier2", license_status="active", is_active=1,
                    created_at=now, updated_at=now,
                ))
        s.add(User(
            id=advisor_id, username=advisor_id, password_hash="h", full_name="Advisor",
            role="advisor", is_active=1, tenant_id=tenant_id,
            created_at=now, updated_at=now,
        ))
        s.add(Client(
            id=cid, client_number=f"C-{suffix}", first_name="Test", last_name="Mandant",
            advisor_id=advisor_id, tenant_id=tenant_id,
            created_at=now, updated_at=now,
        ))
        s.add(Mandate(
            id=mid, client_id=cid, mandate_number=f"M-{suffix}",
            mandate_type="Anlageberatung", opened_at=now, tenant_id=tenant_id,
            created_at=now, updated_at=now,
        ))
        s.add(WealthPosition(
            id=f"pos-depot-{suffix}", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id=f"cf-savings-{suffix}", client_id=cid, label="Sparen",
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
            risk_capacity_total=21, risk_capacity_profile="Dynamisch",
            risk_capacity_score_x10=100,
            investment_horizon_years=15, investment_horizon_label="Mehr als 12 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=4, q_risk_behavior_points=3,
            risk_willingness_total=10, risk_willingness_profile="Wachstumsorientiert",
            risk_willingness_score_x10=80,
            final_score_x10=80, final_profile="Wachstumsorientiert",
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
                id=f"answer-{suffix}-{q}", assessment_id=aid,
                question_number=q, question_section="Risikoprofil",
                answer_label=label, answer_points=points,
                created_at=now,
            ))
        s.commit()
        ensure_runtime_reference_data(s, advisor_id, tenant_id=tenant_id)
        s.commit()
    return {"advisor_id": advisor_id, "mandate_id": mid}


def _add_cheap_private_product(session_factory, *, product_id: str, tenant_id: str) -> None:
    """Ein extrem guenstiger (ter_bps=1) privater Fonds fuer 'Aktien Schweiz'
    -- guenstiger als der globale CH-Default ('iShares Core SPI ETF',
    ter_bps=10, sfdr_class='8') und wuerde ohne Tenant-Filter jede Ranking-
    Runde gewinnen (siehe _product_score(): score -= ter_bps; sfdr_class in
    ('8','9') gleichauf mit dem Default gesetzt, damit ausschliesslich der
    TER-Vorteil ueber den Sieger entscheidet -- 1000-1+40+200+25=1264 vs.
    Default 1000-10+40+200+25=1255)."""
    now = _now()
    with session_factory() as s:
        s.add(Product(
            id=product_id, product_name="Guenstiger Privatfonds", provider="Privat",
            product_type="ETF", asset_class="Aktien", sub_asset_class="Aktien Schweiz",
            currency="CHF", ter_bps=1, sfdr_class="8", is_active=1, tenant_id=tenant_id,
            created_at=now, updated_at=now,
        ))
        s.commit()


def _run_and_collect_positions(session_factory, mandate_id: str, advisor_id: str) -> list[dict]:
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mandate_id).first()
        result = generate_recommendation_run(s, mandate, advisor_id, preferences=None)
    return result["positions"]


def _run_and_collect_product_ids(session_factory, mandate_id: str, advisor_id: str) -> set[str]:
    return {str(p["product_id"]) for p in _run_and_collect_positions(session_factory, mandate_id, advisor_id)}


# ---------------------------------------------------------------------------
# 1. Kreuz-Mandanten-Leck
# ---------------------------------------------------------------------------

def test_foreign_tenant_private_product_not_selected_for_other_tenants_mandate(session_factory):
    victim = _seed_mandate(session_factory, suffix="victim", tenant_id="tenant-b")
    # Tenant A existiert nur als Eigentuemer des privaten Lockprodukts --
    # kein eigenes Mandat noetig, um den Leck-Pfad zu treffen.
    with session_factory() as s:
        s.add(Tenant(
            id="tenant-a", display_name="tenant-a", slug="tenant-a",
            hosting_tier="tier2", license_status="active", is_active=1,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()
    _add_cheap_private_product(session_factory, product_id="prod-tenant-a-private", tenant_id="tenant-a")

    positions = _run_and_collect_positions(session_factory, victim["mandate_id"], victim["advisor_id"])
    used_ids = {str(p["product_id"]) for p in positions}

    assert "prod-tenant-a-private" not in used_ids, (
        "Privates Produkt von Tenant A ist in der Empfehlung fuer ein Mandat "
        f"von Tenant B gelandet -- Kreuz-Mandanten-Leck. Positionen: {used_ids}"
    )
    # Ohne den Filter waere das guenstige Fremdprodukt fuer "Aktien Schweiz"
    # der eindeutige Ranking-Gewinner gewesen -- stattdessen muss der globale
    # CH-Default ('iShares Core SPI ETF', ter_bps=10) fuer diese Sub-Asset-
    # Class verwendet werden.
    ch_equity_positions = [p for p in positions if p["sub_asset_class"] == "Aktien Schweiz"]
    assert ch_equity_positions, "Keine Position fuer 'Aktien Schweiz' gefunden"
    assert all(p["product_name"] == "iShares Core SPI ETF" for p in ch_equity_positions), (
        f"Erwartet den globalen CH-Default fuer 'Aktien Schweiz', erhalten: "
        f"{[p['product_name'] for p in ch_equity_positions]}"
    )


# ---------------------------------------------------------------------------
# 2. Positivkontrolle: eigenes privates Produkt bleibt waehlbar
# ---------------------------------------------------------------------------

def test_own_tenant_private_product_still_selected(session_factory):
    owner = _seed_mandate(session_factory, suffix="owner", tenant_id="tenant-c")
    _add_cheap_private_product(session_factory, product_id="prod-tenant-c-private", tenant_id="tenant-c")

    used_ids = _run_and_collect_product_ids(session_factory, owner["mandate_id"], owner["advisor_id"])

    assert "prod-tenant-c-private" in used_ids, (
        "Das eigene private Produkt des Tenants wurde nicht mehr ausgewaehlt -- "
        f"der Fix darf private Produkte nur fuer FREMDE Tenants ausschliessen. Positionen: {used_ids}"
    )


# ---------------------------------------------------------------------------
# 3. Tier-1-Regression: Mandat ohne tenant_id, nur globaler Katalog.
# ---------------------------------------------------------------------------

def test_tier1_mandate_without_tenant_id_unaffected(session_factory):
    holger = _seed_mandate(session_factory, suffix="tier1", tenant_id=None)

    used_ids = _run_and_collect_product_ids(session_factory, holger["mandate_id"], holger["advisor_id"])

    assert used_ids, "Tier-1-Mandat ohne tenant_id lieferte keine Positionen -- Regression."
