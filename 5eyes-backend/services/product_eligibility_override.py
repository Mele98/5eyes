"""ELIG-OVERRIDE-CAPTURE-001 -- capture path for product eligibility overrides.

A governed rule with ``requires_override=1`` makes a product usable only
with a documented advisor override. Finalize (ELIG-FINAL-001) accepts an
override only if it is bound to run, product and matched rule, inside its
validity window and approved by a second person (four-eyes). Before this
module nothing could create such a row, so these products stayed blocked
for good.

Flow (append-only, never UPDATE/DELETE):

1. ``request``: an advisor/admin of the mandate records the override with a
   reason. Stored with ``approved_by = ""`` -- a pending request is no
   evidence.
2. ``approve``: a DIFFERENT advisor/admin approves it. This inserts a new
   row (requester, approver, reason copied, ``policy_basis`` =
   ``approval_of:<request id>``, ``approval_mode='four_eyes'``) that is the
   evidence. A request is approved at most once.

   Single-approver exception (ELIG-OVERRIDE-SINGLE-APPROVER-001, CIO
   decision 2026-10-27), the same conditions as the rule approval
   (services/product_eligibility_governance.py::approve_rule): the
   requester may confirm their own request only with an explicit
   attestation, a reason of at least MIN_ATTESTATION_REASON_LENGTH
   characters, and if the mandate's tenant has EXACTLY ONE active person
   entitled to approve (OVERRIDE_APPROVER_ROLES, the roles
   ``require_advisor`` admits) and that person is the requester. Stored as
   ``approval_mode='single_approver_attested'`` (part of the evidence hash),
   the attestation reason goes to the audit log.

The table is append-only in the database as well (triggers, see
services/product_eligibility_override_schema.py).

Every row carries ``evidence_hash`` = hash over its own fields plus the
*decision binding hash*: the identity of the eligibility decision it
overrides (run, mandate, product, matched rule id/version/hash, service
mode, risk-score bucket, risk assessment, jurisdiction, tenant). Finalize
recomputes the binding from the CURRENT decision; a new rule version, a new
risk profile or another service mode yields a different binding, so an old
override no longer verifies (stale => blocked). A tampered row fails the
same check. Each step is also written to the immutable ``audit_log``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from database import new_uuid
from models.mandates import Mandate
from models.product_eligibility import ProductEligibilityOverride
from models.profiling import RiskAssessment
from models.review import Product, RecommendationPosition, RecommendationRun
from schemas.product_eligibility import ProductEligibilityDecisionV1
from services.product_eligibility import (
    canonical_hash,
    derive_service_mode,
    evaluate_product_eligibility,
    mandate_tenant_id,
)
from services.product_eligibility_governance import (
    APPROVAL_MODE_FOUR_EYES,
    APPROVAL_MODE_SINGLE_APPROVER_ATTESTED,
    MIN_ATTESTATION_REASON_LENGTH,
    tenant_approver_ids,
)

OVERRIDE_REASON_CODE = "ADVISOR_DOCUMENTED_EXCEPTION"
OVERRIDDEN_DIMENSION = "override"
MIN_OVERRIDE_REASON_LENGTH = 20
# Owner decision pending: validity window of an approved override.
OVERRIDE_VALIDITY_DAYS = 30
OVERRIDE_MISSING_CODE = "OVERRIDE_EVIDENCE_MISSING"
APPROVAL_PREFIX = "approval_of:"
# Roles admitted by services.auth.require_advisor, i.e. who may approve.
OVERRIDE_APPROVER_ROLES: tuple[str, ...] = ("admin", "advisor")


class OverrideConflict(Exception):
    """Business-rule conflict (HTTP 409); ``code`` is machine readable."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DecisionContext:
    mandate: Mandate
    run: RecommendationRun
    assessment: RiskAssessment
    service_mode: str
    score_bucket: int
    jurisdiction: str
    tenant_id: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def decision_context(db: Session, mandate: Mandate, run: RecommendationRun,
                     assessment: RiskAssessment | None = None) -> DecisionContext:
    """Same inputs Finalize uses for ``evaluate_product_eligibility()``."""
    from services.portfolio_engine import _risk_score_bucket

    if assessment is None:
        assessment = db.query(RiskAssessment).filter(
            RiskAssessment.id == run.assessment_id,
            RiskAssessment.mandate_id == mandate.id,
            RiskAssessment.deleted_at.is_(None),
        ).first() if run.assessment_id else None
    if assessment is None:
        raise OverrideConflict("RISK_ASSESSMENT_MISSING", "Empfehlung hat kein gueltiges Risikoprofil.")
    try:
        score_bucket = _risk_score_bucket(assessment)
    except ValueError as exc:
        raise OverrideConflict("RISK_SCORE_UNREADABLE", f"Risikoprofil-Score unlesbar ({exc}).") from exc
    return DecisionContext(
        mandate=mandate,
        run=run,
        assessment=assessment,
        service_mode=derive_service_mode(mandate),
        score_bucket=score_bucket,
        jurisdiction=getattr(mandate, "jurisdiction", None) or "CH",
        tenant_id=mandate_tenant_id(mandate),
    )


