"""Vor-Ort-Signatur mit kundeneigenem Faktor (SIGN-001, Variante b).

Drei append-only Tabellen (UPDATE/DELETE per Trigger verboten, SQLite und
PostgreSQL), alle ohne FK auf mandates/clients (Muster audit_log /
risk_override_decisions: Demo-Purge und Mandatsloeschung bleiben moeglich),
nur Akteure verweisen auf ``users``. ``tenant_id`` direkt (RLS-Plan, PG-002),
aus dem Mandat abgeleitet und per INSERT-Guard geprueft
(core/mandate_evidence_tenant_boundary.py); nicht Teil der Hashes:

``onsite_signature_events``
    Zustandsmaschine als hash-verkettetes Ereignisjournal. Der aktuelle
    Zustand einer Transaktion ist das Ereignis mit der hoechsten
    ``sequence_no``. ``UNIQUE(transaction_id, sequence_no)`` macht jeden
    Uebergang atomar (Doppelklick / parallele Requests: genau einer gewinnt);
    der partielle Unique-Index auf ``challenge_id`` fuer FACTOR_VERIFIED /
    FACTOR_REJECTED macht jede Kunden-Challenge einmalig (Replay-Schutz).

``onsite_signature_challenges``
    Dokumentgebundene Kunden-Challenge. Gespeichert werden nur Salt und
    HMAC des Einmalcodes -- nie der Code selbst -- und der Binding-Hash ueber
    document_hash, transaction_id, customer_id, Zweck, Nonce und Ablaufzeit.

``onsite_signature_evidence``
    Evidence-Paket je signierter Transaktion (hoechstens eines,
    ``UNIQUE(transaction_id)``), in derselben DB-Transaktion geschrieben wie
    das SIGNED-Ereignis. Keine Stift-Biometrie, keine Ausweiskopie, kein
    Freitext; der Zustellnachweis der Kundenkopie folgt als eigenes Ereignis
    (SIGNED -> DELIVERY_PENDING -> DELIVERED).

Die Logik liegt in ``services/onsite_signature/``.
"""
from __future__ import annotations

from sqlalchemy import DDL, Column, ForeignKey, Index, Integer, String, event, text

from database import Base

EVENTS_TABLE = "onsite_signature_events"
CHALLENGES_TABLE = "onsite_signature_challenges"
EVIDENCE_TABLE = "onsite_signature_evidence"
APPEND_ONLY_TABLES = (EVENTS_TABLE, CHALLENGES_TABLE, EVIDENCE_TABLE)

# Einmaligkeit der Kunden-Challenge: hoechstens EIN Verbrauchs-Ereignis je
# challenge_id. Textgleich in ORM, Bootstrap-SQL und Alembic.
CHALLENGE_SINGLE_USE_INDEX = "ux_onsite_signature_events_challenge_use"
CHALLENGE_SINGLE_USE_PREDICATE = (
    "challenge_id IS NOT NULL AND event_type IN ('FACTOR_VERIFIED','FACTOR_REJECTED')"
)


def sqlite_immutability_triggers(table: str) -> tuple[str, str]:
    return (
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update "
        f"BEFORE UPDATE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END",
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_delete "
        f"BEFORE DELETE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END",
    )


class OnsiteSignatureEvent(Base):
    __tablename__ = EVENTS_TABLE
    __table_args__ = (
        Index(
            "ux_onsite_signature_events_sequence",
            "transaction_id",
            "sequence_no",
            unique=True,
        ),
        Index("ix_onsite_signature_events_document", "document_id"),
        Index("ix_onsite_signature_events_mandate", "mandate_id"),
        Index("ix_onsite_signature_events_tenant_id", "tenant_id"),
        Index(
            CHALLENGE_SINGLE_USE_INDEX,
            "challenge_id",
            unique=True,
            sqlite_where=text(CHALLENGE_SINGLE_USE_PREDICATE),
            postgresql_where=text(CHALLENGE_SINGLE_USE_PREDICATE),
        ),
    )

    id = Column(String, primary_key=True)
    schema_version = Column(String, nullable=False, default="OnsiteSignatureEventV1")
    tenant_id = Column(String)
    transaction_id = Column(String, nullable=False)
    sequence_no = Column(Integer, nullable=False)
    event_type = Column(String, nullable=False)
    state = Column(String, nullable=False)
    mandate_id = Column(String, nullable=False)
    client_id = Column(String, nullable=False)
    document_id = Column(String, nullable=False)
    document_hash = Column(String(64), nullable=False)
    challenge_id = Column(String)
    reason_code = Column(String)
    payload_json = Column(String, nullable=False)
    actor_id = Column(String, ForeignKey("users.id"), nullable=False)
    actor_role = Column(String, nullable=False)
    occurred_at = Column(String, nullable=False)
    time_source = Column(String, nullable=False)
    previous_event_hash = Column(String(64))
    event_hash = Column(String(64), nullable=False)
    created_at = Column(String, nullable=False)


