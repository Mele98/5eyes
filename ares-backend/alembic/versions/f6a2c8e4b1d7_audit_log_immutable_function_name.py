"""PostgreSQL: Immutability-Funktion von audit_log heisst fn_ares_audit_log_immutable.

W4-d (BRAND, Dossier D11): Die Funktion hinter den beiden Triggern
``trg_audit_log_no_update`` und ``trg_audit_log_no_delete`` wird per
``ALTER FUNCTION ... RENAME`` umbenannt -- nie DROP/CREATE. Die Trigger
binden die Funktion ueber ihre OID; RENAME laesst OID und Bindung unveraendert,
der Schutz von ``audit_log`` hat damit zu keinem Zeitpunkt eine Luecke.

Die Funktion wird ueber die Trigger gefunden, nicht ueber ihren bisherigen
Namen. Ist sie schon umbenannt (z.B. durch den externen Migrator), ist die
Revision ein No-op. Am Ende prueft dieselbe Transaktion, dass beide Trigger
aktiv an der umbenannten Funktion haengen; sonst Abbruch.

Downgrade benennt die Funktion auf den Namen zurueck, den die anlegende
Revision e84f9a2d1c70 vergibt (dort als Konstante gefuehrt), damit deren
Downgrade unveraendert greift.

Nur PostgreSQL; SQLite nutzt Alembic nicht fuer diese Trigger.

Revision ID: f6a2c8e4b1d7
Revises: 2cbc77503cd9
Create Date: 2026-10-24
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Sequence, Union

from alembic import op


revision: str = "f6a2c8e4b1d7"
down_revision: Union[str, Sequence[str], None] = "2cbc77503cd9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AUDIT_LOG_IMMUTABLE_FUNCTION = "fn_ares_audit_log_immutable"
AUDIT_LOG_TRIGGERS = ("trg_audit_log_no_update", "trg_audit_log_no_delete")


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def _creating_revision_function_name() -> str:
    """Name, den e84f9a2d1c70 beim Anlegen vergibt (fuer den Downgrade)."""
    path = Path(__file__).with_name("e84f9a2d1c70_postgres_market_data_runtime_tables.py")
    spec = importlib.util.spec_from_file_location("_audit_fn_creating_revision", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.AUDIT_LOG_IMMUTABLE_FUNCTION


def _rename_sql(target: str) -> str:
    upd, dele = AUDIT_LOG_TRIGGERS
    return f"""
DO $rename$
DECLARE
    f_update oid;
    f_delete oid;
    f_name text;
    f_schema oid;
BEGIN
    SELECT t.tgfoid INTO f_update FROM pg_trigger t
     WHERE t.tgrelid = 'audit_log'::regclass AND t.tgname = '{upd}' AND NOT t.tgisinternal;
    SELECT t.tgfoid INTO f_delete FROM pg_trigger t
     WHERE t.tgrelid = 'audit_log'::regclass AND t.tgname = '{dele}' AND NOT t.tgisinternal;
    IF f_update IS NULL OR f_delete IS NULL THEN
        RAISE EXCEPTION 'audit_log immutability triggers missing';
    END IF;
    IF f_update <> f_delete THEN
        RAISE EXCEPTION 'audit_log immutability triggers use different functions';
    END IF;
    SELECT p.proname, p.pronamespace INTO f_name, f_schema FROM pg_proc p WHERE p.oid = f_update;
    IF f_name <> '{target}' THEN
        IF EXISTS (SELECT 1 FROM pg_proc p WHERE p.proname = '{target}' AND p.pronamespace = f_schema) THEN
            RAISE EXCEPTION 'target function name already taken';
        END IF;
        EXECUTE format('ALTER FUNCTION %s RENAME TO %I', f_update::regprocedure, '{target}');
    END IF;
    IF (SELECT count(*) FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
         WHERE t.tgrelid = 'audit_log'::regclass
           AND t.tgname IN ('{upd}', '{dele}')
           AND p.oid = f_update AND p.proname = '{target}' AND t.tgenabled <> 'D') <> 2 THEN
        RAISE EXCEPTION 'audit_log immutability triggers not bound to the renamed function';
    END IF;
END
$rename$
"""


def upgrade() -> None:
    if _is_postgres():
        op.execute(_rename_sql(AUDIT_LOG_IMMUTABLE_FUNCTION))


def downgrade() -> None:
    if _is_postgres():
        op.execute(_rename_sql(_creating_revision_function_name()))
