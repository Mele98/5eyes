"""SQL-Modell fuer den Market-Data-Cache (P6 Multi-Source Aggregator).

Ein Eintrag pro Cache-Key. value_json enthaelt das serialisierte Resultat
(Bar als dict, list[Bar] als list[dict], ProductInfo als dict).
expires_at als ISO-String (UTC) — Aggregator vergleicht gegen
datetime.now(timezone.utc).

Tabelle wird via Base.metadata.create_all() automatisch angelegt.
"""
from __future__ import annotations

from sqlalchemy import Column, Index, Integer, String

from database import Base


class MarketDataCacheEntry(Base):
    __tablename__ = "market_data_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cache_kind = Column(String, nullable=False)
    cache_key = Column(String, nullable=False)
    value_json = Column(String, nullable=False)
    fetched_at = Column(String, nullable=False)
    expires_at = Column(String, nullable=False)

    __table_args__ = (
        Index("ix_mdc_kind_key", "cache_kind", "cache_key", unique=True),
        Index("ix_mdc_expires_at", "expires_at"),
    )
