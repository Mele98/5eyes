"""Generate und Reload liefern dieselbe persistierte Optimizer-Evidenz.

OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001 / OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001:
Goal-Driver (Werte, Reihenfolge, Snapshot-Hash) und Objective-Vertrag
(Version, Hash) muessen nach einem Reload identisch zum Generate sein und
aus der Persistenz stammen -- nicht aus der heutigen Umgebung.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

_spec = importlib.util.spec_from_file_location(
    "_shadow_mode_helpers", BACKEND_ROOT / "tests" / "test_optimizer_shadow_mode.py",
)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
session_factory = _helpers.session_factory  # noqa: F811 -- Fixture wiederverwenden
_seed = _helpers._seed_realistic_mandate

import services.portfolio_engine as pe  # noqa: E402
from models.allocation import (  # noqa: E402
    CapitalMarketAssumption,
    OptimizerPolicy,
    OptimizerRun,
)
from models.mandates import Mandate  # noqa: E402
from models.profiling import RiskAssessment  # noqa: E402
from schemas.allocation import TargetAllocationGenerateResponse  # noqa: E402
from services.portfolio_engine import (  # noqa: E402
    build_target_payload_from_allocation,
    generate_target_allocation,
)


def _reload(s, mandate, ta):
    return build_target_payload_from_allocation(
        s, mandate, ta,
        s.query(OptimizerPolicy).filter(OptimizerPolicy.id == ta.policy_id).first(),
        s.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id == ta.capital_market_assumptions_id).first(),
        s.query(RiskAssessment).filter(RiskAssessment.id == ta.based_on_assessment_id).first(),
        None,
    )


@pytest.mark.parametrize("mode", ["shadow_stochastic", "stochastic"])
def test_generate_and_reload_deliver_identical_verified_evidence(session_factory, monkeypatch, mode):
    monkeypatch.setattr(pe.settings, "optimizer_mode", mode)
    advisor_id, _cid, mid, _aid, _gid = _seed(session_factory, suffix=f"ev{mode[:3]}")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generated = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        ta = generated["target_allocation"]
        ta_id = ta.id

    assert generated["optimizer_goal_driver_evidence"]["status"] == "verified"
    assert generated["optimizer_goal_drivers"], "realistisches Mandat hat Ziele"
    contract = generated["objective_contract_evidence"]
    assert contract["status"] == "verified"
    assert contract["objective_contract_version"] == "objective-contract-v3"
    snapshot = json.loads(ta.goal_driver_evidence_json)
    assert snapshot["objective_contract_hash"] == contract["objective_contract_hash"]

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        stored = s.query(type(ta)).filter(type(ta).id == ta_id).first()
        reloaded = _reload(s, mandate, stored)
        run = (
            s.query(OptimizerRun).filter(OptimizerRun.mandate_id == mid)
            .order_by(OptimizerRun.created_at.desc()).first()
        )

    assert reloaded["optimizer_goal_drivers"] == generated["optimizer_goal_drivers"]
    assert reloaded["optimizer_goal_driver_evidence"] == generated["optimizer_goal_driver_evidence"]
    assert reloaded["objective_contract_evidence"] == generated["objective_contract_evidence"]
    # OptimizerRun traegt denselben Vertrag wie die Modellbasis.
    assert run is not None
    assert run.objective_contract_hash == contract["objective_contract_hash"]
    assert run.objective_contract_version == "objective-contract-v3"
    assert json.loads(run.objective_contract_json)["objective_contract_hash"] == run.objective_contract_hash
    if mode == "stochastic":
        assert reloaded["objective_contract_evidence"].get("optimizer_run_bound") is True
    # Beide Payloads ueberstehen das API-Schema (inkl. Decimal/Hex-Validator).
    for payload in (generated, reloaded):
        response = TargetAllocationGenerateResponse.model_validate(payload, from_attributes=True)
        assert [d.goal_id for d in response.optimizer_goal_drivers] == [
            d["goal_id"] for d in generated["optimizer_goal_drivers"]
        ]


def test_reload_detects_manipulated_snapshot_and_returns_no_drivers(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed(session_factory, suffix="evtamp")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        ta = generate_target_allocation(s, mandate, advisor_id, preferences=None)["target_allocation"]
        envelope = json.loads(ta.goal_driver_evidence_json)
        envelope["drivers"][0]["weighted_objective_contribution_decimal"] = "123.0"
        envelope["drivers"][0]["weighted_objective_contribution_binary64_hex"] = (123.0).hex()
        ta.goal_driver_evidence_json = json.dumps(envelope)
        s.commit()
        reloaded = _reload(s, mandate, ta)
    assert reloaded["optimizer_goal_driver_evidence"]["status"] == "corrupt"
    assert reloaded["optimizer_goal_drivers"] == []


def test_house_matrix_reload_is_not_applicable(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, _gid = _seed(session_factory, suffix="evhouse")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generated = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        ta = generated["target_allocation"]
        s.commit()
        reloaded = _reload(s, mandate, ta)
    assert ta.goal_driver_evidence_json is None
    assert generated["optimizer_goal_drivers"] == reloaded["optimizer_goal_drivers"] == []
    assert reloaded["optimizer_goal_driver_evidence"]["status"] == "not_applicable"
    assert reloaded["objective_contract_evidence"]["status"] == "not_applicable"
