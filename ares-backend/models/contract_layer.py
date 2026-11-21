"""L2/L3 Vertragsschicht (H-179, Dok. 112 Kap. 7.1 V-1/A-1/D-1/R-1/P-1/E-1).

Ares erfindet keinen Rechtstext und keinen Owner-Wert. Die Firma (Owner)
erfasst ihre Inhalte versioniert (``owner_content_versions``); wirksam wird
eine Version erst durch die Freigabe einer ZWEITEN Person
(``owner_content_approvals``, gleiches Muster wie die KYC-Wiedervorlage in
models/tenant.py). Beide Tabellen sind append-only; eine Korrektur ist eine
neue Version, die erneut freigegeben wird. Die Freigaben bilden je Firma und
Schluessel eine lineare Kette (UNIQUE auf den Vorgaenger, erste mit
"GENESIS"): zwei gleichzeitige Freigaben auf denselben Stand koennen nie
beide gelingen.

``advice_rationales`` (P-1, Art. 15 FIDLEG) und ``w033_client_declarations``
(E-1) sind Mandats-Evidenz: ``tenant_id`` direkt, Mandant und Kunde aus dem
Mandat (INSERT-Guard, core/mandate_evidence_tenant_boundary.py), kein FK auf
mandates/clients (Purge-fest), append-only.

Alembic: c7e1a9d3f5b2 (gleiche DDL; SQLite legt die Tabellen ueber create_all
an, Trigger unten).
"""
from __future__ import annotations

from sqlalchemy import DDL, CheckConstraint, Column, ForeignKey, Index, Integer, String, UniqueConstraint, event

from database import Base

OWNER_CONTENT_GENESIS = "GENESIS"

OWNER_CONTENT_TABLES: tuple[str, ...] = ("owner_content_versions", "owner_content_approvals")
MANDATE_EVIDENCE_TABLES: tuple[str, ...] = ("advice_rationales", "w033_client_declarations")
CONTRACT_LAYER_APPEND_ONLY_TABLES: tuple[str, ...] = OWNER_CONTENT_TABLES + MANDATE_EVIDENCE_TABLES

W033_DECLARATION_KINDS: tuple[str, ...] = ("angaben_wahr_meldepflicht", "horizont_abraten")
W033_CAPTURE_CHANNELS: tuple[str, ...] = ("persoenlich_papier", "vor_ort", "kundenportal")


def append_only_sqlite_triggers(table: str) -> tuple[str, str]:
    return (
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update "
        f"BEFORE UPDATE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END",
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_delete "
        f"BEFORE DELETE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END",
    )


class OwnerContentVersion(Base):
    """Version eines Owner-Inhalts (Vertragsklausel, DSG-Abschnitt, W033-Text,
    Owner-Wert, Zuwendungsangabe einer Depotbank). ``body_text`` fuer Texte,
    ``value_json`` fuer typisierte Werte; ``content_hash`` = Siegel ueber alle
    Spalten ausser sich selbst (services/recommendation_release_gate.py::row_seal)."""

    __tablename__ = "owner_content_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "content_key", "version", name="uq_owner_content_versions_version"),
        CheckConstraint("version > 0", name="ck_owner_content_versions_version"),
        CheckConstraint(
            "body_text IS NOT NULL OR value_json IS NOT NULL",
            name="ck_owner_content_versions_payload",
        ),
        Index("ix_owner_content_versions_tenant_id", "tenant_id"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    content_key = Column(String, nullable=False)
    catalog_version = Column(String, nullable=False)
    version = Column(Integer, nullable=False)
    body_text = Column(String)
    value_json = Column(String)
    source_reference = Column(String, nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    content_hash = Column(String, nullable=False)


class OwnerContentApproval(Base):
    """Vier-Augen-Freigabe einer Version. Bindet den gesehenen
    ``content_hash`` und die unveraenderliche Freigabereferenz."""

    __tablename__ = "owner_content_approvals"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "content_key", "predecessor_approval_id",
            name="uq_owner_content_approvals_chain",
        ),
        Index("ix_owner_content_approvals_tenant_id", "tenant_id"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    content_key = Column(String, nullable=False)
    content_row_id = Column(String, nullable=False, unique=True)
    predecessor_approval_id = Column(String, nullable=False)
    approved_by = Column(String, ForeignKey("users.id"), nullable=False)
    approved_at = Column(String, nullable=False)
    approval_reference = Column(String, nullable=False)
    content_hash = Column(String, nullable=False)
    approval_hash = Column(String, nullable=False)


class AdviceRationale(Base):
    """P-1 (Art. 15 FIDLEG): Kundenbeduerfnisse und Gruende der Empfehlung je
    Empfehlungslauf, vom Berater erfasst (nie von Ares formuliert). Korrektur =
    neue Zeile; massgebend ist die juengste je Lauf."""

    __tablename__ = "advice_rationales"
    __table_args__ = (
        Index("ix_advice_rationales_tenant_id", "tenant_id"),
        Index("ix_advice_rationales_run", "mandate_id", "recommendation_run_id"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    mandate_id = Column(String, nullable=False)
    client_id = Column(String, nullable=False)
    recommendation_run_id = Column(String, nullable=False)
    client_needs = Column(String, nullable=False)
    recommendation_reasons = Column(String, nullable=False)
    recorded_by = Column(String, ForeignKey("users.id"), nullable=False)
    recorded_at = Column(String, nullable=False)
    rationale_hash = Column(String, nullable=False)


class W033ClientDeclaration(Base):
    """E-1 (Dok. 112 Kap. 4.1): Kundenbestaetigung je Risikoprofil-Version,
    gebunden an die gezeigte, freigegebene Owner-Textversion."""

    __tablename__ = "w033_client_declarations"
    __table_args__ = (
        CheckConstraint(
            "declaration_kind IN ('angaben_wahr_meldepflicht','horizont_abraten')",
            name="ck_w033_client_declarations_kind",
        ),
        CheckConstraint(
            "capture_channel IN ('persoenlich_papier','vor_ort','kundenportal')",
            name="ck_w033_client_declarations_channel",
        ),
        Index("ix_w033_client_declarations_tenant_id", "tenant_id"),
        Index("ix_w033_client_declarations_assessment", "mandate_id", "risk_assessment_id"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    mandate_id = Column(String, nullable=False)
    client_id = Column(String, nullable=False)
    risk_assessment_id = Column(String, nullable=False)
    declaration_kind = Column(String, nullable=False)
    content_key = Column(String, nullable=False)
    content_row_id = Column(String, nullable=False)
    content_hash = Column(String, nullable=False)
    horizon_years = Column(Integer)
    min_horizon_years = Column(Integer)
    capture_channel = Column(String, nullable=False)
    confirmed_at = Column(String, nullable=False)
    recorded_by = Column(String, ForeignKey("users.id"), nullable=False)
    recorded_at = Column(String, nullable=False)
    declaration_hash = Column(String, nullable=False)


for _model in (OwnerContentVersion, OwnerContentApproval, AdviceRationale, W033ClientDeclaration):
    for _trigger_ddl in append_only_sqlite_triggers(_model.__tablename__):
        event.listen(
            _model.__table__,
            "after_create",
            DDL(_trigger_ddl).execute_if(dialect="sqlite"),
        )
