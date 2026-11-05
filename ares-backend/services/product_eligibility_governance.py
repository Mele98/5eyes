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
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from models.product_eligibility import (
    SFDR_CLASSIFICATION_VALUES,
    SUSTAINABILITY_CLIENT_SOURCE_LABELS,
    SUSTAINABILITY_CATEGORIES,
    SUSTAINABILITY_CATEGORY_COVERED_BY,
    SUSTAINABILITY_CLASSIFICATION_CATEGORIES,
    SUSTAINABILITY_CONDUCT_CATEGORIES,
    SUSTAINABILITY_DEFAULT_THRESHOLDS_BPS,
    SUSTAINABILITY_EVIDENCE_VALIDITY_MONTHS,
    SUSTAINABILITY_KINDS_BY_CATEGORY,
    SUSTAINABILITY_REVENUE_CATEGORIES,
    SUSTAINABILITY_SOURCE_TYPES,
    ProductEligibilityRule,
    ProductEligibilityRuleSet,
    ProductSustainabilityAttribute,
    SustainabilityExclusionStandard,
)

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


def _new_id() -> str:
    return str(uuid.uuid4())


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
        # N-855-10: Konsistenzguard der Abloesekette (fail-closed, 409).
        violations = supersession_chain_violations(db, rule)
        if violations:
            raise RuleApprovalConflict(
                "Abloesekette der Eignungsregeln inkonsistent: " + "; ".join(violations)
            )
    db.flush()
    return rule


# ===========================================================================
# AUDIT-2026-11 T1 (Audit 05 §4.1/§4.2/§4.3, Entscheide T-E1..T-E3):
# Nachhaltigkeits- und Ausschlussnachweise je Produkt.
#
# Gleiche Governance wie die Eignungsregeln oben: Vier-Augen-Freigabe
# (Ersteller != Freigeber, 409), Einzelberater-Ausnahme nur mit Attest,
# Plattform-Nachweise (tenant_id NULL) wirken fuer alle Tenants.
#
# is_criterion_satisfied() ist die EINZIGE Stelle, die entscheidet, ob ein
# Produkt ein Nachhaltigkeitskriterium erfuellt. In T1 ruft die Engine sie
# noch nicht auf (Verdrahtung in T3). Sie liest ausschliesslich freigegebene
# Nachweise aus product_sustainability_attributes -- NIE die Seed-/Lesecache-
# Felder products.sfdr_class/esg_rating/esg_score_x10/climate_benchmark/
# theme_tags (T-E2: unbelegte Werte erfuellen kein Kriterium).
# ===========================================================================


class SustainabilityAttributeConflict(Exception):
    """Ungueltiger Lebenszyklus-Schritt eines Nachweises (Router: 409)."""


