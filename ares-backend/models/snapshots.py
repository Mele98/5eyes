from sqlalchemy import (
    DDL, BigInteger, CheckConstraint, Column, ForeignKey, ForeignKeyConstraint, Index, Integer,
    String, UniqueConstraint, event, text,
)
from sqlalchemy.orm import relationship
from database import (
    ADVISORY_ENVELOPE_SQLITE_TENANT_GUARDS,
    ADVISORY_ENVELOPE_SQLITE_TRIGGERS,
    DEPOT_CHECK_ANALYSIS_SQLITE_TRIGGERS,
    DEPOT_SNAPSHOT_SQLITE_TRIGGERS,
    Base,
)


class StrategySnapshot(Base):
    __tablename__ = "strategy_snapshots"
    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    snapshot_date = Column(String, nullable=False)
    advisory_assets_rappen = Column(BigInteger, nullable=False)
    risk_profile_score = Column(Integer, nullable=False)
    risk_profile_label = Column(String, nullable=False)
    soll_equities_bps = Column(Integer, nullable=False)
    soll_bonds_bps = Column(Integer, nullable=False)
    soll_real_estate_bps = Column(Integer, nullable=False)
    soll_liquidity_bps = Column(Integer, nullable=False)
    soll_alternatives_bps = Column(Integer, nullable=False)
    band_equities_lo_bps = Column(Integer)
    band_equities_hi_bps = Column(Integer)
    band_bonds_lo_bps = Column(Integer)
    band_bonds_hi_bps = Column(Integer)
    band_real_estate_lo_bps = Column(Integer)
    band_real_estate_hi_bps = Column(Integer)
    band_liquidity_lo_bps = Column(Integer)
    band_liquidity_hi_bps = Column(Integer)
    band_alternatives_lo_bps = Column(Integer)
    band_alternatives_hi_bps = Column(Integer)
    advisor_note = Column(String)
    goals_summary_json = Column(String)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)
    mandate = relationship("Mandate")


class AssetClassAnnualReturn(Base):
    __tablename__ = "asset_class_annual_returns"
    id = Column(String, primary_key=True)
    year = Column(Integer, nullable=False)
    asset_class = Column(String, nullable=False)
    return_bps = Column(Integer, nullable=False)
    source = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    # Sprint 2026-06-09 (Phase 1 Sub-Asset): Sub-Anlageklassen-Schluessel
    # gemaess symbol_catalog.SUB_ASSET_CATALOG. NULL = Top-Level-Aggregat
    # (Backwards-Compat zu pre-Sprint-Daten).
    sub_asset_class = Column(String, nullable=True)


class AssetClassPriceHistory(Base):
    """Sprint U-P19 (2026-05-22): Tägliche EOD-Index-Serie je Asset-Klasse.

    Persistierte Datenquelle für den Daily-Strategie-Backtest. Wird per
    Admin-Backfill aus dem Marktdaten-Aggregator (Proxy-ETFs) gefüllt; der
    Backtest liest NUR aus dieser Tabelle (offline-fähig, kein Live-Netz).

    `close_rappen` ist der adjusted_close (Total Return inkl. Dividenden, wenn
    vorhanden) der Proxy-Serie in deren Notierungswährung (`currency`) × 100.
    `currency` (U-P19b) trägt die native Währung der Bar; der Backtest rechnet
    die Tagesrenditen damit währungskorrekt nach CHF um (siehe
    AssetClassFxHistory).
    """
    __tablename__ = "asset_class_price_history"
    __table_args__ = (
        UniqueConstraint("asset_class", "price_date", "source",
                         name="uq_acph_class_date_source"),
        Index("ix_acph_class_date", "asset_class", "price_date"),
    )
    id = Column(String, primary_key=True)
    asset_class = Column(String, nullable=False)
    price_date = Column(String, nullable=False)  # ISO-Date "YYYY-MM-DD"
    close_rappen = Column(BigInteger, nullable=False)
    currency = Column(String)  # U-P19b: native Notierungswährung (ISO-3), z.B. "USD"
    source = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    # Sprint 2026-06-09 (Phase 1 Sub-Asset): Sub-Anlageklassen-Schluessel
    # gemaess symbol_catalog.SUB_ASSET_CATALOG. NULL = Top-Level-Aggregat
    # (Backwards-Compat zu pre-Sprint-Daten).
    sub_asset_class = Column(String, nullable=True)


