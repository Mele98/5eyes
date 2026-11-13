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


def check_constraint_label(exc: BaseException) -> str:
    """Log-taugliche Bezeichnung des verletzten CHECK, NIE Zeilenwerte.

    PostgreSQL: ``tabelle.constraint`` aus ``diag`` (das ``DETAIL`` mit
    "Failing row contains (...)" bleibt aussen vor). SQLite: der Constraint-
    Ausdruck bzw. -Name aus der Meldung "CHECK constraint failed: <...>" (die
    Meldung enthaelt keine Zeilenwerte), auf 200 Zeichen gekuerzt.
    """
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    table = getattr(diag, "table_name", None)
    if name or table:
        return f"{table or '?'}.{name or '?'}"
    lines = str(orig if orig is not None else exc).splitlines()
    text = lines[0] if lines else ""
    prefix = "CHECK constraint failed:"
    if prefix in text:
        return text.split(prefix, 1)[1].strip()[:200]
    return "?"


def raise_if_check_violation(exc: BaseException) -> None:
    """In ``except IntegrityError``-Zweigen, die einen Konflikt melden (409
    usw.), ZUERST aufrufen (nach dem Rollback): eine CHECK-Verletzung ist kein
    Konflikt, sondern ein Wert ausserhalb der Werteliste. Sie wird unveraendert
    weitergeworfen und vom zentralen Handler als 422
    ``DB_CHECK_CONSTRAINT_VIOLATION`` (ohne Werte) beantwortet. UNIQUE-, FK-
    und NOT-NULL-Fehler kehren zurueck -> bisheriges Verhalten der Aufrufstelle.
    """
    if is_check_constraint_violation(exc):
        raise exc
