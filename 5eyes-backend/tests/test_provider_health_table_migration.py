from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.market_data.provider_health_registry import (  # noqa: E402
    HEALTH_COLUMNS,
    ensure_provider_health_table,
)


def test_ensure_provider_health_table_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'health.db'}")
    ensure_provider_health_table(engine)
    ensure_provider_health_table(engine)

    with engine.connect() as conn:
        tables = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='provider_health_events'"
        )).fetchall()

    assert len(tables) == 1
    engine.dispose()


def test_provider_health_table_has_expected_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'health.db'}")
    ensure_provider_health_table(engine)

    with engine.connect() as conn:
        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(provider_health_events)")).fetchall()
        }

    assert set(HEALTH_COLUMNS).issubset(columns)
    engine.dispose()


def test_provider_health_table_indexes_created(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'health.db'}")
    ensure_provider_health_table(engine)

    with engine.connect() as conn:
        indexes = {
            row[1]
            for row in conn.execute(text("PRAGMA index_list(provider_health_events)")).fetchall()
        }

    assert "ix_provider_health_events_provider_observed" in indexes
    assert "ix_provider_health_events_status" in indexes
    engine.dispose()


def test_ensure_provider_health_table_upgrades_legacy_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'health.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE provider_health_events (id TEXT PRIMARY KEY)"))

    ensure_provider_health_table(engine)

    with engine.connect() as conn:
        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(provider_health_events)")).fetchall()
        }

    assert set(HEALTH_COLUMNS).issubset(columns)
    engine.dispose()
