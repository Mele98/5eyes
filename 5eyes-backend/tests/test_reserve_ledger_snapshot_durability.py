"""RESERVE-LEDGER-SNAPSHOT-001: der Generate-Ledger ist durable Decision Evidence.

Uebernimmt die zwei Codex-Reproducer
(``docs/audits/reproducers/test_2026_10_19_pr648_reserve_ledger_durability_adversarial.py``,
Branch ``codex/asset-allocation-stochastic-core``) als regulaere Tests ohne
xfail und ergaenzt die Pflichtregressionen aus Abschnitt 7 des
Closure-Reviews: byte-gleicher Snapshot nach neuer Session, Manipulation
bricht das Integritaets-Gate, Historical Replay vs. Live-Preview, Legacy
ohne Snapshot = ``unverifiable``, Finalisierung fail-closed.
"""
from __future__ import annotations

from dataclasses import replace
import json

import pytest
from sqlalchemy import inspect as sa_inspect

import services.portfolio_engine as pe
from models.allocation import TargetAllocation
from services.portfolio_engine_allocation_integrity import allocation_context_hash_for
from services.reserve_funding_ledger import ledger_contract_hash
from services.reserve_funding_ledger_snapshot import (
    CONSTRAINTS_KEY,
    reserve_ledger_finalization_error,
)
from tests.test_optimizer_production_contract import (
    _generate,
    _preferences,
    _reload_payload,
    _seed_clean_mandate,
    session_factory,  # noqa: F401 - pytest fixture re-export
)


@pytest.fixture(autouse=True)
def _no_mc(monkeypatch):
    monkeypatch.setattr(
        pe,
        "_run_allocation_monte_carlo",
        lambda **_kwargs: {"goal_summaries": [], "current_goal_summaries": []},
    )


def _seed_and_generate(session_factory, suffix: str):
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory,
        suffix=suffix,
    )
    generated = _generate(session_factory, mandate_id, advisor_id, _preferences())
    return mandate_id, generated


def _current(session, mandate_id):
    return (
        session.query(TargetAllocation)
        .filter(TargetAllocation.mandate_id == mandate_id, TargetAllocation.is_current == 1)
        .one()
    )


def _patch_future_policy(monkeypatch):
    real_compile = pe.compile_reserve_funding_ledger_for_inputs

    def compile_with_new_policy(**kwargs):
        original = real_compile(**kwargs)
        changed = replace(original, policy_version="future_policy_v999")
        return replace(changed, contract_hash=ledger_contract_hash(changed))

    monkeypatch.setattr(pe, "compile_reserve_funding_ledger_for_inputs", compile_with_new_policy)


# --- Codex-Reproducer (ohne xfail) -------------------------------------------


def test_generated_reserve_ledger_hash_is_bound_to_persisted_allocation(
    session_factory,  # noqa: F811
):
    mandate_id, generated = _seed_and_generate(session_factory, "rls-durable-snapshot")
    generated_hash = generated["reserve_funding_ledger"]["contract_hash"]
    with session_factory() as session:
        allocation = _current(session, mandate_id)
        persisted = {
            column.key: getattr(allocation, column.key)
            for column in sa_inspect(TargetAllocation).columns
        }
    assert generated_hash in json.dumps(persisted, sort_keys=True, default=str)


def test_reload_replays_generated_ledger_instead_of_current_compiler_policy(
    session_factory,  # noqa: F811
    monkeypatch,
):
    mandate_id, generated = _seed_and_generate(session_factory, "rls-policy-replay")
    generated_ledger = generated["reserve_funding_ledger"]
    _patch_future_policy(monkeypatch)
    with session_factory() as session:
        reloaded = _reload_payload(session, _current(session, mandate_id))
    assert reloaded["reserve_funding_ledger"] == generated_ledger
    # Live-Preview ist getrennt ausgewiesen, der Entscheid fail-closed stale.
    replay = reloaded["reserve_funding_ledger_replay"]
    assert replay["mode"] == "historical_replay"
    assert replay["status"] == "stale"
    assert replay["snapshot_hash"] == generated_ledger["contract_hash"]
    assert replay["live_preview"]["policy_version"] == "future_policy_v999"
    assert replay["live_preview"]["contract_hash"] != generated_ledger["contract_hash"]
    assert reserve_ledger_finalization_error(reloaded) is not None


# --- Pflichtregressionen ------------------------------------------------------


