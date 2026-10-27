"""RISK-BUDGET-RELEASE-GATE (2026-10-21): Verhaltens-Tests der drei
Freigabekanaele gegen das zentrale Gate
``services/recommendation_release_gate.assert_recommendation_release_eligible``.

Der Codex-Reproducer (test_risk_budget_release_gate_reproducers.py) prueft
nur per Quelltext, DASS jeder Kanal das Gate aufruft. Hier wird belegt,
WAS dabei passiert: verletztes oder unbelegtes Risikobudget -> 409 mit
Reason-Code, keine Wirkung (kein PDF, keine Signatur, kein Handoff);
budgetkonforme Allokation -> Gate laesst durch.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from database import new_uuid  # noqa: E402
from models.allocation import TargetAllocation  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.portfolio_handoff import PortfolioHandoff  # noqa: E402
from models.review import ContractDocument  # noqa: E402
from models.users import User  # noqa: E402
from routers.pdf_reports import get_advisory_report_pdf  # noqa: E402
from routers.portfolio_handoff import create_portfolio_handoff  # noqa: E402
from routers.review import sign_document  # noqa: E402
from schemas.portfolio_handoff import PortfolioHandoffCreate  # noqa: E402
from schemas.review import ContractDocumentSign  # noqa: E402
from services.recommendation_release_gate import (  # noqa: E402
    CHANNEL_ADVISORY_PDF,
    RELEASE_ALLOCATION_MISSING,
    RISK_BUDGET_EVIDENCE_MISSING,
    RISK_BUDGET_VIOLATED,
    assert_recommendation_release_eligible,
    risk_budget_release_findings,
)
from test_finalization_ignores_risk_budget_violated_lock import (  # noqa: E402
    _FakeRequest,
    _add_full_position,
    _allocation_policy_and_cma,
    _current_allocation_id,
    _force_risk_budget_violation,
    _make_run,
    _seed_realistic_mandate,
    session_factory,
)

_SIGNATURE = "data:image/png;base64,iVBORw0KGgo="


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _setup(session_factory, suffix: str, *, mode: str):
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(
        session_factory, suffix=suffix,
    )
    alloc_id = _current_allocation_id(session_factory, mid, advisor_id)
    if mode == "violated":
        _force_risk_budget_violation(session_factory, alloc_id)
    elif mode == "missing":
        with session_factory() as db:
            allocation = db.query(TargetAllocation).filter(
                TargetAllocation.id == alloc_id
            ).one()
            allocation.risky_fraction_bps_at_generation = None
            db.commit()
    return advisor_id, mid, aid, alloc_id


def _add_document(session_factory, mid, advisor_id, document_type) -> str:
    from signable_document_fixture import archived_pdf_fields

    doc_id = new_uuid()
    now = _iso()
    with session_factory() as db:
        db.add(ContractDocument(
            id=doc_id, mandate_id=mid, document_type=document_type,
            title=document_type, status="Entwurf", signed_by_advisor=0,
            signed_by_client=0, version=1, created_by=advisor_id,
            created_at=now, updated_at=now,
            # CERT-SIGNED-PUBLICATION-001: signierbar ist nur ein
            # archiviertes, pruefsummengesichertes PDF.
            **archived_pdf_fields(),
        ))
        db.commit()
    return doc_id


# ── reine Pruefung ─────────────────────────────────────────────────────────


class _Alloc:
    def __init__(self, budget, realized):
        self.risk_budget_bps_at_generation = budget
        self.risky_fraction_bps_at_generation = realized


@pytest.mark.parametrize(
    "budget, realized, expected",
    [
        (5000, 5000, []),
        (5000, 4999, []),
        (5000, 5001, [RISK_BUDGET_VIOLATED]),
        (5000, None, [RISK_BUDGET_EVIDENCE_MISSING]),
        (None, 4000, [RISK_BUDGET_EVIDENCE_MISSING]),
        (None, None, [RISK_BUDGET_EVIDENCE_MISSING]),
        ("x", 4000, [RISK_BUDGET_EVIDENCE_MISSING]),
    ],
)
def test_findings_matrix(budget, realized, expected):
    codes = [code for code, _ in risk_budget_release_findings(_Alloc(budget, realized))]
    assert codes == expected


# ── Advisory-PDF ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "mode, reason", [("violated", RISK_BUDGET_VIOLATED), ("missing", RISK_BUDGET_EVIDENCE_MISSING)],
)
def test_advisory_pdf_blocks_before_render(session_factory, monkeypatch, mode, reason):
    advisor_id, mid, _aid, _alloc = _setup(session_factory, f"rbg-pdf-{mode}", mode=mode)
    rendered = []
    import services.pdf.documents.advisory_report as adv

    monkeypatch.setattr(
        adv, "render_advisory_report_pdf",
        lambda *a, **k: rendered.append(1) or b"%PDF",
    )
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).one()
        with pytest.raises(HTTPException) as exc:
            get_advisory_report_pdf(mandate_id=mid, db=db, current_user=advisor)
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == reason
    assert "Risikobudget" in exc.value.detail["message"]
    assert rendered == [], "PDF darf bei gesperrtem Gate nicht gerendert werden"


def test_gate_passes_for_allocation_within_budget(session_factory):
    advisor_id, mid, aid, alloc_id = _setup(session_factory, "rbg-ok", mode="ok")
    policy, cma = _allocation_policy_and_cma(session_factory, alloc_id)
    run_id = _make_run(session_factory, mid, alloc_id, aid, advisor_id, policy, cma)
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        from models.review import RecommendationRun

        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).one()
        # wirft nicht
        assert_recommendation_release_eligible(db, mandate, channel=CHANNEL_ADVISORY_PDF)
        assert_recommendation_release_eligible(db, mandate, channel="handoff", run=run)


def test_gate_without_current_allocation_publishes_nothing_to_block(session_factory):
    advisor_id, mid, _aid, alloc_id = _setup(session_factory, "rbg-noalloc", mode="violated")
    with session_factory() as db:
        db.query(TargetAllocation).filter(TargetAllocation.id == alloc_id).update(
            {"is_current": 0}
        )
        db.commit()
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        assert_recommendation_release_eligible(db, mandate, channel=CHANNEL_ADVISORY_PDF)


# ── Signatur ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "mode, reason", [("violated", RISK_BUDGET_VIOLATED), ("missing", RISK_BUDGET_EVIDENCE_MISSING)],
)
def test_signature_of_recommendation_document_blocked_without_mutation(
    session_factory, mode, reason,
):
    advisor_id, mid, _aid, _alloc = _setup(session_factory, f"rbg-sign-{mode}", mode=mode)
    doc_id = _add_document(session_factory, mid, advisor_id, "Anlagestrategie")
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).one()
        with pytest.raises(HTTPException) as exc:
            sign_document(
                mandate_id=mid, doc_id=doc_id,
                body=ContractDocumentSign(
                    signed_by_advisor=True, signature_image=_SIGNATURE,
                    signer_name="Berater",
                ),
                request=_FakeRequest(), db=db, current_user=advisor,
            )
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == reason
    with session_factory() as db:
        doc = db.query(ContractDocument).filter(ContractDocument.id == doc_id).one()
        assert doc.signed_by_advisor == 0
        assert doc.signature_advisor_image is None
        assert doc.status == "Entwurf"


def test_signature_of_non_recommendation_document_is_not_gated(session_factory):
    advisor_id, mid, _aid, _alloc = _setup(session_factory, "rbg-sign-contract", mode="violated")
    doc_id = _add_document(session_factory, mid, advisor_id, "Beratungsvertrag")
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).one()
        doc = sign_document(
            mandate_id=mid, doc_id=doc_id,
            body=ContractDocumentSign(
                signed_by_advisor=True, signature_image=_SIGNATURE,
                signer_name="Berater",
            ),
            request=_FakeRequest(), db=db, current_user=advisor,
        )
        assert doc.signed_by_advisor == 1


# ── Handoff ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "mode, reason", [("violated", RISK_BUDGET_VIOLATED), ("missing", RISK_BUDGET_EVIDENCE_MISSING)],
)
def test_handoff_blocked_without_persisting(session_factory, monkeypatch, mode, reason):
    advisor_id, mid, aid, alloc_id = _setup(session_factory, f"rbg-ho-{mode}", mode=mode)
    with session_factory() as db:
        db.query(Mandate).filter(Mandate.id == mid).update(
            {"mandate_type": "Vermögensverwaltung"}
        )
        db.commit()
    policy, cma = _allocation_policy_and_cma(session_factory, alloc_id)
    run_id = _make_run(
        session_factory, mid, alloc_id, aid, advisor_id, policy, cma,
        result_status="Final",
    )
    _add_full_position(session_factory, run_id)
    snapshots = []
    import routers.portfolio_handoff as ho

    monkeypatch.setattr(
        ho, "snapshot_handoff_trades",
        lambda *a, **k: snapshots.append(1) or ([{"isin": "X"}], 1),
    )
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).one()
        with pytest.raises(HTTPException) as exc:
            create_portfolio_handoff(
                mandate_id=mid, run_id=run_id,
                body=PortfolioHandoffCreate(recipient_name="AM"),
                request=_FakeRequest(), db=db, current_user=advisor,
            )
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == reason
    assert snapshots == []
    with session_factory() as db:
        assert db.query(PortfolioHandoff).filter(
            PortfolioHandoff.mandate_id == mid
        ).count() == 0


def test_handoff_run_without_allocation_is_blocked(session_factory):
    advisor_id, mid, aid, alloc_id = _setup(session_factory, "rbg-ho-noalloc", mode="ok")
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        from models.review import RecommendationRun

        policy, cma = _allocation_policy_and_cma(session_factory, alloc_id)
        run_id = _make_run(session_factory, mid, None, aid, advisor_id, policy, cma)
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).one()
        with pytest.raises(HTTPException) as exc:
            assert_recommendation_release_eligible(db, mandate, channel="handoff", run=run)
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == RELEASE_ALLOCATION_MISSING