class OnsiteSignatureChallenge(Base):
    __tablename__ = CHALLENGES_TABLE
    __table_args__ = (
        Index("ix_onsite_signature_challenges_transaction", "transaction_id"),
        Index("ix_onsite_signature_challenges_tenant_id", "tenant_id"),
    )

    id = Column(String, primary_key=True)
    schema_version = Column(String, nullable=False, default="OnsiteSignatureChallengeV1")
    tenant_id = Column(String)
    transaction_id = Column(String, nullable=False)
    mandate_id = Column(String, nullable=False)
    client_id = Column(String, nullable=False)
    document_hash = Column(String(64), nullable=False)
    purpose = Column(String, nullable=False)
    nonce = Column(String, nullable=False)
    issued_at = Column(String, nullable=False)
    expires_at = Column(String, nullable=False)
    delivery_channel = Column(String, nullable=False)
    code_salt = Column(String, nullable=False)
    code_hmac = Column(String(64), nullable=False)
    binding_hash = Column(String(64), nullable=False)
    policy_version = Column(String, nullable=False)
    actor_id = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)


class OnsiteSignatureEvidence(Base):
    __tablename__ = EVIDENCE_TABLE
    __table_args__ = (
        Index("ux_onsite_signature_evidence_transaction", "transaction_id", unique=True),
        Index("ix_onsite_signature_evidence_mandate", "mandate_id"),
        Index("ix_onsite_signature_evidence_tenant_id", "tenant_id"),
    )

    id = Column(String, primary_key=True)
    schema_version = Column(String, nullable=False, default="OnsiteSignatureEvidenceV1")
    tenant_id = Column(String)
    transaction_id = Column(String, nullable=False)
    mandate_id = Column(String, nullable=False)
    client_id = Column(String, nullable=False)
    document_id = Column(String, nullable=False)
    document_type = Column(String, nullable=False)
    document_version = Column(Integer, nullable=False)
    document_content_hash = Column(String, nullable=False)
    # Das System versioniert PDF-Vorlagen heute nicht; NULL = "nicht
    # versioniert" (ehrlich statt erfundener Versionsnummer).
    template_version = Column(String)
    document_class = Column(String, nullable=False)
    policy_version = Column(String, nullable=False)
    language = Column(String, nullable=False)
    displayed_document_hash = Column(String(64), nullable=False)
    final_document_hash = Column(String(64), nullable=False)
    signer_role = Column(String, nullable=False)
    consent_text_version = Column(String, nullable=False)
    consent_text_hash = Column(String(64), nullable=False)
    signed_at = Column(String, nullable=False)
    time_source = Column(String, nullable=False)
    timezone = Column(String, nullable=False)
    identity_check_result = Column(String, nullable=False)
    identity_check_method = Column(String, nullable=False)
    # Nur maskierte, erforderliche Ausweis-Metadaten (Art, Ausstellerstaat,
    # gueltig ja/nein) -- keine Nummer, keine Kopie.
    id_document_kind = Column(String, nullable=False)
    id_document_country = Column(String, nullable=False)
    id_document_valid = Column(Integer, nullable=False)
    customer_factor_kind = Column(String, nullable=False)
    customer_factor_challenge_id = Column(String, nullable=False)
    customer_factor_binding_hash = Column(String(64), nullable=False)
    customer_factor_channel = Column(String, nullable=False)
    customer_factor_verified_at = Column(String, nullable=False)
    customer_factor_actor_id = Column(String, nullable=False)
    advisor_id = Column(String, ForeignKey("users.id"), nullable=False)
    advisor_auth_method = Column(String, nullable=False)
    witness_statement_version = Column(String, nullable=False)
    witness_statement_hash = Column(String(64), nullable=False)
    device_app_version = Column(String, nullable=False)
    qes_provider = Column(String)
    qes_receipt_hash = Column(String(64))
    qes_certificate_chain_hash = Column(String(64))
    qes_timestamp = Column(String)
    qes_validation_result = Column(String)
    signed_event_hash = Column(String(64), nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    created_at = Column(String, nullable=False)


for _model in (OnsiteSignatureEvent, OnsiteSignatureChallenge, OnsiteSignatureEvidence):
    for _trigger_ddl in sqlite_immutability_triggers(_model.__tablename__):
        event.listen(
            _model.__table__,
            "after_create",
            DDL(_trigger_ddl).execute_if(dialect="sqlite"),
        )
