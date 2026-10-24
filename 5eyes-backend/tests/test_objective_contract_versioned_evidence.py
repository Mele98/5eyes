"""OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001: versionierter, persistierter Vertrag.

Uebernommene unabhaengige Reproducer (ohne xfail, Backend per Struktur):

- Re-Audit 2026-10-14: der Hash bindet die wirksamen Haertegrad-Multiplikatoren;
  Modellbasis und OptimizerRun persistieren Version und Hash.
- Review PR #659 (Restbefund B): ein geaendertes Hashschema traegt eine neue
  Kennung; dazu der dort gruen gefuehrte statische Zeuge.

Danach die Pflichtregressionen: historische V2-Evidence beider Schemas wird
unveraendert als V2 verifiziert, neue Laeufe tragen V3, unbekannt/fehlend/
manipuliert ist fail-closed, Modellbasis und OptimizerRun sind aneinander
gebunden.
"""
from __future__ import annotations

import copy
import inspect
import json
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = next(
    p for p in Path(__file__).resolve().parents
    if (p / "services" / "optimizer" / "objective_contract.py").is_file()
)
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer import objective  # noqa: E402
from services.optimizer.objective_contract import (  # noqa: E402
    ObjectiveContractV1,
    ObjectiveContractV2,
    ObjectiveContractV3,
    ObjectiveContractV4,
    resolve_objective_contract,
    verify_objective_contract_evidence,
)
from services.portfolio_engine_model_basis import (  # noqa: E402
    _build_allocation_model_basis,
)
from services.portfolio_engine_optimizer_integration import (  # noqa: E402
    _persist_optimizer_run,
)

HISTORY = json.loads(
    (BACKEND_ROOT / "tests" / "fixtures" / "objective_contract_v2_history.json")
    .read_text(encoding="utf-8")
)["entries"]


# --------------------------------------------------------------------------
# Reproducer (Re-Audit 2026-10-14)
# --------------------------------------------------------------------------


