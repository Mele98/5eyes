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

Absicherung (CIO/CTO-Abnahme #675), nur wenn wirklich etwas zu aendern ist:
Sicherung per SQLite-Backup-API VOR der Aenderung (sonst keine Aenderung),
danach ``integrity_check`` + ``foreign_key_check`` der betroffenen Tabellen
(nur NEUE Verstoesse zaehlen), bei Befund Ruecksetzen der DDL bzw.
Wiederherstellung aus der Sicherung, Log- und JSON-Protokoll der ergaenzten
Werte.

Nachtrag (Closure-Review #675, Residuen 1+2):

* Erkennung ueber den Mini-Parser ``services.sqlite_check_ddl`` statt Regex.
  Unterstuetzt sind genau ``CHECK(col IN (...))`` und
  ``CHECK(col IS NULL OR col IN (...))``. Jede andere CHECK-Form mit
  String-IN-Liste, die nicht token-identisch im Referenzschema steht, sowie
  mehrere Wertelisten-CHECKs derselben Spalte ergeben
  ``MANUAL_MIGRATION_REQUIRED`` -- nie ein stilles No-op, nie eine Union.
* Typisierte Ergebnisse (:class:`CheckUpgradeOutcome`). Der Start laeuft nur
  bei verifiziertem Vor- oder Zielzustand weiter (``STARTUP_SAFE_OUTCOMES``).
  Kann weder die DDL-Ruecksetzung noch die Wiederherstellung den Vorzustand
  nachweisen, wird die DB quarantaenisiert (Evidence-Datei + Schreibschutz,
  nichts geloescht) und :class:`FatalRecoveryFailed` bricht ``init_db()`` ab.
* Wiederherstellung nur aus der in DIESEM Lauf erzeugten Sicherung, deren
  SHA-256 direkt nach dem Anlegen festgehalten und vor dem Einspielen erneut
  geprueft wird; zuerst in eine Temp-DB, dort voll geprueft, erst dann per
  SQLite-Backup-API (eine Schreibtransaktion) in die Ziel-DB, danach Pool neu
  aufgebaut und ueber die Engine nochmals geprueft.
"""
from __future__ import annotations

import enum
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import stat
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from services.sqlite_check_ddl import (
    DdlParseError,
    SupportedCheck,
    UnsupportedCheck,
    parse_create_tables,
    parse_table_ddl,
    tokenize,
)

logger = logging.getLogger(__name__)

MIGRATION_ID = "UPGRADE-PATH-CHECK-DRIFT-001"
BACKUP_PREFIX = "5eyes_pre_check_upgrade_"
QUARANTINE_SUFFIX = ".check-upgrade-quarantine.json"


class CheckUpgradeOutcome(str, enum.Enum):
    NOOP = "noop"
    APPLIED_VERIFIED = "applied_verified"
    RESTORED_VERIFIED = "restored_verified"
    SKIPPED_BACKUP_FAILED = "skipped_backup_failed"
    MANUAL_MIGRATION_REQUIRED = "manual_migration_required"
    FATAL_RECOVERY_FAILED = "fatal_recovery_failed"


# Nur hier ist der Zustand der DB nachweislich Vor- oder Zielzustand.
STARTUP_SAFE_OUTCOMES = frozenset({
    CheckUpgradeOutcome.NOOP,
    CheckUpgradeOutcome.APPLIED_VERIFIED,
    CheckUpgradeOutcome.RESTORED_VERIFIED,
    CheckUpgradeOutcome.SKIPPED_BACKUP_FAILED,
})


@dataclass(frozen=True)
class CheckUpgradeResult:
    outcome: CheckUpgradeOutcome
    added: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    problems: tuple[str, ...] = ()
    backup_file: Path | None = None
    quarantine_marker: Path | None = None

    @property
    def startup_safe(self) -> bool:
        return self.outcome in STARTUP_SAFE_OUTCOMES


class SqliteCheckUpgradeError(RuntimeError):
    def __init__(self, result: CheckUpgradeResult, message: str) -> None:
        super().__init__(message)
        self.result = result


class ManualMigrationRequired(SqliteCheckUpgradeError):
    """Nicht unterstuetzte CHECK-Form: DB unveraendert, Start blockiert."""


class FatalRecoveryFailed(SqliteCheckUpgradeError):
    """Vorzustand nicht nachweisbar: DB quarantaenisiert, Start blockiert."""


class BackupAuthenticationError(RuntimeError):
    pass


def quarantine_marker_path(db_file: str | Path) -> Path:
    db_file = Path(db_file)
    return db_file.with_name(db_file.name + QUARANTINE_SUFFIX)


def raise_if_quarantined(db_file: str | Path | None) -> None:
    """Startsperre, solange eine Quarantaene-Evidence neben der DB liegt."""
    if not db_file:
        return
    marker = quarantine_marker_path(Path(db_file).expanduser())
    if marker.exists():
        result = CheckUpgradeResult(
            CheckUpgradeOutcome.FATAL_RECOVERY_FAILED,
            problems=("DB ist quarantaenisiert",),
            quarantine_marker=marker,
        )
        raise FatalRecoveryFailed(
            result,
            f"{MIGRATION_ID}: DB quarantaenisiert ({marker}); manuelle Wiederherstellung "
            "erforderlich, Evidence-Datei erst danach entfernen",
        )


def raise_if_startup_unsafe(result: CheckUpgradeResult) -> None:
    if result.startup_safe:
        return
    detail = "; ".join(result.problems) or result.outcome.value
    if result.outcome is CheckUpgradeOutcome.MANUAL_MIGRATION_REQUIRED:
        raise ManualMigrationRequired(
            result, f"{MIGRATION_ID}: manuelle Migration erforderlich: {detail}",
        )
    raise FatalRecoveryFailed(
        result,
        f"{MIGRATION_ID}: Wiederherstellung nicht verifiziert, DB quarantaenisiert "
        f"({result.quarantine_marker}): {detail}",
    )


# --------------------------------------------------------------------------
# Planung (Residuum 1)
# --------------------------------------------------------------------------


def _canonical(expression: str) -> tuple[tuple[str, str], ...]:
    return tuple(
        (token.kind, token.text.lower() if token.kind == "word" else token.text)
        for token in tokenize(expression)
    )


@dataclass(frozen=True)
class _Reference:
    lists: dict[tuple[str, str], list[str]]
    unsupported: dict[str, set]
    problems: tuple[str, ...]


def _reference(schema_sql: str) -> _Reference:
    lists: dict[tuple[str, str], list[str]] = {}
    unsupported: dict[str, set] = {}
    problems: list[str] = []
    try:
        tables = parse_create_tables(schema_sql)
    except DdlParseError as exc:
        return _Reference({}, {}, (f"Referenzschema nicht parsebar: {exc}",))
    for table in tables:
        for check in table.checks:
            if isinstance(check, UnsupportedCheck):
                unsupported.setdefault(table.name, set()).add(_canonical(check.text))
                continue
            key = (table.name, check.column)
            if key in lists:
                problems.append(f"Referenz {table.name}.{check.column}: mehrere Wertelisten-CHECKs")
                continue
            lists[key] = list(check.literals)
    return _Reference(lists, unsupported, tuple(problems))


def reference_check_in_lists(schema_sql: str) -> dict[tuple[str, str], list[str]]:
    """{(table, column): [literal, ...]} aus dem Referenzschema."""
    return _reference(schema_sql).lists


def _literal_value(literal: str) -> str:
    return literal[1:-1].replace("''", "'")


def _widen(
    table: str, table_sql: str, reference: _Reference,
) -> tuple[str, dict[str, list[str]], list[str]]:
    """(neue DDL, {Spalte: ergaenzte Literale}, Befunde fuer manuelle Migration)."""
    parsed = parse_table_ddl(table_sql)
    key_table = table.lower()
    manual: list[str] = []
    known_unsupported = reference.unsupported.get(key_table, set())
    by_column: dict[str, list[SupportedCheck]] = {}
    for check in parsed.checks:
        if isinstance(check, UnsupportedCheck):
            if _canonical(check.text) not in known_unsupported:
                manual.append(
                    f"{table}: nicht unterstuetzte CHECK-Form ({', '.join(sorted(check.columns))})"
                )
            continue
        by_column.setdefault(check.column, []).append(check)
    insertions: list[tuple[int, str, list[str]]] = []
    for column, checks in by_column.items():
        wanted = reference.lists.get((key_table, column))
        if not wanted:
            continue
        if len(checks) > 1:
            manual.append(f"{table}.{column}: mehrere Wertelisten-CHECKs")
            continue
        present = set(checks[0].values)
        missing = [literal for literal in wanted if _literal_value(literal) not in present]
        if missing:
            insertions.append((checks[0].insert_at, column, missing))
    if manual:
        return table_sql, {}, manual
    new_sql = table_sql
    for offset, _column, missing in sorted(insertions, reverse=True):
        new_sql = new_sql[:offset] + "," + ",".join(missing) + new_sql[offset:]
    added = {column: missing for _offset, column, missing in sorted(insertions)}
    return new_sql, added, []


def widened_table_sql(
    table: str,
    table_sql: str,
    reference: dict[tuple[str, str], list[str]],
) -> tuple[str, dict[str, list[str]]]:
    """Kompatibilitaets-Helfer: (neue DDL, {Spalte: ergaenzte Literale})."""
    new_sql, added, manual = _widen(table, table_sql, _Reference(reference, {}, ()))
    if manual:
        raise DdlParseError("; ".join(manual))
    return new_sql, added


def _widening_is_exact(old_sql: str, new_sql: str, added: dict[str, list[str]]) -> bool:
    """Eigene Aenderung semantisch nachpruefen: nur Werte angehaengt."""
    old_checks = parse_table_ddl(old_sql).checks
    new_checks = parse_table_ddl(new_sql).checks
    if len(old_checks) != len(new_checks):
        return False
    for before, after in zip(old_checks, new_checks):
        if type(before) is not type(after):
            return False
        if isinstance(before, UnsupportedCheck):
            if _canonical(before.text) != _canonical(after.text):
                return False
            continue
        if before.column != after.column or before.nullable_form != after.nullable_form:
            return False
        if after.literals != before.literals + tuple(added.get(before.column, ())):
            return False
    return True


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


@dataclass(frozen=True)
class _Plan:
    old_sql: dict[str, str]
    new_sql: dict[str, str]
    added: dict[str, dict[str, list[str]]]
    manual: tuple[str, ...]


def _plan(target_engine: Engine, reference: _Reference) -> _Plan:
    reference_tables = {table for table, _column in reference.lists} | set(reference.unsupported)
    with target_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL")
        ).fetchall()
    old_sql: dict[str, str] = {}
    new_sql: dict[str, str] = {}
    added: dict[str, dict[str, list[str]]] = {}
    manual: list[str] = list(reference.problems)
    for name, table_sql in rows:
        if name.lower() not in reference_tables:
            continue
        try:
            widened, columns, findings = _widen(name, table_sql, reference)
            if findings:
                manual.extend(findings)
                continue
            if not columns:
                continue
            if not _ddl_parses(widened) or not _widening_is_exact(table_sql, widened, columns):
                manual.append(f"{name}: erweiterte DDL ungueltig")
                continue
        except DdlParseError as exc:
            manual.append(f"{name}: DDL nicht parsebar ({exc})")
            continue
        old_sql[name], new_sql[name], added[name] = table_sql, widened, columns
    return _Plan(old_sql, new_sql, added, tuple(manual))


# --------------------------------------------------------------------------
# Anwenden, Pruefen, Wiederherstellen (Residuum 2)
# --------------------------------------------------------------------------


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


@dataclass(frozen=True)
class _Baseline:
    """Vorbestehende Befunde VOR der Aenderung; danach zaehlen nur NEUE.

    Ohne Baseline wuerde eine Alt-DB mit bereits vorhandenen Verstoessen
    (z.B. Zeilen, die eine CHECK-Liste schon vorher verletzten) auch nach
    nachweislich exakter Ruecksetzung als "nicht wiederhergestellt" gelten.
    """
    integrity: frozenset[str]
    fk: frozenset[tuple]


def _integrity(conn) -> set[str]:
    return {str(row[0]) for row in conn.execute("PRAGMA integrity_check").fetchall()} - {"ok"}


def _baseline(db_file: Path, db_key: str | None, tables: list[str]) -> _Baseline:
    from services.backup import _open_connection

    conn = _open_connection(str(db_file), uri=False, db_key=db_key)
    try:
        return _Baseline(frozenset(_integrity(conn)), frozenset(_fk_violations(conn, tables)))
    finally:
        conn.close()


def _state_problems(
    db_file: Path,
    db_key: str | None,
    expected_sql: dict[str, str],
    baseline: _Baseline,
) -> list[str]:
    """Neue integrity_check-Befunde, erwartete DDL und neue FK-Verstoesse in
    einer frischen Verbindung."""
    from services.backup import _open_connection

    problems: list[str] = []
    conn = _open_connection(str(db_file), uri=False, db_key=db_key)
    try:
        new_integrity = sorted(_integrity(conn) - baseline.integrity)
        if new_integrity:
            problems.append(f"integrity_check: {new_integrity[:5]}")
        for name, table_sql in expected_sql.items():
            stored = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
            ).fetchone()
            if not stored or stored[0] != table_sql:
                problems.append(f"DDL von {name} nicht wie erwartet")
        new_fk = _fk_violations(conn, list(expected_sql)) - baseline.fk
        if new_fk:
            problems.append(f"neue foreign_key_check-Verstoesse: {len(new_fk)}")
    finally:
        conn.close()
    return problems


def _state_problems_safe(*args) -> list[str]:
    try:
        return _state_problems(*args)
    except Exception as exc:  # noqa: BLE001 - nicht pruefbar = nicht verifiziert
        return [f"Zustandspruefung nicht ausfuehrbar: {exc}"]


def _post_change_problems(
    db_file: Path,
    db_key: str | None,
    expected_sql: dict[str, str],
    baseline: _Baseline,
) -> list[str]:
    """Pruefung NACH der Aenderung bzw. nach dem Ruecksetzen."""
    return _state_problems(db_file, db_key, expected_sql, baseline)


def _engine_state_problems(
    target_engine: Engine, expected_sql: dict[str, str], baseline: _Baseline,
) -> list[str]:
    """Pruefung ueber die (neu aufgebaute) Engine selbst."""
    problems: list[str] = []
    with target_engine.connect() as conn:
        rows = conn.execute(text("PRAGMA integrity_check")).fetchall()
        new_integrity = sorted({str(row[0]) for row in rows} - {"ok"} - baseline.integrity)
        if new_integrity:
            problems.append(f"Engine integrity_check: {new_integrity[:5]}")
        for name, table_sql in expected_sql.items():
            stored = conn.execute(
                text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :name"),
                {"name": name},
            ).scalar_one_or_none()
            if stored != table_sql:
                problems.append(f"Engine sieht DDL von {name} nicht wie erwartet")
    return problems


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_copy(source_file: Path, destination_file: Path, db_key: str | None) -> None:
    """SQLite-Backup-API: Ziel wird in einer Schreibtransaktion ersetzt."""
    from services.backup import _open_connection

    source = _open_connection(f"file:{source_file.as_posix()}?mode=ro", uri=True, db_key=db_key)
    try:
        destination = _open_connection(str(destination_file), uri=False, db_key=db_key)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()


def _restore_from_backup(
    target_engine: Engine,
    backup_file: Path,
    db_file: Path,
    db_key: str | None,
    *,
    expected_sql: dict[str, str] | None = None,
    baseline: _Baseline | None = None,
    backup_sha256: str | None = None,
) -> None:
    """Atomare, verifizierte Wiederherstellung; wirft bei jedem Befund.

    1. Pool schliessen. 2. Sicherung gegen den beim Anlegen festgehaltenen
    SHA-256 authentifizieren (ohne bekannten Hash: kein Restore). 3. In eine
    Temp-DB restaurieren und dort voll pruefen. 4. Per Backup-API (eine
    Schreibtransaktion) in die Ziel-DB. 5. Pool neu aufbauen und ueber die
    Engine erneut pruefen.
    """
    target_engine.dispose()
    if backup_sha256 is None or not hmac.compare_digest(_sha256(backup_file), backup_sha256):
        raise BackupAuthenticationError(
            f"Sicherung {backup_file.name} nicht authentisch (SHA-256 abweichend oder unbekannt)"
        )
    expected = expected_sql or {}
    baseline = baseline or _Baseline(frozenset(), frozenset())
    staging = backup_file.with_name(backup_file.stem + ".restore-staging.db")
    try:
        _sqlite_copy(backup_file, staging, db_key)
        staged = _state_problems(staging, db_key, expected, baseline)
        if staged:
            raise RuntimeError(f"Temp-Wiederherstellung fehlerhaft: {staged}")
        _sqlite_copy(staging, db_file, db_key)
    finally:
        for leftover in (staging, Path(f"{staging}-wal"), Path(f"{staging}-shm")):
            try:
                leftover.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                logger.warning("CHECK-Drift: Temp-Datei %s nicht entfernbar: %s", leftover, exc)
    target_engine.dispose()  # Pool neu aufbauen
    after = _state_problems(db_file, db_key, expected, baseline)
    after += _engine_state_problems(target_engine, expected, baseline)
    if after:
        raise RuntimeError(f"Ziel-DB nach Wiederherstellung fehlerhaft: {after}")


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


def _quarantine(
    target_engine: Engine,
    db_file: Path,
    *,
    stamp: str,
    problems: list[str],
    backup_file: Path | None,
    backup_sha256: str | None,
) -> CheckUpgradeResult:
    """DB sperren statt weiterlaufen: Pool zu, Schreibschutz, Evidence-Datei.

    Es wird nichts geloescht oder umbenannt: ein Umbenennen liesse den
    naechsten Start still eine leere DB anlegen. Die Evidence-Datei ist
    zugleich die Startsperre (:func:`raise_if_quarantined`).
    """
    target_engine.dispose()
    read_only = False
    try:
        os.chmod(db_file, stat.S_IREAD)
        read_only = True
    except OSError as exc:
        problems = problems + [f"Schreibschutz nicht setzbar: {exc}"]
    marker = quarantine_marker_path(db_file)
    evidence = {
        "event": MIGRATION_ID,
        "outcome": CheckUpgradeOutcome.FATAL_RECOVERY_FAILED.value,
        "detected_at_utc": stamp,
        "db_file": str(db_file),
        "db_marked_read_only": read_only,
        "backup_file": str(backup_file) if backup_file else None,
        "backup_sha256": backup_sha256,
        "problems": problems,
        "recovery": "manuell aus backup_file wiederherstellen, pruefen, dann diese Datei entfernen",
    }
    try:
        marker.write_text(json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        problems = problems + [f"Quarantaene-Evidence nicht schreibbar: {exc}"]
    logger.critical(
        "CHECK-Drift: Vorzustand nicht wiederherstellbar -- DB quarantaenisiert (%s): %s",
        marker, problems,
    )
    return CheckUpgradeResult(
        CheckUpgradeOutcome.FATAL_RECOVERY_FAILED,
        problems=tuple(problems),
        backup_file=backup_file,
        quarantine_marker=marker,
    )


def upgrade_sqlite_check_in_lists(
    target_engine: Engine,
    schema_path: str | Path | None,
    *,
    backup_dir: str | Path | None = None,
    db_key: str | None = None,
) -> CheckUpgradeResult:
    """Erweitert veraltete CHECK-IN-Listen und liefert ein typisiertes Ergebnis.

    Ablauf (nur wenn wirklich etwas fehlt):
      1. Konsistente Sicherung per SQLite-Backup-API nach
         ``<backup_dir>/5eyes_pre_check_upgrade_<UTC-Zeitstempel>.db``
         (Default ``settings.backup_dir``, ueber
         ``services.backup._perform_atomic_copy``; SQLCipher-faehig; das
         Praefix faellt nicht unter die Rotation). SHA-256 wird sofort
         festgehalten. Scheitert die Sicherung: KEINE Aenderung
         (``SKIPPED_BACKUP_FAILED`` nach Pruefung des Vorzustands).
      2. Aenderung in einer Transaktion (writable_schema).
      3. Pruefung in frischer Verbindung: ``integrity_check``, DDL wie
         erwartet, keine NEUEN ``foreign_key_check``-Verstoesse.
      4. Bei Befund: alte DDL zuruecksetzen und pruefen; sonst verifizierte
         Wiederherstellung aus der Sicherung (beides ``RESTORED_VERIFIED``);
         sonst Quarantaene (``FATAL_RECOVERY_FAILED``).
      5. Log-Eintrag + JSON-Protokoll neben der Sicherung.
    """
    noop = CheckUpgradeResult(CheckUpgradeOutcome.NOOP)
    if target_engine.dialect.name != "sqlite" or not schema_path:
        return noop
    schema_file = Path(schema_path)
    if not schema_file.exists():
        return noop
    db_file = _db_file(target_engine)
    if db_file is None or not db_file.exists():
        return noop
    raise_if_quarantined(db_file)
    reference = _reference(schema_file.read_text(encoding="utf-8"))
    plan = _plan(target_engine, reference)
    if plan.manual:
        logger.error("CHECK-Drift: manuelle Migration erforderlich, DB unveraendert: %s", plan.manual)
        return CheckUpgradeResult(CheckUpgradeOutcome.MANUAL_MIGRATION_REQUIRED, problems=plan.manual)
    if not plan.new_sql:
        return noop
    old_sql, new_sql, added = plan.old_sql, plan.new_sql, plan.added

    from config import settings
    from services.backup import _perform_atomic_copy

    key = db_key if db_key is not None else getattr(settings, "db_key", None)
    try:
        baseline = _baseline(db_file, key, list(new_sql))
    except Exception as exc:  # noqa: BLE001 - nichts geaendert, aber nicht pruefbar
        logger.error("CHECK-Drift: Ausgangszustand nicht pruefbar, DB unveraendert: %s", exc)
        return CheckUpgradeResult(
            CheckUpgradeOutcome.MANUAL_MIGRATION_REQUIRED,
            problems=(f"Ausgangszustand nicht pruefbar: {exc}",),
        )
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
        unchanged = _state_problems_safe(db_file, key, old_sql, baseline)
        if unchanged:
            return _quarantine(
                target_engine, db_file, stamp=stamp, backup_file=None, backup_sha256=None,
                problems=[f"Sicherung fehlgeschlagen: {exc}"] + unchanged,
            )
        return CheckUpgradeResult(
            CheckUpgradeOutcome.SKIPPED_BACKUP_FAILED,
            problems=(f"Sicherung fehlgeschlagen: {exc}",),
        )
    _remove_empty_partial_sidecars(backup_file)
    backup_sha256 = _sha256(backup_file)

    def recover(problems: list[str]) -> CheckUpgradeResult:
        logger.error(
            "CHECK-Drift: Ruecksetzen unsauber %s -- stelle aus %s wieder her", problems, backup_file,
        )
        try:
            _restore_from_backup(
                target_engine, backup_file, db_file, key,
                expected_sql=old_sql, baseline=baseline, backup_sha256=backup_sha256,
            )
        except Exception as exc:  # noqa: BLE001 - fail-closed
            return _quarantine(
                target_engine, db_file, stamp=stamp, backup_file=backup_file,
                backup_sha256=backup_sha256,
                problems=problems + [f"Wiederherstellung fehlgeschlagen: {exc}"],
            )
        logger.error("CHECK-Drift: aus Sicherung %s wiederhergestellt (verifiziert)", backup_file)
        return CheckUpgradeResult(
            CheckUpgradeOutcome.RESTORED_VERIFIED, problems=tuple(problems), backup_file=backup_file,
        )

    try:
        _apply(target_engine, new_sql)
    except Exception as exc:  # noqa: BLE001 - Transaktion sollte zurueckgerollt sein
        logger.error("CHECK-Drift-Reparatur fehlgeschlagen (Rollback): %s", exc)
        unchanged = _state_problems_safe(db_file, key, old_sql, baseline)
        if not unchanged:
            return CheckUpgradeResult(
                CheckUpgradeOutcome.RESTORED_VERIFIED,
                problems=(f"Aenderung zurueckgerollt: {exc}",),
                backup_file=backup_file,
            )
        return recover([f"Aenderung fehlgeschlagen: {exc}"] + unchanged)

    try:
        problems = _post_change_problems(db_file, key, new_sql, baseline)
    except Exception as exc:  # noqa: BLE001
        problems = [f"Pruefung nicht ausfuehrbar: {exc}"]
    if problems:
        logger.error(
            "CHECK-Drift: Pruefung nach Aenderung fehlgeschlagen %s -- setze zurueck", problems,
        )
        try:
            _apply(target_engine, old_sql)
            reverted = _post_change_problems(db_file, key, old_sql, baseline)
        except Exception as exc:  # noqa: BLE001
            reverted = [f"Ruecksetzen fehlgeschlagen: {exc}"]
        if not reverted:
            return CheckUpgradeResult(
                CheckUpgradeOutcome.RESTORED_VERIFIED,
                problems=tuple(problems),
                backup_file=backup_file,
            )
        return recover(problems + reverted)

    report = {
        "event": MIGRATION_ID,
        "applied_at_utc": stamp,
        "backup_file": str(backup_file),
        "backup_sha256": backup_sha256,
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
    return CheckUpgradeResult(
        CheckUpgradeOutcome.APPLIED_VERIFIED, added=added, backup_file=backup_file,
    )


def ensure_sqlite_check_in_lists_current(
    target_engine: Engine,
    schema_path: str | Path | None,
    *,
    backup_dir: str | Path | None = None,
    db_key: str | None = None,
) -> dict[str, dict[str, list[str]]]:
    """Startpfad: wie :func:`upgrade_sqlite_check_in_lists`, aber fail-closed.

    Rueckgabe: {table: {column: [ergaenzte Literale]}} bei
    ``APPLIED_VERIFIED``, sonst leer. ``MANUAL_MIGRATION_REQUIRED`` wirft
    :class:`ManualMigrationRequired`, ``FATAL_RECOVERY_FAILED`` wirft
    :class:`FatalRecoveryFailed` -- ``init_db()`` faehrt dann nicht fort.
    """
    result = upgrade_sqlite_check_in_lists(
        target_engine, schema_path, backup_dir=backup_dir, db_key=db_key,
    )
    raise_if_startup_unsafe(result)
    if result.outcome is CheckUpgradeOutcome.APPLIED_VERIFIED:
        return dict(result.added)
    return {}