def evaluate(db: Session, ctx: DecisionContext, product: Product, weight_bps: int,
             override_evidence: dict | None = None) -> ProductEligibilityDecisionV1:
    return evaluate_product_eligibility(
        db,
        product=product,
        service_mode=ctx.service_mode,
        score_bucket=ctx.score_bucket,
        aggregated_weight_bps=weight_bps,
        source_sub_allocations=[],
        jurisdiction=ctx.jurisdiction,
        tenant_id=ctx.tenant_id,
        override_evidence=override_evidence,
    )


def decision_binding_hash(ctx: DecisionContext, decision: ProductEligibilityDecisionV1) -> str:
    return canonical_hash({
        "run_id": ctx.run.id,
        "mandate_id": ctx.mandate.id,
        "product_id": decision.product_id,
        "matched_rule_id": decision.matched_rule_id,
        "matched_rule_version": decision.matched_rule_version,
        "matched_rule_hash": decision.matched_rule_hash,
        "service_mode": ctx.service_mode,
        "score_bucket": int(ctx.score_bucket),
        "assessment_id": ctx.assessment.id,
        "jurisdiction": ctx.jurisdiction,
        "tenant_id": ctx.tenant_id,
    })


def override_evidence_hash(row: ProductEligibilityOverride, binding_hash: str) -> str:
    payload = {
        "id": row.id,
        "decision_binding_hash": binding_hash,
        "recommendation_run_id": row.recommendation_run_id,
        "product_id": row.product_id,
        "rule_id": row.rule_id,
        "original_decision": row.original_decision,
        "overridden_dimension": row.overridden_dimension,
        "reason_code": row.reason_code,
        "reason_text": row.reason_text,
        "policy_basis": row.policy_basis,
        "requested_by": row.requested_by,
        "approved_by": row.approved_by,
        "valid_from": row.valid_from,
        "expires_at": row.expires_at,
    }
    # ELIG-OVERRIDE-SINGLE-APPROVER-001: the approval mode is bound into the
    # hash; omitted when unset, so rows without a mode keep their hash.
    if row.approval_mode:
        payload["approval_mode"] = row.approval_mode
    return canonical_hash(payload)


def is_valid_override(row: ProductEligibilityOverride, *, binding_hash: str,
                      matched_rule_id: str | None, now: str) -> bool:
    if not (row.requested_by and row.approved_by):
        return False
    if row.approved_by == row.requested_by and row.approval_mode != APPROVAL_MODE_SINGLE_APPROVER_ATTESTED:
        return False
    if not matched_rule_id or row.rule_id != matched_rule_id:
        return False
    if not (str(row.valid_from) <= now < str(row.expires_at)):
        return False
    return row.evidence_hash == override_evidence_hash(row, binding_hash)


def _rows(db: Session, run_id: str, product_id: str) -> list[ProductEligibilityOverride]:
    return (
        db.query(ProductEligibilityOverride)
        .filter(
            ProductEligibilityOverride.recommendation_run_id == run_id,
            ProductEligibilityOverride.product_id == product_id,
        )
        .order_by(ProductEligibilityOverride.created_at.desc())
        .all()
    )


def find_valid_override(db: Session, *, run_id: str, product_id: str, binding_hash: str,
                        matched_rule_id: str | None, now: str | None = None) -> ProductEligibilityOverride | None:
    now = now or _now_iso()
    for row in _rows(db, run_id, product_id):
        if is_valid_override(row, binding_hash=binding_hash, matched_rule_id=matched_rule_id, now=now):
            return row
    return None


