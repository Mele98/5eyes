from sqlalchemy import Column, String, Integer, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from database import Base


class StrategySnapshot(Base):
    __tablename__ = "strategy_snapshots"
    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    snapshot_date = Column(String, nullable=False)
    advisory_assets_rappen = Column(Integer, nullable=False)
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
    close_rappen = Column(Integer, nullable=False)
    currency = Column(String)  # U-P19b: native Notierungswährung (ISO-3), z.B. "USD"
    source = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


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
