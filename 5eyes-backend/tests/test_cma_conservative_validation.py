"""Roadmap #51 (CMA-Werte-Pflegeprozess, 2026-07-23): Tests fuer die
Konservativitaets-Warnfunktion `validate_cma_conservative` + die additive
`source_date`-Spalte (Quelle/Datum-Dokumentation, Memory
feedback_conservative_values: "immer der tiefere Wert bei
Renditeerwartungen").

Deckt:
  (a) Warnung wenn eine neue CMA-Version bei einem *_return_bps-Feld
      optimistischer (hoeher) liegt als die vorherige aktuelle Version.
  (b) KEINE Warnung wenn die neue Version konservativer oder gleich ist.
  (c) source_date migriert additiv + idempotent auf einer Alt-DB (Muster:
      tests/test_bootstrap_schema_tenant_id.py).
  (d) Integration in import_cma_csv: conservative_warnings wird pro Zeile
      befuellt, blockiert aber weder Validation noch Apply.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, tenant, users, wealth,
)
from models.allocation import CapitalMarketAssumption
from models.users import User
configure_mappers()

from services.cma_import import (
    _get_current_cma_entry,
    apply_cma_row,
    import_cma_csv,
    validate_cma_conservative,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cma_conservative.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    s = SF()
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


def _make_cma(**overrides) -> CapitalMarketAssumption:
    now = datetime.now(timezone.utc).isoformat()
    defaults: dict = {
        "id": str(uuid.uuid4()),
        "assumption_set_name": "Standard",
        "version": 1,
        "valid_from": "2026-01-01",
        "is_current": 1,
        "created_by": "user-cma",
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return CapitalMarketAssumption(**defaults)


# ============================================================================
# (a) Warnung bei optimistischerer neuer Version
# ============================================================================


def test_warns_when_new_return_higher_than_previous_orm():
    previous = _make_cma(equity_ch_return_bps=500)
    new = _make_cma(version=2, equity_ch_return_bps=650)
    warnings = validate_cma_conservative(new, previous)
    assert len(warnings) == 1
    assert "equity_ch_return_bps" in warnings[0]
    assert "650" in warnings[0] and "500" in warnings[0]


def test_warns_for_each_field_that_regresses():
    previous = _make_cma(equity_ch_return_bps=500, bonds_hy_return_bps=200)
    new = _make_cma(version=2, equity_ch_return_bps=650, bonds_hy_return_bps=250)
    warnings = validate_cma_conservative(new, previous)
    assert len(warnings) == 2
    fields_flagged = {w.split(":")[0] for w in warnings}
    assert fields_flagged == {"equity_ch_return_bps", "bonds_hy_return_bps"}


def test_warns_with_dict_rows_mixed_with_orm():
    previous = _make_cma(equity_intl_return_bps=400)
    new_row = {"equity_intl_return_bps": "550"}  # CSV-Row: String-Wert
    warnings = validate_cma_conservative(new_row, previous)
    assert any("equity_intl_return_bps" in w for w in warnings)


# ============================================================================
# (b) KEINE Warnung wenn konservativ / gleich / keine Vorgaenger-Version
# ============================================================================


def test_no_warning_when_new_return_lower():
    previous = _make_cma(equity_ch_return_bps=650)
    new = _make_cma(version=2, equity_ch_return_bps=500)
    assert validate_cma_conservative(new, previous) == []


def test_no_warning_when_equal():
    previous = _make_cma(equity_ch_return_bps=500)
    new = _make_cma(version=2, equity_ch_return_bps=500)
    assert validate_cma_conservative(new, previous) == []


def test_no_warning_when_no_previous_version():
    new = _make_cma(equity_ch_return_bps=99999)  # waere ausserhalb jeder Plausibilitaet
    assert validate_cma_conservative(new, None) == []


def test_no_warning_when_field_missing_on_either_side():
    previous = _make_cma()  # equity_ch_return_bps bleibt None
    new = _make_cma(version=2, equity_ch_return_bps=500)
    assert validate_cma_conservative(new, previous) == []

    previous2 = _make_cma(equity_ch_return_bps=500)
    new2 = _make_cma(version=2)  # equity_ch_return_bps bleibt None
    assert validate_cma_conservative(new2, previous2) == []


def test_never_raises_and_does_not_mutate_inputs():
    previous = _make_cma(equity_ch_return_bps=500)
    new = _make_cma(version=2, equity_ch_return_bps=650)
    validate_cma_conservative(new, previous)
    # Reines Warnsystem -- Werte duerfen NIE automatisch veraendert werden.
    assert previous.equity_ch_return_bps == 500
    assert new.equity_ch_return_bps == 650


# ============================================================================
# (c) source_date: additive Spalte, Migration idempotent auf Alt-DB
# ============================================================================


def _table_columns(engine, table: str) -> set[str]:
    inspector = inspect(engine)
    if not inspector.has_table(table):
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def _bootstrap_legacy_db(tmp_path, monkeypatch):
    """Bootstrapt eine DB ueber das reale Bootstrap-SQL (5eyes_schema_v4.0_
    FINAL.sql), das `source_date` NICHT enthaelt -- simuliert eine Alt-
    Installation vor Roadmap #51."""
    db_path = tmp_path / "legacy_cma.db"
    schema_file = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"
    import database as db_module
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=schema_file)
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    return test_engine, db_module