def run_product_weights(positions: Iterable[RecommendationPosition]) -> dict[str, int]:
    weights: dict[str, int] = {}
    for position in positions:
        if position.product_id:
            weights[position.product_id] = weights.get(position.product_id, 0) + int(position.target_weight_bps or 0)
    return weights


def _override_required_decision(db: Session, ctx: DecisionContext, product_id: str):
    positions = db.query(RecommendationPosition).filter(RecommendationPosition.run_id == ctx.run.id).all()
    weight = run_product_weights(positions).get(product_id)
    product = db.get(Product, product_id) if weight is not None else None
    if product is None or product.deleted_at is not None:
        raise LookupError("Produkt ist nicht Teil dieser Empfehlung.")
    decision = evaluate(db, ctx, product, weight)
    if OVERRIDE_MISSING_CODE not in decision.reason_codes:
        raise OverrideConflict(
            "OVERRIDE_NOT_REQUIRED",
            "Fuer dieses Produkt verlangt die Eignungsregel keinen Override.",
        )
    return product, decision


def _insert(db: Session, *, ctx: DecisionContext, decision: ProductEligibilityDecisionV1, product_id: str,
            reason_text: str, requested_by: str, approved_by: str, valid_from: str, expires_at: str,
            now: str, policy_basis: str | None = None,
            approval_mode: str | None = None) -> ProductEligibilityOverride:
    row = ProductEligibilityOverride(
        id=new_uuid(),
        rule_id=decision.matched_rule_id,
        product_id=product_id,
        recommendation_run_id=ctx.run.id,
        original_decision=decision.decision,
        overridden_dimension=OVERRIDDEN_DIMENSION,
        reason_code=OVERRIDE_REASON_CODE,
        reason_text=reason_text,
        requested_by=requested_by,
        approved_by=approved_by,
        valid_from=valid_from,
        expires_at=expires_at,
        policy_basis=policy_basis,
        approval_mode=approval_mode,
        created_at=now,
        updated_at=now,
    )
    row.evidence_hash = override_evidence_hash(row, decision_binding_hash(ctx, decision))
    db.add(row)
    db.flush()
    return row


def request_override(db: Session, ctx: DecisionContext, *, product_id: str, reason_text: str,
                     requested_by: str, expected_decision_hash: str | None = None) -> ProductEligibilityOverride:
    reason = (reason_text or "").strip()
    if len(reason) < MIN_OVERRIDE_REASON_LENGTH:
        raise ValueError(f"Begruendung braucht mindestens {MIN_OVERRIDE_REASON_LENGTH} Zeichen.")
    if ctx.run.result_status != "Draft":
        raise OverrideConflict("RUN_NOT_DRAFT", "Overrides nur fuer Draft-Empfehlungen.")
    _product, decision = _override_required_decision(db, ctx, product_id)
    if expected_decision_hash and expected_decision_hash != decision_binding_hash(ctx, decision):
        raise OverrideConflict(
            "ELIGIBILITY_DECISION_CHANGED",
            "Die Eignungsentscheidung hat sich geaendert. Bitte neu laden.",
        )
    now = _now_iso()
    return _insert(
        db, ctx=ctx, decision=decision, product_id=product_id, reason_text=reason,
        requested_by=requested_by, approved_by="", valid_from=now, expires_at=now, now=now,
    )


def override_approver_ids(db: Session, ctx: DecisionContext) -> list[str]:
    """Active users of the mandate's tenant who may approve an override."""
    return tenant_approver_ids(db, ctx.tenant_id, roles=OVERRIDE_APPROVER_ROLES)


def _approval_mode(db: Session, ctx: DecisionContext, *, approver_id: str, requested_by: str,
                   single_approver_attestation: bool, attestation_reason: str | None) -> str:
    if approver_id != requested_by:
        return APPROVAL_MODE_FOUR_EYES
    if not single_approver_attestation:
        raise OverrideConflict(
            "FOUR_EYES_REQUIRED",
            "Vier-Augen-Prinzip: Der Override muss von einer anderen Person freigegeben werden.",
        )
    if len((attestation_reason or "").strip()) < MIN_ATTESTATION_REASON_LENGTH:
        raise OverrideConflict(
            "ATTESTATION_REASON_REQUIRED",
            f"Einzelfreigabe braucht eine Begruendung (mindestens {MIN_ATTESTATION_REASON_LENGTH} Zeichen).",
        )
    approvers = override_approver_ids(db, ctx)
    if approvers != [approver_id]:
        raise OverrideConflict(
            "FOUR_EYES_REQUIRED",
            "Einzelfreigabe ist nur zulaessig, wenn die Verwaltung genau eine freigabeberechtigte "
            f"Person hat. Hier sind {len(approvers)} freigabeberechtigt -- bitte eine andere "
            "Person freigeben lassen.",
        )
    return APPROVAL_MODE_SINGLE_APPROVER_ATTESTED


