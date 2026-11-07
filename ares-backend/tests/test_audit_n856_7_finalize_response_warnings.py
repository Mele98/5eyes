"""N-856-7 (Pruefrunde #856): Finalize-Warnungen in der API-Antwort.

Vorher antwortete die Finalisierung mit ``RecommendationRunResponse`` ohne
Warnungsfeld; [SAA_BUCKET_DEVIATION] (PO-16) und die uebrigen
Finalize-Warnungen standen nur im Audit-Log. Der Berater sah sie beim
Finalisieren nicht.

Jetzt: ``RecommendationFinalizeResponse`` = Lauf + ``warnings`` (Freitext,
identisch zum Audit-Log) + ``warning_codes`` (strukturiert, aus den
``[CODE]``-Suffixen).
"""
from __future__ import annotations

from main import app
from models.users import User
from routers.review import finalize_recommendation
from schemas.review import RecommendationFinalizeResponse, finalize_warning_codes
from test_finalize_mandate_lock import (  # noqa: F401
    _FakeRequest,
    _add_full_position,
    _allocation_policy_and_cma,
    _current_allocation_id,
    _make_run,
    _seed_realistic_mandate,
    session_factory,
)


def test_finalize_returns_saa_deviation_warning_in_the_response(session_factory):
    """Rot vor dem Fix: die Antwort hatte kein ``warnings``-Feld."""
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(session_factory, suffix="n8567")
    alloc_id = _current_allocation_id(session_factory, mid, advisor_id)
    policy, cma = _allocation_policy_and_cma(session_factory, alloc_id)
    run_id = _make_run(session_factory, mid, alloc_id, aid, advisor_id, policy, cma, result_status="Draft")
    _add_full_position(session_factory, run_id)  # 100 % Aktien -> weicht von der SAA ab

    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).first()
        result = finalize_recommendation(
            mandate_id=mid, run_id=run_id, request=_FakeRequest(), db=db, current_user=advisor,
        )
    payload = RecommendationFinalizeResponse.model_validate(result).model_dump()
    assert payload["result_status"] == "Final"
    assert any("[SAA_BUCKET_DEVIATION]" in w for w in payload["warnings"]), payload["warnings"]
    assert "SAA_BUCKET_DEVIATION" in payload["warning_codes"]


def test_warning_codes_are_extracted_deduplicated_in_order():
    warnings = [
        "SAA-Abgleich Aktien: ... [SAA_BUCKET_DEVIATION].",
        "Produkteignung X: Positionsdeckel ueberschritten [POSITION_LIMIT_EXCEEDED].",
        "SAA-Abgleich Obligationen: ... [SAA_BUCKET_DEVIATION].",
        "Mindestens ein Marktpreis ist veraltet.",
    ]
    assert finalize_warning_codes(warnings) == ["SAA_BUCKET_DEVIATION", "POSITION_LIMIT_EXCEEDED"]


def test_finalize_route_declares_the_warning_fields_in_openapi():
    schema = app.openapi()
    path = schema["paths"]["/mandates/{mandate_id}/recommendations/{run_id}/finalize"]["put"]
    ref = path["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/RecommendationFinalizeResponse")
    props = schema["components"]["schemas"]["RecommendationFinalizeResponse"]["properties"]
    assert {"warnings", "warning_codes", "result_status"} <= set(props)
