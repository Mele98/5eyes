import hashlib
import logging
import sqlite3
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import QueuePool

from config import DB_KEY_FORMAT_MESSAGE, db_key_format_ok, settings
from core.mandate_evidence_tenant_boundary import (
    MANDATE_BOUND_TENANT_TABLES,
    create_sqlite_guards_after_metadata_create,
    ensure_sqlite_mandate_evidence_tenant_boundary,
    tenant_index_name,
)

try:
    import sqlcipher3  # type: ignore
except ImportError:
    sqlcipher3 = None


SQLCIPHER_AVAILABLE = sqlcipher3 is not None


def resolve_db_file(db_path: str | Path | None = None) -> Path:
    db_file = Path(db_path or settings.db_path).expanduser().resolve()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    return db_file


def resolve_schema_path() -> Path | None:
    pyinstaller_root = Path(getattr(sys, '_MEIPASS', '')) if getattr(sys, '_MEIPASS', None) else None
    candidates = [
        Path(__file__).parent / 'ares_schema.sql',
        Path(__file__).parent.parent / 'ares_schema.sql',
    ]
    if pyinstaller_root:
        candidates.insert(0, pyinstaller_root / 'ares_schema.sql')
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _sqlcipher_enabled(db_key: str | None = None) -> bool:
    key = db_key or getattr(settings, 'db_key', None)
    return bool(getattr(settings, 'db_use_sqlcipher', False) and key)


# SQLCIPHER-KEY-PRAGMA-001 (Pruefrunde #861): SQLite bindet in PRAGMA-Anweisungen
# keine Parameter -- ``PRAGMA key = ?`` ist mit dem echten sqlcipher3 ein
# Syntaxfehler (``near "?"``). Der Schluessel wird deshalb als SQL-Literal mit
# verdoppelten Hochkommas gesetzt (gleiche Form wie der Migrator-Codec); danach
# die Cipher-Parameter in fester Reihenfolge, vor dem ersten Lesezugriff.
# SQLCIPHER-SINGLE-KEY-PATH-001 (Pruefrunde #864, S-1): das ist der EINZIGE Weg,
# auf dem der Schluessel gesetzt wird -- Engine (connect-Event), Rohschema-
# Bootstrap und Backup. Er steht nicht mehr in der URL (quote_plus/unquote machte
# aus einem Leerzeichen still ein "+", das Dialekt-PRAGMA key="..." brach an ").
SQLCIPHER_CIPHER_PRAGMAS = (
    'PRAGMA cipher_page_size = 4096',
    'PRAGMA kdf_iter = 256000',
    'PRAGMA cipher_hmac_algorithm = HMAC_SHA512',
    'PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512',
)


def sqlcipher_key_pragma(key: str) -> str:
    return "PRAGMA key = '" + str(key).replace("'", "''") + "'"


def apply_sqlcipher_key(conn: Any, key: str) -> None:
    """Schluessel + Cipher-Parameter auf eine rohe sqlcipher3-Verbindung setzen.

    Fail-closed: ein Schluessel ausserhalb des erlaubten Formats (config.py,
    SQLCIPHER-DB-KEY-FORMAT-001) wird nie gesetzt; die Meldung nennt ihn nicht.
    """
    if not db_key_format_ok(key):
        raise ValueError(DB_KEY_FORMAT_MESSAGE)
    conn.execute(sqlcipher_key_pragma(key))
    for pragma in SQLCIPHER_CIPHER_PRAGMAS:
        conn.execute(pragma)


def _configured_database_url(database_url: str | None = None) -> str | None:
    configured = database_url if database_url is not None else getattr(settings, "database_url", None)
    if configured and str(configured).strip():
        return str(configured).strip()
    return None


def is_sqlite_database_url(database_url: str) -> bool:
    return database_url.lower().startswith("sqlite")


def is_postgres_database_url(database_url: str) -> bool:
    return database_url.lower().startswith(("postgresql://", "postgresql+"))


def build_database_url(
    db_path: str | Path | None = None,
    db_key: str | None = None,
    database_url: str | None = None,
) -> str:
    configured = _configured_database_url(database_url)
    if configured:
        return configured
    db_file = resolve_db_file(db_path)
    if _sqlcipher_enabled(db_key=db_key):
        if not SQLCIPHER_AVAILABLE:
            raise RuntimeError(
                'DB_USE_SQLCIPHER=true ist gesetzt, aber sqlcipher3 ist nicht installiert. '
                'Installiere sqlcipher3-binary oder sqlcipher3.'
            )
        # SQLCIPHER-SINGLE-KEY-PATH-001: kein Schluessel in der URL; die Engine
        # nutzt den pysqlite-Dialekt mit module=sqlcipher3 und setzt den
        # Schluessel per connect-Event (create_app_engine).
    return f'sqlite:///{db_file}'


def build_connect_args(
    db_key: str | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    _ = db_key
    url = database_url or build_database_url(db_key=db_key)
    if not is_sqlite_database_url(url):
        return {}
    return {'check_same_thread': False, 'timeout': 30}


def attach_sqlite_pragmas(target_engine: Engine, db_key: str | None = None) -> None:
    if _sqlcipher_enabled(db_key=db_key):
        key = db_key or settings.db_key or ''

        # insert=True: vor jedem anderen connect-Handler, auch vor der
        # Dialekt-Initialisierung beim ersten Connect -- der Schluessel muss
        # vor dem ersten Lesezugriff stehen.
        @event.listens_for(target_engine, 'connect', insert=True)
        def _set_sqlcipher_key(dbapi_connection, connection_record):
            apply_sqlcipher_key(dbapi_connection, key)

    @event.listens_for(target_engine, 'connect')
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA foreign_keys = ON')
        cursor.execute('PRAGMA journal_mode = WAL')
        cursor.execute('PRAGMA busy_timeout = 5000')
        cursor.execute('PRAGMA recursive_triggers = OFF')
        cursor.close()


def create_app_engine(
    db_path: str | Path | None = None,
    db_key: str | None = None,
    echo: bool | None = None,
) -> Engine:
    database_url = build_database_url(db_path=db_path, db_key=db_key)
    connect_args = build_connect_args(db_key=db_key, database_url=database_url)
    kwargs: dict[str, Any] = {
        'echo': settings.db_echo if echo is None else echo,
        'pool_timeout': 30,
    }
    if connect_args:
        kwargs['connect_args'] = connect_args
    if is_sqlite_database_url(database_url) and _sqlcipher_enabled(db_key=db_key):
        kwargs['module'] = sqlcipher3
        # SQLCIPHER-ENGINE-POOL-001 (N-861-6): Der pysqlcipher-Dialekt von
        # SQLAlchemy 2.0 waehlte immer SingletonThreadPool (auch fuer eine
        # Datei-DB). Der kennt kein ``pool_timeout`` -> create_engine brach mit
        # TypeError ab und der SQLCipher-Pfad startete nie. Seit S-1 laeuft die
        # verschluesselte DB ueber den pysqlite-Dialekt mit module=sqlcipher3;
        # der Pool ist explizit derselbe wie bei der Klartext-Datei-DB
        # (QueuePool, pool_timeout=30).
        kwargs['poolclass'] = QueuePool
    app_engine = create_engine(database_url, **kwargs)
    if app_engine.dialect.name == "sqlite":
        attach_sqlite_pragmas(app_engine, db_key=db_key)
    elif app_engine.dialect.name.startswith("postgresql"):
        from services.tenant_context import attach_tenant_context_reset
        attach_tenant_context_reset(app_engine)
    return app_engine


engine = create_app_engine(db_path=settings.db_path, db_key=getattr(settings, 'db_key', None))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


def _resolve_engine(target_engine: Engine | None = None) -> Engine:
    """DB-ENGINE-DEFAULT-BINDING-001: Ziel-Engine zur AUFRUFZEIT aufloesen.

    Ein Default-Argument ``target_engine=engine`` wird beim Import gebunden und
    zeigt danach fuer immer auf die DB, die beim ersten Import konfiguriert war
    -- auch wenn ``database.engine`` spaeter umgebogen wurde. Schema-Schritte
    nehmen deshalb ``None`` als Default und loesen hier ueber die Modul-Engine
    ``database.engine`` auf (aus ``settings.db_path``/``DB_PATH`` gebaut; Tests
    ersetzen genau diese per monkeypatch).
    """
    return target_engine if target_engine is not None else engine


def _session_for(target_engine: Engine | None = None) -> Session:
    """Session auf ``target_engine``; ohne Argument unveraendert ``SessionLocal()``."""
    if target_engine is None:
        return SessionLocal()
    return sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=target_engine,
    )()


logger = logging.getLogger(__name__)

# SEED-FK-HYGIENE (2026-11-05): Seeds/Backfills beim Start verschluckten jede
# Ausnahme (``except Exception: pass``). So fiel der DE-Seed unter
# PRAGMA foreign_keys=ON still aus. Jetzt gezielt: nur "Schema noch nicht da"
# (Tabelle/Spalte fehlt in einer alten/partiellen DB) wird mit WARNING
# uebersprungen; jeder andere Fehler (Integritaet, FK, Unique, Programmfehler)
# wird mit ERROR geloggt und bricht den Start ab (fail-closed).
_SCHEMA_NOT_READY_MARKERS = (
    "no such table",
    "no such column",
    "has no column named",
    "undefinedtable",
    "undefinedcolumn",
)


def _db_error_summary(exc: BaseException) -> str:
    """Kurzform fuer Logs: Fehlerklasse + erste Zeile der Treibermeldung.
    Ohne SQL-Parameter (str(exc) von SQLAlchemy haengt sie an)."""
    orig = getattr(exc, "orig", None)
    detail = str(orig if orig is not None else "").strip().splitlines()
    first = detail[0][:200] if detail else ""
    return f"{type(exc).__name__}: {first}" if first else type(exc).__name__


def _is_schema_not_ready(exc: BaseException) -> bool:
    if not isinstance(exc, (OperationalError, ProgrammingError)):
        return False
    orig = getattr(exc, "orig", None)
    text_ = f"{type(orig).__name__} {orig}".lower()
    return any(marker in text_ for marker in _SCHEMA_NOT_READY_MARKERS) or (
        "does not exist" in text_ and ("relation" in text_ or "column" in text_)
    )


def _handle_startup_step_error(step: str, exc: BaseException) -> None:
    """Fehler eines Start-Seeds/-Backfills behandeln: Schema-nicht-bereit ->
    WARNING und weiter; alles andere -> ERROR und erneut ausloesen."""
    if _is_schema_not_ready(exc):
        logger.warning("Startschritt %s uebersprungen (Schema unvollstaendig): %s",
                       step, _db_error_summary(exc))
        return
    logger.error("Startschritt %s fehlgeschlagen, Start abgebrochen: %s",
                 step, _db_error_summary(exc))
    raise exc


class Base(DeclarativeBase):
    pass


# PG-002: Mandanten-/Kundenschutz beim INSERT fuer die append-only
# Mandats-Evidenz (core/mandate_evidence_tenant_boundary.py). Metadata-Hook:
# laeuft nach create_all, wenn mandates und alle Evidenztabellen existieren.
event.listen(Base.metadata, "after_create", create_sqlite_guards_after_metadata_create)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            from services.tenant_context import reset_tenant_context
            reset_tenant_context(db)
        except Exception:
            pass
        db.close()


def new_uuid() -> str:
    return str(uuid.uuid4())


def bootstrap_sqlite_schema(
    db_path: str | Path | None = None,
    schema_path: str | Path | None = None,
    db_key: str | None = None,
) -> None:
    schema_file = Path(schema_path) if schema_path else resolve_schema_path()
    if not schema_file or not schema_file.exists():
        return

    db_file = resolve_db_file(db_path)
    sql = schema_file.read_text(encoding='utf-8')

    if _sqlcipher_enabled(db_key=db_key):
        if not SQLCIPHER_AVAILABLE:
            raise RuntimeError(
                'DB_USE_SQLCIPHER=true ist gesetzt, aber sqlcipher3 ist nicht installiert. '
                'Installiere sqlcipher3-binary oder sqlcipher3.'
            )
        key = db_key or settings.db_key or ''
        if not db_key_format_ok(key):
            raise ValueError(DB_KEY_FORMAT_MESSAGE)
        with sqlcipher3.connect(str(db_file)) as conn:
            apply_sqlcipher_key(conn, key)
            conn.execute('PRAGMA foreign_keys = OFF')
            try:
                conn.executescript(sql)
            except sqlcipher3.IntegrityError as exc:
                _raise_explained_bootstrap_integrity_error(conn, exc)
                raise
            conn.execute('PRAGMA foreign_keys = ON')
            conn.commit()
        return

    with sqlite3.connect(str(db_file)) as conn:
        conn.execute('PRAGMA foreign_keys = OFF')
        try:
            conn.executescript(sql)
        except sqlite3.IntegrityError as exc:
            _raise_explained_bootstrap_integrity_error(conn, exc)
            raise
        conn.execute('PRAGMA foreign_keys = ON')
        conn.commit()


def _raise_explained_bootstrap_integrity_error(conn, exc: Exception) -> None:
    """N-873-06: Scheitert der Schema-Bootstrap am Unique-Index
    ``ux_goals_rank_active`` (Bestand mit doppelten aktiven Zielraengen, nur
    moeglich, wenn der Index einer Installation je fehlte), bricht der Start
    weiterhin ab (fail-closed) -- aber mit klarer Betreibermeldung statt
    eines rohen IntegrityError. Andere Integritaetsfehler bleiben unveraendert."""
    text_ = str(exc)
    if "goals.mandate_id, goals.rank" not in text_ and "ux_goals_rank_active" not in text_:
        return
    try:
        rows = conn.execute(
            "SELECT mandate_id, rank, count(*) FROM goals "
            "WHERE is_active = 1 AND deleted_at IS NULL "
            "GROUP BY mandate_id, rank HAVING count(*) > 1 ORDER BY mandate_id, rank LIMIT 50"
        ).fetchall()
    except Exception:  # noqa: BLE001 - Diagnose darf die Meldung nicht verhindern
        rows = []
    listed = ", ".join(f"{mid}/{rank}/{n}" for mid, rank, n in rows) or "nicht ermittelbar"
    message = (
        "Datenbankstart abgebrochen: doppelte aktive Zielraenge verhindern den "
        "Unique-Index ux_goals_rank_active (Mandat/Rang/Anzahl: "
        f"{listed}). Bitte vor dem naechsten Start je betroffenem Mandat die "
        "Rangfolge bereinigen (Backup zuerst; Raenge eindeutig machen), dann "
        "neu starten. Ohne Index waeren Hauptziel und Gewichte nicht "
        "deterministisch."
    )
    logger.critical(message)
    raise RuntimeError(message) from exc


class SchemaNotReadyError(RuntimeError):
    """OPS-005: DB ist erreichbar, aber Schema/Migrationsstand passt nicht
    zur laufenden Code-Version (z.B. Migration noch nicht abgeschlossen)."""


def _expected_alembic_head() -> str | None:
    """OPS-005 (Codex-Audit 2026-08-25): einmalig ermittelter Soll-Revisions-
    Kopf der eingecheckten Migrationskette -- Vergleichswert fuer
    database_healthcheck(), damit die Readiness-Probe eine noch nicht
    angewendete/laufende Postgres-Migration erkennt statt nur die
    Verbindung zu pruefen."""
    from alembic.config import Config as AlembicConfig
    from alembic.script import ScriptDirectory

    alembic_ini = Path(__file__).resolve().parent / "alembic.ini"
    alembic_cfg = AlembicConfig(str(alembic_ini))
    return ScriptDirectory.from_config(alembic_cfg).get_current_head()


def database_healthcheck(db: Session) -> dict[str, str]:
    """SELECT 1 beweist nur, dass die Verbindung offen ist -- nicht, dass
    das Schema zur laufenden Code-Version passt. OPS-005 (Codex-Audit
    2026-08-25): unter Postgres mit mehreren Workern kann ein Worker schon
    Traffic annehmen, waehrend ein anderer noch mitten in `alembic upgrade
    head` steckt (siehe PG-004/PG-005) -- die alte Readiness-Probe haette
    das nicht gesehen. Zusaetzlich zur Verbindungspruefung: Postgres
    vergleicht die angewendete `alembic_version` gegen den erwarteten Kopf
    der Migrationskette; SQLite (kein Alembic-Pfad, siehe
    _create_or_migrate_schema) liest stattdessen eine Kern-Tabelle, um ein
    fehlendes/kaputtes Schema von einer bloss langsamen Verbindung zu
    unterscheiden."""
    db.execute(text('SELECT 1'))
    bind = db.get_bind()
    if is_postgres_database_url(str(bind.url)):
        applied = db.execute(text('SELECT version_num FROM alembic_version')).scalar()
        expected = _expected_alembic_head()
        if applied != expected:
            raise SchemaNotReadyError(
                f"Schema nicht auf dem erwarteten Stand (angewendet={applied!r}, "
                f"erwartet={expected!r}) -- Migration laeuft noch oder wurde nicht ausgefuehrt."
            )
    else:
        db.execute(text('SELECT 1 FROM mandates LIMIT 1'))
    return {'database': 'ok'}


def ensure_column(conn, table_name: str, column_name: str, sql_type: str) -> None:
    if not re.match(r'^[a-z][a-z0-9_]+$', table_name):
        raise ValueError(f"Ungueltiger Tabellenname: {table_name!r}")
    if not re.match(r'^[a-z][a-z0-9_]+$', column_name):
        raise ValueError(f"Ungueltiger Spaltenname: {column_name!r}")
    if not re.match(r'^[A-Z]+$', sql_type):
        raise ValueError(f"Ungueltiger SQL-Typ: {sql_type!r}")
    existing = {row[1] for row in conn.execute(text(f'PRAGMA table_info({table_name})')).fetchall()}
    if column_name in existing:
        return
    conn.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}'))


# ESG-PREMIUM-CRITERIA-001 (2026-10-14): (sub_asset_class, theme_tags-JSON)
# fuer den Backfill bestehender Themenprodukte. Bewusst als Literal hier
# (database.py importiert keine services/), synchron mit
# services/portfolio_engine_payload.py::THEME_SUB_ASSET_CLASSES -- per Test
# gepinnt (tests/test_esg_premium_criteria.py).
PRODUCT_INTERNAL_ID_INDEX = "ux_products_tenant_internal_id"
PRODUCT_INTERNAL_ID_INDEX_DDL = (
    f"CREATE UNIQUE INDEX IF NOT EXISTS {PRODUCT_INTERNAL_ID_INDEX} "
    "ON products(tenant_id, internal_product_id) "
    "WHERE internal_product_id IS NOT NULL AND deleted_at IS NULL"
)

THEME_TAG_BACKFILL: tuple[tuple[str, str], ...] = (
    ("Thema Fossile Energie", '["fossil"]'),
    ("Thema Verteidigung", '["defense"]'),
    ("Thema Tabak", '["tobacco"]'),
    ("Thema Alkohol", '["alcohol"]'),
    ("Thema Gluecksspiel", '["gaming"]'),
    ("Thema Kernenergie", '["nuclear"]'),
)


# RISK-OVERRIDE-WRITE-BOUNDARY-001 Restbefund B (2026-10-19): append-only
# RiskOverrideDecisionV1 (models/profiling.py::RiskOverrideDecision). Die
# Trigger werden hier EINMAL definiert und vom Model (after_create fuer
# create_all) sowie von ensure_runtime_columns() (Alt-DBs / Rohschema-
# Fixtures) verwendet; ares_schema.sql traegt dieselbe DDL fuer
# frische Installationen, Alembic c4e9a7d2b815 fuer PostgreSQL.
RISK_OVERRIDE_DECISION_SQLITE_TRIGGERS: tuple[str, ...] = (
    "CREATE TRIGGER IF NOT EXISTS trg_risk_override_decisions_no_update "
    "BEFORE UPDATE ON risk_override_decisions FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'risk_override_decisions is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_risk_override_decisions_no_delete "
    "BEFORE DELETE ON risk_override_decisions FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'risk_override_decisions is immutable'); END",
)