def approve_override(db: Session, ctx: DecisionContext, *, override_id: str, approver_id: str,
                     single_approver_attestation: bool = False,
                     attestation_reason: str | None = None) -> ProductEligibilityOverride:
    request = db.get(ProductEligibilityOverride, override_id)
    if request is None or request.recommendation_run_id != ctx.run.id:
        raise LookupError("Override-Antrag nicht gefunden.")
    approval_ref = APPROVAL_PREFIX + request.id
    if request.approved_by or any(row.policy_basis == approval_ref for row in _rows(db, ctx.run.id, request.product_id)):
        raise OverrideConflict("OVERRIDE_NOT_PENDING", "Dieser Eintrag ist kein offener Antrag.")
    if ctx.run.result_status != "Draft":
        raise OverrideConflict("RUN_NOT_DRAFT", "Overrides nur fuer Draft-Empfehlungen.")
    approval_mode = _approval_mode(
        db, ctx, approver_id=approver_id, requested_by=request.requested_by,
        single_approver_attestation=single_approver_attestation, attestation_reason=attestation_reason,
    )
    _product, decision = _override_required_decision(db, ctx, request.product_id)
    binding = decision_binding_hash(ctx, decision)
    if request.rule_id != decision.matched_rule_id or request.evidence_hash != override_evidence_hash(request, binding):
        raise OverrideConflict(
            "ELIGIBILITY_DECISION_CHANGED",
            "Der Antrag bezieht sich auf eine fruehere Eignungsentscheidung. Bitte neu beantragen.",
        )
    start = datetime.now(timezone.utc)
    now = start.isoformat()
    return _insert(
        db, ctx=ctx, decision=decision, product_id=request.product_id, reason_text=request.reason_text,
        requested_by=request.requested_by, approved_by=approver_id, valid_from=now,
        expires_at=(start + timedelta(days=OVERRIDE_VALIDITY_DAYS)).isoformat(), now=now,
        policy_basis=approval_ref, approval_mode=approval_mode,
    )


def override_overview(db: Session, ctx: DecisionContext) -> list[dict]:
    """Products of the run whose rule demands an override, with the current
    decision binding and every recorded row (newest first)."""
    positions = db.query(RecommendationPosition).filter(RecommendationPosition.run_id == ctx.run.id).all()
    now = _now_iso()
    items: list[dict] = []
    for product_id, weight in sorted(run_product_weights(positions).items()):
        product = db.get(Product, product_id)
        if product is None or product.deleted_at is not None:
            continue
        decision = evaluate(db, ctx, product, weight)
        if OVERRIDE_MISSING_CODE not in decision.reason_codes:
            continue
        binding = decision_binding_hash(ctx, decision)
        rows = []
        all_rows = _rows(db, ctx.run.id, product_id)
        approved_requests = {r.policy_basis[len(APPROVAL_PREFIX):] for r in all_rows
                             if r.approved_by and (r.policy_basis or "").startswith(APPROVAL_PREFIX)}
        for row in all_rows:
            current = row.rule_id == decision.matched_rule_id and row.evidence_hash == override_evidence_hash(row, binding)
            if not row.approved_by:
                state = "approved" if row.id in approved_requests else ("pending" if current else "stale")
            elif is_valid_override(row, binding_hash=binding, matched_rule_id=decision.matched_rule_id, now=now):
                state = "valid"
            else:
                state = "stale" if not current else "invalid"
            rows.append({
                "id": row.id, "state": state, "requested_by": row.requested_by,
                "approved_by": row.approved_by or None, "reason_text": row.reason_text,
                "approval_mode": row.approval_mode,
                "valid_from": row.valid_from, "expires_at": row.expires_at, "created_at": row.created_at,
            })
        items.append({
            "product_id": product_id,
            "product_name": product.product_name,
            "decision_hash": binding,
            "matched_rule_id": decision.matched_rule_id,
            "matched_rule_version": decision.matched_rule_version,
            "has_valid_override": any(r["state"] == "valid" for r in rows),
            "overrides": rows,
        })
    return items