def test_snapshot_is_bytewise_available_after_new_session_and_hash_bound(
    session_factory,  # noqa: F811
):
    mandate_id, generated = _seed_and_generate(session_factory, "rls-bytewise")
    ledger = generated["reserve_funding_ledger"]
    with session_factory() as session:
        allocation = _current(session, mandate_id)
        snapshot = json.loads(allocation.reserve_funding_ledger_json)
        constraints = json.loads(allocation.effective_constraints_json)
        assert allocation.reserve_funding_ledger_hash == ledger["contract_hash"]
        assert snapshot["ledger"] == json.loads(json.dumps(ledger))
        assert constraints[CONSTRAINTS_KEY] == {
            "snapshot_version": "reserve_funding_ledger_snapshot_v1",
            "version": ledger["version"],
            "policy_version": ledger["policy_version"],
            "contract_hash": ledger["contract_hash"],
        }
        reloaded = _reload_payload(session, allocation)
    assert reloaded["reserve_funding_ledger"] == ledger
    assert reloaded["reserve_funding_ledger_replay"]["status"] == "verified"
    assert reloaded["reserve_funding_ledger_replay"]["live_preview"] is None
    assert reserve_ledger_finalization_error(reloaded) is None


@pytest.mark.parametrize(
    "mutation",
    ["release_series", "policy_version", "hash_column", "constraint_reference", "drop_snapshot_only"],
)
def test_any_ledger_mutation_breaks_allocation_integrity_gate(
    session_factory,  # noqa: F811
    mutation,
):
    mandate_id, _generated = _seed_and_generate(session_factory, f"rls-tamper-{mutation}")
    with session_factory() as session:
        allocation = _current(session, mandate_id)
        snapshot = json.loads(allocation.reserve_funding_ledger_json)
        if mutation == "release_series":
            series = list(snapshot["ledger"]["release_series_rappen"])
            series[0] = int(series[0]) + 1
            snapshot["ledger"]["release_series_rappen"] = series
            allocation.reserve_funding_ledger_json = json.dumps(snapshot)
        elif mutation == "policy_version":
            snapshot["ledger"]["policy_version"] = "future_policy_v999"
            allocation.reserve_funding_ledger_json = json.dumps(snapshot)
        elif mutation == "hash_column":
            allocation.reserve_funding_ledger_hash = "0" * 64
        elif mutation == "constraint_reference":
            constraints = json.loads(allocation.effective_constraints_json)
            constraints[CONSTRAINTS_KEY]["contract_hash"] = "0" * 64
            allocation.effective_constraints_json = json.dumps(constraints)
        else:
            allocation.reserve_funding_ledger_json = None
            allocation.reserve_funding_ledger_hash = None
        session.flush()
        with pytest.raises(ValueError):
            _reload_payload(session, allocation)
        session.rollback()


def test_legacy_allocation_without_snapshot_is_unverifiable_not_replaced(
    session_factory,  # noqa: F811
):
    """Legacy (vor diesem Vertrag) korrekt versiegelt, aber ohne Ledger."""
    mandate_id, _generated = _seed_and_generate(session_factory, "rls-legacy")
    with session_factory() as session:
        allocation = _current(session, mandate_id)
        constraints = json.loads(allocation.effective_constraints_json)
        constraints.pop(CONSTRAINTS_KEY)
        allocation.effective_constraints_json = json.dumps(
            constraints, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        allocation.reserve_funding_ledger_json = None
        allocation.reserve_funding_ledger_hash = None
        targets = {
            bucket: int(getattr(allocation, f"target_{bucket}_bps"))
            for bucket in pe.BUCKET_FIELDS
        }
        allocation.allocation_context_hash = allocation_context_hash_for(
            engine_version=constraints["engine_version"],
            policy_id=allocation.policy_id,
            cma_id=allocation.capital_market_assumptions_id,
            assessment_id=allocation.based_on_assessment_id,
            input_snapshot_hash=allocation.input_snapshot_hash,
            preferences_json=allocation.preferences_json,
            targets=targets,
            sub_allocations=json.loads(allocation.sub_allocations_json),
            effective_constraints=constraints,
            optimization_seed=allocation.optimization_seed,
        )
        session.flush()
        reloaded = _reload_payload(session, allocation)
        session.rollback()
    assert reloaded["reserve_funding_ledger"] is None
    replay = reloaded["reserve_funding_ledger_replay"]
    assert replay["status"] == "unverifiable"
    assert replay["mode"] == "legacy_live_preview"
    assert replay["live_preview"]["basis"] == "live_preview_current_compiler"
    assert reserve_ledger_finalization_error(reloaded) is not None


def test_regenerate_after_policy_change_writes_new_verified_snapshot(
    session_factory,  # noqa: F811
    monkeypatch,
):
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory, suffix="rls-regenerate",
    )
    first = _generate(session_factory, mandate_id, advisor_id, _preferences())
    _patch_future_policy(monkeypatch)
    second = _generate(session_factory, mandate_id, advisor_id, _preferences())
    assert second["reserve_funding_ledger"]["policy_version"] == "future_policy_v999"
    with session_factory() as session:
        allocation = _current(session, mandate_id)
        assert allocation.reserve_funding_ledger_hash == second["reserve_funding_ledger"]["contract_hash"]
        assert allocation.reserve_funding_ledger_hash != first["reserve_funding_ledger"]["contract_hash"]
        reloaded = _reload_payload(session, allocation)
    assert reloaded["reserve_funding_ledger_replay"]["status"] == "verified"
