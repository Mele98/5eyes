"""Tests für services/advisory_report.py — Advisory-Report-Aggregator.

Deckt die stabile 15-Seiten-Struktur ab:
- Sektion 1: Cover
- Sektion 2: Disclaimer
- Sektion 3: Inhaltsverzeichnis
- Sektion 4: Ausgangslage (Kundeninformation, Wealth-Summary, Key Metrics)
- Sektionen 5-15: Positionen bis Weiteres Vorgehen
"""
from __future__ import annotations

import json
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
        # U-FINMA-2.2: additive Sektion 16
        "beratungsprotokoll",
        # U-70: additive Sektion 17
        "stress_replay",
        # U-68: additive Sektion 18
        "conflict_disclosures",
        # U-66: additive Sektion 19
        "suitability_compliance",
        # U-73+U-74: additive Sektion 20
        "methodology_models",
        # U-69: additive Sektion 21
        "recommendation_methodology",
        # U-22: additive Sektion 22
        "mandate_lock_status",
        # U-21: additive Sektion 23
        "liquidity_cascade",
        # U-94: additive Sektion 24
        "optimizer_run_history",
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
    assert cover["title"] == "Strategische Portfolioanalyse"
    assert cover["subtitle"] == "Persoenlicher Advisory-Report"
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

def test_inhaltsverzeichnis_has_expected_chapters(session_factory):
    """Spec listet die sichtbaren Kapitel. Reihenfolge + Nummerierung muss stabil sein
    weil Frontend + PDF darauf referenzieren."""
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    kapitel = report["inhaltsverzeichnis"]["kapitel"]
    assert len(kapitel) == 15
    assert [k["nr"] for k in kapitel] == list(range(1, 16))
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
        "Beratungsprotokoll",
        "Historische Stress-Szenarien",
        "Compliance-Audit",
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
    current_amount_rappen: int | None = None,
    sector_exposure_json: str | None = None,
    run: RecommendationRun | None = None,
) -> tuple[RecommendationRun, Product]:
    if run is None:
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
        ter_bps=ter_bps, sector_exposure_json=sector_exposure_json,
        created_at=_NOW, updated_at=_NOW,
    )
    s.add(prod)
    s.flush()
    pos = RecommendationPosition(
        id=str(uuid.uuid4()), run_id=run.id, product_id=prod.id,
        target_weight_bps=10000,
        target_amount_rappen=target_amount_rappen,
        current_amount_rappen=current_amount_rappen,
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

def test_erkenntnisse_yields_10_checks_with_required_fields(session_factory):
    """10 Prüfpunkte gemäss Spec §6 (Stand U-98 2026-06-05: +Waehrungsabsicherung),
    jede mit pruefpunkt/bewertung/beurteilung/handlungsempfehlung."""
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    checks = report["erkenntnisse"]["checks"]
    assert len(checks) == 10
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


def test_ist_basiert_auf_soll_flag_when_current_amounts_missing(session_factory):
    """Wenn alle current_amount_rappen fehlen, markiert der Report den
    Datenstand als SOLL-basiert in allen Drift-Sektionen."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        _make_rec_run_with_position(
            s, mandate_id=mandate.id, client_id=client.id,
            advisor_id=advisor.id,
            target_amount_rappen=1_000_000_00,
            current_amount_rappen=None,
        )
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    assert report["asset_allocation"]["ist_basiert_auf_soll"] is True
    assert report["risikowaehrungen"]["ist_basiert_auf_soll"] is True
    assert report["branchen"]["ist_basiert_auf_soll"] is True


def test_ist_basiert_auf_soll_false_when_current_amount_exists(session_factory):
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        _make_rec_run_with_position(
            s, mandate_id=mandate.id, client_id=client.id,
            advisor_id=advisor.id,
            target_amount_rappen=1_000_000_00,
            current_amount_rappen=900_000_00,
        )
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    assert report["asset_allocation"]["ist_basiert_auf_soll"] is False
    assert report["risikowaehrungen"]["ist_basiert_auf_soll"] is False
    assert report["branchen"]["ist_basiert_auf_soll"] is False


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


def test_branchen_only_aggregates_equity_positions(session_factory):
    """Bond-/Cash-/Immobilien-Positionen dürfen die GICS-Sektorverteilung
    nicht mehr als 'Übrige' verwässern."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        run, _eq = _make_rec_run_with_position(
            s, mandate_id=mandate.id, client_id=client.id,
            advisor_id=advisor.id,
            asset_class="Aktien",
            target_amount_rappen=1_000_000_00,
            current_amount_rappen=1_000_000_00,
            sector_exposure_json=json.dumps({"Information Technology": 10000}),
        )
        _make_rec_run_with_position(
            s, mandate_id=mandate.id, client_id=client.id,
            advisor_id=advisor.id,
            asset_class="Obligationen",
            product_name="Bond Fund",
            isin="CH0000000002",
            target_amount_rappen=9_000_000_00,
            current_amount_rappen=9_000_000_00,
            sector_exposure_json=json.dumps({"Financials": 10000}),
            run=run,
        )
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)

    br = report["branchen"]
    it = next(item for item in br["items"] if item["label"] == "Information Technology")
    financials = next(item for item in br["items"] if item["label"] == "Financials")
    assert br["anteil_aktien_bps"] == 1000
    assert "10.0%" in br["hinweis"]
    assert it["ist_bps"] == 10000
    assert financials["ist_bps"] == 0
    assert "Übrige" not in [item["label"] for item in br["items"]]


