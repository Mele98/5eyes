"""GOAL-ANALYSIS-INTEGRITY-001: Zielanalyse (inkl. Ursachenverteilung) im Integritaetshash.

Codex-Zeuge zu PR #659 (``test_failure_distribution_is_not_yet_part_of_
allocation_integrity_hash``): Der ``allocation_context_hash`` hatte keinen
Ergebnis-Parameter. Die persistierte Zielanalyse
(``TargetAllocation.goal_achievability_json`` mit Wahrscheinlichkeit, Status
und ``failure_event_distribution`` je Ziel) liess sich deshalb aendern, ohne
dass irgendein Verifier es bemerkte.

Vertrag:

* Generate bindet den SHA-256 der exakt persistierten Zielanalyse als
  ``GoalAnalysisSnapshotV1``-Referenz in ``effective_constraints`` und als
  expliziten ``analysis_result_hash`` in den Context-Hash (Hash-Form v2).
* Bestand ohne Referenz verifiziert unveraendert mit der v1-Form; es wird
  nichts nachtraeglich umgehasht.
* Manipulation der Zielanalyse -> Integritaets-Gate schlaegt fehl, und die
  lesenden Kanaele publizieren keine Zielzeilen.
* Die Lifecycle-Invalidierung (NULL) bleibt erlaubt und gilt als
  ``invalidated``, nicht als Manipulation.
"""
from __future__ import annotations

import hashlib
import inspect
import json

import pytest

import services.portfolio_engine as pe
from models.allocation import TargetAllocation
from models.mandates import Mandate
from services.portfolio_engine import generate_target_allocation
from services.portfolio_engine_allocation_integrity import (
    _verified_persisted_allocation_context,
    allocation_context_hash_for,
)
from tests.test_optimizer_phase6 import _seed_mandate, session_factory  # noqa: F401

BUCKETS = ("equities", "bonds", "real_estate", "alternatives", "liquidity")


def _bounds(allocation):
    targets = {b: int(getattr(allocation, f"target_{b}_bps")) for b in BUCKETS}
    minimums = {b: int(getattr(allocation, f"band_{b}_min_bps") or 0) for b in BUCKETS}
    maximums = {b: int(getattr(allocation, f"band_{b}_max_bps") or 0) for b in BUCKETS}
    return {"targets": targets, "minimums": minimums, "maximums": maximums}


def _verify(allocation):
    return _verified_persisted_allocation_context(allocation, **_bounds(allocation))


@pytest.fixture()
def generated(session_factory, monkeypatch):  # noqa: F811
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 64)
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        allocation = (
            s.query(TargetAllocation)
            .filter(TargetAllocation.mandate_id == mid, TargetAllocation.is_current == 1)
            .one()
        )
        assert allocation.goal_achievability_json, "Fixture braucht eine Zielanalyse"
        return session_factory, allocation.id


def _load(session_factory, allocation_id):
    with session_factory() as s:
        return s.query(TargetAllocation).filter(TargetAllocation.id == allocation_id).one()


def _rewrite(session_factory, allocation_id, **columns):
    with session_factory() as s:
        row = s.query(TargetAllocation).filter(TargetAllocation.id == allocation_id).one()
        for key, value in columns.items():
            setattr(row, key, value)
        s.commit()


def _tampered_goal_analysis(raw: str) -> str:
    rows = json.loads(raw)
    target = next(
        (row for row in rows if row.get("failure_event_distribution")),
        rows[0],
    )
    if target.get("failure_event_distribution"):
        # Ursachenverteilung umschreiben (Anteile vertauschen bzw. Event umbenennen).
        dist = target["failure_event_distribution"]
        dist[0] = dict(dist[0], event_id="manipulated_event")
    else:
        target["probability"] = 0.999
        target["failure_event_distribution"] = [
            {"event_id": "manipulated_event", "share": 1.0}
        ]
    return json.dumps(rows, separators=(",", ":"), ensure_ascii=False)


def test_generate_binds_goal_analysis_hash_into_context(generated):
    session_factory, allocation_id = generated
    allocation = _load(session_factory, allocation_id)
    constraints = json.loads(allocation.effective_constraints_json)
    reference = constraints.get("goal_analysis_snapshot")
    assert isinstance(reference, dict), "Zielanalyse ist nicht im Context gebunden"
    assert reference["version"] == "goal_analysis_snapshot_v1"
    assert reference["hash"] == hashlib.sha256(
        allocation.goal_achievability_json.encode("utf-8")
    ).hexdigest()
    sub_allocations, verified = _verify(allocation)
    assert verified is not None and sub_allocations


def test_tampered_cause_distribution_fails_verification(generated):
    session_factory, allocation_id = generated
    allocation = _load(session_factory, allocation_id)
    _rewrite(
        session_factory, allocation_id,
        goal_achievability_json=_tampered_goal_analysis(allocation.goal_achievability_json),
    )
    with pytest.raises(ValueError, match="Zielanalyse"):
        _verify(_load(session_factory, allocation_id))


