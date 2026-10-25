"""RESERVE-LEDGER-SNAPSHOT-001 (CIO 2026-10-22): die Finalisierungs-Sperre
fuer stale/unverifiable Reserve-Ledger ist eine verstaendliche
Handlungsanweisung mit reason_code -- im Backend (strukturierte 422) und im
Monolith (nur Klartext, nie der rohe Code).
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import app  # noqa: F401,E402
import services.portfolio_engine as pe  # noqa: E402
from models.allocation import TargetAllocation  # noqa: E402
from models.users import User  # noqa: E402
from routers.review import finalize_recommendation  # noqa: E402
from services.portfolio_engine_allocation_integrity import allocation_context_hash_for  # noqa: E402
from services.reserve_funding_ledger import ledger_contract_hash  # noqa: E402
from services.reserve_funding_ledger_snapshot import (  # noqa: E402
    CONSTRAINTS_KEY,
    FINALIZATION_MESSAGES,
    REASON_LEDGER_STALE,
    REASON_RECALCULATION_REQUIRED,
    finalization_reason_code,
    reserve_ledger_finalization_block,
)
from test_finalize_mandate_lock import (  # noqa: E402
    _FakeRequest,
    _add_full_position,
    _allocation_policy_and_cma,
    _current_allocation_id,
    _make_run,
)
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: F401,E402

MONOLITH = BACKEND_ROOT.parent / "ares-desktop" / "frontend" / "ares.html"
LEGACY_TEXT = (
    "Die Strategie stammt aus einer früheren Version und muss einmal neu "
    "berechnet werden, bevor sie finalisiert werden kann."
)


def test_block_texts_and_codes():
    assert reserve_ledger_finalization_block(
        {"reserve_funding_ledger_replay": {"status": "verified"}}
    ) is None
    code, text = reserve_ledger_finalization_block(
        {"reserve_funding_ledger_replay": {"status": "unverifiable"}}
    )
    assert code == REASON_RECALCULATION_REQUIRED == "RESERVE_LEDGER_RECALCULATION_REQUIRED"
    assert text.startswith(LEGACY_TEXT)
    assert "Neu berechnen" in text
    # Fehlender Replay-Block (z. B. aelterer Payload) ist ebenfalls fail-closed.
    assert reserve_ledger_finalization_block({})[0] == REASON_RECALCULATION_REQUIRED
    code, text = reserve_ledger_finalization_block(
        {"reserve_funding_ledger_replay": {"status": "stale"}}
    )
    assert code == REASON_LEDGER_STALE
    assert "neu berechnet werden, bevor sie finalisiert werden kann" in text
    for message in FINALIZATION_MESSAGES.values():
        assert "RESERVE_LEDGER" not in message  # kein technischer Code im Klartext
    assert finalization_reason_code(["x", text]) == REASON_LEDGER_STALE
    assert finalization_reason_code(["x"]) is None


def _prepare_run(session_factory, suffix):
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(session_factory, suffix=suffix)
    alloc_id = _current_allocation_id(session_factory, mid, advisor_id)
    policy, cma = _allocation_policy_and_cma(session_factory, alloc_id)
    run_id = _make_run(session_factory, mid, alloc_id, aid, advisor_id, policy, cma)
    _add_full_position(session_factory, run_id)
    return advisor_id, mid, alloc_id, run_id


def _strip_snapshot_to_legacy(session_factory, alloc_id):
    with session_factory() as s:
        allocation = s.query(TargetAllocation).filter(TargetAllocation.id == alloc_id).one()
        constraints = json.loads(allocation.effective_constraints_json)
        constraints.pop(CONSTRAINTS_KEY)
        allocation.effective_constraints_json = json.dumps(
            constraints, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        allocation.reserve_funding_ledger_json = None
        allocation.reserve_funding_ledger_hash = None
        allocation.allocation_context_hash = allocation_context_hash_for(
            engine_version=constraints["engine_version"],
            policy_id=allocation.policy_id,
            cma_id=allocation.capital_market_assumptions_id,
            assessment_id=allocation.based_on_assessment_id,
            input_snapshot_hash=allocation.input_snapshot_hash,
            preferences_json=allocation.preferences_json,
            targets={b: int(getattr(allocation, f"target_{b}_bps")) for b in pe.BUCKET_FIELDS},
            sub_allocations=json.loads(allocation.sub_allocations_json),
            effective_constraints=constraints,
            optimization_seed=allocation.optimization_seed,
        )
        s.commit()


def _finalize_detail(session_factory, advisor_id, mid, run_id):
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).first()
        with pytest.raises(HTTPException) as exc_info:
            finalize_recommendation(
                mandate_id=mid, run_id=run_id, request=_FakeRequest(), db=db, current_user=advisor,
            )
    assert exc_info.value.status_code == 422
    return exc_info.value.detail


def test_finalize_legacy_allocation_returns_recalculation_instruction(session_factory):  # noqa: F811
    advisor_id, mid, alloc_id, run_id = _prepare_run(session_factory, "ledger-final-legacy")
    _strip_snapshot_to_legacy(session_factory, alloc_id)
    detail = _finalize_detail(session_factory, advisor_id, mid, run_id)
    assert detail["reason_code"] == "RESERVE_LEDGER_RECALCULATION_REQUIRED"
    assert LEGACY_TEXT in detail["message"]
    assert FINALIZATION_MESSAGES[REASON_RECALCULATION_REQUIRED] in detail["errors"]


def test_finalize_stale_ledger_policy_returns_stale_code(session_factory, monkeypatch):  # noqa: F811
    advisor_id, mid, _alloc_id, run_id = _prepare_run(session_factory, "ledger-final-stale")
    real_compile = pe.compile_reserve_funding_ledger_for_inputs

    def compile_with_new_policy(**kwargs):
        changed = replace(real_compile(**kwargs), policy_version="future_policy_v999")
        return replace(changed, contract_hash=ledger_contract_hash(changed))

    monkeypatch.setattr(pe, "compile_reserve_funding_ledger_for_inputs", compile_with_new_policy)
    detail = _finalize_detail(session_factory, advisor_id, mid, run_id)
    assert detail["reason_code"] == "RESERVE_LEDGER_STALE"
    assert FINALIZATION_MESSAGES[REASON_LEDGER_STALE] in detail["message"]


def test_monolith_finalize_error_shows_message_not_reason_code():
    html = MONOLITH.read_text(encoding="utf-8")
    recipe = re.search(r"async function confirmImplementationRecipe\(\)\{.*?\n\}", html, re.S)
    assert recipe, "confirmImplementationRecipe fehlt"
    assert "finalizeErrorText(e)" in recipe.group(0)
    helper = re.search(r"function finalizeErrorText\(e\)\{.*?\n\}", html, re.S)
    assert helper, "finalizeErrorText fehlt"
    body = helper.group(0)
    assert "d.reason_code&&d.message" in body
    assert "return String(d.message)" in body
    assert "'['" not in body and "reason_code+" not in body
