"""B4 - Goal-Base Konsistenz: Vermoegens- und Cashflow-Goals werden konsistent
gegen das advisory_wealth (Beratungsvermoegen) bewertet.

Vorher: _goal_base_scale skalierte MC-Pfade um max(advisory,total)/advisory,
ohne das Target zu skalieren -> success_rate verzerrt. Deterministischer
_build_goal_analysis nutzte investable_base=max(advisory,total), MC nutzt
advisory*scale -> zwei verschiedene Pfad-Definitionen.

Wissenschaftlich (Brunel 2003, ASIP §3.2): Goals muessen in EINER Bezugsgroesse
evaluiert werden. Da die Strategie nur das Beratungsvermoegen optimiert, werden
Goals immer gegen advisory_wealth bewertet. External Assets (Eigenheim etc.)
werden NICHT in die Goal-Hochrechnung einbezogen, weil sie nicht
strategie-relevant sind.

B4.1 Deterministisch: _build_goal_analysis nutzt advisory_wealth als investable_base
B4.2 MC: _monte_carlo_goal_summary bewertet path_values_by_year direkt (ohne scale)
B4.3 Konsistenz: deterministisch projected_value vs. MC P50 in identischer Bezugsgroesse
"""
from __future__ import annotations
import sys
import datetime
import uuid
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
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment, RiskAssessmentAnswer
from models.users import User
from models.wealth import Goal, WealthPosition
from services.portfolio_engine import (
    ensure_runtime_reference_data,
    generate_target_allocation,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit_b4.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_with_external_assets(session_factory):
    """200k Beratung + 800k Eigenheim Gesamtvermoegen.
    Goal: Vermoegensziel 'Gesamtvermoegen 1.5M in 10J'."""
    advisor_id = "user-b4-1"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        s.add(User(id=advisor_id, username="adv", password_hash="h",
                   full_name="Adv", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="T", last_name="X",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(WealthPosition(
            id="pos-b4-depot", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=200_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(WealthPosition(
            id="pos-b4-haus", client_id=cid,
            label="Eigenheim", position_type="Liegenschaft", assignment="Gesamtvermögen",
            current_value_rappen=800_000_00, currency="CHF",
            alloc_real_estate_bps=10000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Goal(
            id="goal-b4-total", mandate_id=mid, client_id=cid,
            goal_family="Vermoegen", goal_type="Vermoegensziel",
            goal_scope="Gesamtvermoegen",
            label="Gesamt 1.5M",
            rank=1, weight_bps=10000,
            target_wealth_rappen=1_500_000_00,
            horizon_years=10,
            hardness="Hart",
            value_mode="nominal",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
            q_income_points=2, q_obligations_points=3,
            q_savings_points=6, q_wealth_points=6,
            risk_capacity_total=17, risk_capacity_profile="Wachstumsorientiert",
            risk_capacity_score_x10=60,
            investment_horizon_years=10, investment_horizon_label="8 bis 11 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=3, q_risk_behavior_points=3,
            risk_willingness_total=9, risk_willingness_profile="Ausgewogen",
            risk_willingness_score_x10=60,
            final_score_x10=60, final_profile="Ausgewogen",
            is_overridden=0,
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        for q in (3, 5, 6, 7, 8, 9, 10, 11):
            s.add(RiskAssessmentAnswer(
                id=str(uuid.uuid4()), assessment_id=aid,
                question_number=q, question_section="Risikoprofil",
                answer_label=f"A{q}", answer_points=2,
                created_at=now,
            ))
        s.commit()
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return advisor_id, cid, mid, aid


def test_b4_goal_evaluated_against_advisory_only_consistent(session_factory):
    """Goal mit goal_scope=Gesamtvermoegen wird gegen advisory bewertet.
    deterministisches projected_value muss zur MC-P50-Bezugsgroesse passen
    (beide advisory-only). Vorher war P50 um Faktor (total/advisory) aufgeblaeht.
    """
    advisor_id, cid, mid, aid = _seed_with_external_assets(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)

    goal_analyses = result.get("goal_analysis") or []
    assert goal_analyses, "Goal-Analysis muss vorhanden sein"
    goal = goal_analyses[0]

    deterministic_projected = int(goal.get("projected_value_rappen") or 0)
    mc_p50 = int(goal.get("projected_value_p50_rappen") or 0)
    assert mc_p50 > 0, "MC P50 muss vorhanden sein"

    # B4-Konsistenz: deterministisch und P50 muessen in derselben Bezugsgroesse sein.
    # Mit ~6% Return ueber 10 Jahre ist projected ~ advisory*1.6 = ~320k.
    # Ohne Bug haetten wir P50 ~ advisory*1.6 = ~320k.
    # MIT _goal_base_scale waere P50 ~ 320k * (1000k/200k) = ~1600k (5x aufgeblaeht).
    # Test: P50 darf nicht groesser als deterministic*2.5 sein (sonst Drift).
    assert mc_p50 < deterministic_projected * 2.5, (
        f"P50 {mc_p50} ist unrealistisch viel groesser als deterministic projected "
        f"{deterministic_projected} -> _goal_base_scale Drift moeglich"
    )


def test_b4_goal_base_advisory_target_unchanged(session_factory):
    """Goal target_wealth_rappen bleibt unveraendert (User-Eingabe), Bewertung
    erfolgt gegen advisory_wealth -> erwartetes Ergebnis: niedriger Score
    weil 200k advisory nicht 1.5M erreicht."""
    advisor_id, cid, mid, aid = _seed_with_external_assets(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)

    goal_analyses = result.get("goal_analysis") or []
    goal = goal_analyses[0]
    score = int(goal.get("achievement_score") or 0)
    # Mit nur 200k advisory + ~6% Return ueber 10J ergibt ~360k. Target 1.5M.
    # Score = 360k/1500k ~ 24%
    assert score < 50, f"Score erwartet < 50% (advisory unrealistisch), got {score}"


def test_b4_goal_advisory_only_no_external_inflation(session_factory):
    """Sanity: deterministic projected_value_rappen entspricht der Hochrechnung
    von advisory_wealth_rappen, NICHT von max(advisory, total)."""
    advisor_id, cid, mid, aid = _seed_with_external_assets(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)

    advisory = int(result.get("advisory_wealth_rappen") or 0)
    investable = int(result.get("investable_advisory_wealth_rappen") or advisory)
    goal_analyses = result.get("goal_analysis") or []
    projected = int(goal_analyses[0].get("projected_value_rappen") or 0)
    # 10 Jahre Hochrechnung mit ca 4-7% Return: projected sollte zwischen
    # advisory (Untergrenze) und advisory*4 (extreme Obergrenze) liegen.
    assert advisory <= projected <= advisory * 4, (
        f"Projected {projected} ausserhalb plausibler Range fuer advisory {advisory}"
    )