class AssetClassFxHistory(Base):
    """Sprint U-P19b (2026-05-23): Tägliche FX-Reihe Fremdwährung → CHF.

    Datenquelle für den währungskorrekten Daily-Backtest. Proxy-ETFs notieren in
    USD; ein CHF-Investor trägt das USD/CHF-Risiko. `rate_to_chf_x10000` ist
    `1 <currency> = rate CHF` × 10000 (z.B. USD/CHF 0.91 → 9100). Per
    Admin-Backfill aus dem Aggregator (FX-Symbol-Konvention, z.B. "CHF=X").
    """
    __tablename__ = "asset_class_fx_history"
    __table_args__ = (
        UniqueConstraint("currency", "price_date", "source",
                         name="uq_acfx_ccy_date_source"),
        Index("ix_acfx_ccy_date", "currency", "price_date"),
    )
    id = Column(String, primary_key=True)
    currency = Column(String, nullable=False)  # Fremdwährung (ISO-3)
    price_date = Column(String, nullable=False)
    rate_to_chf_x10000 = Column(Integer, nullable=False)
    source = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class DepotSnapshot(Base):
    """DepotSnapshotV1 -- unveraenderlicher, hash-gebundener IST-Bestand eines
    Mandats (DEPOT-E2E-SNAPSHOT-001, DEPOT-E2E-STRESS-001 Option 2).

    ``snapshot_json`` ist der kanonische Snapshot (services/depot_snapshot.py),
    ``id`` = ``snapshot_id`` (aus dem Hash abgeleitet, gleicher Inhalt = gleiche
    Zeile). Append-only (Trigger); kein FK auf mandates/clients (Purge-fest).
    ``tenant_id`` direkt (RLS-Plan, PG-002), aus dem Mandat abgeleitet und per
    INSERT-Guard geprueft (core/mandate_evidence_tenant_boundary.py);
    nicht Teil des Snapshot-Hashes.
    """

    __tablename__ = "depot_snapshots"
    __table_args__ = (
        Index("ix_depot_snapshots_mandate", "mandate_id", "as_of_date"),
        Index("ix_depot_snapshots_tenant_id", "tenant_id"),
    )

    id = Column(String, primary_key=True)
    schema_version = Column(String, nullable=False, default="DepotSnapshotV1")
    tenant_id = Column(String)
    mandate_id = Column(String, nullable=False)
    client_id = Column(String, nullable=False)
    as_of_date = Column(String, nullable=False)
    currency = Column(String, nullable=False)
    source = Column(String, nullable=False)
    snapshot_json = Column(String, nullable=False)
    snapshot_hash = Column(String, nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)


for _trigger_ddl in DEPOT_SNAPSHOT_SQLITE_TRIGGERS:
    event.listen(
        DepotSnapshot.__table__,
        "after_create",
        DDL(_trigger_ddl).execute_if(dialect="sqlite"),
    )


class DepotCheckAnalysisSnapshot(Base):
    """DepotCheckAnalysisSnapshot -- Depot-Check-Ergebnis, gebunden an genau
    einen DepotSnapshotV1 (DEPOT-E2E-SNAPSHOT-001).

    ``analysis_json`` ist der kanonische Inhalt (services/depot_check_snapshot.py),
    ``id`` = ``analysis_snapshot_id`` (aus dem Hash abgeleitet). JSON-Endpunkt
    und PDF lesen dieselbe Zeile. Append-only (Trigger); kein FK auf
    mandates/clients/depot_snapshots (Purge-fest, Bindung per Hash).
    ``tenant_id`` direkt (RLS-Plan, PG-002), aus dem Mandat abgeleitet und per
    INSERT-Guard geprueft (core/mandate_evidence_tenant_boundary.py);
    nicht Teil der Hashes.
    """

    __tablename__ = "depot_check_analysis_snapshots"
    __table_args__ = (
        Index("ix_depot_check_analysis_snapshots_mandate", "mandate_id", "created_at"),
        Index("ix_depot_check_analysis_snapshots_tenant_id", "tenant_id"),
    )

    id = Column(String, primary_key=True)
    schema_version = Column(String, nullable=False, default="DepotCheckAnalysisV1")
    tenant_id = Column(String)
    mandate_id = Column(String, nullable=False)
    client_id = Column(String, nullable=False)
    depot_snapshot_id = Column(String, nullable=False)
    depot_snapshot_hash = Column(String, nullable=False)
    as_of_date = Column(String, nullable=False)
    analysis_json = Column(String, nullable=False)
    analysis_hash = Column(String, nullable=False)
    result_hash = Column(String, nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)


