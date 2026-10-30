from sqlalchemy import DDL, BigInteger, Column, String, Integer, ForeignKey, UniqueConstraint, Index, event
from sqlalchemy.orm import relationship
from database import DEPOT_CHECK_ANALYSIS_SQLITE_TRIGGERS, DEPOT_SNAPSHOT_SQLITE_TRIGGERS, Base


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
    """

    __tablename__ = "depot_snapshots"
    __table_args__ = (
        Index("ix_depot_snapshots_mandate", "mandate_id", "as_of_date"),
    )

    id = Column(String, primary_key=True)
    schema_version = Column(String, nullable=False, default="DepotSnapshotV1")
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
    """

    __tablename__ = "depot_check_analysis_snapshots"
    __table_args__ = (
        Index("ix_depot_check_analysis_snapshots_mandate", "mandate_id", "created_at"),
    )

    id = Column(String, primary_key=True)
    schema_version = Column(String, nullable=False, default="DepotCheckAnalysisV1")
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