def test_tampered_reference_breaks_context_hash(generated):
    session_factory, allocation_id = generated
    allocation = _load(session_factory, allocation_id)
    tampered_rows = _tampered_goal_analysis(allocation.goal_achievability_json)
    constraints = json.loads(allocation.effective_constraints_json)
    constraints["goal_analysis_snapshot"]["hash"] = hashlib.sha256(
        tampered_rows.encode("utf-8")
    ).hexdigest()
    _rewrite(
        session_factory, allocation_id,
        goal_achievability_json=tampered_rows,
        effective_constraints_json=json.dumps(
            constraints, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ),
    )
    with pytest.raises(ValueError, match="Allocation-Context-Hash"):
        _verify(_load(session_factory, allocation_id))


def test_tampered_goal_analysis_is_not_published_by_readers(generated):
    from services.advisory_report import _load_goal_achievability_view
    from services.goal_analysis_snapshot import bound_goal_achievability_json
    from services.portfolio_engine_payload import _stored_goal_achievability

    session_factory, allocation_id = generated
    intact = _load(session_factory, allocation_id)
    assert bound_goal_achievability_json(intact) == intact.goal_achievability_json
    assert _stored_goal_achievability(intact)
    _rewrite(
        session_factory, allocation_id,
        goal_achievability_json=_tampered_goal_analysis(intact.goal_achievability_json),
    )
    tampered = _load(session_factory, allocation_id)
    assert bound_goal_achievability_json(tampered) is None
    assert _load_goal_achievability_view(tampered) == ([], None)
    assert _stored_goal_achievability(tampered) == []


def test_lifecycle_invalidation_is_not_an_integrity_error(generated):
    from services.goal_analysis_snapshot import goal_analysis_status
    from services.goal_lifecycle_transitions import invalidate_goal_achievability_evidence

    session_factory, allocation_id = generated
    with session_factory() as s:
        mandate_id = s.query(TargetAllocation).filter(
            TargetAllocation.id == allocation_id).one().mandate_id
        assert invalidate_goal_achievability_evidence(s, mandate_id) == 1
        s.commit()
    allocation = _load(session_factory, allocation_id)
    assert allocation.goal_achievability_json is None
    _sub, verified = _verify(allocation)
    assert verified is not None
    assert goal_analysis_status(allocation, verified) == "invalidated"


def test_legacy_context_without_reference_keeps_v1_hash():
    """Bestand: ohne Ergebnis-Hash bleibt die Hash-Form byte-gleich (pinned)."""
    legacy = allocation_context_hash_for(
        engine_version="stochastic_core_v2", policy_id="pol", cma_id="cma",
        assessment_id="ass", input_snapshot_hash="inp", preferences_json=None,
        targets={"equities": 4000, "bonds": 3000, "real_estate": 0,
                 "alternatives": 1000, "liquidity": 2000},
        sub_allocations=[{"asset_class": "Aktien", "target_weight_bps": 4000}],
        effective_constraints={"engine_version": "stochastic_core_v2"},
        optimization_seed=7,
    )
    # Wert auf develop 0610bdde vor dieser Aenderung berechnet.
    assert legacy == "0ee57d503728074212b08d354a4af54ad4dea19bd3143583911e4af4cf5fdd33"
    bound = allocation_context_hash_for(
        engine_version="stochastic_core_v2", policy_id="pol", cma_id="cma",
        assessment_id="ass", input_snapshot_hash="inp", preferences_json=None,
        targets={"equities": 4000, "bonds": 3000, "real_estate": 0,
                 "alternatives": 1000, "liquidity": 2000},
        sub_allocations=[{"asset_class": "Aktien", "target_weight_bps": 4000}],
        effective_constraints={"engine_version": "stochastic_core_v2"},
        optimization_seed=7,
        analysis_result_hash="a" * 64,
    )
    assert bound != legacy


def test_legacy_allocation_without_reference_still_verifies(generated):
    """Ein Datensatz ohne Referenz (Bestand) verifiziert mit der v1-Form und
    wird nicht umgehasht; seine Zielanalyse gilt als ``legacy_unbound``."""
    from services.goal_analysis_snapshot import goal_analysis_status

    session_factory, allocation_id = generated
    allocation = _load(session_factory, allocation_id)
    constraints = json.loads(allocation.effective_constraints_json)
    constraints.pop("goal_analysis_snapshot")
    sub_allocations = json.loads(allocation.sub_allocations_json)
    legacy_hash = allocation_context_hash_for(
        engine_version=constraints["engine_version"],
        policy_id=allocation.policy_id,
        cma_id=allocation.capital_market_assumptions_id,
        assessment_id=allocation.based_on_assessment_id,
        input_snapshot_hash=allocation.input_snapshot_hash,
        preferences_json=allocation.preferences_json,
        targets=_bounds(allocation)["targets"],
        sub_allocations=sub_allocations,
        effective_constraints=constraints,
        optimization_seed=allocation.optimization_seed,
    )
    _rewrite(
        session_factory, allocation_id,
        effective_constraints_json=json.dumps(
            constraints, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ),
        allocation_context_hash=legacy_hash,
    )
    reloaded = _load(session_factory, allocation_id)
    _sub, verified = _verify(reloaded)
    assert verified is not None
    assert reloaded.allocation_context_hash == legacy_hash
    assert goal_analysis_status(reloaded, verified) == "legacy_unbound"


def test_context_hash_has_explicit_versioned_result_parameter():
    """Uebernommener Codex-Zeuge (PR #659), jetzt als Closure-Vertrag."""
    parameters = inspect.signature(allocation_context_hash_for).parameters
    assert "analysis_result_hash" in parameters