for _trigger_ddl in DEPOT_CHECK_ANALYSIS_SQLITE_TRIGGERS:
    event.listen(
        DepotCheckAnalysisSnapshot.__table__,
        "after_create",
        DDL(_trigger_ddl).execute_if(dialect="sqlite"),
    )


# ── CCX-P1 Snapshot und Hash (Vertrag 2026-11-13 §4) ─────────────────────────
#
# Der Beratungsentscheid wird genau einmal als unveraenderlicher Envelope
# ``ares/advisory-envelope/1`` versiegelt (services/advisory_decision_envelope.py,
# Serialisierung core/advisory_envelope_codec.py). DDL-Quelle fuer SQLite:
# database.py (ADVISORY_ENVELOPE_SQLITE_*), textgleich ares_schema.sql;
# PostgreSQL: Alembic (CCX-P1-Revision). Alle drei Tabellen tragen tenant_id
# NOT NULL (RLS-Plan, services/postgres_rls.py) und haben keinen FK auf
# mandates (Purge-fest); der Mandant wird per INSERT-Guard aus dem Mandat
# abgeleitet.

ADVISORY_ENVELOPE_SCHEMA_VERSION = "ares/advisory-envelope/1"
ADVISORY_ENVELOPE_STATUSES = ("DRAFT", "SEALED", "SUPERSEDED")


