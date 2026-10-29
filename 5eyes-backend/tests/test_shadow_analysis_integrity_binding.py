"""SHADOW-ANALYSIS-INTEGRITY-001: Shadow-Container im Integritaetsnachweis.

Folgepunkt zu GOAL-ANALYSIS-INTEGRITY-001 (#793): Im Modus
``shadow_stochastic`` liegt die Zielerreichung des stochastischen
Kandidaten (``achievability``) samt Goal-Drivern und Gewichten in
``TargetAllocation.shadow_optimization_json``. Diese Spalte lag ausserhalb
des ``allocation_context_hash``; Shadow-Vergleich und Ziel-Revision lasen sie
ungeprueft.

Vertrag: Generate bindet den SHA-256 der exakt persistierten Bytes als
``ShadowAnalysisSnapshotV1``-Referenz in ``effective_constraints`` (damit im
Context-Hash; die Hash-Form bleibt). Bestand ohne Referenz verifiziert
unveraendert (``legacy_unbound``). Manipulation -> Gate schlaegt fehl, der
Shadow-Vergleich liefert keinen Kandidaten, die Ziel-Revision keine Evidenz.

Dazu der Lesefehler der Ziel-Revision: sie las ``goal_achievability`` aus dem
Shadow-Container, der Schluessel heisst dort ``achievability`` -- die
Shadow-Evidenz kam nie an.
"""
from __future__ import annotations

import hashlib
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
    return {
        "targets": {b: int(getattr(allocation, f"target_{b}_bps")) for b in BUCKETS},
        "minimums": {b: int(getattr(allocation, f"band_{b}_min_bps") or 0) for b in BUCKETS},
        "maximums": {b: int(getattr(allocation, f"band_{b}_max_bps") or 0) for b in BUCKETS},
    }


def _verify(allocation):
    return _verified_persisted_allocation_context(allocation, **_bounds(allocation))


@pytest.fixture()
def generated(session_factory, monkeypatch):  # noqa: F811
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 64)
    advisor_id, _cid, mid, _aid, goal_id = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        allocation = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid, TargetAllocation.is_current == 1).one()
        assert allocation.shadow_optimization_json, "Fixture braucht einen Shadow-Container"
        return session_factory, allocation.id, mid, goal_id, advisor_id


def _load(session_factory, allocation_id):
    with session_factory() as s:
        return s.query(TargetAllocation).filter(TargetAllocation.id == allocation_id).one()


def _rewrite(session_factory, allocation_id, **columns):
    with session_factory() as s:
        row = s.query(TargetAllocation).filter(TargetAllocation.id == allocation_id).one()
        for key, value in columns.items():
            setattr(row, key, value)
        s.commit()


