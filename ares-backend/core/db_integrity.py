"""Erkennung von CHECK-Verletzungen in Integritaetsfehlern (RC-CH-1-F1).

Blattmodul ohne Importe: arbeitet per Duck-Typing auf ``exc.orig`` und ist
damit fuer Middleware und Router gleichermassen nutzbar.

* PostgreSQL (psycopg 3 ``sqlstate``, psycopg2 ``pgcode``): SQLSTATE 23514
  (check_violation).
* SQLite/SQLCipher: Meldung "CHECK constraint failed".
"""
from __future__ import annotations

PG_CHECK_VIOLATION_SQLSTATE = "23514"


def is_check_constraint_violation(exc: BaseException) -> bool:
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate is not None:
        return sqlstate == PG_CHECK_VIOLATION_SQLSTATE
    return "CHECK constraint failed" in str(orig if orig is not None else exc)