RISK_OVERRIDE_DECISION_SQLITE_TABLE_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS risk_override_decisions (
    id                           TEXT PRIMARY KEY,
    schema_version               TEXT NOT NULL DEFAULT 'RiskOverrideDecisionV1',
    assessment_id                TEXT NOT NULL,
    mandate_id                   TEXT NOT NULL,
    client_id                    TEXT,
    tenant_id                    TEXT,
    assessment_version           INTEGER NOT NULL,
    sequence_no                  INTEGER NOT NULL CHECK(sequence_no >= 1),
    previous_decision_id         TEXT,
    basis_final_score_x10        INTEGER NOT NULL,
    basis_final_profile          TEXT,
    basis_capacity_score_x10     INTEGER,
    basis_willingness_score_x10  INTEGER,
    requested_score_x10          INTEGER NOT NULL CHECK(requested_score_x10 BETWEEN 0 AND 100),
    requested_profile            TEXT NOT NULL,
    reason                       TEXT NOT NULL,
    client_confirmed             INTEGER NOT NULL DEFAULT 0 CHECK(client_confirmed IN (0,1)),
    warning_delivered            INTEGER NOT NULL DEFAULT 0 CHECK(warning_delivered IN (0,1)),
    warning_document_id          TEXT,
    required_client_confirmation INTEGER NOT NULL DEFAULT 0 CHECK(required_client_confirmation IN (0,1)),
    required_warning             INTEGER NOT NULL DEFAULT 0 CHECK(required_warning IN (0,1)),
    actor_id                     TEXT NOT NULL REFERENCES users(id),
    decided_at                   TEXT NOT NULL,
    rules_version                TEXT NOT NULL,
    decision_hash                TEXT NOT NULL,
    created_at                   TEXT NOT NULL
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_risk_override_decision_sequence "
    "ON risk_override_decisions(assessment_id, sequence_no)",
    "CREATE INDEX IF NOT EXISTS ix_risk_override_decisions_mandate "
    "ON risk_override_decisions(mandate_id)",
)
# PG-002 (Codex-Closure-Review PR #662): Index der nachgezogenen tenant_id;
# erst NACH ensure_column ausfuehrbar (Alt-DBs ohne die Spalte).
RISK_OVERRIDE_DECISION_SQLITE_TENANT_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_risk_override_decisions_tenant_id "
    "ON risk_override_decisions(tenant_id)"
)


# RISK-CAPACITY-PLAUSIBILITY-001 Restbefund A (Codex-Closure-Review PR #653,
# 2026-10-20): append-only FinancialCoverageAttestationV1
# (models/wealth.py::FinancialCoverageAttestation). Erfasste Cashflow-Zeilen
# beweisen keine vollstaendige Haushaltserfassung; erst diese Berater-
# Bestaetigung (gehasht, an den Cashflow-Fingerprint gebunden) macht die
# Ausgaben-Coverage zu "recorded". Muster wie risk_override_decisions: kein
# FK auf mandates/clients (Purge-fest), nur actor_id -> users; dieselbe DDL
# in ares_schema.sql, Alembic f3a8d1c6b4e2 fuer PostgreSQL.
FINANCIAL_COVERAGE_ATTESTATION_SQLITE_TRIGGERS: tuple[str, ...] = (
    "CREATE TRIGGER IF NOT EXISTS trg_financial_coverage_attestations_no_update "
    "BEFORE UPDATE ON financial_coverage_attestations FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'financial_coverage_attestations is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_financial_coverage_attestations_no_delete "
    "BEFORE DELETE ON financial_coverage_attestations FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'financial_coverage_attestations is immutable'); END",
)

FINANCIAL_COVERAGE_ATTESTATION_SQLITE_TABLE_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS financial_coverage_attestations (
    id                          TEXT PRIMARY KEY,
    schema_version              TEXT NOT NULL DEFAULT 'FinancialCoverageAttestationV1',
    mandate_id                  TEXT NOT NULL,
    client_id                   TEXT NOT NULL,
    household_persons_json      TEXT NOT NULL,
    household_person_count      INTEGER,
    income_complete             INTEGER NOT NULL CHECK(income_complete IN (0,1)),
    expenses_complete           INTEGER NOT NULL CHECK(expenses_complete IN (0,1)),
    obligations_complete        INTEGER NOT NULL CHECK(obligations_complete IN (0,1)),
    irregular_expenses_reviewed INTEGER NOT NULL CHECK(irregular_expenses_reviewed IN (0,1)),
    as_of_date                  TEXT NOT NULL,
    source                      TEXT NOT NULL,
    note                        TEXT,
    cashflow_fingerprint        TEXT NOT NULL,
    cashflow_row_count          INTEGER NOT NULL,
    actor_id                    TEXT NOT NULL REFERENCES users(id),
    attested_at                 TEXT NOT NULL,
    policy_version              TEXT NOT NULL,
    attestation_hash            TEXT NOT NULL,
    created_at                  TEXT NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS ix_financial_coverage_attestations_mandate "
    "ON financial_coverage_attestations(mandate_id, attested_at)",
)

# CMA-001 (Entscheidungsdokument 2026-10-27): Freigaben einer CMA_POLICY sind
# unveraenderlich (models/cma_policy.py::CmaPolicyApproval). Model
# (after_create) und ensure_runtime_columns() verwenden diese Konstante;
# Alembic b5d2e8f1c4a7 fuer PostgreSQL.
CMA_POLICY_APPROVAL_SQLITE_TRIGGERS: tuple[str, ...] = (
    "CREATE TRIGGER IF NOT EXISTS trg_cma_policy_approvals_no_update "
    "BEFORE UPDATE ON cma_policy_approvals FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'cma_policy_approvals is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_cma_policy_approvals_no_delete "
    "BEFORE DELETE ON cma_policy_approvals FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'cma_policy_approvals is immutable'); END",
)

# DEPOT-E2E-SNAPSHOT-001 / DEPOT-E2E-STRESS-001 Option 2: append-only
# DepotSnapshotV1 (models/snapshots.py::DepotSnapshot,
# services/depot_snapshot.py). Haelt den hash-gebundenen IST-Bestand, auf
# dem der IST-Stress abgespielt wird. Kein FK auf mandates/clients
# (Purge-fest), nur created_by -> users; dieselbe DDL in
# Bootstrap-Schema (ares_schema.sql), Alembic c8e2f4a6b1d3 fuer PostgreSQL.
DEPOT_SNAPSHOT_SQLITE_TRIGGERS: tuple[str, ...] = (
    "CREATE TRIGGER IF NOT EXISTS trg_depot_snapshots_no_update "
    "BEFORE UPDATE ON depot_snapshots FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'depot_snapshots is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_depot_snapshots_no_delete "
    "BEFORE DELETE ON depot_snapshots FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'depot_snapshots is immutable'); END",
)

DEPOT_SNAPSHOT_SQLITE_TABLE_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS depot_snapshots (
    id              TEXT PRIMARY KEY,
    schema_version  TEXT NOT NULL DEFAULT 'DepotSnapshotV1',
    tenant_id       TEXT,
    mandate_id      TEXT NOT NULL,
    client_id       TEXT NOT NULL,
    as_of_date      TEXT NOT NULL,
    currency        TEXT NOT NULL,
    source          TEXT NOT NULL,
    snapshot_json   TEXT NOT NULL,
    snapshot_hash   TEXT NOT NULL,
    created_by      TEXT NOT NULL REFERENCES users(id),
    created_at      TEXT NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS ix_depot_snapshots_mandate "
    "ON depot_snapshots(mandate_id, as_of_date)",
)

# DEPOT-E2E-SNAPSHOT-001: append-only DepotCheckAnalysisSnapshot
# (models/snapshots.py::DepotCheckAnalysisSnapshot,
# services/depot_check_snapshot.py). Depot-Check-Ergebnis, gebunden an genau
# einen DepotSnapshotV1; JSON und PDF lesen dieselbe Zeile. Kein FK auf
# mandates/clients/depot_snapshots (Purge-fest, Bindung per Hash), nur
# created_by -> users; dieselbe DDL im Bootstrap-Schema, Alembic e7a3c9d1b5f2.
DEPOT_CHECK_ANALYSIS_SQLITE_TRIGGERS: tuple[str, ...] = (
    "CREATE TRIGGER IF NOT EXISTS trg_depot_check_analysis_snapshots_no_update "
    "BEFORE UPDATE ON depot_check_analysis_snapshots FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'depot_check_analysis_snapshots is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_depot_check_analysis_snapshots_no_delete "
    "BEFORE DELETE ON depot_check_analysis_snapshots FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'depot_check_analysis_snapshots is immutable'); END",
)

DEPOT_CHECK_ANALYSIS_SQLITE_TABLE_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS depot_check_analysis_snapshots (
    id                  TEXT PRIMARY KEY,
    schema_version      TEXT NOT NULL DEFAULT 'DepotCheckAnalysisV1',
    tenant_id           TEXT,
    mandate_id          TEXT NOT NULL,
    client_id           TEXT NOT NULL,
    depot_snapshot_id   TEXT NOT NULL,
    depot_snapshot_hash TEXT NOT NULL,
    as_of_date          TEXT NOT NULL,
    analysis_json       TEXT NOT NULL,
    analysis_hash       TEXT NOT NULL,
    result_hash         TEXT NOT NULL,
    created_by          TEXT NOT NULL REFERENCES users(id),
    created_at          TEXT NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS ix_depot_check_analysis_snapshots_mandate "
    "ON depot_check_analysis_snapshots(mandate_id, created_at)",
)

# RISK-PROFILE-SIGNOFF-001 (Codex-Closure-Review zu PR #657, 2026-10-20):
# append-only RiskProfileSignoffV1 (models/profiling.py::RiskProfileSignoff).
# Gleiches Muster wie risk_override_decisions: Trigger verbieten UPDATE/
# DELETE, KEIN harter FK auf risk_assessments/mandates (Purge-fest wie
# audit_log), nur actor_id -> users. Die DDL wird hier EINMAL definiert und
# vom Model (after_create), von ensure_runtime_columns() und -- textgleich --
# von ares_schema.sql verwendet; Alembic d7b3f1a9c2e4 fuer
# PostgreSQL.
RISK_PROFILE_SIGNOFF_SQLITE_TRIGGERS: tuple[str, ...] = (
    "CREATE TRIGGER IF NOT EXISTS trg_risk_profile_signoffs_no_update "
    "BEFORE UPDATE ON risk_profile_signoffs FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'risk_profile_signoffs is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_risk_profile_signoffs_no_delete "
    "BEFORE DELETE ON risk_profile_signoffs FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'risk_profile_signoffs is immutable'); END",
)

RISK_PROFILE_SIGNOFF_SQLITE_TABLE_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS risk_profile_signoffs (
    id                     TEXT PRIMARY KEY,
    schema_version         TEXT NOT NULL DEFAULT 'RiskProfileSignoffV1',
    assessment_id          TEXT NOT NULL,
    mandate_id             TEXT NOT NULL,
    client_id              TEXT,
    tenant_id              TEXT,
    assessment_version     INTEGER NOT NULL,
    sequence_no            INTEGER NOT NULL CHECK(sequence_no >= 1),
    previous_signoff_id    TEXT,
    effective_score_x10    INTEGER NOT NULL CHECK(effective_score_x10 BETWEEN 0 AND 100),
    effective_profile      TEXT NOT NULL,
    final_score_x10        INTEGER NOT NULL,
    final_profile          TEXT,
    is_overridden          INTEGER NOT NULL DEFAULT 0 CHECK(is_overridden IN (0,1)),
    override_binding       TEXT NOT NULL CHECK(override_binding IN ('decision','no_override')),
    override_decision_id   TEXT,
    override_decision_hash TEXT,
    override_rules_version TEXT,
    assessment_input_hash  TEXT NOT NULL,
    document_id            TEXT,
    document_hash          TEXT,
    method                 TEXT NOT NULL CHECK(method IN ('advisor_recorded','portal')),
    evidence_level         TEXT NOT NULL CHECK(evidence_level IN ('advisor_attested','client_portal')),
    actor_id               TEXT NOT NULL REFERENCES users(id),
    actor_role             TEXT,
    note                   TEXT,
    signed_at              TEXT NOT NULL,
    rules_version          TEXT NOT NULL,
    signoff_hash           TEXT NOT NULL,
    created_at             TEXT NOT NULL,
    CHECK((override_binding = 'decision' AND override_decision_id IS NOT NULL AND override_decision_hash IS NOT NULL)
          OR (override_binding = 'no_override' AND override_decision_id IS NULL AND override_decision_hash IS NULL))
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_risk_profile_signoff_sequence "
    "ON risk_profile_signoffs(assessment_id, sequence_no)",
    "CREATE INDEX IF NOT EXISTS ix_risk_profile_signoffs_mandate "
    "ON risk_profile_signoffs(mandate_id)",
)
RISK_PROFILE_SIGNOFF_SQLITE_TENANT_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_risk_profile_signoffs_tenant_id "
    "ON risk_profile_signoffs(tenant_id)"
)

# Altbestand: eine Signatur ohne RiskProfileSignoffV1-Snapshot bleibt sichtbar,
# wird aber ausdruecklich als "Altsignatur, nicht an Decision gebunden"
# markiert (idempotent; Alembic d7b3f1a9c2e4 fuehrt dasselbe UPDATE aus).
RISK_PROFILE_SIGNOFF_LEGACY_BACKFILL = (
    "UPDATE risk_assessments SET signoff_status = 'legacy_unbound' "
    "WHERE client_signed_at IS NOT NULL AND signoff_id IS NULL "
    "AND signoff_status IS NULL"
)


