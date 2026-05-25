"""Tests für services/advisory_report.py — Advisory-Report-Aggregator.

Deckt die stabile 15-Seiten-Struktur ab:
- Sektion 1: Cover
- Sektion 2: Disclaimer
- Sektion 3: Inhaltsverzeichnis
- Sektion 4: Ausgangslage (Kundeninformation, Wealth-Summary, Key Metrics)
- Sektionen 5-15: Positionen bis Weiteres Vorgehen
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from models.allocation import OptimizerPolicy, TargetAllocation
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.review import (
    Product,
    RecommendationPosition,
    RecommendationRun,
)
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.advisory_report import compute_advisory_report


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'advisory_report.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


_NOW = "2026-05-24T15:00:00.000Z"


def _seed_minimal_mandate(
    s,
    *,
    advisor_name: str = "Anna Beispiel",
    client_first: str = "Hans",
    client_last: str = "Muster",
    country: str = "CH",
) -> tuple[Mandate, Client, User]:
    """Seedet die kleinste valide Mandat-Konstellation für Cover+Ausgangslage."""
    advisor = User(
        id=str(uuid.uuid4()),
        username=f"adv-{uuid.uuid4().hex[:6]}",
        password_hash="h",
        full_name=advisor_name,
        role="advisor",
        is_active=1,
        created_at=_NOW,
        updated_at=_NOW,
    )
    s.add(advisor)
    client = Client(
        id=str(uuid.uuid4()),
        client_number=f"C-{uuid.uuid4().hex[:6]}",
        first_name=client_first,
        last_name=client_last,
        advisor_id=advisor.id,
        country_of_residence=country,
        created_at=_NOW,
        updated_at=_NOW,
    )
    s.add(client)
    mandate = Mandate(
        id=str(uuid.uuid4()),
        client_id=client.id,
        mandate_number=f"M-{uuid.uuid4().hex[:6]}",
        mandate_type="Anlageberatung",
        opened_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )
    s.add(mandate)
    s.flush()
    return mandate, client, advisor


# ---------------------------------------------------------------------------
# Entry-Point: schema_version + Top-Level-Keys
# ---------------------------------------------------------------------------

def test_compute_returns_expected_top_level_structure(session_factory):
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    assert report["schema_version"] == 2
    assert report["mandate_id"] == mandate.id
    assert report["generated_at"].endswith("Z")
    expected_order = [
        "schema_version", "mandate_id", "generated_at",
        "cover", "disclaimer", "inhaltsverzeichnis", "ausgangslage",
        "positionen", "pruefpunkte", "erkenntnisse",
        "asset_allocation", "risikowaehrungen", "branchen",
        "goal_based_investing", "risikoprofilierung", "building_blocks",
        "statement_pm", "weiteres_vorgehen",
    ]
    assert list(report.keys()) == expected_order


def test_compute_raises_when_mandate_has_no_client_id(session_factory):
    """Defensiv: Mandat ohne client_id → klarer ValueError, kein silent."""
    with session_factory() as s:
        # Direktes Konstrukt eines Mandats ohne client_id (illegal, aber
        # robust gegen Datenfehler getestet)
        bad_mandate = Mandate(
            id="bad-mandate",
            client_id=None,
            mandate_number="BAD",
            mandate_type="Anlageberatung",
            opened_at=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
        )
        with pytest.raises(ValueError, match="client_id"):
            compute_advisory_report(s, bad_mandate)


# ---------------------------------------------------------------------------
# Sektion 1: Cover
# ---------------------------------------------------------------------------

def test_cover_uses_advisor_full_name_and_client_name(session_factory):
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(
            s, advisor_name="Anna Beispiel", client_first="Hans", client_last="Muster"
        )
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    cover = report["cover"]
    assert cover["title"] == "Depotcheck"
    assert cover["subtitle"] == "Strategische Portfolioanalyse"
    assert cover["client_name"] == "Hans Muster"
    assert cover["advisor_name"] == "Anna Beispiel"
    assert cover["mandate_number"].startswith("M-")
    assert len(cover["report_date"]) == 10  # YYYY-MM-DD


def test_cover_handles_missing_advisor_with_dash(session_factory):
    with session_factory() as s:
        mandate, client, _adv = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=None)
    assert report["cover"]["advisor_name"] == "—"


# ---------------------------------------------------------------------------
# Sektion 3: Inhaltsverzeichnis
# ---------------------------------------------------------------------------

def test_inhaltsverzeichnis_has_exactly_12_chapters(session_factory):
    """Spec listet 12 Kapitel. Reihenfolge + Nummerierung muss stabil sein
    weil Frontend + PDF darauf referenzieren."""
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    kapitel = report["inhaltsverzeichnis"]["kapitel"]
    assert len(kapitel) == 12
    assert [k["nr"] for k in kapitel] == list(range(1, 13))
    assert [k["title"] for k in kapitel] == [
        "Ausgangslage",
        "Übersicht Ihrer Positionen",
        "Was wir im Depotcheck prüfen",
        "Erkenntnisse aus dem Depotcheck",
        "Asset Allocation",
        "Risikowährungen",
        "Diversifikation",
        "Statement aus dem Portfoliomanagement",
        "Zielbasierte Optimierung",
        "Risikoprofilierung",
        "Building Blocks",
        "Weiteres Vorgehen",
    ]


# ---------------------------------------------------------------------------
# Sektion 4: Ausgangslage
# ---------------------------------------------------------------------------

def test_ausgangslage_client_info_uses_fallbacks(session_factory):
    """Wenn weder Risikoprofil noch Anlageziel am Mandat gepflegt sind,
    liefert die Sektion „—" statt zu crashen (UI-Render-Stabilität)."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s, country="CH")
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    info = report["ausgangslage"]["client_info"]
    assert info["steuerdomizil"] == "CH"
    assert info["referenzwaehrung"] == "CHF"
    assert info["risikoprofil"] in ("—", "")  # kein Assessment → Fallback
    assert info["anlageziel"] == "—"