def add_months(value: date, months: int) -> date:
    """Kalendermonate addieren; ein nicht existierender Tag (31.04., 29.02.
    im Nicht-Schaltjahr) faellt auf den Monatsletzten."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    for day in (value.day, 30, 29, 28):
        if day <= value.day:
            try:
                return date(year, month, day)
            except ValueError:
                continue
    raise ValueError(f"Datum nicht berechenbar: {value} + {months} Monate")


def default_evidence_valid_until(as_of: date) -> date:
    """T-E3: Gueltigkeit 12 Monate ab Stichtag."""
    return add_months(as_of, SUSTAINABILITY_EVIDENCE_VALIDITY_MONTHS)


def _as_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def criterion_type(category: str) -> str | None:
    """'revenue_threshold' | 'conduct' | 'classification' | None (unbekannt)."""
    if category in SUSTAINABILITY_REVENUE_CATEGORIES:
        return "revenue_threshold"
    if category in SUSTAINABILITY_CONDUCT_CATEGORIES:
        return "conduct"
    if category in SUSTAINABILITY_CLASSIFICATION_CATEGORIES:
        return "classification"
    return None


def sustainability_attribute_errors(values: dict, *, today: date | None = None) -> list[str]:
    """Fachliche Querpruefung eines Nachweises (Erfassen, Bearbeiten, Import).

    Erwartet normalisierte Werte (as_of/valid_until als date oder ISO-Text).
    Liefert deutschsprachige Fehlertexte; leer = gueltig. Fail-closed: eine
    unbekannte Kategorie, Art oder Quelle ist ein Fehler, nie ein Default.
    """
    errors: list[str] = []
    today = today or datetime.now(timezone.utc).date()
    category = values.get("category")
    kind = values.get("kind")
    revenue = values.get("revenue_threshold_bps")
    measured = values.get("measured_exposure_bps")
    value = values.get("value")
    if category not in SUSTAINABILITY_CATEGORIES:
        errors.append(f"Unbekannte Kategorie: {category!r}.")
        return errors
    allowed_kinds = SUSTAINABILITY_KINDS_BY_CATEGORY[category]
    if kind not in allowed_kinds:
        errors.append(f"Art {kind!r} ist fuer {category} nicht zulaessig (erlaubt: {', '.join(allowed_kinds)}).")
        return errors
    for name, number in (("revenue_threshold_bps", revenue), ("measured_exposure_bps", measured)):
        if number is not None and (isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= 10000):
            errors.append(f"{name} muss eine ganze Zahl zwischen 0 und 10000 bps sein.")
    ctype = criterion_type(category)
    if ctype == "revenue_threshold":
        if revenue is None:
            errors.append(
                "Umsatzschwelle (revenue_threshold_bps) fehlt: bei einer Ausschlussrichtlinie die Schwelle "
                "des Produkts, bei einer Messung die verwendete Umsatzgrenze."
            )
        if kind == "exclusion_policy" and measured is not None:
            errors.append("Eine Ausschlussrichtlinie hat keine gemessene Exposure (measured_exposure_bps leer lassen).")
        if kind == "measured_exposure" and measured is None:
            errors.append("Gemessene Exposure (measured_exposure_bps) fehlt.")
        if value not in (None, ""):
            errors.append("Feld value ist nur fuer Klassifikationen vorgesehen.")
    elif ctype == "conduct":
        if revenue is not None:
            errors.append("UN Global Compact hat keine Umsatzschwelle (revenue_threshold_bps leer lassen).")
        if kind == "exclusion_policy" and measured is not None:
            errors.append("Eine Ausschlussrichtlinie hat keine gemessene Exposure (measured_exposure_bps leer lassen).")
        if kind == "measured_exposure" and measured is None:
            errors.append("Gemessene Exposure (measured_exposure_bps) fehlt.")
        if value not in (None, ""):
            errors.append("Feld value ist nur fuer Klassifikationen vorgesehen.")
    else:
        if revenue is not None or measured is not None:
            errors.append("Klassifikationen haben keine Umsatzschwelle und keine Exposure.")
        if category == "sfdr_classification" and value not in SFDR_CLASSIFICATION_VALUES:
            errors.append(f"SFDR-Klassifikation muss einer von {', '.join(SFDR_CLASSIFICATION_VALUES)} sein.")
        if category == "impact_theme" and not str(value or "").strip():
            errors.append("Thema (value) fehlt.")
    source_type = values.get("source_type")
    if source_type not in SUSTAINABILITY_SOURCE_TYPES:
        errors.append(
            f"Quellentyp {source_type!r} ist nicht zulaessig (erlaubt: {', '.join(SUSTAINABILITY_SOURCE_TYPES)})."
        )
    if not str(values.get("source_reference") or "").strip():
        errors.append("Quellenreferenz fehlt (Dokument, Seite/Abschnitt bzw. Export).")
    if source_type == "data_vendor":
        if not str(values.get("source_provider") or "").strip():
            errors.append("Datenanbieter-Export: Anbieter (source_provider) fehlt.")
        if _as_date(values.get("source_retrieved_on")) is None:
            errors.append("Datenanbieter-Export: Abrufdatum (source_retrieved_on) fehlt.")
    retrieved = _as_date(values.get("source_retrieved_on"))
    if retrieved is not None and retrieved > today:
        errors.append("Abrufdatum liegt in der Zukunft.")
    errors.extend(source_document_errors(values, today=today))
    as_of = _as_date(values.get("as_of"))
    valid_until = _as_date(values.get("valid_until"))
    if as_of is None:
        errors.append("Stichtag (as_of) fehlt oder ist kein Datum.")
        return errors
    if as_of > today:
        errors.append("Stichtag liegt in der Zukunft.")
    if valid_until is not None:
        latest = default_evidence_valid_until(as_of)
        if valid_until < as_of:
            errors.append("Gueltig bis liegt vor dem Stichtag.")
        elif valid_until > latest:
            errors.append(
                f"Gueltig bis darf hoechstens {SUSTAINABILITY_EVIDENCE_VALIDITY_MONTHS} Monate nach dem "
                f"Stichtag liegen (spaetestens {latest.isoformat()})."
            )
    return errors


def default_client_source_label(source_type: str | None) -> str | None:
    """N-863-6: Default-Katalogwert der Kunden-Quellbezeichnung = Quellentyp."""
    return source_type if source_type in SUSTAINABILITY_CLIENT_SOURCE_LABELS else None


def client_source_label_text(code: str | None) -> str | None:
    """Anzeigetext eines Katalogwerts (None fuer unbekannt)."""
    return SUSTAINABILITY_CLIENT_SOURCE_LABELS.get(code or "")


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def source_document_errors(values: dict, *, today: date) -> list[str]:
    """FINMA-Sicht (Pruefrunde #863): Dokumentidentitaet und neutrale
    Kunden-Quellbezeichnung. N-863-6: die Kundenbezeichnung ist ein
    Katalogwert (kein Freitext), damit keine Drittmarken ins Kundendokument
    gelangen."""
    errors: list[str] = []
    document_date = values.get("source_document_date")
    if document_date not in (None, ""):
        parsed = _as_date(document_date)
        if parsed is None:
            errors.append("Dokumentdatum ist kein Datum (YYYY-MM-DD).")
        elif parsed > today:
            errors.append("Dokumentdatum liegt in der Zukunft.")
    digest = values.get("source_document_sha256")
    if digest not in (None, "") and not _is_sha256_hex(str(digest)):
        errors.append("source_document_sha256 muss ein SHA-256-Hexwert (64 Zeichen) sein.")
    label = values.get("client_source_label")
    if label not in (None, "") and label not in SUSTAINABILITY_CLIENT_SOURCE_LABELS:
        errors.append(
            "Kunden-Quellbezeichnung muss ein Katalogwert sein "
            f"({', '.join(SUSTAINABILITY_CLIENT_SOURCE_LABELS)})."
        )
    return errors


def sustainability_attribute_visible_to_tenant(attribute, tenant_id: str | None) -> bool:
    """Plattform-Nachweis (tenant_id NULL) fuer alle, Tenant-Nachweis nur
    fuer genau diesen Tenant (Spiegel der Postgres-Referenz-Policy)."""
    if attribute.tenant_id is None:
        return True
    return tenant_id is not None and attribute.tenant_id == tenant_id


def evidence_status(attribute, as_of: date | None = None) -> str:
    """Anzeige-Status: draft | retired | not_yet_valid | expired | valid."""
    if attribute.status != "approved":
        return attribute.status
    as_of = as_of or datetime.now(timezone.utc).date()
    start = _as_date(attribute.as_of)
    end = _as_date(attribute.valid_until)
    if start is None or end is None:
        return "expired"
    if as_of < start:
        return "not_yet_valid"
    if as_of > end:
        return "expired"
    return "valid"


def approve_sustainability_attribute(
    db: Session,
    *,
    attribute_id: str,
    approver_id: str,
    tenant_id: str | None,
    now: str | None = None,
    today: date | None = None,
    single_approver_attestation: bool = False,
    attestation_reason: str | None = None,
) -> tuple[ProductSustainabilityAttribute, list[ProductSustainabilityAttribute]]:
    """Vier-Augen-Freigabe eines Nachweis-Entwurfs.

    Gleiche Regel wie approve_rule(): Ersteller != Freigeber, sonst
    RuleApprovalConflict (409); Einzelberater-Ausnahme nur mit Attest,
    Begruendung und genau einer freigabeberechtigten Person im Tenant
    (fuer Plattform-Nachweise nie). Die Freigabe loest den bisher
    freigegebenen Nachweis desselben Schluessels (Produkt, Tenant-Scope,
    Kategorie, Art) ab. Ein bereits abgelaufener Entwurf oder ein Entwurf,
    der aelter ist als der geltende Nachweis, wird nicht freigegeben.

    Rueckgabe: (freigegebener Nachweis, abgeloeste Nachweise).
    ``LookupError``, wenn der Nachweis fuer ``tenant_id`` nicht sichtbar ist.
    """
    attribute = db.get(ProductSustainabilityAttribute, attribute_id)
    if attribute is None or not sustainability_attribute_visible_to_tenant(attribute, tenant_id):
        raise LookupError("Nachhaltigkeitsnachweis nicht gefunden.")
    if attribute.status != "draft":
        raise RuleApprovalConflict(f"Nachweis ist nicht im Entwurfsstatus (Status: {attribute.status}).")
    if not approver_id:
        raise RuleApprovalConflict("Genehmiger fehlt.")
    today = today or datetime.now(timezone.utc).date()
    valid_until = _as_date(attribute.valid_until)
    if valid_until is None or valid_until < today:
        raise RuleApprovalConflict("Nachweis ist bereits abgelaufen und kann nicht freigegeben werden.")
    if approver_id != attribute.created_by:
        approval_mode = APPROVAL_MODE_FOUR_EYES
    else:
        if not single_approver_attestation:
            raise RuleApprovalConflict(
                "Vier-Augen-Prinzip: Der Nachhaltigkeitsnachweis muss von einer anderen Person "
                "freigegeben werden als von der Person, die ihn erfasst hat."
            )
        if len((attestation_reason or "").strip()) < MIN_ATTESTATION_REASON_LENGTH:
            raise RuleApprovalConflict(
                f"Einzelfreigabe braucht eine Begruendung (mindestens {MIN_ATTESTATION_REASON_LENGTH} Zeichen)."
            )
        if attribute.tenant_id is None or tenant_approver_ids(db, attribute.tenant_id) != [approver_id]:
            raise RuleApprovalConflict(
                "Einzelfreigabe ist nur fuer Tenant-Nachweise zulaessig, wenn die Verwaltung genau eine "
                "freigabeberechtigte Person hat -- bitte eine andere Person freigeben lassen."
            )
        approval_mode = APPROVAL_MODE_SINGLE_APPROVER_ATTESTED
    query = db.query(ProductSustainabilityAttribute).filter(
        ProductSustainabilityAttribute.product_id == attribute.product_id,
        ProductSustainabilityAttribute.category == attribute.category,
        ProductSustainabilityAttribute.kind == attribute.kind,
        ProductSustainabilityAttribute.status == "approved",
        ProductSustainabilityAttribute.id != attribute.id,
    )
    if attribute.tenant_id is None:
        query = query.filter(ProductSustainabilityAttribute.tenant_id.is_(None))
    else:
        query = query.filter(ProductSustainabilityAttribute.tenant_id == attribute.tenant_id)
    previous = query.all()
    if any(str(p.as_of) > str(attribute.as_of) for p in previous):
        raise RuleApprovalConflict(
            "Es gilt bereits ein freigegebener Nachweis mit juengerem Stichtag; "
            "ein aelterer Entwurf kann ihn nicht abloesen."
        )
    now = now or _now_iso()
    for old in previous:
        old.status = "retired"
        old.retired_by = approver_id
        old.retired_at = now
        old.updated_at = now
    if previous and attribute.supersedes_id is None:
        attribute.supersedes_id = previous[0].id
    attribute.status = "approved"
    attribute.approved_by = approver_id
    attribute.approved_at = now
    attribute.approval_mode = approval_mode
    attribute.updated_at = now
    db.flush()
    return attribute, previous


def retire_sustainability_attribute(
    db: Session, *, attribute_id: str, actor_id: str, tenant_id: str | None, now: str | None = None,
) -> ProductSustainabilityAttribute:
    """Freigegebenen Nachweis zurueckziehen (danach zaehlt er nie mehr)."""
    attribute = db.get(ProductSustainabilityAttribute, attribute_id)
    if attribute is None or not sustainability_attribute_visible_to_tenant(attribute, tenant_id):
        raise LookupError("Nachhaltigkeitsnachweis nicht gefunden.")
    if attribute.status != "approved":
        raise SustainabilityAttributeConflict(
            f"Nur freigegebene Nachweise koennen zurueckgezogen werden (Status: {attribute.status}); "
            "Entwuerfe werden geloescht."
        )
    now = now or _now_iso()
    attribute.status = "retired"
    attribute.retired_by = actor_id
    attribute.retired_at = now
    attribute.updated_at = now
    db.flush()
    return attribute


# --- Hausstandard je Tenant (T-E1) -----------------------------------------


def sustainability_standard_categories() -> tuple[str, ...]:
    """Kategorien mit Hausstandard (Umsatz- und Verhaltenskriterien)."""
    return tuple(c for c in SUSTAINABILITY_CATEGORIES if c in SUSTAINABILITY_DEFAULT_THRESHOLDS_BPS)


def _standard_point_in_time(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return value.isoformat() + "T23:59:59.999Z"
    return str(value)


def _standard_rows(db: Session, tenant_id: str | None):
    if tenant_id is None:
        return []
    return db.query(SustainabilityExclusionStandard).filter(
        SustainabilityExclusionStandard.tenant_id == tenant_id,
    ).all()


def _pending_standard(rows, category: str):
    for row in rows:
        if row.category == category and row.status == "draft":
            return row
    return None


def _current_standard(rows, category: str, at: str | None):
    """Geltende freigegebene Version (``at`` None = jetzt, sonst
    Point-in-Time: valid_from <= at < valid_to)."""
    for row in rows:
        if row.category != category or row.approved_at is None:
            continue
        if at is None:
            if row.status == "approved" and row.valid_to is None:
                return row
            continue
        if row.valid_from is not None and row.valid_from <= at and (row.valid_to is None or row.valid_to > at):
            return row
    return None


STANDARD_CHANGE_TIGHTENING = "tightening"
STANDARD_CHANGE_RELAXATION = "relaxation"
STANDARD_CHANGE_UNCHANGED = "unchanged"


def _standard_state(current, category: str) -> tuple[int | None, bool]:
    """(Schwelle, deaktiviert) der geltenden Version; ohne Version der T-E1-Default."""
    if current is None:
        return SUSTAINABILITY_DEFAULT_THRESHOLDS_BPS[category], False
    return current.max_revenue_threshold_bps, bool(current.is_disabled)


def classify_standard_change(
    category: str, current, threshold: int | None, disabled: bool,
) -> str:
    """N-863-5: Richtung einer Aenderung relativ zur GELTENDEN Version.

    - Deaktivieren einer aktiven Kategorie, oder eine hoehere Schwelle als die
      geltende -> Lockerung (Entwurf, Vier-Augen-Freigabe).
    - Aktivieren einer deaktivierten Kategorie, oder eine niedrigere Schwelle
      -> Verschaerfung (sofort).
    - Gleicher Stand -> unveraendert (keine neue Version).
    """
    current_threshold, current_disabled = _standard_state(current, category)
    if disabled:
        return STANDARD_CHANGE_UNCHANGED if current_disabled else STANDARD_CHANGE_RELAXATION
    if current_disabled:
        return STANDARD_CHANGE_TIGHTENING
    if threshold == current_threshold:
        return STANDARD_CHANGE_UNCHANGED
    if current_threshold is None or threshold is None:
        # UNGC ohne Umsatzschwelle: nur Aktivieren/Deaktivieren aendert etwas.
        return STANDARD_CHANGE_UNCHANGED
    return STANDARD_CHANGE_RELAXATION if threshold > current_threshold else STANDARD_CHANGE_TIGHTENING


def effective_sustainability_standards(db: Session, tenant_id: str | None, as_of=None) -> list[dict]:
    """Je Kategorie: Default (T-E1), geltende Tenant-Version und wirksamer
    Wert; mit ``as_of`` Point-in-Time (fuer den Snapshot in T3)."""
    rows = _standard_rows(db, tenant_id)
    at = _standard_point_in_time(as_of)
    items = []
    for category in sustainability_standard_categories():
        default = SUSTAINABILITY_DEFAULT_THRESHOLDS_BPS[category]
        row = _current_standard(rows, category, at)
        pending = None if at is not None else _pending_standard(rows, category)
        disabled = bool(row.is_disabled) if row is not None else False
        if disabled:
            effective = None
        elif row is not None:
            effective = row.max_revenue_threshold_bps
        else:
            effective = default
        items.append({
            "category": category,
            "criterion_type": criterion_type(category),
            "default_threshold_bps": default,
            "tenant_threshold_bps": row.max_revenue_threshold_bps if row is not None else None,
            "effective_threshold_bps": effective,
            "is_overridden": row is not None,
            "is_disabled": disabled,
            "standard_id": row.id if row is not None else None,
            "valid_from": row.valid_from if row is not None else None,
            "approved_by": row.approved_by if row is not None else None,
            "approved_at": row.approved_at if row is not None else None,
            "approval_mode": row.approval_mode if row is not None else None,
            "note": row.note if row is not None else None,
            "updated_by": row.updated_by if row is not None else None,
            "updated_at": row.updated_at if row is not None else None,
            "pending": None if pending is None else {
                "id": pending.id,
                "max_revenue_threshold_bps": pending.max_revenue_threshold_bps,
                "is_disabled": bool(pending.is_disabled),
                "created_by": pending.created_by,
                "created_at": pending.created_at,
                "note": pending.note,
            },
        })
    return items


def effective_sustainability_standard(db: Session, tenant_id: str | None, category: str, as_of=None) -> dict:
    """Wirksamer Hausstandard einer Kategorie (inkl. Version); ``KeyError``
    ohne Hausstandard. T3 speichert daraus Schwelle und standard_id."""
    if category not in SUSTAINABILITY_DEFAULT_THRESHOLDS_BPS:
        raise KeyError(category)
    for item in effective_sustainability_standards(db, tenant_id, as_of):
        if item["category"] == category:
            return item
    raise KeyError(category)  # pragma: no cover - Katalog und Defaults sind synchron


def effective_sustainability_threshold(db: Session, tenant_id: str | None, category: str, as_of=None) -> int | None:
    """Wirksame Hausschwelle (bps); None bei deaktivierter Kategorie oder UNGC."""
    return effective_sustainability_standard(db, tenant_id, category, as_of)["effective_threshold_bps"]


def _retire_standard(row, actor_id: str, now: str) -> None:
    row.status = "retired"
    if row.approved_at is not None and row.valid_to is None:
        row.valid_to = now
    row.updated_by = actor_id
    row.updated_at = now


def set_sustainability_standard(
    db: Session, *, tenant_id: str, category: str, threshold: int | None, disabled: bool,
    note: str | None, actor_id: str, now: str | None = None,
):
    """Neue Version des Hausstandards. Rueckgabe (Zeile oder None, Richtung).

    Richtung relativ zur geltenden Version (N-863-5):
    - Verschaerfung: sofort freigegeben (approval_mode 'immediate_tightening'),
      die bisherige Version endet (valid_to).
    - Lockerung: Entwurf, wirkt erst nach Vier-Augen-Freigabe.
    - Unveraendert: keine neue Version (Zeile None).
    Ein offener Entwurf derselben Kategorie wird bei jeder Aenderung verworfen.
    """
    now = now or _now_iso()
    rows = _standard_rows(db, tenant_id)
    current = _current_standard(rows, category, None)
    change = classify_standard_change(category, current, threshold, disabled)
    if change == STANDARD_CHANGE_UNCHANGED:
        return None, change
    pending = _pending_standard(rows, category)
    if pending is not None:
        _retire_standard(pending, actor_id, now)
        db.flush()
    row = SustainabilityExclusionStandard(
        id=_new_id(), tenant_id=tenant_id, category=category, max_revenue_threshold_bps=threshold,
        is_disabled=1 if disabled else 0, note=note, created_by=actor_id, updated_by=actor_id,
        created_at=now, updated_at=now, status="draft",
    )
    if change == STANDARD_CHANGE_TIGHTENING:
        if current is not None:
            _retire_standard(current, actor_id, now)
            db.flush()
        row.status = "approved"
        row.approved_by = actor_id
        row.approved_at = now
        row.approval_mode = "immediate_tightening"
        row.valid_from = now
    db.add(row)
    db.flush()
    return row, change


def approve_sustainability_standard(
    db: Session, *, tenant_id: str, category: str, approver_id: str, now: str | None = None,
    single_approver_attestation: bool = False, attestation_reason: str | None = None,
):
    """Vier-Augen-Freigabe einer Lockerung (Muster approve_rule):
    Ersteller = Freigeber -> RuleApprovalConflict (409), ausser
    Einzelberater-Attest. ``LookupError`` ohne offenen Entwurf.
    Rueckgabe (freigegebene Version, beendete Version oder None)."""
    rows = _standard_rows(db, tenant_id)
    draft = _pending_standard(rows, category)
    if draft is None:
        raise LookupError("Kein offener Entwurf fuer diesen Hausstandard.")
    if not approver_id:
        raise RuleApprovalConflict("Genehmiger fehlt.")
    if approver_id != draft.created_by:
        mode = APPROVAL_MODE_FOUR_EYES
    else:
        if not single_approver_attestation:
            raise RuleApprovalConflict(
                "Vier-Augen-Prinzip: Eine Lockerung des Hausstandards muss eine andere Person freigeben."
            )
        if len((attestation_reason or "").strip()) < MIN_ATTESTATION_REASON_LENGTH:
            raise RuleApprovalConflict(
                f"Einzelfreigabe braucht eine Begruendung (mindestens {MIN_ATTESTATION_REASON_LENGTH} Zeichen)."
            )
        if tenant_approver_ids(db, tenant_id) != [approver_id]:
            raise RuleApprovalConflict(
                "Einzelfreigabe ist nur zulaessig, wenn die Verwaltung genau eine freigabeberechtigte Person hat."
            )
        mode = APPROVAL_MODE_SINGLE_APPROVER_ATTESTED
    now = now or _now_iso()
    previous = _current_standard(rows, category, None)
    if previous is not None:
        _retire_standard(previous, approver_id, now)
        db.flush()
    draft.status = "approved"
    draft.approved_by = approver_id
    draft.approved_at = now
    draft.approval_mode = mode
    draft.valid_from = now
    draft.updated_by = approver_id
    draft.updated_at = now
    db.flush()
    return draft, previous


def reset_sustainability_standard(
    db: Session, *, tenant_id: str, category: str, actor_id: str, now: str | None = None,
):
    """Zurueck auf den T-E1-Default. N-863-5: Ist die geltende Version
    strenger als der Default, ist das eine Lockerung -> Entwurf mit dem
    Default-Wert (Vier-Augen-Freigabe). Ist sie lockerer oder deaktiviert,
    endet sie sofort (Verschaerfung). Rueckgabe (betroffene Zeile, Richtung)."""
    now = now or _now_iso()
    rows = _standard_rows(db, tenant_id)
    current = _current_standard(rows, category, None)
    if current is None:
        return None, STANDARD_CHANGE_UNCHANGED
    default = SUSTAINABILITY_DEFAULT_THRESHOLDS_BPS[category]
    change = classify_standard_change(category, current, default, False)
    if change == STANDARD_CHANGE_RELAXATION:
        return set_sustainability_standard(
            db, tenant_id=tenant_id, category=category, threshold=default, disabled=False,
            note="Ruecksetzung auf den Haus-Default", actor_id=actor_id, now=now,
        )
    pending = _pending_standard(rows, category)
    for row in (current, pending):
        if row is not None:
            _retire_standard(row, actor_id, now)
    db.flush()
    return current, (STANDARD_CHANGE_TIGHTENING if change == STANDARD_CHANGE_TIGHTENING else STANDARD_CHANGE_UNCHANGED)


def discard_pending_sustainability_standard(
    db: Session, *, tenant_id: str, category: str, actor_id: str, now: str | None = None,
):
    """Offenen Entwurf (Lockerung) verwerfen. Rueckgabe: verworfener Entwurf."""
    now = now or _now_iso()
    draft = _pending_standard(_standard_rows(db, tenant_id), category)
    if draft is not None:
        _retire_standard(draft, actor_id, now)
        db.flush()
    return draft


# --- Kriterium erfuellt? (T3 verdrahtet) ------------------------------------

#: Begruendungen, schwerste zuerst (fuer die Lueckenliste in T3).
CRITERION_REASONS: tuple[str, ...] = (
    "satisfied",
    "conflicting_evidence",
    "exposure_present",
    "threshold_exceeded",
    "inconclusive_measurement",
    "classification_below_threshold",
    "expired",
    "not_yet_valid",
    "not_approved",
    "value_mismatch",
    "no_evidence",
    "no_threshold",
    "no_expected_value",
    "unknown_category",
)


def _normalized_theme(value) -> str:
    return " ".join(str(value or "").split()).casefold()


@dataclass(frozen=True)
class CriterionEvaluation:
    satisfied: bool
    reason: str
    attribute_id: str | None = None
    candidate_reasons: tuple[str, ...] = field(default_factory=tuple)


def _row_reason(attribute, ctype: str, threshold, check_date: date, expected_value=None) -> str:
    if attribute.status != "approved":
        return "not_approved"
    start = _as_date(attribute.as_of)
    end = _as_date(attribute.valid_until)
    if start is None or end is None or check_date > end:
        return "expired"
    if check_date < start:
        return "not_yet_valid"
    if ctype == "revenue_threshold":
        cutoff = attribute.revenue_threshold_bps
        if attribute.kind == "measured_exposure":
            # N-863-1: measured_exposure_bps = Fondsgewicht der Emittenten
            # mit Umsatzanteil UEBER der Messgrenze (cutoff).
            # - Gewicht 0 und Messgrenze <= Hausschwelle: kein Emittent ueber
            #   der Hausschwelle -> erfuellt (T-E4: keine Toleranz).
            # - Gewicht > 0 und Messgrenze >= Hausschwelle: belegter Verstoss
            #   -> exposure_present (blockiert, siehe evaluate_criterion).
            # - sonst nicht schluessig (erfuellt nicht, blockiert nicht).
            exposure = attribute.measured_exposure_bps
            if cutoff is None or exposure is None:
                return "inconclusive_measurement"
            if exposure == 0:
                return "satisfied" if cutoff <= threshold else "threshold_exceeded"
            return "exposure_present" if cutoff >= threshold else "inconclusive_measurement"
        if cutoff is None or cutoff > threshold:
            return "threshold_exceeded"
        return "satisfied" if attribute.kind == "exclusion_policy" else "no_evidence"
    if ctype == "conduct":
        if attribute.kind == "exclusion_policy":
            return "satisfied"
        if attribute.kind == "measured_exposure":
            return "satisfied" if attribute.measured_exposure_bps == 0 else "exposure_present"
        return "no_evidence"
    if attribute.category == "sfdr_classification":
        try:
            article = int(str(attribute.value))
        except (TypeError, ValueError):
            return "no_evidence"
        return "satisfied" if article >= int(threshold) else "classification_below_threshold"
    # N-863-2: impact_theme nur mit Sollthema; Vergleich normalisiert
    # (Gross-/Kleinschreibung, Leerraum), sonst fail-closed.
    if not _normalized_theme(attribute.value):
        return "no_evidence"
    return "satisfied" if _normalized_theme(attribute.value) == _normalized_theme(expected_value) else "value_mismatch"


def evaluate_criterion(
    db: Session | None,
    product,
    category: str,
    threshold: int | None,
    as_of,
    *,
    tenant_id: str | None = None,
    attributes=None,
    expected_value: str | None = None,
) -> CriterionEvaluation:
    """Erfuellt ``product`` das Kriterium ``category`` am Stichtag ``as_of``?

    ``threshold``: bei Umsatzkriterien die Hausschwelle in bps (Nachweis
    zaehlt, wenn seine Umsatzgrenze <= threshold ist; Grenze inklusive);
    bei ``sfdr_classification`` der Mindest-Artikel (8 oder 9); bei
    ``ungc_violation`` und ``impact_theme`` ohne Bedeutung.
    ``expected_value``: Pflicht bei ``impact_theme`` (Sollthema, gleicher
    Schluessel wie das Praeferenz-Vokabular); fehlt es -> no_expected_value
    (N-863-2, fail-closed).

    Widerspruch (N-863-1): Liegt eine gueltige, sichtbare Messung mit
    belegter Exposure vor, ist das Kriterium nie erfuellt
    (``conflicting_evidence``, wenn ein anderer Nachweis es sonst erfuellen
    wuerde, sonst ``exposure_present``).

    Zaehlt nur ein freigegebener Nachweis, dessen Stichtag <= as_of <=
    gueltig bis ist und der fuer ``tenant_id`` sichtbar ist (Plattform oder
    eigener Tenant). Entwuerfe, zurueckgezogene, abgelaufene und noch nicht
    gueltige Nachweise sowie jede Angabe ausserhalb dieser Tabelle (Seed-
    Felder am Produkt) erfuellen nichts. ``attributes`` erlaubt T3, die
    Nachweise vorab gebuendelt zu laden.
    """
    ctype = criterion_type(category)
    if ctype is None:
        return CriterionEvaluation(False, "unknown_category")
    needs_threshold = ctype == "revenue_threshold" or category == "sfdr_classification"
    if needs_threshold and (threshold is None or isinstance(threshold, bool) or not isinstance(threshold, int)):
        return CriterionEvaluation(False, "no_threshold")
    if category == "impact_theme" and not _normalized_theme(expected_value):
        return CriterionEvaluation(False, "no_expected_value")
    check_date = _as_date(as_of)
    if check_date is None:
        return CriterionEvaluation(False, "no_threshold")
    product_id = getattr(product, "id", product)
    covering = SUSTAINABILITY_CATEGORY_COVERED_BY.get(category, ())
    if attributes is None:
        if db is None:
            return CriterionEvaluation(False, "no_evidence")
        attributes = db.query(ProductSustainabilityAttribute).filter(
            ProductSustainabilityAttribute.product_id == product_id,
            ProductSustainabilityAttribute.category.in_((category, *covering)),
        ).all()
    visible = [
        a for a in attributes
        if a.product_id == product_id and sustainability_attribute_visible_to_tenant(a, tenant_id)
    ]
    candidates = [a for a in visible if a.category == category]
    # H-4: Nachweise der Oberkategorie koennen nur ERFUELLEN (Schwelle der
    # angefragten Kategorie), nie blockieren.
    covering_candidates = [a for a in visible if a.category in covering]
    if not candidates and not covering_candidates:
        return CriterionEvaluation(False, "no_evidence")
    ordered = sorted(candidates, key=lambda a: (str(a.as_of), str(a.id)), reverse=True)
    evaluated = [
        (attribute, _row_reason(attribute, ctype, threshold, check_date, expected_value)) for attribute in ordered
    ]
    reasons = tuple(reason for _attribute, reason in evaluated)
    # N-863-1: eine freigegebene, gueltige, sichtbare Messung mit belegter
    # Exposure blockiert IMMER -- unabhaengig von Scope (Plattform/Tenant)
    # und davon, ob eine Ausschlussrichtlinie (Absichtserklaerung) oder eine
    # andere Messung das Kriterium sonst erfuellen wuerde. Eine Tatsachen-
    # feststellung schlaegt eine Absichtserklaerung; ein Tenant-Overlay
    # ersetzt den Plattform-Nachweis nicht, beide gelten.
    covering_ordered = sorted(covering_candidates, key=lambda a: (str(a.as_of), str(a.id)), reverse=True)
    covering_evaluated = [
        (attribute, _row_reason(attribute, ctype, threshold, check_date, expected_value))
        for attribute in covering_ordered
    ]
    # N-863-4 (Grenzen-Regel): Eine gueltige, sichtbare Messung der eigenen
    # Kategorie mit Exposure > 0 und Messgrenze c_m belegt Emittenten mit
    # Umsatz > c_m im Produkt. Sie widerlegt jeden sonst erfuellenden
    # Nachweis (eigene Kategorie oder Oberkategorie, Richtlinie oder Messung
    # mit 0) mit Grenze c <= c_m -> conflicting_evidence. Nur ein Nachweis mit
    # strengerer Messgrenze-Lage c > c_m bleibt erfuellt (z. B. Richtlinie 5 %
    # gegen Messung "jede Beteiligung" 3 %: Emittenten zwischen 0 und 5 %
    # Umsatz sind unter der Richtlinie erlaubt), mit Hinweis
    # inconclusive_measurement in candidate_reasons. Bei UNGC (ohne Grenze)
    # widerlegt jede Messung mit Exposure > 0 jeden anderen Nachweis.
    blocking_cutoffs = [
        attribute.revenue_threshold_bps
        for attribute, reason in evaluated
        if reason in ("exposure_present", "inconclusive_measurement")
        and attribute.kind == "measured_exposure"
        and (attribute.measured_exposure_bps or 0) > 0
    ]

    def _refuted(attribute) -> bool:
        if not blocking_cutoffs:
            return False
        if ctype != "revenue_threshold":
            return True
        limit = attribute.revenue_threshold_bps
        return any(c_m is None or limit is None or limit <= c_m for c_m in blocking_cutoffs)

    satisfying = [a for a, reason in evaluated if reason == "satisfied"]
    covering_satisfied = [a for a, reason in covering_evaluated if reason == "satisfied"]
    surviving = [a for a in satisfying if not _refuted(a)]
    # N-863-7: eine Messung der OBERKATEGORIE (Grenze c_m, Exposure > 0)
    # blockiert die Unterkategorie nicht (die Exposure kann eine andere
    # Unterkategorie betreffen), widerlegt aber jeden Nachweis der
    # Oberkategorie mit Grenze <= c_m. Ein so widerlegter Ober-Nachweis darf
    # die Unterkategorie nicht erfuellen.
    parent_blocking = {}
    for attribute, reason in covering_evaluated:
        if (
            reason in ("exposure_present", "inconclusive_measurement")
            and attribute.kind == "measured_exposure"
            and (attribute.measured_exposure_bps or 0) > 0
        ):
            parent_blocking.setdefault(attribute.category, []).append(attribute.revenue_threshold_bps)

    def _refuted_by_parent_measurement(attribute) -> bool:
        cutoffs = parent_blocking.get(attribute.category, [])
        if not cutoffs:
            return False
        limit = attribute.revenue_threshold_bps
        return any(c_m is None or limit is None or limit <= c_m for c_m in cutoffs)

    surviving_covering = [
        a for a in covering_satisfied if not _refuted(a) and not _refuted_by_parent_measurement(a)
    ]
    if (satisfying or covering_satisfied) and not (surviving or surviving_covering):
        return CriterionEvaluation(False, "conflicting_evidence", None, reasons)
    if "exposure_present" in reasons and not (surviving or surviving_covering):
        return CriterionEvaluation(False, "exposure_present", None, reasons)
    if surviving:
        return CriterionEvaluation(True, "satisfied", surviving[0].id, reasons)
    if surviving_covering:
        return CriterionEvaluation(
            True, "satisfied", surviving_covering[0].id, reasons + ("satisfied_by_parent_category",),
        )
    # Messungen der Oberkategorie mit Exposure sind fuer die Unterkategorie
    # nicht schluessig (blockieren nicht).
    reasons = reasons + tuple(
        "inconclusive_measurement" if reason == "exposure_present" else reason
        for _attribute, reason in covering_evaluated
    )
    worst = min(reasons, key=CRITERION_REASONS.index)
    return CriterionEvaluation(False, worst, None, reasons)


def is_criterion_satisfied(
    db: Session | None,
    product,
    category: str,
    threshold: int | None,
    as_of,
    *,
    tenant_id: str | None = None,
    attributes=None,
    expected_value: str | None = None,
) -> bool:
    """Boolesche Kurzform von evaluate_criterion() (fail-closed)."""
    return evaluate_criterion(
        db, product, category, threshold, as_of, tenant_id=tenant_id, attributes=attributes,
        expected_value=expected_value,
    ).satisfied


def supersession_chain_violations(db: Session, rule: ProductEligibilityRule) -> list[str]:
    """N-855-10 (2026-11): prueft die Abloesekette der exakten Regeln eines
    Produkts (gleiche Jurisdiktion und gleicher Tenant) nach einer Freigabe:

    * jede Folgeregel mit freigegebenem Vorgaenger:
      previous.valid_to == successor.valid_from == successor.approved_at;
    * keine zwei je wirksam gewesenen Regeln (approved, oder retired mit
      approved_at und valid_to) mit ueberlappenden halboffenen Intervallen
      [valid_from, valid_to).

    Zeitvergleiche als UTC-datetime. Rueckgabe: Liste der Verstoesse."""
    db.flush()
    rows = (
        db.query(ProductEligibilityRule)
        .filter(
            ProductEligibilityRule.product_id == rule.product_id,
            ProductEligibilityRule.jurisdiction == rule.jurisdiction,
            ProductEligibilityRule.status.in_(("approved", "retired")),
        )
        .all()
    )
    effective = [
        row for row in rows
        if row.tenant_id == rule.tenant_id and row.approved_at is not None
        and (row.status == "approved" or row.valid_to is not None)
    ]
    by_id = {row.id: row for row in effective}
    violations: list[str] = []
    for row in effective:
        previous = by_id.get(row.supersedes_id) if row.supersedes_id else None
        if previous is None:
            continue
        stamps = (
            parse_utc_timestamp(previous.valid_to),
            parse_utc_timestamp(row.valid_from),
            parse_utc_timestamp(row.approved_at),
        )
        if None in stamps or len(set(stamps)) != 1:
            violations.append(
                f"{previous.id}.valid_to/{row.id}.valid_from/{row.id}.approved_at ungleich"
            )
    intervals = []
    for row in effective:
        start = parse_utc_timestamp(row.valid_from)
        end = parse_utc_timestamp(row.valid_to) if row.valid_to is not None else None
        if start is None or (row.valid_to is not None and end is None):
            violations.append(f"{row.id}: Gueltigkeitsfenster unlesbar")
            continue
        if end is not None and end < start:
            violations.append(f"{row.id}: valid_to vor valid_from")
            continue
        intervals.append((start, end, row.id))
    intervals.sort(key=lambda item: item[0])
    open_until, open_id = None, None  # weitestes bisheriges Intervallende
    for index, (start, end, row_id) in enumerate(intervals):
        if index and (open_until is None or start < open_until):
            violations.append(f"Intervalle von {open_id} und {row_id} ueberlappen")
        if index == 0 or open_until is not None and (end is None or end > open_until):
            open_until, open_id = end, row_id
    return violations
