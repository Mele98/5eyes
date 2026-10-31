"""Die drei Reporting-Views auch auf dem Alembic-Pfad anlegen.

Befund 2026-10-12 (Ende-zu-Ende-Durchlauf Mock-Mandant "Thierry Gössi").
`v_client_wealth_summary`, `v_client_cashflow_surplus` und
`v_active_triggers` existierten AUSSCHLIESSLICH in
`ares_schema.sql`. Views sind nicht Teil des ORM-Metadata, und
Alembic enthielt keine einzige `CREATE VIEW`.

Folge, aus `database.py::_create_or_migrate_schema()` abgelesen:

    SQLite   -> init_db() faehrt zuerst bootstrap_sqlite_schema() (die
                SQL-Datei, also MIT Views), danach create_all(). Views da.
    Postgres -> ausschliesslich `alembic upgrade head`. KEINE Views.

Drei Endpunkte lesen sie per rohem SQL, ohne Rueckfall:

    routers/clients.py   GET /clients/{id}/wealth-summary
                         GET /clients/{id}/cashflow-summary
    routers/review.py    Dashboard-Zusammenfassung + aktive Trigger
                         (zwei Abfragen auf v_active_triggers)

Auf Postgres -- dem Ziel fuer die gehosteten Tiers 2/3 -- laufen diese
Endpunkte damit in `UndefinedTable` und antworten HTTP 500. Kein Test hat
das bemerkt, weil die SQLite-Tests die Views ueber den Bootstrap bekommen
und die Postgres-Tests diese Endpunkte nicht anfassen.

KEINE KOPIE: zwei Views sind so, wie sie in der SQL-Datei stehen, unter
Postgres UNGUELTIG
-------------------------------------------------------------------------
Beide Summen-Views gruppieren nur nach `c.id`, selektieren aber zusaetzlich
`c.first_name`, `c.last_name` und (bei der Vermoegens-View)
`c.client_classification`. SQLite erlaubt das als Erweiterung; Postgres
verlangt nach dem SQL-Standard, dass jede nicht aggregierte Spalte in
GROUP BY steht, und wirft sonst

    column "c.first_name" must appear in the GROUP BY clause

Die GROUP-BY-Listen sind hier deshalb vollstaendig. Das ist keine
Verhaltensaenderung: `clients.id` ist Primaerschluessel, die
hinzugefuegten Spalten sind davon funktional abhaengig, also bleiben
Gruppierung und Ergebnis identisch.

`CREATE VIEW IF NOT EXISTS` ist ebenfalls SQLite-Syntax. Postgres kennt
`CREATE OR REPLACE VIEW`; die Migration unterscheidet die Dialekte,
damit sie auch gegen SQLite laufen kann (der Alembic-Pfad ist heute
Postgres-only, aber die Bootstrap-Tests fahren Migrationen auch gegen
SQLite).

Revision ID: a3c7e9d14b60
Revises: f4a81c6b2e37
Create Date: 2026-10-12
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a3c7e9d14b60"
down_revision: Union[str, Sequence[str], None] = "f4a81c6b2e37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_VIEW_NAMES = (
    "v_client_wealth_summary",
    "v_client_cashflow_surplus",
    "v_active_triggers",
)

_WEALTH_SUMMARY_BODY = """
SELECT
    c.id AS client_id,
    c.first_name || ' ' || c.last_name AS client_name,
    c.client_classification,
    COALESCE(SUM(CASE WHEN wp.assignment != 'Verbindlichkeit' THEN wp.current_value_rappen ELSE 0 END),0) AS gross_wealth_rappen,
    COALESCE(SUM(CASE WHEN wp.assignment = 'Verbindlichkeit' THEN wp.current_value_rappen ELSE 0 END),0) AS liabilities_rappen,
    COALESCE(SUM(CASE WHEN wp.assignment != 'Verbindlichkeit' THEN wp.current_value_rappen ELSE 0 END),0)
    - COALESCE(SUM(CASE WHEN wp.assignment = 'Verbindlichkeit' THEN wp.current_value_rappen ELSE 0 END),0) AS net_worth_rappen,
    COALESCE(SUM(CASE WHEN wp.assignment = 'Beratungsvermögen' THEN wp.current_value_rappen ELSE 0 END),0) AS advisory_wealth_rappen
FROM clients c
LEFT JOIN wealth_positions wp ON wp.client_id = c.id AND wp.deleted_at IS NULL AND wp.is_active = 1
WHERE c.deleted_at IS NULL
GROUP BY c.id, c.first_name, c.last_name, c.client_classification
"""

_CASHFLOW_SURPLUS_BODY = """
SELECT
    c.id AS client_id,
    c.first_name || ' ' || c.last_name AS client_name,
    COALESCE(SUM(CASE WHEN cf.cashflow_type = 'Income' THEN cf.amount_rappen ELSE 0 END),0) AS total_income_rappen,
    COALESCE(SUM(CASE WHEN cf.cashflow_type = 'Expense' THEN cf.amount_rappen ELSE 0 END),0) AS total_expense_rappen,
    COALESCE(SUM(CASE WHEN cf.cashflow_type = 'Income' THEN cf.amount_rappen ELSE 0 END),0)
    - COALESCE(SUM(CASE WHEN cf.cashflow_type = 'Expense' THEN cf.amount_rappen ELSE 0 END),0) AS surplus_rappen
FROM clients c
LEFT JOIN cashflows cf ON cf.client_id = c.id AND cf.deleted_at IS NULL AND cf.is_active = 1
WHERE c.deleted_at IS NULL
GROUP BY c.id, c.first_name, c.last_name
"""

# Kein GROUP BY, keine Anpassung noetig -- `rt.*` plus zwei Joins ist
# portabel.
_ACTIVE_TRIGGERS_BODY = """
SELECT rt.*, c.first_name || ' ' || c.last_name AS client_name, m.mandate_number
FROM review_triggers rt
JOIN mandates m ON m.id = rt.mandate_id
JOIN clients c ON c.id = m.client_id
WHERE rt.status IN ('Aktiv','Ausgelöst') AND rt.deleted_at IS NULL
  AND m.deleted_at IS NULL AND c.deleted_at IS NULL
ORDER BY CASE rt.status WHEN 'Ausgelöst' THEN 0 ELSE 1 END, rt.next_due_at
"""

_VIEW_BODIES = {
    "v_client_wealth_summary": _WEALTH_SUMMARY_BODY,
    "v_client_cashflow_surplus": _CASHFLOW_SURPLUS_BODY,
    "v_active_triggers": _ACTIVE_TRIGGERS_BODY,
}


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name.startswith("postgresql")
    for name in _VIEW_NAMES:
        body = _VIEW_BODIES[name].strip()
        if is_postgres:
            # Idempotent und ohne die SQLite-Sonderform. `OR REPLACE`
            # erlaubt es, eine spaetere Korrektur derselben View ueber eine
            # Folgerevision einzuspielen.
            op.execute(f"CREATE OR REPLACE VIEW {name} AS {body}")
        else:
            op.execute(f"CREATE VIEW IF NOT EXISTS {name} AS {body}")


def downgrade() -> None:
    for name in reversed(_VIEW_NAMES):
        op.execute(f"DROP VIEW IF EXISTS {name}")
