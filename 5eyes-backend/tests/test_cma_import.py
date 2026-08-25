"""Phase 10 Tests: CMA-CSV-Import.

Schreibt Test-CSVs in tmp_path, prueft Validation + Diff + Apply gegen
echte SQLite-DB (Base.metadata.create_all).
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, users, wealth,
)
from models.allocation import CapitalMarketAssumption
from models.users import User
configure_mappers()

from services.cma_import import (
    CMA_NUMERIC_COLUMNS,
    apply_cma_row,
    diff_against_current,
    import_cma_csv,
    read_cma_csv,
    validate_cma_row,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cma.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    s = SF()
    # User anlegen (CMA.created_by ist FK)
    now = datetime.now(timezone.utc).isoformat()
    user = User(
        id="user-cma", username="cma", password_hash="h",
        full_name="CMA", role="advisor", is_active=1,
        created_at=now, updated_at=now,
    )
    s.add(user)
    s.commit()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _csv_path(tmp_path, content: str) -> str:
    p = tmp_path / "cma.csv"
    p.write_text(content, encoding="utf-8")
    return str(p)


# ============================================================================
# read_cma_csv
# ============================================================================


def test_read_cma_csv_basic(tmp_path):
    p = _csv_path(tmp_path, (
        "assumption_set_name,valid_from,equity_ch_return_bps\n"
        "BlackRock Q2,2026-04-01,620\n"
    ))
    rows = read_cma_csv(p)
    assert len(rows) == 1
    assert rows[0]["assumption_set_name"] == "BlackRock Q2"
    assert rows[0]["valid_from"] == "2026-04-01"
    assert rows[0]["equity_ch_return_bps"] == "620"


def test_read_cma_csv_skips_empty_rows(tmp_path):
    p = _csv_path(tmp_path, (
        "assumption_set_name,valid_from\n"
        "Set A,2026-04-01\n"
        ",\n"
        "Set B,2026-07-01\n"
    ))
    rows = read_cma_csv(p)
    assert len(rows) == 2


def test_read_cma_csv_strips_whitespace(tmp_path):
    p = _csv_path(tmp_path, (
        "assumption_set_name,valid_from\n"
        "  Spaced  , 2026-04-01 \n"
    ))
    rows = read_cma_csv(p)
    assert rows[0]["assumption_set_name"] == "Spaced"
    assert rows[0]["valid_from"] == "2026-04-01"


# ============================================================================
# validate_cma_row
# ============================================================================


def test_validate_ok_returns_no_issues():
    row = {
        "assumption_set_name": "Test",
        "valid_from": "2026-04-01",
        "equity_ch_return_bps": "620",
        "equity_ch_vol_bps": "1450",
    }
    assert validate_cma_row(row, 1) == []


def test_validate_missing_set_name():
    row = {"valid_from": "2026-04-01"}
    issues = validate_cma_row(row, 1)
    assert any(i.column == "assumption_set_name" for i in issues)


def test_validate_invalid_date():
    row = {"assumption_set_name": "X", "valid_from": "not-a-date"}
    issues = validate_cma_row(row, 1)
    assert any(i.column == "valid_from" for i in issues)


def test_validate_return_out_of_range():
    row = {
        "assumption_set_name": "X", "valid_from": "2026-04-01",
        "equity_ch_return_bps": "999999",
    }
    issues = validate_cma_row(row, 1)
    assert any(i.column == "equity_ch_return_bps" for i in issues)


def test_validate_vol_out_of_range():
    row = {
        "assumption_set_name": "X", "valid_from": "2026-04-01",
        "equity_ch_vol_bps": "-100",
    }
    issues = validate_cma_row(row, 1)
    assert any(i.column == "equity_ch_vol_bps" for i in issues)


def test_validate_non_integer():
    row = {
        "assumption_set_name": "X", "valid_from": "2026-04-01",
        "equity_ch_return_bps": "abc",
    }
    issues = validate_cma_row(row, 1)
    assert any(i.column == "equity_ch_return_bps" for i in issues)


# ============================================================================
# apply_cma_row / Diff / End-to-end
# ============================================================================


def test_apply_creates_new_cma_entry(session):
    row = {
        "assumption_set_name": "BlackRock Q2",
        "valid_from": "2026-04-01",
        "source": "BlackRock LTCMA",
        "equity_ch_return_bps": "620",
        "equity_ch_vol_bps": "1450",
    }
    apply_cma_row(session, row, user_id="user-cma")
    session.commit()
    entries = session.query(CapitalMarketAssumption).all()
    assert len(entries) == 1
    e = entries[0]
    assert e.assumption_set_name == "BlackRock Q2"
    assert e.is_current == 1
    assert e.version == 1
    assert e.equity_ch_return_bps == 620
    assert e.source == "BlackRock LTCMA"


def test_apply_supersedes_previous_current(session):
    row1 = {
        "assumption_set_name": "BlackRock Q2",
        "valid_from": "2026-04-01",
        "equity_ch_return_bps": "620",
    }
    apply_cma_row(session, row1, user_id="user-cma")
    session.commit()

    row2 = {
        "assumption_set_name": "BlackRock Q2",
        "valid_from": "2026-07-01",
        "equity_ch_return_bps": "650",
    }
    apply_cma_row(session, row2, user_id="user-cma")
    session.commit()

    entries = (
        session.query(CapitalMarketAssumption)
        .filter(CapitalMarketAssumption.assumption_set_name == "BlackRock Q2")
        .order_by(CapitalMarketAssumption.version)
        .all()
    )
    assert len(entries) == 2
    assert entries[0].version == 1 and entries[0].is_current == 0
    assert entries[1].version == 2 and entries[1].is_current == 1
    assert entries[1].equity_ch_return_bps == 650


def test_diff_against_current_shows_changes(session):
    row1 = {
        "assumption_set_name": "S1", "valid_from": "2026-04-01",
        "equity_ch_return_bps": "620",
    }
    apply_cma_row(session, row1, user_id="user-cma")
    session.commit()

    row2_proposed = {
        "assumption_set_name": "S1", "valid_from": "2026-07-01",
        "equity_ch_return_bps": "650",
        "equity_ch_vol_bps": "1500",
    }
    diff = diff_against_current(session, row2_proposed)
    assert diff["equity_ch_return_bps"] == (620, 650)
    assert diff["equity_ch_vol_bps"] == (None, 1500)


def test_diff_empty_when_no_previous(session):
    row = {"assumption_set_name": "NewSet", "valid_from": "2026-04-01"}
    diff = diff_against_current(session, row)
    assert diff == {}


# ============================================================================
# import_cma_csv End-to-end
# ============================================================================


def test_import_dry_run_does_not_write(session, tmp_path):
    p = _csv_path(tmp_path, (
        "assumption_set_name,valid_from,equity_ch_return_bps\n"
        "Dry,2026-04-01,620\n"
    ))
    result = import_cma_csv(session, p, user_id="user-cma", dry_run=True)
    assert not result.has_errors
    assert result.applied_count == 0
    assert session.query(CapitalMarketAssumption).count() == 0


def test_import_apply_writes(session, tmp_path):
    p = _csv_path(tmp_path, (
        "assumption_set_name,valid_from,equity_ch_return_bps\n"
        "Apply,2026-04-01,620\n"
    ))
    result = import_cma_csv(session, p, user_id="user-cma", dry_run=False)
    assert not result.has_errors
    assert result.applied_count == 1
    assert session.query(CapitalMarketAssumption).count() == 1


def test_import_skips_rows_with_errors(session, tmp_path):
    p = _csv_path(tmp_path, (
        "assumption_set_name,valid_from,equity_ch_return_bps\n"
        ",2026-04-01,620\n"  # missing name -> error
        "Good,2026-04-01,650\n"
    ))
    result = import_cma_csv(session, p, user_id="user-cma", dry_run=False)
    assert result.has_errors  # zeile 1 hat Error
    # Zeile 2 wird trotzdem applied
    assert result.applied_count == 1
    assert session.query(CapitalMarketAssumption).count() == 1
    assert session.query(CapitalMarketAssumption).first().assumption_set_name == "Good"