def test_ausgangslage_wealth_summary_aggregates_positions(session_factory):
    """WealthPositions werden korrekt nach Kategorie aggregiert:
    gesamtvermoegen = Σ aller; beratungsvermoegen filtert auf
    assignment=Beratungsvermögen; immobilien/vorsorge nach position_type."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        # 3 Positionen: Depot (Beratungsv.), Liegenschaft, Pensionskasse
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=client.id,
            label="Depot UBS", position_type="Depot",
            assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            is_active=1, created_at=_NOW, updated_at=_NOW,
        ))
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=client.id,
            label="Liegenschaft Zürich", position_type="Immobilie",
            assignment="Eigenvermögen",
            current_value_rappen=1_200_000_00, currency="CHF",
            is_active=1, created_at=_NOW, updated_at=_NOW,
        ))
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=client.id,
            label="PK-Guthaben", position_type="Pensionskasse",
            assignment="Vorsorge",
            current_value_rappen=300_000_00, currency="CHF",
            is_active=1, created_at=_NOW, updated_at=_NOW,
        ))
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    ws = report["ausgangslage"]["wealth_summary"]
    assert ws["gesamtvermoegen_rappen"] == 2_000_000_00
    assert ws["beratungsvermoegen_rappen"] == 500_000_00
    assert ws["immobilien_rappen"] == 1_200_000_00
    assert ws["vorsorge_rappen"] == 300_000_00
    assert ws["kredite_rappen"] == 0


def test_ausgangslage_cashflows_and_goals_listed(session_factory):
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        s.add(Cashflow(
            id=str(uuid.uuid4()), client_id=client.id, label="Lohn",
            cashflow_type="Income", amount_rappen=120_000_00,
            currency="CHF", frequency="jährlich",
            nature="wiederkehrend",
            is_active=1, created_at=_NOW, updated_at=_NOW,
        ))
        s.add(Goal(
            id=str(uuid.uuid4()), mandate_id=mandate.id, client_id=client.id,
            goal_family="Vermoegen", goal_type="Vermoegensziel",
            label="Hauskauf 2032", rank=1, weight_bps=5000,
            goal_scope="Beratungsvermögen", value_mode="real",
            target_wealth_rappen=800_000_00, frequency="einmalig",
            target_date="2032-06-01", is_ongoing=0, hardness="Primaer",
            is_active=1, created_at=_NOW, updated_at=_NOW,
        ))
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    ws = report["ausgangslage"]["wealth_summary"]
    assert len(ws["cashflows"]) == 1
    assert ws["cashflows"][0]["label"] == "Lohn"
    assert ws["cashflows"][0]["amount_rappen"] == 120_000_00
    assert len(ws["ziele"]) == 1
    assert ws["ziele"][0]["label"] == "Hauskauf 2032"
    assert ws["ziele"][0]["hardness"] == "Primaer"


def test_ausgangslage_key_metrics_all_none_without_target_allocation(session_factory):
    """Wenn das Mandat noch keine TargetAllocation hat, sollen alle 6
    Key-Metric-Karten None liefern (UI zeigt „—"), ohne zu crashen."""
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    km = report["ausgangslage"]["key_metrics"]
    assert km == {
        "risky_fraction_bps": None,
        "zielerreichung_bps": None,
        "exp_vol_bps": None,
        "exp_return_bps": None,
        "max_drawdown_bps": None,
        "var_95_bps": None,
    }


# ---------------------------------------------------------------------------
# Sektion 2: Disclaimer
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Helpers für Sektionen 4-6
# ---------------------------------------------------------------------------

def _make_optimizer_policy(s, advisor_id: str) -> OptimizerPolicy:
    pol = OptimizerPolicy(
        id=str(uuid.uuid4()),
        policy_name=f"pol-{uuid.uuid4().hex[:4]}",
        version=1, is_current=1,
        valid_from=_NOW, optimizer_engine="goal_based_v1",
        created_by=advisor_id, created_at=_NOW, updated_at=_NOW,
    )
    s.add(pol)
    s.flush()
    return pol


def _make_rec_run_with_position(
    s, *, mandate_id: str, client_id: str, advisor_id: str,
    target_amount_rappen: int,
    asset_class: str = "Aktien",
    sub_asset_class: str = "Aktien Schweiz",
    product_name: str = "Test-ETF",
    isin: str = "CH0000000001",
    currency: str = "CHF",
    ter_bps: int = 25,
) -> tuple[RecommendationRun, Product]:
    pol = _make_optimizer_policy(s, advisor_id)
    run = RecommendationRun(
        id=str(uuid.uuid4()),
        mandate_id=mandate_id, client_id=client_id,
        policy_id=pol.id, run_type="Standard", result_status="Draft",
        created_by=advisor_id, created_at=_NOW, updated_at=_NOW,
    )
    s.add(run)
    prod = Product(
        id=str(uuid.uuid4()), isin=isin, product_name=product_name,
        product_type="ETF", asset_class=asset_class,
        sub_asset_class=sub_asset_class, currency=currency,
        ter_bps=ter_bps, created_at=_NOW, updated_at=_NOW,
    )
    s.add(prod)
    s.flush()
    pos = RecommendationPosition(
        id=str(uuid.uuid4()), run_id=run.id, product_id=prod.id,
        target_weight_bps=10000,
        target_amount_rappen=target_amount_rappen,
        created_at=_NOW, updated_at=_NOW,
    )
    s.add(pos)
    s.flush()
    return run, prod


# ---------------------------------------------------------------------------
# Sektion 5: Positionen (SOLL aus RecommendationRun)
# ---------------------------------------------------------------------------

def test_positionen_returns_5_empty_groups_when_no_recommendation_run(session_factory):
    """Konsistente UI-Struktur: 5 Anlageklassen immer vorhanden, auch leer."""
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    pos = report["positionen"]
    assert pos["has_recommendation_run"] is False
    assert pos["total_rappen"] == 0
    assert len(pos["groups"]) == 5
    assert [g["key"] for g in pos["groups"]] == [
        "liquidity", "bonds", "equities", "real_estate", "alternatives"
    ]
    assert all(g["positions"] == [] for g in pos["groups"])
    assert "Empfehlung" in pos["hinweis"]


def test_positionen_aggregates_recommendation_positions_with_shares(session_factory):
    """RecommendationPositions werden korrekt nach Bucket gruppiert + Anteils-bps."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        _make_rec_run_with_position(
            s, mandate_id=mandate.id, client_id=client.id,
            advisor_id=advisor.id,
            target_amount_rappen=600_000_00,
            asset_class="Aktien", product_name="Aktien-ETF Global",
            isin="CH9999990001", currency="USD", ter_bps=18,
        )
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    pos = report["positionen"]
    assert pos["has_recommendation_run"] is True
    assert pos["total_rappen"] == 600_000_00
    eq_group = next(g for g in pos["groups"] if g["key"] == "equities")
    assert len(eq_group["positions"]) == 1
    assert eq_group["share_bps"] == 10000
    pos0 = eq_group["positions"][0]
    assert pos0["product_name"] == "Aktien-ETF Global"
    assert pos0["isin"] == "CH9999990001"
    assert pos0["currency"] == "USD"
    assert pos0["ter_bps"] == 18
    assert pos0["share_bps"] == 10000


# ---------------------------------------------------------------------------
# Sektion 6: Prüfpunkte (statisch)
# ---------------------------------------------------------------------------

def test_pruefpunkte_returns_10_blocks_with_stable_keys(session_factory):
    """Spec §5 verlangt 10 Blöcke mit stabilen Keys (UI/PDF referenzieren)."""
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    bloecke = report["pruefpunkte"]["bloecke"]
    assert len(bloecke) == 10
    expected_keys = {
        "diversifikation", "waehrungsrisiken", "konzentrationsrisiken",
        "branchenrisiken", "home_bias", "liquiditaetsquote",
        "strategische_aa", "gebuehrenstruktur", "zielkompatibilitaet",
        "risiko_passung",
    }
    assert {b["key"] for b in bloecke} == expected_keys
    # Branding-Disziplin: keine Dritt-Marken in den statischen Beschreibungen
    full = " ".join(b["beschreibung"] for b in bloecke).lower()
    for term in ("ubs", "pictet", "julius bär", "swiss life", "3eyes"):
        assert term not in full


# ---------------------------------------------------------------------------
# Sektion 7: Erkenntnisse (Ampel-Logik)
# ---------------------------------------------------------------------------

def test_erkenntnisse_yields_9_checks_with_required_fields(session_factory):
    """9 Prüfpunkte gemäss Spec §6, jede mit pruefpunkt/bewertung/
    beurteilung/handlungsempfehlung."""
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    checks = report["erkenntnisse"]["checks"]
    assert len(checks) == 9
    for c in checks:
        assert set(c.keys()) == {
            "pruefpunkt", "bewertung", "beurteilung", "handlungsempfehlung"
        }
        assert c["bewertung"] in (
            "gruen", "gelb", "rot", "nicht_beurteilbar"
        )


def test_erkenntnisse_risikoprofil_rot_without_assessment(session_factory):
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    risk_check = next(
        c for c in report["erkenntnisse"]["checks"]
        if c["pruefpunkt"] == "Risikoprofil"
    )
    assert risk_check["bewertung"] == "rot"
    assert "kein Risikoprofil" in risk_check["beurteilung"]


def test_erkenntnisse_risikoprofil_gruen_with_recent_assessment(session_factory):
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.add(RiskAssessment(
            id=str(uuid.uuid4()), mandate_id=mandate.id,
            version=1, is_current=1, valid_from=_NOW,
            q_income_points=3, q_obligations_points=3,
            q_savings_points=3, q_wealth_points=3,
            risk_capacity_total=12,
            risk_capacity_profile="Wachstumsorientiert",
            investment_horizon_years=15,
            investment_horizon_label="Langfristig",
            risk_capacity_score_x10=80,
            q_investment_goal_points=3,
            q_risk_preference_points=3,
            q_risk_behavior_points=3,
            risk_willingness_total=9,
            risk_willingness_profile="Ausgewogen",
            risk_willingness_score_x10=60,
            final_score_x10=70,
            final_profile="Ausgewogen",
            assessed_at=_NOW, assessed_by=advisor.id,
            created_at=_NOW, updated_at=_NOW,
        ))
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    risk_check = next(
        c for c in report["erkenntnisse"]["checks"]
        if c["pruefpunkt"] == "Risikoprofil"
    )
    assert risk_check["bewertung"] == "gruen"


def test_erkenntnisse_zielkompatibilitaet_nicht_beurteilbar_without_ta(session_factory):
    """Ohne TargetAllocation kann Zielkompatibilität nicht bewertet werden."""
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    ziel_check = next(
        c for c in report["erkenntnisse"]["checks"]
        if c["pruefpunkt"] == "Zielkompatibilität"
    )
    assert ziel_check["bewertung"] == "nicht_beurteilbar"
    assert "Anlagestrategie" in ziel_check["handlungsempfehlung"]


# ---------------------------------------------------------------------------
# Sektion 8: Asset Allocation
# ---------------------------------------------------------------------------

def test_asset_allocation_returns_5_buckets_in_stable_order(session_factory):
    """Reihenfolge gemäss Spec §7: Liquidität→Obligationen→Aktien→Immobilien→
    Alternative Anlagen. Auch ohne Daten muss UI konsistent rendern."""
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    aa = report["asset_allocation"]
    labels = [it["label"] for it in aa["items"]]
    assert labels == [
        "Liquidität", "Obligationen", "Aktien",
        "Immobilien", "Alternative Anlagen",
    ]
    # Ohne Daten: alle Werte 0, Default-Anmerkung neutral
    assert all(it["ist_bps"] == 0 for it in aa["items"])
    assert all(it["soll_bps"] == 0 for it in aa["items"])
    assert "Toleranzbänder" in aa["anmerkungen"] or "Toleranzband" in aa["anmerkungen"]


def test_asset_allocation_carries_drift_and_band_info(session_factory):
    """Wenn TA + Positionen vorhanden: ist_bps/soll_bps/drift_bps/
    band_min_bps/band_max_bps/in_band sind alle gesetzt."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        _make_rec_run_with_position(
            s, mandate_id=mandate.id, client_id=client.id,
            advisor_id=advisor.id,
            target_amount_rappen=1_000_000_00,
            asset_class="Aktien",
        )
        # TargetAllocation pflegen (für Bucket-Band-Info)
        pol2 = OptimizerPolicy(
            id=str(uuid.uuid4()),
            policy_name=f"pol2-{uuid.uuid4().hex[:4]}",
            version=1, is_current=1, valid_from=_NOW,
            optimizer_engine="goal_based_v1",
            created_by=advisor.id, created_at=_NOW, updated_at=_NOW,
        )
        s.add(pol2)
        s.flush()
        s.add(TargetAllocation(
            id=str(uuid.uuid4()), mandate_id=mandate.id,
            version=1, is_current=1,
            target_equities_bps=6000, target_bonds_bps=2500,
            target_real_estate_bps=500, target_alternatives_bps=500,
            target_liquidity_bps=500,
            band_equities_min_bps=5500, band_equities_max_bps=6500,
            band_bonds_min_bps=2000, band_bonds_max_bps=3000,
            band_real_estate_min_bps=0, band_real_estate_max_bps=1000,
            band_alternatives_min_bps=0, band_alternatives_max_bps=1000,
            band_liquidity_min_bps=0, band_liquidity_max_bps=1000,
            policy_id=pol2.id, set_by=advisor.id, set_at=_NOW,
            created_at=_NOW, updated_at=_NOW,
        ))
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    aa = report["asset_allocation"]
    eq = next(it for it in aa["items"] if it["label"] == "Aktien")
    assert eq["soll_bps"] == 6000
    # IST = 100% Aktien (1 Position) — drift kommt aus depot_check
    assert eq["ist_bps"] > 0
    assert eq["drift_bps"] == eq["ist_bps"] - eq["soll_bps"]
    assert eq["band_min_bps"] == 5500
    assert eq["band_max_bps"] == 6500


