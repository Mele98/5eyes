"""Red test fuer MANUAL-TARGET-SEMANTICS-001 (Round 46).

Befund (verifiziert per Grep gegen `services/optimizer/solver.py` und
`services/optimizer/objective.py`): das manuelle Asset-Klassen-Ziel
(`target_bps` in `AllocationPreferencesPayload.bands`, z.B. "Aktien-Ziel
60%") taucht in keiner der beiden Dateien ausserhalb eines voellig
unverwandten Konzepts auf (`target_bps` in `objective.py` ist dort der
Renditeziel-Wert eines Goals, nicht die manuelle Asset-Klassen-Praeferenz).

Der reale Produktions-Einstiegspunkt, der die Berater-Praeferenzen in den
Solver einspeist, ist `services.portfolio_engine_optimizer_integration.
_run_stochastic_optimizer_pass()`, aufgerufen aus
`services.portfolio_engine.generate_target_allocation()`. Dort wird
`context_kwargs` (das sowohl an `build_optimizer_context()` als auch an
`run_solver()` geht) ausschliesslich aus `cma`, `goals`, `house_matrix`,
`score_x10`, `advisory_wealth_rappen`, `cashflow_series_rappen`,
`external_wealth_rappen(_series)`, `horizon_years`, `n_paths`,
`inflation_series_bps`, `risky_fraction_per_bucket`,
`max_risky_fraction_bps`, `sub_allocations`, `effective_bounds_bps` sowie
Tax-/Mortalitaets-kwargs gebaut -- der mutable `targets`-Parameter (der den
per `_apply_band_preferences()` angewendeten manuellen `target_bps`-Wert
traegt) wird NUR als Output-Container ueberschrieben (`targets[bucket] =
result.weights_bps[bucket]`, nur falls `apply_targets=True` und konvergiert)
und niemals als Input in Context/Initial-Guess/Objective gelesen. Nur die
davon abgeleiteten `effective_bounds_bps` (min/max) beeinflussen den Solver.

Dieser Test baut zwei sonst identische Szenarien (gleiches Mandat, gleiche
CMA, gleiche Bandbreiten 0..10000 bps je Bucket) und unterscheidet sich NUR
im manuellen `target_bps` fuer equities/bonds (20%/50% vs. 60%/10% --
Beispiel aus dem Audit-Finding). Weil die Bandbreiten (min/max) in beiden
Szenarien identisch und absichtlich weit sind (0..10000 bps), beeinflusst
der manuelle Zielwert den Solver NICHT -- beide Laeufe konvergieren auf
exakt dieselbe Allokation mit demselben Seed.

xfail(strict=True): das ist das AKTUELL falsche Verhalten. Sobald
MANUAL-TARGET-SEMANTICS-001 gefixt ist (z.B. durch einen Soft-Penalty-Term
im Objective fuer Abweichung vom manuellen Ziel, oder einen beim Solver
registrierten Initial-Guess), muss dieser Test wieder rot werden (XPASS)
und sollte dann entfernt bzw. in einen echten Assertions-Test ueberfuehrt
werden.
"""
from __future__ import annotations

import datetime
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers
from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users,
    wealth,
)
configure_mappers()

