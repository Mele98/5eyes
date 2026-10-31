"""MONEY-COLUMN-WIDTH-001 live auf PostgreSQL.

Faehrt die vollstaendige Alembic-Kette in ein eigenes Schema und belegt:

* jede ``*_rappen``-/``*_milli``-Spalte ist danach ``bigint`` (Ratsche fuer
  kuenftige Migrationen -- eine neue Betragsspalte als ``Integer`` faellt hier
  auf);
* ein Vermoegen von CHF 50 Mio. (5'000'000'000 Rappen) ist speicherbar und
  kommt unveraendert zurueck -- vorher ``NumericValueOutOfRange``, weil
  ``integer`` auf Postgres bei 2'147'483'647 Rappen (CHF 21,47 Mio.) endet;
* die Summen-Views liefern weiterhin ganze Zahlen (``bigint``) und nicht
  ``numeric``, das ``SUM(bigint)`` ohne Cast ergaebe.

Ohne ``POSTGRES_TEST_DATABASE_URL`` wird uebersprungen; in CI setzt der Job
"Postgres RLS Adversarial Tests" die Variable.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; ohne echtes Postgres nicht pruefbar",
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

NOW = "2026-10-26T00:00:00Z"
FIFTY_MILLION_CHF_RAPPEN = 50_000_000 * 100
INT32_MAX = 2_147_483_647


def _qi(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


@pytest.fixture(scope="module")
def pg_head():
    pytest.importorskip("psycopg")
    from alembic import command  # noqa: PLC0415
    from alembic.config import Config as AlembicConfig  # noqa: PLC0415

    assert POSTGRES_URL is not None
    schema = f"money_{uuid.uuid4().hex[:12]}"
    admin_engine = create_engine(POSTGRES_URL, future=True)
    with admin_engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    separator = "&" if "?" in POSTGRES_URL else "?"
    scoped_url = f"{POSTGRES_URL}{separator}options=-csearch_path%3D{schema}"
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", scoped_url.replace("%", "%%"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    try:
        command.upgrade(cfg, "head")
        engine = create_engine(scoped_url, future=True)
        try:
            with engine.connect() as conn:
                landed = conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.tables"
                        " WHERE table_schema = :schema AND table_name = 'alembic_version'"
                    ),
                    {"schema": schema},
                ).scalar()
            assert landed == 1, f"Migrationen nicht im Testschema {schema} gelandet"
            yield {"schema": schema, "engine": engine}
        finally:
            engine.dispose()
    finally:
        with admin_engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
        admin_engine.dispose()


def test_every_rappen_and_milli_column_is_bigint_on_postgres(pg_head):
    with pg_head["engine"].connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.table_name, c.column_name, c.data_type"
                " FROM information_schema.columns c"
                " JOIN information_schema.tables t"
                "   ON t.table_schema = c.table_schema AND t.table_name = c.table_name"
                " WHERE c.table_schema = :schema AND t.table_type = 'BASE TABLE'"
                "   AND (c.column_name LIKE '%\\_rappen' OR c.column_name LIKE '%\\_milli')"
            ),
            {"schema": pg_head["schema"]},
        ).fetchall()
    assert len(rows) >= 25, f"Zu wenige Betragsspalten gefunden -- Scan defekt? {rows}"
    narrow = sorted(f"{table}.{column} ({dtype})" for table, column, dtype in rows if dtype != "bigint")
    assert not narrow, (
        "Diese Betragsspalten sind auf PostgreSQL nicht bigint und laufen bei "
        f"CHF 21,47 Mio. ueber: {narrow}"
    )


def test_fifty_million_chf_round_trips_on_postgres(pg_head):
    from sqlalchemy.orm import sessionmaker  # noqa: PLC0415

    from models.clients import Client  # noqa: PLC0415
    from models.tenant import Tenant  # noqa: PLC0415
    from models.users import User  # noqa: PLC0415
    from models.wealth import Cashflow, WealthPosition  # noqa: PLC0415

    assert FIFTY_MILLION_CHF_RAPPEN > INT32_MAX
    engine = pg_head["engine"]
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        session.add(Tenant(id="mb-t1", display_name="MB", slug="mb-t1", created_at=NOW, updated_at=NOW))
        session.flush()
        session.add(User(
            id="mb-adv", username="mb-advisor", password_hash="x",
            full_name="Beraterin Test", tenant_id="mb-t1", created_at=NOW, updated_at=NOW,
        ))
        session.add(Client(
            id="mb-c1", client_number="MB-1", first_name="Test", last_name="Gross",
            advisor_id="mb-adv", tenant_id="mb-t1", created_at=NOW, updated_at=NOW,
        ))
        session.add(WealthPosition(
            id="mb-w1", client_id="mb-c1", label="Depot gross", position_type="Depot",
            assignment="Beratungsvermögen", current_value_rappen=FIFTY_MILLION_CHF_RAPPEN,
            created_at=NOW, updated_at=NOW,
        ))
        session.add(Cashflow(
            id="mb-cf1", client_id="mb-c1", cashflow_type="Income", label="Verkauf",
            amount_rappen=FIFTY_MILLION_CHF_RAPPEN, created_at=NOW, updated_at=NOW,
        ))
        session.commit()

    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT current_value_rappen FROM wealth_positions WHERE id = 'mb-w1'")
        ).scalar()
        summary = conn.execute(
            text(
                "SELECT gross_wealth_rappen, net_worth_rappen, advisory_wealth_rappen"
                " FROM v_client_wealth_summary WHERE client_id = 'mb-c1'"
            )
        ).one()
        surplus = conn.execute(
            text("SELECT surplus_rappen FROM v_client_cashflow_surplus WHERE client_id = 'mb-c1'")
        ).scalar()
    assert stored == FIFTY_MILLION_CHF_RAPPEN
    assert tuple(summary) == (FIFTY_MILLION_CHF_RAPPEN,) * 3
    assert surplus == FIFTY_MILLION_CHF_RAPPEN
    # Typ bleibt ganzzahlig (bigint -> int), nicht numeric -> Decimal.
    assert all(type(value) is int for value in (*summary, surplus)), [type(v) for v in (*summary, surplus)]