# ---------------------------------------------------------------------------
# Sektion 9: Risikowährungen
# ---------------------------------------------------------------------------

def test_risikowaehrungen_returns_7_buckets_in_stable_order(session_factory):
    """7 Kategorien: CHF/USD/EUR/GBP/JPY/EM FX/Andere."""
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    fx = report["risikowaehrungen"]
    labels = [it["label"] for it in fx["items"]]
    assert labels == ["CHF", "USD", "EUR", "GBP", "JPY", "EM FX", "Andere"]


def test_risikowaehrungen_em_fx_buckets_emerging_market_currencies(session_factory):
    """Schwellenländer-Codes (BRL, INR, CNY, ...) landen im 'EM FX'-Bucket,
    nicht in 'Andere'."""
    from services.advisory_report import _aggregate_fx_into_display_buckets
    raw = {
        "CHF": 4000, "USD": 3000, "EUR": 1000,
        "BRL": 500, "INR": 300, "CNY": 700,
        "AUD": 500,  # AUD = Andere (nicht EM)
    }
    out = _aggregate_fx_into_display_buckets(raw)
    assert out["CHF"] == 4000
    assert out["USD"] == 3000
    assert out["EUR"] == 1000
    assert out["EM FX"] == 1500  # 500+300+700
    assert out["Andere"] == 500  # AUD