def test_contract_hash_binds_effective_hardness_multiplier_math(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hash claiming exact mathematics must change when 10x becomes 11x."""
    before = ObjectiveContractV1(
        objective_mode="goal_shortfall",
        goal_weighting_mode="hardness",
    )

    monkeypatch.setitem(objective.HARDNESS_WEIGHT, "hart", 11.0)
    after = ObjectiveContractV1(
        objective_mode="goal_shortfall",
        goal_weighting_mode="hardness",
    )

    assert before.contract_hash != after.contract_hash
    assert before.as_evidence() != after.as_evidence()


def test_productive_persistence_emits_versioned_objective_contract_evidence() -> None:
    """The run/TA evidence graph must persist version, fields and contract hash."""
    model_basis_source = inspect.getsource(_build_allocation_model_basis)
    optimizer_run_source = inspect.getsource(_persist_optimizer_run)

    required_tokens = {
        "objective_contract_version",
        "objective_contract_hash",
    }
    # Uebernahme-Korrektur: der Reproducer schrieb
    # ``required_tokens.difference(source)``. ``set.difference`` iteriert einen
    # String zeichenweise; ein mehrbuchstabiges Token wird so nie entfernt und
    # der Test waere fuer JEDEN Quelltext rot (unerfuellbar). Gemeint ist
    # "Token kommt im Quelltext vor" -- genau das prueft die Mengenbildung.
    missing_from_model_basis = {t for t in required_tokens if t not in model_basis_source}
    missing_from_optimizer_run = {t for t in required_tokens if t not in optimizer_run_source}

    assert not missing_from_model_basis, (
        "allocation model basis omits ObjectiveContract evidence: "
        f"{sorted(missing_from_model_basis)}"
    )
    assert not missing_from_optimizer_run, (
        "OptimizerRun persistence omits ObjectiveContract evidence: "
        f"{sorted(missing_from_optimizer_run)}"
    )


# --------------------------------------------------------------------------
# Reproducer (Review PR #659, Restbefund B + statischer Zeuge)
# --------------------------------------------------------------------------


def test_changed_objective_contract_schema_must_use_a_new_version():
    """A version identifier may not describe two incompatible hash schemas."""
    current = ObjectiveContractV2(
        objective_mode="goal_shortfall",
        goal_weighting_mode="hardness",
    )
    assert current.contract_hash != (
        "78419c3e53c3d9959e69ea1d756738f7ce6d7f1cb0703389ae67c8bea0bcb8eb"
    )
    assert len(current.as_evidence()) == 28

    active = resolve_objective_contract()
    assert active.version != "objective-contract-v2"
    assert type(active) is not ObjectiveContractV2


def test_failure_distribution_is_not_yet_part_of_allocation_integrity_hash():
    """Static witness: the integrity hash has no result parameter (unchanged)."""
    from services.portfolio_engine_allocation_integrity import (
        allocation_context_hash_for,
    )

    parameters = inspect.signature(allocation_context_hash_for).parameters
    assert "goal_achievability" not in parameters
    assert "analysis_result_hash" not in parameters


# --------------------------------------------------------------------------
# Pflichtregressionen
# --------------------------------------------------------------------------


@pytest.mark.parametrize("entry", HISTORY, ids=lambda e: e["evidence"]["objective_contract_hash"][:8])
def test_historical_v2_evidence_replays_as_v2_with_its_own_hash(entry):
    result = verify_objective_contract_evidence(copy.deepcopy(entry["evidence"]))
    assert result["status"] == "verified", result
    assert result["objective_contract_version"] == "objective-contract-v2"
    assert result["objective_contract_hash"] == entry["evidence"]["objective_contract_hash"]


def test_both_v2_schemas_are_distinguished():
    schemas = {
        verify_objective_contract_evidence(e["evidence"])["schema"]: e["evidence"]
        for e in HISTORY
    }
    assert set(schemas) == {"v2_policy_22", "v2_policy_24"}
    base = next(e["evidence"] for e in HISTORY if e["source_commit"] == "61077c041edf"
                and e["evidence"]["goal_weighting_mode"] == "hardness")
    assert base["objective_contract_hash"] == (
        "78419c3e53c3d9959e69ea1d756738f7ce6d7f1cb0703389ae67c8bea0bcb8eb"
    )
    assert len(base) == 26


def test_v2_class_is_unchanged_for_its_current_schema():
    """Die V2-Klasse traegt weiter ihr 24-Felder-Schema und Hashrezept."""
    v2 = ObjectiveContractV2(objective_mode="goal_shortfall", goal_weighting_mode="hardness")
    develop = next(e["evidence"] for e in HISTORY if e["source_commit"] == "5461aa705ec7")
    assert set(v2.as_evidence()) == set(develop)
    result = verify_objective_contract_evidence(v2.as_evidence())
    assert (result["status"], result["schema"]) == ("verified", "v2_policy_24")


def test_new_runs_resolve_v4_and_never_v2_or_v3():
    # Engine v15 (WISH-GOAL-SOFT-TRADEOFF-001): V4; V3 bleibt verifizierbar.
    contract = resolve_objective_contract()
    assert type(contract) is ObjectiveContractV4
    assert type(contract) is not ObjectiveContractV3
    evidence = contract.as_evidence()
    assert evidence["objective_contract_version"] == "objective-contract-v4"
    assert verify_objective_contract_evidence(evidence)["status"] == "verified"
    v2 = ObjectiveContractV2(
        objective_mode=contract.objective_mode,
        goal_weighting_mode=contract.goal_weighting_mode,
    )
    assert contract.contract_hash != v2.contract_hash
    with pytest.raises(Exception):
        ObjectiveContractV3(
            objective_mode="goal_shortfall", goal_weighting_mode="hardness",
            version="objective-contract-v2",
        )


def _v3_evidence() -> dict:
    return ObjectiveContractV3(
        objective_mode="goal_shortfall", goal_weighting_mode="hardness",
    ).as_evidence()


def test_unknown_version_is_blocked():
    evidence = _v3_evidence()
    evidence["objective_contract_version"] = "objective-contract-v9"
    assert verify_objective_contract_evidence(evidence)["status"] == "unknown_version"


@pytest.mark.parametrize("mutation", [
    "drop_field", "extra_field", "tamper_value", "tamper_weight", "tamper_hash",
    "v3_relabelled_as_v2", "bad_mode", "nan_value",
])
def test_tampered_or_incomplete_evidence_is_corrupt(mutation):
    evidence = _v3_evidence()
    if mutation == "drop_field":
        evidence.pop("goal_evaluation_scope")
    elif mutation == "extra_field":
        evidence["new_policy"] = "x"
    elif mutation == "tamper_value":
        evidence["chance_penalty_weight"] = 2.0
    elif mutation == "tamper_weight":
        evidence["hardness_weights"]["hart"] = 11.0
    elif mutation == "tamper_hash":
        evidence["objective_contract_hash"] = "0" * 64
    elif mutation == "v3_relabelled_as_v2":
        evidence["objective_contract_version"] = "objective-contract-v2"
    elif mutation == "bad_mode":
        evidence["objective_mode"] = "no_such_mode"
    elif mutation == "nan_value":
        evidence["goal_erosion_z"] = float("nan")
    assert verify_objective_contract_evidence(evidence)["status"] == "corrupt"


def test_missing_evidence_is_unverifiable_not_current():
    result = verify_objective_contract_evidence(None)
    assert result["status"] == "unverifiable"
    assert result["objective_contract_hash"] is None


def test_v1_evidence_binds_multipliers_and_verifies(monkeypatch):
    v1 = ObjectiveContractV1(objective_mode="goal_shortfall", goal_weighting_mode="hardness")
    evidence = v1.as_evidence()
    assert evidence["hardness_weights"] == {"hart": 10.0, "opportunistisch": 0.2, "primaer": 1.0}
    assert verify_objective_contract_evidence(evidence)["status"] == "verified"
    # Der Vertrag ist eingefroren: eine spaetere Aenderung des Mappings
    # aendert weder den gebauten Vertrag noch seinen Nachweis.
    monkeypatch.setitem(objective.HARDNESS_WEIGHT, "hart", 11.0)
    assert v1.as_evidence() == evidence


def test_json_roundtrip_keeps_hash_verifiable():
    evidence = json.loads(json.dumps(_v3_evidence(), sort_keys=True))
    assert verify_objective_contract_evidence(evidence)["status"] == "verified"


# --------------------------------------------------------------------------
# Bindung Modellbasis <-> OptimizerRun
# --------------------------------------------------------------------------


class _Run:
    def __init__(self, evidence: dict | None):
        self.objective_contract_version = (evidence or {}).get("objective_contract_version")
        self.objective_contract_hash = (evidence or {}).get("objective_contract_hash")
        self.objective_contract_json = json.dumps(evidence) if evidence else None


def _basis(evidence: dict | None) -> dict:
    return {"optimization": {
        "basis_id": "stochastic_decision_v2",
        "objective_contract": evidence,
        "objective_contract_version": (evidence or {}).get("objective_contract_version"),
        "objective_contract_hash": (evidence or {}).get("objective_contract_hash"),
    }}


def test_model_basis_and_run_with_same_contract_are_bound():
    from services.allocation_evidence_replay import objective_contract_replay

    evidence = _v3_evidence()
    result = objective_contract_replay(_basis(evidence), _Run(evidence))
    assert result["status"] == "verified"
    assert result["optimizer_run_bound"] is True


def test_run_with_another_contract_blocks():
    from services.allocation_evidence_replay import objective_contract_replay

    evidence = _v3_evidence()
    other = ObjectiveContractV3(
        objective_mode="goal_shortfall", goal_weighting_mode="equal",
    ).as_evidence()
    assert objective_contract_replay(_basis(evidence), _Run(other))["status"] == "corrupt"


def test_flat_basis_anchor_must_match_block():
    from services.allocation_evidence_replay import objective_contract_replay

    basis = _basis(_v3_evidence())
    basis["optimization"]["objective_contract_hash"] = "f" * 64
    assert objective_contract_replay(basis, None)["status"] == "corrupt"


def test_legacy_basis_states():
    from services.allocation_evidence_replay import objective_contract_replay

    # Bestand ohne jeden Vertragsnachweis.
    assert objective_contract_replay({"optimization": {"basis_id": "x"}}, None)["status"] == (
        "unverifiable"
    )
    # Moderne Basis ohne Solver-Lauf.
    assert objective_contract_replay(_basis(None), None)["status"] == "not_applicable"
    # Aeltere stochastische Basis: V2 nur im Resampling-Audit -> als V2 verifiziert.
    legacy = {"optimization": {"resampling": {"objective_contract": HISTORY[2]["evidence"]}}}
    result = objective_contract_replay(legacy, None)
    assert result["status"] == "verified"
    assert result["source"] == "model_basis_resampling"
    assert result["objective_contract_version"] == "objective-contract-v2"
