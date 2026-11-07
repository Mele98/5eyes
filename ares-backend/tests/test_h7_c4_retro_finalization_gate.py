"""H7 C-4 (Compliance-Audit 2026-11-07, Luecke 4): Retro-Gate bei der
Finalisierung.

Befund an der Basis 2e5dfcc3: ``build_cost_disclosure`` setzt
``is_complete=False`` bei unbekannter (NULL) oder ungeregelter Retrozession
(Art. 26 FIDLEG; Art. 400 OR; BGE 137 III 393 / 143 III 348), aber
``PUT /mandates/{id}/recommendations/{run_id}/finalize`` fror den
unvollstaendigen Ausweis trotzdem ein und setzte den Lauf auf "Final".

Soll: fail-closed 422 mit Reason-Code, Lauf bleibt "Draft", kein
eingefrorener Ausweis, Sperre im Audit-Log. Retrozessionsfreie Produkte
(Satz 0 mit Quelle) bleiben finalisierbar.
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from models.review import AuditLog, Product, RecommendationPosition, RecommendationRun
from models.users import User
from routers.review import finalize_recommendation
from services.cost_disclosure import (
    RETRO_INCOMPLETE,
    RETRO_UNAVAILABLE,
    retrocession_finalization_block,
)
from test_finalize_mandate_lock import (  # noqa: F401
    _FakeRequest,
    _add_full_position,
    _allocation_policy_and_cma,
    _current_allocation_id,
    _make_run,
    _seed_realistic_mandate,
    session_factory,
)


def _draft_run_with_product(session_factory, suffix: str, *, retro_bps, source="Vertriebsvertrag 2026"):
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(session_factory, suffix=suffix)
    alloc_id = _current_allocation_id(session_factory, mid, advisor_id)
    policy, cma = _allocation_policy_and_cma(session_factory, alloc_id)
    run_id = _make_run(session_factory, mid, alloc_id, aid, advisor_id, policy, cma, result_status="Draft")
    _add_full_position(session_factory, run_id)
    with session_factory() as s:
        position = s.query(RecommendationPosition).filter(RecommendationPosition.run_id == run_id).one()
        product = s.get(Product, position.product_id)
        product.retrocession_bps = retro_bps
        product.retrocession_source = source if retro_bps is not None else None
        s.commit()
    return advisor_id, mid, run_id


def _finalize(session_factory, advisor_id, mid, run_id):
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).first()
        return finalize_recommendation(
            mandate_id=mid, run_id=run_id, request=_FakeRequest(), db=db, current_user=advisor,
        )


def _assert_blocked(session_factory, advisor_id, mid, run_id, expected_code):
    with pytest.raises(HTTPException) as excinfo:
        _finalize(session_factory, advisor_id, mid, run_id)
    assert excinfo.value.status_code == 422
    detail = excinfo.value.detail
    assert isinstance(detail, dict), detail
    assert detail["reason_code"] == expected_code
    assert "Art. 26 FIDLEG" in detail["message"]
    with session_factory() as s:
        run = s.get(RecommendationRun, run_id)
        assert run.result_status == "Draft"
        assert run.cost_disclosure_snapshot_json is None
        blocked = (
            s.query(AuditLog)
            .filter(AuditLog.record_id == run_id, AuditLog.field_name == "finalization_blocked")
            .all()
        )
        assert len(blocked) == 1
        assert json.loads(blocked[0].new_value)["reason_code"] == expected_code
        assert blocked[0].mandate_id == mid
    return detail


def test_finalize_blocks_unknown_retrocession(session_factory):
    advisor_id, mid, run_id = _draft_run_with_product(session_factory, "c4-unknown", retro_bps=None)
    detail = _assert_blocked(session_factory, advisor_id, mid, run_id, RETRO_INCOMPLETE)
    assert "Retrozession unbekannt für Test ETF" in detail["message"]


def test_finalize_blocks_unresolved_retrocession_without_waiver_or_refund(session_factory):
    advisor_id, mid, run_id = _draft_run_with_product(session_factory, "c4-unresolved", retro_bps=50)
    detail = _assert_blocked(session_factory, advisor_id, mid, run_id, RETRO_INCOMPLETE)
    assert "nicht oder nicht vollständig geregelt" in detail["message"]


def test_finalize_allows_retrocession_free_product(session_factory):
    advisor_id, mid, run_id = _draft_run_with_product(session_factory, "c4-free", retro_bps=0)
    result = _finalize(session_factory, advisor_id, mid, run_id)
    assert result.result_status == "Final"
    with session_factory() as s:
        snapshot = json.loads(s.get(RecommendationRun, run_id).cost_disclosure_snapshot_json)
        retro = snapshot["payload"]["product_retrocessions"]
        assert retro["complete"] is True


def test_gate_blocks_when_disclosure_is_not_computable_and_retro_unknown(session_factory, monkeypatch):
    advisor_id, mid, run_id = _draft_run_with_product(session_factory, "c4-pending", retro_bps=None)
    import services.cost_disclosure as cd

    monkeypatch.setattr(cd, "build_cost_disclosure_for_run", lambda *a, **k: {"data_pending": True})
    with session_factory() as s:
        from models.mandates import Mandate

        block = retrocession_finalization_block(s, s.get(Mandate, mid), s.get(RecommendationRun, run_id))
    assert block is not None and block["reason_code"] == RETRO_UNAVAILABLE

    def _boom(*args, **kwargs):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(cd, "build_cost_disclosure_for_run", _boom)
    with session_factory() as s:
        from models.mandates import Mandate

        block = retrocession_finalization_block(s, s.get(Mandate, mid), s.get(RecommendationRun, run_id))
    assert block is not None and block["reason_code"] == RETRO_UNAVAILABLE


def test_gate_passes_not_computable_disclosure_for_retro_free_products(session_factory, monkeypatch):
    advisor_id, mid, run_id = _draft_run_with_product(session_factory, "c4-pending-free", retro_bps=0)
    import services.cost_disclosure as cd

    monkeypatch.setattr(cd, "build_cost_disclosure_for_run", lambda *a, **k: {"data_pending": True})
    with session_factory() as s:
        from models.mandates import Mandate

        assert retrocession_finalization_block(s, s.get(Mandate, mid), s.get(RecommendationRun, run_id)) is None


def test_gate_blocks_manual_inducement_without_waiver():
    """Auch eine manuell erfasste Verguetung von Dritten ohne Verzicht bzw.
    Weitergabe (cost_item.requires_resolution) sperrt."""
    from types import SimpleNamespace
    from unittest.mock import patch

    payload = {
        "data_pending": False,
        "cost_items": [{"label": "Vergütung von Dritten (Anbieter A)", "requires_resolution": True}],
        "product_retrocessions": None,
    }
    with patch("services.cost_disclosure.build_cost_disclosure_for_run", return_value=payload):
        block = retrocession_finalization_block(None, SimpleNamespace(), SimpleNamespace(id="r"))
    assert block["reason_code"] == RETRO_INCOMPLETE
    assert "Anbieter A" in block["message"]