# ---------------------------------------------------------------------------
# Sektion 10: Branchen (GICS)
# ---------------------------------------------------------------------------

def test_branchen_returns_11_gics_sectors_in_stable_order(session_factory):
    """11 GICS-Sektoren in stabiler Reihenfolge (IT zuerst, dann Financials...).
    Nicht-GICS-Sektoren landen in 'Übrige' nur wenn > 0."""
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    br = report["branchen"]
    labels = [it["label"] for it in br["items"]]
    # Mind. 11 GICS-Sektoren, in stabiler Reihenfolge
    assert labels[0] == "Information Technology"
    assert labels[1] == "Financials"
    assert "Real Estate" in labels
    # Ohne Daten: keine "Übrige"-Kategorie (suppressed wenn 0)
    assert "Übrige" not in labels


def _make_ta_with_goals(
    s, *, mandate_id: str, advisor_id: str,
    goal_achievability_json: str | None = None,
    risky_fraction_bps: int = 6000,
    risk_budget_bps: int = 8000,
) -> TargetAllocation:
    pol = _make_optimizer_policy(s, advisor_id)
    ta = TargetAllocation(
        id=str(uuid.uuid4()), mandate_id=mandate_id,
        version=1, is_current=1,
        target_equities_bps=5500, target_bonds_bps=2500,
        target_real_estate_bps=1000, target_alternatives_bps=500,
        target_liquidity_bps=500,
        band_equities_min_bps=5000, band_equities_max_bps=6000,
        band_bonds_min_bps=2000, band_bonds_max_bps=3000,
        band_real_estate_min_bps=500, band_real_estate_max_bps=1500,
        band_alternatives_min_bps=0, band_alternatives_max_bps=1000,
        band_liquidity_min_bps=0, band_liquidity_max_bps=1000,
        risky_fraction_bps=risky_fraction_bps,
        risk_budget_bps_at_generation=risk_budget_bps,
        goal_achievability_json=goal_achievability_json,
        policy_id=pol.id, set_by=advisor_id, set_at=_NOW,
        created_at=_NOW, updated_at=_NOW,
    )
    s.add(ta)
    s.flush()
    return ta


