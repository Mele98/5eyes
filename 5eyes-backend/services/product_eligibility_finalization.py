"""ELIG-FINAL-001 -- Finalize re-evaluates the product eligibility of every
aggregated position with the same core Generate uses.

Before, `_validate_recommendation_for_finalization()` only checked that a
position's product exists and is active. A manually added position
(POST .../positions only applies the preference matcher) or a product
whose governed rule demands appropriateness/override evidence could be
finalized without any of it.

Now, per product (weights of several positions of the same product are
summed first):

* `evaluate_product_eligibility()` with the mandate's service mode, tenant,
  jurisdiction and the run's risk-score bucket;
* appropriateness evidence = the latest "Angemessenheitsprüfung" bound to
  THIS run and carrying a knowledge anchor (ELIG-KNOWLEDGE-001);
* override evidence = a `ProductEligibilityOverride` bound to this run,
  product and matched rule, inside its validity window and approved by a
  second person (four-eyes).

Every non-eligible dimension is a finalize error, with two documented
exceptions that stay warnings until the owner decides:

* `POSITION_LIMIT_EXCEEDED` (ELIG-LIMIT-001): the default catalog caps are
  exceeded by most standard generated runs; blocking needs a decision on
  the caps or on Generate's product split first.
* `KNOWLEDGE_COVERAGE_MISSING`: owner rule "knowledge gap = hint, not a
  block" until the open owner point is decided.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from models.mandates import Mandate
from models.product_eligibility import ProductEligibilityOverride
from models.profiling import RiskAssessment, SuitabilityCheck
from models.review import Product, RecommendationPosition, RecommendationRun
from services.product_eligibility import (
    derive_service_mode,
    evaluate_product_eligibility,
    mandate_tenant_id,
)

APPROPRIATENESS_DUTY = "Angemessenheitsprüfung"

# Reason codes that are reported as warnings only (see module docstring).
WARNING_ONLY_REASON_CODES = frozenset({"POSITION_LIMIT_EXCEEDED", "KNOWLEDGE_COVERAGE_MISSING"})

_REASON_TEXT = {
    "NO_GOVERNED_RULE": "keine freigegebene Eignungsregel",
    "AMBIGUOUS_RULE_MATCH": "mehrdeutige Eignungsregeln",
    "PRODUCT_PROHIBITED": "Produkt ist gesperrt",
    "RISK_BAND_MISMATCH": "ausserhalb des Risikobands der Eignungsregel",
    "NO_SERVICE_MODE_DECLARED": "Eignungsregel nennt keine Dienstleistung",
    "SERVICE_MODE_NOT_PERMITTED": "fuer diese Dienstleistung nicht freigegeben",
    "KNOWLEDGE_COVERAGE_MISSING": "Kenntnis-Abdeckung nicht belegt",
    "APPROPRIATENESS_EVIDENCE_MISSING": (
        "Angemessenheitspruefung zu dieser Empfehlung fehlt (mit Kenntnis-Nachweis erfassen)"
    ),
    "APPROPRIATENESS_NOT_POSITIVE": "Angemessenheitspruefung ist nicht positiv",
    "OVERRIDE_EVIDENCE_MISSING": "gueltiger Override-Nachweis (Vier-Augen) fehlt",
    "POSITION_LIMIT_EXCEEDED": "Positionsdeckel ueberschritten",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _appropriateness_result(db: Session, mandate: Mandate, run: RecommendationRun) -> str | None:
    check = (
        db.query(SuitabilityCheck)
        .filter(
            SuitabilityCheck.mandate_id == mandate.id,
            SuitabilityCheck.recommendation_run_id == run.id,
            SuitabilityCheck.duty_type == APPROPRIATENESS_DUTY,
        )
        .order_by(SuitabilityCheck.checked_at.desc(), SuitabilityCheck.created_at.desc())
        .first()
    )
    if check is None:
        return None
    if check.result == "Angemessen" and not (check.knowledge_assessment_id or check.risk_assessment_id):
        # Legacy positive row without knowledge anchor is no evidence.
        return None
    return str(check.result)


def _valid_override(
    db: Session, run: RecommendationRun, product_id: str, now: str,
) -> ProductEligibilityOverride | None:
    rows = (
        db.query(ProductEligibilityOverride)
        .filter(
            ProductEligibilityOverride.recommendation_run_id == run.id,
            ProductEligibilityOverride.product_id == product_id,
        )
        .order_by(ProductEligibilityOverride.created_at.desc())
        .all()
    )
    for row in rows:
        if not (row.evidence_hash and row.requested_by and row.approved_by):
            continue
        if row.approved_by == row.requested_by:
            continue
        if not (str(row.valid_from) <= now < str(row.expires_at)):
            continue
        return row
    return None


def _aggregate(positions: Iterable[RecommendationPosition]) -> dict[str, int]:
    weights: dict[str, int] = {}
    for position in positions:
        if position.product_id:
            weights[position.product_id] = weights.get(position.product_id, 0) + int(position.target_weight_bps or 0)
    return weights


def finalization_eligibility_findings(
    db: Session,
    *,
    mandate: Mandate,
    run: RecommendationRun,
    assessment: RiskAssessment,
    positions: Iterable[RecommendationPosition],
    products: dict[str, Product],
) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for the product eligibility of the run's
    aggregated positions. Inactive/missing products are reported by the
    caller and skipped here."""
    from services.portfolio_engine import _risk_score_bucket

    errors: list[str] = []
    warnings: list[str] = []
    try:
        score_bucket = _risk_score_bucket(assessment)
    except ValueError as exc:
        return [f"Produkteignung nicht pruefbar: Risikoprofil-Score unlesbar ({exc})."], warnings

    service_mode = derive_service_mode(mandate)
    tenant_id = mandate_tenant_id(mandate)
    jurisdiction = getattr(mandate, "jurisdiction", None) or "CH"
    appropriateness = _appropriateness_result(db, mandate, run)
    now = _now_iso()

    for product_id, weight in sorted(_aggregate(positions).items()):
        product = products.get(product_id)
        if product is None or product.deleted_at is not None or int(product.is_active or 0) != 1:
            continue
        override = _valid_override(db, run, product_id, now)
        decision = evaluate_product_eligibility(
            db,
            product=product,
            service_mode=service_mode,
            score_bucket=score_bucket,
            aggregated_weight_bps=weight,
            source_sub_allocations=[],
            jurisdiction=jurisdiction,
            tenant_id=tenant_id,
            appropriateness_result=appropriateness,
            override_evidence={"override_id": override.id, "rule_id": override.rule_id} if override else None,
        )
        reason_codes = list(decision.reason_codes)
        if override is not None and override.rule_id != decision.matched_rule_id and decision.matched_rule_id:
            # Override bound to another rule is no evidence for this one.
            reason_codes.append("OVERRIDE_EVIDENCE_MISSING")
        blocking = [code for code in reason_codes if code not in WARNING_ONLY_REASON_CODES]
        soft = [code for code in reason_codes if code in WARNING_ONLY_REASON_CODES]
        name = product.product_name or product_id
        if blocking:
            texts = "; ".join(_REASON_TEXT.get(code, code) for code in dict.fromkeys(blocking))
            errors.append(f"Produkteignung {name}: {texts} [{', '.join(dict.fromkeys(blocking))}].")
        for code in dict.fromkeys(soft):
            detail = _REASON_TEXT.get(code, code)
            if code == "POSITION_LIMIT_EXCEEDED":
                detail += f" ({weight} bps, Deckel {decision.position_limit_bps} bps)"
            warnings.append(f"Produkteignung {name}: {detail} [{code}].")
    return errors, warnings
