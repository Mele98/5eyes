"""Sieben ORM-Spalten nachziehen, die der Alembic-Pfad nie angelegt hat.

Gefunden 2026-10-12 beim Gruenziehen von `test_postgres_alembic_views_live.py`
-- der neue Test seedete einen `User` ueber das ORM und bekam auf echtem
PostgreSQL:

    psycopg.errors.UndefinedColumn: column "calendar_feed_token_hash"
    of relation "users" does not exist

Danach systematisch gemessen: ORM-Metadata gegen `alembic upgrade head`
verglichen (65 Tabellen). Keine Tabelle fehlt, aber SIEBEN Spalten in VIER
Kerntabellen:

    clients             erased_at, erasure_reason
    contract_documents  content_hash, pdf_base64
    mandates            tax_estimate_in_cashflow_enabled
    users               calendar_feed_token_hash,
                        calendar_feed_token_created_at

Warum das auf SQLite nie auffiel
--------------------------------
Die Installationspfade sind verschieden (siehe
`database.py::_create_or_migrate_schema()`):

    SQLite   -> Bootstrap-SQL, dann `create_all()` (legt ORM-Spalten an),
                dann `_run_sqlite_legacy_schema_maintenance()` mit
                `ensure_column(...)`. Fuenf der sieben Spalten stehen genau
                dort (database.py), die beiden `contract_documents`-Spalten
                ebenfalls. SQLite ist also vollstaendig.
    Postgres -> AUSSCHLIESSLICH `alembic upgrade head`. Dort stand keine
                einzige dieser Spalten.

Die Folge auf Postgres ist nicht eine fehlende Nebenspalte: SQLAlchemy
generiert in JEDEM ORM-Statement die vollstaendige Spaltenliste. Ein
`SELECT` oder `INSERT` auf `users`, `clients`, `mandates` oder
`contract_documents` scheitert damit mit `UndefinedColumn` -- also praktisch
jede Anfrage der Anwendung, Anmeldung eingeschlossen.

Zwei der Spalten sind zudem inhaltlich schwer: `contract_documents.
pdf_base64` haelt das archivierte Dokument selbst und `content_hash` dessen
Integritaetsnachweis; `clients.erased_at` / `erasure_reason` sind der
Loeschnachweis nach DSG Art. 32.

Additiv und sicher
------------------
Alle sieben sind im ORM `nullable=True`. `tax_estimate_in_cashflow_enabled`
traegt einen PYTHON-seitigen Default (0), keinen Server-Default -- der wird
hier bewusst NICHT als `server_default` nachgezogen: das waere eine
Verhaltensaenderung gegenueber SQLite, wo `ensure_column` die Spalte
ebenfalls ohne Server-Default anlegt und bestehende Zeilen NULL behalten.
Gleiche Semantik auf beiden Pfaden ist hier wichtiger als ein huebscherer
Default.

Revision ID: b8f3d2a71c45
Revises: a3c7e9d14b60
Create Date: 2026-10-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8f3d2a71c45"
down_revision: Union[str, Sequence[str], None] = "a3c7e9d14b60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (Tabelle, Spalte, Typ) -- Typen aus dem ORM uebernommen, nicht geraten.
_MISSING_COLUMNS: tuple[tuple[str, str, object], ...] = (
    ("clients", "erased_at", sa.String()),
    ("clients", "erasure_reason", sa.String()),
    ("contract_documents", "content_hash", sa.String()),
    ("contract_documents", "pdf_base64", sa.String()),
    ("mandates", "tax_estimate_in_cashflow_enabled", sa.Integer()),
    ("users", "calendar_feed_token_hash", sa.String()),
    ("users", "calendar_feed_token_created_at", sa.String()),
)


def _existing_columns(table_name: str) -> set[str] | None:
    """Vorhandene Spalten -- oder None, wenn nicht introspizierbar.

    Im Offline-Modus (`alembic upgrade --sql`) ist der Bind eine
    `MockConnection`: es gibt keine Datenbank, die man befragen koennte, und
    `sa.inspect()` wirft `NoInspectionAvailable`. Zwei bestehende
    Vertragstests erzeugen die Postgres-DDL genau so. Dort wird die Spalte
    unbedingt ausgegeben -- das ist auch richtig: ein SQL-Skript soll die
    Anweisung ENTHALTEN, nicht sie anhand eines Zustands weglassen, den es
    beim Erzeugen nicht kennt.
    """
    context = op.get_context()
    if getattr(context, "as_sql", False):
        return None
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def upgrade() -> None:
    # Idempotent: auf einer DB, die eine dieser Spalten schon hat (etwa ein
    # SQLite-Bestand, auf dem `ensure_column` sie bereits nachgezogen hat und
    # auf dem spaeter doch Alembic laeuft), darf die Migration nicht brechen.
    for table_name, column_name, column_type in _MISSING_COLUMNS:
        existing = _existing_columns(table_name)
        if existing is not None and column_name in existing:
            continue
        op.add_column(table_name, sa.Column(column_name, column_type, nullable=True))


def downgrade() -> None:
    for table_name, column_name, _column_type in reversed(_MISSING_COLUMNS):
        existing = _existing_columns(table_name)
        if existing is not None and column_name not in existing:
            continue
        op.drop_column(table_name, column_name)