# ---------------------------------------------------------------------------
# Sektion 11: Goal-Based Investing
# ---------------------------------------------------------------------------

def test_goal_based_investing_empty_without_ta(session_factory):
    """Ohne TA: leere Goal-Liste, achievement_score=0, MC-Paths-Flag gesetzt."""
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    gbi = report["goal_based_investing"]
    assert gbi["goals"] == []
    assert gbi["goal_achievement_score_bps"] == 0
    assert gbi["monte_carlo_paths"]["data_pending"] is True


def test_goal_based_investing_aggregates_persisted_achievability(session_factory):
    """Bei vorhandener TA mit goal_achievability_json wird die Liste
    geparst und ein gewichteter Achievement-Score berechnet."""
    import json
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        goal_id_1 = str(uuid.uuid4())
        s.add(Goal(
            id=goal_id_1, mandate_id=mandate.id, client_id=client.id,
            goal_family="Vermoegen", goal_type="Vermoegensziel",
            label="Hauskauf", rank=1, weight_bps=6000,
            goal_scope="Beratungsvermögen", value_mode="real",
            target_wealth_rappen=500_000_00, frequency="einmalig",
            target_date="2032-06-01", is_ongoing=0, hardness="Hart",
            is_active=1, created_at=_NOW, updated_at=_NOW,
        ))
        json_payload = json.dumps([
            {"goal_id": goal_id_1, "label": "Hauskauf",
             "probability": 0.85, "status": "erreichbar", "hardness": "Hart"},
        ])
        _make_ta_with_goals(
            s, mandate_id=mandate.id, advisor_id=advisor.id,
            goal_achievability_json=json_payload,
        )
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    gbi = report["goal_based_investing"]
    assert len(gbi["goals"]) == 1
    g0 = gbi["goals"][0]
    assert g0["label"] == "Hauskauf"
    assert g0["probability_bps"] == 8500
    assert g0["status"] == "erreichbar"
    assert g0["target_amount_rappen"] == 500_000_00
    # Single-Goal Score = Goal-Probability
    assert gbi["goal_achievement_score_bps"] == 8500


