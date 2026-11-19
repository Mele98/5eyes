import contextvars
import datetime as _dt
import hashlib
import json
import weakref
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import (
    DDL, BigInteger, CheckConstraint, Column, ForeignKey, ForeignKeyConstraint, Index, Integer,
    String, UniqueConstraint, bindparam, event, select, text,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, relationship
from sqlalchemy.sql.dml import UpdateBase
from database import (
    ADVISORY_TENANT_BOUNDARY_COLUMNS,
    ALLOCATION_PUBLICATION_SQLITE_TENANT_GUARDS,
    ALLOCATION_PUBLICATION_SQLITE_TRIGGERS,
    ADVISORY_ENVELOPE_SQLITE_TENANT_GUARDS,
    ADVISORY_ENVELOPE_SQLITE_TRIGGERS,
    ADVISORY_FRESHNESS_SQLITE_TRIGGERS,
    DEPOT_CHECK_ANALYSIS_SQLITE_TRIGGERS,
    DEPOT_SNAPSHOT_SQLITE_TRIGGERS,
    HOLDINGS_VALUATION_SQLITE_TENANT_GUARDS,
    HOLDINGS_VALUATION_SQLITE_TRIGGERS,
    Base,
    new_uuid,
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
    # CCX-P2 (Vertrag 2026-11-13 §5): Frische. Einfuegen nur als UNKNOWN,
    # FRESH nur beim Siegel mit Abhaengigkeitskanten, danach nur noch STALE
    # (Trigger SQLite + PostgreSQL); jede Aenderung erhoeht optimistic_version.
    freshness_status = Column(
        String,
        CheckConstraint(
            "freshness_status IN ('FRESH','STALE','UNKNOWN')",
            name="ck_advisory_decision_envelopes_freshness",
        ),
        nullable=False,
        default="UNKNOWN",
        server_default=text("'UNKNOWN'"),
    )
    stale_at = Column(String)
    stale_reason_code = Column(String)


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


class AdvisoryDependencyEdge(Base):
    """CCX-P2: Abhaengigkeitskante eines Envelopes -- welches Objekt in welcher
    Version mit welchem ``dependency_hash`` beim Siegel wirkte. Nur solange der
    Envelope DRAFT ist einfuegbar, danach unveraenderlich; Mandant ueber den
    zusammengesetzten Fremdschluessel (tenant_id, envelope_id)."""

    __tablename__ = "advisory_dependency_edges"
    __table_args__ = (
        CheckConstraint("length(dependency_hash) = 64", name="ck_advisory_dependency_edges_hash_length"),
        UniqueConstraint(
            "envelope_id", "dependency_kind", "dependency_object_id",
            name="uq_advisory_dependency_edges_kind_object",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "envelope_id"],
            ["advisory_decision_envelopes.tenant_id", "advisory_decision_envelopes.id"],
            name="fk_advisory_dependency_edges_envelope",
        ),
        Index("ix_advisory_dependency_edges_tenant_id", "tenant_id"),
        Index("ix_advisory_dependency_edges_object", "dependency_kind", "dependency_object_id"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    envelope_id = Column(String, nullable=False)
    dependency_kind = Column(String, nullable=False)
    dependency_object_id = Column(String, nullable=False)
    dependency_version = Column(Integer)
    dependency_hash = Column(String, nullable=False)
    observed_at = Column(String, nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)


class AdvisoryInvalidationEvent(Base):
    """CCX-P2: append-only Invalidationsereignis. Je Envelope eine lueckenlose
    ``invalidation_sequence`` (1, 2, 3 ...; Unique + Trigger), geschrieben im
    selben Commit wie die Mutation; der Envelope ist danach STALE (Reason-Code
    ``CCX_INPUT_STALE``). ``old_hash``/``new_hash`` sind die Projektions-Hashes
    des mutierten Quellobjekts (NULL: neu angelegt bzw. geloescht/Massen-
    aenderung); ``created_by`` ist der Benutzer der Mutation oder ``system``."""

    __tablename__ = "advisory_invalidation_events"
    __table_args__ = (
        CheckConstraint("old_hash IS NULL OR length(old_hash) = 64", name="ck_advisory_invalidation_events_old_hash"),
        CheckConstraint("new_hash IS NULL OR length(new_hash) = 64", name="ck_advisory_invalidation_events_new_hash"),
        CheckConstraint("reason_code = 'CCX_INPUT_STALE'", name="ck_advisory_invalidation_events_reason"),
        CheckConstraint("invalidation_sequence >= 1", name="ck_advisory_invalidation_events_sequence"),
        CheckConstraint("length(created_by) > 0", name="ck_advisory_invalidation_events_actor"),
        UniqueConstraint("envelope_id", "invalidation_sequence", name="uq_advisory_invalidation_events_sequence"),
        ForeignKeyConstraint(
            ["tenant_id", "envelope_id"],
            ["advisory_decision_envelopes.tenant_id", "advisory_decision_envelopes.id"],
            name="fk_advisory_invalidation_events_envelope",
        ),
        Index("ix_advisory_invalidation_events_tenant_id", "tenant_id"),
        Index("ix_advisory_invalidation_events_mandate", "tenant_id", "mandate_id"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    mandate_id = Column(String, nullable=False)
    envelope_id = Column(String, nullable=False)
    source_kind = Column(String, nullable=False)
    source_object_id = Column(String, nullable=False)
    old_hash = Column(String)
    new_hash = Column(String)
    reason_code = Column(String, nullable=False)
    invalidation_sequence = Column(Integer, nullable=False)
    created_at = Column(String, nullable=False)
    created_by = Column(String, nullable=False)


ADVISORY_ENVELOPE_TABLES = (
    AdvisoryDecisionEnvelope.__tablename__,
    AdvisoryEnvelopeBinding.__tablename__,
    AdvisoryEffectiveInputManifest.__tablename__,
)
ADVISORY_FRESHNESS_TABLES = (
    AdvisoryDependencyEdge.__tablename__,
    AdvisoryInvalidationEvent.__tablename__,
)


def _create_advisory_envelope_sqlite_triggers(_metadata, connection, **_kw) -> None:
    """Metadata-Hook (SQLite): Trigger erst, wenn alle drei Tabellen und
    ``mandates.tenant_id`` existieren (verweisen gegenseitig/auf mandates)."""
    if connection.dialect.name != "sqlite":
        return
    tables = {row[0] for row in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    if not set(ADVISORY_ENVELOPE_TABLES + ADVISORY_FRESHNESS_TABLES) <= tables:
        return
    for ddl in ADVISORY_ENVELOPE_SQLITE_TRIGGERS + ADVISORY_FRESHNESS_SQLITE_TRIGGERS:
        connection.exec_driver_sql(ddl)
    if "mandates" in tables and "tenant_id" in {
        row[1] for row in connection.exec_driver_sql("PRAGMA table_info(mandates)")
    }:
        for ddl in ADVISORY_ENVELOPE_SQLITE_TENANT_GUARDS:
            connection.exec_driver_sql(ddl)


event.listen(Base.metadata, "after_create", _create_advisory_envelope_sqlite_triggers)


# ── CCX-P2: zentraler Mutation Hook (Vertrag 2026-11-13 §5) ──────────────────
#
# Jede Mutation einer Abhaengigkeit eines Beratungsentscheids (Ziele,
# Cashflows, Vermoegen/Positionen, Risikoprofil, ESG-Praeferenz, CMA/Policy,
# Benchmark, Restriktionen, Mandats-/Kundendaten) schreibt IM SELBEN
# DB-Commit ein Invalidationsereignis und setzt die betroffenen Envelopes
# (SEALED, auch einen gerade entstehenden DRAFT) auf STALE. Der Hook haengt
# zentral an der ORM-Session (``after_flush`` fuer Einzelobjekte,
# ``do_orm_execute`` fuer Massen-UPDATE/-DELETE) -- keine Route muss daran
# denken, ihn aufzurufen. Rohes SQL und ORM-Massen-INSERT auf diese Tabellen
# sind per Vollstaendigkeits-Waechter (tests/test_ccx_p2_hook_completeness.py)
# ausserhalb einer begruendeten Allowlist verboten.
#
# Nebenlaeufigkeit: unter PostgreSQL sperrt der Hook die betroffenen
# Mandatszeilen (FOR UPDATE, sortiert) -- dieselbe Sperre wie die
# Finalisierung. Eine Mutation waehrend der Versiegelung wartet also bis zum
# Siegel-Commit und markiert danach den neuen Envelope STALE; umgekehrt
# liest die Versiegelung erst nach dem Mutations-Commit. Die
# ``invalidation_sequence`` ist damit je Envelope lueckenlos (Trigger +
# Unique als zweite Linie). Keine Fachwirkung: der Hook liest und schreibt
# ausschliesslich Envelope-Frische und Ereignisse.

INVALIDATION_REASON_CODE = "CCX_INPUT_STALE"
SYSTEM_ACTOR = "system"
ACTOR_INFO_KEY = "ares_actor_user_id"
FRESHNESS_FRESH = "FRESH"
FRESHNESS_STALE = "STALE"
FRESHNESS_UNKNOWN = "UNKNOWN"
_PENDING_AUDIT_KEY = "ares_ccx_p2_pending_invalidations"
_TABLES_PRESENT_KEY = "ares_ccx_p2_tables_present"
_SIGNED_COLUMN_KEY = "ares_ccx_p2_signed_sql_v2"
_INVALIDATION_DOMAIN = "ares/advisory-invalidation/1"
_UNLOADED = "<unloaded>"

SCOPE_MANDATE = "mandate"
SCOPE_CLIENT = "client"
SCOPE_EDGE = "edge"
SCOPE_ASSESSMENT = "assessment"


@dataclass(frozen=True)
class DependencySource:
    """Abhaengigkeitsquelle: Tabelle -> ``kind`` (= ``source_kind`` und
    ``dependency_kind``), Reichweite (Mandat, Kunde, Kante, Risikoprofil) und
    das Attribut mit dem Reichweitenwert. ``current_flag``: das Einfuegen einer
    sofort wirksamen globalen Version (z. B. neue aktuelle CMA) trifft alle
    versiegelten Envelopes mit einer Kante dieser Art (konservativ)."""

    kind: str
    scope: str
    key: str
    current_flag: str | None = None
    # KN3-B / N-917R2-01: ``tenant_id`` ist Mandantengrenze, kein
    # Beratungsinhalt (Begruendung bei ADVISORY_TENANT_BOUNDARY_COLUMNS in
    # database.py). Der Mandant eines Ereignisses wird separat gelesen
    # (``_Change.tenant_id``), er bleibt fuer die Reichweite massgeblich.
    volatile: frozenset[str] = frozenset({"updated_at"}) | ADVISORY_TENANT_BOUNDARY_COLUMNS


DEPENDENCY_SOURCES: dict[str, DependencySource] = {
    # Mandats-/Kundendaten
    "clients": DependencySource("client", SCOPE_CLIENT, "id"),
    "mandates": DependencySource("mandate", SCOPE_MANDATE, "id"),
    "planning_assumptions": DependencySource("planning", SCOPE_MANDATE, "mandate_id"),
    # Ziele
    "goals": DependencySource("goals", SCOPE_MANDATE, "mandate_id"),
    "goal_revision_decisions": DependencySource("goal_revisions", SCOPE_MANDATE, "mandate_id"),
    "goal_lifecycle_transitions": DependencySource("goal_transitions", SCOPE_MANDATE, "mandate_id"),
    # Cashflows und Vermoegen/Positionen
    "cashflows": DependencySource("cashflows", SCOPE_CLIENT, "client_id"),
    "wealth_inflows": DependencySource("wealth_inflows", SCOPE_CLIENT, "client_id"),
    "wealth_positions": DependencySource("positions", SCOPE_CLIENT, "client_id"),
    "recommendation_holdings": DependencySource("run_holdings", SCOPE_EDGE, "run_id"),
    # Risikoprofil (inkl. Antworten, Override, Freigabe, Plausibilisierung)
    "risk_assessments": DependencySource("risk", SCOPE_MANDATE, "mandate_id"),
    "risk_assessment_answers": DependencySource("risk", SCOPE_ASSESSMENT, "assessment_id"),
    "risk_override_decisions": DependencySource("risk_overrides", SCOPE_MANDATE, "mandate_id"),
    "risk_profile_signoffs": DependencySource("risk_signoffs", SCOPE_MANDATE, "mandate_id"),
    "risk_capacity_plausibility_evaluations": DependencySource("risk_plausibility", SCOPE_MANDATE, "mandate_id"),
    "financial_coverage_attestations": DependencySource("coverage_attestations", SCOPE_MANDATE, "mandate_id"),
    # ESG-/Nachhaltigkeitspraeferenz
    "investment_preference_decisions": DependencySource("preference", SCOPE_MANDATE, "mandate_id"),
    # Restriktionen/Baender/Praeferenz-Snapshot der Soll-Allokation
    "target_allocations": DependencySource("constraints", SCOPE_MANDATE, "mandate_id"),
    # CMA-/Policy-Version und Benchmark (Hausmatrix der Policy)
    "capital_market_assumptions": DependencySource("cma", SCOPE_EDGE, "id", current_flag="is_current"),
    "optimizer_policies": DependencySource("optimizer_policy", SCOPE_EDGE, "id", current_flag="is_current"),
    "building_blocks": DependencySource("building_blocks", SCOPE_EDGE, "policy_id"),
    "cma_policies": DependencySource("cma_policy", SCOPE_EDGE, "id"),
    "cma_policy_components": DependencySource("cma_policy_components", SCOPE_EDGE, "policy_row_id"),
    "cma_policy_approvals": DependencySource("cma_policy_approvals", SCOPE_EDGE, "policy_row_id"),
    "house_matrix": DependencySource("benchmark", SCOPE_EDGE, "policy_id"),
}

# Kanten, die die Versiegelung schreibt (services/effective_input_manifest.py
# ::collect_dependency_parts); jede Hook-Art muss hier vorkommen.
DEPENDENCY_KINDS = (
    "client", "mandate", "goals", "cashflows", "wealth_inflows", "positions", "run_holdings", "risk",
    "preference", "constraints", "cma", "optimizer_policy", "cma_policy", "benchmark",
    # N-908-04: Kanten auch fuer die Tabellen, die bisher nur ueber die Reichweite liefen.
    "goal_revisions", "goal_transitions", "planning", "risk_overrides", "risk_signoffs",
    "risk_plausibility", "coverage_attestations", "building_blocks", "cma_policy_components",
    "cma_policy_approvals",
)

_AUDIT_SINKS: list = []
# Laufzeitschutz (N-908-02): Core-DML auf Abhaengigkeitstabellen ist nur aus
# einem Session-Flush oder dem Massen-Hook heraus erlaubt.
_HOOK_SCOPE: contextvars.ContextVar[bool] = contextvars.ContextVar("ares_ccx_p2_hook_scope", default=False)
_FLUSH_DEPTH: contextvars.ContextVar[int] = contextvars.ContextVar("ares_ccx_p2_flush_depth", default=0)
# H12 N-908-07: Sessions, die in diesem Kontext einen Flush begonnen haben. Der
# Laufzeitschutz fragt nicht den Zaehler, sondern ob eine davon JETZT flusht
# (``Session._flushing``): ein Flush ohne Arbeit (``flush(objects=...)``) laesst
# den Zaehler bis zum Transaktionsende stehen, ``_flushing`` ist danach sofort
# wieder falsch -- Core-DML in derselben Transaktion bleibt damit geschuetzt.
_FLUSHING_SESSIONS: contextvars.ContextVar["weakref.WeakSet | None"] = contextvars.ContextVar(
    "ares_ccx_p2_flushing_sessions", default=None,
)
# Referenzdaten-Arten: Hausmeinung (CMA, Policy, CMA-Policy, Benchmark).
REFERENCE_KINDS = frozenset({
    "cma", "optimizer_policy", "cma_policy", "benchmark", "building_blocks", "cma_policy_components",
    "cma_policy_approvals",
})
# Entscheid (Owner-Vertretung, N-908, Anlagephilosophie Strategietreue): ein vom
# Kunden UNTERZEICHNETER Entscheid wird durch eine neue Hausmeinung (CMA/Policy/
# Benchmark) nicht veraendert und nicht STALE -- kein Rebalancing, keine
# Ueberwachung. Unterzeichnet (N-908-05) = GENAU DIESER Entscheid wurde vom
# Kunden unterzeichnet: ein nicht geloeschtes Dokument an seiner Soll-Allokation,
# das NACH seinem Siegel erzeugt UND nach seinem Siegel vom Kunden signiert wurde
# -- per E-Signing (signed_by_client + Signaturzeit) oder per Vor-Ort-Signatur
# (Evidenz mit signer_role = 'client'). Weil je Mandat hoechstens ein SEALED-
# Entscheid existiert und jede Neuversiegelung den Vorgaenger abloest, ordnet
# das Zeitfenster [sealed_at, ...) ein Dokument eindeutig dem Entscheid zu: ein
# neuer Lauf E2 auf derselben Allokation erbt die Unterschrift von E1 nicht
# (dessen Dokument entstand vor E2s Siegel). Vergleich auf Millisekunden.
# Aenderungen an Kundendaten (Ziele, Vermoegen, Risikoprofil ...) invalidieren
# weiterhin; STALE sperrt dort nur neue Kanalwirkungen (P5), nie Bestehendes.
_SIGNED_DOCUMENT_SQL = (
    "EXISTS (SELECT 1 FROM contract_documents cd JOIN advisory_envelope_bindings sb "
    "ON sb.envelope_id = e.id AND sb.binding_kind = 'target_allocation' "
    "WHERE cd.mandate_id = e.mandate_id AND cd.bound_target_allocation_id = sb.object_id "
    "AND cd.deleted_at IS NULL AND e.sealed_at IS NOT NULL "
    "AND substr(cd.created_at, 1, 23) >= substr(e.sealed_at, 1, 23) "
    "AND ((cd.signed_by_client = 1 "
    "AND substr(COALESCE(cd.signature_client_signed_at, cd.signed_at), 1, 23) >= substr(e.sealed_at, 1, 23))"
    "@@ONSITE@@))"
)
_ONSITE_SIGNED_SQL = (
    " OR EXISTS (SELECT 1 FROM onsite_signature_evidence ev WHERE ev.document_id = cd.id "
    "AND ev.mandate_id = cd.mandate_id AND ev.signer_role = 'client' "
    "AND substr(ev.signed_at, 1, 23) >= substr(e.sealed_at, 1, 23))"
)
SIGNED_DECISION_SQL = _SIGNED_DOCUMENT_SQL.replace("@@ONSITE@@", _ONSITE_SIGNED_SQL)


def register_invalidation_audit_sink(sink) -> None:
    """Service-Schicht registriert den Audit-Schreiber (``ccx.envelope.
    invalidated``); er laeuft vor dem Commit derselben Transaktion."""
    if sink not in _AUDIT_SINKS:
        _AUDIT_SINKS.append(sink)


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _jsonable(value):
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return "f:" + repr(value)
    if isinstance(value, Decimal):
        return "d:" + str(value)
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "b:" + bytes(value).hex()
    return "r:" + repr(value)


def projection_hash(table: str, values: dict) -> str:
    """Domaenenseparierter SHA-256 ueber die Zeilenprojektion eines
    Quellobjekts (alte bzw. neue Fassung), lowercase 64-hex."""
    payload = json.dumps(
        {key: _jsonable(values[key]) for key in sorted(values)},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    domain = b"Ares\x00" + f"{_INVALIDATION_DOMAIN}/{table}".encode("utf-8") + b"\x00"
    return hashlib.sha256(domain + payload).hexdigest()


@dataclass
class _Change:
    table: str
    source: DependencySource
    op: str
    object_id: str
    old_hash: str | None
    new_hash: str | None
    scope_values: tuple[str, ...]
    fallback_client: str | None = None
    global_current: bool = False
    tenant_id: str | None = None


# KN-B / E2E2-04: Spalten mit dieser Markierung (``Column(info=...)``, z. B.
# Beruf in models/clients.py) sind nicht Teil des Siegels -- gleiche Regel wie
# services/effective_input_manifest.py::_columns.
HASH_EXEMPT_INFO_KEY = "advisory_hash_exempt"


def _hash_exempt(column) -> bool:
    return bool((getattr(column, "info", None) or {}).get(HASH_EXEMPT_INFO_KEY))


def _row_projection(table, row, source: DependencySource) -> dict:
    """Siegel-Projektion einer Tabellenzeile (Massen-/Core-Pfad)."""
    columns = table.c
    return {key: value for key, value in row.items()
            if key not in source.volatile and not (key in columns and _hash_exempt(columns[key]))}


def _old_new(state, volatile: frozenset[str]) -> tuple[dict, dict]:
    old: dict = {}
    new: dict = {}
    for attr in state.mapper.column_attrs:
        key = attr.key
        if key in volatile or any(_hash_exempt(column) for column in attr.columns):
            continue
        current = state.dict.get(key, _UNLOADED)
        history = state.attrs[key].history
        new[key] = current
        if history.deleted:
            old[key] = history.deleted[0]
        elif history.added:
            old[key] = _UNLOADED  # vorheriger Wert nicht geladen -> konservativ "geaendert"
        else:
            old[key] = current
    return old, new


def _scope(values: dict, key: str) -> str | None:
    value = values.get(key)
    if value in (None, "", _UNLOADED):
        return None
    return str(value)


def _change(table: str, source: DependencySource, op: str, old: dict, new: dict,
            tenant: str | None = None) -> _Change | None:
    old_hash = None if op == "insert" else projection_hash(table, old)
    new_hash = None if op == "delete" else projection_hash(table, new)
    if op == "update" and old_hash == new_hash:
        return None  # Wiederholungs-/Leermutation: idempotent, kein Ereignis
    views = (new,) if op == "insert" else (old,) if op == "delete" else (old, new)
    scope_values = tuple(sorted({v for v in (_scope(view, source.key) for view in views) if v}))
    fallback = next((v for v in (_scope(view, "client_id") for view in views) if v), None)
    flag = source.current_flag
    return _Change(
        table=table, source=source, op=op,
        object_id=_scope(new, "id") or _scope(old, "id") or "-",
        old_hash=old_hash, new_hash=new_hash, scope_values=scope_values,
        fallback_client=fallback if source.scope == SCOPE_MANDATE and not scope_values else None,
        global_current=bool(op == "insert" and flag and new.get(flag) not in (None, 0, False, "", _UNLOADED)),
        tenant_id=_scope({"tenant_id": tenant}, "tenant_id") or _scope(new, "tenant_id") or _scope(old, "tenant_id"),
    )


def _state_tenant(state) -> str | None:
    """Mandant eines ORM-Objekts (neu, sonst alt) -- ausserhalb der Projektion,
    weil ``tenant_id`` volatil ist (KN3-B / N-917R2-01)."""
    if "tenant_id" not in state.mapper.column_attrs.keys():
        return None
    value = state.dict.get("tenant_id")
    if value in (None, ""):
        deleted = state.attrs["tenant_id"].history.deleted
        value = deleted[0] if deleted else None
    return str(value) if value not in (None, "") else None


def _row_tenant(row) -> str | None:
    value = row.get("tenant_id") if hasattr(row, "get") else None
    return str(value) if value not in (None, "") else None


def _session_changes(session: Session) -> list[_Change]:
    changes: list[_Change] = []
    for op, objects in (("insert", session.new), ("update", session.dirty), ("delete", session.deleted)):
        for obj in list(objects):
            try:
                state = sa_inspect(obj)
            except NoInspectionAvailable:
                continue
            table = getattr(getattr(state.mapper, "local_table", None), "name", None)
            source = DEPENDENCY_SOURCES.get(table)
            if source is None:
                continue
            if op == "update" and not session.is_modified(obj, include_collections=False):
                continue
            old, new = _old_new(state, source.volatile)
            change = _change(table, source, op, old, new, tenant=_state_tenant(state))
            if change is not None:
                changes.append(change)
    return changes


def freshness_tables_present(connection) -> bool:
    """True, wenn Envelope-, Kanten- und Ereignistabelle existieren (nur ein
    positives Ergebnis wird je Verbindung gemerkt). Ohne Envelope-Tabelle gibt
    es nichts zu invalidieren."""
    if connection.info.get(_TABLES_PRESENT_KEY):
        return True
    inspector = sa_inspect(connection)
    present = all(inspector.has_table(name) for name in (
        AdvisoryDecisionEnvelope.__tablename__, AdvisoryDependencyEdge.__tablename__,
        AdvisoryInvalidationEvent.__tablename__,
    ))
    if present:
        connection.info[_TABLES_PRESENT_KEY] = True
    return present


def _expanding(sql: str, *names: str):
    return text(sql).bindparams(*(bindparam(name, expanding=True) for name in names))


def mark_envelope_stale(
    connection,
    *,
    envelope_id: str,
    tenant_id: str,
    mandate_id: str,
    source_kind: str,
    source_object_id: str,
    old_hash: str | None,
    new_hash: str | None,
    actor: str | None,
) -> int | None:
    """Setzt den Envelope STALE (optimistic_version + 1, erster stale_at/
    Reason bleibt) und haengt das naechste Ereignis an. Rueckgabe: die neue
    ``invalidation_sequence`` (None, wenn der Envelope nicht mehr SEALED/DRAFT
    ist)."""
    now = _utc_now()
    updated = connection.execute(text(
        "UPDATE advisory_decision_envelopes SET optimistic_version = optimistic_version + 1, "
        "freshness_status = 'STALE', stale_at = COALESCE(stale_at, :now), "
        "stale_reason_code = COALESCE(stale_reason_code, :reason) "
        "WHERE id = :envelope_id AND status IN ('SEALED', 'DRAFT')"
    ), {"now": now, "reason": INVALIDATION_REASON_CODE, "envelope_id": envelope_id}).rowcount
    if updated != 1:
        return None
    return connection.execute(text(
        "INSERT INTO advisory_invalidation_events (id, tenant_id, mandate_id, envelope_id, source_kind, "
        "source_object_id, old_hash, new_hash, reason_code, invalidation_sequence, created_at, created_by) "
        # Typen explizit (PostgreSQL leitet Parameter in der SELECT-Liste nicht
        # ab; :envelope_id steht zudem im WHERE -> eigener Parametername).
        "SELECT CAST(:id AS VARCHAR), CAST(:tenant_id AS VARCHAR), CAST(:mandate_id AS VARCHAR), "
        "CAST(:envelope_id AS VARCHAR), CAST(:source_kind AS VARCHAR), CAST(:source_object_id AS VARCHAR), "
        "CAST(:old_hash AS VARCHAR), CAST(:new_hash AS VARCHAR), CAST(:reason AS VARCHAR), "
        "COALESCE(MAX(i.invalidation_sequence), 0) + 1, CAST(:now AS VARCHAR), CAST(:actor AS VARCHAR) "
        "FROM advisory_invalidation_events i WHERE i.envelope_id = :sequence_envelope_id "
        "RETURNING invalidation_sequence"
    ), {
        "id": new_uuid(), "tenant_id": tenant_id, "mandate_id": mandate_id, "envelope_id": envelope_id,
        "sequence_envelope_id": envelope_id,
        "source_kind": source_kind, "source_object_id": source_object_id, "old_hash": old_hash,
        "new_hash": new_hash, "reason": INVALIDATION_REASON_CODE, "now": now,
        "actor": str(actor or SYSTEM_ACTOR),
    }).scalar_one()


def _mandates_by(connection, sql: str, ids: list[str]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    if ids:
        for key, mandate_id in connection.execute(_expanding(sql, "ids"), {"ids": ids}):
            if key is not None and mandate_id is not None:
                result.setdefault(str(key), set()).add(str(mandate_id))
    return result


def _apply_invalidations(session: Session, changes: list[_Change]) -> None:
    _apply_invalidations_on(
        session.connection(), changes, actor=session.info.get(ACTOR_INFO_KEY) or SYSTEM_ACTOR,
        pending=session.info.setdefault(_PENDING_AUDIT_KEY, []),
    )


def signed_decision_sql(connection) -> str:
    """``SIGNED_DECISION_SQL`` passend zum Schema der Verbindung: ohne
    Bindungs-/Signaturspalten in ``contract_documents`` (aeltere Bootstrap-
    Schemata ohne Laufzeitpatch) gibt es keinen gebundenen, unterzeichneten
    Entscheid (``0 = 1``); ohne Vor-Ort-Evidenztabelle zaehlt nur E-Signing."""
    cached = connection.info.get(_SIGNED_COLUMN_KEY)
    if cached is None:
        inspector = sa_inspect(connection)
        columns = {c["name"] for c in inspector.get_columns("contract_documents")} \
            if inspector.has_table("contract_documents") else set()
        required = {"bound_target_allocation_id", "signed_by_client", "signature_client_signed_at", "signed_at",
                    "created_at", "deleted_at"}
        if not required <= columns:
            cached = "0 = 1"
        elif inspector.has_table("onsite_signature_evidence"):
            cached = SIGNED_DECISION_SQL
        else:
            cached = _SIGNED_DOCUMENT_SQL.replace("@@ONSITE@@", "")
        connection.info[_SIGNED_COLUMN_KEY] = cached
    return cached


def _apply_invalidations_on(connection, changes: list[_Change], *, actor: str, pending: list | None) -> None:
    if not freshness_tables_present(connection):
        return
    is_pg = connection.dialect.name.startswith("postgresql")
    mandate_changes = [c for c in changes if c.source.scope != SCOPE_EDGE]
    edge_changes = [c for c in changes if c.source.scope == SCOPE_EDGE]

    # 1. Reichweite -> Mandate (direkt, ueber den Kunden, ueber das Risikoprofil).
    client_ids = sorted({v for c in mandate_changes if c.source.scope == SCOPE_CLIENT for v in c.scope_values}
                        | {c.fallback_client for c in mandate_changes if c.fallback_client})
    assessment_ids = sorted({v for c in mandate_changes if c.source.scope == SCOPE_ASSESSMENT
                             for v in c.scope_values})
    by_client = _mandates_by(connection, "SELECT client_id, id FROM mandates WHERE client_id IN :ids", client_ids)
    by_assessment = _mandates_by(
        connection, "SELECT id, mandate_id FROM risk_assessments WHERE id IN :ids", assessment_ids,
    )
    mandates_of: list[set[str]] = []
    for change in mandate_changes:
        lookup = {SCOPE_CLIENT: by_client, SCOPE_ASSESSMENT: by_assessment}.get(change.source.scope)
        ids = set(change.scope_values) if lookup is None else {
            m for value in change.scope_values for m in lookup.get(value, ())
        }
        if change.fallback_client:
            ids |= by_client.get(change.fallback_client, set())
        mandates_of.append(ids)

    # 2. Kanten-Reichweite (CMA/Policy/Benchmark/Lauf-Bestaende).
    edge_rows: list = []
    if edge_changes:
        edge_rows = connection.execute(_expanding(
            "SELECT d.envelope_id, d.dependency_kind, d.dependency_object_id, e.mandate_id, e.tenant_id, "
            f"e.status, CASE WHEN {signed_decision_sql(connection)} THEN 1 ELSE 0 END AS signed "
            "FROM advisory_dependency_edges d JOIN advisory_decision_envelopes e "
            "ON e.id = d.envelope_id WHERE d.dependency_kind IN :kinds AND e.status IN ('SEALED', 'DRAFT')",
            "kinds"), {"kinds": sorted({c.source.kind for c in edge_changes})}).all()
    edge_hits: list[set[str]] = []
    for change in edge_changes:
        hits = set()
        for row in edge_rows:
            if row.dependency_kind != change.source.kind:
                continue
            if change.source.kind in REFERENCE_KINDS and int(row.signed or 0):
                continue  # unterzeichneter Entscheid: Hausmeinung wirkt nicht zurueck
            if str(row.dependency_object_id) in change.scope_values or (
                change.global_current and row.status == "SEALED"
                and (change.tenant_id is None or str(row.tenant_id) == change.tenant_id)
            ):
                hits.add(str(row.envelope_id))
        edge_hits.append(hits)
    hit_ids = set().union(*edge_hits) if edge_hits else set()
    all_mandates = sorted(
        set().union(*mandates_of)
        | {str(row.mandate_id) for row in edge_rows if str(row.envelope_id) in hit_ids}
    )
    if not all_mandates:
        return

    # 3. PostgreSQL: Mandatssperre (dieselbe Sperre wie die Finalisierung).
    if is_pg:
        connection.execute(_expanding(
            "SELECT id FROM mandates WHERE id IN :ids ORDER BY id FOR UPDATE", "ids"), {"ids": all_mandates})

    # 4. Envelopes nach der Sperre frisch lesen und invalidieren.
    envelopes = {
        str(row.id): row for row in connection.execute(_expanding(
            "SELECT id, tenant_id, mandate_id FROM advisory_decision_envelopes "
            "WHERE mandate_id IN :ids AND status IN ('SEALED', 'DRAFT') ORDER BY id", "ids"),
            {"ids": all_mandates})
    }
    if not envelopes:
        return
    targets: list[tuple[_Change, object]] = []
    for change, ids in zip(mandate_changes, mandates_of):
        targets.extend((change, row) for row in envelopes.values() if str(row.mandate_id) in ids)
    for change, hits in zip(edge_changes, edge_hits):
        targets.extend((change, envelopes[eid]) for eid in sorted(hits) if eid in envelopes)
    if not targets:
        return
    for change, row in targets:
        sequence = mark_envelope_stale(
            connection, envelope_id=str(row.id), tenant_id=str(row.tenant_id), mandate_id=str(row.mandate_id),
            source_kind=change.source.kind, source_object_id=change.object_id,
            old_hash=change.old_hash, new_hash=change.new_hash, actor=actor,
        )
        if sequence is not None and pending is not None:
            pending.append({
                "envelope_id": str(row.id), "tenant_id": str(row.tenant_id), "mandate_id": str(row.mandate_id),
                "source_kind": change.source.kind, "source_table": change.table,
                "source_object_id": change.object_id, "operation": change.op,
                "old_hash": change.old_hash, "new_hash": change.new_hash,
                "invalidation_sequence": int(sequence), "actor": str(actor),
            })


def _after_flush(session: Session, _flush_context) -> None:
    changes = _session_changes(session)
    if changes:
        _apply_invalidations(session, changes)


def _dml_table(orm_execute_state):
    """Zieltabelle eines DML-Statements -- ORM-Entitaet (``update(Model)``)
    ODER Core-Tabelle (``update(Model.__table__)``, N-908-02)."""
    mapper = orm_execute_state.bind_mapper
    table = getattr(mapper, "local_table", None)
    if table is None:
        candidate = getattr(orm_execute_state.statement, "table", None)
        table = candidate if getattr(candidate, "name", None) else None
    return table


def _bulk_orm_write(orm_execute_state):
    """Massen-UPDATE/-DELETE ueber die Session (``query(...).update()``,
    ``update(Model)``, ``update(Model.__table__)``): betroffene Zeilen VOR der
    Ausfuehrung lesen (PostgreSQL: ``FOR UPDATE``, damit eine parallele
    Versiegelung sichtbar committet ist) und invalidieren (gleiche Transaktion;
    neue Fassung unbekannt -> konservativ geaendert). Massen-INSERT auf
    Abhaengigkeitstabellen ist verboten. Das Statement selbst laeuft danach im
    Hook-Kontext (der Laufzeitschutz ``_guard_core_dml`` laesst es durch)."""
    if not (orm_execute_state.is_update or orm_execute_state.is_delete or orm_execute_state.is_insert):
        return None
    table = _dml_table(orm_execute_state)
    source = DEPENDENCY_SOURCES.get(getattr(table, "name", None))
    if source is None:
        return None
    if orm_execute_state.is_insert:
        raise RuntimeError(
            f"CCX-P2: Massen-INSERT auf {table.name} umgeht den Invalidation-Hook; "
            "Objekte einzeln ueber die Session anlegen."
        )
    session = orm_execute_state.session
    connection = session.connection()
    where = getattr(orm_execute_state.statement, "whereclause", None)
    query = select(table) if where is None else select(table).where(where)
    query = query.order_by(*table.primary_key.columns)  # feste Lesereihenfolge (H-868 D1)
    if connection.dialect.name.startswith("postgresql"):
        query = query.with_for_update()
    rows = connection.execute(query).mappings().all()
    changes = []
    for row in rows:
        old = _row_projection(table, row, source)
        change = _change(table.name, source, "delete", old, {}, tenant=_row_tenant(row))
        if orm_execute_state.is_update:
            change.op = "update"
        changes.append(change)
    if changes:
        _apply_invalidations(session, changes)
    token = _HOOK_SCOPE.set(True)
    try:
        return orm_execute_state.invoke_statement()
    finally:
        _HOOK_SCOPE.reset(token)


def _enter_flush(session, _flush_context, _instances) -> None:
    _FLUSH_DEPTH.set(_FLUSH_DEPTH.get() + 1)
    sessions = _FLUSHING_SESSIONS.get()
    if sessions is None:
        sessions = weakref.WeakSet()
        _FLUSHING_SESSIONS.set(sessions)
    sessions.add(session)


def _flush_in_progress() -> bool:
    """H12 N-908-07: flusht in diesem Kontext gerade eine Session (der
    after_flush-Hook deckt deren DML ab)? Zaehler UND ``_flushing`` muessen
    zustimmen; ein haengender Zaehler nach einem Flush ohne Arbeit schaltet
    den Schutz nicht mehr ab."""
    if _FLUSH_DEPTH.get() <= 0:
        return False
    sessions = _FLUSHING_SESSIONS.get()
    return bool(sessions) and any(getattr(s, "_flushing", False) for s in list(sessions))


def _leave_flush(_session, *_args) -> None:
    _FLUSH_DEPTH.set(max(0, _FLUSH_DEPTH.get() - 1))


def _reset_flush_depth(_session, *_args) -> None:
    """Transaktionsende: ein Flush ohne Arbeit (``flush_context.has_work``
    falsch, z. B. ``flush(objects=...)``) kehrt nach ``before_flush`` ohne
    ``after_flush_postexec`` zurueck -- der Zaehler darf den Laufzeitschutz
    nicht ueber die Transaktion hinaus abschalten."""
    _FLUSH_DEPTH.set(0)


def _insert_rows(clauseelement, multiparams, params) -> list[dict]:
    compiled = dict(clauseelement.compile().params or {})
    rows = []
    batches = multiparams if multiparams else ([params] if params else [{}])
    for batch in batches:
        for item in (batch if isinstance(batch, (list, tuple)) else [batch]):
            if isinstance(item, dict):
                rows.append({**compiled, **item})
    return [{key: value for key, value in row.items() if value is not None} for row in rows] or [compiled]


def _guard_core_dml(conn, clauseelement, multiparams, params, execution_options):
    """N-908-02 Laufzeitschutz: Core-DML (``update/delete/insert``) auf eine
    Abhaengigkeitstabelle, die weder aus einem Session-Flush (``after_flush``-
    Hook) noch aus dem Massen-Hook kommt -- z. B. ``db.connection().execute(
    update(Goal))`` oder ``engine.begin()`` -- loest den Hook auf Verbindungs-
    ebene aus: betroffene Zeilen werden vor der Ausfuehrung gelesen (UPDATE/
    DELETE; PostgreSQL ``FOR UPDATE``) bzw. die einzufuegenden Werte
    ausgewertet (INSERT) und invalidiert, im selben Commit. Ohne Session gibt
    es keinen Benutzerkontext: Actor ``system``; das Ereignis selbst ist der
    Beleg. Rohes SQL (``text``) verbietet der statische Waechter."""
    if not isinstance(clauseelement, UpdateBase):
        return
    table = getattr(clauseelement, "table", None)
    source = DEPENDENCY_SOURCES.get(getattr(table, "name", None))
    if source is None or _HOOK_SCOPE.get() or _flush_in_progress():
        return
    if not freshness_tables_present(conn):
        return
    token = _HOOK_SCOPE.set(True)
    try:
        changes: list[_Change] = []
        if clauseelement.is_insert:
            for row in _insert_rows(clauseelement, multiparams, params):
                values = _row_projection(table, row, source)
                changes.append(_change(table.name, source, "insert", {}, values, tenant=_row_tenant(row)))
        else:
            where = getattr(clauseelement, "whereclause", None)
            query = select(table) if where is None else select(table).where(where)
            query = query.order_by(*table.primary_key.columns)
            if conn.dialect.name.startswith("postgresql"):
                query = query.with_for_update()
            for row in conn.execute(query).mappings().all():
                old = _row_projection(table, row, source)
                change = _change(table.name, source, "delete", old, {}, tenant=_row_tenant(row))
                if clauseelement.is_update:
                    change.op = "update"
                changes.append(change)
        if changes:
            _apply_invalidations_on(conn, changes, actor=SYSTEM_ACTOR, pending=None)
    finally:
        _HOOK_SCOPE.reset(token)


def _write_pending_audit(session: Session) -> None:
    if session.new or session.dirty or session.deleted:
        session.flush()
    pending = session.info.pop(_PENDING_AUDIT_KEY, None)
    if pending:
        for sink in list(_AUDIT_SINKS):
            sink(session, pending)


def _discard_pending_audit(session: Session, *_args) -> None:
    session.info.pop(_PENDING_AUDIT_KEY, None)


event.listen(Session, "before_flush", _enter_flush)
event.listen(Session, "after_flush", _after_flush)
event.listen(Session, "after_flush_postexec", _leave_flush)
event.listen(Session, "after_soft_rollback", _reset_flush_depth)
event.listen(Session, "after_commit", _reset_flush_depth)
event.listen(Session, "after_rollback", _reset_flush_depth)
event.listen(Session, "do_orm_execute", _bulk_orm_write)
event.listen(Engine, "before_execute", _guard_core_dml)
event.listen(Session, "before_commit", _write_pending_audit)
event.listen(Session, "after_rollback", _discard_pending_audit)


# ── CCX-P3 Markt- und Depot-Wahrheit (Vertrag 2026-11-13 §6 + Nachtrag P3-FX) ──
#
# * HoldingsValuationSnapshot: Bewertungs-Snapshot eines Mandats zu einem
#   Stichtag -- Quelle, Beobachtungszeitpunkt (aeltester Beleg),
#   Referenzwaehrung, gebundene FX-Basis (fx_basis_hash + Kurse),
#   coverage_status COMPLETE|PARTIAL|UNKNOWN; nur COMPLETE traegt Gesamt- und
#   Beratungsvermoegen (Minor Units), sonst sind beide NULL.
# * HoldingsValuationRow: verlustfreie Positionsprojektion -- jede aktive
#   Vermoegensposition (inkl. Verbindlichkeit) und jede Depotposition des
#   massgebenden Laufs genau einmal; unbekannt ist base_value_minor NULL, nie 0.
# * PositionDecisionLedger: KEEP|SELL|REVIEW je bestehender Depotposition, an
#   den P1-Envelope gebunden (nur im DRAFT einfuegbar).
# DDL-Quelle SQLite: database.py (HOLDINGS_VALUATION_SQLITE_*), textgleich
# ares_schema.sql; PostgreSQL: Alembic (CCX-P3-Revision). Append-only.

HOLDINGS_VALUATION_SCHEMA_VERSION = "ares/holdings-valuation/1"
COVERAGE_STATUSES = ("COMPLETE", "PARTIAL", "UNKNOWN")
POSITION_DECISIONS = ("KEEP", "SELL", "REVIEW")


class HoldingsValuationSnapshot(Base):
    """Bewertungs-Snapshot (Stichtag + Quelle + FX-Basis + Abdeckung)."""

    __tablename__ = "holdings_valuation_snapshots"
    __table_args__ = (
        CheckConstraint(
            "schema_version = 'ares/holdings-valuation/1'",
            name="ck_holdings_valuation_snapshots_schema_version",
        ),
        CheckConstraint("length(fx_basis_hash) = 64", name="ck_holdings_valuation_snapshots_fx_hash"),
        CheckConstraint(
            "coverage_status IN ('COMPLETE','PARTIAL','UNKNOWN')",
            name="ck_holdings_valuation_snapshots_coverage",
        ),
        CheckConstraint(
            "holdings_basis IN ('recorded','confirmed_no_holdings')",
            name="ck_holdings_valuation_snapshots_basis",
        ),
        CheckConstraint("position_count >= 0", name="ck_holdings_valuation_snapshots_count"),
        CheckConstraint("length(snapshot_hash) = 64", name="ck_holdings_valuation_snapshots_hash"),
        CheckConstraint(
            "manual_valuation_attested IN (0, 1)", name="ck_holdings_valuation_snapshots_attested",
        ),
        CheckConstraint(
            "coverage_status <> 'COMPLETE' OR (total_base_minor IS NOT NULL AND advisory_base_minor IS NOT NULL "
            "AND blocker_codes_json = '[]')",
            name="ck_holdings_valuation_snapshots_complete_total",
        ),
        CheckConstraint(
            "coverage_status = 'COMPLETE' OR (total_base_minor IS NULL AND advisory_base_minor IS NULL "
            "AND blocker_codes_json <> '[]')",
            name="ck_holdings_valuation_snapshots_unknown_total",
        ),
        CheckConstraint(
            "holdings_basis = 'recorded' OR position_count = 0",
            name="ck_holdings_valuation_snapshots_no_holdings",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_holdings_valuation_snapshots_tenant_id"),
        UniqueConstraint(
            "tenant_id", "mandate_id", "snapshot_hash", name="uq_holdings_valuation_snapshots_hash",
        ),
        Index("ix_holdings_valuation_snapshots_tenant_id", "tenant_id"),
        Index("ix_holdings_valuation_snapshots_mandate", "tenant_id", "mandate_id", "as_of"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    mandate_id = Column(String, nullable=False)
    schema_version = Column(String, nullable=False, default=HOLDINGS_VALUATION_SCHEMA_VERSION)
    as_of = Column(String, nullable=False)
    source_observed_at = Column(String)
    source_system = Column(String, nullable=False)
    base_currency = Column(String, nullable=False)
    fx_basis_hash = Column(String, nullable=False)
    fx_basis_json = Column(String, nullable=False)
    coverage_status = Column(String, nullable=False)
    holdings_basis = Column(String, nullable=False)
    position_count = Column(Integer, nullable=False)
    total_base_minor = Column(BigInteger)
    advisory_base_minor = Column(BigInteger)
    blocker_codes_json = Column(String, nullable=False)
    # N-909-07: Bestaetigung "Bewertung aktuell" durch den Berater (ohne
    # Owner-Frist Pflicht) und die wirksame Owner-Frist; beides im Hash.
    manual_valuation_attested = Column(Integer, nullable=False, default=0)
    manual_valuation_max_age_days = Column(Integer)
    snapshot_hash = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)


class HoldingsValuationRow(Base):
    """Eine Positionszeile des Snapshots (verlustfrei, nie 0 fuer unbekannt)."""

    __tablename__ = "holdings_valuation_rows"
    __table_args__ = (
        CheckConstraint(
            "source_kind IN ('wealth_position','depot_holding')",
            name="ck_holdings_valuation_rows_source_kind",
        ),
        CheckConstraint("included_in_total IN (0, 1)", name="ck_holdings_valuation_rows_included"),
        CheckConstraint("length(row_hash) = 64", name="ck_holdings_valuation_rows_hash"),
        CheckConstraint(
            "data_quality <> 'OK' OR base_value_minor IS NOT NULL",
            name="ck_holdings_valuation_rows_ok_value",
        ),
        UniqueConstraint("snapshot_id", "position_id", name="uq_holdings_valuation_rows_position"),
        ForeignKeyConstraint(
            ["tenant_id", "snapshot_id"],
            ["holdings_valuation_snapshots.tenant_id", "holdings_valuation_snapshots.id"],
            name="fk_holdings_valuation_rows_snapshot",
        ),
        Index("ix_holdings_valuation_rows_tenant_id", "tenant_id"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    snapshot_id = Column(String, nullable=False)
    position_id = Column(String, nullable=False)
    source_kind = Column(String, nullable=False)
    instrument_id = Column(String)
    assignment = Column(String)
    quantity_decimal_string = Column(String)
    price_minor = Column(BigInteger)
    price_currency = Column(String)
    source_amount_minor = Column(BigInteger)
    fx_rate_ppm = Column(BigInteger)
    fx_rate_ratio = Column(String)
    fx_source = Column(String)
    fx_observed_at = Column(String)
    base_value_minor = Column(BigInteger)
    price_observed_at = Column(String)
    data_quality = Column(String, nullable=False)
    included_in_total = Column(Integer, nullable=False)
    row_hash = Column(String, nullable=False)


class PositionDecisionLedger(Base):
    """Entscheid je bestehender Depotposition, gebunden an den Envelope."""

    __tablename__ = "position_decision_ledger"
    __table_args__ = (
        CheckConstraint("decision IN ('KEEP','SELL','REVIEW')", name="ck_position_decision_ledger_decision"),
        CheckConstraint(
            "length(source_snapshot_hash) = 64", name="ck_position_decision_ledger_snapshot_hash",
        ),
        UniqueConstraint("envelope_id", "position_id", name="uq_position_decision_ledger_position"),
        ForeignKeyConstraint(
            ["tenant_id", "envelope_id"],
            ["advisory_decision_envelopes.tenant_id", "advisory_decision_envelopes.id"],
            name="fk_position_decision_ledger_envelope",
        ),
        Index("ix_position_decision_ledger_tenant_id", "tenant_id"),
        Index("ix_position_decision_ledger_mandate", "tenant_id", "mandate_id"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    mandate_id = Column(String, nullable=False)
    envelope_id = Column(String, nullable=False)
    position_id = Column(String, nullable=False)
    decision = Column(String, nullable=False)
    reason_code = Column(String, nullable=False)
    source_snapshot_hash = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)


HOLDINGS_VALUATION_TABLES = (
    HoldingsValuationSnapshot.__tablename__,
    HoldingsValuationRow.__tablename__,
    PositionDecisionLedger.__tablename__,
)


def _create_holdings_valuation_sqlite_triggers(_metadata, connection, **_kw) -> None:
    """Metadata-Hook (SQLite): Trigger erst, wenn alle Tabellen (inkl. P1-Envelope)
    und ``mandates.tenant_id`` existieren."""
    if connection.dialect.name != "sqlite":
        return
    tables = {row[0] for row in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    if not (set(HOLDINGS_VALUATION_TABLES) | {"advisory_decision_envelopes"}) <= tables:
        return
    for ddl in HOLDINGS_VALUATION_SQLITE_TRIGGERS:
        connection.exec_driver_sql(ddl)
    if "mandates" in tables and "tenant_id" in {
        row[1] for row in connection.exec_driver_sql("PRAGMA table_info(mandates)")
    }:
        for ddl in HOLDINGS_VALUATION_SQLITE_TENANT_GUARDS:
            connection.exec_driver_sql(ddl)


event.listen(Base.metadata, "after_create", _create_holdings_valuation_sqlite_triggers)


# ── CCX-P4 Allocation-Publish (Vertrag 2026-11-13 §7) ──
#
# CCX-P4 Allocation-Publish (Vertrag 2026-11-13 §7).
#
# * ``AllocationPublicationDecision``: append-only Publikationsentscheid je
#   Mandat (fortlaufende ``publication_sequence``). ``publishable = 1`` traegt
#   die Freigabe (``approval_hash``, Freigeber, Zeit, Modus) und den
#   publizierten ``published_envelope_hash``; ``publishable = 0`` haelt einen
#   abgelehnten Publikationsversuch samt katalogisierten ``blocker_codes_json``
#   fest. ``validation_hash`` bindet den geprueften Stand (Envelope, Soll-
#   Allokation, Bewertung, Gate-Ergebnisse).
# * ``AllocationActivePublication``: Active-Pointer, hoechstens einer je Mandat
#   (Unique ``mandate_id``); er zeigt nur auf einen publizierbaren Entscheid
#   desselben Mandats, wandert nur vorwaerts (hoehere Sequenz) und steigt dabei
#   in ``optimistic_version`` um genau 1. Nie geloescht.
#
# Geschrieben werden beide Tabellen ausschliesslich von
# ``services/allocation_publication_gate.py::publish_allocation`` (AST-Waechter
# ``tests/test_ccx_p4_allocation_publish.py``). DDL-Quelle SQLite: database.py
# (``ALLOCATION_PUBLICATION_SQLITE_*``), textgleich ares_schema.sql;
# PostgreSQL: Alembic (CCX-P4-Revision). Kein Backfill: Bestand ist nicht
# publiziert.

ALLOCATION_PUBLICATION_SCHEMA_VERSION = "ares/allocation-publication/1"
APPROVAL_MODES = ("four_eyes", "single_approver_attested")


class AllocationPublicationDecision(Base):
    """Publikationsentscheid (append-only, auch abgelehnte Versuche)."""

    __tablename__ = "allocation_publication_decisions"
    __table_args__ = (
        CheckConstraint(
            "schema_version = 'ares/allocation-publication/1'",
            name="ck_allocation_publication_decisions_schema_version",
        ),
        CheckConstraint("publication_sequence >= 1", name="ck_allocation_publication_decisions_sequence_min"),
        CheckConstraint("length(validation_hash) = 64", name="ck_allocation_publication_decisions_validation"),
        CheckConstraint(
            "approval_hash IS NULL OR length(approval_hash) = 64",
            name="ck_allocation_publication_decisions_approval",
        ),
        CheckConstraint(
            "approval_mode IS NULL OR approval_mode IN ('four_eyes','single_approver_attested')",
            name="ck_allocation_publication_decisions_mode",
        ),
        CheckConstraint("publishable IN (0, 1)", name="ck_allocation_publication_decisions_flag"),
        CheckConstraint(
            "published_envelope_hash IS NULL OR length(published_envelope_hash) = 64",
            name="ck_allocation_publication_decisions_envelope_hash",
        ),
        CheckConstraint(
            "publishable = 0 OR (envelope_id IS NOT NULL AND target_allocation_id IS NOT NULL "
            "AND approval_hash IS NOT NULL AND approval_mode IS NOT NULL AND approved_at IS NOT NULL "
            "AND approved_by IS NOT NULL AND published_envelope_hash IS NOT NULL "
            "AND blocker_codes_json = '[]' "
            "AND eligible_approver_count IS NOT NULL AND single_person_firm IS NOT NULL)",
            name="ck_allocation_publication_decisions_published",
        ),
        CheckConstraint(
            "publishable = 1 OR (published_envelope_hash IS NULL AND approval_hash IS NULL "
            "AND blocker_codes_json <> '[]')",
            name="ck_allocation_publication_decisions_blocked",
        ),
        CheckConstraint(
            "eligible_approver_count IS NULL OR eligible_approver_count >= 0",
            name="ck_allocation_publication_decisions_approver_count",
        ),
        CheckConstraint(
            "single_person_firm IS NULL OR single_person_firm IN (0, 1)",
            name="ck_allocation_publication_decisions_single_flag",
        ),
        CheckConstraint(
            "approval_mode IS NULL OR approval_mode <> 'single_approver_attested' "
            "OR (single_person_firm = 1 AND eligible_approver_count = 1)",
            name="ck_allocation_publication_decisions_single",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_allocation_publication_decisions_tenant_id"),
        UniqueConstraint(
            "mandate_id", "publication_sequence", name="uq_allocation_publication_decisions_sequence",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "envelope_id"],
            ["advisory_decision_envelopes.tenant_id", "advisory_decision_envelopes.id"],
            name="fk_allocation_publication_decisions_envelope",
        ),
        Index("ix_allocation_publication_decisions_tenant_id", "tenant_id"),
        Index("ix_allocation_publication_decisions_mandate", "tenant_id", "mandate_id"),
        Index(
            "ux_allocation_publication_decisions_one_per_envelope", "envelope_id", unique=True,
            sqlite_where=text("publishable = 1"), postgresql_where=text("publishable = 1"),
        ),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    mandate_id = Column(String, nullable=False)
    schema_version = Column(String, nullable=False)
    envelope_id = Column(String)
    # N-910-06: FK auf die Soll-Allokation (Mandatsgleichheit prueft der Guard).
    target_allocation_id = Column(String, ForeignKey("target_allocations.id"))
    publication_sequence = Column(Integer, nullable=False)
    validation_hash = Column(String, nullable=False)
    approval_hash = Column(String)
    approval_mode = Column(String)
    approved_at = Column(String)
    approved_by = Column(String, ForeignKey("users.id"))
    publishable = Column(Integer, nullable=False)
    blocker_codes_json = Column(String, nullable=False)
    published_envelope_hash = Column(String)
    created_at = Column(String, nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    # N-910-02: Basis der Freigabe -- Zahl der aktiven Publish-Berechtigten und
    # die Tenant-Konfiguration "Ein-Personen-Firma" zum Zeitpunkt (im approval_hash).
    eligible_approver_count = Column(Integer)
    single_person_firm = Column(Integer)
    # H12 N-910-14: Version des Approval-Schluessels (= tenants.dek_version beim
    # Binden), auch im approval_hash. NULL nur bei Altpublikationen vor H12 bzw.
    # abgelehnten Versuchen; eine publizierte Zeile ohne Version ist ungueltig
    # (CCX_APPROVAL_KEY_VERSION_MISSING, im Lesepfad; kein CHECK, weil SQLite den
    # bestehenden CHECK nicht ohne Tabellen-Neuaufbau samt Triggern aendern kann).
    approval_key_version = Column(Integer)


class AllocationActivePublication(Base):
    """Active-Pointer: hoechstens eine aktive Publikation je Mandat."""

    __tablename__ = "allocation_active_publications"
    __table_args__ = (
        CheckConstraint("optimistic_version >= 1", name="ck_allocation_active_publications_version"),
        UniqueConstraint("mandate_id", name="uq_allocation_active_publications_mandate"),
        ForeignKeyConstraint(
            ["tenant_id", "publication_id"],
            ["allocation_publication_decisions.tenant_id", "allocation_publication_decisions.id"],
            name="fk_allocation_active_publications_publication",
        ),
        Index("ix_allocation_active_publications_tenant_id", "tenant_id"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    mandate_id = Column(String, nullable=False)
    publication_id = Column(String, nullable=False)
    optimistic_version = Column(Integer, nullable=False)
    updated_at = Column(String, nullable=False)
    updated_by = Column(String, ForeignKey("users.id"), nullable=False)


ALLOCATION_PUBLICATION_TABLES = (
    AllocationPublicationDecision.__tablename__,
    AllocationActivePublication.__tablename__,
)


def _create_allocation_publication_sqlite_triggers(_metadata, connection, **_kw) -> None:
    """Metadata-Hook (SQLite): Trigger erst, wenn beide Tabellen und der
    P1/P2-Envelope existieren; Mandanten-Guards nur mit ``mandates.tenant_id``."""
    if connection.dialect.name != "sqlite":
        return
    tables = {row[0] for row in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    if not (set(ALLOCATION_PUBLICATION_TABLES) | {"advisory_decision_envelopes"}) <= tables:
        return
    for ddl in ALLOCATION_PUBLICATION_SQLITE_TRIGGERS:
        connection.exec_driver_sql(ddl)
    if "mandates" in tables and "tenant_id" in {
        row[1] for row in connection.exec_driver_sql("PRAGMA table_info(mandates)")
    }:
        for ddl in ALLOCATION_PUBLICATION_SQLITE_TENANT_GUARDS:
            connection.exec_driver_sql(ddl)


event.listen(Base.metadata, "after_create", _create_allocation_publication_sqlite_triggers)