def test_branchen_returns_zero_when_no_equity(session_factory):
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        _make_rec_run_with_position(
            s, mandate_id=mandate.id, client_id=client.id,
            advisor_id=advisor.id,
            asset_class="Obligationen",
            target_amount_rappen=1_000_000_00,
            current_amount_rappen=1_000_000_00,
            sector_exposure_json=json.dumps({"Financials": 10000}),
        )
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)

    br = report["branchen"]
    assert br["anteil_aktien_bps"] == 0
    assert all(item["ist_bps"] == 0 for item in br["items"])
    assert "keine Aktien-Positionen" in br["hinweis"]


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


def test_stress_replay_pending_without_target_allocation(session_factory):
    """Ohne aktuelle TA bleibt die neue Report-Sektion fail-soft."""
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)

    sr = report["stress_replay"]
    assert sr["data_pending"] is True
    assert sr["scenarios"] == []
    assert "Target-Allocation" in sr["note"]


def test_stress_replay_returns_foundation_scenarios_from_current_ta(session_factory):
    """Mit aktueller TA liefert der Aggregator die 5 U-P13 Stress-Szenarien."""
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        _make_ta_with_goals(s, mandate_id=mandate.id, advisor_id=advisor.id)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)

    sr = report["stress_replay"]
    assert sr["data_pending"] is False
    assert sr["weights_bps"]["equities"] == 5500
    assert len(sr["scenarios"]) == 5
    assert any("Dotcom" in scenario["label"] for scenario in sr["scenarios"])
    first = sr["scenarios"][0]
    assert {
        "id", "label", "period", "cumulative_return_bps",
        "max_drawdown_bps", "recovery_months", "annual_breakdown",
    } <= set(first)


def test_stress_replay_fail_soft_when_service_raises(session_factory, monkeypatch):
    """Ein Stress-Service-Fehler darf den Advisory-Report nicht abbrechen."""
    from services import backtest_stress

    def _boom(db, mandate):
        raise RuntimeError("boom")

    monkeypatch.setattr(backtest_stress, "compute_stress_replays", _boom)
    with session_factory() as s:
        mandate, _c, advisor = _seed_minimal_mandate(s)
        _make_ta_with_goals(s, mandate_id=mandate.id, advisor_id=advisor.id)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)

    sr = report["stress_replay"]
    assert sr["data_pending"] is True
    assert sr["scenarios"] == []
    assert "boom" in sr["note"]


