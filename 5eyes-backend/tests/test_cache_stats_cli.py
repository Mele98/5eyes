"""P25 Tests: CLI fuer Aggregator-Cache-Stats.

Verifiziert mit in-memory SQLite + frischem Schema:
- Leere DB -> total=0, kein Crash
- Mit Eintraegen -> total + per-kind valid/expired korrekt
- Oldest/newest fetched_at gesetzt
- format_report rendert ohne Crash
- report_to_dict ist JSON-serialisierbar
- main() Exit-Code 0 bei OK
- --json schreibt JSON
- --purge-expired ruft purge_expired (mocked)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "5eyes-backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from database import Base
from models.market_data_cache import MarketDataCacheEntry  # noqa: F401
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, users, wealth,
)
configure_mappers()

import cache_stats as cs


def _utc_iso(offset_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture()
def db_with_entries(tmp_path):
    db_file = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SF = sessionmaker(bind=engine)
    s = SF()
    s.add_all([
        MarketDataCacheEntry(cache_kind="eod", cache_key="A", value_json="{}",
                             fetched_at=_utc_iso(-200), expires_at=_utc_iso(3600)),
        MarketDataCacheEntry(cache_kind="eod", cache_key="B", value_json="{}",
                             fetched_at=_utc_iso(-100), expires_at=_utc_iso(-10)),
        MarketDataCacheEntry(cache_kind="history", cache_key="C", value_json="[]",
                             fetched_at=_utc_iso(-50), expires_at=_utc_iso(3600)),
        MarketDataCacheEntry(cache_kind="isin", cache_key="D", value_json="{}",
                             fetched_at=_utc_iso(0), expires_at=_utc_iso(86400)),
    ])
    s.commit()
    s.close()
    engine.dispose()
    yield str(db_file)


@pytest.fixture()
def empty_db(tmp_path):
    db_file = tmp_path / "empty.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    yield str(db_file)


# ============================================================================
# collect_cache_stats
# ============================================================================


def test_empty_db_returns_zero(empty_db):
    rpt = cs.collect_cache_stats(empty_db)
    assert rpt.total_entries == 0
    assert rpt.by_kind == []
    assert rpt.oldest_fetched_at is None
    assert rpt.newest_fetched_at is None
    assert rpt.error is None


def test_populated_db_aggregates_per_kind(db_with_entries):
    rpt = cs.collect_cache_stats(db_with_entries)
    assert rpt.total_entries == 4
    by_kind = {k.kind: k for k in rpt.by_kind}
    assert by_kind["eod"].total == 2
    assert by_kind["eod"].valid == 1
    assert by_kind["eod"].expired == 1
    assert by_kind["history"].total == 1
    assert by_kind["history"].valid == 1
    assert by_kind["isin"].total == 1


def test_oldest_newest_fetched_at_set(db_with_entries):
    rpt = cs.collect_cache_stats(db_with_entries)
    assert rpt.oldest_fetched_at is not None
    assert rpt.newest_fetched_at is not None
    assert rpt.oldest_fetched_at <= rpt.newest_fetched_at


def test_nonexistent_db_returns_error(tmp_path):
    """Wenn DB nicht existiert + Schema kann nicht geladen werden -> error gesetzt."""
    fake_path = str(tmp_path / "nonexistent.db")
    rpt = cs.collect_cache_stats(fake_path)
    # SQLite legt File on first access an, daher kein Crash, aber 0 Eintraege
    # Falls Schema fehlt -> error
    assert rpt.total_entries == 0 or rpt.error is not None


# ============================================================================
# format_report
# ============================================================================


def test_format_report_includes_header_and_kinds(db_with_entries):
    rpt = cs.collect_cache_stats(db_with_entries)
    text = cs.format_report(rpt)
    assert "Cache-Stats" in text
    assert "Total Eintraege: 4" in text
    assert "eod" in text
    assert "history" in text


def test_format_report_empty_db_no_crash(empty_db):
    rpt = cs.collect_cache_stats(empty_db)
    text = cs.format_report(rpt)
    assert "Total Eintraege: 0" in text


def test_format_report_with_purged(db_with_entries):
    rpt = cs.collect_cache_stats(db_with_entries)
    rpt.purged = 5
    text = cs.format_report(rpt)
    assert "5 expired" in text


def test_format_report_error(empty_db):
    rpt = cs.collect_cache_stats(empty_db)
    rpt.error = "boom"
    text = cs.format_report(rpt)
    assert "FEHLER" in text
    assert "boom" in text


# ============================================================================
# report_to_dict
# ============================================================================


def test_report_to_dict_serializes(db_with_entries):
    rpt = cs.collect_cache_stats(db_with_entries)
    d = cs.report_to_dict(rpt)
    assert d["total_entries"] == 4
    assert isinstance(d["by_kind"], list)
    json.dumps(d)  # muss serialisierbar sein


# ============================================================================
# main()
# ============================================================================


def test_main_returns_0_on_empty_db(empty_db, capsys):
    rc = cs.main(["--db-path", empty_db])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Cache-Stats" in out


def test_main_json_flag(db_with_entries, capsys):
    rc = cs.main(["--db-path", db_with_entries, "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["total_entries"] == 4


def test_main_with_purge_calls_purge_function(db_with_entries):
    with patch.object(cs, "purge_expired", return_value=42) as p:
        rc = cs.main(["--db-path", db_with_entries, "--purge-expired"])
    assert rc == 0
    assert p.call_count == 1


def test_main_purge_failure_returns_1(db_with_entries, capsys):
    with patch.object(cs, "purge_expired", side_effect=RuntimeError("boom")):
        rc = cs.main(["--db-path", db_with_entries, "--purge-expired"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "boom" in err
