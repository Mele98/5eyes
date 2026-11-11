"""H10 C-DSG-04: Register der Verletzungen der Datensicherheit.

DSG-Technikaudit 2026-11-11, Befund C-DSG-04: ``privacy_security_incidents``
haelt Entdeckung, Risikobewertung, Meldeentscheid an den EDOEB (bei hohem
Risiko per CHECK nur 'NOTIFY'), Meldenachweis, Entscheid und Nachweis der
Information Betroffener, Nachweise und Abschluss. ``tenant_id`` direkt (RLS
beim Boot ueber ``ensure_postgres_rls_policies``), kein FK. Neue Tabelle,
kein Backfill. SQLite ueber create_all (Modell in models/privacy.py).

Revision ID: a7c3e9f1b5d2
Revises: f4b8d2e6a3c7
Create Date: 2026-11-11
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a7c3e9f1b5d2"
down_revision: Union[str, Sequence[str], None] = "f4b8d2e6a3c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "privacy_security_incidents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("reference", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("discovered_at", sa.String(), nullable=False),
        sa.Column("incident_type", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("affected_data_categories_json", sa.Text(), nullable=False),
        sa.Column("affected_subjects_count", sa.Integer(), nullable=True),
        sa.Column("containment_measures", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(), nullable=True),
        sa.Column("risk_rationale", sa.Text(), nullable=True),
        sa.Column("risk_assessed_by", sa.String(), nullable=True),
        sa.Column("risk_assessed_at", sa.String(), nullable=True),
        sa.Column("notification_decision", sa.String(), nullable=True),
        sa.Column("notification_decision_reason", sa.Text(), nullable=True),
        sa.Column("notification_decided_by", sa.String(), nullable=True),
        sa.Column("notification_decided_at", sa.String(), nullable=True),
        sa.Column("edoeb_notified_at", sa.String(), nullable=True),
        sa.Column("edoeb_reference", sa.Text(), nullable=True),
        sa.Column("edoeb_notified_by", sa.String(), nullable=True),
        sa.Column("subject_notification_decision", sa.String(), nullable=True),
        sa.Column("subject_notification_reason", sa.Text(), nullable=True),
        sa.Column("subject_notification_decided_by", sa.String(), nullable=True),
        sa.Column("subject_notification_decided_at", sa.String(), nullable=True),
        sa.Column("subjects_notified_at", sa.String(), nullable=True),
        sa.Column("subject_notification_channel", sa.String(), nullable=True),
        sa.Column("subject_notification_reference", sa.Text(), nullable=True),
        sa.Column("subjects_notified_by", sa.String(), nullable=True),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("closed_at", sa.String(), nullable=True),
        sa.Column("closed_by", sa.String(), nullable=True),
        sa.Column("closure_note", sa.Text(), nullable=True),
        sa.CheckConstraint("incident_type IN ('CONFIDENTIALITY','INTEGRITY','AVAILABILITY')", name="ck_privacy_incident_type"),
        sa.CheckConstraint("notification_decision IS NULL OR notification_decision IN ('NOTIFY','NOT_REQUIRED')", name="ck_privacy_incident_notification_decision"),
        sa.CheckConstraint("subject_notification_decision IS NULL OR subject_notification_decision IN ('NOTIFY','NOT_REQUIRED','DEFERRED')", name="ck_privacy_incident_subject_decision"),
        sa.CheckConstraint("risk_level IS NULL OR risk_level IN ('LOW','HIGH')", name="ck_privacy_incident_risk"),
        sa.CheckConstraint("status IN ('OPEN','ASSESSED','DECIDED','CLOSED')", name="ck_privacy_incident_status"),
        sa.CheckConstraint("NOT (risk_level = 'HIGH' AND notification_decision = 'NOT_REQUIRED')", name="ck_privacy_incident_high_risk_notify"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_privacy_security_incidents_status", "privacy_security_incidents",
        ["tenant_id", "status", "discovered_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_privacy_security_incidents_status", table_name="privacy_security_incidents")
    op.drop_table("privacy_security_incidents")
