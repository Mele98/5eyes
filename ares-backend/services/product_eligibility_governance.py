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
    "supersedes_id",
)

# N-855-7 (2026-11): valid_to ist ein Lebenszyklus-Feld. Es wird erst bei der
# Abloesung durch eine Folgeregel gesetzt (approve_rule) und separat im
# Audit-Log gefuehrt. Im Hash steht es weiter mit seinem verfassten Wert
# None -- so bleibt jeder bestehende rule_hash byte-gleich (alle
# Autorenpfade setzen valid_to=None) und laesst sich nach der Abloesung
# weiter aus der Zeile nachrechnen.
RULE_LIFECYCLE_FIELDS: tuple[str, ...] = ("valid_to",)

# Quelle der Tenant-Produktregeln (Erfassen, Import, Re-Import); Teil des
# rule_hash. Hier definiert, damit approve_rule den Hash nach dem Setzen von
# valid_from neu binden kann; services.product_eligibility re-exportiert ihn.
TENANT_PRODUCT_RULE_SOURCE = "tenant_product_creation_v1"

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


def parse_utc_timestamp(value) -> datetime | None:
    """ISO-Zeitstempel ('Z' oder '+00:00', mit/ohne Sekundenbruchteil) bzw.
    datetime -> aware UTC-datetime; naive Werte gelten als UTC. Unlesbar oder
    leer -> None. Fuer robuste Zeitvergleiche statt String-Vergleich."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
    for field in RULE_LIFECYCLE_FIELDS:
        payload[field] = None
    payload["source"] = source
    return canonical_hash(payload)


def rule_hash_from_row(rule, *, source: str | None) -> str:
    """N-855-7: rule_hash einer gespeicherten Regel aus ihrer Zeile
    nachrechnen (verfasster Policy-Hash, bei Freigabe mit approval_mode
    gebunden). Gleiche Regel wie beim Verfassen und Freigeben."""
    authored = compute_rule_hash({field: getattr(rule, field) for field in RULE_POLICY_FIELDS}, source=source)
    if rule.approval_mode:
        return approval_bound_rule_hash(authored, rule.approval_mode)
    return authored


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


APPROVAL_MODE_FOUR_EYES = "four_eyes"
APPROVAL_MODE_SINGLE_APPROVER_ATTESTED = "single_approver_attested"
APPROVER_ROLES: tuple[str, ...] = ("admin", "super_admin")
MIN_ATTESTATION_REASON_LENGTH = 20


def tenant_approver_ids(db: Session, tenant_id: str | None,
                        roles: tuple[str, ...] = APPROVER_ROLES) -> list[str]:
    """Active users of `tenant_id` holding the approval right (default: the
    roles services.auth.require_admin admits; product eligibility overrides
    pass the roles of require_advisor). Users without tenant_id belong to
    DEFAULT_TENANT_ID, exactly like services.auth._resolve_tenant_id_for_user."""
    from models.tenant import DEFAULT_TENANT_ID
    from models.users import User

    if tenant_id is None:
        return []
    query = db.query(User.id).filter(
        User.role.in_(roles),
        User.is_active == 1,
        User.deleted_at.is_(None),
    )
    if tenant_id == DEFAULT_TENANT_ID:
        query = query.filter((User.tenant_id.is_(None)) | (User.tenant_id == "") | (User.tenant_id == tenant_id))
    else:
        query = query.filter(User.tenant_id == tenant_id)
    return sorted(str(row[0]) for row in query.all())


def approval_bound_rule_hash(authored_rule_hash: str, approval_mode: str) -> str:
    """The approval mode becomes part of the persisted rule_hash: the
    authored policy hash (all policy fields) chained with the mode, so a
    single-approver attestation is distinguishable in every decision that
    references the hash."""
    from services.product_eligibility import canonical_hash

    return canonical_hash({
        "authored_rule_hash": authored_rule_hash,
        "approval_mode": approval_mode,
    })


def approve_rule(
    db: Session,
    *,
    rule_id: str,
    approver_id: str,
    tenant_id: str | None,
    now: str | None = None,
    single_approver_attestation: bool = False,
    attestation_reason: str | None = None,
) -> ProductEligibilityRule:
    """Approve a draft rule (and its still-draft rule set).

    Default is four-eyes: the approver must differ from the author of the
    rule and of a still-draft rule set.

    Single-approver exception (CIO decision 2026-10-22, fail-closed): the
    author may approve their own rule only if (1) the tenant has EXACTLY ONE
    active approver and that approver is the author, (2)
    `single_approver_attestation` is true and (3) a reason of at least
    MIN_ATTESTATION_REASON_LENGTH characters is given. The rule is then
    stored with approval_mode='single_approver_attested' (part of
    rule_hash). With two or more approvers the author always gets
    RuleApprovalConflict (HTTP 409).

    Raises ``LookupError`` if the rule is not visible to ``tenant_id``.
    """
    rule = db.get(ProductEligibilityRule, rule_id)
    rule_set = db.get(ProductEligibilityRuleSet, rule.rule_set_id) if rule else None
    if rule is None or rule_set is None or not rule_visible_to_tenant(rule, rule_set, tenant_id):
        raise LookupError("Eignungsregel nicht gefunden.")
    if rule.status != "draft":
        raise RuleApprovalConflict(
            f"Eignungsregel ist nicht im Entwurfsstatus (Status: {rule.status})."
        )
    if rule_set.status not in ("draft", "approved"):
        raise RuleApprovalConflict(
            f"Regelset ist nicht genehmigungsfaehig (Status: {rule_set.status})."
        )
    if not approver_id:
        raise RuleApprovalConflict("Genehmiger fehlt.")
    self_approval = approver_id == rule.created_by or (
        rule_set.status == "draft" and approver_id == rule_set.created_by
    )
    if not self_approval:
        approval_mode = APPROVAL_MODE_FOUR_EYES
    else:
        if not single_approver_attestation:
            raise RuleApprovalConflict(
                "Vier-Augen-Prinzip: Die Eignungsregel muss von einer anderen Person "
                "genehmigt werden als von ihrem Autor."
            )
        if len((attestation_reason or "").strip()) < MIN_ATTESTATION_REASON_LENGTH:
            raise RuleApprovalConflict(
                "Einzelfreigabe braucht eine Begruendung "
                f"(mindestens {MIN_ATTESTATION_REASON_LENGTH} Zeichen)."
            )
        approvers = tenant_approver_ids(db, tenant_id)
        if approvers != [approver_id]:
            raise RuleApprovalConflict(
                "Einzelfreigabe ist nur zulaessig, wenn die Verwaltung genau eine "
                "freigabeberechtigte Person hat. Hier sind "
                f"{len(approvers)} freigabeberechtigt -- bitte eine andere Person "
                "freigeben lassen."
            )
        approval_mode = APPROVAL_MODE_SINGLE_APPROVER_ATTESTED
    now = now or _now_iso()
    if rule_set.status == "draft":
        rule_set.status = "approved"
        rule_set.approved_by = approver_id
        rule_set.approved_at = now
        rule_set.updated_at = now
    previous = None
    if rule.supersedes_id:
        candidate = db.get(ProductEligibilityRule, rule.supersedes_id)
        if (
            candidate is not None
            and candidate.status == "approved"
            and candidate.product_id == rule.product_id
            and candidate.jurisdiction == rule.jurisdiction
        ):
            previous = candidate
    authored_hash = rule.rule_hash
    if previous is not None:
        # N-855-7: valid_from der Folgeregel VOR dem Binden setzen und den
        # verfassten Hash neu rechnen, damit rule_hash aus der Zeile
        # reproduzierbar bleibt. Fail-closed, wenn der Entwurf nicht aus dem
        # Tenant-Produktpfad stammt (Quelle nicht nachweisbar).
        if compute_rule_hash(
            {field: getattr(rule, field) for field in RULE_POLICY_FIELDS}, source=TENANT_PRODUCT_RULE_SOURCE,
        ) != rule.rule_hash:
            raise RuleApprovalConflict(
                "Folgeregel: verfasster rule_hash nicht nachvollziehbar, Freigabe abgelehnt."
            )
        rule.valid_from = now
        authored_hash = compute_rule_hash(
            {field: getattr(rule, field) for field in RULE_POLICY_FIELDS}, source=TENANT_PRODUCT_RULE_SOURCE,
        )
    rule.status = "approved"
    rule.approved_by = approver_id
    rule.approved_at = now
    rule.approval_mode = approval_mode
    rule.rule_hash = approval_bound_rule_hash(authored_hash, approval_mode)
    rule.updated_at = now
    # AUDIT-FIX Fondsuniversum R7/F3 (2026-11): ein Folge-Entwurf aus dem
    # Re-Import (supersedes_id) loest die bisher freigegebene Regel desselben
    # Produkts erst JETZT ab -- sonst waeren zwei exakte Regeln aktiv
    # (AMBIGUOUS_RULE_MATCH).
    # N-855-2: Point-in-Time korrekt -- die alte Regel gilt bis zur Freigabe
    # (valid_to = Freigabezeitpunkt), die neue ab der Freigabe (valid_from),
    # nicht ab dem Import. rule_hash bleibt bei beiden der Hash der verfassten
    # bzw. freigegebenen Policy; der Wechsel der Geltung ist ein
    # Lebenszyklus-Ereignis und steht im Audit-Log.
    # N-855-7: valid_to ist Lebenszyklus-Feld (RULE_LIFECYCLE_FIELDS), der
    # rule_hash der alten Regel bleibt daher nachrechenbar.
    if previous is not None:
        previous.status = "retired"
        previous.valid_to = now
        previous.updated_at = now
    db.flush()
    return rule