# DSG-ERASURE-APPEND-ONLY-001 (2026-10-21): Schluessel pro Kunde fuer das
# Crypto-Shredding der Freitexte in append-only Evidence-Tabellen
# (services/pii_vault.py). Bewusst VERAENDERBAR (die Erasure muss den
# Schluessel vernichten koennen), aber nur in eine Richtung: der Trigger
# erlaubt ausschliesslich das Vernichten (key_material -> NULL), nie das
# Setzen/Ersetzen eines Schluessels oder das Umhaengen auf einen anderen
# Kunden -- ein vernichteter Schluessel kann nicht "wiederbelebt" werden.
# DELETE ist verboten, damit der Tombstone (shredded_at) als Nachweis der
# Vernichtung stehen bleibt und seal_for_client() fuer geloeschte Kunden
# fail-closed bleibt. Kein FK auf clients (Purge-fest wie audit_log).
# Alembic e8a4c2f7d913 fuer PostgreSQL.
CLIENT_PII_KEYS_SQLITE_TABLE_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS client_pii_keys (
    client_id     TEXT PRIMARY KEY,
    key_id        TEXT NOT NULL UNIQUE,
    key_material  TEXT,
    created_at    TEXT NOT NULL,
    shredded_at   TEXT,
    CHECK ((key_material IS NULL) = (shredded_at IS NOT NULL))
)""",
)

CLIENT_PII_KEYS_SQLITE_TRIGGERS: tuple[str, ...] = (
    "CREATE TRIGGER IF NOT EXISTS trg_client_pii_keys_shred_only "
    "BEFORE UPDATE ON client_pii_keys FOR EACH ROW "
    "WHEN NEW.client_id IS NOT OLD.client_id OR NEW.key_id IS NOT OLD.key_id "
    "OR (NEW.key_material IS NOT NULL AND NEW.key_material IS NOT OLD.key_material) "
    "OR (OLD.shredded_at IS NOT NULL AND NEW.shredded_at IS NOT OLD.shredded_at) "
    "BEGIN SELECT RAISE(ABORT, 'client_pii_keys is shred-only'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_client_pii_keys_no_delete "
    "BEFORE DELETE ON client_pii_keys FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'client_pii_keys is shred-only'); END",
)


# GOAL-REVISION-DECISION-001 (CIO-Entscheid 2026-10-21, Codex-Closure-Review
# zu PR #655): append-only GoalRevisionDecisionV1 (models/wealth.py::
# GoalRevisionDecision). Einzige Quelle einer Herabstufung eines Ziels zum
# nachrangigen Wunschziel. Gleiches Muster wie risk_override_decisions:
# Trigger verbieten UPDATE/DELETE, KEIN harter FK auf goals/mandates
# (Purge-fest), nur actor_id -> users. Die DDL wird hier EINMAL definiert und
# vom Model (after_create), von ensure_runtime_columns() und -- textgleich --
# von ares_schema.sql verwendet; Alembic e3c7a91f5b28 fuer
# PostgreSQL.
GOAL_REVISION_DECISION_SQLITE_TRIGGERS: tuple[str, ...] = (
    "CREATE TRIGGER IF NOT EXISTS trg_goal_revision_decisions_no_update "
    "BEFORE UPDATE ON goal_revision_decisions FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'goal_revision_decisions is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_goal_revision_decisions_no_delete "
    "BEFORE DELETE ON goal_revision_decisions FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'goal_revision_decisions is immutable'); END",
)

GOAL_REVISION_DECISION_SQLITE_TABLE_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS goal_revision_decisions (
    id                            TEXT PRIMARY KEY,
    schema_version                TEXT NOT NULL DEFAULT 'GoalRevisionDecisionV1',
    goal_id                       TEXT NOT NULL,
    mandate_id                    TEXT NOT NULL,
    client_id                     TEXT,
    sequence_no                   INTEGER NOT NULL CHECK(sequence_no >= 1),
    previous_decision_id          TEXT,
    goal_snapshot_hash            TEXT NOT NULL,
    goal_snapshot_json            TEXT NOT NULL,
    previous_hardness             TEXT NOT NULL,
    new_status                    TEXT NOT NULL CHECK(new_status IN ('nachrangiges_wunschziel')),
    reason                        TEXT NOT NULL,
    evidence_status               TEXT NOT NULL,
    evidence_best_probability_bps INTEGER,
    evidence_wilson_upper_bps     INTEGER,
    evidence_tau_bps              INTEGER,
    evidence_engine_version       TEXT NOT NULL,
    evidence_allocation_id        TEXT,
    evidence_screening_cube_hash  TEXT,
    actor_id                      TEXT NOT NULL REFERENCES users(id),
    decided_at                    TEXT NOT NULL,
    rules_version                 TEXT NOT NULL,
    decision_hash                 TEXT NOT NULL,
    created_at                    TEXT NOT NULL
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_goal_revision_decision_sequence "
    "ON goal_revision_decisions(goal_id, sequence_no)",
    "CREATE INDEX IF NOT EXISTS ix_goal_revision_decisions_mandate "
    "ON goal_revision_decisions(mandate_id)",
)


# RISK-CAPACITY-EVALUATION-SNAPSHOT-001 (Codex-Closure-Reviews PR #647/#653/
# #677, Residual "Bewertung live und ungehasht"): append-only
# RiskCapacityPlausibilityEvaluationV1 (models/profiling.py::
# RiskCapacityPlausibilityEvaluation). Jede beim Speichern des Risikoprofils
# bzw. bei der Generierung gebundene Plausibilitaetsbewertung mit Eingaben,
# Regelversion, Ergebnis und kanonischem Hash. Gleiches Muster wie
# risk_profile_signoffs: Trigger verbieten UPDATE/DELETE, KEIN harter FK auf
# mandates/risk_assessments (Purge-fest), nur actor_id -> users; tenant_id
# direkt (RLS). Dieselbe DDL textgleich in ares_schema.sql,
# Alembic a7c4e9b2d1f3 fuer PostgreSQL.
RISK_CAPACITY_EVALUATION_SQLITE_TRIGGERS: tuple[str, ...] = (
    "CREATE TRIGGER IF NOT EXISTS trg_risk_capacity_plausibility_evaluations_no_update "
    "BEFORE UPDATE ON risk_capacity_plausibility_evaluations FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'risk_capacity_plausibility_evaluations is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_risk_capacity_plausibility_evaluations_no_delete "
    "BEFORE DELETE ON risk_capacity_plausibility_evaluations FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'risk_capacity_plausibility_evaluations is immutable'); END",
)

RISK_CAPACITY_EVALUATION_SQLITE_TABLE_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS risk_capacity_plausibility_evaluations (
    id                 TEXT PRIMARY KEY,
    schema_version     TEXT NOT NULL DEFAULT 'RiskCapacityPlausibilityEvaluationV1',
    tenant_id          TEXT,
    mandate_id         TEXT NOT NULL,
    client_id          TEXT,
    assessment_id      TEXT,
    binding_context    TEXT NOT NULL CHECK(binding_context IN ('risk_assessment_saved','allocation_generated')),
    binding_record_id  TEXT NOT NULL,
    as_of_date         TEXT NOT NULL,
    rules_version      TEXT NOT NULL,
    status             TEXT NOT NULL,
    inputs_json        TEXT,
    inputs_hash        TEXT,
    result_json        TEXT NOT NULL,
    evaluation_hash    TEXT,
    actor_id           TEXT NOT NULL REFERENCES users(id),
    evaluated_at       TEXT NOT NULL,
    snapshot_hash      TEXT NOT NULL,
    created_at         TEXT NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS ix_risk_capacity_plausibility_evaluations_mandate "
    "ON risk_capacity_plausibility_evaluations(mandate_id, evaluated_at)",
    "CREATE INDEX IF NOT EXISTS ix_risk_capacity_plausibility_evaluations_tenant_id "
    "ON risk_capacity_plausibility_evaluations(tenant_id)",
)


# N-869-4: einmaliger Nachtrag von audit_log_sequence_counter.last_hash aus der
# Zeile mit sequence = value (nur solange last_hash noch NULL ist). Gleiche
# Anweisung in Alembic c8a2f4e6b0d9 (dort unter Operator-Bypass, RLS).
_COUNTER_LAST_HASH_BACKFILL_SQL = (
    "UPDATE audit_log_sequence_counter SET last_hash = ("
    "SELECT a.integrity_hash FROM audit_log a "
    "WHERE a.sequence = audit_log_sequence_counter.value ORDER BY a.id LIMIT 1) "
    "WHERE id = 'singleton' AND last_hash IS NULL AND value > 0"
)


def ensure_runtime_columns(target_engine: Engine | None = None) -> None:
    target_engine = _resolve_engine(target_engine)
    additive_columns: dict[str, list[tuple]] = {  # (name, TYPE) oder (name, TYPE, int_default)
        # Sprint T1 (2026-06-08): tenant_id fuer 3-Tier-Architektur.
        # Bootstrap-SQL hat das Feld noch nicht — Migration ergaenzt die
        # Column idempotent auf Live-DBs, sonst koennen Tier-2-Endpoints
        # den tenant-Scope nicht setzen und frische Installationen
        # crashen beim User-Anlegen.
        'users': [
            ('tenant_id', 'TEXT'),
            # E1 (2026-06-13): TOTP-2FA fuer externe Logins.
            ('totp_secret', 'TEXT'),
            ('totp_enabled', 'INTEGER'),
            # E1 (2026-06-14): erzwungener Passwortwechsel beim ersten Login.
            ('must_change_password', 'INTEGER'),
            # E1 (2026-06-14): Invite-Link-Onboarding (Token-Hash + Ablauf).
            ('invite_token_hash', 'TEXT'),
            ('invite_expires_at', 'TEXT'),
            # #25/#27 (2026-06-15): Self-Service Passwort-Reset + 2FA-Recovery-Codes.
            # MUSS hier (Startup-Migration) stehen, nicht nur lazy: das User-Modell
            # selektiert diese Spalten bei JEDEM Query (inkl. Login) -> auf bestehenden
            # DBs ohne die Spalten crasht sonst der Login (OperationalError).
            ('reset_token_hash', 'TEXT'),
            ('reset_token_expires_at', 'TEXT'),
            ('totp_recovery_codes', 'TEXT'),
            # AUTH-04 (2026-07-22): Token-Revocation-Timestamp fuer /auth/logout.
            ('token_revoked_before', 'TEXT'),
            # AUTH-06 (2026-07-22): letzter akzeptierter TOTP-Zeitschritt (Anti-Replay).
            ('totp_last_counter', 'TEXT'),
            # SEC-TOTP-REPLAY-WINDOW (2026-09-15): sha256 des zuletzt akzeptierten
            # TOTP-Codes -- totp_last_counter allein liess einen woertlichen
            # Code-Replay durch, sobald die Uhr ins naechste (per +/-1-Drift-
            # Toleranz weiterhin gueltige) Zeitfenster weiterrueckte.
            ('totp_last_code_hash', 'TEXT'),
            # REVIEW-CALENDAR-001 (2026-09-24): siehe models/users.py.
            ('calendar_feed_token_hash', 'TEXT'),
            ('calendar_feed_token_created_at', 'TEXT'),
        ],
        'tenants': [
            ('encrypted_dek', 'TEXT'),
            ('dek_version', 'INTEGER'),
            ('dek_rotated_at', 'TEXT'),
            # AF-5: Generation der Master-KEK (siehe models/tenant.py).
            ('kek_version', 'INTEGER', 1),
            # 2026-07-27 (Retrozessions-Feature): Firmenweite Vorbelegung,
            # siehe models/tenant.py.
            ('default_retrocession_reimbursement', 'INTEGER', 0),
            # 2026-08-01 (Onboarding): Land der lizenznehmenden Firma, siehe
            # models/tenant.py. NULL = "CH" (kein DB-Default fuer TEXT-Spalten).
            ('home_jurisdiction', 'TEXT'),
            # 2026-08-02 (HUD-Polish): firmenweiter Default fuer die UI-
            # "Maske" (Wealthmanagement/Consulting), siehe models/tenant.py.
            # NULL = "wealthmanagement".
            ('default_presentation_mode', 'TEXT'),
            # 2026-08-09 (FINIG-Gate): siehe models/tenant.py +
            # services/tenant_licensing.py. Default 1 = Bestandsmandanten
            # bleiben funktionsfaehig; neue Tenants starten via
            # schemas/tenants.py::TenantCreate explizit mit False.
            ('discretionary_management_licensed', 'INTEGER', 1),
        ],
        # CERT-HANDOFF-EXECUTION-001 (2026-10-25): siehe models/portfolio_handoff.py
        # und Alembic c7e4a19b3d52. Nullable, kein Backfill.
        'portfolio_handoffs': [
            ('snapshot_sha256', 'TEXT'),
            ('business_key_hash', 'TEXT'),
            ('execution_evidence_kind', 'TEXT'),
            ('execution_external_reference', 'TEXT'),
            ('execution_confirmed_on', 'TEXT'),
            # HANDOFF-NEW-PRODUCT-001 (Alembic d2f8b6a1c4e9).
            ('holdings_basis', 'TEXT'),
        ],
        # ELIG-GOVERNANCE-001 (2026-10-22): siehe models/product_eligibility.py.
        'product_eligibility_rules': [
            ('approval_mode', 'TEXT'),
        ],
        # 2026-07-27 (Retrozessions-Feature): siehe models/review.py.
        'conflict_of_interest_disclosures': [
            ('reimbursed_to_client', 'INTEGER', 0),
            ('waiver_document_id', 'TEXT'),
            # N-861-1: optionale Produktbindung, siehe models/review.py.
            ('product_id', 'TEXT'),
        ],
        # 2026-06-18 (#84): Miete-Teuerungsindexierung pro Immobilien-Position.
        # NOT NULL DEFAULT 0 -> Bestandszeilen werden auf 0 gesetzt (Response-Schema
        # erwartet int, nicht NULL).
        'wealth_positions': [
            ('property_rental_inflation_linked', 'INTEGER', 0),
            # PG-002 (2026-10-24): direkte Mandantenbindung, aus clients.tenant_id
            # abgeleitet (services/wealth_tenant_boundary.py backfillt + Trigger).
            ('tenant_id', 'TEXT'),
            # VORSORGE-PROJECTION-001 (2026-10-18): siehe models/wealth.py.
            # Alle NULL = Defaults je Anlageform (unveraendert erfassbar).
            ('pension_vehicle', 'TEXT'),
            ('pension_interest_rate_bps', 'INTEGER'),
            ('pension_maturity_value_rappen', 'INTEGER'),
            ('pension_maturity_date', 'TEXT'),
            ('pension_lumpsum_tax_rappen', 'INTEGER'),
            ('pension_lumpsum_tax_bps', 'INTEGER'),
        ],
        # A2-Smoke-Test-Fund (2026-07-22): 'target_allocations' hatte einen
        # DOPPELTEN Dict-Key in diesem Literal (hier + weiter unten). In Python
        # gewinnt der ZWEITE — der erste Block war dadurch tote Migration:
        # preferences_json, input_snapshot_hash, die advisory/total/reserve-
        # Rappen-Spalten, alle optimization_*-Legacy-Felder, stress_evaluations_
        # json und optimizer_reasoning_json wurden NIE auf einer per Raw-SQL-
        # Bootstrap (ares_schema.sql) frisch angelegten DB migriert
        # -> jede fabrikneue Installation crashte mit 'no such column:
        # target_allocations.preferences_json' auf /target-allocation/current/
        # payload + /recommendations/current/payload — der Blocker fuer den
        # allerersten echten Mandanten. Beide Bloecke hier zu EINEM gemergt;
        # ensure_column() ist idempotent (PRAGMA-Check), das Zusammenfuehren
        # ist ohne Risiko fuer DBs, die einzelne Spalten schon haben.
        'target_allocations': [
            ('capital_market_assumptions_id', 'TEXT'),
            # C8 audit anchors fuer Reproduzierbarkeit / Drift-Erkennung
            ('preferences_json', 'TEXT'),
            ('input_snapshot_hash', 'TEXT'),
            ('advisory_wealth_at_generation_rappen', 'INTEGER'),
            ('total_wealth_at_generation_rappen', 'INTEGER'),
            ('reserve_needed_at_generation_rappen', 'INTEGER'),
            ('external_reserve_at_generation_rappen', 'INTEGER'),
            # RESERVE-LEDGER-SNAPSHOT-001
            ('reserve_funding_ledger_json', 'TEXT'),
            ('reserve_funding_ledger_hash', 'TEXT'),
            # Optimizer-Audit-Anchor (Spec 2026-05-05). NULL fuer pre-Optimizer-
            # Allocations - bedeutet "via House-Matrix-Default berechnet".
            ('optimization_method', 'TEXT'),
            ('optimization_objective_value_milli', 'INTEGER'),
            ('optimization_iterations', 'INTEGER'),
            ('optimization_seed', 'INTEGER'),
            ('optimization_status', 'TEXT'),
            ('risky_fraction_bps_at_generation', 'INTEGER'),
            ('risk_budget_bps_at_generation', 'INTEGER'),
            ('limiting_factor', 'TEXT'),
            ('goal_achievability_json', 'TEXT'),
            ('sub_allocations_json', 'TEXT'),
            ('effective_constraints_json', 'TEXT'),
            ('allocation_context_hash', 'TEXT'),
            ('context_artifacts_required', 'INTEGER', 0),
            # Phase 6: persistierte Stress-Auswertungen (Phase 5.2) als JSON-String.
            # NULL bei house_matrix-Modus oder Pre-Optimizer-Allocations.
            ('stress_evaluations_json', 'TEXT'),
            # Phase 6.2: persistierter Solver-Reasoning-Trace (list[str] JSON).
            # Damit /current/payload das identische Reasoning liefert wie /generate.
            ('optimizer_reasoning_json', 'TEXT'),
            # V3 Sprint 2.1 (2026-05-09 / Plan §4.1): Verknuepfung zur eigenen
            # optimizer_runs-Zeile (nur im zweiten, vormals lebenden Block).
            ('optimization_run_id', 'TEXT'),
            # Stochastic Goal Engine Stage 5: persistierter Shadow-Vergleich
            # fuer Admin-/Compliance-Auswertung.
            ('shadow_optimization_json', 'TEXT'),
            # AR-2 (2026-07-19): MC-Risiko-KPIs (bps) fuer FIDLEG-Report.
            ('mc_exp_vol_bps', 'INTEGER'),
            ('mc_exp_return_bps', 'INTEGER'),
            ('mc_max_drawdown_bps', 'INTEGER'),
            ('mc_var_95_bps', 'INTEGER'),
            # SIM-HORIZON-CONFIRM-001 (2026-10-17): Berater-Bestaetigung eines
            # vor SIM-HORIZON-ALWAYS-EXPLICIT-001 gespeicherten Horizonts. Seit
            # SIM-HORIZON-FROM-RISK-PROFILE-001 ungenutzt; Spalten bleiben.
            ('sim_horizon_confirmed_at', 'TEXT'),
            ('sim_horizon_confirmed_by', 'TEXT'),
            # PENSION-TRANSFER-LEDGER-001 (2026-10-21): PensionTransferLedgerSnapshotV1.
            ('pension_transfer_ledger_snapshot_json', 'TEXT'),
            # OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001 (2026-10-24): Goal-
            # Driver-Snapshot, siehe models/allocation.py::TargetAllocation.
            ('goal_driver_evidence_json', 'TEXT'),
            # GOAL-CALENDAR-HORIZON-PARITY-001 / ADR-1b (2026-10-25):
            # gebundener Bewertungsstichtag des Laufs.
            ('valuation_date', 'TEXT'),
        ],
        'recommendation_positions': [
            ('reference_price_rappen', 'INTEGER'),
            ('reference_price_date', 'TEXT'),
            ('reference_price_source', 'TEXT'),
            ('reference_lookup_mode', 'TEXT'),
            ('reference_price_fetched_at', 'TEXT'),
            # Sprint U-P20 (2026-05-24): Echte IST-Holdings des Kunden.
            # NULL = noch nicht gepflegt (Empfehlung erstellt, Kunde hat
            # noch nichts gekauft). depot_check.py liest das Feld für den
            # IST/SOLL-Drift im Country/Sector/Currency-Vergleich.
            # HOTFIX U-P20.1 (2026-05-25): Migration war im Sprint U-P20
            # vergessen — Live-DBs hatten die Column nicht und der
            # /advisory-report-Endpoint warf 500. Mit Eintrag hier wird
            # die Column beim naechsten Backend-Start idempotent ergaenzt.
            ('current_amount_rappen', 'INTEGER'),
        ],
        'clients': [
            ('investment_horizon_start', 'TEXT'),
            ('investment_horizon_end', 'TEXT'),
            # Sprint T1 (2026-06-08): tenant_id fuer 3-Tier-Architektur.
            # Bootstrap-SQL hat das Feld noch nicht — Migration ergaenzt
            # die Column idempotent auf Live-DBs, sonst koennen Tier-2-
            # Endpoints den tenant-Scope nicht setzen.
            ('tenant_id', 'TEXT'),
            # DSG Art. 32 (2026-08-15): siehe models/clients.py.
            ('erased_at', 'TEXT'),
            ('erasure_reason', 'TEXT'),
        ],
        # DUAL-STACK-01-Nachtrag (2026-10-07): siehe models/clients.py
        # ClientOptHistory -- Flag-Uebergaenge fuer is_professional_opt_out/
        # is_qualified_investor in derselben History-Zeile wie die
        # Klassifikationsaenderung. NULL = Flag bei dieser Transition
        # unveraendert.
        'client_opt_history': [
            ('from_professional_opt_out', 'INTEGER'),
            ('to_professional_opt_out', 'INTEGER'),
            ('from_qualified_investor', 'INTEGER'),
            ('to_qualified_investor', 'INTEGER'),
        ],
        # Sprint U-37 (2026-06-03): Notes-Versionierungs-Log.
        # Append-only JSON-Array von Edit-Snapshots fuer FINMA-Audit
        # (was-stand-zu-welchem-Zeitpunkt-im-Bericht).
        'mandate_report_notes': [
            ('previous_versions_json', 'TEXT'),
        ],
        # Sprint U-P19b (2026-05-23): native Notierungswährung der Proxy-Bar
        # fuer waehrungskorrekten Daily-Backtest (NULL = wie CHF behandelt).
        # Sprint 2026-06-09 (Phase 1 Sub-Asset): sub_asset_class fuer
        # Sub-Anlageklassen-Backfill (NULL = Top-Level-Aggregat wie bisher,
        # NOT NULL = z.B. "Aktien_CH_Large" gemaess symbol_catalog.py).
        'asset_class_price_history': [
            ('currency', 'TEXT'),
            ('sub_asset_class', 'TEXT'),
        ],
        # Sprint 2026-06-09 (Phase 1 Sub-Asset): Annual-Returns auch fuer
        # Sub-Anlageklassen. NULL = Top-Level-Aggregat (Bisheriges Verhalten).
        'asset_class_annual_returns': [
            ('sub_asset_class', 'TEXT'),
        ],
        'mandates': [
            # Sprint T1 (2026-06-08): tenant_id fuer 3-Tier-Architektur.
            # Bootstrap-SQL hat das Feld noch nicht — Migration ergaenzt
            # die Column idempotent auf Live-DBs.
            ('tenant_id', 'TEXT'),
            # Sprint A3 (2026-05-06): Rentenalter + Lebenserwartung pro Mandat.
            ('retirement_year', 'INTEGER'),
            ('life_expectancy_year', 'INTEGER'),
            # Sprint B4 (2026-05-07): Anlageuniversum (Advisory-Methodik-Pattern).
            # Standard | Alternativ; Filter fuer Produkt-Auswahl.
            ('investment_universe', 'TEXT'),
            # Sprint B1 (2026-05-07): Building-Block-Wahl pro Mandat (JSON).
            ('default_building_blocks_json', 'TEXT'),
            # Sprint 4 Phase 3 (2026-05-17): BFS-Mortalitaets-Sampling
            # Wenn use_mortality_simulation=1 und client_birth_year + client_sex
            # gesetzt, sampled portfolio_engine das Sterbe-Alter aus der BFS-Tafel.
            ('client_birth_year', 'INTEGER'),
            ('client_sex', 'TEXT'),
            ('use_mortality_simulation', 'INTEGER'),
            # Sprint U-P3 (2026-05-19): Steuersitz fuer tax-aware Allocations-MC.
            # NULL = tax-naiv (Backwards-Compat). Pattern matched gegen Tax-Registry
            # ('CH', 'DE', 'CH-ZH', 'DE-BY', '*' = Generic).
            ('tax_jurisdiction', 'TEXT'),
            ('tax_overrides_json', 'TEXT'),
            # 2026-07-27 (HUD-Konfiguration): siehe models/mandates.py.
            ('hidden_report_sections', 'TEXT'),
            # 2026-07-27 (Laender-Skalierung): siehe models/mandates.py. NULL
            # (kein DB-Default möglich fuer TEXT-Spalten in dieser Migration-
            # Helper-Funktion) -- Code interpretiert NULL als "CH".
            ('jurisdiction', 'TEXT'),
            # Roadmap #39 (Standpunkt 2026-08-07): siehe models/mandates.py.
            ('tax_estimate_in_cashflow_enabled', 'INTEGER', 0),
        ],
        'cashflows': [
            ('gross_amount_rappen', 'INTEGER'),
            ('tax_amount_rappen', 'INTEGER'),
            ('timing_precision', 'TEXT'),
            # CASHFLOW-GOAL-INCLUDE-TOGGLE-001 (Audit-Feedback, 2026-10-08):
            # siehe models/wealth.py::Cashflow.is_included fuer die Semantik.
            # int_default=1 -> Bestandszeilen bleiben "eingeschlossen"
            # (unveraendertes Verhalten), rueckwaertskompatibel.
            ('is_included', 'INTEGER', 1),
        ],
        'goals': [
            # Sprint B6 (2026-05-08): bedingte Goals — Eintrittswahrscheinlichkeit (0-100).
            # NULL bei pre-B6-Goals -> Engine interpretiert als 100 (sicher).
            ('probability_pct', 'INTEGER'),
            # Sprint B3 (2026-05-08): Vorsorge-Saeule fuer Pensionsausgabe-Goals.
            # AHV / BVG / 3a / 1e / FZG. NULL bei nicht-Pensionsausgabe oder unspezifiziert.
            ('pension_pillar', 'TEXT'),
            # Stochastic Goal Engine Stage 1 (2026-05-23): Renditeziel + Zielwahrscheinlichkeit.
            ('target_return_bps', 'INTEGER'),
            ('success_probability_min_x100', 'INTEGER'),
            # CASHFLOW-GOAL-INCLUDE-TOGGLE-001: siehe models/wealth.py::Goal.is_included.
            ('is_included', 'INTEGER', 1),
            # GOAL-PAST-DATE-LIFECYCLE-001 / ADR-3 (2026-10-12): persistierter
            # Lifecycle-Entscheid. NULL = nicht entschieden -> der Zeit-Zustand
            # wird abgeleitet (services/goal_lifecycle.py). Alt-DBs bekommen die
            # Spalte hier, frische Installationen aus dem Bootstrap-DDL.
            ('lifecycle_decision', 'TEXT'),
        ],
        # VORSORGE-TRANSFER-001 (2026-10-18): siehe models/wealth.py::
        # WealthInflow.linked_position_id. NULL = Zufluss ist neues Vermoegen
        # (unveraendertes Verhalten fuer Bestandszeilen).
        'wealth_inflows': [
            ('linked_position_id', 'TEXT'),
            # PG-002: siehe wealth_positions.tenant_id.
            ('tenant_id', 'TEXT'),
            # INFLOW-CERTAINTY-001: NULL = 'sicher' (services/wealth_inflow_certainty.py).
            ('certainty', 'TEXT'),
        ],
        'capital_market_assumptions': [
            ('correlation_matrix_json', 'TEXT'),
            ('sub_asset_class_assumptions_json', 'TEXT'),
            # WP1 (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
            # siehe models/allocation.py::CapitalMarketAssumption. jurisdiction
            # NULL = "CH" (gleiches Nullable-Pattern wie mandates.jurisdiction).
            # status hat KEINEN DB-Default (bleibt NULL fuer neue Inserts von
            # aussen) -- Bestandszeilen werden weiter unten (WP1-Status-Backfill)
            # EINMALIG beim erstmaligen Anlegen dieser Spalte auf
            # 'committee_approved' zurueckgeschrieben, weil Bestandszeilen
            # bereits IC-freigegebene CH-Zahlen sind. Erlaubte Werte fuer
            # status (Validierung folgt in einem spaeteren Schema/Router-Paket):
            # "provisional" | "data_derived" | "committee_approved".
            ('jurisdiction', 'TEXT'),
            ('status', 'TEXT'),
            ('source_detail', 'TEXT'),
            ('computed_at', 'TEXT'),
            ('computed_by', 'TEXT'),
            # Generische Home-Bias-Gegenstuecke zu equity_ch_*/bonds_chf_ig_*/
            # real_estate_ch_* -- die CH-Spalten bleiben unveraendert und werden
            # weiterhin ausschliesslich vom CH-Pfad gelesen.
            ('equity_home_return_bps', 'INTEGER'),
            ('equity_home_vol_bps', 'INTEGER'),
            ('bonds_home_ig_return_bps', 'INTEGER'),
            ('bonds_home_ig_vol_bps', 'INTEGER'),
            ('real_estate_home_return_bps', 'INTEGER'),
            ('real_estate_home_vol_bps', 'INTEGER'),
            # 2026-07-31 (Tenant-Override): NULL = firmenweite CMA-Zeile
            # (Default). Gesetzt = Tenant-spezifischer Override, hat Vorrang
            # vor der firmenweiten Zeile derselben Jurisdiktion. CH-Pfad
            # ignoriert diese Spalte weiterhin komplett.
            ('tenant_id', 'TEXT'),
            # Optimizer-Phase 1: Skewness + Excess-Kurtosis pro Bucket fuer
            # Cornish-Fisher fat-tail Sampling. NULL/0 -> Normal-Verteilung
            # (backwards-compat). Werte in bps (z.B. -5000 = -0.5 skew).
            ('equities_skewness_bps', 'INTEGER'),
            ('equities_excess_kurt_bps', 'INTEGER'),
            ('bonds_skewness_bps', 'INTEGER'),
            ('bonds_excess_kurt_bps', 'INTEGER'),
            ('real_estate_skewness_bps', 'INTEGER'),
            ('real_estate_excess_kurt_bps', 'INTEGER'),
            ('alternatives_skewness_bps', 'INTEGER'),
            ('alternatives_excess_kurt_bps', 'INTEGER'),
            ('liquidity_skewness_bps', 'INTEGER'),
            ('liquidity_excess_kurt_bps', 'INTEGER'),
            # Sprint 6 Phase 2 (2026-05-17): Nelson-Siegel Yield-Curve fuer Bonds.
            ('bonds_ns_beta0_bps', 'INTEGER'),
            ('bonds_ns_beta1_bps', 'INTEGER'),
            ('bonds_ns_beta2_bps', 'INTEGER'),
            ('bonds_ns_lambda_x100', 'INTEGER'),
            # Sprint 7 (2026-05-17): KGV-Mean-Reversion fuer Equity-Returns.
            ('equity_kgv_current_x10', 'INTEGER'),
            ('equity_kgv_fair_x10', 'INTEGER'),
            ('equity_kgv_alpha_x100', 'INTEGER'),
            # Sprint 8 (2026-05-17): Risikopraemien-Modell fuer RE + Alternatives.
            ('real_estate_risk_premium_bps', 'INTEGER'),
            ('alternatives_risk_premium_bps', 'INTEGER'),
            # Roadmap #51 (2026-07-23): CMA-Werte-Pflegeprozess -- Quelle/Datum
            # dokumentieren. source (Herkunft) existierte bereits im Bootstrap-
            # SQL; source_date (ISO-Datum der Quellpublikation, kann von
            # valid_from abweichen) fehlte -- additive Migration fuer Alt-DBs.
            ('source_date', 'TEXT'),
        ],
        # WP1 (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
        # siehe models/allocation.py::BuildingBlock. jurisdiction NULL = "CH"
        # (gleiches Nullable-Pattern wie mandates.jurisdiction). is_provisional
        # ist ein reiner int-Default (0 = kein IC-Vorbehalt) -- zulaessig, weil
        # INTEGER (siehe ensure_runtime_columns()-Docstring zu int_default).
        'building_blocks': [
            ('jurisdiction', 'TEXT'),
            ('is_provisional', 'INTEGER', 0),
            ('role', 'TEXT'),
        ],
        # WP1 (2026-07-30): siehe models/review.py::RecommendationRun. JSON-
        # Warnhinweis, wenn der Lauf provisorische (noch nicht IC-geprueft)
        # CMA-/Home-Bias-Daten verwendet hat -- Vorbild fee_assumptions_json
        # (gleicher Spaltentyp/-Stil, gleiche Klasse).
        'recommendation_runs': [
            ('provisional_data_warning', 'TEXT'),
            # COST-CONTEXT-001b / COST-EVIDENCE-001 (2026-10-13): der bei der
            # Finalisierung eingefrorene Kostenausweis, siehe
            # models/review.py::RecommendationRun.
            ('cost_disclosure_snapshot_json', 'TEXT'),
            # CMA-001: CMA_POLICY, an die eine Finalisierung gebunden wurde
            # (models/cma_policy.py; NULL solange das Modell nicht aktiv ist).
            ('cma_policy_row_id', 'TEXT'),
        ],
        'optimizer_runs': [
            # U-9 Stage-9 Telemetry: pro Solver-Start n_paths/n_starts/Seed/
            # Status/elapsed_ms/reason auditierbar persistieren.
            ('restart_results_json', 'TEXT'),
            ('robustification_json', 'TEXT'),
            # OPTIMIZER-POST-SELECTION-CERTIFICATION-001 (2026-10-10): Anker
            # der unabhaengigen Validierungsstichprobe, siehe
            # models/allocation.py::OptimizerRun. NULL = nie validiert.
            ('validation_seed', 'INTEGER'),
            ('validation_cube_hash', 'TEXT'),
            ('validation_n_paths', 'INTEGER'),
            # OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001 (2026-10-24): Objective-
            # Vertrag des Laufs, siehe models/allocation.py::OptimizerRun.
            ('objective_contract_version', 'TEXT'),
            ('objective_contract_hash', 'TEXT'),
            ('objective_contract_json', 'TEXT'),
        ],
        'products': [
            ('lookup_mode_override', 'TEXT'),
            ('lookup_symbol_override', 'TEXT'),
            ('figi', 'TEXT'),
            ('composite_figi', 'TEXT'),
            ('share_class_figi', 'TEXT'),
            ('exchange_code', 'TEXT'),
            ('market_sector', 'TEXT'),
            ('security_type', 'TEXT'),
            ('security_type2', 'TEXT'),
            ('mapping_provider', 'TEXT'),
            ('mapping_resolved_at', 'TEXT'),
            ('reference_data_provider', 'TEXT'),
            ('reference_data_refreshed_at', 'TEXT'),
            # Sprint U-P10 (2026-05-20): Depot-Check Diversifikations-Tiefe
            ('country_exposure_json', 'TEXT'),
            ('sector_exposure_json', 'TEXT'),
            ('currency_exposure_json', 'TEXT'),
            ('duration_years_x10', 'INTEGER'),
            ('credit_rating', 'TEXT'),
            ('esg_score_x10', 'INTEGER'),
            ('liquidity_tier', 'TEXT'),
            # ESG-PREMIUM-CRITERIA-001 (2026-10-14): siehe models/review.py
            # Product.climate_benchmark / Product.theme_tags. Backfill der
            # theme_tags fuer "Thema X"-Produkte weiter unten.
            ('climate_benchmark', 'TEXT'),
            ('theme_tags', 'TEXT'),
            # AUDIT-2026-11 P1 (PO-6, L1): Produkt-Stammdaten, siehe
            # models/review.py::Product und Alembic a8d3c5e7f9b1. Ohne
            # Default/Backfill: NULL = nicht erfasst (nichts erfinden).
            ('domicile', 'TEXT'),
            ('is_hedged', 'INTEGER'),
            ('hedge_currency', 'TEXT'),
            ('ter_source', 'TEXT'),
            ('ter_as_of', 'TEXT'),
            ('retrocession_bps', 'INTEGER'),
            ('retrocession_source', 'TEXT'),
            ('is_house_product', 'INTEGER'),
            ('distribution_policy', 'TEXT'),
            ('valor', 'TEXT'),
            ('minimum_investment_minor_units', 'INTEGER'),
            # Owner-Anforderung P1 (eigene Fonds), Alembic c2e6f8a1b3d5.
            ('listing_status', 'TEXT'),
            ('internal_product_id', 'TEXT'),
            ('price_source', 'TEXT'),
            ('nav_frequency', 'TEXT'),
            ('nav_as_of', 'TEXT'),
            ('redemption_period_days', 'INTEGER'),
            ('notice_period_days', 'INTEGER'),
            ('has_gating', 'INTEGER'),
            ('gating_terms', 'TEXT'),
            # 2026-08-01 (Laender-Skalierung, Cross-Jurisdiktions-Leck-Fix):
            # siehe models/review.py::Product.jurisdiction. NULL = "CH".
            ('jurisdiction', 'TEXT'),
        ],
        # Roadmap #21 (2026-08-08): tenant_id direkt am Eintrag gespeichert
        # (statt nur ueber client_id/mandate_id/user_id transitiv abgeleitet)
        # -- siehe services/audit.py::log() + routers/system.py::get_audit_log.
        # Schliesst die Luecke, dass ein Firmen-Admin bisher NUR eigene
        # Aktionen ODER Aktionen mit eigenem Client-/Mandats-Bezug sah, aber
        # NICHT die Aktionen ANDERER Admins der eigenen Firma auf tenant-
        # weiten (nicht client-/mandats-gebundenen) Tabellen (z.B. house_matrix,
        # optimizer_policies, tax_parameter_sets).
        'audit_log': [
            ('tenant_id', 'TEXT'),
            # SEC-003 (Codex-Audit 2026-08-26): atomar vergebene Sequenz +
            # persistierter Vorgaenger-Hash -- schliesst die Race-Luecke der
            # bisherigen ORDER-BY-created_at-Ermittlung. NULL bei Altdaten,
            # siehe Kommentar an models.review.AuditLog.sequence.
            ('sequence', 'INTEGER'),
            ('previous_hash', 'TEXT'),
        ],
        # REVIEW-STATE-003 (Codex-Audit 2026-08-27): resolve_trigger() verwarf
        # bisher das Pflichtfeld `decision` komplett und besass keine
        # Evidence-Spalten -- ein Resolve war beliebig oft wiederholbar und
        # verschob die Faellligkeit stillschweigend, ohne dass je
        # nachvollziehbar war, WER WANN WELCHEN Entscheid getroffen hat oder
        # welcher Faelligkeitsanker davor galt. Siehe models/review.py::
        # ReviewTrigger + routers/review.py::resolve_trigger().
        'review_triggers': [
            ('resolution_decision', 'TEXT'),
            ('resolved_by', 'TEXT'),
            ('resolved_at', 'TEXT'),
            ('previous_next_due_at', 'TEXT'),
        ],
    }
    inspector = inspect(target_engine)
    # WP1 (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
    # gesetzt, wenn 'status' auf capital_market_assumptions in DIESEM Lauf
    # neu per ALTER TABLE angelegt wurde (siehe Backfill weiter unten).
    cma_status_newly_added = False
    with target_engine.begin() as conn:
        for table_name, columns in additive_columns.items():
            # Defensive (2026-06-08): wenn eine Tabelle (noch) nicht
            # existiert, Migration ueberspringen statt zu crashen. create_all
            # legt die fehlenden Tabellen erst nach unserem Aufruf an
            # (Bootstrap-SQL deckt nicht alle ORM-Tabellen ab).
            if not inspector.has_table(table_name):
                continue
            existing = {column['name'] for column in inspector.get_columns(table_name)}
            for spec in columns:
                # spec = (column_name, sql_type) ODER (column_name, sql_type, int_default).
                # int_default -> Spalte als NOT NULL DEFAULT <int> (Bestandszeilen erhalten
                # den Default; rohe SQL-Inserts ohne die Spalte brechen nicht).
                column_name, sql_type = spec[0], spec[1]
                default = spec[2] if len(spec) > 2 else None
                if not re.match(r'^[a-z][a-z0-9_]*$', table_name):
                    raise ValueError(f"Ungültiger Tabellenname: {table_name!r}")
                if not re.match(r'^[a-z][a-z0-9_]*$', column_name):
                    raise ValueError(f"Ungültiger Spaltenname: {column_name!r}")
                if not re.match(r'^[A-Z]+$', sql_type):
                    raise ValueError(f"Ungültiger SQL-Typ: {sql_type!r}")
                if default is not None and (not isinstance(default, int) or isinstance(default, bool)):
                    raise ValueError(f"Ungültiger Default (nur int): {default!r}")
                column_is_new = column_name not in existing
                if column_is_new:
                    ddl = f'ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}'
                    if default is not None:
                        ddl += f' NOT NULL DEFAULT {int(default)}'
                    conn.execute(text(ddl))
                    if table_name == 'capital_market_assumptions' and column_name == 'status':
                        cma_status_newly_added = True
                # WP-500-Fix (2026-07-01): idempotenter Backfill. Wenn die Column in
                # einer FRÜHEREN Migration OHNE Default zugefügt wurde, sind Bestands-
                # zeilen NULL geblieben — der `NOT NULL DEFAULT` oben greift nur beim
                # erstmaligen Anlegen, und ein bereits vorhandener Column-Name führte
                # bisher zu `continue` (kein Backfill). Response-Schemas erwarten aber
                # int (nicht NULL) -> ein einziges NULL liess `/wealth-positions` u.ä.
                # mit 500 (ResponseValidationError) fehlschlagen. NULL->default auf
                # jedem Start reparieren (idempotent, betrifft nur Alt-NULLs).
                if default is not None:
                    conn.execute(
                        text(f'UPDATE {table_name} SET {column_name} = :d WHERE {column_name} IS NULL'),
                        {'d': int(default)},
                    )
                existing.add(column_name)

        # WP1-Status-Backfill (2026-07-30): 'status' auf capital_market_assumptions
        # ist eine TEXT-Spalte -> kein int_default moeglich (siehe Validierung
        # oben). Bestandszeilen (heutige CH-Zeilen) sind aber bereits vom
        # Investment Committee freigegebene Zahlen -- deshalb EINMALIG beim
        # erstmaligen Anlegen dieser Spalte per Backfill auf
        # 'committee_approved' setzen (Muster wie WP-500-Fix: UPDATE ... WHERE
        # status IS NULL). BEWUSST NUR innerhalb des column_is_new-Zweigs
        # (nicht auf jedem Boot-Lauf, anders als WP-500-Fix): Constraint aus der
        # Spezifikation ist, dass status fuer NEUE Inserts von aussen (z.B.
        # provisorische Nicht-CH-CMA-Zeilen aus einem spaeteren Arbeitspaket)
        # NICHT automatisch beim naechsten Backend-Start auf
        # 'committee_approved' hochgestuft werden darf -- die Spalte bleibt
        # NULL/leer, bis ein Mensch/Prozess sie explizit setzt.
        if cma_status_newly_added:
            conn.execute(
                text(
                    "UPDATE capital_market_assumptions SET status = 'committee_approved' "
                    "WHERE status IS NULL"
                )
            )

        # Owner-Anforderung P1 (eigene Fonds): interne Produkt-ID eindeutig je
        # Tenant (aktive Zeilen). Identisch zu Alembic c2e6f8a1b3d5.
        # products.tenant_id kommt sonst erst spaeter (ensure_column im
        # Fondsuniversum-Patch) -- hier idempotent vorziehen, damit der Index
        # auf jeder Bootstrap-Reihenfolge angelegt werden kann.
        if inspector.has_table('products'):
            product_columns = {
                row[1] for row in conn.execute(text("PRAGMA table_info(products)"))
            } if target_engine.dialect.name == 'sqlite' else {
                column['name'] for column in inspect(conn).get_columns('products')
            }
            if 'tenant_id' not in product_columns:
                conn.execute(text('ALTER TABLE products ADD COLUMN tenant_id TEXT'))
            conn.execute(text(PRODUCT_INTERNAL_ID_INDEX_DDL))

        # ESG-PREMIUM-CRITERIA-001 (2026-10-14): idempotenter Backfill --
        # Produkte mit Sub-Anlageklasse "Thema X" erhalten den Tag X, sofern
        # noch KEINE Tags gepflegt sind (gepflegte Tags nie ueberschreiben).
        # Identisch zur Alembic-Revision d7c3e9a2f5b1 (Postgres-Pfad).
        if inspector.has_table('products'):
            for sub_asset_class, theme_tags in THEME_TAG_BACKFILL:
                conn.execute(
                    text(
                        "UPDATE products SET theme_tags = :tags "
                        "WHERE sub_asset_class = :sub AND theme_tags IS NULL"
                    ),
                    {'tags': theme_tags, 'sub': sub_asset_class},
                )

        # SEC-003 (Codex-Audit 2026-08-26): audit_log_sequence_counter ist eine
        # neue ORM-only-Tabelle (models.review.AuditLogSequenceCounter). In der
        # realen Boot-Sequenz legt Base.metadata.create_all() sie an -- hier
        # zusaetzlich idempotent per Raw-SQL, damit JEDER Aufrufer von
        # ensure_runtime_columns() (u.a. mehrere bestehende Test-Fixtures, die
        # die Rohschema-Datei direkt bootstrappen und create_all() nicht
        # aufrufen) sich auf die Existenz verlassen kann, bevor
        # services.audit.py::log() das erste Mal laeuft. CREATE TABLE IF NOT
        # EXISTS + INSERT OR IGNORE sind beide von Natur aus idempotent.
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS audit_log_sequence_counter ("
                "id TEXT PRIMARY KEY, value INTEGER NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT OR IGNORE INTO audit_log_sequence_counter (id, value) "
                "VALUES ('singleton', 0)"
            )
        )
        # N-869-4 (Pruefrunde #869): Hash des letzten Eintrags auf der
        # Zaehlerzeile, damit log() den Vorgaenger nie aus audit_log lesen
        # muss (unter PostgreSQL-RLS ist der Vorgaenger eines anderen Tenants
        # unsichtbar). Einmaliger Nachtrag aus der Zeile mit sequence = value
        # (identisch zur Alembic-Revision c8a2f4e6b0d9).
        ensure_column(conn, "audit_log_sequence_counter", "last_hash", "TEXT")
        if inspector.has_table('audit_log'):
            audit_columns = {
                row[1] for row in conn.execute(text("PRAGMA table_info(audit_log)")).fetchall()
            }
            if {"sequence", "integrity_hash"} <= audit_columns:
                conn.execute(text(_COUNTER_LAST_HASH_BACKFILL_SQL))

        # RiskAssessment - Kenntnisse & Erfahrungen (Referenzmodell Eignungspruefung, 2026-04-16)
        ensure_column(conn, "risk_assessments", "knowledge_services_json", "TEXT")
        ensure_column(conn, "risk_assessments", "knowledge_instruments_json", "TEXT")
        ensure_column(conn, "risk_assessments", "income_sources_json", "TEXT")
        # FIDLEG-Signatur (2026-07-19): Kunden-Signatur des Risikoprofils. Reine
        # Dokumentation (aendert die Eignungs-Konformitaet NICHT). ensure_column ist
        # idempotent -> ergaenzt die Spalten auf bestehenden SQLite-DBs beim Start.
        ensure_column(conn, "risk_assessments", "client_signed_at", "TEXT")
        ensure_column(conn, "risk_assessments", "client_signed_method", "TEXT")
        ensure_column(conn, "risk_assessments", "client_signed_ref", "TEXT")
        # RISK-OVERRIDE-WRITE-BOUNDARY-001 Restbefund B (2026-10-19): Pointer
        # auf die aktuell wirksame RiskOverrideDecisionV1 + die append-only
        # Decision-Tabelle selbst (idempotent; siehe Konstanten oben).
        ensure_column(conn, "risk_assessments", "override_decision_id", "TEXT")
        ensure_column(conn, "risk_assessments", "override_decision_hash", "TEXT")
        for ddl in RISK_OVERRIDE_DECISION_SQLITE_TABLE_DDL + RISK_OVERRIDE_DECISION_SQLITE_TRIGGERS:
            conn.execute(text(ddl))
        # PG-002 (Codex-Closure-Review PR #662): direkte Mandantenbindung der
        # Evidence (ADD COLUMN feuert den UPDATE-Trigger nicht); Backfill +
        # Guard: services/risk_evidence_tenant_boundary.py.
        ensure_column(conn, "risk_override_decisions", "tenant_id", "TEXT")
        conn.execute(text(RISK_OVERRIDE_DECISION_SQLITE_TENANT_INDEX))
        # HANDOFF-IDEMPOTENCY-001: partieller Unique-Index auf Bestands-DBs
        # (erst nach dem ADD COLUMN oben ausfuehrbar; frische DBs: create_all).
        if inspector.has_table("portfolio_handoffs"):
            from models.portfolio_handoff import (
                HANDOFF_OPEN_BUSINESS_KEY_INDEX,
                HANDOFF_OPEN_BUSINESS_KEY_PREDICATE,
            )

            conn.execute(text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {HANDOFF_OPEN_BUSINESS_KEY_INDEX} "
                f"ON portfolio_handoffs(business_key_hash) WHERE {HANDOFF_OPEN_BUSINESS_KEY_PREDICATE}"
            ))
            # HANDOFF-DB-INVARIANT-001: Status-/Count-/Hash-Invarianten fuer
            # neue Schreibvorgaenge (Altzeilen bleiben unberuehrt).
            from models.portfolio_handoff import (
                HANDOFF_INVARIANT_SQLITE_INSERT_TRIGGER,
                HANDOFF_INVARIANT_SQLITE_TRIGGERS,
            )

            # Red-Team 2026-10-28 Befund 4: der Insert-Trigger hat seit
            # Alembic e5b3c9d1a7f4 eine strengere Bedingung -- ein bestehender
            # Trigger gleichen Namens wird ersetzt, nicht per IF NOT EXISTS
            # behalten. Idempotent; Altzeilen bleiben unberuehrt.
            conn.execute(text(f"DROP TRIGGER IF EXISTS {HANDOFF_INVARIANT_SQLITE_INSERT_TRIGGER}"))
            for ddl in HANDOFF_INVARIANT_SQLITE_TRIGGERS:
                conn.execute(text(ddl))
        # RISK-CAPACITY-PLAUSIBILITY-001 Restbefund A (2026-10-20): append-only
        # FinancialCoverageAttestationV1 (idempotent; siehe Konstanten oben).
        for ddl in (FINANCIAL_COVERAGE_ATTESTATION_SQLITE_TABLE_DDL
                    + FINANCIAL_COVERAGE_ATTESTATION_SQLITE_TRIGGERS):
            conn.execute(text(ddl))
        # CMA-001: append-only CMA_POLICY-Freigaben (Tabelle legt create_all an).
        if inspect(conn).has_table("cma_policy_approvals"):
            for ddl in CMA_POLICY_APPROVAL_SQLITE_TRIGGERS:
                conn.execute(text(ddl))
        # DEPOT-E2E-SNAPSHOT-001: append-only DepotSnapshotV1 (idempotent).
        for ddl in DEPOT_SNAPSHOT_SQLITE_TABLE_DDL + DEPOT_SNAPSHOT_SQLITE_TRIGGERS:
            conn.execute(text(ddl))
        # DEPOT-E2E-SNAPSHOT-001: append-only DepotCheckAnalysisSnapshot (idempotent).
        for ddl in DEPOT_CHECK_ANALYSIS_SQLITE_TABLE_DDL + DEPOT_CHECK_ANALYSIS_SQLITE_TRIGGERS:
            conn.execute(text(ddl))
        # DSG-ERASURE-NEW-EVIDENCE-001: hash-gebundene Personenzahl (Schema V2;
        # Namen/Notiz versiegelt). ADD COLUMN feuert den UPDATE-Trigger nicht.
        ensure_column(conn, "financial_coverage_attestations", "household_person_count", "INTEGER")
        # RISK-PROFILE-SIGNOFF-001 (2026-10-20): Signoff-Pointer/-Status am
        # Assessment + append-only Signoff-Tabelle + Altbestand-Markierung.
        ensure_column(conn, "risk_assessments", "signoff_id", "TEXT")
        ensure_column(conn, "risk_assessments", "signoff_hash", "TEXT")
        ensure_column(conn, "risk_assessments", "signoff_status", "TEXT")
        for ddl in RISK_PROFILE_SIGNOFF_SQLITE_TABLE_DDL + RISK_PROFILE_SIGNOFF_SQLITE_TRIGGERS:
            conn.execute(text(ddl))
        ensure_column(conn, "risk_profile_signoffs", "tenant_id", "TEXT")
        conn.execute(text(RISK_PROFILE_SIGNOFF_SQLITE_TENANT_INDEX))
        conn.execute(text(RISK_PROFILE_SIGNOFF_LEGACY_BACKFILL))
        # DSG-ERASURE-APPEND-ONLY-001 (2026-10-21): Kundenschluessel fuer das
        # Crypto-Shredding (services/pii_vault.py), idempotent.
        for ddl in CLIENT_PII_KEYS_SQLITE_TABLE_DDL + CLIENT_PII_KEYS_SQLITE_TRIGGERS:
            conn.execute(text(ddl))
        # GOAL-REVISION-DECISION-001 (2026-10-21): append-only Herabstufungs-
        # Entscheidungen (idempotent; siehe Konstanten oben).
        for ddl in GOAL_REVISION_DECISION_SQLITE_TABLE_DDL + GOAL_REVISION_DECISION_SQLITE_TRIGGERS:
            conn.execute(text(ddl))
        # RISK-CAPACITY-EVALUATION-SNAPSHOT-001: append-only gebundene
        # Plausibilitaetsbewertungen (idempotent; siehe Konstanten oben).
        for ddl in RISK_CAPACITY_EVALUATION_SQLITE_TABLE_DDL + RISK_CAPACITY_EVALUATION_SQLITE_TRIGGERS:
            conn.execute(text(ddl))
        # SIGN-001 (2026-10-27): append-only Vor-Ort-Signatur; DDL einzig aus
        # dem ORM (Indizes + after_create-Trigger), idempotent per checkfirst.
        from models.onsite_signature import APPEND_ONLY_TABLES

        for table_name in APPEND_ONLY_TABLES:
            Base.metadata.tables[table_name].create(bind=conn, checkfirst=True)
        # PG-002 (Red-Team 2026-10-28, Befund 6): direkte Mandantenbindung der
        # append-only Mandats-Evidenz (ADD COLUMN feuert den UPDATE-Trigger
        # nicht); Backfill + Guard: core/mandate_evidence_tenant_boundary.py.
        for table_name in MANDATE_BOUND_TENANT_TABLES:
            ensure_column(conn, table_name, "tenant_id", "TEXT")
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS {tenant_index_name(table_name)} ON {table_name}(tenant_id)"
            ))
        # E-Signing (2026-08-05, User-Direktive): echtes Signatur-Artefakt pro
        # Unterzeichner auf ContractDocument, statt der bisherigen reinen
        # Checkbox-Flags (signed_by_advisor/client). ensure_column ist
        # idempotent -> ergaenzt die Spalten auf bestehenden SQLite-DBs beim
        # naechsten Start, ohne bestehende Vertragsdokumente zu beruehren.
        ensure_column(conn, "contract_documents", "signature_advisor_image", "TEXT")
        ensure_column(conn, "contract_documents", "signature_advisor_signer_name", "TEXT")
        ensure_column(conn, "contract_documents", "signature_advisor_signed_at", "TEXT")
        ensure_column(conn, "contract_documents", "signature_advisor_ip", "TEXT")
        ensure_column(conn, "contract_documents", "signature_client_image", "TEXT")
        ensure_column(conn, "contract_documents", "signature_client_signer_name", "TEXT")
        ensure_column(conn, "contract_documents", "signature_client_signed_at", "TEXT")
        ensure_column(conn, "contract_documents", "signature_client_ip", "TEXT")
        # Fondsuniversum (2026-08-05, User-Direktive): NULL = globaler Katalog
        # (unveraendert), gesetzt = privater Fonds eines Tenants. ensure_column
        # ist idempotent -> ergaenzt bestehende SQLite-DBs additiv.
        ensure_column(conn, "products", "tenant_id", "TEXT")
        # Dokumenten-Archiv (2026-08-20, Kundenfeedback): siehe
        # models/review.py::ContractDocument.pdf_base64. ensure_column ist
        # idempotent -> ergaenzt bestehende SQLite-DBs additiv beim naechsten
        # Start, ohne vorhandene Vertragsdokumente zu beruehren.
        ensure_column(conn, "contract_documents", "pdf_base64", "TEXT")
        ensure_column(conn, "contract_documents", "content_hash", "TEXT")


_ADVISORY_LOG_HASH_FIELDS_PRE_REC007: tuple[str, ...] = (
    "mandate_id", "advisor_id", "entry_type", "entry_datetime",
    "duration_minutes", "communication_channel", "language", "location",
    "title", "description", "decision", "status", "participants_json",
    "topics_json", "risk_warnings_given_json", "cost_disclosure_given",
    "conflict_disclosure_ids_json", "suitability_check_id",
    "recommendation_run_id", "client_signed", "client_signed_at", "version",
)


def _advisory_log_hash_text(row: dict, fields: tuple[str, ...]) -> str:
    """Reproduziert services.advisory_log_integrity.compute_integrity_hash()
    aus einem rohen DB-Row-Dict, ohne die Model-Klasse zu instanziieren
    (diese Migration laeuft mit einer rohen Engine-Connection, vor jedem
    ORM-Session-Setup)."""
    parts = []
    for key in fields:
        value = row.get(key)
        if value is None:
            parts.append("")
        elif isinstance(value, bool) or key in ("cost_disclosure_given", "client_signed"):
            parts.append("1" if value else "0")
        else:
            parts.append(str(value))
    return "\x1f".join(parts)


def migrate_advisory_log_hash_scheme_cost_disclosure_snapshot(target_engine: Engine | None = None) -> None:
    """REC-007 (Codex-Audit 2026-08-25): cost_disclosure_snapshot_json wurde
    dem Integritaets-Hash-Feld-Vertrag hinzugefuegt (siehe
    services/advisory_log_integrity.py::compute_integrity_hash) -- eine
    nachtraegliche Aenderung der tatsaechlich gezeigten Kostenzahlen liess
    integrity_hash vorher unveraendert. Bestehende Zeilen wurden mit dem
    ALTEN Feld-Vertrag signiert; ein blindes Neuberechnen wuerde nicht
    unterscheiden koennen zwischen "Zeile ist unveraendert, nur das Hash-
    Schema wurde erweitert" und "Zeile wurde tatsaechlich manipuliert".

    Diese Migration prueft daher JEDE Zeile zuerst gegen den ALTEN
    Feld-Vertrag (_ADVISORY_LOG_HASH_FIELDS_PRE_REC007) -- nur wenn diese
    Pruefung noch stimmt (Zeile war unter dem alten Schema intakt), wird der
    Hash unter dem NEUEN Vertrag neu berechnet. Zeilen, die schon unter dem
    alten Schema nicht mehr passten (echter Manipulationsverdacht oder ganz
    ohne Hash), werden NICHT angefasst -- der bestehende Alarm bleibt
    sichtbar statt durch die Migration verdeckt zu werden. Idempotent: eine
    bereits migrierte Zeile (Hash passt schon zum neuen Vertrag) wird beim
    naechsten Lauf uebersprungen.
    """
    target_engine = _resolve_engine(target_engine)
    from services.advisory_log_integrity import compute_integrity_hash

    # Nur der SQLite-Legacy-Pfad ruft diese Funktion auf (siehe
    # _run_sqlite_legacy_schema_maintenance) -- Postgres erhaelt das
    # vollstaendige Schema inkl. dieser Spalte bereits ueber die
    # Alembic-Baseline, kein Backfill noetig.
    inspector = inspect(target_engine)
    if not inspector.has_table('advisory_log'):
        return

    with target_engine.begin() as conn:
        existing_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(advisory_log)")).fetchall()
        }
        if "cost_disclosure_snapshot_json" not in existing_columns:
            return
        rows = conn.execute(text(
            "SELECT id, mandate_id, advisor_id, entry_type, entry_datetime, "
            "duration_minutes, communication_channel, language, location, title, "
            "description, decision, status, participants_json, topics_json, "
            "risk_warnings_given_json, cost_disclosure_given, "
            "cost_disclosure_snapshot_json, conflict_disclosure_ids_json, "
            "suitability_check_id, recommendation_run_id, client_signed, "
            "client_signed_at, version, integrity_hash FROM advisory_log "
            "WHERE integrity_hash IS NOT NULL"
        )).mappings().fetchall()
        for row in rows:
            row = dict(row)
            stored_hash = row.get("integrity_hash")
            old_scheme_hash = hashlib.sha256(
                _advisory_log_hash_text(row, _ADVISORY_LOG_HASH_FIELDS_PRE_REC007).encode("utf-8")
            ).hexdigest()
            if old_scheme_hash != stored_hash:
                # Entweder schon migriert (neuer Vertrag) oder echter
                # Manipulationsverdacht -- in beiden Faellen nicht anfassen.
                continue
            new_hash = compute_integrity_hash(payload=row)
            if new_hash == stored_hash:
                continue
            conn.execute(
                text("UPDATE advisory_log SET integrity_hash = :hash WHERE id = :id"),
                {"hash": new_hash, "id": row["id"]},
            )


# H7 C-6: retain_until der Beratungsprotokolle ab Mandatsende statt ab Eintrag.
# Offenes Mandat -> NULL, aber nur fuer die Altberechnung "Eintrag + 10 J."
# (Python-Regel inkl. 29.02. -> 28.02.); jede andere Frist (z.B. nach
# Wiedereroeffnung, N-884-06) bleibt als Mindestfrist stehen. Beendetes Mandat
# -> Maximum aus bisheriger Frist, Eintrag + 10 J. und Mandatsende + 10 J. (nie
# verkuerzend). Gleiche Regel wie services/advisory_log_integrity.py::
# extended_retain_until und Alembic e1c6a7d4b2f9 (PG). Idempotent.
_ADVISORY_LEGACY_RETAIN_SQL = (
    "CASE WHEN strftime('%m-%d', substr(advisory_log.entry_datetime, 1, 10)) = '02-29' "
    "THEN date(substr(advisory_log.entry_datetime, 1, 10), '+10 years', '-1 day') "
    "ELSE date(substr(advisory_log.entry_datetime, 1, 10), '+10 years') END"
)
_ADVISORY_RETAIN_FROM_MANDATE_END_SQL = (
    "(SELECT CASE WHEN date(substr(m.closed_at, 1, 10)) IS NULL THEN "
    "(CASE WHEN substr(advisory_log.retain_until, 1, 10) = "
    f"{_ADVISORY_LEGACY_RETAIN_SQL} THEN NULL ELSE advisory_log.retain_until END) "
    "ELSE MAX(COALESCE(substr(advisory_log.retain_until, 1, 10), ''), "
    "date(substr(m.closed_at, 1, 10), '+10 years'), "
    "COALESCE(date(substr(advisory_log.entry_datetime, 1, 10), '+10 years'), '')) END "
    "FROM mandates m WHERE m.id = advisory_log.mandate_id)"
)


def migrate_advisory_log_retention_from_mandate_end(target_engine: Engine | None = None) -> int:
    """Bestandsmigration fuer retain_until (H7 C-6); Rueckgabe: geaenderte Zeilen."""
    target_engine = _resolve_engine(target_engine)
    inspector = inspect(target_engine)
    if not (inspector.has_table('advisory_log') and inspector.has_table('mandates')):
        return 0
    scope = (
        "EXISTS (SELECT 1 FROM mandates m WHERE m.id = advisory_log.mandate_id) "
        f"AND advisory_log.retain_until IS NOT {_ADVISORY_RETAIN_FROM_MANDATE_END_SQL}"
    )
    with target_engine.begin() as conn:
        pending = conn.execute(text(f"SELECT COUNT(*) FROM advisory_log WHERE {scope}")).scalar() or 0
        if pending:
            conn.execute(text(
                f"UPDATE advisory_log SET retain_until = {_ADVISORY_RETAIN_FROM_MANDATE_END_SQL} "
                f"WHERE {scope}"
            ))
            logger.info(
                "H7 C-6: retain_until von %s Beratungsprotokoll-Zeilen auf Mandatsende "
                "umgestellt (nie verkuerzend; offenes Mandat = NULL)", pending,
            )
    return int(pending)


def run_advisory_log_migration(target_engine: Engine | None = None) -> None:
    target_engine = _resolve_engine(target_engine)
    inspector = inspect(target_engine)
    if not inspector.has_table('advisory_log'):
        return

    with target_engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(advisory_log)"))
        existing = {row[1] for row in result.fetchall()}
        if "recommendation_run_id" not in existing:
            conn.execute(text(
                "ALTER TABLE advisory_log ADD COLUMN recommendation_run_id TEXT"
            ))
        if "status" not in existing:
            conn.execute(text(
                "ALTER TABLE advisory_log ADD COLUMN status TEXT NOT NULL DEFAULT 'Empfohlen'"
            ))
        # Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): Kosten-Offenlegungs-Snapshot,
        # siehe models/review.py::AdvisoryLog.cost_disclosure_snapshot_json.
        if "cost_disclosure_snapshot_json" not in existing:
            conn.execute(text(
                "ALTER TABLE advisory_log ADD COLUMN cost_disclosure_snapshot_json TEXT"
            ))
        # RISK-PROFILE-SIGNOFF-001 (2026-10-20): Kennzeichnung von System-
        # Ereignissen (z.B. 'risk_profile_signoff'), die KEIN Beratungs-
        # gespraech sind und nie als "letzter Termin" zaehlen.
        if "system_event" not in existing:
            conn.execute(text(
                "ALTER TABLE advisory_log ADD COLUMN system_event TEXT"
            ))
        conn.commit()


def run_risk_assessment_answer_migration(target_engine: Engine | None = None) -> None:
    """Bringt risk_assessment_answers auf die kanonische DDL (CHECKs, UNIQUE).

    ANSWERS-MIGRATION-IDEMPOTENT-001 (Incident 2026-10-15): die Bedingung
    verglich 'KENNTNISSE & ERFAHRUNGEN' mit der NICHT grossgeschriebenen DDL
    und war damit immer wahr -- jeder App-Start baute die Tabelle um. pysqlite
    committet DDL sofort; ein unterbrochener oder paralleler Start hinterliess
    risk_assessment_answers__old (alle Zeilen) neben einer leeren ORM-Tabelle,
    und jeder weitere Start scheiterte am RENAME. Jetzt: korrekter Vergleich,
    Umbau in EINER expliziten SQLite-Transaktion, und ein vorgefundener
    unterbrochener Zustand wird sicher abgeschlossen (nur wenn die neue
    Tabelle leer ist -- sonst laut abbrechen statt zu raten).
    """
    target_engine = _resolve_engine(target_engine)
    inspector = inspect(target_engine)
    has_new = inspector.has_table('risk_assessment_answers')
    has_old = inspector.has_table('risk_assessment_answers__old')
    if not has_new and not has_old:
        return

    raw = target_engine.raw_connection()
    try:
        dbapi = raw.driver_connection if hasattr(raw, "driver_connection") else raw.connection
        previous_isolation = dbapi.isolation_level
        dbapi.isolation_level = None  # explizite Transaktionssteuerung, DDL inklusive
        cur = dbapi.cursor()
        # Vorherigen FK-Modus der (gepoolten) Verbindung merken und exakt
        # wiederherstellen -- nie hart auf ON setzen, sonst aendert die
        # Migration das FK-Verhalten aller spaeteren Sessions auf dieser
        # Verbindung (der alte Code setzte die PRAGMAs innerhalb der
        # Transaktion, wo SQLite sie ignoriert).
        previous_fk = int(cur.execute('PRAGMA foreign_keys').fetchone()[0])
        cur.execute('PRAGMA foreign_keys = OFF')
        cur.execute('BEGIN IMMEDIATE')
        try:
            names = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'risk_assessment_answers__old' in names:
                # Unterbrochener Umbau: neue Tabelle darf nur leer sein.
                if 'risk_assessment_answers' in names:
                    n_new = cur.execute('SELECT COUNT(*) FROM risk_assessment_answers').fetchone()[0]
                    if n_new:
                        raise RuntimeError(
                            "risk_assessment_answers__old existiert neben einer NICHT leeren "
                            "risk_assessment_answers -- unterbrochene Migration, bitte manuell pruefen."
                        )
                    cur.execute('DROP TABLE risk_assessment_answers')
            else:
                ddl_text = str(cur.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='risk_assessment_answers'"
                ).fetchone()[0] or '')
                ddl_upper = ddl_text.upper()
                needs_question_upgrade = 'BETWEEN 1 AND 12' not in ddl_upper
                needs_section_upgrade = 'KENNTNISSE & ERFAHRUNGEN' not in ddl_upper
                if not needs_question_upgrade and not needs_section_upgrade:
                    cur.execute('COMMIT')
                    return
                cur.execute('ALTER TABLE risk_assessment_answers RENAME TO risk_assessment_answers__old')
            _rebuild_risk_assessment_answers_from_old(cur)
            cur.execute('COMMIT')
        except Exception:
            cur.execute('ROLLBACK')
            raise
        finally:
            cur.execute(f'PRAGMA foreign_keys = {"ON" if previous_fk else "OFF"}')
            dbapi.isolation_level = previous_isolation
    finally:
        raw.close()


def _rebuild_risk_assessment_answers_from_old(cur) -> None:
    """Kanonische Tabelle aus risk_assessment_answers__old neu aufbauen.

    Laeuft innerhalb der expliziten Transaktion des Aufrufers; prueft, dass
    jede Zeile uebernommen wurde, bevor __old geloescht wird.
    """
    n_old = cur.execute('SELECT COUNT(*) FROM risk_assessment_answers__old').fetchone()[0]
    cur.execute("""
        CREATE TABLE risk_assessment_answers (
            id TEXT PRIMARY KEY,
            assessment_id TEXT NOT NULL REFERENCES risk_assessments(id) ON UPDATE CASCADE,
            question_number INTEGER NOT NULL CHECK(question_number BETWEEN 1 AND 12),
            question_section TEXT NOT NULL CHECK(question_section IN ('Kenntnisse & Erfahrungen','Risikofähigkeit','Risikobereitschaft')),
            answer_label TEXT NOT NULL,
            answer_points INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            UNIQUE(assessment_id, question_number)
        )
    """)
    cur.execute("""
        INSERT INTO risk_assessment_answers (
            id, assessment_id, question_number, question_section,
            answer_label, answer_points, created_at
        )
        SELECT
            id, assessment_id, question_number, question_section,
            answer_label, answer_points, created_at
        FROM risk_assessment_answers__old
    """)
    n_new = cur.execute('SELECT COUNT(*) FROM risk_assessment_answers').fetchone()[0]
    if n_new != n_old:
        raise RuntimeError(
            f"risk_assessment_answers-Umbau unvollstaendig ({n_new} von {n_old} Zeilen)."
        )
    cur.execute('CREATE INDEX IF NOT EXISTS idx_risk_answers ON risk_assessment_answers(assessment_id)')
    cur.execute('DROP TABLE risk_assessment_answers__old')

class AuditLogRebuildInterrupted(RuntimeError):
    """N-869-1 (Pruefrunde #869): ein unterbrochener audit_log-Neuaufbau, der
    sich nicht sicher automatisch abschliessen laesst. Start blockiert
    (fail-closed), CRITICAL im Log -- nie still."""


_audit_log_logger = logging.getLogger("database.audit_log")

_AUDIT_LOG_REBUILT_DDL = """
    CREATE TABLE audit_log (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        user_name TEXT NOT NULL,
        table_name TEXT NOT NULL,
        record_id TEXT NOT NULL,
        action TEXT NOT NULL CHECK(action IN (
            'CREATE','UPDATE','DELETE','LOGIN','EXPORT','PASSWORD_RESET',
            '2FA_DISABLE','2FA_ENABLE','2FA_RECOVERY_REGEN','2FA_RECOVERY_USED',
            'ACTIVATE','APPROVE','BACKFILL','BACKUP','CLIENT_ERASE','CLONE',
            'DB_OPTIMIZE','FOUNDATION_EXAMPLE','FOUNDATION_PURGE','INVITE',
            'INVITE_ACCEPT','INVITE_RESEND','INVITE_REVOKE','MARKET_DATA_PURGE',
            'MARKET_DATA_REFRESH','OPTIMIZER_MODE_CHANGE','PASSWORD_CHANGE',
            'PASSWORD_RESET_CONFIRM','PASSWORD_RESET_REQUEST','REPLACE',
            'REPLACE_ALL','SENSITIVITY','SUPPORT_BUNDLE','UPSERT'
        )),
        field_name TEXT,
        old_value TEXT,
        new_value TEXT,
        mandate_id TEXT,
        client_id TEXT,
        integrity_hash TEXT,
        ip_address TEXT,
        created_at TEXT NOT NULL,
        tenant_id TEXT,
        sequence INTEGER,
        previous_hash TEXT
    )
"""


def _audit_log_ddl_is_current(ddl_text: str) -> bool:
    ddl_text = str(ddl_text or '').upper()
    has_password_reset = 'PASSWORD_RESET' in ddl_text
    has_integrity_hash = 'INTEGRITY_HASH' in ddl_text
    has_ip_address = 'IP_ADDRESS' in ddl_text
    # Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): Marker fuer die erweiterte
    # action-CHECK-Liste (siehe ares_schema.sql) -- ohne diesen 4. Marker
    # wuerden bereits migrierte Installationen (die anderen 3 Marker bereits
    # erfuellt) NIE die erweiterte Liste erhalten und weiterhin bei jedem
    # Admin-Endpunkt mit einem der 26 fehlenden action-Werte crashen.
    has_expanded_actions = 'UPSERT' in ddl_text
    # DSG Art. 32 (2026-08-15): eigener Marker fuer die neue 'CLIENT_ERASE'-
    # Action (identische Bugklasse wie has_expanded_actions oben).
    has_erasure_action = 'CLIENT_ERASE' in ddl_text
    return (
        has_password_reset and has_integrity_hash and has_ip_address
        and has_expanded_actions and has_erasure_action
    )


def ensure_audit_log_actions(target_engine: Engine | None = None) -> None:
    """SQLite: audit_log auf den aktuellen action-CHECK bringen (RENAME +
    Neuaufbau, SQLite kann CHECKs nicht aendern).

    N-869-1 (Pruefrunde #869): Der Neuaufbau lief bisher in
    ``engine.begin()``. pysqlite (Legacy-Transaktionsmodus) oeffnet die
    Transaktion aber erst beim ersten DML -- RENAME und CREATE TABLE liefen im
    Autocommit. Scheiterte das Kopieren (z.B. eine Altzeile verletzt den neuen
    CHECK), blieben ``audit_log__old`` mit der GANZEN Historie und ein leeres
    ``audit_log`` ohne Trigger committet zurueck; beim naechsten Start
    erfuellte das neue DDL alle Marker, die Funktion kehrte sofort zurueck
    und die Historie war fuer Export und Pruefung unsichtbar.

    Jetzt (Muster run_risk_assessment_answer_migration): explizite
    Transaktion ``BEGIN IMMEDIATE`` mit ``isolation_level=None`` -- RENAME,
    CREATE, Kopie, Zeilenzahl-Abgleich, DROP und Trigger sind EINE atomare
    Einheit, ein Fehler rollt alles zurueck. Ein vorgefundener unterbrochener
    Zustand (``audit_log__old`` existiert) wird fortgesetzt, wenn die neue
    Tabelle fehlt oder leer ist (WARNING); liegen in beiden Tabellen Zeilen,
    ist der Zustand nicht sicher aufloesbar: CRITICAL und
    AuditLogRebuildInterrupted (Start blockiert, DB unveraendert).
    """
    target_engine = _resolve_engine(target_engine)
    inspector = inspect(target_engine)
    if not inspector.has_table('audit_log') and not inspector.has_table('audit_log__old'):
        return

    raw = target_engine.raw_connection()
    try:
        dbapi = raw.driver_connection if hasattr(raw, "driver_connection") else raw.connection
        previous_isolation = dbapi.isolation_level
        dbapi.isolation_level = None  # explizite Transaktionssteuerung, DDL inklusive
        cur = dbapi.cursor()
        cur.execute('BEGIN IMMEDIATE')
        try:
            names = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'audit_log__old' in names:
                n_old = cur.execute('SELECT COUNT(*) FROM audit_log__old').fetchone()[0]
                if 'audit_log' in names:
                    n_new = cur.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]
                    if n_new:
                        message = (
                            "audit_log__old (%s Zeilen) existiert neben einer NICHT leeren "
                            "audit_log (%s Zeilen) -- unterbrochener Neuaufbau, nicht sicher "
                            "aufloesbar. Start blockiert, Datenbank unveraendert; bitte manuell "
                            "pruefen (Historie liegt in audit_log__old)." % (n_old, n_new)
                        )
                        _audit_log_logger.critical(message)
                        raise AuditLogRebuildInterrupted(message)
                    cur.execute('DROP TABLE audit_log')
                _audit_log_logger.warning(
                    "Unterbrochener audit_log-Neuaufbau gefunden (%s Zeilen in audit_log__old) "
                    "-- wird atomar fortgesetzt",
                    n_old,
                )
            else:
                ddl = cur.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='audit_log'"
                ).fetchone()[0]
                if _audit_log_ddl_is_current(ddl):
                    cur.execute('COMMIT')
                    return
                cur.execute('ALTER TABLE audit_log RENAME TO audit_log__old')
            _rebuild_audit_log_from_old(cur)
            cur.execute('COMMIT')
        except Exception:
            cur.execute('ROLLBACK')
            raise
        finally:
            dbapi.isolation_level = previous_isolation
    finally:
        raw.close()


def _rebuild_audit_log_from_old(cur) -> None:
    """Neue audit_log aus audit_log__old aufbauen -- innerhalb der expliziten
    Transaktion des Aufrufers. Prueft, dass jede Zeile uebernommen wurde,
    bevor __old geloescht wird, und legt die Trigger wieder an."""
    n_old = cur.execute('SELECT COUNT(*) FROM audit_log__old').fetchone()[0]
    cur.execute(_AUDIT_LOG_REBUILT_DDL)
    # Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): frueher wurden hier NUR die
    # Spalten aus audit_log__old kopiert, die diese Migration bereits
    # kannte -- ein bereits vorhandenes ip_address (aus einem frueheren
    # Lauf dieser selben Migration, z.B. bei erneuter Ausfuehrung nach
    # einem Teil-Upgrade) wuerde sonst stillschweigend verworfen. Daher
    # dynamisch anhand der tatsaechlichen Spalten von audit_log__old.
    # Roadmap #21 (2026-08-08): tenant_id nach demselben Muster.
    # SEC-003 (Codex-Audit 2026-08-26): dito fuer sequence/previous_hash --
    # ohne diese dynamische Uebernahme wuerde eine frische Installation
    # die per ensure_runtime_columns() bereits angelegten Sequenz-Spalten
    # sofort wieder verlieren.
    old_columns = {row[1] for row in cur.execute("PRAGMA table_info(audit_log__old)").fetchall()}
    ip_address_select = "ip_address" if "ip_address" in old_columns else "NULL AS ip_address"
    tenant_id_select = "tenant_id" if "tenant_id" in old_columns else "NULL AS tenant_id"
    sequence_select = "sequence" if "sequence" in old_columns else "NULL AS sequence"
    previous_hash_select = "previous_hash" if "previous_hash" in old_columns else "NULL AS previous_hash"
    # H-865-1 (Pruefrunde #865): integrity_hash wurde hier bisher hart mit
    # "NULL AS integrity_hash" kopiert -- jeder spaetere Neuaufbau haette
    # ALLEN bestehenden Zeilen den Hash genommen, auch den verketteten.
    # integrity_hash, sequence und previous_hash werden 1:1 uebernommen.
    integrity_hash_select = (
        "integrity_hash" if "integrity_hash" in old_columns else "NULL AS integrity_hash"
    )
    cur.execute(f"""
        INSERT INTO audit_log (
            id, user_id, user_name, table_name, record_id, action,
            field_name, old_value, new_value, mandate_id, client_id,
            integrity_hash, ip_address, created_at, tenant_id,
            sequence, previous_hash
        )
        SELECT
            id, user_id, user_name, table_name, record_id, action,
            field_name, old_value, new_value, mandate_id, client_id,
            {integrity_hash_select},
            {ip_address_select},
            created_at,
            {tenant_id_select},
            {sequence_select},
            {previous_hash_select}
        FROM audit_log__old
    """)
    n_new = cur.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]
    if n_new != n_old:
        raise RuntimeError(f"audit_log-Neuaufbau unvollstaendig ({n_new} von {n_old} Zeilen).")
    cur.execute('DROP TABLE audit_log__old')
    # H-865-1: SQLite verwirft beim DROP TABLE audit_log__old die dorthin
    # mitgewanderten Unveraenderlichkeits-Trigger (Befund CEO/CFO/CIO-Audit
    # 2026-08-07). Sie werden hier, in derselben (jetzt echten, N-869-1)
    # Transaktion, wieder angelegt: die neue Tabelle ist nie ohne Schutz
    # committet.
    for statement in _AUDIT_LOG_TRIGGER_DDL:
        cur.execute(statement)


def ensure_audit_log_triggers(target_engine: Engine | None = None) -> None:
    """Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): ensure_audit_log_actions()
    baut audit_log per RENAME+Neuaufbau um (siehe oben). SQLite bindet
    Trigger an die UMBENANNTE Tabelle (audit_log__old) und verwirft sie beim
    abschliessenden DROP TABLE audit_log__old -- die neu angelegte
    audit_log-Tabelle hat danach GAR KEINEN Schutz mehr vor UPDATE/DELETE,
    obwohl ares_schema.sql die Tabelle ausdruecklich als
    unveraenderlich deklariert (trg_audit_log_no_update/no_delete). Da JEDE
    Installation beim ersten Start durch ensure_audit_log_actions() migriert
    wird (die Rohschema-Datei hat noch kein integrity_hash), war dieser
    Schutz in JEDER bisherigen Installation nach dem ersten Start weg --
    unbemerkt, weil kein Test die Trigger tatsaechlich ausloeste. Diese
    Funktion stellt beide Trigger idempotent wieder her (unabhaengig davon,
    ob ensure_audit_log_actions() in diesem Lauf ueberhaupt etwas migriert
    hat) und muss nach JEDEM Start aufgerufen werden."""
    target_engine = _resolve_engine(target_engine)
    inspector = inspect(target_engine)
    if not inspector.has_table('audit_log'):
        return
    with target_engine.begin() as conn:
        _create_audit_log_immutability_triggers(conn)


_AUDIT_LOG_TRIGGER_DDL = (
    """
    CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_update
    BEFORE UPDATE ON audit_log FOR EACH ROW
    BEGIN SELECT RAISE(ABORT, 'audit_log is immutable'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_delete
    BEFORE DELETE ON audit_log FOR EACH ROW
    BEGIN SELECT RAISE(ABORT, 'audit_log is immutable'); END
    """,
    # N-869-3 (Pruefrunde #869): der eigentliche Single-Writer-Schutz. Jede
    # NEUE Zeile muss Teil der Hash-Kette sein (sequence, integrity_hash,
    # previous_hash gesetzt -- previous_hash ist bei der Genesis '' und nie
    # NULL, siehe services/audit.py::log()). Altzeilen ohne sequence bleiben
    # unberuehrt: der Trigger wirkt nur auf INSERT, und der Kopierschritt
    # des Neuaufbaus laeuft, BEVOR die Trigger auf der neuen Tabelle
    # angelegt werden (_rebuild_audit_log_from_old).
    """
    CREATE TRIGGER IF NOT EXISTS trg_audit_log_require_chain
    BEFORE INSERT ON audit_log FOR EACH ROW
    WHEN NEW.sequence IS NULL OR NEW.integrity_hash IS NULL OR NEW.previous_hash IS NULL
    BEGIN SELECT RAISE(ABORT, 'audit_log insert outside hash chain'); END
    """,
    # N-869-7 (Delta-Pruefung #869): INSERT OR REPLACE / REPLACE INTO mit einer
    # vorhandenen id loescht die alte Zeile als Teil der Konfliktaufloesung --
    # bei recursive_triggers=OFF (SQLite-Default) OHNE trg_audit_log_no_delete
    # auszuloesen: eine Zeile liess sich so am Unveraenderlichkeitsschutz
    # vorbei ersetzen. BEFORE-INSERT-Trigger feuern vor der Konfliktaufloesung;
    # dieser weist jede bereits vorhandene id und jede bereits vergebene
    # sequence ab (log() vergibt beide nie doppelt). Der Kopierschritt des
    # Neuaufbaus laeuft vor dem Anlegen der Trigger; sqlite3.backup kopiert
    # Seiten und loest keine Trigger aus.
    """
    CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_replace
    BEFORE INSERT ON audit_log FOR EACH ROW
    WHEN EXISTS (SELECT 1 FROM audit_log WHERE id = NEW.id)
      OR (NEW.sequence IS NOT NULL AND EXISTS (SELECT 1 FROM audit_log WHERE sequence = NEW.sequence))
    BEGIN SELECT RAISE(ABORT, 'audit_log row already exists (no replace)'); END
    """,
)


def _create_audit_log_immutability_triggers(conn) -> None:
    """audit_log-Trigger idempotent anlegen (SQLite). Gemeinsame Quelle
    _AUDIT_LOG_TRIGGER_DDL fuer ensure_audit_log_triggers() und den
    Neuaufbau in ensure_audit_log_actions() (H-865-1, N-869-1)."""
    for statement in _AUDIT_LOG_TRIGGER_DDL:
        conn.execute(text(statement))


SEED_ASSET_CLASS_RETURNS = [
    # year, asset_class, return_bps  (Quelle: SPI/SBI/KGAST konservativ kalibriert)
    (2015, "Aktien",        290),   (2015, "Obligationen",   100),
    (2015, "Immobilien",    180),   (2015, "Liquiditaet",    -30),   (2015, "Alternative",     50),
    (2016, "Aktien",       -180),   (2016, "Obligationen",    20),
    (2016, "Immobilien",    640),   (2016, "Liquiditaet",    -30),   (2016, "Alternative",    380),
    (2017, "Aktien",       2010),   (2017, "Obligationen",   140),
    (2017, "Immobilien",    550),   (2017, "Liquiditaet",    -30),   (2017, "Alternative",    490),
    (2018, "Aktien",       -870),   (2018, "Obligationen",    30),
    (2018, "Immobilien",    110),   (2018, "Liquiditaet",    -10),   (2018, "Alternative",   -980),
    (2019, "Aktien",       3040),   (2019, "Obligationen",   390),
    (2019, "Immobilien",    820),   (2019, "Liquiditaet",    -30),   (2019, "Alternative",    910),
    (2020, "Aktien",        360),   (2020, "Obligationen",   180),
    (2020, "Immobilien",    250),   (2020, "Liquiditaet",    -50),   (2020, "Alternative",    420),
    (2021, "Aktien",       2320),   (2021, "Obligationen",  -120),
    (2021, "Immobilien",    710),   (2021, "Liquiditaet",    -70),   (2021, "Alternative",    630),
    (2022, "Aktien",      -1650),   (2022, "Obligationen", -1280),
    (2022, "Immobilien", -1030),    (2022, "Liquiditaet",    180),   (2022, "Alternative",   -810),
    (2023, "Aktien",       1980),   (2023, "Obligationen",   510),
    (2023, "Immobilien",    -90),   (2023, "Liquiditaet",    150),   (2023, "Alternative",    720),
    (2024, "Aktien",       1320),   (2024, "Obligationen",   310),
    (2024, "Immobilien",    420),   (2024, "Liquiditaet",    100),   (2024, "Alternative",    890),
]


def _seed_asset_class_returns(conn) -> None:
    count = conn.execute(text("SELECT COUNT(*) FROM asset_class_annual_returns")).scalar()
    if count and count > 0:
        return
    from datetime import datetime as _dt
    now = _dt.utcnow().isoformat()
    for (year, ac, ret) in SEED_ASSET_CLASS_RETURNS:
        conn.execute(text("""
            INSERT OR IGNORE INTO asset_class_annual_returns
            (id, year, asset_class, return_bps, source, created_at, updated_at)
            VALUES (:id, :year, :ac, :ret, 'seed', :now, :now)
        """), {"id": str(uuid.uuid4()), "year": year, "ac": ac, "ret": ret, "now": now})


def ensure_snapshot_tables(target_engine: Engine | None = None) -> None:
    with _resolve_engine(target_engine).begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS strategy_snapshots (
                id TEXT PRIMARY KEY,
                mandate_id TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                advisory_assets_rappen INTEGER NOT NULL,
                risk_profile_score INTEGER NOT NULL,
                risk_profile_label TEXT NOT NULL,
                soll_equities_bps INTEGER NOT NULL,
                soll_bonds_bps INTEGER NOT NULL,
                soll_real_estate_bps INTEGER NOT NULL,
                soll_liquidity_bps INTEGER NOT NULL,
                soll_alternatives_bps INTEGER NOT NULL,
                band_equities_lo_bps INTEGER,
                band_equities_hi_bps INTEGER,
                band_bonds_lo_bps INTEGER,
                band_bonds_hi_bps INTEGER,
                band_real_estate_lo_bps INTEGER,
                band_real_estate_hi_bps INTEGER,
                band_liquidity_lo_bps INTEGER,
                band_liquidity_hi_bps INTEGER,
                band_alternatives_lo_bps INTEGER,
                band_alternatives_hi_bps INTEGER,
                advisor_note TEXT,
                goals_summary_json TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_strategy_snapshots_mandate
            ON strategy_snapshots(mandate_id, deleted_at, snapshot_date)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS asset_class_annual_returns (
                id TEXT PRIMARY KEY,
                year INTEGER NOT NULL,
                asset_class TEXT NOT NULL,
                return_bps INTEGER NOT NULL,
                source TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_acr_year_class
            ON asset_class_annual_returns(year, asset_class)
        """))
        # Sprint U-P19: tägliche EOD-Serie je Asset-Klasse (Daily-Backtest)
        # U-P19b: + currency (native Notierungswährung der Proxy-Bar)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS asset_class_price_history (
                id TEXT PRIMARY KEY,
                asset_class TEXT NOT NULL,
                price_date TEXT NOT NULL,
                close_rappen INTEGER NOT NULL,
                currency TEXT,
                source TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_acph_class_date_source
            ON asset_class_price_history(asset_class, price_date, source)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_acph_class_date
            ON asset_class_price_history(asset_class, price_date)
        """))
        # Sprint U-P19b: tägliche FX-Reihe Fremdwährung → CHF
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS asset_class_fx_history (
                id TEXT PRIMARY KEY,
                currency TEXT NOT NULL,
                price_date TEXT NOT NULL,
                rate_to_chf_x10000 INTEGER NOT NULL,
                source TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_acfx_ccy_date_source
            ON asset_class_fx_history(currency, price_date, source)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_acfx_ccy_date
            ON asset_class_fx_history(currency, price_date)
        """))
        _seed_asset_class_returns(conn)


