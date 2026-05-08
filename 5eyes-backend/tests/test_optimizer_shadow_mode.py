"""V3 Sprint 1 Tests: shadow_stochastic Modus.

Verifiziert:
- shadow_stochastic ist gueltiger Wert in config.validate_optimizer_mode
- Solver laeuft, ersetzt aber nicht die TargetAllocation-Targets
- TargetAllocation.optimization_* bleibt None (kein faelschliches Audit)
- stress_evaluations_json bleibt None (gehoert zur aktiven Allokation)
- optimizer_reasoning_json bleibt None (gehoert zur aktiven Allokation)
- allocation_method_comparison wird befuellt mit House-Matrix vs. Solver
- Sensitivity ist im shadow-Modus erlaubt
- Backwards-compat: house_matrix und stochastic Modus unveraendert
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
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
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
    evaluate_goal_sensitivity,
    generate_target_allocation,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'opt_shadow.db'}",
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
    """Mandant mit Depot 500k + Pension-Goal 24k/J ab 5J + Vermoegensziel."""
    suffix = suffix or str(uuid.uuid4())[:6]
    advisor_id = f"user-shadow-{suffix}"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    gid_pension = f"goal-shadow-pension-{suffix}"
    now = _now()
    today = date.today()
    pension_start = (today + timedelta(days=365 * 5)).isoformat()
    pension_end = (today + timedelta(days=365 * 30)).isoformat()
    wealth_target_date = (today + timedelta(days=365 * 10)).isoformat()

    with session_factory() as s:
        s.add(User(id=advisor_id, username=f"adv-shadow-{suffix}", password_hash="h",
                   full_name="Adv Shadow", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="Shadow", last_name="Mandant",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(WealthPosition(
            id=f"pos-shadow-depot-{suffix}", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id=f"cf-shadow-savings-{suffix}", client_id=cid, label="Sparen",
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
            id=f"goal-shadow-wealth-{suffix}", mandate_id=mid, client_id=cid,
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
            risk_capacity_total=21, risk_capacity_profile="Wachstumsorientiert",
            risk_capacity_score_x10=70,
            investment_horizon_years=15, investment_horizon_label="12 bis 17 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=4, q_risk_behavior_points=3,
            risk_willingness_total=10, risk_willingness_profile="Wachstumsorientiert",
            risk_willingness_score_x10=70,
            final_score_x10=70, final_profile="Wachstumsorientiert",
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
    return advisor_id, cid, mid, aid, gid_pension


# ============================================================================
# Config: shadow_stochastic akzeptiert
# ============================================================================


def test_validate_optimizer_mode_accepts_shadow_stochastic():
    from config import Settings
    # Wir nutzen den Validator direkt, damit wir nicht das ganze Settings-Set
    # neu instanziieren muessen (haengt von .env-Pfaden ab).
    assert Settings.validate_optimizer_mode("shadow_stochastic") == "shadow_stochastic"
    assert Settings.validate_optimizer_mode("SHADOW_STOCHASTIC") == "shadow_stochastic"


def test_validate_optimizer_mode_rejects_unknown():
    from config import Settings
    with pytest.raises(ValueError):
        Settings.validate_optimizer_mode("does-not-exist")


# ============================================================================
# Shadow-Modus laeuft, ersetzt aber Targets nicht
# ============================================================================


def test_shadow_stochastic_runs_solver_but_keeps_house_targets(session_factory, monkeypatch):
    """House-Matrix-Targets bleiben erhalten, Shadow-Vergleich ist im Response."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="keep")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        house = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        house_ta = house["target_allocation"]
        house_weights = {
            "equities": house_ta.target_equities_bps,
            "bonds": house_ta.target_bonds_bps,
            "real_estate": house_ta.target_real_estate_bps,
            "alternatives": house_ta.target_alternatives_bps,
            "liquidity": house_ta.target_liquidity_bps,
        }

    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        shadow = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        shadow_ta = shadow["target_allocation"]
        shadow_active_weights = {
            "equities": shadow_ta.target_equities_bps,
            "bonds": shadow_ta.target_bonds_bps,
            "real_estate": shadow_ta.target_real_estate_bps,
            "alternatives": shadow_ta.target_alternatives_bps,
            "liquidity": shadow_ta.target_liquidity_bps,
        }
        comparison = shadow.get("allocation_method_comparison")

    assert shadow_active_weights == house_weights, "Shadow darf aktive Targets nicht aendern"
    assert comparison is not None
    assert comparison["active_method"] == "house_matrix"
    assert comparison["shadow_method"] == "stochastic"
    assert comparison["shadow_status"] in (
        "converged", "diverged", "diverged_infeasible", "fallback_house_matrix",
    )
    # Comparison enthaelt aktive + Shadow-Gewichte
    assert comparison["active_weights_bps"] == shadow_active_weights
    assert isinstance(comparison["shadow_weights_bps"], dict)
    assert isinstance(comparison["weight_deltas_bps"], dict)
    assert "advisory_note" in comparison and comparison["advisory_note"]