def test_goal_based_investing_returns_data_pending_goals_without_achievability(session_factory):
    """Wenn Goals existieren, aber noch keine stochastic Achievability
    persistiert ist, darf die UI nicht fälschlich 0 Goals sehen."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        goal_id = str(uuid.uuid4())
        s.add(Goal(
            id=goal_id, mandate_id=mandate.id, client_id=client.id,
            goal_family="Vermoegen", goal_type="Vermoegensziel",
            label="Pension", rank=1, weight_bps=5000,
            goal_scope="Beratungsvermögen", value_mode="real",
            target_wealth_rappen=1_200_000_00, frequency="einmalig",
            target_date="2035-12-31", is_ongoing=0, hardness="Hart",
            is_active=1, created_at=_NOW, updated_at=_NOW,
        ))
        _make_ta_with_goals(
            s, mandate_id=mandate.id, advisor_id=advisor.id,
            goal_achievability_json=None,
        )
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)

    gbi = report["goal_based_investing"]
    assert len(gbi["goals"]) == 1
    assert gbi["goals"][0]["label"] == "Pension"
    assert gbi["goals"][0]["probability_bps"] is None
    assert gbi["goals"][0]["status"] == "data_pending"
    assert gbi["goal_achievement_score_bps"] == 0


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
        # U-FINMA-2.2: additive Sektion 16
        "beratungsprotokoll",
        # U-70: additive Sektion 17
        "stress_replay",
        # U-68: additive Sektion 18
        "conflict_disclosures",
        # U-66: additive Sektion 19
        "suitability_compliance",
        # U-73+U-74: additive Sektion 20
        "methodology_models",
        # U-69: additive Sektion 21
        "recommendation_methodology",
        # U-22: additive Sektion 22
        "mandate_lock_status",
        # U-21: additive Sektion 23
        "liquidity_cascade",
        # U-94: additive Sektion 24
        "optimizer_run_history",
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


# ---------------------------------------------------------------------------
# Sprint U-P30: Ausgangslage-Felder aus existierenden Daten ableiten
# ---------------------------------------------------------------------------

def test_ausgangslage_derives_age_from_date_of_birth(session_factory):
    """`client.date_of_birth` (ISO YYYY-MM-DD) → erwartetes Alter."""
    from datetime import date

    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        # 1976-09-18 → erwartetes Alter abhängig vom heutigen Datum
        client.date_of_birth = "1976-09-18"
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    age = report["ausgangslage"]["client_info"]["alter"]
    today = date.today()
    birth = date(1976, 9, 18)
    expected = today.year - birth.year - (
        (today.month, today.day) < (birth.month, birth.day)
    )
    assert age == expected
    assert age >= 49  # sanity-check: in 2026 sind das 49 oder 50


def test_ausgangslage_returns_zero_when_dob_missing_or_invalid(session_factory):
    """Robust gegen leeres / kaputtes Format → 0."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        client.date_of_birth = None
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    assert report["ausgangslage"]["client_info"]["alter"] == 0

    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        client.date_of_birth = "not-a-date"
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    assert report["ausgangslage"]["client_info"]["alter"] == 0


def test_ausgangslage_derives_horizon_from_retirement_year(session_factory):
    """`mandate.retirement_year` minus aktuelles Jahr → Horizont."""
    from datetime import date

    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        mandate.retirement_year = date.today().year + 15
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    assert report["ausgangslage"]["client_info"]["anlagehorizont_jahre"] == 15


def test_ausgangslage_horizon_falls_back_to_life_expectancy(session_factory):
    """Ohne `retirement_year` → `life_expectancy_year` greift."""
    from datetime import date

    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        mandate.retirement_year = None
        mandate.life_expectancy_year = date.today().year + 30
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    assert report["ausgangslage"]["client_info"]["anlagehorizont_jahre"] == 30


def test_ausgangslage_horizon_default_is_10_years(session_factory):
    """Ohne `retirement_year` und ohne `life_expectancy_year` → konservativ 10."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        mandate.retirement_year = None
        mandate.life_expectancy_year = None
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    assert report["ausgangslage"]["client_info"]["anlagehorizont_jahre"] == 10


def test_ausgangslage_horizon_derives_from_planning_assumption(session_factory):
    """Regression nach Live-Smoke 2026-05-28: Foundation-Mandat seedet
    `PlanningAssumption.retirement_age_primary=63`, aber NICHT
    `mandate.retirement_year`. Ohne PlanningAssumption-Fallback griff
    der Default 10. Daniel 49 + Pension 63 → Horizont muss 14 sein.
    """
    from datetime import date

    from models.wealth import PlanningAssumption

    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        mandate.retirement_year = None
        mandate.life_expectancy_year = None
        # Kunde 49 Jahre alt (geboren in einem Jahr das current_year - 49 ist)
        today_year = date.today().year
        birth_year = today_year - 49
        client.date_of_birth = f"{birth_year}-09-18"
        s.add(
            PlanningAssumption(
                id=str(uuid.uuid4()),
                mandate_id=mandate.id,
                client_id=client.id,
                version=1,
                is_current=1,
                valid_from=_NOW[:10],
                retirement_age_primary=63,
                retirement_age_partner=64,
                life_expectancy_primary=92,
                life_expectancy_partner=94,
                inflation_assumption_bps=150,
                pension_indexation_bps=100,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    # Pension bei 63, Kunde 49 → Horizont 14 Jahre
    horizon = report["ausgangslage"]["client_info"]["anlagehorizont_jahre"]
    assert horizon == 14, (
        f"Erwartet 14 Jahre (Pension 63 - Alter 49), gefunden {horizon}"
    )


def test_ausgangslage_horizon_planning_assumption_ignored_without_dob(session_factory):
    """Edge-Case: PlanningAssumption ohne Geburtsdatum → kein Ableitungspfad,
    fällt auf Default zurück."""
    from models.wealth import PlanningAssumption

    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        mandate.retirement_year = None
        mandate.life_expectancy_year = None
        client.date_of_birth = None
        s.add(
            PlanningAssumption(
                id=str(uuid.uuid4()),
                mandate_id=mandate.id,
                client_id=client.id,
                version=1,
                is_current=1,
                valid_from=_NOW[:10],
                retirement_age_primary=63,
                retirement_age_partner=64,
                life_expectancy_primary=92,
                life_expectancy_partner=94,
                inflation_assumption_bps=150,
                pension_indexation_bps=100,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    assert report["ausgangslage"]["client_info"]["anlagehorizont_jahre"] == 10


def test_ausgangslage_derives_primary_goal_label_from_lowest_rank(session_factory):
    """Wichtigstes Goal = niedrigster `rank`."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        s.add_all([
            Goal(
                id=str(uuid.uuid4()),
                mandate_id=mandate.id,
                client_id=client.id,
                goal_family="Vermögen",
                goal_type="Pension",
                label="Frühpension mit 60",
                rank=1,
                is_active=1,
                created_at=_NOW,
                updated_at=_NOW,
            ),
            Goal(
                id=str(uuid.uuid4()),
                mandate_id=mandate.id,
                client_id=client.id,
                goal_family="Liquidität",
                goal_type="Sparziel",
                label="Haus-Umbau in 5 J",
                rank=2,
                is_active=1,
                created_at=_NOW,
                updated_at=_NOW,
            ),
        ])
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    assert (
        report["ausgangslage"]["client_info"]["anlageziel"]
        == "Frühpension mit 60"
    )


