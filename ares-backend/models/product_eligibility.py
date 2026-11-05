"""CERT-PRODUCT-ELIGIBILITY-001 -- governed product eligibility domain.

Implements the persistence layer of `ProductEligibilityRuleV1`,
`ProductEligibilitySnapshotV1`, `ProductEligibilityDecisionV1` and
`ProductEligibilityOverrideV1` from the Ares/Codex certification spec
(docs/audits/2026-10-08-product-eligibility-appropriateness-and-
finalization-certification-spec.md in the Ares audit worktree, Sections
4, 7 and 11).

This is additive and does not replace `models.review.ProductSuitability`.
The legacy table is not migrated here -- Section 15 of the spec requires an
explicit governance decision before any legacy row is promoted into an
approved rule, which is a business/compliance call, not an engineering one.
Until that decision is made and rules are actually approved here, every
product is `indeterminate` under `evaluate_product_eligibility()`
(services/product_eligibility.py) -- by design, fail-closed.
"""
from __future__ import annotations

from sqlalchemy import DDL, CheckConstraint, Column, ForeignKey, Index, Integer, String, event, text
from sqlalchemy.orm import relationship

from database import Base
from core import product_eligibility_override_schema as _override_schema


class ProductEligibilityRuleSet(Base):
    __tablename__ = "product_eligibility_rule_sets"

    id = Column(String, primary_key=True)
    # Section 4.3 / 11: tenant_scope in {"global", "tenant"}; tenant_id only
    # set for tenant-scoped rule sets.
    tenant_scope = Column(String, nullable=False, default="global")
    tenant_id = Column(String, ForeignKey("tenants.id"))
    jurisdiction = Column(String, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="draft")  # draft|approved|retired
    valid_from = Column(String, nullable=False)
    valid_to = Column(String)
    created_by = Column(String, nullable=False)
    approved_by = Column(String)
    approved_at = Column(String)
    supersedes_id = Column(String, ForeignKey("product_eligibility_rule_sets.id"))
    rule_set_hash = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    rules = relationship("ProductEligibilityRule", back_populates="rule_set")

    __table_args__ = (
        Index(
            "ix_product_eligibility_rule_sets_scope",
            "tenant_scope", "tenant_id", "jurisdiction", "status",
        ),
        # ELIG-GOVERNANCE-001 (2026-10-21): services.product_eligibility.
        # ensure_rule_set() ist ein find-or-create ueber (tenant_scope,
        # tenant_id, jurisdiction, created_by). Ohne DB-Unique-Key konnten
        # zwei parallele Requests beide den Precheck bestehen und zwei
        # RuleSets derselben Linie anlegen. version gehoert zum Schluessel,
        # damit eine spaetere Folgeversion (supersedes_id) moeglich bleibt.
        # Zwei partielle Indizes, weil NULL in Unique-Indizes (SQLite und
        # Postgres) als verschieden gilt -- globale Sets haben tenant_id NULL.
        # Postgres-Pfad: alembic/versions/b5e1c7d9a3f2_*.py.
        Index(
            "ux_product_eligibility_rule_sets_lineage_tenant",
            "tenant_scope", "tenant_id", "jurisdiction", "created_by", "version",
            unique=True,
            sqlite_where=text("tenant_id IS NOT NULL"),
            postgresql_where=text("tenant_id IS NOT NULL"),
        ),
        Index(
            "ux_product_eligibility_rule_sets_lineage_global",
            "tenant_scope", "jurisdiction", "created_by", "version",
            unique=True,
            sqlite_where=text("tenant_id IS NULL"),
            postgresql_where=text("tenant_id IS NULL"),
        ),
    )


