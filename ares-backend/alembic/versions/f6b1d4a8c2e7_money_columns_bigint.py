"""Betrags- und Mengenspalten auf PostgreSQL auf BIGINT verbreitern.

MONEY-COLUMN-WIDTH-001: Rappen-Betraege waren als ``Integer`` deklariert. Auf
PostgreSQL ist ``integer`` 32 Bit -- Obergrenze 2'147'483'647 Rappen =
CHF 21,47 Mio. Vermoegen, Ziele, Hypotheken oder Immobilien darueber liefen
in ``NumericValueOutOfRange``; auf SQLite (INTEGER = 64 Bit) gingen sie durch.

Upgrade (nur PostgreSQL):

1. Die beiden Summen-Views lesen ``wealth_positions.current_value_rappen``
   und ``cashflows.amount_rappen``; Postgres verweigert ``ALTER COLUMN ...
   TYPE`` an Spalten, an denen eine View haengt. Sie werden vorher entfernt.
2. ``ALTER COLUMN ... TYPE BIGINT`` fuer jede Spalte in ``MONEY_COLUMNS``.
   integer -> bigint ist verlustfrei; ein erneuter Lauf auf bereits
   verbreiterten Spalten aendert nichts.
3. Die Views werden neu angelegt. ``SUM(bigint)`` ergaebe auf Postgres
   ``numeric`` (Python: ``Decimal``) -- der Cast auf ``BIGINT`` haelt den
   bisherigen Ergebnistyp (``SUM(integer)`` = ``bigint``) stabil.

SQLite: No-op. INTEGER ist dort bereits 64 Bit; die ORM-Deklaration
``BigInteger`` aendert am Speicherverhalten nichts.

Downgrade (nur PostgreSQL): Ruecknahme auf ``integer`` mit den urspruenglichen
View-Definitionen. Bestehen Werte ueber 2'147'483'647, scheitert der Downgrade
bewusst (kein stilles Abschneiden von Betraegen).

Revision ID: f6b1d4a8c2e7
Revises: a7c4e9b2d1f3
Create Date: 2026-10-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f6b1d4a8c2e7"
down_revision: Union[str, Sequence[str], None] = "a7c4e9b2d1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MONEY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("asset_class_price_history", "close_rappen"),
    ("cashflows", "amount_rappen"),
    ("cashflows", "gross_amount_rappen"),
    ("cashflows", "tax_amount_rappen"),
    ("conflict_of_interest_disclosures", "inducement_amount_rappen"),
    ("goals", "target_amount_rappen"),
    ("goals", "target_wealth_rappen"),
    ("optimizer_runs", "objective_value_milli"),
    ("portfolio_handoffs", "live_total_value_rappen"),
    ("price_history", "price_rappen"),
    ("recommendation_holdings", "units_milli"),
    ("recommendation_holdings", "market_value_rappen"),
    ("recommendation_holdings", "avg_cost_price_rappen"),
    ("recommendation_positions", "target_amount_rappen"),
    ("recommendation_positions", "current_amount_rappen"),
    ("recommendation_positions", "reference_price_rappen"),
    ("strategy_snapshots", "advisory_assets_rappen"),
    ("target_allocations", "advisory_wealth_at_generation_rappen"),
    ("target_allocations", "total_wealth_at_generation_rappen"),
    ("target_allocations", "reserve_needed_at_generation_rappen"),
    ("target_allocations", "external_reserve_at_generation_rappen"),
    ("target_allocations", "optimization_objective_value_milli"),
    ("wealth_inflows", "amount_rappen"),
    ("wealth_positions", "current_value_rappen"),
    ("wealth_positions", "property_rental_income_rappen"),
    ("wealth_positions", "pension_maturity_value_rappen"),
    ("wealth_positions", "pension_lumpsum_tax_rappen"),
    ("wealth_positions", "mortgage_amortization_rappen"),
)

# Views, die an Spalten aus MONEY_COLUMNS haengen. v_active_triggers liest
# keine dieser Spalten und bleibt unberuehrt.
_DEPENDENT_VIEWS = ("v_client_wealth_summary", "v_client_cashflow_surplus")

# Eingefrorene Definitionen (Stand a3c7e9d14b60), Summen mit BIGINT-Cast.
_WEALTH_SUMMARY_BIGINT = """
SELECT
    c.id AS client_id,
    c.first_name || ' ' || c.last_name AS client_name,
    c.client_classification,
    CAST(COALESCE(SUM(CASE WHEN wp.assignment != 'Verbindlichkeit' THEN wp.current_value_rappen ELSE 0 END),0) AS BIGINT) AS gross_wealth_rappen,
    CAST(COALESCE(SUM(CASE WHEN wp.assignment = 'Verbindlichkeit' THEN wp.current_value_rappen ELSE 0 END),0) AS BIGINT) AS liabilities_rappen,
    CAST(COALESCE(SUM(CASE WHEN wp.assignment != 'Verbindlichkeit' THEN wp.current_value_rappen ELSE 0 END),0)
    - COALESCE(SUM(CASE WHEN wp.assignment = 'Verbindlichkeit' THEN wp.current_value_rappen ELSE 0 END),0) AS BIGINT) AS net_worth_rappen,
    CAST(COALESCE(SUM(CASE WHEN wp.assignment = 'Beratungsvermögen' THEN wp.current_value_rappen ELSE 0 END),0) AS BIGINT) AS advisory_wealth_rappen