def _tampered_shadow(raw: str) -> str:
    shadow = json.loads(raw)
    rows = shadow.get("achievability") or []
    if rows:
        rows[0]["probability"] = 0.999
        rows[0]["status"] = "erreichbar"
    else:
        shadow["achievability"] = [{"goal_id": "x", "probability": 0.999}]
    return json.dumps(shadow, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def test_generate_binds_shadow_container_into_context(generated):
    session_factory, allocation_id, *_ = generated
    allocation = _load(session_factory, allocation_id)
    reference = json.loads(allocation.effective_constraints_json).get("shadow_analysis_snapshot")
    assert isinstance(reference, dict), "Shadow-Container ist nicht im Context gebunden"
    assert reference == {
        "version": "shadow_analysis_snapshot_v1",
        "hash": hashlib.sha256(allocation.shadow_optimization_json.encode("utf-8")).hexdigest(),
    }
    _sub, verified = _verify(allocation)
    assert verified is not None


def test_tampered_shadow_achievability_fails_verification(generated):
    session_factory, allocation_id, *_ = generated
    allocation = _load(session_factory, allocation_id)
    _rewrite(session_factory, allocation_id,
             shadow_optimization_json=_tampered_shadow(allocation.shadow_optimization_json))
    with pytest.raises(ValueError, match="Shadow"):
        _verify(_load(session_factory, allocation_id))


def test_tampered_shadow_reference_breaks_context_hash(generated):
    session_factory, allocation_id, *_ = generated
    allocation = _load(session_factory, allocation_id)
    tampered = _tampered_shadow(allocation.shadow_optimization_json)
    constraints = json.loads(allocation.effective_constraints_json)
    constraints["shadow_analysis_snapshot"]["hash"] = hashlib.sha256(
        tampered.encode("utf-8")).hexdigest()
    _rewrite(session_factory, allocation_id, shadow_optimization_json=tampered,
             effective_constraints_json=json.dumps(
                 constraints, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    with pytest.raises(ValueError, match="Allocation-Context-Hash"):
        _verify(_load(session_factory, allocation_id))


def test_shadow_comparison_refuses_tampered_container(generated):
    from services.shadow_comparison import (
        ShadowComparisonMissing,
        build_shadow_comparison_payload,
    )

    session_factory, allocation_id, mid, *_ = generated
    with session_factory() as s:
        assert build_shadow_comparison_payload(s, mid)["target_allocation_id"] == allocation_id
    allocation = _load(session_factory, allocation_id)
    _rewrite(session_factory, allocation_id,
             shadow_optimization_json=_tampered_shadow(allocation.shadow_optimization_json))
    with session_factory() as s:
        with pytest.raises(ShadowComparisonMissing, match="Integrit"):
            build_shadow_comparison_payload(s, mid)


def test_goal_revision_reads_bound_shadow_achievability(generated):
    from services.goal_revision_decision import engine_evidence_for_goal

    session_factory, allocation_id, _mid, goal_id, _adv = generated
    allocation = _load(session_factory, allocation_id)
    shadow = json.loads(allocation.shadow_optimization_json)
    rows = shadow.get("achievability") or []
    # Kontrolle mit eindeutiger Evidenz nur im Shadow-Container (Schluessel
    # ``achievability``), gebunden durch neue Referenz + Context-Hash.
    marker = {"source": "shadow-only-marker"}
    rows = [dict(r) for r in rows] or [{"goal_id": goal_id}]
    for row in rows:
        if str(row.get("goal_id")) == str(goal_id):
            row["goal_revision"] = marker
    if not any(str(r.get("goal_id")) == str(goal_id) for r in rows):
        rows.append({"goal_id": goal_id, "goal_revision": marker})
    shadow["achievability"] = rows
    raw = json.dumps(shadow, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    constraints = json.loads(allocation.effective_constraints_json)
    constraints["shadow_analysis_snapshot"]["hash"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    from services.goal_analysis_snapshot import bound_analysis_result_hash

    context_hash = allocation_context_hash_for(
        engine_version=constraints["engine_version"], policy_id=allocation.policy_id,
        cma_id=allocation.capital_market_assumptions_id,
        assessment_id=allocation.based_on_assessment_id,
        input_snapshot_hash=allocation.input_snapshot_hash,
        preferences_json=allocation.preferences_json, targets=_bounds(allocation)["targets"],
        sub_allocations=json.loads(allocation.sub_allocations_json),
        effective_constraints=constraints, optimization_seed=allocation.optimization_seed,
        analysis_result_hash=bound_analysis_result_hash(constraints),
    )
    _rewrite(session_factory, allocation_id, shadow_optimization_json=raw,
             effective_constraints_json=json.dumps(
                 constraints, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
             allocation_context_hash=context_hash)
    rebound = _load(session_factory, allocation_id)
    if rebound.goal_achievability_json:
        # Die aktive Zielanalyse darf die Shadow-Evidenz nicht verdecken.
        _rewrite(session_factory, allocation_id, goal_achievability_json=None)
        rebound = _load(session_factory, allocation_id)
    assert engine_evidence_for_goal(rebound, goal_id) == marker
    _rewrite(session_factory, allocation_id, shadow_optimization_json=_tampered_shadow(raw))
    assert engine_evidence_for_goal(_load(session_factory, allocation_id), goal_id) is None


def test_legacy_allocation_without_shadow_reference_still_verifies(generated):
    from services.goal_analysis_snapshot import bound_analysis_result_hash, shadow_analysis_status

    session_factory, allocation_id, *_ = generated
    allocation = _load(session_factory, allocation_id)
    constraints = json.loads(allocation.effective_constraints_json)
    constraints.pop("shadow_analysis_snapshot")
    legacy_hash = allocation_context_hash_for(
        engine_version=constraints["engine_version"], policy_id=allocation.policy_id,
        cma_id=allocation.capital_market_assumptions_id,
        assessment_id=allocation.based_on_assessment_id,
        input_snapshot_hash=allocation.input_snapshot_hash,
        preferences_json=allocation.preferences_json, targets=_bounds(allocation)["targets"],
        sub_allocations=json.loads(allocation.sub_allocations_json),
        effective_constraints=constraints, optimization_seed=allocation.optimization_seed,
        analysis_result_hash=bound_analysis_result_hash(constraints),
    )
    _rewrite(session_factory, allocation_id,
             effective_constraints_json=json.dumps(
                 constraints, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
             allocation_context_hash=legacy_hash)
    reloaded = _load(session_factory, allocation_id)
    _sub, verified = _verify(reloaded)
    assert verified is not None
    assert shadow_analysis_status(reloaded, verified) == "legacy_unbound"


def test_tampered_methodology_is_still_rejected_by_readers(generated):
    """Die Leser rufen das volle semantische Gate: eine manipulierte Methodik
    (Methodenspalte widerspricht der gehashten Modellbasis) blendet Zielanalyse
    und Shadow-Container aus, obwohl deren Bytes unveraendert sind."""
    from services.goal_analysis_snapshot import (
        analysis_integrity_report,
        bound_goal_achievability_json,
        bound_shadow_optimization_json,
    )

    session_factory, allocation_id, *_ = generated
    intact = _load(session_factory, allocation_id)
    assert bound_shadow_optimization_json(intact) == intact.shadow_optimization_json
    _rewrite(session_factory, allocation_id, optimization_method="stochastic",
             optimization_status="converged")
    tampered = _load(session_factory, allocation_id)
    with pytest.raises(ValueError):
        _verify(tampered)
    assert bound_shadow_optimization_json(tampered) is None
    if tampered.goal_achievability_json:
        assert bound_goal_achievability_json(tampered) is None
    report = analysis_integrity_report(tampered)
    assert report["shadow_analysis"] == "integrity_mismatch"
    assert report["needs_attention"] is True


def test_lifecycle_invalidation_clears_shadow_container(generated):
    from services.goal_analysis_snapshot import analysis_integrity_report
    from services.goal_lifecycle_transitions import invalidate_goal_achievability_evidence
    from services.shadow_comparison import (
        ShadowComparisonMissing,
        build_shadow_comparison_payload,
    )

    session_factory, allocation_id, mid, *_ = generated
    with session_factory() as s:
        assert invalidate_goal_achievability_evidence(s, mid) == 1
        s.commit()
    allocation = _load(session_factory, allocation_id)
    assert allocation.shadow_optimization_json is None
    _sub, verified = _verify(allocation)
    assert verified is not None
    report = analysis_integrity_report(allocation)
    assert report["shadow_analysis"] == "invalidated"
    assert report["needs_attention"] is False
    with session_factory() as s:
        with pytest.raises(ShadowComparisonMissing):
            build_shadow_comparison_payload(s, mid)


# --------------------------------------------------------------------------
# Status-Endpunkt fuer den ruhigen UI-Hinweis
# --------------------------------------------------------------------------


def _client(session_factory, user):
    from fastapi.testclient import TestClient

    from database import get_db
    from main import app
    from services.auth import get_current_user, require_advisor

    def override_db():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_advisor] = lambda: user
    return TestClient(app), app


def _advisor(session_factory, advisor_id):
    from models.users import User

    with session_factory() as s:
        return s.query(User).filter(User.id == advisor_id).one()


def test_integrity_endpoint_reports_verified_then_mismatch(generated):
    session_factory, allocation_id, mid, _goal, advisor_id = generated
    client, app = _client(session_factory, _advisor(session_factory, advisor_id))
    try:
        url = f"/mandates/{mid}/target-allocation/current/analysis-integrity"
        intact = client.get(url)
        assert intact.status_code == 200, intact.text
        body = intact.json()
        assert body["target_allocation_id"] == allocation_id
        assert body["shadow_analysis"] == "verified"
        assert body["needs_attention"] is False
        allocation = _load(session_factory, allocation_id)
        _rewrite(session_factory, allocation_id,
                 shadow_optimization_json=_tampered_shadow(allocation.shadow_optimization_json))
        tampered = client.get(url).json()
        assert tampered["shadow_analysis"] == "integrity_mismatch"
        assert tampered["needs_attention"] is True
        assert tampered["label"]
        assert "neu berechnen" in tampered["text"]
    finally:
        app.dependency_overrides.clear()


def test_integrity_endpoint_without_allocation_is_404(session_factory):  # noqa: F811
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    client, app = _client(session_factory, _advisor(session_factory, advisor_id))
    try:
        response = client.get(f"/mandates/{mid}/target-allocation/current/analysis-integrity")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