# N-869-9: partieller Unique-Index -- hoechstens ein Bestandssiegel-Eintrag
# (field_name='LEGACY_SEAL' auf table_name='audit_log', siehe services/audit.py).
# Gleiche Anweisung in Alembic d3b7f1a5c9e2 (PostgreSQL).
_LEGACY_SEAL_UNIQUE_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_audit_log_legacy_seal "
    "ON audit_log(field_name) "
    "WHERE field_name = 'LEGACY_SEAL' AND table_name = 'audit_log'"
)


def ensure_audit_log_indexes(target_engine: Engine | None = None) -> None:
    """Sprint U-38 (Roadmap-Punkt 38, 2026-06-01): idempotente Audit-Log-
    Indexes — inkl. neuer Composite-Index (mandate_id, table_name).

    Die Indexes werden zwar im fresh-init via Schema-SQL angelegt, aber
    ensure_audit_log_actions baut die Tabelle bei Schema-Migration neu
    auf und droppt dabei alle existierenden Indexes. Diese Funktion
    stellt sicher dass alle Indexes nach jedem Migrations-Lauf wieder
    da sind.

    Neuer Index in U-38: idx_audit_mandate_table — beschleunigt Queries
    wie "alle Audit-Eintraege fuer Mandat X auf Tabelle Y" (typisches
    Pattern in services.data_export._query_audit_log und in den FINMA-
    Compliance-Reports).
    """
    target_engine = _resolve_engine(target_engine)
    inspector = inspect(target_engine)
    if not inspector.has_table('audit_log'):
        return

    with target_engine.begin() as conn:
        # Alle Indexes idempotent — IF NOT EXISTS macht das Re-Run safe.
        # Reihenfolge nach Spezifitaet: composite zuerst, single-column danach.
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_audit_mandate_table "
            "ON audit_log(mandate_id, table_name)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_audit_record "
            "ON audit_log(table_name, record_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_audit_mandate "
            "ON audit_log(mandate_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_audit_user "
            "ON audit_log(user_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_audit_time "
            "ON audit_log(created_at)"
        ))
        # Roadmap #21 (2026-08-08): beschleunigt den tenant_id-Scope in
        # routers/system.py::get_audit_log (siehe additive_columns['audit_log']
        # in ensure_runtime_columns fuer die Spalte selbst).
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_audit_tenant "
            "ON audit_log(tenant_id)"
        ))
        # N-869-7: Index fuer die sequence-Pruefung in trg_audit_log_no_replace
        # und den Verifier (sonst Tabellenscan je INSERT).
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_audit_sequence "
            "ON audit_log(sequence)"
        ))
    # N-869-9 (Delta 2 #869): hoechstens EIN Bestandssiegel (zweite
    # Verteidigungslinie neben der Sperre in services/audit.py::
    # ensure_legacy_seal). Eigene Transaktion: liegen ausnahmsweise schon
    # zwei Siegel vor, scheitert nur dieser Index -- laut (CRITICAL), ohne
    # den Start zu blockieren; der Verifier prueft dann beide.
    try:
        with target_engine.begin() as conn:
            conn.execute(text(_LEGACY_SEAL_UNIQUE_INDEX_SQL))
    except Exception as exc:  # noqa: BLE001 -- Index darf den Boot nicht stoppen
        _audit_log_logger.critical(
            "Unique-Index ux_audit_log_legacy_seal nicht angelegt (%s) -- mehr als ein "
            "Bestandssiegel vorhanden? Pruefung: GET /admin/system/audit-log/verify",
            type(exc).__name__,
        )


