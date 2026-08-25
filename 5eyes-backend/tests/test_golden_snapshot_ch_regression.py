"""Golden-Snapshot-Baseline fuer den Schweiz-Pfad (jurisdiction IS NULL / "CH").

Die Baseline friert den fachlich freigegebenen stochastischen Kern inklusive
aktiver Methode/Status ein. Damit darf eine kuenftige Aenderung weder unbemerkt
auf die House Matrix zurueckfallen noch Ziel-, Suballokations- oder
Implementierungsgewichte verschieben.

Vorgehen: fuer 6 Kombinationen aus Risikoprofil-Score (unterschiedliche
_risk_score_bucket-Buckets) und Anlagepraeferenzen (equitiesGeo-Varianten,
chfOnly) wird ein frisches Test-Mandat geseedet, `generate_target_allocation`
und `generate_recommendation_run` End-to-End aufgerufen und das Ergebnis gegen
ein eingefrorenes JSON-Fixture unter tests/fixtures/golden_ch_recommendations/
verglichen (exakte Gleichheit, kein "similar enough").

Aus dem Vergleich ausgeschlossene/normalisierte Felder (nicht deterministisch
ueber getrennte Testlaeufe/DBs hinweg) -- Begruendung pro Feld:

- Alle Primary-/Foreign-Key-IDs (Mandate/Client/Assessment/Policy/CMA/Product/
  Position/Run-IDs) sowie created_at/updated_at/assessed_at/set_at-Zeitstempel:
  klassische Laufzeit-Artefakte (new_uuid()/_now()), nie Teil der Fachlogik.
  Wir bauen daher gezielt ein reduziertes, benanntes Snapshot-Dict aus den
  Ergebnis-Dicts von generate_target_allocation()/generate_recommendation_run()
  statt die rohen ORM-Objekte/Positions-Payloads zu dumpen.
- Monte-Carlo-abgeleitete Implementierungskennzahlen (TargetAllocation.mc_*,
  result["monte_carlo"]/result["goal_analysis"]): Sie besitzen eigene, breite
  statistische Vertrags-Suites und gehoeren nicht in diesen kompakten
  Produkt-/Gewichts-Snapshot. Die CMA-ID wird hier dennoch explizit fixiert,
  weil sie auch den aktiven stochastischen Entscheidungs-Seed bindet. Eingefroren
  werden Methode/Status/Engine-Version, targets_bps, bands_bps,
  risky_fraction_bps, limiting_factor, erwartete Momente sowie die komplette
  Produktselektion und -gewichtung.
- live_rebalancing / reasoning-Freitext: bewusst nicht Teil des Snapshots
  (siehe DEVIATIONS im Task-Report) -- Fokus liegt spec-gemaess auf
  sub_allocations, Produktgewichten und Gesamtsummen.

Sanity-Check (siehe Kommentar `SANITY_CHECK_INSTRUCTIONS` unten): dieser Test
wurde manuell verifiziert, dass er ROT wird, wenn man den CH-Default
"Schweiz Fokus" (equities_geo-Default in _build_sub_allocations) lokal
aendert. Die testweise Aenderung wurde NICHT committet.

WICHTIG (2026-08-19): Diese Fixtures sind SLSQP-Konvergenzergebnisse und
duerfen NUR auf dem Linux-CI-Runner regeneriert werden, nie lokal unter
Windows. Trotz exakt gepinnter numpy/scipy-Versionen (requirements.txt)
liefert der Solver auf Windows minimal andere Werte als auf Linux
(vermutlich unterschiedliche BLAS/LAPACK-Backends je Wheel-Plattform,
z.B. expected_return_bps 396 vs. 397) -- lokal unter Windows neu
eingefrorene Fixtures faellen daher reproduzierbar in CI durch. Zum
Regenerieren: temporaeren CI-Schritt einbauen, der _build_ch_snapshot()
fuer alle COMBOS aufruft und das Ergebnis als Artefakt hochlaedt (siehe
Git-Historie des Merge-Commits fuer ein Beispiel), dann das Artefakt
herunterladen und in tests/fixtures/golden_ch_recommendations/ kopieren.
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
# Vollstaendiges Modell-Set importieren (analog test_optimizer_shadow_mode.py),
# damit Base.metadata.create_all() unabhaengig von der Testreihenfolge/Isolation
# alle per ForeignKey referenzierten Tabellen kennt (z.B. clients.tenant_id ->
# tenants.id). Ohne diesen Import schlaegt create_all() fehl, wenn diese Datei
# als einzige/erste Testdatei eines pytest-Laufs geladen wird.
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)
configure_mappers()
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment, RiskAssessmentAnswer
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.portfolio_engine import (
    ensure_runtime_reference_data,
    generate_recommendation_run,
    generate_target_allocation,
)
from services.risk_scoring import profile_for_score_x10

FIXTURES_DIR = TESTS_ROOT / "fixtures" / "golden_ch_recommendations"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'golden_ch_snapshot.db'}",
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
# 6 Kombinationen aus Risikoprofil-Score (-> unterschiedliche
# _risk_score_bucket-Buckets 1..10) und Anlagepraeferenzen.
# ---------------------------------------------------------------------------
COMBOS: list[dict] = [
    {"name": "bucket3_defensiv_default_prefs", "score_x10": 30, "preferences": None},
    {"name": "bucket5_ausgewogen_default_prefs", "score_x10": 50, "preferences": None},
    {"name": "bucket7_wachstum_default_prefs", "score_x10": 70, "preferences": None},
    {"name": "bucket9_dynamisch_default_prefs", "score_x10": 90, "preferences": None},
    {
        "name": "bucket5_ausgewogen_equities_global",
        "score_x10": 50,
        "preferences": {"assetClasses": {"equitiesGeo": "Global"}},
    },
    {
        "name": "bucket5_ausgewogen_chfonly_em_focus",
        "score_x10": 50,
        "preferences": {
            "geo": {"chfOnly": True},
            "assetClasses": {"equitiesGeo": "Schwellenlaender"},
        },
    },
]


def _seed_ch_mandate(session_factory, *, suffix: str, score_x10: int) -> tuple[str, str, str, str]:
    """Seedet ein realistisches CH-Mandat (Depot 500k + Sparen + Pension-/
    Vermoegensziel) mit deterministischen IDs (basierend auf `suffix`, keine
    uuid4()) und einem parametrisierbaren Risikoprofil-Score, analog zum
    Seeding-Pattern in tests/test_optimizer_shadow_mode.py::_seed_realistic_mandate.
    """
    advisor_id = f"golden-adv-{suffix}"
    cid = f"golden-client-{suffix}"
    mid = f"golden-mandate-{suffix}"
    aid = f"golden-assessment-{suffix}"
    gid_pension = f"golden-goal-pension-{suffix}"
    gid_wealth = f"golden-goal-wealth-{suffix}"
    now = _now()
    today = date.today()
    pension_start = (today + timedelta(days=365 * 5)).isoformat()
    pension_end = (today + timedelta(days=365 * 30)).isoformat()
    wealth_target_date = (today + timedelta(days=365 * 10)).isoformat()

    with session_factory() as s:
        s.add(User(
            id=advisor_id, username=f"golden-adv-{suffix}", password_hash="h",
            full_name="Golden Advisor", role="advisor", is_active=1,
            created_at=now, updated_at=now,
        ))
        s.add(Client(
            id=cid, client_number=f"C-GOLD-{suffix}",
            first_name="Golden", last_name="Mandant",
            advisor_id=advisor_id, created_at=now, updated_at=now,
        ))
        s.add(Mandate(
            id=mid, client_id=cid, mandate_number=f"M-GOLD-{suffix}",
            mandate_type="Anlageberatung", opened_at=now,
            created_at=now, updated_at=now,
        ))
        s.add(WealthPosition(
            id=f"golden-pos-depot-{suffix}", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id=f"golden-cf-savings-{suffix}", client_id=cid, label="Sparen",
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
            # Golden cases need several effective score buckets. Keep one
            # truthful base questionnaire and express the case score through
            # the same documented override contract used in production.
            is_overridden=1,
            override_score_x10=score_x10,
            override_profile=profile_for_score_x10(score_x10),
            override_reason="Golden-Testfall mit ausdruecklich dokumentiertem Kundenwunsch",
            override_client_confirmed=1,
            override_warning_delivered=1,
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
                id=f"golden-answer-{suffix}-{q}", assessment_id=aid,
                question_number=q, question_section="Risikoprofil",
                answer_label=label, answer_points=points,
                created_at=now,
            ))
        s.commit()
        _policy, cma = ensure_runtime_reference_data(s, advisor_id)
        # Der stochastische Seed bindet die CMA-ID. Ein Golden-Test muss daher
        # auch diese fachliche Eingabe deterministisch halten; andernfalls
        # prueft er bloss zwei unterschiedliche Szenario-Stichproben.
        cma.id = f"golden-cma-{suffix}"
        s.commit()
    return advisor_id, cid, mid, aid


def _build_ch_snapshot(session_factory, combo: dict) -> dict:
    """Erzeugt das deterministische, sortierte Snapshot-Dict fuer einen Combo.

    Siehe Modul-Docstring fuer die vollstaendige Begruendung, welche Felder
    bewusst NICHT enthalten sind (IDs, Zeitstempel, Monte-Carlo-Kennzahlen).
    """
    suffix = combo["name"]
    score_x10 = combo["score_x10"]
    preferences = combo["preferences"]
    advisor_id, _cid, mid, _aid = _seed_ch_mandate(session_factory, suffix=suffix, score_x10=score_x10)

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        ta_result = generate_target_allocation(s, mandate, advisor_id, preferences=preferences)
        allocation = ta_result["target_allocation"]
        assert allocation.optimization_method == "stochastic"
        assert allocation.optimization_status in {"converged", "converged_robustified"}
        effective_constraints = json.loads(allocation.effective_constraints_json or "{}")
        target_allocation_snapshot = {
            "score_bucket": ta_result["score_bucket"],
            "house_matrix_profile": ta_result["house_matrix_profile"],
            "optimization_method": allocation.optimization_method,
            "optimization_status": allocation.optimization_status,
            "engine_version": effective_constraints.get("engine_version"),
            "targets_bps": {
                "equities": allocation.target_equities_bps,
                "bonds": allocation.target_bonds_bps,
                "real_estate": allocation.target_real_estate_bps,
                "alternatives": allocation.target_alternatives_bps,
                "liquidity": allocation.target_liquidity_bps,
            },
            "bands_bps": {
                "equities": [allocation.band_equities_min_bps, allocation.band_equities_max_bps],
                "bonds": [allocation.band_bonds_min_bps, allocation.band_bonds_max_bps],
                "real_estate": [allocation.band_real_estate_min_bps, allocation.band_real_estate_max_bps],
                "alternatives": [allocation.band_alternatives_min_bps, allocation.band_alternatives_max_bps],
                "liquidity": [allocation.band_liquidity_min_bps, allocation.band_liquidity_max_bps],
            },
            "risky_fraction_bps": allocation.risky_fraction_bps,
            "limiting_factor": allocation.limiting_factor,
            "expected_return_bps": int(ta_result["expected_return_bps"]),
            "expected_volatility_bps": int(ta_result["expected_volatility_bps"]),
            "advisory_wealth_rappen": int(ta_result["advisory_wealth_rappen"]),
            "investable_advisory_wealth_rappen": int(ta_result["investable_advisory_wealth_rappen"]),
            "reserve_needed_rappen": int(ta_result["reserve_needed_rappen"]),
            "external_reserve_rappen": int(ta_result["external_reserve_rappen"]),
        }
        sub_allocations_snapshot = sorted(
            (
                {
                    "asset_class": item["asset_class"],
                    "sub_asset_class": item["sub_asset_class"],
                    "target_weight_bps": int(item["target_weight_bps"]),
                    "rationale": item["rationale"],
                }
                for item in ta_result["sub_allocations"]
            ),
            key=lambda item: (item["asset_class"], item["sub_asset_class"]),
        )
        target_allocation_warnings = sorted(
            (f"{w.get('code')}:{w.get('message')}" if isinstance(w, dict) else str(w))
            for w in (ta_result.get("warnings") or [])
        )
        allocation_id = allocation.id
        s.commit()

    with session_factory() as s2:
        mandate = s2.query(Mandate).filter(Mandate.id == mid).first()
        run_result = generate_recommendation_run(
            s2,
            mandate,
            advisor_id,
            preferences=preferences,
            target_allocation_id=allocation_id,
        )
        positions_snapshot = sorted(
            (
                {
                    "product_name": item["product_name"],
                    "provider": item["provider"],
                    "asset_class": item["asset_class"],
                    "sub_asset_class": item["sub_asset_class"],
                    "source_sub_asset_classes": sorted(item["source_sub_asset_classes"]),
                    "currency": item["currency"],
                    "ter_bps": item["ter_bps"],
                    "target_weight_bps": int(item["target_weight_bps"]),
                    "target_amount_rappen": int(item["target_amount_rappen"]),
                    "rationale": item["rationale"],
                }
                for item in run_result["positions"]
            ),
            key=lambda item: item["product_name"],
        )
        recommendation_warnings = sorted(str(w) for w in (run_result.get("warnings") or []))
        totals_snapshot = {
            "advisory_wealth_rappen": int(run_result["advisory_wealth_rappen"]),
            "investable_advisory_wealth_rappen": int(run_result["investable_advisory_wealth_rappen"]),
            "expected_return_bps": int(run_result["expected_return_bps"]),
            "expected_volatility_bps": int(run_result["expected_volatility_bps"]),
            "average_ter_bps": run_result["average_ter_bps"],
            "average_ter_coverage_bps": run_result["average_ter_coverage_bps"],
            "missing_ter_positions_count": run_result["missing_ter_positions_count"],
            "sum_target_weight_bps": sum(p["target_weight_bps"] for p in positions_snapshot),
            "sum_target_amount_rappen": sum(p["target_amount_rappen"] for p in positions_snapshot),
        }
        implementation_steps_snapshot = list(run_result.get("implementation_steps") or [])

    return {
        "combo": {
            "name": combo["name"],
            "score_x10": score_x10,
            "preferences": preferences,
        },
        "target_allocation": target_allocation_snapshot,
        "sub_allocations": sub_allocations_snapshot,
        "target_allocation_warnings": target_allocation_warnings,
        "positions": positions_snapshot,
        "recommendation_warnings": recommendation_warnings,
        "totals": totals_snapshot,
        "implementation_steps": implementation_steps_snapshot,
    }


@pytest.mark.parametrize("combo", COMBOS, ids=[c["name"] for c in COMBOS])
def test_golden_ch_snapshot_matches_frozen_fixture(session_factory, combo):
    """Diff-Gate: der frisch erzeugte CH-Empfehlungs-Snapshot muss EXAKT
    (nicht nur "aehnlich") mit dem eingefrorenen Fixture-JSON uebereinstimmen.
    """
    fixture_path = FIXTURES_DIR / f"{combo['name']}.json"
    assert fixture_path.exists(), f"Fixture fehlt: {fixture_path}"
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))

    actual = _build_ch_snapshot(session_factory, combo)

    assert actual == expected


def test_all_combos_have_a_frozen_fixture_file():
    """Verhindert stilles Auseinanderlaufen von COMBOS und den Fixture-Dateien."""
    expected_files = {f"{combo['name']}.json" for combo in COMBOS}
    actual_files = {p.name for p in FIXTURES_DIR.glob("*.json")}
    assert expected_files == actual_files
