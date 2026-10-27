"""MONEY-COLUMN-WIDTH-001: Betrags-/Mengenspalten muessen 64 Bit breit sein.

Befund
------
Alle Rappen-Betraege waren im ORM und in Alembic als ``Integer`` deklariert.
Auf SQLite ist INTEGER ohnehin 64 Bit; auf PostgreSQL ist ``integer`` aber
32 Bit -- Obergrenze 2'147'483'647 Rappen = CHF 21,47 Mio. Ein Vermoegen,
Ziel, eine Hypothek oder Immobilie darueber war auf Postgres nicht
speicherbar (``NumericValueOutOfRange``), auf SQLite schon:
Plattformdivergenz.

Dieser Test ist die Ratsche auf der ORM-Seite (laeuft in jedem CI-Job ohne
Postgres). Die Gegenprobe auf echtem Postgres -- jede Rappen-Spalte nach
``alembic upgrade head`` ist ``bigint`` und CHF 50 Mio. sind speicherbar --
steht in ``tests/test_postgres_money_bigint_live.py``.
"""
from __future__ import annotations

import re
import sys
from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from pydantic import ValidationError
from sqlalchemy import BigInteger, Integer

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

MIGRATION_REVISION = "f6b1d4a8c2e7"
MIGRATION_DOWN_REVISION = "a7c4e9b2d1f3"

# Rappen-Betraege und milli-skalierte Groessen (Stueckzahl, Zielfunktionswert
# mit 64-Bit-Kappung in der Engine). Basispunkte, Jahre, Flags und Zaehler
# sind bewusst NICHT erfasst -- sie bleiben klein.
_WIDE_COLUMN_NAME = re.compile(r"_(rappen|milli)$")


def _alembic_config(database_url: str, *, output_buffer=None) -> AlembicConfig:
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"), output_buffer=output_buffer)
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _orm_metadata():
    """Alle Modellmodule importieren -- sonst fehlen Tabellen im Metadata.

    ``models/__init__.py`` registriert nur einen Teil; ohne vollstaendigen
    Import waere die Ratsche je nach Testreihenfolge zu mild.
    """
    import importlib  # noqa: PLC0415
    import pkgutil  # noqa: PLC0415

    import models  # noqa: PLC0415
    from database import Base  # noqa: PLC0415

    for module in pkgutil.iter_modules(models.__path__):
        importlib.import_module(f"models.{module.name}")
    return Base.metadata


def _wide_orm_columns() -> dict[tuple[str, str], object]:
    found = {}
    for table_name, table in _orm_metadata().tables.items():
        for column in table.columns:
            if _WIDE_COLUMN_NAME.search(column.name) and isinstance(column.type, Integer):
                found[(table_name, column.name)] = column.type
    return found


def _migration_module():
    script = ScriptDirectory.from_config(_alembic_config("sqlite://"))
    return script.get_revision(MIGRATION_REVISION).module


def test_wide_column_scan_is_not_trivially_empty():
    """Sanity-Anker: ohne Treffer waere die Ratsche unten wertlos."""
    columns = _wide_orm_columns()
    assert ("wealth_positions", "current_value_rappen") in columns
    assert ("goals", "target_amount_rappen") in columns
    assert len(columns) >= 25, sorted(columns)


def test_every_orm_rappen_and_milli_column_is_biginteger():
    narrow = sorted(
        f"{table}.{column}"
        for (table, column), column_type in _wide_orm_columns().items()
        if not isinstance(column_type, BigInteger)
    )
    assert not narrow, (
        "Diese Betrags-/Mengenspalten sind im ORM nur `Integer` und damit auf "
        f"PostgreSQL 32 Bit (max. CHF 21,47 Mio.): {narrow}. "
        "Als `BigInteger` deklarieren und per Alembic auf BIGINT verbreitern."
    )


def test_migration_widens_exactly_known_orm_columns():
    """Die Migration darf keine Spalte nennen, die es im ORM nicht gibt."""
    widened = set(_migration_module().MONEY_COLUMNS)
    orm_columns = set(_wide_orm_columns())
    assert widened, "Migration nennt keine Spalten"
    unknown = sorted(widened - orm_columns)
    assert not unknown, f"Migration nennt unbekannte Spalten: {unknown}"
    missing = sorted(orm_columns - widened)
    assert not missing, (
        f"ORM-Spalten ohne Verbreiterung auf Postgres: {missing}. Fuer neue "
        "Spalten reicht es, sie direkt als BigInteger anzulegen -- dann diese "
        "Liste hier um die neue Revision ergaenzen."
    )


