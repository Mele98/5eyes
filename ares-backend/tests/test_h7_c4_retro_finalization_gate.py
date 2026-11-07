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


# ---------------------------------------------------------------------------
# N-884-04: bereits finale Laeufe (vor dem Gate finalisiert) werden weder
# weitergeleitet noch unterzeichnet, solange die Retrozession nicht geklaert
# ist. Gelesen wird das eingefrorene L1-Urteil.
# ---------------------------------------------------------------------------

from core.reason_codes import DomainError  # noqa: E402
from services.recommendation_release_gate import (  # noqa: E402
    CHANNEL_HANDOFF,
    CHANNEL_SIGNATURE,
    assert_retrocession_release_eligible,
)


def _final_run(session_factory, suffix):
    advisor_id, mid, run_id = _draft_run_with_product(session_factory, suffix, retro_bps=0)
    _finalize(session_factory, advisor_id, mid, run_id)
    return mid, run_id


def _tamper_snapshot(session_factory, run_id, mutate):
    with session_factory() as s:
        run = s.get(RecommendationRun, run_id)
        envelope = json.loads(run.cost_disclosure_snapshot_json)
        mutate(envelope["payload"])
        run.cost_disclosure_snapshot_json = json.dumps(envelope)
        s.commit()


def _check(session_factory, mid, run_id=None, channel=CHANNEL_SIGNATURE):
    from models.mandates import Mandate

    calls = []
    with session_factory() as s:
        run = s.get(RecommendationRun, run_id) if run_id else None
        assert_retrocession_release_eligible(
            s, s.get(Mandate, mid), channel=channel, run=run,
            on_block=lambda code, rid: calls.append((code, rid)),
        )
    return calls


def test_clean_final_run_is_releasable(session_factory):
    mid, run_id = _final_run(session_factory, "c4-rel-clean")
    assert _check(session_factory, mid) == []
    assert _check(session_factory, mid, run_id, CHANNEL_HANDOFF) == []


def test_legacy_final_run_with_incomplete_retro_blocks_signature_and_handoff(session_factory):
    mid, run_id = _final_run(session_factory, "c4-rel-legacy")
    _tamper_snapshot(
        session_factory, run_id,
        lambda payload: payload["product_retrocessions"].update(complete=False),
    )
    for channel, rid in ((CHANNEL_SIGNATURE, None), (CHANNEL_HANDOFF, run_id)):
        calls = []
        from models.mandates import Mandate

        with session_factory() as s:
            run = s.get(RecommendationRun, rid) if rid else None
            with pytest.raises(DomainError) as excinfo:
                assert_retrocession_release_eligible(
                    s, s.get(Mandate, mid), channel=channel, run=run,
                    on_block=lambda code, r: calls.append((code, r)),
                )
        assert excinfo.value.http_status == 409
        assert excinfo.value.as_detail()["reason_code"] == RETRO_INCOMPLETE
        assert calls == [(RETRO_INCOMPLETE, run_id)]


def test_final_run_without_snapshot_and_unknown_retro_blocks(session_factory):
    mid, run_id = _final_run(session_factory, "c4-rel-nosnap")
    with session_factory() as s:
        run = s.get(RecommendationRun, run_id)
        run.cost_disclosure_snapshot_json = None
        position = s.query(RecommendationPosition).filter(RecommendationPosition.run_id == run_id).one()
        s.get(Product, position.product_id).retrocession_bps = None
        s.commit()
    with pytest.raises(DomainError) as excinfo:
        _check(session_factory, mid, run_id, CHANNEL_HANDOFF)
    assert excinfo.value.as_detail()["reason_code"] == RETRO_UNAVAILABLE


# Router-Verdrahtung samt Audit-Eintrag: tests/test_h7_n884_07_release_block_audit.py