# ---------------------------------------------------------------------------
# Sektion 12: Risikoprofilierung
# ---------------------------------------------------------------------------

def test_risikoprofilierung_returns_defaults_without_assessment(session_factory):
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    rp = report["risikoprofilierung"]
    assert rp["final_profile"] == "—"
    assert rp["final_score_x10"] is None
    assert rp["is_overridden"] is False
    assert len(rp["questions"]) == 8  # 7 Spec + Marktverlust-Frage


def test_risikoprofilierung_with_assessment_returns_real_scores(session_factory):
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.add(RiskAssessment(
            id=str(uuid.uuid4()), mandate_id=mandate.id,
            version=1, is_current=1, valid_from=_NOW,
            q_income_points=3, q_obligations_points=2,
            q_savings_points=3, q_wealth_points=4,
            risk_capacity_total=12,
            risk_capacity_profile="Wachstumsorientiert",
            investment_horizon_years=15,
            investment_horizon_label="Langfristig",
            risk_capacity_score_x10=80,
            q_investment_goal_points=4,
            q_risk_preference_points=3,
            q_risk_behavior_points=2,
            risk_willingness_total=9,
            risk_willingness_profile="Ausgewogen",
            risk_willingness_score_x10=60,
            final_score_x10=70,
            final_profile="Wachstumsorientiert",
            assessed_at=_NOW, assessed_by=advisor.id,
            created_at=_NOW, updated_at=_NOW,
        ))
        _make_ta_with_goals(
            s, mandate_id=mandate.id, advisor_id=advisor.id,
            risky_fraction_bps=7500,
        )
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    rp = report["risikoprofilierung"]
    assert rp["risk_capacity_score_x10"] == 80
    assert rp["risk_willingness_score_x10"] == 60
    assert rp["final_score_x10"] == 70
    assert rp["final_profile"] == "Wachstumsorientiert"
    assert rp["risky_fraction_bps"] == 7500
    # Default-Fragen mit echten Punkten
    income_q = next(q for q in rp["questions"] if q["key"] == "einkommen")
    assert income_q["points"] == 3