def test_migration_sits_on_the_expected_chain():
    script = ScriptDirectory.from_config(_alembic_config("sqlite://"))
    revision = script.get_revision(MIGRATION_REVISION)
    assert revision is not None
    assert revision.down_revision == MIGRATION_DOWN_REVISION
    ancestors = {rev.revision for rev in script.walk_revisions(base="base", head=MIGRATION_REVISION)}
    assert MIGRATION_DOWN_REVISION in ancestors


def test_migration_is_noop_on_sqlite(tmp_path):
    """SQLite ist bereits 64 Bit: upgrade/downgrade duerfen nichts anfassen."""
    db_url = f"sqlite:///{tmp_path / 'bigint_chain.db'}"
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, MIGRATION_REVISION)
    command.downgrade(cfg, MIGRATION_DOWN_REVISION)
    command.upgrade(cfg, MIGRATION_REVISION)


def test_postgres_ddl_alters_every_money_column_and_recreates_views():
    output = StringIO()
    command.upgrade(
        _alembic_config(
            "postgresql://migration-test:unused@localhost/unused",
            output_buffer=output,
        ),
        f"{MIGRATION_DOWN_REVISION}:{MIGRATION_REVISION}",
        sql=True,
    )
    ddl = output.getvalue()
    for table, column in _migration_module().MONEY_COLUMNS:
        assert f"ALTER TABLE {table} ALTER COLUMN {column} TYPE BIGINT" in ddl, (table, column)
    # Die Summen-Views haengen an den Spalten -- ohne DROP scheitert ALTER.
    for view in ("v_client_wealth_summary", "v_client_cashflow_surplus"):
        assert f"DROP VIEW IF EXISTS {view}" in ddl
        assert f"CREATE VIEW {view}" in ddl
    assert ddl.index("DROP VIEW IF EXISTS v_client_wealth_summary") < ddl.index(
        "ALTER TABLE wealth_positions ALTER COLUMN current_value_rappen TYPE BIGINT"
    )


# ---------------------------------------------------------------------------
# API-Grenze: ein Python-int > 2^63-1 ist auf KEINER Plattform speicherbar
# (SQLite: OverflowError, Postgres: NumericValueOutOfRange) -> heute HTTP 500.
# ---------------------------------------------------------------------------
_TOO_LARGE = 2**63
_LARGEST = 2**63 - 1


def _cashflow(**overrides):
    payload = {"cashflow_type": "Income", "label": "x", "amount_rappen": 1}
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("field", ["amount_rappen", "gross_amount_rappen", "tax_amount_rappen"])
def test_cashflow_amount_beyond_64_bit_is_rejected(field):
    from schemas.wealth import CashflowCreate, CashflowUpdate  # noqa: PLC0415

    with pytest.raises(ValidationError):
        CashflowCreate(**_cashflow(**{field: _TOO_LARGE}))
    with pytest.raises(ValidationError):
        CashflowUpdate(**{field: _TOO_LARGE})
    CashflowCreate(**_cashflow(**{field: _LARGEST}))


def test_wealth_inflow_amount_beyond_64_bit_is_rejected():
    from schemas.wealth import WealthInflowCreate, WealthInflowUpdate  # noqa: PLC0415

    base = {"label": "Erbe", "source_type": "Erbschaft", "expected_year": 2030}
    with pytest.raises(ValidationError):
        WealthInflowCreate(**base, amount_rappen=_TOO_LARGE)
    with pytest.raises(ValidationError):
        WealthInflowUpdate(amount_rappen=_TOO_LARGE)
    WealthInflowCreate(**base, amount_rappen=_LARGEST)


@pytest.mark.parametrize("field", ["units_milli", "market_value_rappen", "avg_cost_price_rappen"])
def test_recommendation_holding_beyond_64_bit_is_rejected(field):
    from schemas.review import RecommendationHoldingUpsert  # noqa: PLC0415

    base = {"market_value_rappen": 1}
    with pytest.raises(ValidationError):
        RecommendationHoldingUpsert(**{**base, field: _TOO_LARGE})
    RecommendationHoldingUpsert(**{**base, field: _LARGEST})


def test_recommendation_position_amount_beyond_64_bit_is_rejected():
    from schemas.review import RecommendationPositionCreate  # noqa: PLC0415

    base = {"product_id": "p1", "target_weight_bps": 100}
    with pytest.raises(ValidationError):
        RecommendationPositionCreate(**base, target_amount_rappen=_TOO_LARGE)
    RecommendationPositionCreate(**base, target_amount_rappen=_LARGEST)
