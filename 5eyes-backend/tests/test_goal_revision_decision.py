"""GOAL-REVISION-DECISION-001 (CIO-Entscheid 2026-10-21, Engine
``saa_resampled_v11``) -- Codex-Closure-Review zu PR #655
(docs/audits/2026-10-20-goal-reachability-certificate-pr655-closure-
review.md, P0).

Befund: eine zulaessige Allokation erreicht ein hartes Ziel auf 400/400
Pfaden; die schmale Erfolgsinsel liegt zwischen allen Startpunkten, SLSQP
verfehlt sie, das Ergebnis wurde trotzdem ``certified_unreachable_on_screen_
cube`` -> Herabstufung aus Stufe 1. Ein lokales Optimum ist kein globaler
Unmoeglichkeitsnachweis.

Entscheid:
1. keine automatische Herabstufung aus einer lokalen Suche; Status
   ``not_found_reachable_locally`` / ``global_certificate_unavailable``; das
   Ziel bleibt mit seinem Haertegrad in Stufe 1;
2. herabgestuft wird nur ueber eine explizite, replaybare
   GoalRevisionDecisionV1 (append-only), deren Ziel-Snapshot-Hash zum
   aktuellen Ziel passt;
3. Vorschlag statt Automatik (Reasoning + AA-Ansicht + POST-Endpunkt).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from services import goal_revision_decision as revision  # noqa: E402
from services.optimizer import goal_reachability as reachability  # noqa: E402
from services.optimizer import objective as objective_module  # noqa: E402
from services.optimizer import solver as solver_module  # noqa: E402
from services.optimizer.goal_liabilities import GoalLiability  # noqa: E402
from services.optimizer.objective_contract import ObjectiveContractV1  # noqa: E402


def _hard_goal() -> GoalLiability:
    return GoalLiability(
        goal_id="reachable-island",
        label="Reachable island",
        goal_type="Vermoegensziel",
        target_kind="wealth_at_t",
        target_amount_rappen=1_000,
        target_year_index=1,
        liability_path_rappen=[0],
        hardness_key="hart",
        weight_bps=10_000,
        success_probability_min_x100=8_000,
    )


# ---------------------------------------------------------------------------
# 1. Codex-Reproducer (docs/audits/reproducers/test_2026_10_20_pr655_goal_
#    reachability_certificate_adversarial.py), unveraendert uebernommen, nur
#    ohne xfail-Marker. Rot auf develop (v10): certified_unreachable +
#    demoted_goal_ids == ["reachable-island"], Stufe 1 leer.
# ---------------------------------------------------------------------------


def _island_context(monkeypatch, n_paths: int = 400):
    goal = _hard_goal()
    context = SimpleNamespace(
        liabilities=[goal],
        horizon_years=1,
        n_paths=n_paths,
        advisory_wealth_rappen=100,
        bounds=[(0.0, 1.0)] * 5,
        scipy_constraints=[
            {"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)},
        ],
        scenario_weights=None,
        objective_contract=ObjectiveContractV1(
            objective_mode="goal_shortfall",
            goal_weighting_mode="hardness",
        ),
    )
    candidates = [np.eye(5)[index] for index in range(5)]
    monkeypatch.setattr(
        reachability,
        "candidate_allocations",
        lambda _context: [candidate.copy() for candidate in candidates],
    )
    monkeypatch.setattr(
        reachability,
        "_build_screening_context",
        lambda _context: (context, 655, "narrow-island-cube"),
    )

    def terminal_value(weight_first: float) -> float:
        x = float(weight_first)
        local_width = 0.01
        hidden_width = 0.01
        local = 10.0 * sum(
            np.exp(-((x - peak) / local_width) ** 2)
            for peak in (0.0, 0.2, 1.0)
        )
        hidden = 200.0 * np.exp(-((x - 0.25) / hidden_width) ** 2)
        return 900.0 + local + hidden

    def simulate(_context, weights):
        terminal = terminal_value(np.asarray(weights, dtype=np.float64)[0])
        return np.column_stack([
            np.full(n_paths, 100.0),
            np.full(n_paths, terminal),
        ])

    monkeypatch.setattr(solver_module, "_simulate_context_wealth", simulate)
    monkeypatch.setattr(
        solver_module,
        "_annualized_twr_bps_per_path",
        lambda _context, _weights: np.zeros(n_paths),
    )
    return context, goal, terminal_value, simulate


def test_local_multistart_failure_cannot_certify_global_unreachability(monkeypatch):
    """A narrow feasible success island exists between every local start."""
    context, goal, terminal_value, simulate = _island_context(monkeypatch)

    hidden_portfolio = np.array([0.25, 0.1875, 0.1875, 0.1875, 0.1875])
    hidden_wealth = simulate(context, hidden_portfolio)
    assert np.all(
        objective_module._goal_probability_core(hidden_wealth, goal, 100)
    )
    assert terminal_value(0.25) > 1_000.0
    assert all(terminal_value(x) < 1_000.0 for x in (0.0, 0.2, 1.0))

    screen = reachability.goal_reachability_screen(context)
    row = screen["goals"][0]
    certificate = row["certificate"]

    assert certificate["status"] != "certified_unreachable_on_screen_cube"
    assert screen["certified_unreachable_goal_ids"] == []
    assert screen["demoted_goal_ids"] == []
    context.goal_reachability = screen
    assert solver_module._stage1_liabilities(context) == [goal]


def test_local_miss_is_disclosed_as_not_found_with_a_suggestion(monkeypatch):
    """Derselbe Gegenfall -- aus dem RICHTIGEN Grund gruen: die lokale Suche
    verfehlt die Insel tatsaechlich (der Status ist ehrlich "lokal nicht
    gefunden"), das Ziel bleibt trotzdem Stufe 1, und die Engine schlaegt
    die Einstufung nur vor."""
    context, goal, _tv, _sim = _island_context(monkeypatch)
    screen = reachability.goal_reachability_screen(context)
    row = screen["goals"][0]
    certificate = row["certificate"]
    assert certificate["status"] == reachability.CERTIFICATE_STATUS_NOT_FOUND
    assert certificate["status"] == "not_found_reachable_locally"
    assert certificate["global_certificate"] == "unavailable_local_search_only"
    assert certificate["upper_bound_kind"] == "sampling_wilson_at_best_found_point"
    assert certificate["max_probability"] == 0.0  # Insel nicht gefunden
    assert certificate["n_local_solves"] >= 1
    assert sum(certificate["solver_status_counts"].values()) >= certificate["n_local_solves"]
    assert row["certified_unreachable"] is False
    assert row["revision_suggested"] is True
    assert screen["revision_suggested_goal_ids"] == ["reachable-island"]
    context.goal_reachability = screen
    assert solver_module._stage1_liabilities(context) == [goal]


def test_solver_failure_is_fail_safe_stage1(monkeypatch):
    """Codex 6: ``minimize.success=False``/NaN/Iterationslimit sind nie eine
    Herabstufung."""
    context, goal, _tv, _sim = _island_context(monkeypatch)
    import scipy.optimize

    def broken(fun, x0, **_kwargs):
        fun(np.asarray(x0))
        return SimpleNamespace(success=False, x=np.full(len(x0), np.nan), message="boom")

    monkeypatch.setattr(scipy.optimize, "minimize", broken)
    screen = reachability.goal_reachability_screen(context)
    certificate = screen["goals"][0]["certificate"]
    assert certificate["status"] == "not_found_reachable_locally"
    assert certificate["solver_status_counts"]["failure"] == certificate["n_local_solves"]
    assert certificate["solver_status_counts"]["non_finite"] == certificate["n_local_solves"]
    assert screen["demoted_goal_ids"] == []
    context.goal_reachability = screen
    assert solver_module._stage1_liabilities(context) == [goal]


def test_without_feasible_set_status_is_global_certificate_unavailable(monkeypatch):
    context, goal, _tv, _sim = _island_context(monkeypatch)
    del context.bounds
    screen = reachability.goal_reachability_screen(context)
    assert screen["goals"][0]["certificate"]["status"] == "global_certificate_unavailable"
    assert screen["demoted_goal_ids"] == []
    context.goal_reachability = screen
    assert solver_module._stage1_liabilities(context) == [goal]


# ---------------------------------------------------------------------------
# 2. Decision: Hash, Gueltigkeit, Engine-Wirkung
# ---------------------------------------------------------------------------


def _goal(**overrides):
    base = dict(
        id="g-far", goal_family="Vermoegen", goal_type="Vermoegensziel", rank=2,
        weight_bps=None, goal_scope="Beratungsvermögen", value_mode="nominal",
        target_amount_rappen=50_000_000_00, target_wealth_rappen=50_000_000_00,
        target_return_bps=None, success_probability_min_x100=8000,
        start_date="2026-01-01", horizon_years=None, target_date="2051-01-01",
        is_ongoing=0, frequency=None, hardness="Hart", probability_pct=100,
        pension_pillar=None, linked_position_id=None, is_included=1,
        lifecycle_decision=None, label="Aussichtslos",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _decision_for(goal, **overrides) -> dict:
    payload = {
        "id": "grd-1",
        "schema_version": revision.SCHEMA_VERSION,
        "goal_id": goal.id,
        "mandate_id": "m-1",
        "client_id": "c-1",
        "sequence_no": 1,
        "previous_decision_id": None,
        "goal_snapshot_hash": revision.goal_snapshot_hash(goal),
        "goal_snapshot_json": json.dumps(revision.goal_snapshot(goal), sort_keys=True),
        "previous_hardness": goal.hardness,
        "new_status": revision.NEW_STATUS_SUBORDINATE_WISH,
        "reason": "Mit dem Kunden besprochen: Familienvermoegen ist ein Wunsch, kein Muss.",
        "evidence_status": "not_found_reachable_locally",
        "evidence_best_probability_bps": 170,
        "evidence_wilson_upper_bps": 300,
        "evidence_tau_bps": 8000,
        "evidence_engine_version": "saa_resampled_v11",
        "evidence_allocation_id": "ta-1",
        "evidence_screening_cube_hash": "cube",
        "actor_id": "adv-1",
        "decided_at": "2026-10-21T10:00:00.000Z",
        "rules_version": revision.RULES_VERSION,
    }
    payload.update(overrides)
    payload["decision_hash"] = revision.compute_decision_hash(payload)
    return payload


def test_decision_validity_binds_hash_goal_and_goal_snapshot():
    goal = _goal()
    decision = _decision_for(goal)
    assert revision.decision_validity(goal, decision) == "valid"
    tampered = dict(decision, reason="Manipulierte Begruendung ohne neuen Hash")
    assert revision.decision_validity(goal, tampered) == "hash_mismatch"
    assert revision.decision_validity(_goal(id="other"), decision) == "goal_mismatch"
    # Jede Zieldefinitions-Aenderung macht die Decision unwirksam ...
    for change in (
        {"target_amount_rappen": 40_000_000_00}, {"target_date": "2052-01-01"},
        {"hardness": "Primär"}, {"rank": 1}, {"success_probability_min_x100": 7000},
        {"is_included": 0},
    ):
        assert revision.decision_validity(_goal(**change), decision) == "goal_changed", change
    # ... die Bezeichnung nicht (keine wirtschaftliche Aenderung).
    assert revision.decision_validity(_goal(label="Neuer Name"), decision) == "valid"


def _engine_inputs(goals):
    from test_engine_input_sensitivity import _cma, _hm_wachstum

    return dict(
        cma=_cma(), goals=goals, house_matrix_row=_hm_wachstum(), score_x10=75,
        advisory_wealth_rappen=500_000_00, cashflow_series_rappen=[0] * 25,
        horizon_years=25, n_paths=300,
    )


def _engine_goal(goal_id, *, target, hardness, rank):
    from test_engine_reference_mandates import _make_goal

    goal = _make_goal(
        goal_id=goal_id, label=goal_id, hardness=hardness, goal_type="Vermoegensziel",
        target_rappen=target, target_date_offset_days=365 * 25,
    )
    goal.rank = rank
    return goal


def test_engine_demotes_only_with_a_valid_decision_and_never_automatically():
    """Ohne Decision bleibt auch ein aussichtsloses HARTES Ziel Stufe 1
    (Engine v11: keine Auto-Herabstufung); mit gueltiger Decision ist es
    nachrangig; nach einer Zielaenderung wieder normal."""
    reach = _engine_goal("reach", target=700_000_00, hardness="Primär", rank=1)
    far = _engine_goal("far", target=50_000_000_00, hardness="Hart", rank=2)

    plain = solver_module.build_optimizer_context(seed=11, **_engine_inputs([reach, far]))
    screen = plain.goal_reachability
    assert screen["revision_suggested_goal_ids"] == ["far"]
    assert screen["demoted_goal_ids"] == []
    assert screen["certified_unreachable_goal_ids"] == []
    assert sorted(str(l.goal_id) for l in solver_module._stage1_liabilities(plain)) == ["far", "reach"]
    assert not any(l.demoted for l in plain.liabilities)

    far.goal_revision_decision = _decision_for(far)
    decided = solver_module.build_optimizer_context(seed=11, **_engine_inputs([reach, far]))
    by_id = {str(l.goal_id): l for l in decided.liabilities}
    assert by_id["far"].demoted is True
    assert by_id["far"].revision_decision_id == "grd-1"
    assert by_id["far"].revision_decision_hash == far.goal_revision_decision["decision_hash"]
    assert by_id["reach"].demoted is False
    assert [str(l.goal_id) for l in solver_module._stage1_liabilities(decided)] == ["reach"]
    assert decided.goal_reachability["demoted_goal_ids"] == ["far"]
    # Gleicher Wuerfel: die Decision aendert nicht den Inhalts-Seed.
    assert decided.seed == plain.seed

    far.target_wealth_rappen = far.target_amount_rappen = 45_000_000_00  # Zielaenderung
    changed = solver_module.build_optimizer_context(seed=11, **_engine_inputs([reach, far]))
    assert not any(l.demoted for l in changed.liabilities)
    assert sorted(str(l.goal_id) for l in solver_module._stage1_liabilities(changed)) == ["far", "reach"]


def test_reasoning_and_published_rows_carry_suggestion_without_impossibility_claim():
    reach = _engine_goal("reach", target=700_000_00, hardness="Primär", rank=1)
    far = _engine_goal("far", target=50_000_000_00, hardness="Hart", rank=2)
    context = solver_module.build_optimizer_context(seed=11, **_engine_inputs([reach, far]))
    lines = reachability.reachability_reasoning(context.goal_reachability)
    assert len(lines) == 1
    text = lines[0]
    assert "'far'" in text
    assert "nicht mit ausreichender Sicherheit erreicht" in text
    assert "als nachrangiges Wunschziel einstufen" in text
    assert "vorrangig geschuetzt" in text
    for forbidden in ("unerreichbar", "zertifiziert", "garantiert", "unmoeglich"):
        assert forbidden not in text.lower()

    rows = reachability.annotate_rows(
        [{"goal_id": "far", "probability": 0.0}, {"goal_id": "reach", "probability": 0.9}],
        context.goal_reachability,
    )
    far_row = rows[0]
    # bool-Vertrag (v7/v9): nicht gefunden; der ehrliche Status steht in goal_revision.
    assert far_row["feasible_set_reachable"] is False
    evidence = far_row["goal_revision"]
    assert evidence["revision_suggested"] is True
    assert evidence["status"] == "not_found_reachable_locally"
    assert evidence["engine_version"] == "saa_resampled_v13"
    assert evidence["goal_snapshot_hash"] == revision.goal_snapshot_hash(far)
    assert evidence["upper_bound_kind"] == "sampling_wilson_at_best_found_point"
    assert 0.0 <= evidence["best_probability"] <= evidence["wilson_upper_bound"] < evidence["threshold"]
    assert rows[1]["feasible_set_reachable"] is True
    assert rows[1]["goal_revision"]["revision_suggested"] is False

    far.goal_revision_decision = _decision_for(far)
    decided = solver_module.build_optimizer_context(seed=11, **_engine_inputs([reach, far]))
    decided_lines = reachability.reachability_reasoning(decided.goal_reachability)
    assert len(decided_lines) == 1
    assert "per Beraterentscheid (grd-1" in decided_lines[0]
    assert "als nachrangiges Wunschziel eingestuft" in decided_lines[0]
    assert "als nachrangiges Wunschziel verfolgt" in decided_lines[0]
    assert "verdraengt keine erreichbaren Ziele" in decided_lines[0]


def test_engine_version_and_policies_are_v11():
    from services.optimizer.objective import DEMOTED_GOAL_POLICY_VERSION
    from services.optimizer.objective_contract import resolve_objective_contract

    assert solver_module.OPTIMIZER_ENGINE_VERSION == "saa_resampled_v13"
    evidence = resolve_objective_contract().as_evidence()
    assert evidence["goal_reachability_policy"] == reachability.GOAL_REACHABILITY_SCREEN_VERSION
    assert "no_auto_demotion" in reachability.GOAL_REACHABILITY_SCREEN_VERSION
    assert evidence["goal_demotion_policy"] == DEMOTED_GOAL_POLICY_VERSION
    assert DEMOTED_GOAL_POLICY_VERSION.startswith("goal_revision_decision_")


def test_input_snapshot_hash_changes_with_an_attached_decision():
    """Eine neue Decision macht die aktuelle Allokation veraltet (sonst
    wuerde REGENERATE-IDEMPOTENT-001 die alte, nicht herabgestufte
    Allokation wiederverwenden); ohne Decision bleibt der Hash bitgleich."""
    from services.portfolio_engine import _compute_input_snapshot_hash

    goal = _goal()
    kwargs = dict(
        advisory_positions=[], all_positions=[], cashflows=[], goals=[goal],
        advisory_wealth_rappen=1, total_wealth_rappen=1, wealth_inflows=[],
        projection_context={"k": 1},
    )
    before = _compute_input_snapshot_hash(**kwargs)
    goal.goal_revision_decision = None
    assert _compute_input_snapshot_hash(**kwargs) == before
    goal.goal_revision_decision = _decision_for(goal)
    assert _compute_input_snapshot_hash(**kwargs) != before


# ---------------------------------------------------------------------------
# 3. Persistenz + POST-Endpunkt
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database import Base
    from services.postgres_rls import import_tenant_models

    import_tenant_models()
    from tests.test_risk_capacity_plausibility import _seed

    engine = create_engine(
        f"sqlite:///{tmp_path / 'goal_revision.db'}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    with factory() as session:
        advisor = _seed(session)
        yield session, advisor, tmp_path / "goal_revision.db"
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


NOW = "2026-10-21T09:00:00.000Z"


def _db_goal(session):
    from models.wealth import Goal

    goal = Goal(
        id="g-far", mandate_id="m-rcp", client_id="cl-rcp", goal_family="Vermoegen",
        goal_type="Vermoegensziel", label="Familienvermoegen", rank=2,
        goal_scope="Beratungsvermögen", value_mode="nominal",
        target_amount_rappen=5_000_000_00, success_probability_min_x100=8000,
        start_date="2026-01-01", target_date="2035-12-31", is_ongoing=0,
        hardness="Primär", probability_pct=100, is_active=1, is_included=1,
        created_at=NOW, updated_at=NOW,
    )
    session.add(goal)
    session.commit()
    return goal


def _allocation(session, goal, *, suggested=True, snapshot_hash=None, ta_id="ta-1"):
    from models.allocation import TargetAllocation

    evidence = {
        "status": "not_found_reachable_locally" if suggested else "reachable",
        "revision_suggested": suggested,
        "demoted_by_decision": False,
        "best_probability": 0.166,
        "wilson_upper_bound": 0.18,
        "tau": 0.8,
        "threshold": 0.4,
        "screening_cube_hash": "cube-hash",
        "goal_snapshot_hash": snapshot_hash or revision.goal_snapshot_hash(goal),
        "engine_version": "saa_resampled_v11",
    }
    bands = {
        f"band_{b}_{k}_bps": v
        for b in ("equities", "bonds", "real_estate", "alternatives", "liquidity")
        for k, v in (("min", 0), ("max", 10000))
    }
    allocation = TargetAllocation(
        id=ta_id, mandate_id="m-rcp", version=1, is_current=1,
        target_equities_bps=6000, target_bonds_bps=2000, target_real_estate_bps=1500,
        target_alternatives_bps=300, target_liquidity_bps=200, policy_id="pol",
        set_by="adv-rcp", set_at=NOW, context_artifacts_required=0,
        goal_achievability_json=json.dumps([
            {"goal_id": goal.id, "probability": 0.11, "goal_revision": evidence},
        ]),
        created_at=NOW, updated_at=NOW, **bands,
    )
    session.add(allocation)
    session.commit()
    return allocation


def _post(session, advisor, reason, goal_id="g-far"):
    from routers import wealth as wealth_router
    from schemas.wealth import GoalRevisionDecisionCreate

    return wealth_router.create_goal_revision_decision(
        mandate_id="m-rcp", goal_id=goal_id,
        body=GoalRevisionDecisionCreate(reason=reason),
        db=session, current_user=advisor,
    )


REASON = "Mit dem Kunden besprochen: das Familienvermoegen 2035 ist ein Wunsch, kein Muss."


def test_post_creates_a_verified_append_only_decision_with_engine_evidence(seeded):
    from models.review import AuditLog
    from models.wealth import Goal, GoalRevisionDecision

    session, advisor, _path = seeded
    goal = _db_goal(session)
    _allocation(session, goal)
    view = _post(session, advisor, REASON)
    assert view["active"] is True and view["validity"] == "valid"
    assert view["new_status"] == "nachrangiges_wunschziel"
    row = session.get(GoalRevisionDecision, view["decision_id"])
    assert revision.verify_decision(row)
    assert row.goal_snapshot_hash == revision.goal_snapshot_hash(goal)
    assert json.loads(row.goal_snapshot_json)["target_amount_rappen"] == 5_000_000_00
    assert row.previous_hardness == "Primär"
    assert row.evidence_status == "not_found_reachable_locally"
    assert row.evidence_best_probability_bps == 1660
    assert row.evidence_wilson_upper_bps == 1800
    assert row.evidence_tau_bps == 8000
    assert row.evidence_engine_version == "saa_resampled_v11"
    assert row.evidence_allocation_id == "ta-1"
    assert row.actor_id == advisor.id and row.sequence_no == 1
    audit = session.query(AuditLog).filter(AuditLog.record_id == row.id).one()
    snapshot = json.loads(audit.new_value)
    assert snapshot["decision_hash"] == row.decision_hash
    assert snapshot["goal_snapshot_hash"] == row.goal_snapshot_hash

    # Engine-Seite: geladenes Ziel traegt die Decision, die Liability ist
    # herabgestuft -- bis das Ziel geaendert wird.
    goals = revision.included_goals_with_revisions(session, [session.get(Goal, "g-far")])
    assert revision.valid_revision_decisions(goals) == {
        "g-far": revision.decision_snapshot(row),
    }
    goal_row = session.get(Goal, "g-far")
    goal_row.target_amount_rappen = 4_000_000_00
    session.commit()
    goals = revision.included_goals_with_revisions(session, [goal_row])
    assert revision.valid_revision_decisions(goals) == {}
    listed = __import__("routers.wealth", fromlist=["x"]).list_goal_revision_decisions(
        mandate_id="m-rcp", goal_id="g-far", db=session, current_user=advisor,
    )
    assert [item["validity"] for item in listed] == ["goal_changed"]


@pytest.mark.parametrize("reason,code", [
    ("", "reason_empty"),
    ("zu kurz", "reason_too_short"),
    ("kundenwunsch kundenwunsch kundenwunsch", "reason_generic_phrase"),
    ("1111111111 2222222222 33333", "reason_insufficient_words"),
])
def test_post_rejects_low_quality_reason_before_any_write(seeded, reason, code):
    from models.wealth import GoalRevisionDecision

    session, advisor, _path = seeded
    goal = _db_goal(session)
    _allocation(session, goal)
    with pytest.raises(HTTPException) as exc:
        _post(session, advisor, reason)
    assert exc.value.status_code == 422
    assert exc.value.detail["reason_code"] == code
    assert session.query(GoalRevisionDecision).count() == 0


@pytest.mark.parametrize("setup,code", [
    ("no_allocation", "evidence_missing"),
    ("not_suggested", "not_suggested"),
    ("stale", "evidence_stale"),
])
def test_post_requires_current_engine_suggestion(seeded, setup, code):
    from models.wealth import GoalRevisionDecision

    session, advisor, _path = seeded
    goal = _db_goal(session)
    if setup == "not_suggested":
        _allocation(session, goal, suggested=False)
    elif setup == "stale":
        _allocation(session, goal, snapshot_hash="0" * 64)
    with pytest.raises(HTTPException) as exc:
        _post(session, advisor, REASON)
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == code
    assert session.query(GoalRevisionDecision).count() == 0


def test_second_decision_on_unchanged_goal_is_rejected_new_goal_state_appends(seeded):
    from models.wealth import Goal, GoalRevisionDecision

    session, advisor, _path = seeded
    goal = _db_goal(session)
    _allocation(session, goal)
    first = _post(session, advisor, REASON)
    with pytest.raises(HTTPException) as exc:
        _post(session, advisor, REASON)
    assert exc.value.detail["reason_code"] == "already_active"
    # Ziel geaendert + neu berechnet -> neue Decision verkettet (append-only).
    goal_row = session.get(Goal, "g-far")
    goal_row.target_amount_rappen = 4_000_000_00
    session.commit()
    old = session.get(__import__("models.allocation", fromlist=["x"]).TargetAllocation, "ta-1")
    old.is_current = 0
    session.commit()
    _allocation(session, goal_row, ta_id="ta-2")
    second = _post(session, advisor, REASON)
    row = session.get(GoalRevisionDecision, second["decision_id"])
    assert row.sequence_no == 2 and row.previous_decision_id == first["decision_id"]
    assert row.evidence_allocation_id == "ta-2"


def test_decision_rows_are_immutable(seeded):
    session, advisor, path = seeded
    goal = _db_goal(session)
    _allocation(session, goal)
    _post(session, advisor, REASON)
    with sqlite3.connect(str(path)) as conn:
        for statement in (
            "UPDATE goal_revision_decisions SET reason = 'x'",
            "DELETE FROM goal_revision_decisions",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute(statement)


def test_reduced_stage2_starts_only_change_search_budget_not_protection():
    """Laufzeit (Engine v11): schuetzt Stufe 1 ein lokal nicht gefundenes
    Ziel, bekommt Stufe 2 dasselbe reduzierte Startbudget wie bis v10 bei
    herabgestuften Zielen. Die Schutzklasse bleibt unberuehrt."""
    context = SimpleNamespace(goal_reachability={"revision_suggested_goal_ids": ["far"]})
    assert solver_module._protects_unfound_goal(context, {"protected_goal_ids": ["reach", "far"]})
    assert not solver_module._protects_unfound_goal(context, {"protected_goal_ids": ["reach"]})
    assert not solver_module._protects_unfound_goal(SimpleNamespace(), {"protected_goal_ids": ["far"]})