PURGE_HISTORY_COLUMNS: tuple[str, ...] = (
    "id",
    "started_at",
    "finished_at",
    "purged_rows",
    "skipped_providers_json",
    "duration_seconds",
    "errors_json",
)

PURGE_HISTORY_COLUMN_SQL_TYPES: dict[str, str] = {
    "id": "INTEGER",
    "started_at": "TEXT",
    "finished_at": "TEXT",
    "purged_rows": "INTEGER NOT NULL DEFAULT 0",
    "skipped_providers_json": "TEXT",
    "duration_seconds": "REAL",
    "errors_json": "TEXT",
}


def ensure_purge_history_table(target_engine: Engine | None = None) -> None:
    """Create/upgrade ``market_data_purge_history`` for SQLite installs.

    PostgreSQL is provisioned exclusively by Alembic.  In particular, this
    helper must not execute SQLite's ``AUTOINCREMENT`` or ``PRAGMA`` syntax on
    a production connection.  Keeping the no-op here (rather than only in
    ``init_db``) also protects the lazy calls made by the purge service.
    """
    target_engine = _resolve_engine(target_engine)
    if target_engine.dialect.name != "sqlite":
        return
    with target_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS market_data_purge_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                purged_rows INTEGER NOT NULL DEFAULT 0,
                skipped_providers_json TEXT,
                duration_seconds REAL,
                errors_json TEXT
            )
        """))
        existing = {
            str(row[1])
            for row in conn.execute(text("PRAGMA table_info(market_data_purge_history)")).fetchall()
        }
        for column_name, sql_type in PURGE_HISTORY_COLUMN_SQL_TYPES.items():
            if column_name in existing:
                continue
            conn.execute(text(
                f"ALTER TABLE market_data_purge_history ADD COLUMN {column_name} {sql_type}"
            ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_market_data_purge_history_started "
            "ON market_data_purge_history(started_at)"
        ))


def ensure_default_tenant(target_engine: Engine | None = None) -> None:
    """Sprint T1 (2026-06-08): legt den Default-Tenant 'main' an wenn nicht da.

    Tier 1 (Self-Hosted) und Tier 3 (Dedicated) nutzen genau diesen einen
    Eintrag. Tier 2 (Shared-Cloud) ueberschreibt das via T4-Admin-API.

    Idempotent: zweiter Aufruf macht nichts.

    Defensive: Bei Fehler (z.B. Schema noch nicht vollstaendig migriert)
    wird das Anlegen geloggt, der Boot aber nicht abgebrochen.
    """
    try:
        from datetime import datetime, timezone
        from models.tenant import (
            DEFAULT_TENANT_ID,
            LICENSE_STATUS_ACTIVE,
            TIER_1_SELF_HOSTED,
            Tenant,
        )

        with _session_for(target_engine) as db:
            existing = db.query(Tenant).filter(
                Tenant.id == DEFAULT_TENANT_ID
            ).first()
            if existing is not None:
                return
            now = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            )[:-3] + "Z"
            tenant = Tenant(
                id=DEFAULT_TENANT_ID,
                display_name="Default Tenant",
                slug="main",
                hosting_tier=getattr(settings, "deployment_tier", TIER_1_SELF_HOSTED),
                license_status=LICENSE_STATUS_ACTIVE,
                license_valid_until=None,
                max_users=1,
                max_mandates=None,
                storage_quota_mb=None,
                is_active=1,
                created_at=now,
                updated_at=now,
            )
            db.add(tenant)
            db.commit()
    except Exception as exc:  # noqa: BLE001 - gezielt in _handle_startup_step_error
        # Fail-closed (SEED-FK-HYGIENE): ohne 'main' scheitern Tenant-Backfill
        # und Lizenzpruefung; nur ein unvollstaendiges Schema wird uebersprungen.
        _handle_startup_step_error("ensure_default_tenant", exc)


def ensure_default_ch_jurisdiction(target_engine: Engine | None = None) -> None:
    """WP1 (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
    legt die JurisdictionProfile-Zeile fuer "CH" an, wenn sie fehlt.

    Analog zu ensure_default_tenant() direkt darueber: genau eine
    approved/nicht-provisorische Zeile fuer den einzigen heute existierenden
    Markt (Schweiz). Kein Mandat referenziert diese Zeile per FK -- Mandate.
    jurisdiction bleibt NULL fuer CH (siehe models/mandates.py) und wird von
    der bestehenden Engine ausschliesslich als String "CH" interpretiert,
    NICHT als Fremdschluessel auf diese Tabelle. Diese Zeile ist reine
    Stammdaten-Grundlage fuer spaetere Arbeitspakete (Router/UI), die eine
    Liste verfuegbarer/freigegebener Jurisdiktionen brauchen.

    Idempotent: zweiter Aufruf legt keine zweite CH-Zeile an (code ist
    UNIQUE).

    Defensive: Bei Fehler (z.B. Schema noch nicht vollstaendig migriert)
    wird das Anlegen geloggt, der Boot aber nicht abgebrochen.
    """
    try:
        from datetime import datetime, timezone
        from models.jurisdiction import JurisdictionProfile

        with _session_for(target_engine) as db:
            existing = db.query(JurisdictionProfile).filter(
                JurisdictionProfile.code == "CH"
            ).first()
            if existing is not None:
                return
            now = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            )[:-3] + "Z"
            profile = JurisdictionProfile(
                id=new_uuid(),
                code="CH",
                display_name="Schweiz",
                home_currency="CHF",
                is_active=1,
                is_provisional=0,
                status="approved",
                created_by=None,
                created_at=now,
                updated_at=now,
            )
            db.add(profile)
            db.commit()
    except Exception as exc:  # noqa: BLE001 - gezielt in _handle_startup_step_error
        _handle_startup_step_error("ensure_default_ch_jurisdiction", exc)


def ensure_default_de_jurisdiction(target_engine: Engine | None = None) -> None:
    """Deutschland-Anbindung (2026-07-31, Entscheid Auftraggeber): legt die
    DE-JurisdictionProfile-Zeile + Home-Bias-Default-Zeilen an (siehe
    services/jurisdiction/de_seed.py::ensure_de_jurisdiction_seed -- dort die
    volle Herleitung/Begruendung der Werte). Idempotent, defensiv wie
    ensure_default_ch_jurisdiction() direkt darueber -- beruehrt NIE eine
    CH-Zeile und blockiert den Boot nie."""
    try:
        from services.jurisdiction.de_seed import (
            ensure_de_jurisdiction_seed,
            log_legacy_pseudo_created_by_repair,
        )

        with _session_for(target_engine) as db:
            repaired = ensure_de_jurisdiction_seed(db)
            db.commit()
        # N-870-5: erst nach erfolgreichem Commit melden; bei Rollback keine
        # Erfolgszeile.
        log_legacy_pseudo_created_by_repair(repaired)
    except Exception as exc:  # noqa: BLE001 - gezielt in _handle_startup_step_error
        # Hier fiel der DE-Seed unter PRAGMA foreign_keys=ON still aus
        # (Pseudo-Kennung in created_by, SEED-FK-HYGIENE).
        _handle_startup_step_error("ensure_default_de_jurisdiction", exc)


def ensure_client_login_user_tenant_backfill(engine_to_use=None) -> None:
    """SEC-1 (2026-07-04): weist Bestands-Client-Login-User (role='client') mit
    tenant_id IS NULL den Tenant ihres verlinkten Clients zu.

    Hintergrund: Der Client-Login-Pfad (routers/clients.py:create_client_login)
    hat den User historisch OHNE tenant_id angelegt -> NULL-Tenant-User, die im
    Non-Strict-Modus fuer JEDEN Tenant sichtbar sind (Bruch der Mandantentrennung,
    FINMA/FIDLEG/DSG). Der generische ensure_tenant_backfill() wuerde diese Rows
    pauschal nach 'main' ziehen — FALSCH, wenn der verlinkte Client zu einer
    anderen Firma gehoert. Deshalb laeuft dieser praezise Backfill (Tenant vom
    verlinkten Client via client_logins-Linkage) ZUERST.

    Idempotent (zweiter Lauf trifft 0 Rows) und defensiv (fehlende Tabelle/Spalte
    wird uebersprungen; Boot wird nie abgebrochen).
    """
    eng = engine_to_use if engine_to_use is not None else engine
    try:
        from sqlalchemy import text as _sql_text
        with eng.begin() as conn:
            conn.execute(
                _sql_text(
                    """
                    UPDATE users
                    SET tenant_id = (
                        SELECT c.tenant_id
                        FROM client_logins cl
                        JOIN clients c ON c.id = cl.client_id
                        WHERE cl.user_id = users.id
                    )
                    WHERE role = 'client'
                      AND tenant_id IS NULL
                      AND id IN (
                          SELECT cl2.user_id
                          FROM client_logins cl2
                          JOIN clients c2 ON c2.id = cl2.client_id
                          WHERE c2.tenant_id IS NOT NULL
                      )
                    """
                )
            )
    except Exception as exc:  # noqa: BLE001 - gezielt in _handle_startup_step_error
        # Tabelle/Spalte (noch) nicht vorhanden -> ueberspringen. Jeder andere
        # Fehler bricht ab: sonst zoege ensure_tenant_backfill() danach die
        # Client-User pauschal nach 'main' (Bruch der Mandantentrennung).
        _handle_startup_step_error("ensure_client_login_user_tenant_backfill", exc)


def ensure_tenant_backfill(engine_to_use=None) -> None:
    """E1 (2026-06-12, External-Access-Rollout): weist Bestands-Rows mit
    tenant_id IS NULL dem Default-Tenant 'main' zu.

    Hintergrund: tenant_id-Columns sind aus BC-Gruenden NULLABLE; die Isolation
    erlaubt heute `tenant_id == user_tid OR tenant_id IS NULL`. Vor Multi-Firma-
    Echtbetrieb muessen NULL-Rows verschwinden (sonst waeren sie fuer JEDEN Tenant
    sichtbar). Dieser Backfill ist die Vorbereitung fuer eine spaetere NOT-NULL-
    Constraint + das Entfernen der `OR IS NULL`-Klausel.

    2026-07-25 (Generalaudit): NUR in tenancy_mode == "single" (Tier 1/3 —
    strukturell IMMER genau ein Tenant, siehe models/tenant.py-Docstring)
    ist "main" fachlich garantiert korrekt. In tenancy_mode == "multi"
    (Tier 2, mehrere echte Firmen) lief dieser Backfill bisher UNCONDITIONAL
    bei JEDEM Boot und haette jede zukuenftige NULL-tenant_id-Zeile (z.B. durch
    einen noch nicht auditierten Endpoint oder Bug) STILLSCHWEIGEND der Firma
    zugewiesen, die zufaellig 'main' heisst -- eine falsche Zuordnung ist hier
    schlimmer als das (bereits bekannte, dokumentierte) NULL-bleibt-sichtbar-
    fuer-alle-Verhalten, weil sie den Datensatz faelschlich als legitimes
    Eigentum von 'main' erscheinen laesst (Bruch der Mandantentrennung durch
    die Migration selbst). Deshalb: in "multi" ueberspringen, NULL bleibt NULL.

    Kontrollrunde 2026-09-21 (tier_config-Audit): der reine tenancy_mode-
    String-Vergleich oben konnte "nie gesetzt" nicht von "explizit auf den
    Default 'single' gesetzt" unterscheiden -- Settings.tenancy_mode hat den
    Klassendefault "single" (config.py), nicht None. Ein Tier-2-Deployment,
    das NUR deployment_tier=tier2 setzt (wie die Modul-Doku von
    services/tier_config.py es verspricht) aber TENANCY_MODE nicht explizit
    setzt, hatte tenancy_mode=="single" und lief damit durch DIESEN Guard,
    obwohl es ein echtes Multi-Tenant-Deployment ist -- genau das oben
    beschriebene Risiko (falsche 'main'-Zuordnung verwaister Zeilen) blieb
    fuer diesen konkreten, dokumentierten Deployment-Pfad ungeschuetzt.
    Fix: wiederverwendet services.auth._effective_strict_tenant_isolation
    (bereits die kanonische "ist dieses Deployment mandantenfaehig?"-Pruefung,
    inkl. deployment_tier=='tier2'-Fallback) statt eine dritte, abweichende
    Kopie derselben Logik zu pflegen.

    Idempotent (zweiter Lauf trifft 0 Rows) und defensiv (pro Tabelle isoliert;
    fehlende Tabelle/Spalte wird uebersprungen; Boot wird nie abgebrochen).
    """
    from services.auth import _effective_strict_tenant_isolation
    if _effective_strict_tenant_isolation(settings):
        return
    eng = engine_to_use if engine_to_use is not None else engine
    from models.tenant import DEFAULT_TENANT_ID
    for table in ("users", "clients", "mandates", "protocol_bausteine"):
        try:
            with eng.begin() as conn:
                conn.execute(
                    text(
                        f"UPDATE {table} SET tenant_id = :tid WHERE tenant_id IS NULL"
                    ),
                    {"tid": DEFAULT_TENANT_ID},
                )
        except Exception as exc:  # noqa: BLE001 - gezielt in _handle_startup_step_error
            # Tabelle/Spalte (noch) nicht vorhanden -> ueberspringen; sonst Abbruch.
            _handle_startup_step_error(f"ensure_tenant_backfill[{table}]", exc)


_LEGACY_HOUSE_MATRIX_REAL_ESTATE_MAX = {
    "Kapitalschutz": 1000,
    "Defensiv": 1500,
    "Ausgewogen": 1500,
    "Wachstumsorientiert": 1200,
    # Bestehende Datenbanken koennen noch den historischen Kurznamen tragen.
    "Wachstum": 1200,
    "Dynamisch": 1000,
    "Aktien": 800,
}


def migrate_house_matrix_real_estate_cap_20(engine_to_use=None) -> int:
    """Hebt nur unveraenderte Legacy-Defaults auf die neue 20%-Obergrenze.

    Bewusst kein pauschales UPDATE: individuell konfigurierte House-Matrix-
    Zeilen bleiben erhalten. Die Zielquote wird nicht veraendert.
    """
    eng = engine_to_use if engine_to_use is not None else engine
    updated = 0
    try:
        with eng.begin() as conn:
            for profile_name, legacy_max_bps in _LEGACY_HOUSE_MATRIX_REAL_ESTATE_MAX.items():
                result = conn.execute(
                    text(
                        """
                        UPDATE house_matrix
                        SET real_estate_max_bps = 2000,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE is_active = 1
                          AND profile_name = :profile_name
                          AND real_estate_max_bps = :legacy_max_bps
                          AND policy_id IN (
                              SELECT id
                              FROM optimizer_policies
                              WHERE is_current = 1
                                AND max_real_estate_bps >= 2000
                          )
                        """
                    ),
                    {
                        "profile_name": profile_name,
                        "legacy_max_bps": legacy_max_bps,
                    },
                )
                if result.rowcount and result.rowcount > 0:
                    updated += int(result.rowcount)
    except Exception as exc:  # noqa: BLE001 - gezielt in _handle_startup_step_error
        # Eine alte/partielle DB (Tabelle/Spalte fehlt) darf den Start nicht
        # stoppen; ein echter Fehler der Datenmigration schon.
        _handle_startup_step_error("migrate_house_matrix_real_estate_cap_20", exc)
        return 0
    return updated


def _create_or_migrate_schema(active_url: str, target_engine: Engine | None = None) -> None:
    """Roadmap #90: Baseline-Migration + init_db-Switch create_all<->alembic.

    SQLite (Dev/Test/Electron-Desktop, alle 5200+ Tests): unveraendert
    Base.metadata.create_all() -- kein Risiko fuer den bestehenden, sehr gut
    getesteten Pfad.

    Postgres (echte Produktion): alembic upgrade head statt create_all, damit
    Schema-Aenderungen ab jetzt ueber versionierte Migrationen laufen statt
    ueber implizite create_all-Diffs. Die Baseline-Revision (alembic/versions/
    c91f2c722881_baseline_schema.py) wurde aus genau demselben Base.metadata
    generiert -- eine frische Postgres-DB landet exakt beim selben Schema wie
    create_all es fuer SQLite erzeugt. `alembic upgrade head` ist idempotent
    (kein Effekt, wenn die DB schon auf dem neuesten Stand ist), also sicher
    bei jedem App-Start erneut aufzurufen -- wie create_all().

    Die nachfolgenden Legacy-Schemareparaturen gehoeren ausschliesslich zum
    SQLite-Pfad: sie enthalten u.a. PRAGMA, sqlite_master, AUTOINCREMENT und
    SQLite-Trigger-Syntax. PostgreSQL erhaelt das vollstaendige Schema
    stattdessen ueber additive Alembic-Revisionen.
    """
    if not is_postgres_database_url(active_url):
        Base.metadata.create_all(bind=_resolve_engine(target_engine))
        return
    from alembic import command
    from alembic.config import Config as AlembicConfig

    alembic_ini = Path(__file__).resolve().parent / "alembic.ini"
    alembic_cfg = AlembicConfig(str(alembic_ini))
    alembic_cfg.set_main_option("sqlalchemy.url", active_url)
    command.upgrade(alembic_cfg, "head")


_SQLITE_CURRENT_ANCHOR_INDEXES: tuple[tuple[str, str, str, str], ...] = (
    (
        "ux_risk_one_current",
        "risk_assessments",
        "mandate_id",
        "is_current = 1 AND deleted_at IS NULL",
    ),
    (
        "ux_target_alloc_one_current",
        "target_allocations",
        "mandate_id",
        "is_current = 1 AND deleted_at IS NULL",
    ),
    (
        "ux_optimizer_one_current",
        "optimizer_policies",
        "is_current",
        "is_current = 1",
    ),
    # REC-008 (Codex-Audit 2026-08-25): siehe models/review.py::
    # ProductUniverseEntry -- kein "current anchor" im engeren Sinn, aber
    # dasselbe Reparatur-Bedarf-Muster (neue partielle Unique-Index-
    # Definition, die create_all() auf bereits existierenden SQLite-
    # Tabellen nicht rueckwirkend ergaenzt).
    (
        "ux_product_universe_active_entry",
        "product_universe_entries",
        "tenant_id, jurisdiction, product_id",
        "deleted_at IS NULL",
    ),
    (
        # FX-REF-001 (2026-09-04): globale Current-FX-Zeile pro Waehrung war
        # bislang nur applikationsseitig (with_for_update()) geschuetzt.
        "ux_fx_rate_one_current",
        "fx_rates",
        "currency",
        "is_current = 1 AND valid_until IS NULL",
    ),
    (
        # PENSION-TRANSFER-LEDGER-001 (2026-10-19): hoechstens ein aktiver
        # Vorsorgebezug je Quelle, siehe models/wealth.py::WealthInflow.
        # Bestehende Doppel-Links lassen den Index-Aufbau laut scheitern
        # (manuelle Bereinigung statt stiller Gewinnerwahl).
        "ux_wealth_inflow_one_active_pension_link",
        "wealth_inflows",
        "linked_position_id",
        "linked_position_id IS NOT NULL AND is_active = 1 AND deleted_at IS NULL",
    ),
    (
        # ELIG-GOVERNANCE-001 (2026-10-21): find-or-create-Schluessel der
        # Produkt-Eignungs-RuleSets, siehe models/product_eligibility.py.
        "ux_product_eligibility_rule_sets_lineage_tenant",
        "product_eligibility_rule_sets",
        "tenant_scope, tenant_id, jurisdiction, created_by, version",
        "tenant_id IS NOT NULL",
    ),
    (
        "ux_product_eligibility_rule_sets_lineage_global",
        "product_eligibility_rule_sets",
        "tenant_scope, jurisdiction, created_by, version",
        "tenant_id IS NULL",
    ),
)


def _canonical_sqlite_ddl(value: str | None) -> str:
    canonical = re.sub(r'["`\[\]]', "", str(value or "").lower())
    canonical = re.sub(r"\s+", " ", canonical).strip().rstrip(";")
    return canonical.replace(" (", "(").replace("( ", "(").replace(" )", ")")


def ensure_current_anchor_unique_indexes(engine_to_use=None) -> None:
    """Repair current-anchor index drift on existing SQLite databases.

    ``CREATE INDEX IF NOT EXISTS`` does not replace a same-named index whose
    columns changed.  Older desktop databases therefore retain the historical
    OptimizerPolicy index on ``policy_name`` even after the reference schema
    moves to the runtime's global-current contract.  Rebuild only mismatched
    definitions; creation intentionally fails when corrupt duplicate current
    anchors exist instead of choosing an arbitrary row to archive.
    """
    eng = engine_to_use if engine_to_use is not None else engine
    if eng.dialect.name != "sqlite":
        return

    with eng.begin() as conn:
        existing_tables = set(inspect(conn).get_table_names())
        for index_name, table_name, column_name, predicate in (
            _SQLITE_CURRENT_ANCHOR_INDEXES
        ):
            if table_name not in existing_tables:
                continue
            expected = (
                f"CREATE UNIQUE INDEX {index_name} ON {table_name}"
                f"({column_name}) WHERE {predicate}"
            )
            existing = conn.execute(
                text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type = 'index' AND name = :index_name"
                ),
                {"index_name": index_name},
            ).scalar_one_or_none()
            if _canonical_sqlite_ddl(existing) == _canonical_sqlite_ddl(expected):
                continue
            if existing is not None:
                conn.execute(text(f"DROP INDEX {index_name}"))
            conn.execute(text(expected))


def _run_sqlite_legacy_schema_maintenance(target_engine: Engine | None = None) -> None:
    """Run the backwards-compatible schema repair path for SQLite only."""
    eng = _resolve_engine(target_engine)
    ensure_runtime_columns(eng)
    ensure_current_anchor_unique_indexes(eng)
    # UPGRADE-PATH-CHECK-DRIFT-001: erweiterte CHECK-IN-Listen des
    # Referenzschemas erreichten bestehende DBs nie (CREATE TABLE IF NOT EXISTS).
    # Fail-closed (Closure-Review #675): wirft ManualMigrationRequired bzw.
    # FatalRecoveryFailed, wenn Vor- oder Zielzustand nicht verifiziert ist --
    # init_db() faehrt dann bewusst NICHT fort.
    from services.sqlite_check_constraint_upgrade import ensure_sqlite_check_in_lists_current

    ensure_sqlite_check_in_lists_current(eng, resolve_schema_path())
    # PG-002: Tenant-Backfill + Link-/Tenant-Trigger fuer wealth_positions/
    # wealth_inflows; nach dem CHECK-Upgrade, das Tabellen neu aufbauen kann.
    from services.wealth_tenant_boundary import ensure_sqlite_wealth_tenant_boundary

    ensure_sqlite_wealth_tenant_boundary(eng)
    from services.risk_evidence_tenant_boundary import ensure_sqlite_risk_evidence_tenant_boundary

    ensure_sqlite_risk_evidence_tenant_boundary(eng)
    # ELIG-OVERRIDE-APPEND-ONLY-001: Override-Nachweise append-only (Trigger),
    # ohne harten Run-FK (Purge-fest), Spalten approval_mode/tenant_id.
    from core.product_eligibility_override_schema import ensure_sqlite_override_append_only

    ensure_sqlite_override_append_only(eng)
    # PG-002: Mandanten-Guard + Backfill der Mandats-Evidenz NACH dem
    # Override-Umbau (ein Tabellen-Neuaufbau verwirft alle Trigger).
    ensure_sqlite_mandate_evidence_tenant_boundary(eng)
    migrate_house_matrix_real_estate_cap_20(eng)
    ensure_snapshot_tables(eng)
    from services.market_data.provider_health_registry import ensure_provider_health_table

    ensure_provider_health_table(eng)
    ensure_purge_history_table(eng)
    run_risk_assessment_answer_migration(eng)
    run_advisory_log_migration(eng)
    migrate_advisory_log_hash_scheme_cost_disclosure_snapshot(eng)
    migrate_advisory_log_retention_from_mandate_end(eng)
    ensure_audit_log_actions(eng)
    # U-38: Indexes nach ensure_audit_log_actions, weil das die Tabelle
    # ggf. komplett neu baut (Index-Drift-Risk).
    ensure_audit_log_indexes(eng)
    # Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): Immutability-Trigger nach JEDEM
    # Start sicherstellen -- ensure_audit_log_actions() kann sie beim
    # Tabellen-Neuaufbau verwerfen (siehe Docstring dort).
    ensure_audit_log_triggers(eng)


def init_db(target_engine: Engine | None = None) -> None:
    """Schema anlegen/migrieren und Stammdaten sicherstellen.

    DB-ENGINE-DEFAULT-BINDING-001: ``target_engine`` (Default: Modul-Engine zur
    Aufrufzeit) wird an JEDEN Schritt durchgereicht. Ohne Argument bleibt das
    Verhalten unveraendert (``settings.db_path``/Modul-Engine). Mit expliziter
    SQLite-Engine gelten Quarantaene-Pruefung und Rohschema-Bootstrap deren
    Datei; eine SQLite-Engine ohne Datei (In-Memory) faellt dafuer NIE auf
    ``settings.db_path`` zurueck, sondern ueberspringt beide Schritte.
    """
    eng = _resolve_engine(target_engine)
    if target_engine is None:
        active_url = build_database_url(db_path=settings.db_path, db_key=getattr(settings, 'db_key', None))
        db_file = settings.db_path
    else:
        active_url = target_engine.url.render_as_string(hide_password=False)
        db_file = target_engine.url.database if target_engine.dialect.name == "sqlite" else None
        if db_file in ("", ":memory:"):
            db_file = None
    if is_sqlite_database_url(active_url) and db_file:
        # UPGRADE-PATH-CHECK-DRIFT-001: eine quarantaenisierte DB (gescheiterte,
        # nicht verifizierte Wiederherstellung) blockiert jeden weiteren Start.
        from services.sqlite_check_constraint_upgrade import raise_if_quarantined

        raise_if_quarantined(db_file)
    if settings.db_bootstrap_schema_on_startup and is_sqlite_database_url(active_url) and db_file:
        bootstrap_sqlite_schema(db_path=db_file, db_key=getattr(settings, 'db_key', None))

    # Import von Tenant-Model VOR create_all, damit das Table angelegt wird.
    import models.tenant  # noqa: F401
    # WP1 (2026-07-30): dito fuer die neuen Jurisdiktions-Tabellen.
    import models.jurisdiction  # noqa: F401

    _create_or_migrate_schema(active_url, eng)
    if is_sqlite_database_url(active_url):
        _run_sqlite_legacy_schema_maintenance(eng)
    # Sprint T1 (2026-06-08): Default-Tenant 'main' anlegen wenn nicht da.
    # Backwards-Compat: tenant_id-Columns sind NULLABLE, aber die Existenz
    # der 'main'-Row erlaubt T2-Sprint die Auth-Layer-Migration.
    ensure_default_tenant(eng)
    # WP1 (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
    # Default-Jurisdiktion 'CH' anlegen wenn nicht da (analog zu
    # ensure_default_tenant() direkt darueber).
    ensure_default_ch_jurisdiction(eng)
    # Deutschland-Anbindung (2026-07-31): zweite Jurisdiktion, analog CH.
    ensure_default_de_jurisdiction(eng)
    # SEC-1 (2026-07-04): Client-Login-User mit NULL-Tenant praezise auf den
    # Tenant ihres verlinkten Clients ziehen — MUSS vor dem generischen
    # ensure_tenant_backfill() laufen, das sonst pauschal nach 'main' zieht.
    ensure_client_login_user_tenant_backfill(eng)
    # E1 (2026-06-12): Bestands-Rows ohne tenant_id dem 'main'-Tenant zuweisen.
    ensure_tenant_backfill(eng)
    if is_sqlite_database_url(active_url):
        # PG-002: Vermoegens-Tenant erst NACH dem Client-Backfill nachziehen.
        from services.wealth_tenant_boundary import ensure_sqlite_wealth_tenant_boundary

        ensure_sqlite_wealth_tenant_boundary(eng)
        # PG-002 (PR #662): Risiko-Evidence ebenfalls erst nach dem Mandats-
        # Backfill an den Mandanten binden.
        from services.risk_evidence_tenant_boundary import ensure_sqlite_risk_evidence_tenant_boundary

        ensure_sqlite_risk_evidence_tenant_boundary(eng)
        # PG-002 (Red-Team 2026-10-28): Depot-Snapshots und Vor-Ort-Signatur
        # ebenso erst nach dem Mandats-Backfill an den Mandanten binden.
        ensure_sqlite_mandate_evidence_tenant_boundary(eng)
    # Postgres/RLS: SQLite bleibt unveraendert; PostgreSQL erzwingt die
    # Tenant-Isolation zusaetzlich auf Datenbankebene.
    # PG-003 (Codex-Audit 2026-08-25): ensure_postgres_tenant_not_null() lief
    # bisher OHNE table_names-Filter -- also ueber ALLE 8 tenant-gescopten
    # Tabellen inkl. capital_market_assumptions/products. Diese beiden sind
    # aber bewusst GLOBAL/geteilt gedacht (tenant_id IS NULL bedeutet "fuer
    # alle Mandanten", siehe ensure_default_products()); ein Blanket-Backfill
    # nach 'main' + anschliessendes NOT NULL haette diese Semantik
    # UNUMKEHRBAR zerstoert.
    #
    # User-Entscheid 2026-08-26: statt implizitem globalem Teilen sollte jeder
    # Tenant unter Postgres explizit provisionierte eigene Kopien bekommen.
    # Die dafuer vorgesehene Provisioning-Funktion wurde nie gebaut.
    # Stattdessen (RLS-GLOBAL-REFERENCE-ROWS, 2026-10-24): globale Zeilen
    # (tenant_id IS NULL) der Referenztabellen products, capital_market_
    # assumptions und product_eligibility_rule_sets/_rules sind per RLS fuer
    # alle Sessions LESBAR, schreibbar nur per Operator-Bypass (siehe
    # services/postgres_rls.py::GLOBAL_REFERENCE_TABLES). Fuer capital_market_
    # assumptions/optimizer_policies GEHT das mit dem heutigen Schema NICHT
    # ohne groessere Aenderung: beide haben eine GLOBALE (nicht tenant-
    # gescopte) Unique-Constraint auf is_current allein (ux_optimizer_one_
    # current, analog fuer CMA) -- es kann installationsweit nur EINE
    # aktuelle Policy/CMA geben, nicht eine pro Tenant. Eine echte Pro-Tenant-
    # Policy/CMA braeuchte eine Schema-Migration (Unique-Index auf
    # (tenant_id, is_current) statt is_current) UND Anpassung jeder Stelle,
    # die heute "WHERE is_current == 1" als global-eindeutig annimmt
    # (portfolio_engine.py, advisory_report.py, monte_carlo_paths.py, u.v.m.)
    # -- ein eigenstaendiges Architektur-Vorhaben, bewusst NICHT Teil dieses
    # Fixes. Bis dahin bleiben CMA/Policy global (unveraendertes Verhalten);
    # der NOT-NULL-Backfill unten schliesst sie weiterhin aus.
    #
    # Backfill jetzt auf genau dieselben vier Tabellen beschraenkt, die
    # ensure_tenant_backfill() (SQLite, direkt darueber) bereits als sicher
    # erwiesen hat -- product_universe_entries ist ohnehin NOT NULL im
    # Schema, audit_log wird bewusst NIE automatisch zugewiesen (Audit-
    # Provenienz darf nicht geraten werden).
    #
    # Gleicher Guard wie ensure_tenant_backfill() (Kontrollrunde 2026-09-21:
    # ueber _effective_strict_tenant_isolation statt eigenem tenancy_mode-
    # String-Vergleich, siehe dortiger Kommentar -- derselbe Tier-2-ohne-
    # explizites-TENANCY_MODE-Luecke galt hier identisch).
    from services.auth import _effective_strict_tenant_isolation
    if not _effective_strict_tenant_isolation(settings):
        from services.postgres_rls import ensure_postgres_tenant_not_null
        ensure_postgres_tenant_not_null(
            eng, table_names=("users", "clients", "mandates", "protocol_bausteine"),
        )
    from services.postgres_rls import ensure_postgres_rls_policies
    ensure_postgres_rls_policies(eng)