class ProductEligibilityRule(Base):
    __tablename__ = "product_eligibility_rules"

    id = Column(String, primary_key=True)
    rule_set_id = Column(String, ForeignKey("product_eligibility_rule_sets.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    # Exactly one of product_id / product_category_selector is set.
    product_id = Column(String, ForeignKey("products.id"))
    product_category_selector = Column(String)
    tenant_scope = Column(String, nullable=False, default="global")
    tenant_id = Column(String, ForeignKey("tenants.id"))
    jurisdiction = Column(String, nullable=False)
    # JSON-encoded lists (consistent with this codebase's *_json convention,
    # e.g. models.allocation.CapitalMarketAssumption.correlation_matrix_json).
    client_classifications_json = Column(String, nullable=False, default="[]")
    service_modes_json = Column(String, nullable=False, default="[]")
    profile_from = Column(Integer, nullable=False)
    profile_to = Column(Integer, nullable=False)
    requires_knowledge_categories_json = Column(String, nullable=False, default="[]")
    minimum_experience_level = Column(String)
    requires_appropriateness = Column(Integer, nullable=False, default=0)
    requires_suitability = Column(Integer, nullable=False, default=0)
    requires_override = Column(Integer, nullable=False, default=0)
    max_position_bps = Column(Integer)
    prohibited = Column(Integer, nullable=False, default=0)
    valid_from = Column(String, nullable=False)
    valid_to = Column(String)
    status = Column(String, nullable=False, default="draft")  # draft|approved|retired
    created_by = Column(String, nullable=False)
    approved_by = Column(String)
    approved_at = Column(String)
    # ELIG-GOVERNANCE-001 (2026-10-22): wie die Regel freigegeben wurde --
    # 'four_eyes' oder 'single_approver_attested' (Einzelberater-Ausnahme,
    # services/product_eligibility_governance.approve_rule). NULL = vor
    # dieser Spalte bzw. beim Anlegen genehmigt (Bootstrap/Backfill/Legacy).
    approval_mode = Column(String)
    supersedes_id = Column(String, ForeignKey("product_eligibility_rules.id"))
    rule_hash = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    rule_set = relationship("ProductEligibilityRuleSet", back_populates="rules")
    product = relationship("Product")

    __table_args__ = (
        Index(
            "ix_product_eligibility_rules_product_status",
            "product_id", "status", "valid_from", "valid_to",
        ),
    )


class ProductEligibilitySnapshot(Base):
    __tablename__ = "product_eligibility_snapshots"

    id = Column(String, primary_key=True)
    schema_version = Column(Integer, nullable=False, default=1)
    tenant_id = Column(String, ForeignKey("tenants.id"))
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    recommendation_run_id = Column(String, ForeignKey("recommendation_runs.id"), nullable=False)
    target_allocation_id = Column(String)
    allocation_context_hash = Column(String)
    service_mode = Column(String, nullable=False)
    client_classification = Column(String)
    jurisdiction = Column(String, nullable=False)
    assessment_id = Column(String)
    risk_profile = Column(String)
    knowledge_assessment_id = Column(String)
    knowledge_assessment_version = Column(Integer)
    knowledge_hash = Column(String)
    suitability_check_id = Column(String)
    appropriateness_check_id = Column(String)
    product_rule_set_id = Column(String, ForeignKey("product_eligibility_rule_sets.id"))
    product_rule_set_version = Column(Integer)
    product_rule_set_hash = Column(String)
    cost_snapshot_id = Column(String)
    conflict_snapshot_id = Column(String)
    evaluated_positions_json = Column(String, nullable=False, default="[]")
    portfolio_aggregation_checks_json = Column(String, nullable=False, default="[]")
    overrides_json = Column(String, nullable=False, default="[]")
    blockers_json = Column(String, nullable=False, default="[]")
    warnings_json = Column(String, nullable=False, default="[]")
    verdict = Column(String, nullable=False)  # eligible|ineligible|indeterminate|stale|superseded
    evaluated_at = Column(String, nullable=False)
    expires_at = Column(String)
    evaluator_version = Column(String, nullable=False)
    snapshot_hash = Column(String, nullable=False)
    created_at = Column(String, nullable=False)

    decisions = relationship("ProductEligibilityDecision", back_populates="snapshot")

    __table_args__ = (
        Index(
            "ix_product_eligibility_snapshots_run",
            "recommendation_run_id",
        ),
    )


class ProductEligibilityDecision(Base):
    __tablename__ = "product_eligibility_decisions"

    id = Column(String, primary_key=True)
    snapshot_id = Column(String, ForeignKey("product_eligibility_snapshots.id"), nullable=False)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    stable_instrument_id = Column(String)
    aggregated_weight_bps = Column(Integer, nullable=False)
    source_sub_allocations_json = Column(String, nullable=False, default="[]")
    service_mode = Column(String, nullable=False)
    matched_rule_id = Column(String, ForeignKey("product_eligibility_rules.id"))
    matched_rule_version = Column(Integer)
    matched_rule_hash = Column(String)
    rule_scope = Column(String)
    risk_band_status = Column(String, nullable=False)
    service_permission_status = Column(String, nullable=False)
    knowledge_status = Column(String, nullable=False)
    appropriateness_status = Column(String, nullable=False)
    suitability_status = Column(String, nullable=False)
    override_status = Column(String, nullable=False)
    position_limit_bps = Column(Integer)
    position_limit_status = Column(String, nullable=False)
    cost_evidence_status = Column(String, nullable=False, default="not_evaluated")
    conflict_evidence_status = Column(String, nullable=False, default="not_evaluated")
    decision = Column(String, nullable=False)  # eligible|ineligible|indeterminate
    reason_codes_json = Column(String, nullable=False, default="[]")
    created_at = Column(String, nullable=False)

    snapshot = relationship("ProductEligibilitySnapshot", back_populates="decisions")

    __table_args__ = (
        Index(
            "ix_product_eligibility_decisions_snapshot_product",
            "snapshot_id", "product_id",
        ),
    )


class ProductEligibilityOverride(Base):
    """Append-only (ELIG-OVERRIDE-APPEND-ONLY-001): UPDATE/DELETE are
    rejected by triggers; no hard FK to the run (Purge-fest), see
    core/product_eligibility_override_schema.py."""

    __tablename__ = "product_eligibility_overrides"

    id = Column(String, primary_key=True)
    snapshot_id = Column(String, ForeignKey("product_eligibility_snapshots.id"))
    rule_id = Column(String, ForeignKey("product_eligibility_rules.id"))
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    recommendation_run_id = Column(String, nullable=False)
    original_decision = Column(String, nullable=False)
    overridden_dimension = Column(String, nullable=False)
    reason_code = Column(String, nullable=False)
    reason_text = Column(String)
    requested_by = Column(String, nullable=False)
    approved_by = Column(String, nullable=False)
    client_acknowledgement_id = Column(String)
    warning_delivery_id = Column(String)
    valid_from = Column(String, nullable=False)
    expires_at = Column(String, nullable=False)
    policy_basis = Column(String)
    # ELIG-OVERRIDE-SINGLE-APPROVER-001: approval rows carry 'four_eyes' or
    # 'single_approver_attested' (part of the evidence hash); NULL on requests.
    approval_mode = Column(String)
    evidence_hash = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    # PG-002: Mandant direkt (RLS-Plan), aus Lauf -> Mandat abgeleitet und per
    # INSERT-Guard geprueft (core/mandate_evidence_tenant_boundary.py);
    # nicht Teil des Evidence-Hashes.
    tenant_id = Column(String)

    __table_args__ = (
        Index(
            "ix_product_eligibility_overrides_run_product",
            "recommendation_run_id", "product_id",
        ),
        Index("ix_product_eligibility_overrides_tenant_id", "tenant_id"),
    )


for _trigger_ddl in _override_schema.SQLITE_TRIGGERS:
    event.listen(
        ProductEligibilityOverride.__table__,
        "after_create",
        DDL(_trigger_ddl).execute_if(dialect="sqlite"),
    )


# ---------------------------------------------------------------------------
# AUDIT-2026-11 T1 (Audit 05 §4.1/§4.2, Entscheide T-E1..T-E3):
# Nachhaltigkeits- und Ausschlussmerkmale je Produkt plus Hausstandard je
# Tenant. Liegt bewusst in diesem Modul (gleiche Governance wie die
# Eignungsregeln: Vier-Augen-Freigabe, globale Zeilen = Plattform, R3).
# In T1 OHNE Engine-Wirkung; services/product_eligibility_governance.py::
# is_criterion_satisfied() wird erst in T3 verdrahtet.
#
# Grundsatz (T-E2): nur freigegebene, nicht abgelaufene Nachweise MIT Quelle
# zaehlen. Seed-/Default-Werte auf products (sfdr_class, esg_rating, ...)
# werden NICHT hierher migriert und erfuellen nie ein Kriterium.
# ---------------------------------------------------------------------------

#: Kategorienkatalog (erweiterbar; neue Werte hier und im Literal in
#: schemas/review.py, ein Sync-Test haelt beide gleich).
SUSTAINABILITY_REVENUE_CATEGORIES: tuple[str, ...] = (
    "controversial_weapons",
    "conventional_weapons",
    "weapons",
    "tobacco",
    "thermal_coal",
    "fossil_fuels",
    "gambling",
    "adult_entertainment",
    "alcohol",
    "nuclear_power",
    "animal_testing",
)
SUSTAINABILITY_CONDUCT_CATEGORIES: tuple[str, ...] = ("ungc_violation",)

#: H-4 Kategorie-Hierarchie (konservativ, fest): Ein Nachweis der
#: uebergeordneten Kategorie deckt die untergeordnete ab, nie umgekehrt.
#: "weapons" = Waffen insgesamt (konventionelle und kontroverse); ein
#: Ausschluss "Waffen" mit Schwelle <= Hausschwelle erfuellt daher auch
#: "kontroverse Waffen" bzw. "konventionelle Waffen". Eine Messung der
#: Oberkategorie mit Exposure belegt dagegen keinen Verstoss in einer
#: bestimmten Unterkategorie und blockiert sie nicht.
SUSTAINABILITY_CATEGORY_COVERED_BY: dict[str, tuple[str, ...]] = {
    "controversial_weapons": ("weapons",),
    "conventional_weapons": ("weapons",),
}
SUSTAINABILITY_CLASSIFICATION_CATEGORIES: tuple[str, ...] = ("sfdr_classification", "impact_theme")
SUSTAINABILITY_CATEGORIES: tuple[str, ...] = (
    SUSTAINABILITY_REVENUE_CATEGORIES
    + SUSTAINABILITY_CONDUCT_CATEGORIES
    + SUSTAINABILITY_CLASSIFICATION_CATEGORIES
)

SUSTAINABILITY_KINDS: tuple[str, ...] = (
    "exclusion_policy",    # Produkt schliesst Emittenten ab x % Umsatz aus
    "measured_exposure",   # gemessenes Gewicht betroffener Emittenten (Look-through)
    "certification",       # Zertifikat/Label mit Nachweis
    "classification",      # z. B. SFDR-Artikel 6/8/9
)

#: Zulaessige Arten je Kategorie (fail-closed: alles andere 422).
SUSTAINABILITY_KINDS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    **{c: ("exclusion_policy", "measured_exposure") for c in SUSTAINABILITY_REVENUE_CATEGORIES},
    "ungc_violation": ("exclusion_policy", "measured_exposure"),
    "sfdr_classification": ("classification",),
    "impact_theme": ("classification", "certification"),
}

SFDR_CLASSIFICATION_VALUES: tuple[str, ...] = ("6", "8", "9")

#: Zulaessige Quellen (T-E3). Eine Quelle 'seed' gibt es bewusst nicht.
SUSTAINABILITY_SOURCE_TYPES: tuple[str, ...] = (
    "prospectus",
    "fund_contract",
    "kid",
    "factsheet",
    "provider_exclusion_policy",
    "provider_confirmation",
    "data_vendor",
    "house_analysis",
)

SUSTAINABILITY_STATUSES: tuple[str, ...] = ("draft", "approved", "retired")

#: Neutrale Quellbezeichnung fuer Kundendokumente je Quellentyp (FINMA-Sicht,
#: Pruefrunde #863): ohne Dritt- oder Markennamen. Default, wenn beim Erfassen
#: kein eigenes client_source_label angegeben wird.
SUSTAINABILITY_CLIENT_SOURCE_LABELS: dict[str, str] = {
    "prospectus": "Verkaufsprospekt",
    "fund_contract": "Fondsvertrag",
    "kid": "Basisinformationsblatt",
    "factsheet": "Factsheet des Anbieters",
    "provider_exclusion_policy": "Ausschlussrichtlinie des Anbieters",
    "provider_confirmation": "Bestätigung des Anbieters",
    "data_vendor": "Externer Datenanbieter",
    "house_analysis": "Eigene Analyse",
}

#: Hausstandard-Defaults (T-E1), Umsatzanteil des Emittenten in bps.
#: ungc_violation: keine Umsatzschwelle (schwere/anhaltende Verstoesse
#: ausgeschlossen) -> None. sfdr_classification/impact_theme sind keine
#: Umsatzkriterien und haben keinen Hausstandard. Tenant-aenderbar ueber
#: sustainability_exclusion_standards.
SUSTAINABILITY_DEFAULT_THRESHOLDS_BPS: dict[str, int | None] = {
    "controversial_weapons": 0,
    "conventional_weapons": 1000,
    "weapons": 1000,
    "tobacco": 500,
    "thermal_coal": 1000,
    "gambling": 500,
    "adult_entertainment": 500,
    "alcohol": 1000,
    "ungc_violation": None,
    "nuclear_power": 1000,
    "animal_testing": 1000,
    "fossil_fuels": 1000,
}

#: Gueltigkeit eines Nachweises ab Stichtag (T-E3).
SUSTAINABILITY_EVIDENCE_VALIDITY_MONTHS = 12

_SUSTAINABILITY_FOUR_EYES_CHECK = (
    "approved_by IS NULL OR approved_by <> created_by "
    "OR approval_mode = 'single_approver_attested'"
)


class ProductSustainabilityAttribute(Base):
    """Ein Nachweis je Produkt x Kategorie x Art x Stichtag.

    ``tenant_id`` NULL = Plattform-Nachweis (globaler Katalog; in Multi-
    Tenant nur super_admin, Regel R3); gesetzt = Tenant-Nachweis (Overlay,
    nur fuer diesen Tenant sichtbar). Freigegebene Zeilen sind inhaltlich
    unveraenderlich; eine Korrektur ist ein neuer Entwurf, der bei Freigabe
    den Vorgaenger abloest (status 'retired').
    """

    __tablename__ = "product_sustainability_attributes"

    id = Column(String, primary_key=True)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    tenant_id = Column(String, ForeignKey("tenants.id"))
    category = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    revenue_threshold_bps = Column(Integer)
    measured_exposure_bps = Column(Integer)
    value = Column(String)
    source_type = Column(String, nullable=False)
    source_reference = Column(String, nullable=False)
    source_provider = Column(String)
    source_retrieved_on = Column(String)
    # FINMA-Kundenanzeige (Pruefrunde #863, 9b/9c): Identitaet des
    # Quelldokuments und eine neutrale, kundentaugliche Quellbezeichnung
    # (keine Drittmarken), getrennt von source_provider (intern).
    source_document_title = Column(String)
    source_document_version = Column(String)
    source_document_date = Column(String)
    source_document_sha256 = Column(String)
    client_source_label = Column(String)
    as_of = Column(String, nullable=False)
    valid_until = Column(String, nullable=False)
    status = Column(String, nullable=False, default="draft")
    note = Column(String)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    approved_by = Column(String, ForeignKey("users.id"))
    approved_at = Column(String)
    approval_mode = Column(String)
    retired_by = Column(String, ForeignKey("users.id"))
    retired_at = Column(String)
    supersedes_id = Column(String, ForeignKey("product_sustainability_attributes.id"))
    updated_at = Column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('draft', 'approved', 'retired')", name="ck_psa_status"),
        CheckConstraint(
            "kind IN ('exclusion_policy', 'measured_exposure', 'certification', 'classification')",
            name="ck_psa_kind",
        ),
        CheckConstraint(
            "revenue_threshold_bps IS NULL OR (revenue_threshold_bps >= 0 AND revenue_threshold_bps <= 10000)",
            name="ck_psa_revenue_threshold_bps",
        ),
        CheckConstraint(
            "measured_exposure_bps IS NULL OR (measured_exposure_bps >= 0 AND measured_exposure_bps <= 10000)",
            name="ck_psa_measured_exposure_bps",
        ),
        CheckConstraint("valid_until >= as_of", name="ck_psa_valid_until"),
        CheckConstraint(_SUSTAINABILITY_FOUR_EYES_CHECK, name="ck_psa_four_eyes"),
        Index("ix_psa_product_category_status", "product_id", "category", "status"),
        Index("ix_psa_tenant_id", "tenant_id"),
        # Unique (product, tenant, category, kind, as_of) fuer nicht
        # abgeloeste Zeilen. Zwei partielle Indizes, weil NULL in Unique-
        # Indizes als verschieden gilt (Muster product_eligibility_rule_sets).
        Index(
            "ux_psa_active_tenant",
            "product_id", "tenant_id", "category", "kind", "as_of",
            unique=True,
            sqlite_where=text("tenant_id IS NOT NULL AND status <> 'retired'"),
            postgresql_where=text("tenant_id IS NOT NULL AND status <> 'retired'"),
        ),
        Index(
            "ux_psa_active_global",
            "product_id", "category", "kind", "as_of",
            unique=True,
            sqlite_where=text("tenant_id IS NULL AND status <> 'retired'"),
            postgresql_where=text("tenant_id IS NULL AND status <> 'retired'"),
        ),
    )