def test_ausgangslage_primary_goal_falls_back_to_dash_when_no_goals(session_factory):
    """Ohne Goals → '—'."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    assert report["ausgangslage"]["client_info"]["anlageziel"] == "—"


def test_ausgangslage_derives_liquidity_need_from_expense_cashflows(session_factory):
    """6 Monate Ausgaben → liquiditaetsbedarf_rappen."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        s.add_all([
            Cashflow(
                id=str(uuid.uuid4()),
                client_id=client.id,
                cashflow_type="Expense",
                label="Lebenshaltung",
                amount_rappen=10_000_00,   # CHF 10'000 monatlich
                frequency="monatlich",
                is_active=1,
                created_at=_NOW,
                updated_at=_NOW,
            ),
            Cashflow(
                id=str(uuid.uuid4()),
                client_id=client.id,
                cashflow_type="Expense",
                label="Krankenkasse-Sondervorlage",
                amount_rappen=12_000_00,   # CHF 12'000 jährlich
                frequency="jährlich",
                is_active=1,
                created_at=_NOW,
                updated_at=_NOW,
            ),
            # Income wird ignoriert:
            Cashflow(
                id=str(uuid.uuid4()),
                client_id=client.id,
                cashflow_type="Income",
                label="Salär",
                amount_rappen=15_000_00,
                frequency="monatlich",
                is_active=1,
                created_at=_NOW,
                updated_at=_NOW,
            ),
        ])
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    # Jahresausgaben = 10000*12 + 12000 = 132'000 CHF = 13'200'000 Rappen
    # 6 Monate = 6'600'000 Rappen
    assert (
        report["ausgangslage"]["client_info"]["liquiditaetsbedarf_rappen"]
        == 6_600_000
    )


def test_ausgangslage_liquidity_need_is_zero_when_no_cashflows(session_factory):
    """Ohne Cashflows → 0 (Frontend zeigt 'noch nicht erfasst')."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    assert report["ausgangslage"]["client_info"]["liquiditaetsbedarf_rappen"] == 0


# ---------------------------------------------------------------------------
# Sprint U-P28 PR B: MandateReportNotes-Aggregator-Integration
# ---------------------------------------------------------------------------

def _seed_report_notes(s, mandate_id: str, advisor_id: str, **fields):
    """Helper: legt eine MandateReportNotes-Zeile mit beliebigen Feldern an."""
    from models.review import MandateReportNotes

    notes = MandateReportNotes(
        id=str(uuid.uuid4()),
        mandate_id=mandate_id,
        last_edited_by=advisor_id,
        last_edited_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
        **fields,
    )
    s.add(notes)
    return notes


def test_override_aa_anmerkungen_replaces_auto_text(session_factory):
    """`aa_anmerkungen` aus Notes überschreibt den Auto-Drift-Text."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        _seed_report_notes(
            s, mandate.id, advisor.id,
            aa_anmerkungen="Berater-Text: SAA stabil, kein Handlungsbedarf.",
        )
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    assert (
        report["asset_allocation"]["anmerkungen"]
        == "Berater-Text: SAA stabil, kein Handlungsbedarf."
    )


