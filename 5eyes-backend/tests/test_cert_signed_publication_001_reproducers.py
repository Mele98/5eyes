"""CERT-SIGNED-PUBLICATION-001 -- permanent repository reproducers.

Source of truth: the Ares/Codex audit worktree
`C:\\Users\\Emanuele\\Documents\\ChatGPT\\5eyes wird zu Ares\\asset-allocation-stochastic-core`
(branch `codex/asset-allocation-stochastic-core`),
`docs/audits/2026-10-08-signed-publication-principal-eligibility-and-execution-certification-spec.md`.
That spec documents five reproduced-but-not-committed findings against
`develop@e77910c5242d7033fb04787c8b768495b0877b29` (its own temporary
reproducers were deliberately removed after the run, per its
`product_code_mutated: false` / `tests_mutated: false` audit discipline).
Section 12.1/13 of that spec's own "Implementierungsreihenfolge fuer Claude"
is to adopt these five reproducers as PERMANENT repository tests before
touching any product code (mirrors the already-merged sibling package
CERT-PRODUCT-ELIGIBILITY-001, see test_cert_product_eligibility_001_
reproducers.py). This file is that step.

All five root causes below were independently re-verified against this
repo's actual current `develop` HEAD before writing these tests -- not
copied from the spec's historical evidence unchecked:

- SIGN-IDENTITY-001: routers/review.py::sign_document is guarded only by
  require_advisor; the body alone decides signed_by_advisor vs.
  signed_by_client, and the same authenticated advisor principal can set
  either flag. There is no AuthenticatedSignerPrincipalV1 that derives the
  allowed signer role from the authenticated principal and mandate
  relationship.
- SIGN-CONTEXT-001: routers/review.py::create_document persists a
  ContractDocument with status="Entwurf" and no required pdf_base64/
  checksum_sha256/content_hash/recommendation/allocation/release anchors.
  sign_document() does not require any of them before accepting a
  signature.
- SIGN-HASH-001: models/review.py::ContractDocument carries pdf_base64/
  checksum_sha256/content_hash columns, but sign_document() never
  recomputes or verifies them -- a deliberately wrong checksum does not
  block the signature.
- SIGN-CLAIM-001: routers/pdf_reports.py::_build_protokoll_data loads the
  single most recently created RecommendationRun of the mandate with no
  filter on result_status == "Final", and uses its objective_summary (or
  its raw status string) as `latest_recommendation_summary`, which flows
  straight into ContractSignoffData.final_recommendation on the "Final
  customer sign-off" PDF.
- SIGN-ELIGIBILITY-001: routers/portfolio_handoff.py::create_portfolio_
  handoff / _get_recommendation_run_or_404 only checks mandate_type and
  existence of the RecommendationRun row -- it never requires
  result_status == "Final" nor any ReleaseEligibilityCertificateV1, so a
  Draft run can still produce a portfolio handoff.

Do not close any of these by weakening the assertion, deleting the test,
hiding the frontend button, or flipping a config default. The spec's
Section 4 target contract (SignedPublicationSnapshotV1,
AuthenticatedSignerPrincipalV1, SignatureEventV1,
ReleaseEligibilityCertificateV1, ExecutionInstructionSnapshotV1) is the real
closure bar.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from database import Base  # noqa: E402
from models.mandates import Mandate  # noqa: E402,F401
from models.review import RecommendationRun  # noqa: E402

import routers.review as review_router  # noqa: E402
from routers.review import create_document, sign_document  # noqa: E402
from routers.pdf_reports import _build_protokoll_data  # noqa: E402
from routers.portfolio_handoff import create_portfolio_handoff  # noqa: E402
from schemas.review import ContractDocumentCreate, ContractDocumentSign  # noqa: E402
from schemas.portfolio_handoff import PortfolioHandoffCreate  # noqa: E402

from test_runtime_contracts import (  # noqa: E402
    _ADVISOR_SIGNATURE_PNG,
    _CLIENT_SIGNATURE_PNG,
    _FakeSignRequest,
    advisor_user,
    seed_client_and_mandate,
    session_factory,
)
from test_portfolio_handoff import (  # noqa: E402,F401
    _drift,
    _FakeRequest,
    _patch_engine,
    _seed_mandate_and_run,
)


# ---------------------------------------------------------------------------
# SIGN-IDENTITY-001 -- the sole authenticated advisor principal can also
# claim the client signature role on the same endpoint.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="SIGN-IDENTITY-001 -- CERT-SIGNED-PUBLICATION-001")
def test_advisor_principal_cannot_sign_as_client(session_factory, advisor_user, monkeypatch):
    _, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    with session_factory() as session:
        doc = create_document(
            request=_FakeSignRequest(),
            mandate_id=mandate_id,
            body=ContractDocumentCreate(
                document_type="Anlagestrategie",
                title="Strategie 2026",
            ),
            db=session,
            current_user=advisor_user,
        )
        monkeypatch.setattr(review_router, "_now", lambda: "2026-10-09T09:00:00.000Z")

        # Soll: an advisor-only authenticated principal has no client
        # identity and must be rejected (403) when it claims the client
        # signature role. There is no separately authenticated client
        # principal here -- it is literally the same advisor_user as the
        # Berater call would use.
        with pytest.raises(HTTPException) as exc_info:
            sign_document(
                mandate_id=mandate_id,
                doc_id=doc.id,
                body=ContractDocumentSign(
                    signed_by_client=True,
                    signature_image=_CLIENT_SIGNATURE_PNG,
                    signer_name="Daniel Kunde",
                ),
                request=_FakeSignRequest("10.0.0.9"),
                db=session,
                current_user=advisor_user,
            )
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# SIGN-CONTEXT-001 -- an empty draft with no archived PDF, checksum,
# content hash, recommendation, allocation or release binding is signable.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="SIGN-CONTEXT-001 -- CERT-SIGNED-PUBLICATION-001")
def test_document_without_archived_bytes_or_decision_context_is_not_signable(
    session_factory, advisor_user, monkeypatch
):
    _, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    with session_factory() as session:
        doc = create_document(
            request=_FakeSignRequest(),
            mandate_id=mandate_id,
            body=ContractDocumentCreate(
                document_type="Anlagestrategie",
                title="Strategie 2026",
            ),
            db=session,
            current_user=advisor_user,
        )
        # Confirms the gap this test targets: create_document() has no
        # pdf_base64/checksum_sha256/content_hash requirement at all.
        assert doc.pdf_base64 is None
        assert doc.checksum_sha256 is None
        assert doc.content_hash is None
        assert doc.status == "Entwurf"

        monkeypatch.setattr(review_router, "_now", lambda: "2026-10-09T09:00:00.000Z")

        # Soll: a document with no archived signable artefact (empty
        # draft) must not be acceptable to sign_document().
        with pytest.raises(HTTPException) as exc_info:
            sign_document(
                mandate_id=mandate_id,
                doc_id=doc.id,
                body=ContractDocumentSign(
                    signed_by_advisor=True,
                    signature_image=_ADVISOR_SIGNATURE_PNG,
                    signer_name="Anna Berater",
                ),
                request=_FakeSignRequest("10.0.0.5"),
                db=session,
                current_user=advisor_user,
            )
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# SIGN-HASH-001 -- a deliberately wrong SHA-256 checksum on otherwise
# present archived PDF bytes does not block the signature.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="SIGN-HASH-001 -- CERT-SIGNED-PUBLICATION-001")
def test_checksum_mismatch_blocks_signature(session_factory, advisor_user, monkeypatch):
    _, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    with session_factory() as session:
        doc = create_document(
            request=_FakeSignRequest(),
            mandate_id=mandate_id,
            body=ContractDocumentCreate(
                document_type="Anlagestrategie",
                title="Strategie 2026",
            ),
            db=session,
            current_user=advisor_user,
        )
        # Simulate an already-archived document (as services/document_
        # archive.py::archive_generated_pdf would produce): real PDF bytes
        # are present, but checksum_sha256 is deliberately wrong (does not
        # match the actual bytes) -- exactly the SIGN-HASH-001 scenario
        # from the spec's section 3.3.
        real_pdf_bytes = b"%PDF-1.4 fake but real bytes for hashing\n%%EOF"
        correct_checksum = hashlib.sha256(real_pdf_bytes).hexdigest()
        wrong_checksum = hashlib.sha256(b"not the same bytes at all").hexdigest()
        assert wrong_checksum != correct_checksum

        import base64
        doc.pdf_base64 = base64.b64encode(real_pdf_bytes).decode("ascii")
        doc.checksum_sha256 = wrong_checksum
        doc.content_hash = "arbitrary-content-hash-does-not-matter-here"
        doc.status = "Bereit zur Unterzeichnung"
        session.commit()
        session.refresh(doc)

        monkeypatch.setattr(review_router, "_now", lambda: "2026-10-09T09:00:00.000Z")

        # Soll: sign_document() must recompute SHA-256 over doc.pdf_base64
        # and refuse to sign when it disagrees with the stored
        # checksum_sha256 -- a byte/checksum drift must block, not pass
        # silently through to a valid signature.
        with pytest.raises(HTTPException) as exc_info:
            sign_document(
                mandate_id=mandate_id,
                doc_id=doc.id,
                body=ContractDocumentSign(
                    signed_by_advisor=True,
                    signature_image=_ADVISOR_SIGNATURE_PNG,
                    signer_name="Anna Berater",
                ),
                request=_FakeSignRequest("10.0.0.5"),
                db=session,
                current_user=advisor_user,
            )
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# SIGN-CLAIM-001 -- the "final" contract sign-off adopts the time-wise
# latest RecommendationRun as the final recommendation even when it is
# Draft, with no result_status == "Final" filter.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="SIGN-CLAIM-001 -- CERT-SIGNED-PUBLICATION-001")
def test_draft_recommendation_is_not_published_as_final_in_contract_signoff(
    session_factory, advisor_user
):
    _, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        draft_run = RecommendationRun(
            id="run-draft-1",
            mandate_id=mandate_id,
            client_id=mandate.client_id,
            policy_id="policy-1",
            run_type="Initial",
            objective_summary="Unreviewed draft objective -- not approved yet",
            result_status="Draft",
            created_by=advisor_user.id,
            created_at="2026-10-09T09:00:00.000Z",
            updated_at="2026-10-09T09:00:00.000Z",
        )
        session.add(draft_run)
        session.commit()

        protocol = _build_protokoll_data(mandate, session)

        # Soll: with no Final run in existence, the "final customer
        # sign-off" must not surface a Draft's objective_summary (or its
        # raw status string) as the final recommendation claim -- it
        # should be None/not_evidenced instead.
        assert protocol.latest_recommendation_summary is None


# ---------------------------------------------------------------------------
# SIGN-ELIGIBILITY-001 -- a Draft RecommendationRun can still be handed off
# to the portfolio execution desk; no shared release certificate is
# required.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="SIGN-ELIGIBILITY-001 -- CERT-SIGNED-PUBLICATION-001")
def test_draft_recommendation_run_cannot_produce_portfolio_handoff(
    session_factory, advisor_user, monkeypatch
):
    _seed_mandate_and_run(session_factory, advisor_user)
    with session_factory() as session:
        run = session.query(RecommendationRun).filter(RecommendationRun.id == "run-1").one()
        run.result_status = "Draft"
        session.commit()

    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])

    with session_factory() as session:
        # Soll: create_portfolio_handoff() must require result_status ==
        # "Final" (plus, per the spec's full target contract, a valid
        # shared ReleaseEligibilityCertificateV1) before producing an
        # execution handoff -- a Draft run must be rejected with 409, not
        # silently converted into a trade list sent to the execution desk.
        with pytest.raises(HTTPException) as exc_info:
            create_portfolio_handoff(
                mandate_id="mandate-1",
                run_id="run-1",
                body=PortfolioHandoffCreate(recipient_name="Bank XY Trading Desk"),
                request=_FakeRequest(),
                db=session,
                current_user=advisor_user,
            )
        assert exc_info.value.status_code == 409
