"""ELIG-GOVERNANCE-001 / ELIG-TENANT-SCOPE-001 / ELIG-CATEGORY-SELECTOR-001
(Codex-Audit 2026-10-09/13, Fix 2026-10-21) -- governance primitives for
governed product eligibility rules.

Kept separate from services/product_eligibility.py (evaluator core) so the
rules about *which* rule may count as evidence live in one place:

* ``compute_rule_hash()`` -- the persisted ``rule_hash`` covers EVERY
  policy-relevant field. Before, it covered only rule_set_id/product_id/
  band/service_modes/source: tightening ``max_position_bps`` or switching
  on ``requires_appropriateness`` left the hash unchanged, so the hash was
  no evidence of the policy that was actually applied.
* ``selector_matches_product()`` -- a ``product_category_selector`` is a
  JSON object of exact attribute matches. Before, ANY global selector rule
  matched EVERY product (the selector content was never read).
* ``approve_rule()`` -- four-eyes approval: the approver must differ from
  the author of the rule and of a still-draft rule set (HTTP 409 otherwise).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.product_eligibility import ProductEligibilityRule, ProductEligibilityRuleSet

# Every column that changes what a rule permits/blocks. Governance metadata
# (status, created_by, approved_by, approved_at, timestamps, id) is
# deliberately NOT part of the hash: approving a rule must not change the
# evidence hash of the policy that was reviewed.
RULE_POLICY_FIELDS: tuple[str, ...] = (
    "rule_set_id",
    "version",
    "product_id",
    "product_category_selector",
    "tenant_scope",
    "tenant_id",
    "jurisdiction",
    "client_classifications_json",
    "service_modes_json",
    "profile_from",
    "profile_to",
    "requires_knowledge_categories_json",
    "minimum_experience_level",
    "requires_appropriateness",
    "requires_suitability",
    "requires_override",
    "max_position_bps",
    "prohibited",
    "valid_from",
    "valid_to",
    "supersedes_id",
)

# Product attributes a category selector may address. Exact string equality
# only; any other key makes the selector unmatchable (fail-closed: an
# unknown key must never be silently ignored and widen the match).
SELECTOR_ATTRIBUTES: frozenset[str] = frozenset({
    "asset_class",
    "sub_asset_class",
    "product_type",
    "currency",
    "jurisdiction",
})


class RuleApprovalConflict(Exception):
    """Four-eyes violation or invalid approval state (router maps to 409)."""


def _canonical_json_field(value):
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def compute_rule_hash(values: dict, *, source: str | None = None) -> str:
    from services.product_eligibility import canonical_hash

    payload = {}
    for field in RULE_POLICY_FIELDS:
        value = values.get(field)
        if field.endswith("_json") or field == "product_category_selector":
            value = _canonical_json_field(value)
        payload[field] = value
    payload["source"] = source
    return canonical_hash(payload)


def selector_matches_product(selector: str | None, product) -> bool:
    if not selector:
        return False
    try:
        parsed = json.loads(selector)
    except (TypeError, ValueError):
        return False
    if not isinstance(parsed, dict) or not parsed:
        return False
    for key, expected in parsed.items():
        if key not in SELECTOR_ATTRIBUTES or not isinstance(expected, str):
            return False
        actual = getattr(product, key, None)
        if actual is None or str(actual) != expected:
            return False
    return True


def rule_visible_to_tenant(
    rule: ProductEligibilityRule,
    rule_set: ProductEligibilityRuleSet,
    tenant_id: str | None,
) -> bool:
    """Application-side mirror of the Postgres RLS predicate
    (services/postgres_rls.py: ``tenant_id = current tenant``), applied to
    the rule AND its RuleSet so SQLite installs get the same isolation:

    * ``tenant_scope='global'`` with ``tenant_id`` NULL -> every tenant.
    * any row carrying a ``tenant_id`` (tenant-scoped, or a per-tenant
      provisioned copy of a global rule as Postgres requires) -> exactly
      that tenant, never another one and never a call without tenant.
    * any other scope value -> nobody (fail-closed).
    """
    for scoped in (rule, rule_set):
        scope = str(scoped.tenant_scope or "")
        if scope not in ("global", "tenant"):
            return False
        if scope == "global" and scoped.tenant_id is None:
            continue
        if tenant_id is None or scoped.tenant_id != tenant_id:
            return False
    return True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def approve_rule(
    db: Session,
    *,
    rule_id: str,
    approver_id: str,
    tenant_id: str | None,
    now: str | None = None,
) -> ProductEligibilityRule:
    """Approve a draft rule (and its still-draft rule set) under four-eyes.

    Raises ``LookupError`` if the rule is not visible to ``tenant_id`` and
    ``RuleApprovalConflict`` if the approver authored the rule or the draft
    rule set, or if the rule is not in draft state.
    """
    rule = db.get(ProductEligibilityRule, rule_id)
    rule_set = db.get(ProductEligibilityRuleSet, rule.rule_set_id) if rule else None
    if rule is None or rule_set is None or not rule_visible_to_tenant(rule, rule_set, tenant_id):
        raise LookupError("Eignungsregel nicht gefunden.")
    if rule.status != "draft":
        raise RuleApprovalConflict(
            f"Eignungsregel ist nicht im Entwurfsstatus (Status: {rule.status})."
        )
    if not approver_id or approver_id == rule.created_by:
        raise RuleApprovalConflict(
            "Vier-Augen-Prinzip: Die Eignungsregel muss von einer anderen Person "
            "genehmigt werden als von ihrem Autor."
        )
    if rule_set.status == "draft" and approver_id == rule_set.created_by:
        raise RuleApprovalConflict(
            "Vier-Augen-Prinzip: Das Regelset muss von einer anderen Person "
            "genehmigt werden als von seinem Autor."
        )
    if rule_set.status not in ("draft", "approved"):
        raise RuleApprovalConflict(
            f"Regelset ist nicht genehmigungsfaehig (Status: {rule_set.status})."
        )
    now = now or _now_iso()
    if rule_set.status == "draft":
        rule_set.status = "approved"
        rule_set.approved_by = approver_id
        rule_set.approved_at = now
        rule_set.updated_at = now
    rule.status = "approved"
    rule.approved_by = approver_id
    rule.approved_at = now
    rule.updated_at = now
    db.flush()
    return rule