# ---------------------------------------------------------------------------
# Sektion 13: Building Blocks / iSAA
# ---------------------------------------------------------------------------

def test_building_blocks_returns_5_blocks_zero_without_ta(session_factory):
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    bb = report["building_blocks"]
    assert len(bb["blocks"]) == 5
    assert all(b["target_bps"] == 0 for b in bb["blocks"])
    assert bb["constraints"] == []
    assert "iSAA" in bb["methodologie"] or "Strategic-Asset-Allocation" in bb["methodologie"]


def test_building_blocks_reads_target_bps_from_ta(session_factory):
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        _make_ta_with_goals(
            s, mandate_id=mandate.id, advisor_id=advisor.id,
            risk_budget_bps=8500,
        )
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    bb = report["building_blocks"]
    eq = next(b for b in bb["blocks"] if b["key"] == "equities")
    assert eq["target_bps"] == 5500
    assert eq["band_min_bps"] == 5000
    assert eq["band_max_bps"] == 6000
    # Risk-Budget-Constraint kommt mit
    risk_constraint = next(
        c for c in bb["constraints"] if c["key"] == "max_risky_fraction"
    )
    assert risk_constraint["value_bps"] == 8500


# ---------------------------------------------------------------------------
# Sektion 14: Statement aus dem Portfoliomanagement
# ---------------------------------------------------------------------------

