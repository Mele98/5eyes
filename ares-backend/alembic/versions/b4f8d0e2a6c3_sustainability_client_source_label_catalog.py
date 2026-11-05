"""Kunden-Quellbezeichnung der Nachhaltigkeitsnachweise als Katalogwert.

Audit 2026-11 / 05, Paket T1, Delta-Pruefung #863 N-863-6: Freitext in
``client_source_label`` liess Dritt-/Markennamen durch (die Teilstring-
Pruefung gegen den Anbieter reichte nicht). Neu ist das Feld ein Katalogwert
mit denselben Codes wie ``source_type`` (Texte in
``models.product_eligibility.SUSTAINABILITY_CLIENT_SOURCE_LABELS``).

- Bestand: Werte ausserhalb des Katalogs werden auf den Code des
  Quellentyps gesetzt (neutraler Default, kein Freitext bleibt stehen). Der
  Unveraenderlichkeits-Trigger (a3e7c9d1f5b4) wird dafuer nur innerhalb
  dieser Migration ausgesetzt (Postgres: DISABLE/ENABLE TRIGGER; SQLite:
  Update-Trigger entfernen und mit identischer DDL neu anlegen).
- Postgres: CHECK ``ck_psa_client_source_label``.
- SQLite (Alembic-Pfad, nur Tests): kein nachtraeglicher CHECK, weil dafuer
  die Tabelle neu aufgebaut werden muesste und die Trigger verloren gingen.
  Die Desktop-Installation (create_all) bekommt den CHECK aus dem ORM, die
  API prueft den Katalog immer.
- Downgrade: CHECK entfernen (Postgres); die Codes bleiben als Text stehen.

Revision ID: b4f8d0e2a6c3
Revises: a3e7c9d1f5b4
Create Date: 2026-11-05
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

from alembic import op


revision: str = "b4f8d0e2a6c3"
down_revision: Union[str, Sequence[str], None] = "a3e7c9d1f5b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "product_sustainability_attributes"
CODES = (
    "prospectus", "fund_contract", "kid", "factsheet", "provider_exclusion_policy",
    "provider_confirmation", "data_vendor", "house_analysis",
)
_IN = ", ".join(f"'{c}'" for c in CODES)
CHECK_SQL = f"client_source_label IS NULL OR client_source_label IN ({_IN})"
NORMALIZE_SQL = (
    f"UPDATE {TABLE} SET client_source_label = source_type "
    f"WHERE client_source_label IS NOT NULL AND client_source_label NOT IN ({_IN})"
)


def _immutable_migration():
    path = Path(__file__).with_name("a3e7c9d1f5b4_sustainability_attributes_immutable.py")
    spec = importlib.util.spec_from_file_location("_a3e7c9d1f5b4", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect.startswith("postgresql"):
        op.execute(f"ALTER TABLE {TABLE} DISABLE TRIGGER trg_psa_immutable")
        op.execute(NORMALIZE_SQL)
        op.execute(f"ALTER TABLE {TABLE} ENABLE TRIGGER trg_psa_immutable")
        op.create_check_constraint("ck_psa_client_source_label", TABLE, CHECK_SQL)
        return
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_psa_immutable_update")
        op.execute(NORMALIZE_SQL)
        op.execute(_immutable_migration().SQLITE_TRIGGERS[0])


def downgrade() -> None:
    if op.get_context().dialect.name.startswith("postgresql"):
        op.drop_constraint("ck_psa_client_source_label", TABLE, type_="check")
