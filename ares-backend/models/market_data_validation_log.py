"""SQL-Modell fuer Cross-Validation-Log (P7 Multi-Source Aggregator).

Dokumentiert pro Symbol-Tag wie 2-3 Provider sich unterschieden haben.
is_alert markiert Diffs > Threshold (default 300 bps = 3%).
Eingaben kommen von services/market_data/validation.py.
"""
from __future__ import annotations

from sqlalchemy import Column, Index, Integer, String

from database import Base


class MarketDataValidationLog(Base):
    __tablename__ = "market_data_validation_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    on_date = Column(String, nullable=False)        # ISO date
    checked_at = Column(String, nullable=False)     # ISO datetime UTC

    # Bis zu 3 Provider-Quotes (median wird ueber alle gerechnet).
    providers_json = Column(String, nullable=False)  # JSON: [{"name":"yfinance","close":"28.75"}, ...]
    median_close = Column(String, nullable=False)
    min_close = Column(String, nullable=False)
    max_close = Column(String, nullable=False)
    diff_bps = Column(Integer, nullable=False)       # (max-min)/median * 10000
    threshold_bps = Column(Integer, nullable=False)
    is_alert = Column(Integer, nullable=False, default=0)
    n_providers = Column(Integer, nullable=False)

    __table_args__ = (
        Index("ix_mdvl_symbol_date", "symbol", "on_date"),
        Index("ix_mdvl_alert_checked", "is_alert", "checked_at"),
    )