def test_source_date_missing_before_migration(tmp_path, monkeypatch):
    test_engine, _ = _bootstrap_legacy_db(tmp_path, monkeypatch)
    cols = _table_columns(test_engine, "capital_market_assumptions")
    assert "source_date" not in cols, "Bootstrap-SQL enthaelt source_date schon -- Test obsolet"
    # source existiert bereits im Bootstrap-SQL (Roadmap #51 ergaenzt nur das
    # fehlende Datum-Feld, nicht die Quelle selbst).
    assert "source" in cols


def test_ensure_runtime_columns_adds_source_date(tmp_path, monkeypatch):
    test_engine, db_module = _bootstrap_legacy_db(tmp_path, monkeypatch)
    db_module.ensure_runtime_columns()
    cols = _table_columns(test_engine, "capital_market_assumptions")
    assert "source_date" in cols


def test_ensure_runtime_columns_source_date_idempotent(tmp_path, monkeypatch):
    test_engine, db_module = _bootstrap_legacy_db(tmp_path, monkeypatch)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # zweite Ausfuehrung darf nicht crashen
    assert "source_date" in _table_columns(test_engine, "capital_market_assumptions")


# ============================================================================
# (d) Integration: import_cma_csv befuellt conservative_warnings
# ============================================================================


def _csv_path(tmp_path, content: str) -> str:
    p = tmp_path / "cma.csv"
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_import_populates_conservative_warnings_on_regression(session, tmp_path):
    row1 = {
        "assumption_set_name": "Regress-Set", "valid_from": "2026-01-01",
        "equity_ch_return_bps": "500",
    }
    apply_cma_row(session, row1, user_id="user-cma")
    session.commit()

    p = _csv_path(tmp_path, (
        "assumption_set_name,valid_from,equity_ch_return_bps\n"
        "Regress-Set,2026-07-01,650\n"
    ))
    result = import_cma_csv(session, p, user_id="user-cma", dry_run=True)
    assert len(result.rows) == 1
    row_result = result.rows[0]
    assert not row_result.has_errors, "Warnung darf keine Validation-Errors erzeugen"
    assert any("equity_ch_return_bps" in w for w in row_result.conservative_warnings)


def test_import_no_conservative_warning_when_lower_or_new_set(session, tmp_path):
    row1 = {
        "assumption_set_name": "Conservative-Set", "valid_from": "2026-01-01",
        "equity_ch_return_bps": "650",
    }
    apply_cma_row(session, row1, user_id="user-cma")
    session.commit()

    p = _csv_path(tmp_path, (
        "assumption_set_name,valid_from,equity_ch_return_bps\n"
        "Conservative-Set,2026-07-01,500\n"
        "Brand-New-Set,2026-07-01,999\n"
    ))
    result = import_cma_csv(session, p, user_id="user-cma", dry_run=True)
    assert len(result.rows) == 2
    for row_result in result.rows:
        assert row_result.conservative_warnings == []


def test_import_apply_writes_source_date(session, tmp_path):
    p = _csv_path(tmp_path, (
        "assumption_set_name,valid_from,source,source_date,equity_ch_return_bps\n"
        "SourceDated,2026-07-01,Pictet CMA 2026Q3,2026-06-15,500\n"
    ))
    result = import_cma_csv(session, p, user_id="user-cma", dry_run=False)
    assert not result.has_errors
    assert result.applied_count == 1
    entry = session.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.assumption_set_name == "SourceDated"
    ).one()
    assert entry.source == "Pictet CMA 2026Q3"
    assert entry.source_date == "2026-06-15"


def test_get_current_cma_entry_returns_none_when_absent(session):
    assert _get_current_cma_entry(session, "Does-Not-Exist") is None


def test_get_current_cma_entry_returns_latest_current(session):
    row1 = {"assumption_set_name": "Latest-Set", "valid_from": "2026-01-01", "equity_ch_return_bps": "500"}
    apply_cma_row(session, row1, user_id="user-cma")
    session.commit()
    row2 = {"assumption_set_name": "Latest-Set", "valid_from": "2026-07-01", "equity_ch_return_bps": "480"}
    apply_cma_row(session, row2, user_id="user-cma")
    session.commit()

    current = _get_current_cma_entry(session, "Latest-Set")
    assert current is not None
    assert current.version == 2
    assert current.equity_ch_return_bps == 480
