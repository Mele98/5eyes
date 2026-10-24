"""UPGRADE-PATH-CHECK-DRIFT-001: CHECK-IN-Listen bestehender SQLite-DBs nachziehen.

Befund (Upgrade-Pfad-Verifikation 2026-10-21 gegen eine Kopie der echten
Desktop-DB): ``bootstrap_sqlite_schema()`` fuehrt ``CREATE TABLE IF NOT
EXISTS`` aus. Wird im Referenzschema (``ares_schema.sql``) eine
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

Absicherung (CIO/CTO-Abnahme #675), nur wenn wirklich etwas zu aendern ist:
Sicherung per SQLite-Backup-API VOR der Aenderung (sonst keine Aenderung),
danach ``integrity_check`` + ``foreign_key_check`` der betroffenen Tabellen
(nur NEUE Verstoesse zaehlen), bei Befund Ruecksetzen der DDL bzw.
Wiederherstellung aus der Sicherung, Log- und JSON-Protokoll der ergaenzten
Werte.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
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
BACKUP_PREFIX = "5eyes_pre_check_upgrade_"


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
) -> tuple[str, dict[str, list[str]]]:
    """Gibt (neue DDL, {Spalte: ergaenzte Literale}) zurueck; DDL unveraendert,
    wenn nichts fehlt."""
    added: list[tuple[str, list[str]]] = []
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
        added.append((column, missing))
    return new_sql, dict(reversed(added))


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


def _db_file(target_engine: Engine) -> Path | None:
    database = target_engine.url.database
    if not database or database == ":memory:" or database.startswith("file:"):
        return None
    return Path(database)


def _fk_violations(conn, tables: list[str]) -> set[tuple]:
    found: set[tuple] = set()
    for table in tables:
        for row in conn.execute(f'PRAGMA foreign_key_check("{table}")').fetchall():
            found.add(tuple(row))
    return found


def _write_schema(dbapi, sql_by_table: dict[str, str]) -> None:
    """Dokumentiertes writable_schema-Verfahren in EINER Transaktion."""
    previous_isolation = dbapi.isolation_level
    dbapi.isolation_level = None  # Transaktion explizit steuern
    try:
        dbapi.execute("BEGIN IMMEDIATE")
        try:
            schema_version = dbapi.execute("PRAGMA schema_version").fetchone()[0]
            dbapi.execute("PRAGMA writable_schema = ON")
            for name, table_sql in sql_by_table.items():
                dbapi.execute(
                    "UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = ?",
                    (table_sql, name),
                )
            dbapi.execute(f"PRAGMA schema_version = {int(schema_version) + 1}")
            dbapi.execute("PRAGMA writable_schema = OFF")
            dbapi.execute("COMMIT")
        except Exception:
            dbapi.execute("ROLLBACK")
            raise
    finally:
        dbapi.isolation_level = previous_isolation


def _apply(target_engine: Engine, sql_by_table: dict[str, str]) -> None:
    raw = target_engine.raw_connection()
    try:
        _write_schema(raw.driver_connection, sql_by_table)
    finally:
        raw.close()


def _post_change_problems(
    db_file: Path,
    db_key: str | None,
    expected_sql: dict[str, str],
    fk_before: set[tuple],
) -> list[str]:
    """Pruefung NACH der Aenderung in einer frischen Verbindung."""
    from services.backup import _open_connection

    problems: list[str] = []
    conn = _open_connection(str(db_file), uri=False, db_key=db_key)
    try:
        integrity = [row[0] for row in conn.execute("PRAGMA integrity_check").fetchall()]
        if integrity != ["ok"]:
            problems.append(f"integrity_check: {integrity[:5]}")
        for name, table_sql in expected_sql.items():
            stored = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
            ).fetchone()
            if not stored or stored[0] != table_sql:
                problems.append(f"DDL von {name} nicht wie erwartet")
        new_fk = _fk_violations(conn, list(expected_sql)) - fk_before
        if new_fk:
            problems.append(f"neue foreign_key_check-Verstoesse: {len(new_fk)}")
    finally:
        conn.close()
    return problems


def _restore_from_backup(
    target_engine: Engine, backup_file: Path, db_file: Path, db_key: str | None
) -> None:
    from services.backup import _open_connection

    target_engine.dispose()
    source = _open_connection(f"file:{backup_file.as_posix()}?mode=ro", uri=True, db_key=db_key)
    try:
        destination = _open_connection(str(db_file), uri=False, db_key=db_key)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()


def _remove_empty_partial_sidecars(backup_file: Path) -> None:
    """``_perform_atomic_copy`` hinterlaesst bei WAL-Quellen ``*.partial-wal``/
    ``*.partial-shm`` der Temp-Datei (Name nach os.replace verwaist). Nur
    entfernen, wenn das WAL leer ist (dann geht nachweislich nichts verloren)."""
    for wal in backup_file.parent.glob(f"{backup_file.name}.*.partial-wal"):
        try:
            if wal.stat().st_size != 0:
                continue
            shm = wal.with_name(wal.name[: -len("-wal")] + "-shm")
            wal.unlink()
            if shm.exists():
                shm.unlink()
        except OSError:
            pass


def _plan(
    target_engine: Engine, reference: dict[tuple[str, str], list[str]]
) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, list[str]]]]:
    reference_tables = {table for table, _column in reference}
    with target_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL")
        ).fetchall()
    old_sql: dict[str, str] = {}
    new_sql: dict[str, str] = {}
    added: dict[str, dict[str, list[str]]] = {}
    for name, table_sql in rows:
        if name.lower() not in reference_tables:
            continue
        try:
            widened, columns = widened_table_sql(name, table_sql, reference)
        except ValueError:
            logger.error("CHECK-Drift: DDL von %s nicht parsebar, uebersprungen", name)
            continue
        if not columns:
            continue
        if not _ddl_parses(widened):
            logger.error("CHECK-Drift: erweiterte DDL von %s ungueltig, uebersprungen", name)
            continue
        old_sql[name], new_sql[name], added[name] = table_sql, widened, columns
    return old_sql, new_sql, added


def ensure_sqlite_check_in_lists_current(
    target_engine: Engine,
    schema_path: str | Path | None,
    *,
    backup_dir: str | Path | None = None,
    db_key: str | None = None,
) -> dict[str, dict[str, list[str]]]:
    """Erweitert veraltete CHECK-IN-Listen bestehender SQLite-Tabellen.

    Ablauf (nur wenn wirklich etwas fehlt):
      1. Konsistente Sicherung per SQLite-Backup-API nach
         ``<backup_dir>/5eyes_pre_check_upgrade_<UTC-Zeitstempel>.db``
         (Default ``settings.backup_dir``, ueber
         ``services.backup._perform_atomic_copy``: Temp-Datei,
         integrity_check, atomarer Rename; SQLCipher-faehig). Das Praefix
         faellt bewusst NICHT unter das Rotations-Glob ``5eyes-backup-*.db``,
         wird also nicht automatisch weggeraeumt. Scheitert die Sicherung:
         KEINE Aenderung.
      2. Aenderung in einer Transaktion (writable_schema).
      3. Pruefung in frischer Verbindung: ``PRAGMA integrity_check``, DDL wie
         erwartet, ``foreign_key_check`` der betroffenen Tabellen ohne NEUE
         Verstoesse (vorbestehende zaehlen nicht).
      4. Bei Befund: alte DDL zuruecksetzen; gelingt das nicht sauber,
         Wiederherstellung aus der Sicherung aus Schritt 1.
      5. Log-Eintrag + JSON-Protokoll neben der Sicherung: welche Werte in
         welchen Tabellen/Spalten ergaenzt wurden.

    Rueckgabe: {table: {column: [ergaenzte Literale]}}; leer, wenn nichts zu
    tun war oder die Aenderung verworfen wurde. Fehler stoppen den Boot nie
    (die App laeuft dann mit dem alten Schema weiter).
    """
    if target_engine.dialect.name != "sqlite" or not schema_path:
        return {}
    schema_file = Path(schema_path)
    if not schema_file.exists():
        return {}
    db_file = _db_file(target_engine)
    if db_file is None or not db_file.exists():
        return {}
    reference = reference_check_in_lists(schema_file.read_text(encoding="utf-8"))
    old_sql, new_sql, added = _plan(target_engine, reference)
    if not new_sql:
        return {}

    from config import settings
    from services.backup import _open_connection, _perform_atomic_copy

    key = db_key if db_key is not None else getattr(settings, "db_key", None)
    target_dir = Path(backup_dir if backup_dir is not None else settings.backup_dir).expanduser()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    backup_file = target_dir / f"{BACKUP_PREFIX}{stamp}.db"
    try:
        _perform_atomic_copy(db_file, backup_file, db_key=key)
    except Exception as exc:  # noqa: BLE001 - ohne Sicherung keine Aenderung
        logger.error(
            "CHECK-Drift: Sicherung nach %s fehlgeschlagen -- Schema bleibt unveraendert: %s",
            backup_file, exc,
        )
        return {}
    _remove_empty_partial_sidecars(backup_file)

    try:
        conn = _open_connection(str(db_file), uri=False, db_key=key)
        try:
            fk_before = _fk_violations(conn, list(new_sql))
        finally:
            conn.close()
        _apply(target_engine, new_sql)
    except Exception as exc:  # noqa: BLE001 - Transaktion ist zurueckgerollt
        logger.error("CHECK-Drift-Reparatur fehlgeschlagen (Rollback, unveraendert): %s", exc)
        return {}

    try:
        problems = _post_change_problems(db_file, key, new_sql, fk_before)
    except Exception as exc:  # noqa: BLE001
        problems = [f"Pruefung nicht ausfuehrbar: {exc}"]
    if problems:
        logger.error(
            "CHECK-Drift: Pruefung nach Aenderung fehlgeschlagen %s -- setze zurueck", problems,
        )
        try:
            _apply(target_engine, old_sql)
            reverted = _post_change_problems(db_file, key, old_sql, fk_before)
        except Exception as exc:  # noqa: BLE001
            reverted = [f"Ruecksetzen fehlgeschlagen: {exc}"]
        if reverted:
            logger.error(
                "CHECK-Drift: Ruecksetzen unsauber %s -- stelle aus %s wieder her",
                reverted, backup_file,
            )
            try:
                _restore_from_backup(target_engine, backup_file, db_file, key)
            except Exception as exc:  # noqa: BLE001
                logger.critical(
                    "CHECK-Drift: Wiederherstellung aus %s fehlgeschlagen: %s", backup_file, exc,
                )
        return {}

    report = {
        "event": "UPGRADE-PATH-CHECK-DRIFT-001",
        "applied_at_utc": stamp,
        "backup_file": str(backup_file),
        "added_values": added,
    }
    try:
        backup_file.with_suffix(".json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("CHECK-Drift: Protokolldatei nicht schreibbar: %s", exc)
    logger.warning(
        "CHECK-Drift: veraltete CHECK-Wertelisten erweitert (Sicherung %s): %s",
        backup_file, json.dumps(added, ensure_ascii=False),
    )
    return added
