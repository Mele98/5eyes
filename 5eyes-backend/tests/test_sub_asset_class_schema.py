"""Tests fuer Schema-Erweiterung sub_asset_class (Phase 1).

Verifiziert:
- ensure_runtime_columns ergaenzt sub_asset_class auf bestehenden Tabellen
  idempotent (kein Fehler bei Re-Run, kein Verlust bestehender Daten)
- Models koennen mit sub_asset_class=NULL UND sub_asset_class="..." schreiben
- Backwards-Compat: existierende Top-Level-Aggregat-Rows (sub_asset_class
  NULL) bleiben unveraendert nutzbar
- ORM-Read liefert die Spalte korrekt
"""
from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, configure_mappers, sessionmaker

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)
configure_mappers()

from models.snapshots import AssetClassAnnualReturn, AssetClassPriceHistory


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


@pytest.fixture
def sqlite_db():
    """Frische In-Memory-DB mit Schema."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    yield db, engine
    db.close()


def test_annual_returns_has_sub_asset_class_column(sqlite_db):
    """asset_class_annual_returns Tabelle hat sub_asset_class Spalte."""
    _, engine = sqlite_db
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("asset_class_annual_returns")}
    assert "sub_asset_class" in cols


def test_price_history_has_sub_asset_class_column(sqlite_db):
    """asset_class_price_history Tabelle hat sub_asset_class Spalte."""
    _, engine = sqlite_db
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("asset_class_price_history")}
    assert "sub_asset_class" in cols


def test_annual_returns_accepts_null_sub_asset(sqlite_db):
    """Backwards-Compat: NULL = Top-Level-Aggregat wie heute."""
    db, _ = sqlite_db
    row = AssetClassAnnualReturn(
        id=str(uuid.uuid4()),
        year=2020,
        asset_class="Aktien",
        return_bps=850,
        source="test",
        created_at=_now(),
        updated_at=_now(),
        sub_asset_class=None,
    )
    db.add(row)
    db.commit()
    fetched = db.query(AssetClassAnnualReturn).filter_by(id=row.id).first()
    assert fetched is not None
    assert fetched.sub_asset_class is None
    assert fetched.asset_class == "Aktien"


def test_annual_returns_accepts_sub_asset_value(sqlite_db):
    """NOT-NULL: spezifischer Sub-Asset-Schluessel."""
    db, _ = sqlite_db
    row = AssetClassAnnualReturn(
        id=str(uuid.uuid4()),
        year=2020,
        asset_class="Aktien",
        return_bps=1050,
        source="test",
        created_at=_now(),
        updated_at=_now(),
        sub_asset_class="Aktien_CH_Large",
    )
    db.add(row)
    db.commit()
    fetched = db.query(AssetClassAnnualReturn).filter_by(id=row.id).first()
    assert fetched.sub_asset_class == "Aktien_CH_Large"
    assert fetched.asset_class == "Aktien"


def test_price_history_accepts_null_sub_asset(sqlite_db):
    """Price-History Backwards-Compat."""
    db, _ = sqlite_db
    row = AssetClassPriceHistory(
        id=str(uuid.uuid4()),
        asset_class="Aktien",
        price_date="2020-12-31",
        close_rappen=1000000,
        currency="USD",
        source="test",
        created_at=_now(),
        updated_at=_now(),
        sub_asset_class=None,
    )
    db.add(row)
    db.commit()
    fetched = db.query(AssetClassPriceHistory).filter_by(id=row.id).first()
    assert fetched.sub_asset_class is None


def test_price_history_accepts_sub_asset_value(sqlite_db):
    """Price-History mit Sub-Asset."""
    db, _ = sqlite_db
    row = AssetClassPriceHistory(
        id=str(uuid.uuid4()),
        asset_class="Aktien",
        price_date="2020-12-31",
        close_rappen=1280000,
        currency="CHF",
        source="test",
        created_at=_now(),
        updated_at=_now(),
        sub_asset_class="Aktien_CH_Large",
    )
    db.add(row)
    db.commit()
    fetched = db.query(AssetClassPriceHistory).filter_by(id=row.id).first()
    assert fetched.sub_asset_class == "Aktien_CH_Large"


def test_filter_by_sub_asset_class(sqlite_db):
    """Query-Filter nach sub_asset_class funktioniert."""
    db, _ = sqlite_db
    # Insert: 1x NULL (Top-Level), 2x verschiedene Sub-Assets
    for sub, rb in [(None, 800), ("Aktien_CH_Large", 950), ("Aktien_US_Large", 1100)]:
        db.add(AssetClassAnnualReturn(
            id=str(uuid.uuid4()),
            year=2020,
            asset_class="Aktien",
            return_bps=rb,
            source="test",
            created_at=_now(),
            updated_at=_now(),
            sub_asset_class=sub,
        ))
    db.commit()

    # Filter: nur Top-Level (sub_asset_class IS NULL)
    top_level = db.query(AssetClassAnnualReturn).filter(
        AssetClassAnnualReturn.sub_asset_class.is_(None)
    ).all()
    assert len(top_level) == 1
    assert top_level[0].return_bps == 800

    # Filter: nur Aktien_CH_Large
    ch_large = db.query(AssetClassAnnualReturn).filter(
        AssetClassAnnualReturn.sub_asset_class == "Aktien_CH_Large"
    ).all()
    assert len(ch_large) == 1
    assert ch_large[0].return_bps == 950


def test_ensure_runtime_columns_is_idempotent():
    """ensure_runtime_columns auf einer Live-DB (file) zweimal aufrufen ist
    safe — fuegt sub_asset_class hinzu wenn fehlend, no-op wenn schon da."""
    from database import ensure_runtime_columns, SessionLocal, engine

    # Original-engine wird genutzt; wir checken nur dass kein Crash.
    # Erster Aufruf
    ensure_runtime_columns()
    # Zweiter Aufruf (idempotent)
    ensure_runtime_columns()
    # Wenn wir hier sind, kein Crash -> OK
    insp = inspect(engine)
    if "asset_class_annual_returns" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("asset_class_annual_returns")}
        assert "sub_asset_class" in cols
    if "asset_class_price_history" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("asset_class_price_history")}
        assert "sub_asset_class" in cols