import services.portfolio_engine as pe
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment, RiskAssessmentAnswer
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.portfolio_engine import (
    ensure_runtime_reference_data,
    generate_target_allocation,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'manual_target_bps_ignored.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_realistic_mandate(session_factory, suffix: str = ""):
    """Identischer Aufbau zu test_optimizer_integration._seed_realistic_mandate
    (Depot 500k + Pension-Goal + Vermoegensziel, "Wachstumsorientiert"-Profil
    mit weiten House-Matrix-Bandbreiten, damit der stochastische Solver fuer
    beide Szenarien unten tatsaechlich konvergiert, statt auf den
    House-Matrix-Fallback zurueckzufallen)."""
    suffix = suffix or str(uuid.uuid4())[:6]
    advisor_id = f"user-mtbi-{suffix}"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    now = _now()
    today = date.today()
    pension_start = (today + timedelta(days=365 * 5)).isoformat()
    pension_end = (today + timedelta(days=365 * 30)).isoformat()
    wealth_target_date = (today + timedelta(days=365 * 10)).isoformat()

    with session_factory() as s:
        s.add(User(id=advisor_id, username=f"adv-mtbi-{suffix}", password_hash="h",
                   full_name="Adv MTBI", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="MTBI", last_name="Mandant",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(WealthPosition(
            id=f"pos-mtbi-depot-{suffix}", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id=f"cf-mtbi-savings-{suffix}", client_id=cid, label="Sparen",
            cashflow_type="Income", amount_rappen=20_000_00,
            currency="CHF", frequency="jährlich", nature="wiederkehrend",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Goal(
            id=f"goal-mtbi-pension-{suffix}", mandate_id=mid, client_id=cid,
            goal_family="Lebenshaltung", goal_type="Pensionsausgabe",
            label="Pension", rank=1, weight_bps=5000,
            goal_scope="Beratungsvermögen", value_mode="real",
            target_amount_rappen=24_000_00, frequency="jährlich",
            start_date=pension_start, target_date=pension_end,
            is_ongoing=0, hardness="Hart",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Goal(
            id=f"goal-mtbi-wealth-{suffix}", mandate_id=mid, client_id=cid,
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
                id=str(uuid.uuid4()), assessment_id=aid,
                question_number=q, question_section="Risikoprofil",
                answer_label=label, answer_points=points,
                created_at=now,
            ))
        s.commit()
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return advisor_id, cid, mid, aid


# Zwei Szenarien, gleiche (weite, identische) Bandbreiten 0..10000 bps je
# Bucket, gleiche Mandatsdaten -- nur target_bps fuer equities/bonds ist
# gegensaetzlich (Audit-Beispiel: Aktien 20% vs. 60%, Obligationen 50% vs
# 10%). Weil min/max in beiden Szenarien identisch sind, ist dies die
# einzige Variable.
_BOUNDS_FIXED = {"min_bps": 0, "max_bps": 10000}

_PREFS_LOW_EQUITY = {
    "bands": {
        "equities": {**_BOUNDS_FIXED, "target_bps": 2000},
        "bonds": {**_BOUNDS_FIXED, "target_bps": 5000},
        "real_estate": {**_BOUNDS_FIXED, "target_bps": 1000},
        "alternatives": {**_BOUNDS_FIXED, "target_bps": 1000},
        "liquidity": {**_BOUNDS_FIXED, "target_bps": 1000},
    }
}

_PREFS_HIGH_EQUITY = {
    "bands": {
        "equities": {**_BOUNDS_FIXED, "target_bps": 6000},
        "bonds": {**_BOUNDS_FIXED, "target_bps": 1000},
        "real_estate": {**_BOUNDS_FIXED, "target_bps": 1000},
        "alternatives": {**_BOUNDS_FIXED, "target_bps": 1000},
        "liquidity": {**_BOUNDS_FIXED, "target_bps": 1000},
    }
}


def test_contradictory_manual_target_bps_should_change_converged_allocation(
    session_factory, monkeypatch
):
    """Zwei gegensaetzliche manuelle Asset-Klassen-Ziele (equities 20% vs.
    60%, bonds 50% vs. 10%), identische, weite Bandbreiten (0..10000 bps je
    Bucket) und dasselbe Mandat/CMA/Seed MUESSEN den konvergierten
    Stochastic-Solver-Output unterschiedlich beeinflussen -- sonst ist der
    manuelle Zielwert im Classic-UI reine Deko, die der Solver niemals
    konsumiert.

    HEUTIGES (fehlerhaftes) Verhalten: `_run_stochastic_optimizer_pass()`
    baut `context_kwargs` nur aus CMA/Goals/House-Matrix/Score/Cashflows/
    `effective_bounds_bps` -- der mutable `targets`-Parameter (der den
    manuellen `target_bps`-Wert traegt) geht nie in `build_optimizer_context`
    oder `run_solver` ein. Weil die Bandbreiten hier bewusst in beiden
    Szenarien identisch und weit sind, ist das Solver-Ergebnis fuer beide
    Szenarien numerisch IDENTISCH (gleicher Seed, gleiche Allokation,
    gleicher Objective-Wert) -- der Beweis, dass der manuelle Zielwert nie
    konsumiert wurde.
    """
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, cid, mid, aid = _seed_realistic_mandate(session_factory, suffix="mtbi")

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result_low = generate_target_allocation(
            s, mandate, advisor_id, preferences=_PREFS_LOW_EQUITY
        )
        ta_low = result_low["target_allocation"]

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result_high = generate_target_allocation(
            s, mandate, advisor_id, preferences=_PREFS_HIGH_EQUITY
        )
        ta_high = result_high["target_allocation"]

    # Sanity: beides lief tatsaechlich im stochastischen Solver-Pfad mit
    # demselben Mandat -> deterministic_seed() haengt nur von cma.id,
    # goal_ids, score_x10, horizon und n_paths ab, NICHT von preferences ->
    # erwartungsgemaess identischer Seed in beiden Szenarien.
    assert ta_low.optimization_method is not None
    assert ta_high.optimization_method is not None
    assert ta_low.optimization_seed == ta_high.optimization_seed

    # Die eigentliche Behauptung (heute FALSCH, siehe Docstring): ein
    # gegensaetzliches manuelles equities-Ziel (20% vs. 60%) muss zu einer
    # unterschiedlichen konvergierten equities-Allokation fuehren.
    assert ta_low.target_equities_bps != ta_high.target_equities_bps, (
        f"equities bps identisch trotz gegensaetzlicher manueller Ziele "
        f"(20% vs. 60%): low={ta_low.target_equities_bps}, "
        f"high={ta_high.target_equities_bps}. Der manuelle target_bps-Wert "
        f"erreicht den stochastischen Solver nicht."
    )
    assert ta_low.target_bonds_bps != ta_high.target_bonds_bps, (
        f"bonds bps identisch trotz gegensaetzlicher manueller Ziele "
        f"(50% vs. 10%): low={ta_low.target_bonds_bps}, "
        f"high={ta_high.target_bonds_bps}."
    )
