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

from sqlalchemy import DDL, CheckConstraint, Column, Index, Integer, String, Text, UniqueConstraint, event

from database import Base, _append_only_sqlite_triggers


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


class PrivacyOwnerValue(Base):
    """C-DSG-01/05: Angabe des Verantwortlichen zu einem Owner-Feld des
    Bearbeitungsverzeichnisses bzw. des Egress-Manifests (z. B. Kontakt,
    Begruendung einer Aufbewahrungsdauer, Staat und Garantie eines Kanals).

    Versioniert: eine Aenderung legt eine neue Zeile (``revision`` + 1) an und
    setzt die bisherige auf ``RETIRED``. Ares belegt keine dieser Angaben vor;
    ohne ``CONFIRMED``-Zeile gilt das Feld als offen."""

    __tablename__ = "privacy_owner_values"
    __table_args__ = (
        CheckConstraint("status IN ('CONFIRMED','RETIRED')", name="ck_privacy_owner_value_status"),
        Index("ix_privacy_owner_values_lookup", "tenant_id", "field_key", "status"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    field_key = Column(String, nullable=False)
    value = Column(Text, nullable=False)
    revision = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="CONFIRMED")
    value_sha256 = Column(String(64), nullable=False)
    confirmed_by = Column(String, nullable=False)
    confirmed_at = Column(String, nullable=False)
    retired_at = Column(String)


class PrivacySubjectRequest(Base):
    """C-DSG-02: Betroffenenanfrage (Auskunft, Herausgabe, Berichtigung,
    Loeschung) als Fall mit Eingang, Identitaetspruefung, Frist,
    Einschraenkungsentscheid und Zustellnachweis.

    ``due_at`` = Eingang + 30 Tage (Kalendertage, Datum). Eine Verlaengerung
    braucht Begruendung und Mitteilung an die betroffene Person. Der Export
    fuer Auskunft/Herausgabe entsteht nur ueber diesen Fall; sein Hash steht
    in ``export_sha256``. Kein FK auf clients/users (der Nachweis muss eine
    Loeschung des Kunden ueberdauern)."""

    __tablename__ = "privacy_subject_requests"
    __table_args__ = (
        CheckConstraint(
            "request_type IN ('ACCESS','PORTABILITY','RECTIFICATION','ERASURE')",
            name="ck_privacy_subject_request_type",
        ),
        CheckConstraint(
            "status IN ('RECEIVED','IDENTITY_VERIFIED','IDENTITY_FAILED','DECIDED','COMPLETED','WITHDRAWN')",
            name="ck_privacy_subject_request_status",
        ),
        CheckConstraint(
            "received_channel IN ('EMAIL','LETTER','IN_PERSON','PORTAL','OTHER')",
            name="ck_privacy_subject_request_received_channel",
        ),
        CheckConstraint(
            "requester_relation IN ('SELF','REPRESENTATIVE')",
            name="ck_privacy_subject_request_relation",
        ),
        CheckConstraint(
            "identity_method IS NULL OR identity_method IN ('ID_DOCUMENT_IN_PERSON','KNOWN_PERSON_IN_PERSON',"
            "'CERTIFIED_COPY','VIDEO_IDENTIFICATION','OTHER')",
            name="ck_privacy_subject_request_identity_method",
        ),
        CheckConstraint(
            "decision IS NULL OR decision IN ('FULFILL','RESTRICT','REFUSE')",
            name="ck_privacy_subject_request_decision",
        ),
        CheckConstraint(
            "delivery_channel IS NULL OR delivery_channel IN ('EMAIL','LETTER','IN_PERSON','PORTAL','OTHER')",
            name="ck_privacy_subject_request_delivery_channel",
        ),
        Index("ix_privacy_subject_requests_client", "tenant_id", "client_id"),
        Index("ix_privacy_subject_requests_status", "tenant_id", "status", "due_at"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    client_id = Column(String, nullable=False)
    request_type = Column(String, nullable=False)
    status = Column(String, nullable=False)
    received_at = Column(String, nullable=False)
    received_channel = Column(String, nullable=False)
    requester_relation = Column(String, nullable=False)
    request_summary = Column(Text)
    due_at = Column(String)  # aus der Fristen-Policy (Owner-Feld); fehlt sie, bleibt NULL
    extended_due_at = Column(String)
    extension_reason = Column(Text)
    extension_notified_at = Column(String)
    identity_verified_at = Column(String)
    identity_verified_by = Column(String)
    identity_method = Column(String)
    identity_evidence_reference = Column(Text)
    identity_failure_reason = Column(Text)
    decision = Column(String)
    decision_reason = Column(Text)
    decision_scope_json = Column(Text)
    decided_by = Column(String)
    decided_at = Column(String)
    completion_note = Column(Text)
    linked_erasure_case_id = Column(String)
    action_completed_by = Column(String)
    action_completed_at = Column(String)
    export_sha256 = Column(String(64))
    export_schema_version = Column(Integer)
    exported_by = Column(String)
    exported_at = Column(String)
    delivered_at = Column(String)
    delivery_channel = Column(String)
    delivery_reference = Column(Text)
    delivered_by = Column(String)
    delivery_recorded_at = Column(String)
    withdrawn_reason = Column(Text)
    withdrawn_at = Column(String)
    opened_by = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    # Optimistische Sperre (Vertrag C-DSG-02, Nachtrag 1): zwei gleichzeitige
    # Statuswechsel -> genau einer wirksam, der andere 409.
    row_version = Column(Integer, nullable=False, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": row_version}


class PrivacySecurityIncident(Base):
    """C-DSG-04: Verletzung der Datensicherheit als Fall mit Entdeckung,
    Risikobewertung, Meldeentscheid an den EDOEB, Information der Betroffenen,
    Nachweisen und Abschluss (services/security_incident_register.py)."""

    __tablename__ = "privacy_security_incidents"
    __table_args__ = (
        CheckConstraint("status IN ('OPEN','ASSESSED','DECIDED','CLOSED')", name="ck_privacy_incident_status"),
        CheckConstraint(
            "incident_type IN ('CONFIDENTIALITY','INTEGRITY','AVAILABILITY')", name="ck_privacy_incident_type",
        ),
        CheckConstraint("risk_level IS NULL OR risk_level IN ('LOW','HIGH','UNKNOWN')", name="ck_privacy_incident_risk"),
        CheckConstraint(
            "notification_decision IS NULL OR notification_decision IN ('NOTIFY','NOT_REQUIRED')",
            name="ck_privacy_incident_notification_decision",
        ),
        CheckConstraint(
            "subject_notification_decision IS NULL OR subject_notification_decision IN "
            "('NOTIFY','NOT_REQUIRED','DEFERRED')",
            name="ck_privacy_incident_subject_decision",
        ),
        CheckConstraint(
            "NOT (risk_level IN ('HIGH','UNKNOWN') AND notification_decision = 'NOT_REQUIRED')",
            name="ck_privacy_incident_high_risk_notify",
        ),
        CheckConstraint("remediation_status IN ('OPEN','DONE')", name="ck_privacy_incident_remediation"),
        Index("ix_privacy_security_incidents_status", "tenant_id", "status", "discovered_at"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    reference = Column(String, nullable=False)
    status = Column(String, nullable=False)
    discovered_at = Column(String, nullable=False)
    incident_type = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    affected_data_categories_json = Column(Text, nullable=False)
    affected_subjects_count = Column(Integer)
    containment_measures = Column(Text)
    risk_level = Column(String)
    risk_rationale = Column(Text)
    risk_assessed_by = Column(String)
    risk_assessed_at = Column(String)
    notification_decision = Column(String)
    notification_decision_reason = Column(Text)
    notification_decided_by = Column(String)
    notification_decided_at = Column(String)
    edoeb_notified_at = Column(String)
    edoeb_reference = Column(Text)
    edoeb_notified_by = Column(String)
    subject_notification_decision = Column(String)
    subject_notification_reason = Column(Text)
    subject_notification_decided_by = Column(String)
    subject_notification_decided_at = Column(String)
    subjects_notified_at = Column(String)
    subject_notification_channel = Column(String)
    subject_notification_reference = Column(Text)
    subjects_notified_by = Column(String)
    evidence_json = Column(Text, nullable=False)
    recorded_by = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    closed_at = Column(String)
    closed_by = Column(String)
    closure_note = Column(Text)
    remediation_status = Column(String, nullable=False, default="OPEN")
    remediation_note = Column(Text)
    remediation_completed_by = Column(String)
    remediation_completed_at = Column(String)
    row_version = Column(Integer, nullable=False, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": row_version}



# ── H10 Nachtrag 1 (Codex-Vertrag 2026-11-12): versionierte Freigaben und
# append-only Ereignisse. Alle Tabellen tenant_direct, ohne FK, append-only
# per Trigger (SQLite hier, PostgreSQL in Alembic c4e8a2f6d0b7).

class ProcessingActivityVersion(Base):
    """C-DSG-01: freigegebene Fassung einer Bearbeitung je Mandant. Inhalt =
    Bearbeitung aus dem Register samt aufgeloesten Owner-Angaben; Hash ueber
    die kanonische Form. Gueltig ab ``valid_from`` bis zur naechsten Fassung."""

    __tablename__ = "processing_activity_versions"
    __table_args__ = (
        CheckConstraint("status IN ('INVENTORY_REQUIRED','APPROVED')", name="ck_processing_activity_version_status"),
        UniqueConstraint("tenant_id", "activity_key", "valid_from", name="uq_processing_activity_version_valid_from"),
        Index("ix_processing_activity_versions_key", "tenant_id", "activity_key", "valid_from"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    activity_key = Column(String, nullable=False)
    version = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    register_version = Column(String, nullable=False)
    content_json = Column(Text, nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    valid_from = Column(String, nullable=False)
    approved_by = Column(String)
    approved_at = Column(String)
    created_by = Column(String, nullable=False)
    created_at = Column(String, nullable=False)


class OutboundManifestVersion(Base):
    """C-DSG-03: freigegebene Fassung eines Egress-Kanals je Mandant (Kanal
    samt aufgeloesten Staat-/Garantie-/Grundlage-Angaben, Hash)."""

    __tablename__ = "outbound_processing_manifest_versions"
    __table_args__ = (
        CheckConstraint("status IN ('INVENTORY_REQUIRED','APPROVED')", name="ck_outbound_manifest_version_status"),
        UniqueConstraint("tenant_id", "channel_id", "valid_from", name="uq_outbound_manifest_version_valid_from"),
        Index("ix_outbound_manifest_versions_key", "tenant_id", "channel_id", "valid_from"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    channel_id = Column(String, nullable=False)
    version = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    manifest_version = Column(String, nullable=False)
    content_json = Column(Text, nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    valid_from = Column(String, nullable=False)
    approved_by = Column(String)
    approved_at = Column(String)
    created_by = Column(String, nullable=False)
    created_at = Column(String, nullable=False)


class OutboundProcessingEvent(Base):
    """C-DSG-03: blockierte ausgehende Verbindung (persistent, Mandant der
    Installation). Nur Kanal, Klasse, Zielhost, Reason-Code, Zeit und die
    Hash-Referenz des Kanals -- nie Payload, Secrets oder Personendaten."""

    __tablename__ = "privacy_egress_events"
    __table_args__ = (
        CheckConstraint("result IN ('BLOCKED')", name="ck_privacy_egress_event_result"),
        Index("ix_privacy_egress_events_time", "tenant_id", "occurred_at"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    occurred_at = Column(String, nullable=False)
    channel_id = Column(String)
    channel_class = Column(String)
    destination_host = Column(String, nullable=False)
    reason_code = Column(String, nullable=False)
    result = Column(String, nullable=False)
    manifest_version = Column(String)
    channel_sha256 = Column(String(64))
    # H10 Nachtrag 2 (C-900-02): Manifest-Hash und Schema-Hash des Payloads
    # (nur Methode, Pfadtiefe, Feldnamen -- nie Werte).
    manifest_sha256 = Column(String(64))
    payload_schema_hash = Column(String(64))


class OutboundTransferDailyCount(Base):
    """H10 Nachtrag 3: erlaubte Uebertragungen nur als Zaehler je Kanal und
    Tag (Mandant der Installation), ohne Inhalt, Ziel-URL oder Payload."""

    __tablename__ = "privacy_egress_daily_counts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "day", "channel_id", name="uq_privacy_egress_daily_count"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    day = Column(String, nullable=False)
    channel_id = Column(String, nullable=False)
    allowed_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(String, nullable=False)


class SecurityIncidentArtifact(Base):
    """C-DSG-04 / C-900-03: Nachweis-Artefakt eines Vorfalls mit Digest,
    Medientyp, Groesse und Erfassungszeit; ``row_sha256`` versiegelt die
    Zeile, ``event_sha256`` bindet sie an das Ereignis der Fallkette.
    Append-only."""

    __tablename__ = "privacy_security_incident_artifacts"
    __table_args__ = (
        Index("ix_privacy_security_incident_artifacts_incident", "tenant_id", "incident_id"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    incident_id = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    reference = Column(Text, nullable=False)
    sha256 = Column(String(64), nullable=False)
    media_type = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    recorded_by = Column(String, nullable=False)
    recorded_at = Column(String, nullable=False)
    event_sha256 = Column(String(64))
    row_sha256 = Column(String(64), nullable=False)


class _CaseEventColumns:
    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    case_id = Column(String, nullable=False)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String, nullable=False)
    actor_id = Column(String, nullable=False)
    occurred_at = Column(String, nullable=False)
    payload_json = Column(Text, nullable=False)
    artifact_sha256 = Column(String(64))
    previous_sha256 = Column(String(64))
    event_sha256 = Column(String(64), nullable=False)


class PrivacySubjectRequestEvent(_CaseEventColumns, Base):
    """C-DSG-02: append-only, verkettete Ereignisse eines Anfragefalls
    (Eingang, Identitaet, Verlaengerung, Entscheid, Export, Umsetzung,
    Zustellung, Rueckzug). ``(case_id, sequence)`` eindeutig."""

    __tablename__ = "privacy_subject_request_events"
    __table_args__ = (
        UniqueConstraint("case_id", "sequence", name="uq_privacy_subject_request_event_sequence"),
        Index("ix_privacy_subject_request_events_case", "tenant_id", "case_id"),
    )


class PrivacySecurityIncidentEvent(_CaseEventColumns, Base):
    """C-DSG-04: append-only, verkettete Ereignisse eines Vorfalls inkl.
    Nachweisen mit Artefakt-Hash (``artifact_sha256``)."""

    __tablename__ = "privacy_security_incident_events"
    __table_args__ = (
        UniqueConstraint("case_id", "sequence", name="uq_privacy_security_incident_event_sequence"),
        Index("ix_privacy_security_incident_events_case", "tenant_id", "case_id"),
    )


H10_APPEND_ONLY_TABLES = (
    "processing_activity_versions", "outbound_processing_manifest_versions", "privacy_egress_events",
    "privacy_subject_request_events", "privacy_security_incident_events", "privacy_security_incident_artifacts",
)

for _model in (ProcessingActivityVersion, OutboundManifestVersion, OutboundProcessingEvent,
               PrivacySubjectRequestEvent, PrivacySecurityIncidentEvent, SecurityIncidentArtifact):
    for _trigger_ddl in _append_only_sqlite_triggers(_model.__tablename__):
        event.listen(_model.__table__, "after_create", DDL(_trigger_ddl).execute_if(dialect="sqlite"))