FROM clients c
LEFT JOIN wealth_positions wp ON wp.client_id = c.id AND wp.deleted_at IS NULL AND wp.is_active = 1
WHERE c.deleted_at IS NULL
GROUP BY c.id, c.first_name, c.last_name, c.client_classification
"""

_CASHFLOW_SURPLUS_BIGINT = """
SELECT
    c.id AS client_id,
    c.first_name || ' ' || c.last_name AS client_name,
    CAST(COALESCE(SUM(CASE WHEN cf.cashflow_type = 'Income' THEN cf.amount_rappen ELSE 0 END),0) AS BIGINT) AS total_income_rappen,
    CAST(COALESCE(SUM(CASE WHEN cf.cashflow_type = 'Expense' THEN cf.amount_rappen ELSE 0 END),0) AS BIGINT) AS total_expense_rappen,
    CAST(COALESCE(SUM(CASE WHEN cf.cashflow_type = 'Income' THEN cf.amount_rappen ELSE 0 END),0)
    - COALESCE(SUM(CASE WHEN cf.cashflow_type = 'Expense' THEN cf.amount_rappen ELSE 0 END),0) AS BIGINT) AS surplus_rappen
FROM clients c
LEFT JOIN cashflows cf ON cf.client_id = c.id AND cf.deleted_at IS NULL AND cf.is_active = 1
WHERE c.deleted_at IS NULL
GROUP BY c.id, c.first_name, c.last_name
"""

# Fuer den Downgrade: exakt die Definitionen aus a3c7e9d14b60.
_WEALTH_SUMMARY_ORIGINAL = """
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

_CASHFLOW_SURPLUS_ORIGINAL = """
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


def _is_postgres() -> bool:
    return op.get_context().dialect.name.startswith("postgresql")


def _drop_dependent_views() -> None:
    for name in _DEPENDENT_VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {name}")


def _create_views(wealth_body: str, cashflow_body: str) -> None:
    op.execute(f"CREATE VIEW v_client_wealth_summary AS {wealth_body.strip()}")
    op.execute(f"CREATE VIEW v_client_cashflow_surplus AS {cashflow_body.strip()}")


def upgrade() -> None:
    if not _is_postgres():
        return
    _drop_dependent_views()
    for table, column in MONEY_COLUMNS:
        op.alter_column(table, column, type_=sa.BigInteger(), existing_type=sa.Integer())
    _create_views(_WEALTH_SUMMARY_BIGINT, _CASHFLOW_SURPLUS_BIGINT)


def downgrade() -> None:
    if not _is_postgres():
        return
    _drop_dependent_views()
    for table, column in MONEY_COLUMNS:
        op.alter_column(table, column, type_=sa.Integer(), existing_type=sa.BigInteger())
    _create_views(_WEALTH_SUMMARY_ORIGINAL, _CASHFLOW_SURPLUS_ORIGINAL)