def test_statement_pm_returns_7_principles_with_stable_keys(session_factory):
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    principles = report["statement_pm"]["principles"]
    assert len(principles) == 7
    keys = {p["key"] for p in principles}
    assert keys == {
        "langfristigkeit", "diversifikation", "disziplin", "markt_timing",
        "waehrungsabsicherung", "effiziente_maerkte", "verhaltensfehler",
    }
    # Branding-Compliance: keine Dritt-Marken, keine Renditeversprechen
    full = " ".join(p["body"] for p in principles).lower()
    for term in ("ubs", "pictet", "swiss life", "3eyes", "garantiert", "garantie"):
        assert term not in full


# ---------------------------------------------------------------------------
# Sektion 15: Weiteres Vorgehen
# ---------------------------------------------------------------------------

def test_weiteres_vorgehen_returns_placeholders(session_factory):
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    wv = report["weiteres_vorgehen"]
    assert "Berater" in wv["block_optimierungen"]
    assert "Berater" in wv["block_zielstrategie"]
    assert wv["offene_fragen"] == []
    assert wv["naechster_termin"] is None
    assert wv["todos"] == []
    assert wv["dokumente"] == []


# ---------------------------------------------------------------------------
# Endpoint-Smoketest
# ---------------------------------------------------------------------------

def test_endpoint_returns_full_report_structure(session_factory):
    """GET /mandates/{id}/advisory-report liefert das volle 15-Sektionen-JSON."""
    from types import SimpleNamespace
    from fastapi.testclient import TestClient

    from database import get_db
    from main import app
    from services.auth import get_current_user

    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        mid = mandate.id
        advisor_id = advisor.id

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    current = SimpleNamespace(
        id=advisor_id, full_name="Test Advisor",
        email="adv@test.local", role="advisor",
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current
    try:
        with TestClient(app) as client:
            response = client.get(f"/mandates/{mid}/advisory-report")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    expected = [
        "schema_version", "mandate_id", "generated_at",
        "cover", "disclaimer", "inhaltsverzeichnis", "ausgangslage",
        "positionen", "pruefpunkte", "erkenntnisse",
        "asset_allocation", "risikowaehrungen", "branchen",
        "goal_based_investing", "risikoprofilierung", "building_blocks",
        "statement_pm", "weiteres_vorgehen",
    ]
    assert list(data.keys()) == expected
    assert data["schema_version"] == 2
    assert data["mandate_id"] == mid


# ---------------------------------------------------------------------------
# Sektion 2: Disclaimer (bleibt unverändert)
# ---------------------------------------------------------------------------

def test_disclaimer_contains_finma_required_clauses(session_factory):
    """FINMA-Disclaimer muss alle Pflichthinweise enthalten:
    - keine Anlageempfehlung
    - keine Garantie
    - vergangene Performance ≠ Zukunft
    - Modell-Risiken (Monte-Carlo)
    - keine Steuer-/Rechtsberatung
    - keine automatische Umsetzung
    - Vertraulichkeit
    """
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    hinweise = report["disclaimer"]["hinweise"]
    full_text = " ".join(hinweise).lower()
    # Pflicht-Phrasen prüfen
    assert "keine anlageempfehlung" in full_text
    assert "keine garantie" in full_text
    assert "vergangene performance" in full_text
    assert "monte-carlo" in full_text
    assert "modell-risiken" in full_text or "modell-risiko" in full_text
    assert "steuer" in full_text and "rechts" in full_text
    assert "vertraulich" in full_text
    assert "keine automatische transaktion" in full_text
    # FINMA-Branding-Compliance: KEINE Dritt-Marken im Disclaimer
    forbidden = ["ubs", "pictet", "julius bär", "ppc metrics", "swiss life", "3eyes"]
    for term in forbidden:
        assert term not in full_text, f"Verbotene Marke '{term}' im Disclaimer"
