"""CMA_POLICY: versionierte, vier-Augen-genehmigte Kapitalmarktannahmen-Policy.

CMA-001 (Entscheidungsdokument 2026-10-27, Abschnitt 5 und Paragraf 7.4):
ein ``CMA_POLICY``-Paket bindet eine CMA-Version an Herkunft, Methode,
Komponentenledger und zwei unabhaengige Freigaben. Das Modell erfindet
KEINE Fachwerte -- Werte, Quellen und Bereiche kommen ausschliesslich vom
Ersteller und werden vom Ausschuss freigegeben.

Lebenszyklus: DRAFT -> VALIDATED -> APPROVED -> ACTIVE -> RETIRED/REVOKED
(services/cma_policy.py). Inhalt und Komponenten sind nur im DRAFT
aenderbar; ab VALIDATED bindet ``content_hash`` den Inhalt, und jede
Freigabe speichert den Hash, den sie gesehen hat. Freigaben sind
append-only (Trigger). Korrektur = neue Version; Rollback = erneut
genehmigte neue Version mit unveraendert uebernommenem Inhalt.

Globale Referenzdaten ohne Tenant-Spalte (wie ``optimizer_policies``);
Schreibrecht nur Portfolio Management (services/auth.py::
require_portfolio_management).
"""
from __future__ import annotations

from sqlalchemy import (
    DDL,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
)

from database import CMA_POLICY_APPROVAL_SQLITE_TRIGGERS, Base


class CmaPolicy(Base):
    __tablename__ = "cma_policies"
    __table_args__ = (
        UniqueConstraint("policy_id", "version", name="uq_cma_policies_policy_version"),
        Index("ix_cma_policies_cma_status", "capital_market_assumptions_id", "status"),
    )

    id = Column(String, primary_key=True)
    policy_id = Column(String, nullable=False)
    version = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="DRAFT")
    capital_market_assumptions_id = Column(
        String, ForeignKey("capital_market_assumptions.id"), nullable=False,
    )
    # Eigene Entscheidungs-ID der Korrelationsannahme (z. B. CMA-CORR-001);
    # bewusst NICHT ADR-12a (KGV).
    correlation_policy_ref = Column(String)
    valid_from = Column(String, nullable=False)
    valid_until = Column(String)
    data_as_of = Column(String, nullable=False)
    base_currency = Column(String, nullable=False)
    return_basis = Column(String, nullable=False)  # nominal | real
    fee_basis = Column(String, nullable=False)  # gross | net
    method_version = Column(String, nullable=False)
    sources_json = Column(String, nullable=False)
    rationale = Column(String, nullable=False)
    impact_report_ref = Column(String)
    supersedes_id = Column(String, ForeignKey("cma_policies.id"))
    expiry_rule = Column(String)
    exception_rule = Column(String)
    rollback_rule = Column(String)
    content_hash = Column(String(64))
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    validated_by = Column(String, ForeignKey("users.id"))
    validated_at = Column(String)
    approved_at = Column(String)
    activated_by = Column(String, ForeignKey("users.id"))
    activated_at = Column(String)
    retired_at = Column(String)
    revoked_by = Column(String, ForeignKey("users.id"))
    revoked_at = Column(String)
    revocation_reason = Column(String)


class CmaPolicyComponent(Base):
    """Komponentenledger je Renditeannahme. Ein Eintrag pro
    (Policy, Anlage, Komponente) -- verhindert Doppelanwendung."""

    __tablename__ = "cma_policy_components"
    __table_args__ = (
        UniqueConstraint(
            "policy_row_id", "asset_key", "component",
            name="uq_cma_policy_components_asset_component",
        ),
    )

    id = Column(String, primary_key=True)
    policy_row_id = Column(String, ForeignKey("cma_policies.id"), nullable=False)
    asset_key = Column(String, nullable=False)
    component = Column(String, nullable=False)
    value_bps = Column(Integer, nullable=False)
    unit = Column(String, nullable=False)
    horizon_years = Column(Integer, nullable=False)
    method = Column(String, nullable=False)
    source = Column(String, nullable=False)
    sign = Column(String, nullable=False)  # positive | negative | either
    confidence = Column(String)
    range_min_bps = Column(Integer, nullable=False)
    range_max_bps = Column(Integer, nullable=False)
    created_at = Column(String, nullable=False)


class CmaPolicyApproval(Base):
    """Append-only Freigabe; bindet den gesehenen Inhalts-Hash."""

    __tablename__ = "cma_policy_approvals"
    __table_args__ = (
        UniqueConstraint(
            "policy_row_id", "approver_id", name="uq_cma_policy_approvals_approver",
        ),
    )

    id = Column(String, primary_key=True)
    policy_row_id = Column(String, ForeignKey("cma_policies.id"), nullable=False)
    approver_id = Column(String, ForeignKey("users.id"), nullable=False)
    approved_at = Column(String, nullable=False)
    rationale = Column(String, nullable=False)
    content_hash = Column(String(64), nullable=False)


for _trigger_ddl in CMA_POLICY_APPROVAL_SQLITE_TRIGGERS:
    event.listen(
        CmaPolicyApproval.__table__,
        "after_create",
        DDL(_trigger_ddl).execute_if(dialect="sqlite"),
    )
