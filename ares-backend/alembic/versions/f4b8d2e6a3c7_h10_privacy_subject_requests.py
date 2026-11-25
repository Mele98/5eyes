"""H10 C-DSG-02: Betroffenenanfragen als Fall.

DSG-Technikaudit 2026-11-11, Befund C-DSG-02: ``privacy_subject_requests``
haelt Eingang, Identitaetspruefung, Faelligkeit (``due_at`` aus der Fristen-Policy) mit
begruendeter Verlaengerung, Einschraenkungsentscheid (``decision_reason``),
Export-Hash und Zustellnachweis. ``tenant_id`` direkt (RLS beim Boot ueber
``ensure_postgres_rls_policies``), bewusst ohne FK auf clients/users (der
Nachweis ueberdauert eine Loeschung). Neue Tabelle, kein Backfill. SQLite
ueber create_all (Modell in models/privacy.py).

Revision ID: f4b8d2e6a3c7
Revises: e2f7c4a9d1b3
Create Date: 2026-11-11
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f4b8d2e6a3c7"
down_revision: Union[str, Sequence[str], None] = "e2f7c4a9d1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "privacy_subject_requests",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("request_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("received_at", sa.String(), nullable=False),
        sa.Column("received_channel", sa.String(), nullable=False),
        sa.Column("requester_relation", sa.String(), nullable=False),
        sa.Column("request_summary", sa.Text(), nullable=True),
        sa.Column("due_at", sa.String(), nullable=True),
        sa.Column("extended_due_at", sa.String(), nullable=True),
        sa.Column("extension_reason", sa.Text(), nullable=True),
        sa.Column("extension_notified_at", sa.String(), nullable=True),
        sa.Column("identity_verified_at", sa.String(), nullable=True),
        sa.Column("identity_verified_by", sa.String(), nullable=True),
        sa.Column("identity_method", sa.String(), nullable=True),
        sa.Column("identity_evidence_reference", sa.Text(), nullable=True),
        sa.Column("identity_failure_reason", sa.Text(), nullable=True),
        sa.Column("decision", sa.String(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decision_scope_json", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column("decided_at", sa.String(), nullable=True),
        sa.Column("completion_note", sa.Text(), nullable=True),
        sa.Column("linked_erasure_case_id", sa.String(), nullable=True),
        sa.Column("action_completed_by", sa.String(), nullable=True),
        sa.Column("action_completed_at", sa.String(), nullable=True),
        sa.Column("export_sha256", sa.String(length=64), nullable=True),
        sa.Column("export_schema_version", sa.Integer(), nullable=True),
        sa.Column("exported_by", sa.String(), nullable=True),
        sa.Column("exported_at", sa.String(), nullable=True),
        sa.Column("delivered_at", sa.String(), nullable=True),
        sa.Column("delivery_channel", sa.String(), nullable=True),
        sa.Column("delivery_reference", sa.Text(), nullable=True),
        sa.Column("delivered_by", sa.String(), nullable=True),
        sa.Column("delivery_recorded_at", sa.String(), nullable=True),
        sa.Column("withdrawn_reason", sa.Text(), nullable=True),
        sa.Column("withdrawn_at", sa.String(), nullable=True),
        sa.Column("opened_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint("received_channel IN ('EMAIL','LETTER','IN_PERSON','PORTAL','OTHER')", name="ck_privacy_subject_request_received_channel"),
        sa.CheckConstraint("delivery_channel IS NULL OR delivery_channel IN ('EMAIL','LETTER','IN_PERSON','PORTAL','OTHER')", name="ck_privacy_subject_request_delivery_channel"),
        sa.CheckConstraint("identity_method IS NULL OR identity_method IN ('ID_DOCUMENT_IN_PERSON','KNOWN_PERSON_IN_PERSON','CERTIFIED_COPY','VIDEO_IDENTIFICATION','OTHER')", name="ck_privacy_subject_request_identity_method"),
        sa.CheckConstraint("request_type IN ('ACCESS','PORTABILITY','RECTIFICATION','ERASURE')", name="ck_privacy_subject_request_type"),
        sa.CheckConstraint("status IN ('RECEIVED','IDENTITY_VERIFIED','IDENTITY_FAILED','DECIDED','COMPLETED','WITHDRAWN')", name="ck_privacy_subject_request_status"),
        sa.CheckConstraint("decision IS NULL OR decision IN ('FULFILL','RESTRICT','REFUSE')", name="ck_privacy_subject_request_decision"),
        sa.CheckConstraint("requester_relation IN ('SELF','REPRESENTATIVE')", name="ck_privacy_subject_request_relation"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_privacy_subject_requests_client", "privacy_subject_requests", ["tenant_id", "client_id"],
    )
    op.create_index(
        "ix_privacy_subject_requests_status", "privacy_subject_requests", ["tenant_id", "status", "due_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_privacy_subject_requests_status", table_name="privacy_subject_requests")
    op.drop_index("ix_privacy_subject_requests_client", table_name="privacy_subject_requests")
    op.drop_table("privacy_subject_requests")
