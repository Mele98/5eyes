"""`alembic upgrade head` gegen ECHTES PostgreSQL ausfuehren.

Warum das fehlte -- und warum der Befund deshalb ueberlebt hat
--------------------------------------------------------------
Befund 2026-10-12 (E2E-Durchlauf Mock-Mandant "Thierry Goessi"): die drei
Reporting-Views standen ausschliesslich in `5eyes_schema_v4.0_FINAL.sql`;
Alembic enthielt keine einzige `CREATE VIEW`. Auf Postgres laeuft
AUSSCHLIESSLICH Alembic (`database.py::_create_or_migrate_schema()`), also
fehlten sie dort -- waehrend drei Endpunkte sie per rohem SQL ohne Rueckfall
lesen.

Dass niemand das bemerkte, hat einen strukturellen Grund: die Migrationen
wurden in KEINEM CI-Job gegen echtes Postgres AUSGEFUEHRT.

    tests/test_postgres_bootstrap_migrations.py  faehrt `upgrade head`
        gegen SQLite und erzeugt die Postgres-DDL nur OFFLINE als Text
        (`sql=True`). Beides ist wertvoll, aber keines fuehrt die
        Anweisungen auf einem Postgres aus.
    tests/test_postgres_rls_*.py                 nutzen
        `Base.metadata.create_all()` bzw. ein handgebautes Mini-Schema --
        also gar keine Migrationen.

Eine Anweisung, die SQLite akzeptiert und Postgres ablehnt, konnte damit
durch die gesamte Suite. Genau diese Klasse liegt hier vor: beide
Summen-Views gruppierten nur nach `c.id`, selektierten aber
`c.first_name`/`c.last_name`. SQLite erlaubt das; Postgres antwortet

    column "c.first_name" must appear in the GROUP BY clause

Dieser Test schliesst die Luecke: er faehrt die VOLLSTAENDIGE
Migrationskette auf einem echten Postgres in ein eigenes Schema und fragt
jede View danach auch AB -- erst die Abfrage beweist, dass die Definition
gueltig ist.

Ohne `POSTGRES_TEST_DATABASE_URL` wird uebersprungen (gleiches Muster wie
die uebrigen Postgres-Tests); in CI setzt der `postgres-rls`-Job sie.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect, text

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; ohne echtes Postgres nicht pruefbar",
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

_EXPECTED_VIEWS = (
    "v_client_wealth_summary",
    "v_client_cashflow_surplus",
    "v_active_triggers",
)


def _qi(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


@pytest.fixture(scope="module")
def migrated_postgres_schema():
    """Ein frisches Schema mit der vollstaendigen Migrationskette darin.

    Eigenes Schema je Lauf, damit parallele Jobs sich nicht in die Quere
    kommen -- gleiche Isolation wie in tests/test_postgres_rls_adversarial.py.
    Der `search_path` wird ueber die Verbindungsoptionen gesetzt, damit
    Alembic (das seine eigenen Verbindungen oeffnet) im richtigen Schema
    arbeitet.
    """
    pytest.importorskip("psycopg")
    assert POSTGRES_URL is not None

    schema = f"mig_{uuid.uuid4().hex[:12]}"
    admin_engine = create_engine(POSTGRES_URL, future=True)
    with admin_engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))

    separator = "&" if "?" in POSTGRES_URL else "?"
    scoped_url = f"{POSTGRES_URL}{separator}options=-csearch_path%3D{schema}"

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", scoped_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))

    try:
        command.upgrade(cfg, "head")
        yield {"schema": schema, "url": scoped_url, "config": cfg}
    finally:
        with admin_engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
        admin_engine.dispose()


def test_migration_chain_applies_cleanly_on_postgres(migrated_postgres_schema):
    """Die Kette selbst -- der Fixture-Aufbau wuerde sonst still scheitern.

    Ein eigener Test dafuer, damit ein Fehler in `upgrade head` als
    EIGENER Fehlschlag erscheint und nicht als Fehler in einem der
    View-Tests darunter.
    """
    engine = create_engine(migrated_postgres_schema["url"], future=True)
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()
    assert version, "alembic_version ist leer -- die Kette lief nicht durch"


def test_every_reporting_view_exists_on_postgres(migrated_postgres_schema):
    engine = create_engine(migrated_postgres_schema["url"], future=True)
    try:
        existing = set(inspect(engine).get_view_names(schema=migrated_postgres_schema["schema"]))
    finally:
        engine.dispose()
    missing = set(_EXPECTED_VIEWS) - existing
    assert not missing, (
        f"Nach `alembic upgrade head` fehlen auf Postgres: {sorted(missing)}. "
        "Jede fehlende View ist ein HTTP 500 in jedem Endpunkt, der sie liest."
    )


@pytest.mark.parametrize("view_name", _EXPECTED_VIEWS)
def test_reporting_view_is_queryable_on_postgres(migrated_postgres_schema, view_name):
    """Die eigentliche Pruefung: die View muss ABFRAGBAR sein.

    Postgres validiert eine View-Definition bereits bei `CREATE`, aber erst
    eine Abfrage zeigt, dass Spalten und Gruppierung zusammenpassen und die
    View nicht bloss als Huelle existiert. Hier waere die unveraenderte
    SQLite-Definition gescheitert ("column must appear in the GROUP BY
    clause").
    """
    engine = create_engine(migrated_postgres_schema["url"], future=True)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"SELECT * FROM {_qi(view_name)} LIMIT 1")).fetchall()
    finally:
        engine.dispose()
    # Leer ist in Ordnung -- ein frisches Schema hat keine Mandanten. Die
    # Aussage ist, dass die Abfrage ueberhaupt durchlaeuft.
    assert rows == [] or rows


def test_wealth_summary_aggregates_correctly_on_postgres(migrated_postgres_schema):
    """Mit Daten: die Gruppierung muss auch RECHNEN, nicht nur laufen.

    Die erweiterte GROUP-BY-Liste darf das Ergebnis nicht veraendern. Sie
    fuegt nur Spalten hinzu, die von `clients.id` (Primaerschluessel)
    funktional abhaengen -- die Gruppen bleiben dieselben. Dieser Test
    belegt das an Zahlen statt es bloss zu behaupten: zwei Positionen auf
    EINEM Kunden muessen EINE Zeile ergeben, nicht zwei.
    """
    engine = create_engine(migrated_postgres_schema["url"], future=True)
    now = "2026-10-12T00:00:00Z"
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO clients (id, client_number, first_name, last_name,"
                    " created_at, updated_at)"
                    " VALUES (:id, :num, :first, :last, :now, :now)"
                ),
                {"id": "pg-c1", "num": "PG-1", "first": "Thierry", "last": "Goessi", "now": now},
            )
            for position_id, assignment, value in (
                ("pg-w1", "Beratungsvermögen", 450_000_00),
                ("pg-w2", "Beratungsvermögen", 80_000_00),
                ("pg-w3", "Verbindlichkeit", 600_000_00),
            ):
                conn.execute(
                    text(
                        "INSERT INTO wealth_positions (id, client_id, label, position_type,"
                        " assignment, current_value_rappen, is_active, created_at, updated_at)"
                        " VALUES (:id, :client, :label, :ptype, :assignment, :value, 1,"
                        " :now, :now)"
                    ),
                    {
                        "id": position_id, "client": "pg-c1", "label": position_id,
                        "ptype": "Depot", "assignment": assignment, "value": value,
                        "now": now,
                    },
                )

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT client_name, gross_wealth_rappen, liabilities_rappen,"
                    " net_worth_rappen, advisory_wealth_rappen"
                    " FROM v_client_wealth_summary WHERE client_id = 'pg-c1'"
                )
            ).fetchall()
    finally:
        engine.dispose()

    assert len(rows) == 1, f"Gruppierung zerfaellt in mehrere Zeilen: {rows}"
    name, gross, liabilities, net, advisory = rows[0]
    assert name == "Thierry Goessi"
    assert gross == 530_000_00
    assert liabilities == 600_000_00
    assert net == -70_000_00
    assert advisory == 530_000_00