class SustainabilityExclusionStandard(Base):
    """Hausstandard je Tenant und Kategorie (Audit 05 §4.2, T-E1), versioniert.

    Je Tenant und Kategorie gilt hoechstens eine freigegebene Version mit
    offenem ``valid_to`` (aktuell); fehlt sie, gilt der Code-Default
    (``SUSTAINABILITY_DEFAULT_THRESHOLDS_BPS``). H-1 (Pruefrunde #863):
    Verschaerfungen (Schwelle <= Default, Kategorie aktiv) wirken sofort
    (approval_mode 'immediate_tightening'); Lockerungen unter den T-E1-
    Default (hoehere Schwelle oder Kategorie deaktiviert) entstehen als
    Entwurf und brauchen eine Vier-Augen-Freigabe. ``valid_from``/``valid_to``
    erlauben T3, die am Generate-Stichtag verwendete Schwelle samt Version im
    Snapshot zu speichern. Jede Aenderung steht im Audit-Log.
    """

    __tablename__ = "sustainability_exclusion_standards"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    category = Column(String, nullable=False)
    max_revenue_threshold_bps = Column(Integer)
    is_disabled = Column(Integer, nullable=False, default=0, server_default=text("0"))
    status = Column(String, nullable=False, default="approved", server_default=text("'approved'"))
    note = Column(String)
    updated_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_by = Column(String, ForeignKey("users.id"))
    approved_by = Column(String, ForeignKey("users.id"))
    approved_at = Column(String)
    approval_mode = Column(String)
    valid_from = Column(String)
    valid_to = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "max_revenue_threshold_bps IS NULL OR "
            "(max_revenue_threshold_bps >= 0 AND max_revenue_threshold_bps <= 10000)",
            name="ck_ses_threshold_bps",
        ),
        CheckConstraint("status IN ('draft', 'approved', 'retired')", name="ck_ses_status"),
        CheckConstraint("is_disabled IN (0, 1)", name="ck_ses_is_disabled"),
        CheckConstraint(
            "approved_by IS NULL OR created_by IS NULL OR approved_by <> created_by "
            "OR approval_mode IN ('immediate_tightening', 'single_approver_attested', 'pre_versioning')",
            name="ck_ses_four_eyes",
        ),
        Index("ix_ses_tenant_category", "tenant_id", "category", "status"),
        Index(
            "ux_ses_tenant_category_current", "tenant_id", "category", unique=True,
            sqlite_where=text("status = 'approved' AND valid_to IS NULL"),
            postgresql_where=text("status = 'approved' AND valid_to IS NULL"),
        ),
        Index(
            "ux_ses_tenant_category_pending", "tenant_id", "category", unique=True,
            sqlite_where=text("status = 'draft'"),
            postgresql_where=text("status = 'draft'"),
        ),
    )