class AdvisoryDecisionEnvelope(Base):
    """Versiegelter Beratungsentscheid (DRAFT -> SEALED -> SUPERSEDED).

    ``canonical_payload_json`` sind die kanonischen Bytes (UTF-8, NFC,
    Schluessel in Schema-Reihenfolge, nur Integer-Rohwerte, inkl.
    ``rounding_policy_version``), ``envelope_hash`` = SHA-256 ueber die
    Root-Domaene ``Ares<NUL>ares/advisory-envelope/1<NUL>`` + kanonische
    Bytes. SEALED ist append-only (Trigger SQLite + PostgreSQL); einzige
    erlaubte Aenderung ist SEALED -> SUPERSEDED bei unveraendertem Inhalt.
    """

    __tablename__ = "advisory_decision_envelopes"
    __table_args__ = (
        CheckConstraint(
            "schema_version = 'ares/advisory-envelope/1'",
            name="ck_advisory_decision_envelopes_schema_version",
        ),
        CheckConstraint(
            "status IN ('DRAFT','SEALED','SUPERSEDED')",
            name="ck_advisory_decision_envelopes_status",
        ),
        CheckConstraint(
            "envelope_hash IS NULL OR length(envelope_hash) = 64",
            name="ck_advisory_decision_envelopes_hash_length",
        ),
        CheckConstraint("optimistic_version >= 1", name="ck_advisory_decision_envelopes_version"),
        CheckConstraint(
            "status = 'DRAFT' OR (canonical_payload_json IS NOT NULL AND envelope_hash IS NOT NULL "
            "AND sealed_at IS NOT NULL AND sealed_by IS NOT NULL)",
            name="ck_advisory_decision_envelopes_sealed_complete",
        ),
        UniqueConstraint("tenant_id", "envelope_hash", name="uq_advisory_decision_envelopes_tenant_hash"),
        UniqueConstraint("tenant_id", "id", name="uq_advisory_decision_envelopes_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "predecessor_id"],
            ["advisory_decision_envelopes.tenant_id", "advisory_decision_envelopes.id"],
            name="fk_advisory_decision_envelopes_predecessor",
        ),
        Index("ix_advisory_decision_envelopes_tenant_id", "tenant_id"),
        Index("ix_advisory_decision_envelopes_mandate", "tenant_id", "mandate_id", "status"),
        Index(
            "ux_advisory_decision_envelopes_one_sealed", "tenant_id", "mandate_id", unique=True,
            sqlite_where=text("status = 'SEALED'"), postgresql_where=text("status = 'SEALED'"),
        ),
        Index(
            "ux_advisory_decision_envelopes_one_successor", "predecessor_id", unique=True,
            sqlite_where=text("predecessor_id IS NOT NULL"),
            postgresql_where=text("predecessor_id IS NOT NULL"),
        ),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    mandate_id = Column(String, nullable=False)
    schema_version = Column(String, nullable=False, default=ADVISORY_ENVELOPE_SCHEMA_VERSION)
    status = Column(String, nullable=False, default="DRAFT")
    locale = Column(String, nullable=False)
    base_currency = Column(String, nullable=False)
    canonical_payload_json = Column(String)
    envelope_hash = Column(String)
    predecessor_id = Column(String)
    created_at = Column(String, nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    sealed_at = Column(String)
    sealed_by = Column(String, ForeignKey("users.id"))
    optimistic_version = Column(Integer, nullable=False, default=1)


class AdvisoryEnvelopeBinding(Base):
    """Kind-Bindung eines Envelopes (Merkle-Blatt): Objekt, Version und
    domaenenseparierter Kind-Hash. Nur solange der Envelope DRAFT ist
    einfuegbar, danach unveraenderlich; Mandant ueber den zusammengesetzten
    Fremdschluessel (tenant_id, envelope_id) an den Envelope gebunden."""

    __tablename__ = "advisory_envelope_bindings"
    __table_args__ = (
        CheckConstraint("length(child_hash) = 64", name="ck_advisory_envelope_bindings_hash_length"),
        CheckConstraint("ordinal >= 0", name="ck_advisory_envelope_bindings_ordinal"),
        UniqueConstraint(
            "envelope_id", "binding_kind", "ordinal", name="uq_advisory_envelope_bindings_kind_ordinal",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "envelope_id"],
            ["advisory_decision_envelopes.tenant_id", "advisory_decision_envelopes.id"],
            name="fk_advisory_envelope_bindings_envelope",
        ),
        Index("ix_advisory_envelope_bindings_tenant_id", "tenant_id"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    envelope_id = Column(String, nullable=False)
    binding_kind = Column(String, nullable=False)
    object_type = Column(String, nullable=False)
    object_id = Column(String, nullable=False)
    object_version = Column(Integer)
    child_hash = Column(String, nullable=False)
    ordinal = Column(Integer, nullable=False)
    created_at = Column(String, nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)


class AdvisoryEffectiveInputManifest(Base):
    """Effective-Input-Manifest: je wirkender Inputgruppe ein Kind-Hash plus
    Engine-Version, Zufallsstrom und ``rounding_policy_version``;
    ``manifest_hash`` ist der Kind-Hash ``effective-input-manifest`` darueber.
    Append-only."""

    __tablename__ = "advisory_effective_input_manifests"
    __table_args__ = (
        CheckConstraint("length(manifest_hash) = 64", name="ck_advisory_effective_input_manifests_hash"),
        UniqueConstraint("tenant_id", "id", name="uq_advisory_effective_input_manifests_tenant_id"),
        Index("ix_advisory_effective_input_manifests_tenant_id", "tenant_id"),
        Index("ix_advisory_effective_input_manifests_mandate", "tenant_id", "mandate_id"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    mandate_id = Column(String, nullable=False)
    client_hash = Column(String, nullable=False)
    mandate_hash = Column(String, nullable=False)
    goals_hash = Column(String, nullable=False)
    cashflows_hash = Column(String, nullable=False)
    risk_hash = Column(String, nullable=False)
    preference_hash = Column(String, nullable=False)
    cma_hash = Column(String, nullable=False)
    policy_hash = Column(String, nullable=False)
    constraints_hash = Column(String, nullable=False)
    holdings_hash = Column(String, nullable=False)
    engine_version = Column(String, nullable=False)
    random_stream_id = Column(String, nullable=False)
    rounding_policy_version = Column(String, nullable=False)
    manifest_hash = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)


ADVISORY_ENVELOPE_TABLES = (
    AdvisoryDecisionEnvelope.__tablename__,
    AdvisoryEnvelopeBinding.__tablename__,
    AdvisoryEffectiveInputManifest.__tablename__,
)


def _create_advisory_envelope_sqlite_triggers(_metadata, connection, **_kw) -> None:
    """Metadata-Hook (SQLite): Trigger erst, wenn alle drei Tabellen und
    ``mandates.tenant_id`` existieren (verweisen gegenseitig/auf mandates)."""
    if connection.dialect.name != "sqlite":
        return
    tables = {row[0] for row in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    if not set(ADVISORY_ENVELOPE_TABLES) <= tables:
        return
    for ddl in ADVISORY_ENVELOPE_SQLITE_TRIGGERS:
        connection.exec_driver_sql(ddl)
    if "mandates" in tables and "tenant_id" in {
        row[1] for row in connection.exec_driver_sql("PRAGMA table_info(mandates)")
    }:
        for ddl in ADVISORY_ENVELOPE_SQLITE_TENANT_GUARDS:
            connection.exec_driver_sql(ddl)


event.listen(Base.metadata, "after_create", _create_advisory_envelope_sqlite_triggers)
