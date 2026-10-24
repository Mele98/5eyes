"""OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001: Goal-Driver-Evidenz persistiert und abspielbar.

Uebernommener unabhaengiger Reproducer (Re-Audit 2026-10-14, ohne xfail,
Backend per Struktur), danach die Pflichtregressionen des Reviews:
Decimal/Hex atomar, gehashter Snapshot, typisierte Zustaende statt still
``[]``, Bindung an den Objective-Vertrag, Rangpruefung.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = next(
    p for p in Path(__file__).resolve().parents
    if (p / "schemas" / "allocation.py").is_file()
)
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from schemas.allocation import OptimizerGoalDriverResponse  # noqa: E402
from services.allocation_evidence_replay import (  # noqa: E402
    build_goal_driver_evidence_json,
    replay_goal_drivers,
)
from services.optimizer.objective_contract import ObjectiveContractV3  # noqa: E402
from services.portfolio_engine import build_target_payload_from_allocation  # noqa: E402


def _driver(**overrides) -> dict:
    payload = {
        "goal_id": "goal-a",
        "label": "Goal A",
        "target_kind": "wealth_at_t",
        "hardness_key": "hart",
        "weight_bps": 5000,
        "weighted_objective_contribution_milli": 0,
        "weighted_objective_contribution_decimal": "0.1",
        "weighted_objective_contribution_binary64_hex": float(0.1).hex(),
        "rank": 1,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Reproducer
# --------------------------------------------------------------------------


def test_decimal_and_binary64_goal_driver_evidence_must_agree() -> None:
    """Two contradictory 'lossless' values must be rejected at the API schema."""
    with pytest.raises(ValidationError):
        OptimizerGoalDriverResponse(
            **_driver(
                weighted_objective_contribution_decimal="0.1",
                weighted_objective_contribution_binary64_hex=float(0.2).hex(),
            )
        )


def test_current_allocation_reload_restores_persisted_goal_driver_evidence() -> None:
    """A reload must consume the stored drivers instead of returning []."""
    source = inspect.getsource(build_target_payload_from_allocation)

    assert "shadow_optimization_json" in source, (
        "reload path never reads the persisted optimizer evidence container"
    )
    assert "optimizer_goal_drivers" in source, (
        "reload path does not return persisted lossless goal-driver evidence"
    )


# --------------------------------------------------------------------------
# Decimal/Hex-Paar
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", [0.0, 4e-12, 4e-5, 0.00049, 5e-324, -1.25, 1e300])
def test_bit_identical_pair_is_accepted(value):
    row = OptimizerGoalDriverResponse(**_driver(
        weighted_objective_contribution_decimal=repr(value),
        weighted_objective_contribution_binary64_hex=value.hex(),
    ))
    assert float.fromhex(row.weighted_objective_contribution_binary64_hex) == value


def test_unavailable_pair_is_accepted_and_distinct_from_zero():
    row = OptimizerGoalDriverResponse(**_driver(
        weighted_objective_contribution_decimal=None,
        weighted_objective_contribution_binary64_hex=None,
    ))
    assert row.weighted_objective_contribution_decimal is None


@pytest.mark.parametrize("decimal_text, hex_text", [
    ("0.1", None),                      # nur eine Haelfte
    (None, float(0.1).hex()),
    ("nan", float("nan").hex()),        # nicht endlich
    ("inf", float("inf").hex()),
    ("0.10", float(0.1).hex()),         # nicht kanonisch
    ("abc", "0x1p-3"),                  # unparsebar
    ("-0.0", float(0.0).hex()),         # Vorzeichen zaehlt
    ("0.0", float(-0.0).hex()),
])
def test_incomplete_non_finite_non_canonical_or_signed_pairs_are_rejected(decimal_text, hex_text):
    with pytest.raises(ValidationError):
        OptimizerGoalDriverResponse(**_driver(
            weighted_objective_contribution_decimal=decimal_text,
            weighted_objective_contribution_binary64_hex=hex_text,
        ))


# --------------------------------------------------------------------------
# Snapshot und Replay
# --------------------------------------------------------------------------


def _contract_basis(basis_id: str = "stochastic_shadow_candidate_v2") -> dict:
    evidence = ObjectiveContractV3(
        objective_mode="goal_shortfall", goal_weighting_mode="hardness",
    ).as_evidence()
    return {"optimization": {
        "basis_id": basis_id,
        "objective_contract": evidence,
        "objective_contract_version": evidence["objective_contract_version"],
        "objective_contract_hash": evidence["objective_contract_hash"],
    }}


def _drivers() -> list[dict]:
    return [
        _driver(goal_id="a", rank=1, weighted_objective_contribution_decimal="0.00049",
                weighted_objective_contribution_binary64_hex=(0.00049).hex()),
        _driver(goal_id="b", rank=2, weighted_objective_contribution_decimal="4e-12",
                weighted_objective_contribution_binary64_hex=(4e-12).hex()),
        _driver(goal_id="c", rank=3, weighted_objective_contribution_decimal="0.0",
                weighted_objective_contribution_binary64_hex=(0.0).hex()),
    ]


def _snapshot(drivers=None, basis=None) -> str:
    return build_goal_driver_evidence_json(
        _drivers() if drivers is None else drivers,
        optimizer_mode="shadow_stochastic", optimizer_result=object(),
        model_basis=basis or _contract_basis(),
    )


def test_snapshot_roundtrip_replays_identical_drivers_and_hash():
    basis = _contract_basis()
    snapshot = _snapshot(basis=basis)
    first = replay_goal_drivers(snapshot, legacy_shadow_json=None, model_basis=basis)
    second = replay_goal_drivers(snapshot, legacy_shadow_json=None, model_basis=basis)
    assert first["evidence"]["status"] == "verified"
    assert first == second
    assert [d["goal_id"] for d in first["drivers"]] == ["a", "b", "c"]
    assert [d["weighted_objective_contribution_decimal"] for d in first["drivers"]] == [
        "0.00049", "4e-12", "0.0",
    ]
    assert first["evidence"]["evidence_hash"] == json.loads(snapshot)["evidence_hash"]
    assert first["evidence"]["objective_contract_hash"] == (
        basis["optimization"]["objective_contract_hash"]
    )


def test_true_empty_driver_list_is_verified_not_unavailable():
    basis = _contract_basis()
    replay = replay_goal_drivers(_snapshot(drivers=[], basis=basis),
                                 legacy_shadow_json=None, model_basis=basis)
    assert replay["evidence"]["status"] == "verified"
    assert replay["drivers"] == []


def test_no_snapshot_without_solver_run():
    assert build_goal_driver_evidence_json(
        _drivers(), optimizer_mode="house_matrix", optimizer_result=None,
        model_basis=_contract_basis(),
    ) is None


@pytest.mark.parametrize("mutation", [
    "decimal", "hex_and_decimal", "rank", "hash", "version", "contract", "extra_key", "not_json",
])
def test_tampered_snapshot_is_corrupt_without_fallback(mutation):
    basis = _contract_basis()
    envelope = json.loads(_snapshot(basis=basis))
    if mutation == "decimal":
        envelope["drivers"][0]["weighted_objective_contribution_decimal"] = "0.0005"
    elif mutation == "hex_and_decimal":
        envelope["drivers"][0]["weighted_objective_contribution_decimal"] = "0.0005"
        envelope["drivers"][0]["weighted_objective_contribution_binary64_hex"] = (0.0005).hex()
    elif mutation == "rank":
        envelope["drivers"][1]["rank"] = 1
    elif mutation == "hash":
        envelope["evidence_hash"] = "0" * 64
    elif mutation == "version":
        envelope["schema_version"] = "optimizer-goal-driver-evidence-v9"
    elif mutation == "contract":
        envelope["objective_contract_hash"] = "e" * 64
    elif mutation == "extra_key":
        envelope["note"] = "x"
    text = "{not json" if mutation == "not_json" else json.dumps(envelope)
    replay = replay_goal_drivers(
        text, legacy_shadow_json=json.dumps({"goal_drivers": _drivers()}), model_basis=basis,
    )
    assert replay["evidence"]["status"] == "corrupt"
    assert replay["drivers"] == []


def test_snapshot_bound_to_another_contract_is_corrupt():
    snapshot = _snapshot(basis=_contract_basis())
    other = ObjectiveContractV3(
        objective_mode="goal_shortfall", goal_weighting_mode="equal",
    ).as_evidence()
    basis = {"optimization": {
        "basis_id": "stochastic_shadow_candidate_v2",
        "objective_contract": other,
        "objective_contract_version": other["objective_contract_version"],
        "objective_contract_hash": other["objective_contract_hash"],
    }}
    assert replay_goal_drivers(snapshot, legacy_shadow_json=None, model_basis=basis)[
        "evidence"]["status"] == "corrupt"


def test_ranking_contradicting_raw_values_is_rejected_at_build():
    drivers = _drivers()
    drivers[0], drivers[1] = dict(drivers[1], rank=1), dict(drivers[0], rank=2)
    with pytest.raises(ValueError):
        _snapshot(drivers=drivers)


def test_legacy_states_are_discriminated():
    legacy_shadow = json.dumps({"goal_drivers": _drivers()})
    legacy = replay_goal_drivers(None, legacy_shadow_json=legacy_shadow,
                                 model_basis={"optimization": {"basis_id": "stochastic_shadow_candidate_v2"}})
    assert legacy["evidence"]["status"] == "unverifiable"
    assert legacy["evidence"]["source"] == "shadow_optimization_json"
    assert [d["goal_id"] for d in legacy["drivers"]] == ["a", "b", "c"]

    unavailable = replay_goal_drivers(None, legacy_shadow_json=None,
                                      model_basis={"optimization": {"basis_id": "stochastic_decision_v2"}})
    assert unavailable["evidence"]["status"] == "unavailable"
    assert unavailable["drivers"] == []

    house = replay_goal_drivers(None, legacy_shadow_json=None,
                                model_basis={"optimization": {"basis_id": "house_matrix_policy_v1"}})
    assert house["evidence"]["status"] == "not_applicable"

    bad = json.dumps({"goal_drivers": [_driver(weighted_objective_contribution_binary64_hex=(0.2).hex())]})
    assert replay_goal_drivers(None, legacy_shadow_json=bad,
                               model_basis={"optimization": {}})["evidence"]["status"] == "corrupt"