def test_shadow_does_not_persist_optimizer_audit_on_target_allocation(session_factory, monkeypatch):
    """In Shadow darf die TA keine optimization_* Audit-Felder tragen."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="audit")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        ta = result["target_allocation"]
        assert ta.optimization_method is None
        assert ta.optimization_status is None
        assert ta.optimization_seed is None
        assert ta.optimization_iterations is None
        assert ta.optimization_objective_value_milli is None
        assert ta.stress_evaluations_json is None
        assert ta.optimizer_reasoning_json is None


def test_shadow_top_level_stress_evaluations_is_none(session_factory, monkeypatch):
    """Top-Level stress_evaluations gehoert zur aktiven (House) Allokation."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="stress")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        # Im Shadow-Modus liefert Top-Level None; Shadow-Stress wandert ggf.
        # in allocation_method_comparison (Sprint 1b).
        assert result.get("stress_evaluations") is None


def test_shadow_reasoning_mentions_shadow_not_replacement(session_factory, monkeypatch):
    """Reasoning erklaert klar, dass Shadow nicht angewendet wurde."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="reason")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        joined = " | ".join(result.get("reasoning", []))
        assert "Shadow" in joined or "House-Matrix bleibt aktive" in joined or "konvergierte nicht" in joined or "Optimizer Status" in joined


def test_shadow_comparison_advisory_note_no_marketing_language(session_factory, monkeypatch):
    """Beratungsnote enthaelt keine Marketing-/Garantie-Sprache."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="note")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        cmp = result.get("allocation_method_comparison")
        assert cmp is not None
        note = cmp.get("advisory_note", "").lower()
        for forbidden in ("garantiert", "ueberlegen", "beste", "optimal", "perfekt"):
            assert forbidden not in note, f"Marketing-Sprache '{forbidden}' in Beratungsnote: {note}"


def test_shadow_comparison_objective_delta_pct_none_in_sprint1(session_factory, monkeypatch):
    """Sprint 1 ohne Apples-to-Apples Objective: objective_delta_pct = None."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="delta")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        cmp = result["allocation_method_comparison"]
        assert cmp["objective_delta_pct"] is None
        assert cmp["objective_value_milli_active"] is None


def test_shadow_comparison_includes_two_candidates(session_factory, monkeypatch):
    """Candidates: einmal active=house_matrix, einmal shadow=stochastic."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="cands")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        cmp = result["allocation_method_comparison"]
        cands = cmp.get("candidates") or []
        roles = {c.get("role") for c in cands}
        assert roles == {"active", "shadow"}
        active_cand = next(c for c in cands if c["role"] == "active")
        shadow_cand = next(c for c in cands if c["role"] == "shadow")
        assert active_cand["method"] == "house_matrix"
        assert shadow_cand["method"] == "stochastic"


# ============================================================================
# Sensitivity in Shadow erlaubt
# ============================================================================


def test_sensitivity_allowed_in_shadow_stochastic(session_factory, monkeypatch):
    """Sensitivity-Analyse darf auch in shadow_stochastic laufen."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_realistic_mandate(session_factory, suffix="sens")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        # Smoke-Test: Funktion wirft NICHT ValueError wegen Modus.
        # Solver kann konvergieren oder fallback sein, beides akzeptabel.
        result = evaluate_goal_sensitivity(
            db=s, mandate=mandate, user_id=advisor_id,
            goal_id=gid, target_delta_pct=10,
        )
        assert result["goal_id"] == gid
        assert "status_baseline" in result


def test_sensitivity_blocked_in_house_matrix(session_factory, monkeypatch):
    """In house_matrix bleibt der 409 Fehler, weil Sensitivity Solver erfordert."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, gid = _seed_realistic_mandate(session_factory, suffix="hmsens")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        with pytest.raises(ValueError):
            evaluate_goal_sensitivity(
                db=s, mandate=mandate, user_id=advisor_id,
                goal_id=gid, target_delta_pct=10,
            )


# ============================================================================
# Backwards-compat: house_matrix Modus liefert kein comparison
# ============================================================================


def test_house_matrix_mode_has_no_comparison(session_factory, monkeypatch):
    """In house_matrix gibt es keinen Methodenvergleich."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="hmcmp")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        assert result.get("allocation_method_comparison") is None


def test_stochastic_mode_has_no_comparison(session_factory, monkeypatch):
    """In stochastic ist comparison aktuell ebenfalls None (Sprint 1).

    Sprint 1b kann optional auch fuer den stochastic-Modus einen Vergleich
    House-vs-Stochastic liefern; aktuell beschraenken wir das auf Shadow.
    """
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="stcmp")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        assert result.get("allocation_method_comparison") is None
