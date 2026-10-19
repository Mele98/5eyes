"""RISK-OVERRIDE-WRITE-BOUNDARY-001: der Override-Endpunkt prueft dieselbe
Dokumentationsregel wie alle nachgelagerten Consumer VOR jeder Mutation.

Uebernommen aus dem adversarialen Codex-Review zu PR #639
(docs/audits/reproducers/test_2026_10_18_risk_override_client_wish_adversarial.py,
dort xfail-strict); hier als regulaerer Regressionstest ohne xfail.
"""
from __future__ import annotations

import pytest

from models.profiling import RiskAssessment
from tests.test_bug2_risk_override_save import (
    VALID_REASON,
    _setup_full,
    advisor_user,
    auth_client,
    session_factory,
)


def _assert_override_not_persisted(session_factory, ra_id: str) -> None:
    with session_factory() as db:
        assessment = (
            db.query(RiskAssessment)
            .filter(RiskAssessment.id == ra_id)
            .one()
        )
        assert int(assessment.is_overridden or 0) == 0
        assert assessment.override_score_x10 is None
        assert assessment.override_profile is None
        assert not str(assessment.override_reason or "").strip()
        assert int(assessment.override_client_confirmed or 0) == 0
        assert int(assessment.override_warning_delivered or 0) == 0


def test_upward_override_without_client_wish_is_rejected_atomically(
    auth_client,
    advisor_user,
    session_factory,
):
    """The public write boundary must enforce the new CIO rule itself.

    A direct API caller can bypass the modal. Persisting an incomplete override
    and relying on later allocation gates leaves canonical client evidence in
    a state the domain contract itself rejects. The request must return 422
    (or an equivalent validation error) and leave the assessment unchanged.
    """
    _, mandate_id, ra_id = _setup_full(auth_client, advisor_user)

    response = auth_client.post(
        f"/mandates/{mandate_id}/risk-assessments/{ra_id}/override",
        json={
            "override_score_x10": 100,
            "override_profile": "Aktien",
            "override_reason": VALID_REASON,
            "override_client_confirmed": False,
            "override_warning_delivered": False,
        },
    )

    _assert_override_not_persisted(session_factory, ra_id)
    assert response.status_code == 422, response.text


def test_override_above_capacity_without_warning_is_rejected_atomically(
    auth_client,
    advisor_user,
    session_factory,
):
    """Client wish cannot substitute the separately required risk warning."""
    _, mandate_id, ra_id = _setup_full(auth_client, advisor_user)

    response = auth_client.post(
        f"/mandates/{mandate_id}/risk-assessments/{ra_id}/override",
        json={
            "override_score_x10": 100,
            "override_profile": "Aktien",
            "override_reason": VALID_REASON,
            "override_client_confirmed": True,
            "override_warning_delivered": False,
        },
    )

    _assert_override_not_persisted(session_factory, ra_id)
    assert response.status_code == 422, response.text
