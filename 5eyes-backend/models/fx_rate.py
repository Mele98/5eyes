"""FXRate-Model: Wechselkurse zu CHF mit valid_from/until-Versionierung.

Spec: docs/planning/2026-05-17-sprint-9-multi-currency.md Phase 2
"""
from __future__ import annotations

from sqlalchemy import Column, Integer, String

from database import Base


class FXRate(Base):
    """Wechselkurs zu CHF (Basis-Waehrung 5eyes).

    Konvention: rate_x10000 = rate * 10000 (Integer-DB-Persistierung).
    Bei rate=0.95: rate_x10000=9500.

    Versionierung: pro currency mehrere Eintraege moeglich, der mit
    is_current=1 wird vom FXRateSource genutzt. Historische Eintraege
    bleiben fuer Audit-Reproduzierbarkeit.
    """

    __tablename__ = "fx_rates"

    id = Column(String, primary_key=True)
    currency = Column(String, nullable=False)  # ISO 3-Letter Code
    rate_x10000 = Column(Integer, nullable=False)  # rate-to-CHF * 10000
    valid_from = Column(String, nullable=False)
    valid_until = Column(String)
    is_current = Column(Integer, nullable=False, default=1)
    source = Column(String, default="Manual")  # 'Manual' | 'API' | 'Default'
    notes = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    created_by = Column(String)
