"""OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001 (Rest): Zielfunktionswert verlustfrei.

Befund (develop 0610bdde): Der Zielfunktionswert eines Laufs war nur als
milli-Integer persistiert --
``services/portfolio_engine_optimizer_integration.py``
``_optimizer_audit_fields`` (``int(round(value * 1000.0))`` ->
``target_allocations.optimization_objective_value_milli``) und
``_objective_to_milli`` (-> ``optimizer_runs.objective_value_milli``,
Methodenvergleich, Shadow-Container). 0.0006 und 0.0014 (+133 %) wurden beide
zu 1, 0.0001 und 0.0002 beide zu 0. Verlustfrei war nur der Beitrag je Ziel
(Goal-Driver), nicht der Wert selbst.

Fix: Goal-Driver-Snapshot Schema v2 mit ``solver_objective_value``
(Decimal + binary64-Hex, kanonisch, gegengeprueft), exakter Replay und
Bindung der Legacy-milli-Spalten an diesen Wert. v1 bleibt verifizierbar.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services.allocation_evidence_replay import (
    GOAL_DRIVER_EVIDENCE_VERSION,
    GOAL_DRIVER_EVIDENCE_VERSION_V1,
    _bind_legacy_objective_milli,
    build_goal_driver_evidence_json,
    replay_goal_drivers,
)
from services.optimizer.objective_contract import ObjectiveContractV3
from services.portfolio_engine_optimizer_integration import _objective_to_milli
from tests.test_optimizer_phase6 import _seed_mandate, session_factory  # noqa: F401


def _basis() -> dict:
    evidence = ObjectiveContractV3(
        objective_mode="goal_shortfall", goal_weighting_mode="hardness",
    ).as_evidence()
    return {"optimization": {
        "basis_id": "stochastic_shadow_candidate_v2",
        "objective_contract": evidence,
        "objective_contract_version": evidence["objective_contract_version"],
        "objective_contract_hash": evidence["objective_contract_hash"],
    }}


def _snapshot(objective_value, basis=None) -> str:
    return build_goal_driver_evidence_json(
        [], optimizer_mode="stochastic",
        optimizer_result=SimpleNamespace(objective_value=objective_value),
        model_basis=basis or _basis(),
    )


def _replay(snapshot: str, basis=None) -> dict:
    return replay_goal_drivers(snapshot, legacy_shadow_json=None, model_basis=basis or _basis())


@pytest.mark.parametrize("low,high", [(0.0006, 0.0014), (0.0001, 0.0002), (4e-12, 4e-5)])
def test_values_that_collapse_in_milli_stay_distinct_and_exact(low, high):
    # Befund: die Legacy-Skala kollabiert beide Werte.
    assert _objective_to_milli(low) == _objective_to_milli(high)
    basis = _basis()
    first = _replay(_snapshot(low, basis), basis)["evidence"]
    second = _replay(_snapshot(high, basis), basis)["evidence"]
    assert first["status"] == second["status"] == "verified"
    assert first["schema_version"] == GOAL_DRIVER_EVIDENCE_VERSION
    assert float(first["solver_objective_value"]["decimal"]) == low
    assert float(second["solver_objective_value"]["decimal"]) == high
    assert float.fromhex(second["solver_objective_value"]["binary64_hex"]) == high
    true_delta = (high - low) / low * 100.0
    published = (
        float(second["solver_objective_value"]["decimal"])
        - float(first["solver_objective_value"]["decimal"])
    ) / float(first["solver_objective_value"]["decimal"]) * 100.0
    assert published == true_delta


@pytest.mark.parametrize("value", [float("nan"), float("inf"), None])
def test_non_finite_or_missing_objective_is_null_not_zero(value):
    evidence = _replay(_snapshot(value))["evidence"]
    assert evidence["status"] == "verified"
    assert evidence["solver_objective_value"] is None


@pytest.mark.parametrize("mutation", ["decimal", "hex", "both_rehashed", "non_canonical", "shape"])
def test_tampered_objective_value_is_corrupt(mutation):
    import hashlib

    basis = _basis()
    envelope = json.loads(_snapshot(0.0006, basis))
    block = envelope["solver_objective_value"]
    if mutation == "decimal":
        block["decimal"] = "0.0014"
    elif mutation == "hex":
        block["binary64_hex"] = (0.0014).hex()
    elif mutation == "non_canonical":
        block["decimal"] = "6e-4"
    elif mutation == "shape":
        block["extra"] = 1
    else:
        block["decimal"] = "0.0014"
        block["binary64_hex"] = (0.0014).hex()
    if mutation != "both_rehashed":
        envelope["evidence_hash"] = hashlib.sha256(json.dumps(
            {k: v for k, v in envelope.items() if k != "evidence_hash"},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")).hexdigest()
    replay = _replay(json.dumps(envelope), basis)
    assert replay["evidence"]["status"] == "corrupt"


def test_v1_snapshot_still_verifies_without_lossless_value():
    import hashlib

    basis = _basis()
    envelope = json.loads(_snapshot(0.0006, basis))
    envelope.pop("solver_objective_value")
    envelope["schema_version"] = GOAL_DRIVER_EVIDENCE_VERSION_V1
    body = {k: v for k, v in envelope.items() if k != "evidence_hash"}
    envelope["evidence_hash"] = hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    evidence = _replay(json.dumps(envelope), basis)["evidence"]
    assert evidence["status"] == "verified"
    assert evidence["schema_version"] == GOAL_DRIVER_EVIDENCE_VERSION_V1
    assert evidence["solver_objective_value"] is None


def test_legacy_milli_columns_are_bound_to_the_lossless_value():
    basis = _basis()
    replay = _replay(_snapshot(0.0014, basis), basis)
    matching = SimpleNamespace(optimization_objective_value_milli=1)
    run = SimpleNamespace(objective_value_milli=1)
    assert _bind_legacy_objective_milli(replay, matching, run)["evidence"]["status"] == "verified"
    forged_allocation = SimpleNamespace(optimization_objective_value_milli=7)
    assert _bind_legacy_objective_milli(replay, forged_allocation, run)[
        "evidence"]["status"] == "corrupt"
    forged_run = SimpleNamespace(objective_value_milli=0)
    assert _bind_legacy_objective_milli(replay, matching, forged_run)[
        "evidence"]["status"] == "corrupt"
    # Shadow-Modus: keine milli-Spalte -> keine Aussage, kein Fehler.
    empty = SimpleNamespace(optimization_objective_value_milli=None)
    assert _bind_legacy_objective_milli(replay, empty, None)["evidence"]["status"] == "verified"


def test_generate_persists_and_replays_lossless_objective_value(session_factory, monkeypatch):  # noqa: F811
    """Ende-zu-Ende: Generate (stochastic) -> v2-Snapshot verifiziert, Legacy-
    milli-Spalte von Allokation und aktivem Lauf exakt aus dem Wert ableitbar."""
    import services.portfolio_engine as pe
    from models.allocation import OptimizerRun, TargetAllocation
    from models.mandates import Mandate

    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 64)
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = pe.generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        allocation = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid, TargetAllocation.is_current == 1).one()
        run = s.query(OptimizerRun).filter(
            OptimizerRun.id == allocation.optimization_run_id).one()
        evidence = result["optimizer_goal_driver_evidence"]
        assert evidence["status"] == "verified"
        assert evidence["schema_version"] == GOAL_DRIVER_EVIDENCE_VERSION
        value = evidence["solver_objective_value"]
        assert value is not None
        stored = json.loads(allocation.goal_driver_evidence_json)["solver_objective_value"]
        assert stored == value
        expected_milli = _objective_to_milli(float(value["decimal"]))
        assert allocation.optimization_objective_value_milli == expected_milli
        assert run.objective_value_milli == expected_milli
