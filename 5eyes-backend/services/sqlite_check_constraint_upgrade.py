"""UPGRADE-PATH-CHECK-DRIFT-001: CHECK-IN-Listen bestehender SQLite-DBs nachziehen.

Befund (Upgrade-Pfad-Verifikation 2026-10-21 gegen eine Kopie der echten
Desktop-DB): ``bootstrap_sqlite_schema()`` fuehrt ``CREATE TABLE IF NOT
EXISTS`` aus. Wird im Referenzschema (``5eyes_schema_v4.0_FINAL.sql``) eine
``CHECK(col IN (...))``-Werteliste erweitert, erreicht das nur
Neuinstallationen -- bestehende Datenbanken behalten die alte, engere Liste.
Auf der realen DB waren dadurch u.a. folgende, heute vom Code geschriebene
Werte per ``CHECK constraint failed`` blockiert:

* ``users.role``: 'super_admin', 'portfolio_management', 'client'
* ``contract_documents.status``: 'Teilweise unterzeichnet' (E-Signing)
* ``contract_documents.document_type``: 'Kostenausweis' (Archivierung)
* ``wealth_positions.mortgage_amortization_type``: 'Indirekt (Säule 3a)'
  (Frontend-Default der Hypothek)

Die frueheren Fixes dieser Bugklasse (c63d4ce, d48c8d5, 4bb1f8c) korrigierten
nur das Referenzschema, also nur fabrikneue Installationen.

Reparatur: Fuer jede Tabelle wird jede spaltenweise ``CHECK(col IN (...))``-
Liste der bestehenden DB mit der Liste des Referenzschemas verglichen. Fehlen
Werte, wird die bestehende Liste zur VEREINIGUNGSMENGE erweitert (bestehende
Werte bleiben in Originalreihenfolge erhalten, fehlende werden angehaengt).
Es wird nie ein Wert entfernt -- der Constraint wird nur gelockert, bestehende
Zeilen erfuellen ihn daher garantiert weiterhin.

Mechanik: das von SQLite dokumentierte Verfahren fuer Constraint-Aenderungen
ohne Aenderung des On-Disk-Formats (https://www.sqlite.org/lang_altertable.html,
Abschnitt "Making Other Kinds Of Table Schema Changes": ``writable_schema``,
``UPDATE sqlite_schema``, ``schema_version`` + 1, danach Integritaetspruefung).
Kein Tabellen-Neuaufbau, daher bleiben Indizes, Trigger und Fremdschluessel
anderer Tabellen unberuehrt. Die neue DDL wird vorher in einer In-Memory-DB
auf Syntax geprueft. Idempotent: ein zweiter Lauf findet keine Abweichung.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`\[]?(\w+)[\"`\]]?\s*\(",
    re.IGNORECASE,
)
_CHECK_IN_RE = re.compile(
    r"CHECK\s*\(\s*[\"`\[]?(\w+)[\"`\]]?\s+IN\s*\(",
    re.IGNORECASE,
)
_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")


def _matching_paren(sql: str, open_index: int) -> int:
    depth = 0
    in_literal = False
    index = open_index
    while index < len(sql):
        char = sql[index]
        if in_literal:
            if char == "'":
                if index + 1 < len(sql) and sql[index + 1] == "'":
                    index += 1
                else:
                    in_literal = False
        elif char == "'":
            in_literal = True
        elif char == "-" and sql.startswith("--", index):
            newline = sql.find("\n", index)
            index = len(sql) if newline < 0 else newline
            continue
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ValueError("unbalancierte Klammern in DDL")


def _in_lists(table_sql: str) -> list[tuple[str, int, int, list[str]]]:
    """(column, start, end, literals) je ``CHECK(col IN (...))``.

    ``start``/``end`` umfassen den Inhalt der IN-Klammer (exklusive Klammern).
    """
    found = []
    for match in _CHECK_IN_RE.finditer(table_sql):
        open_index = match.end() - 1
        close_index = _matching_paren(table_sql, open_index)
        body = table_sql[open_index + 1:close_index]
        literals = _LITERAL_RE.findall(_LINE_COMMENT_RE.sub("", body))
        if not literals:
            continue  # numerische Listen wie IN (0,1) -- nicht Gegenstand
        found.append((match.group(1).lower(), open_index + 1, close_index, literals))
    return found


def reference_check_in_lists(schema_sql: str) -> dict[tuple[str, str], list[str]]:
    """{(table, column): [literal, ...]} aus dem Referenzschema."""
    result: dict[tuple[str, str], list[str]] = {}
    for match in _CREATE_TABLE_RE.finditer(schema_sql):
        table = match.group(1).lower()
        close_index = _matching_paren(schema_sql, match.end() - 1)
        table_sql = schema_sql[match.start():close_index + 1]
        for column, _start, _end, literals in _in_lists(table_sql):
            # Mehrfache CHECKs derselben Spalte: Vereinigung (nie enger).
            merged = result.setdefault((table, column), [])
            merged.extend(value for value in literals if value not in merged)
    return result


def widened_table_sql(
    table: str,
    table_sql: str,
    reference: dict[tuple[str, str], list[str]],
) -> tuple[str, list[str]]:
    """Gibt (neue DDL, Liste geaenderter Spalten) zurueck; DDL unveraendert,
    wenn nichts fehlt."""
    changed: list[str] = []
    new_sql = table_sql
    # Von hinten ersetzen, damit Offsets gueltig bleiben.
    for column, start, end, literals in reversed(_in_lists(table_sql)):
        wanted = reference.get((table.lower(), column))
        if not wanted:
            continue
        missing = [value for value in wanted if value not in literals]
        if not missing:
            continue
        new_sql = new_sql[:start] + ",".join(literals + missing) + new_sql[end:]
        changed.append(column)
    return new_sql, list(reversed(changed))


def _ddl_parses(table_sql: str) -> bool:
    probe = sqlite3.connect(":memory:")
    try:
        probe.execute("PRAGMA foreign_keys = OFF")
        probe.execute(table_sql)
        return True
    except sqlite3.Error:
        return False
    finally:
        probe.close()


def ensure_sqlite_check_in_lists_current(
    target_engine: Engine,
    schema_path: str | Path | None,
) -> dict[str, list[str]]:
    """Erweitert veraltete CHECK-IN-Listen bestehender SQLite-Tabellen.

    Rueckgabe: {table: [geaenderte Spalten]} (leer, wenn nichts zu tun war).
    Fehler stoppen den Boot nicht (Verhalten dann wie bisher), werden aber
    laut geloggt.
    """
    if target_engine.dialect.name != "sqlite" or not schema_path:
        return {}
    schema_file = Path(schema_path)
    if not schema_file.exists():
        return {}
    reference = reference_check_in_lists(schema_file.read_text(encoding="utf-8"))
    reference_tables = {table for table, _column in reference}

    with target_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL")
        ).fetchall()
    plans: list[tuple[str, str, list[str]]] = []
    for name, table_sql in rows:
        if name.lower() not in reference_tables:
            continue
        try:
            new_sql, columns = widened_table_sql(name, table_sql, reference)
        except ValueError:
            logger.error("CHECK-Drift: DDL von %s nicht parsebar, uebersprungen", name)
            continue
        if not columns:
            continue
        if not _ddl_parses(new_sql):
            logger.error("CHECK-Drift: erweiterte DDL von %s ungueltig, uebersprungen", name)
            continue
        plans.append((name, new_sql, columns))
    if not plans:
        return {}

    raw = target_engine.raw_connection()
    try:
        dbapi = raw.driver_connection
        previous_isolation = dbapi.isolation_level
        dbapi.isolation_level = None  # Transaktion explizit steuern
        try:
            dbapi.execute("BEGIN IMMEDIATE")
            try:
                schema_version = dbapi.execute("PRAGMA schema_version").fetchone()[0]
                dbapi.execute("PRAGMA writable_schema = ON")
                for name, new_sql, _columns in plans:
                    dbapi.execute(
                        "UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = ?",
                        (new_sql, name),
                    )
                dbapi.execute(f"PRAGMA schema_version = {int(schema_version) + 1}")
                dbapi.execute("PRAGMA writable_schema = OFF")
                dbapi.execute("COMMIT")
            except Exception:
                dbapi.execute("ROLLBACK")
                raise
        finally:
            dbapi.isolation_level = previous_isolation
    except Exception as exc:  # noqa: BLE001 - Boot darf nicht stoppen
        logger.error("CHECK-Drift-Reparatur fehlgeschlagen (unveraendert): %s", exc)
        return {}
    finally:
        raw.close()

    with target_engine.connect() as conn:
        check = conn.execute(text("PRAGMA quick_check")).scalar()
    if check != "ok":
        logger.error("CHECK-Drift-Reparatur: quick_check meldet %r", check)
    changed = {name: columns for name, _sql, columns in plans}
    logger.warning("CHECK-Drift: veraltete Wertelisten erweitert: %s", changed)
    return changed
