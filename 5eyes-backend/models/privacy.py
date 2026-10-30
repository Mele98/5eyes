"""PRIVACY-001: Aufbewahrungsmatrix, Legal Holds und Loeschvorgaenge.

Fachliche Logik: services/privacy_erasure.py. Inventar der durchsuchten
Tabellen: services/privacy_erasure_inventory.py.

Alle Tabellen tragen ``tenant_id`` direkt (RLS-Plan, tenant_direct) und
bewusst keinen harten FK auf clients/mandates/users: ein Demo-Purge darf
nicht an ihnen scheitern, und der Loeschbeleg muss den Kunden ueberdauern.
Fristen, Rechtsgrundlagen und Methodenbeschreibungen sind Policy-Daten
(``privacy_retention_policies``), nie Code-Konstanten.
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, Index, Integer, String, Text

from database import Base


class PrivacyRetentionPolicy(Base):
    """Eine Zeile der Aufbewahrungsmatrix je Mandant, Nachweisart und
    Datenkategorie (``*`` = alle Kategorien der Nachweisart), versioniert.

    Nur ``APPROVED`` wirkt. ``PROPOSED`` ist ein Vorschlag ohne Wirkung; ein
    Loeschgesuch bleibt dann "Entscheid ausstehend"."""

    __tablename__ = "privacy_retention_policies"
    __table_args__ = (
        CheckConstraint("status IN ('PROPOSED','APPROVED','RETIRED')", name="ck_privacy_policy_status"),
        CheckConstraint(
            "disposition IN ('DELETE','ANONYMIZE','PARTIAL_DELETE_MINIMIZE','RETAIN_RESTRICTED')",
            name="ck_privacy_policy_disposition",
        ),
        Index("ix_privacy_retention_policies_lookup", "tenant_id", "evidence_type", "data_category", "status"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    evidence_type = Column(String, nullable=False)
    data_category = Column(String, nullable=False)
    version = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="PROPOSED")
    disposition = Column(String, nullable=False)
    legal_basis = Column(Text)
    retention_trigger = Column(String)
    retention_months = Column(Integer)
    matrix_json = Column(Text, nullable=False)
    policy_hash = Column(String(64), nullable=False)
    proposed_by = Column(String, nullable=False)
    proposed_at = Column(String, nullable=False)
    approved_by = Column(String)
    approved_at = Column(String)
    retired_at = Column(String)


class PrivacyRoleDesignation(Base):
    """Benennung eines Benutzers als Legal oder Privacy innerhalb eines
    Mandanten. Nur so benannte Personen duerfen Policies genehmigen und
    Legal Holds setzen, verlaengern oder aufheben."""

    __tablename__ = "privacy_role_designations"
    __table_args__ = (
        CheckConstraint("privacy_role IN ('LEGAL','PRIVACY')", name="ck_privacy_role_designation_role"),
        Index("ix_privacy_role_designations_user", "tenant_id", "user_id"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    user_id = Column(String, nullable=False)
    privacy_role = Column(String, nullable=False)
    granted_by = Column(String, nullable=False)
    granted_at = Column(String, nullable=False)
    revoked_by = Column(String)
    revoked_at = Column(String)


class PrivacyLegalHold(Base):
    """Legal Hold mit Fall-ID, Rechtsgrund, Umfang (Nachweisarten),
    Setzer, Genehmiger und Review-/Ablaufdatum."""

    __tablename__ = "privacy_legal_holds"
    __table_args__ = (
        CheckConstraint("status IN ('PROPOSED','ACTIVE','RELEASED')", name="ck_privacy_legal_hold_status"),
        Index("ix_privacy_legal_holds_client", "tenant_id", "client_id", "status"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    client_id = Column(String, nullable=False)
    case_reference = Column(String, nullable=False)
    legal_reason = Column(Text, nullable=False)
    scope_json = Column(Text, nullable=False)
    set_by = Column(String, nullable=False)
    approved_by = Column(String)
    approved_at = Column(String)
    review_date = Column(String, nullable=False)
    expires_at = Column(String)
    status = Column(String, nullable=False, default="PROPOSED")
    extension_count = Column(Integer, nullable=False, default=0)
    released_by = Column(String)
    released_at = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class PrivacyErasureCase(Base):
    """Ein Loeschgesuch (Vorgang) mit Status und Loeschbeleg.

    Der Beleg (``receipt_json``) enthaelt Vorgangs-ID, Kategorien,
    Zaehlungen und Digests, aber keine kopierten Personendaten."""

    __tablename__ = "privacy_erasure_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DECISION_PENDING','READY','EXECUTED','PARTIALLY_EXECUTED')",
            name="ck_privacy_erasure_case_status",
        ),
        Index("ix_privacy_erasure_cases_client", "tenant_id", "client_id"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    client_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    inventory_version = Column(String, nullable=False)
    relationship_end_date = Column(String)
    opened_by = Column(String, nullable=False)
    opened_at = Column(String, nullable=False)
    executed_by = Column(String)
    executed_at = Column(String)
    receipt_json = Column(Text)
    receipt_sha256 = Column(String(64))
    updated_at = Column(String, nullable=False)


class PrivacyErasureDisposition(Base):
    """Disposition je Tabelle und Datenkategorie innerhalb eines Vorgangs.

    ``decision_status``: ``NO_DATA`` (keine Zeilen), ``DECISION_PENDING``
    (keine genehmigte Policy bzw. Fristausloeser fehlt), ``DECIDED``,
    ``APPLIED``, ``FAILED`` (mit ``failure_code``), ``DISPOSAL_DUE``
    (Frist abgelaufen, Entsorgung offen), ``DISPOSED``.

    Eine angewendete ``RETAIN_RESTRICTED``-/``LEGAL_HOLD``-Zeile ist der
    Sperrvermerk: die Nachweisart ist fuer Beratung, Analytics und Export
    gesperrt, bis die Zeile entsorgt ist."""

    __tablename__ = "privacy_erasure_dispositions"
    __table_args__ = (
        CheckConstraint(
            "decision_status IN ('NO_DATA','DECISION_PENDING','DECIDED','APPLIED','FAILED',"
            "'DISPOSAL_DUE','DISPOSED')",
            name="ck_privacy_disposition_decision_status",
        ),
        CheckConstraint(
            "disposition IS NULL OR disposition IN ('DELETE','ANONYMIZE','PARTIAL_DELETE_MINIMIZE',"
            "'RETAIN_RESTRICTED','LEGAL_HOLD')",
            name="ck_privacy_disposition_value",
        ),
        Index("ix_privacy_erasure_dispositions_case", "case_id"),
        Index("ix_privacy_erasure_dispositions_client", "tenant_id", "client_id", "evidence_type"),
    )

    id = Column(String, primary_key=True)
    case_id = Column(String, nullable=False)
    tenant_id = Column(String)
    client_id = Column(String, nullable=False)
    table_name = Column(String, nullable=False)
    data_category = Column(String, nullable=False)
    evidence_type = Column(String, nullable=False)
    method = Column(String)
    row_count = Column(Integer, nullable=False, default=0)
    rows_digest = Column(String(64))
    decision_status = Column(String, nullable=False)
    disposition = Column(String)
    policy_id = Column(String)
    legal_hold_id = Column(String)
    legal_basis = Column(Text)
    retention_trigger = Column(String)
    retain_until = Column(String)
    failure_code = Column(String)
    applied_at = Column(String)
    disposed_at = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