def test_no_notes_row_keeps_auto_defaults_unchanged(session_factory):
    """Kein Notes-Eintrag → Aggregator verhält sich wie vor U-P28
    (Backwards-Compat-Garantie)."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    # Auto-Defaults sind nicht-leere Strings + leere Listen
    aa = report["asset_allocation"]
    wae = report["risikowaehrungen"]
    br = report["branchen"]
    wv = report["weiteres_vorgehen"]

    assert isinstance(aa["anmerkungen"], str) and aa["anmerkungen"]
    assert isinstance(wae["erklaerung"], str) and wae["erklaerung"]
    assert isinstance(br["analyse"], str) and br["analyse"]
    assert wv["block_optimierungen"].startswith("(Vom Berater zu ergänzen")
    assert wv["block_zielstrategie"].startswith("(Vom Berater zu ergänzen")
    assert wv["offene_fragen"] == []
    assert wv["todos"] == []
    assert wv["dokumente"] == []
    assert wv["naechster_termin"] is None


def test_empty_or_whitespace_override_falls_back_to_auto_default(session_factory):
    """Leere oder Nur-Whitespace-Overrides triggern den Default — der
    Berater soll mit '' explizit löschen können, ohne dass leere Strings
    den Auto-Text verschlucken."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        _seed_report_notes(
            s, mandate.id, advisor.id,
            aa_anmerkungen="",
            waehrungen_erklaerung="   ",
            branchen_analyse=None,
            vorgehen_block_optimierungen="",
            vorgehen_block_zielstrategie="\n  ",
        )
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    # Alle 4 müssen den Auto-Default zeigen (= nicht-leer, nicht-whitespace)
    assert report["asset_allocation"]["anmerkungen"].strip()
    assert report["risikowaehrungen"]["erklaerung"].strip()
    assert report["branchen"]["analyse"].strip()
    assert (
        report["weiteres_vorgehen"]["block_optimierungen"]
        .startswith("(Vom Berater zu ergänzen")
    )
    assert (
        report["weiteres_vorgehen"]["block_zielstrategie"]
        .startswith("(Vom Berater zu ergänzen")
    )


def test_weiteres_vorgehen_json_lists_and_termin_are_mapped(session_factory):
    """Die 3 JSON-Listen-Felder + naechster_termin werden korrekt
    materialisiert. Kaputtes JSON darf nicht crashen."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        _seed_report_notes(
            s, mandate.id, advisor.id,
            vorgehen_offene_fragen_json=json.dumps(
                ["BVG-Einkauf prüfen?", "Pillar 3a-Limit erreicht?"]
            ),
            vorgehen_todos_json=json.dumps(
                ["Vorsorgeauftrag aufsetzen", "Risikoabsicherung überprüfen"]
            ),
            vorgehen_dokumente_json="kaputtes-json {",  # corrupted
            vorgehen_naechster_termin="2026-08-15",
        )
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    wv = report["weiteres_vorgehen"]
    assert wv["offene_fragen"] == [
        "BVG-Einkauf prüfen?", "Pillar 3a-Limit erreicht?",
    ]
    assert wv["todos"] == [
        "Vorsorgeauftrag aufsetzen", "Risikoabsicherung überprüfen",
    ]
    # Kaputtes JSON → leere Liste, kein Crash
    assert wv["dokumente"] == []
    assert wv["naechster_termin"] == "2026-08-15"


def test_audit_anchor_not_leaked_to_aggregator_output(session_factory):
    """`last_edited_by` und `last_edited_at` aus Notes dürfen NICHT in der
    Aggregator-Antwort auftauchen — die sind für den GET /report-notes-
    Endpoint da, nicht für die JSON-Struktur des Reports."""
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        _seed_report_notes(
            s, mandate.id, advisor.id,
            aa_anmerkungen="X",
        )
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    raw = json.dumps(report)
    assert "last_edited_by" not in raw
    assert "last_edited_at" not in raw
    # advisor.id darf vorkommen (im Cover advisor-Block), aber nicht als
    # last_edited_by-Wert im AssetAllocation-Output. Reicht: kein
    # "last_edited"-Key irgendwo in der Sektion.
    assert "last_edited" not in json.dumps(report["asset_allocation"])
    assert "last_edited" not in json.dumps(report["weiteres_vorgehen"])
