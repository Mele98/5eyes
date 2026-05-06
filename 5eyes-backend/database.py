import re
import sqlite3
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Generator
from urllib.parse import quote_plus

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import settings

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
        Path(__file__).parent / '5eyes_schema_v4.0_FINAL.sql',
        Path(__file__).parent.parent / '5eyes_schema_v4.0_FINAL.sql',
    ]
    if pyinstaller_root:
        candidates.insert(0, pyinstaller_root / '5eyes_schema_v4.0_FINAL.sql')
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _sqlcipher_enabled(db_key: str | None = None) -> bool:
    key = db_key or getattr(settings, 'db_key', None)
    return bool(getattr(settings, 'db_use_sqlcipher', False) and key)


def build_database_url(db_path: str | Path | None = None, db_key: str | None = None) -> str:
    db_file = resolve_db_file(db_path)
    if _sqlcipher_enabled(db_key=db_key):
        if not SQLCIPHER_AVAILABLE:
            raise RuntimeError(
                'DB_USE_SQLCIPHER=true ist gesetzt, aber sqlcipher3 ist nicht installiert. '
                'Installiere sqlcipher3-binary oder sqlcipher3.'
            )
        key = quote_plus((db_key or settings.db_key or ''))
        return f'sqlite+pysqlcipher://:{key}@/{db_file}'
    return f'sqlite:///{db_file}'


def build_connect_args(db_key: str | None = None) -> dict[str, Any]:
    _ = db_key
    return {'check_same_thread': False, 'timeout': 30}


def attach_sqlite_pragmas(target_engine: Engine, db_key: str | None = None) -> None:
    @event.listens_for(target_engine, 'connect')
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        if _sqlcipher_enabled(db_key=db_key):
            cursor.execute('PRAGMA cipher_page_size = 4096')
            cursor.execute('PRAGMA kdf_iter = 256000')
            cursor.execute('PRAGMA cipher_hmac_algorithm = HMAC_SHA512')
            cursor.execute('PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512')
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
    kwargs: dict[str, Any] = {
        'connect_args': build_connect_args(db_key=db_key),
        'echo': settings.db_echo if echo is None else echo,
        'pool_timeout': 30,
    }
    if _sqlcipher_enabled(db_key=db_key):
        kwargs['module'] = sqlcipher3
    app_engine = create_engine(build_database_url(db_path=db_path, db_key=db_key), **kwargs)
    attach_sqlite_pragmas(app_engine, db_key=db_key)
    return app_engine


engine = create_app_engine(db_path=settings.db_path, db_key=getattr(settings, 'db_key', None))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
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
        with sqlcipher3.connect(str(db_file)) as conn:
            conn.execute("PRAGMA key = ?", [db_key or settings.db_key or ''])
            conn.execute('PRAGMA cipher_page_size = 4096')
            conn.execute('PRAGMA kdf_iter = 256000')
            conn.execute('PRAGMA cipher_hmac_algorithm = HMAC_SHA512')
            conn.execute('PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512')
            conn.execute('PRAGMA foreign_keys = OFF')
            conn.executescript(sql)
            conn.execute('PRAGMA foreign_keys = ON')
            conn.commit()
        return

    with sqlite3.connect(str(db_file)) as conn:
        conn.execute('PRAGMA foreign_keys = OFF')
        conn.executescript(sql)
        conn.execute('PRAGMA foreign_keys = ON')
        conn.commit()


def database_healthcheck(db: Session) -> dict[str, str]:
    db.execute(text('SELECT 1'))
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


def ensure_runtime_columns() -> None:
    additive_columns: dict[str, list[tuple[str, str]]] = {
        'target_allocations': [
            ('capital_market_assumptions_id', 'TEXT'),
            # C8 audit anchors fuer Reproduzierbarkeit / Drift-Erkennung
            ('preferences_json', 'TEXT'),
            ('input_snapshot_hash', 'TEXT'),
            ('advisory_wealth_at_generation_rappen', 'INTEGER'),
            ('total_wealth_at_generation_rappen', 'INTEGER'),
            ('reserve_needed_at_generation_rappen', 'INTEGER'),
            ('external_reserve_at_generation_rappen', 'INTEGER'),
            # Optimizer-Audit-Anchor (Spec 2026-05-05). NULL fuer pre-Optimizer-
            # Allocations - bedeutet "via House-Matrix-Default berechnet".
            ('optimization_method', 'TEXT'),
            ('optimization_objective_value_milli', 'INTEGER'),
            ('optimization_iterations', 'INTEGER'),
            ('optimization_seed', 'INTEGER'),
            ('optimization_status', 'TEXT'),
            # Phase 6: persistierte Stress-Auswertungen (Phase 5.2) als JSON-String.
            # NULL bei house_matrix-Modus oder Pre-Optimizer-Allocations.
            ('stress_evaluations_json', 'TEXT'),
            # Phase 6.2: persistierter Solver-Reasoning-Trace (list[str] JSON).
            # Damit /current/payload das identische Reasoning liefert wie /generate.
            ('optimizer_reasoning_json', 'TEXT'),
        ],
        'recommendation_positions': [
            ('reference_price_rappen', 'INTEGER'),
            ('reference_price_date', 'TEXT'),
            ('reference_price_source', 'TEXT'),
            ('reference_lookup_mode', 'TEXT'),
            ('reference_price_fetched_at', 'TEXT'),
        ],
        'clients': [
            ('investment_horizon_start', 'TEXT'),
            ('investment_horizon_end', 'TEXT'),
        ],
        'cashflows': [
            ('gross_amount_rappen', 'INTEGER'),
            ('tax_amount_rappen', 'INTEGER'),
            ('timing_precision', 'TEXT'),
        ],
        'capital_market_assumptions': [
            ('correlation_matrix_json', 'TEXT'),
            ('sub_asset_class_assumptions_json', 'TEXT'),
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
        ],
        'target_allocations': [
            ('external_reserve_at_generation_rappen', 'INTEGER'),
            ('capital_market_assumptions_id', 'TEXT'),
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
        ],
    }
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table_name, columns in additive_columns.items():
            existing = {column['name'] for column in inspector.get_columns(table_name)}
            for column_name, sql_type in columns:
                if column_name in existing:
                    continue
                if not re.match(r'^[a-z][a-z0-9_]*$', table_name):
                    raise ValueError(f"Ungültiger Tabellenname: {table_name!r}")
                if not re.match(r'^[a-z][a-z0-9_]*$', column_name):
                    raise ValueError(f"Ungültiger Spaltenname: {column_name!r}")
                if not re.match(r'^[A-Z]+$', sql_type):
                    raise ValueError(f"Ungültiger SQL-Typ: {sql_type!r}")
                conn.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}'))
                existing.add(column_name)

        # RiskAssessment - Kenntnisse & Erfahrungen (SwissLife W305.03, 2026-04-16)
        ensure_column(conn, "risk_assessments", "knowledge_services_json", "TEXT")
        ensure_column(conn, "risk_assessments", "knowledge_instruments_json", "TEXT")
        ensure_column(conn, "risk_assessments", "income_sources_json", "TEXT")


def run_advisory_log_migration(target_engine: Engine = engine) -> None:
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
        conn.commit()


def run_risk_assessment_answer_migration(target_engine: Engine = engine) -> None:
    inspector = inspect(target_engine)
    if not inspector.has_table('risk_assessment_answers'):
        return

    with target_engine.begin() as conn:
        ddl = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='risk_assessment_answers'")
        ).scalar()
        ddl_text = str(ddl or '')
        ddl_upper = ddl_text.upper()
        needs_question_upgrade = 'BETWEEN 1 AND 12' not in ddl_upper
        needs_section_upgrade = 'KENNTNISSE & ERFAHRUNGEN' not in ddl_text
        if not needs_question_upgrade and not needs_section_upgrade:
            return

        conn.execute(text('PRAGMA foreign_keys = OFF'))
        conn.execute(text('ALTER TABLE risk_assessment_answers RENAME TO risk_assessment_answers__old'))
        conn.execute(text("""
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
        """))
        conn.execute(text("""
            INSERT INTO risk_assessment_answers (
                id, assessment_id, question_number, question_section,
                answer_label, answer_points, created_at
            )
            SELECT
                id, assessment_id, question_number, question_section,
                answer_label, answer_points, created_at
            FROM risk_assessment_answers__old
        """))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_risk_answers ON risk_assessment_answers(assessment_id)'))
        conn.execute(text('DROP TABLE risk_assessment_answers__old'))
        conn.execute(text('PRAGMA foreign_keys = ON'))


def ensure_audit_log_actions(target_engine: Engine = engine) -> None:
    inspector = inspect(target_engine)
    if not inspector.has_table('audit_log'):
        return

    with target_engine.begin() as conn:
        ddl = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='audit_log'")
        ).scalar()
        ddl_text = str(ddl or '').upper()
        has_password_reset = 'PASSWORD_RESET' in ddl_text
        has_integrity_hash = 'INTEGRITY_HASH' in ddl_text
        if has_password_reset and has_integrity_hash:
            return

        conn.execute(text('ALTER TABLE audit_log RENAME TO audit_log__old'))
        conn.execute(text("""
            CREATE TABLE audit_log (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                user_name TEXT NOT NULL,
                table_name TEXT NOT NULL,
                record_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('CREATE','UPDATE','DELETE','LOGIN','EXPORT','PASSWORD_RESET')),
                field_name TEXT,
                old_value TEXT,
                new_value TEXT,
                mandate_id TEXT,
                client_id TEXT,
                integrity_hash TEXT,
                created_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            INSERT INTO audit_log (
                id, user_id, user_name, table_name, record_id, action,
                field_name, old_value, new_value, mandate_id, client_id, integrity_hash, created_at
            )
            SELECT
                id, user_id, user_name, table_name, record_id, action,
                field_name, old_value, new_value, mandate_id, client_id,
                NULL AS integrity_hash,
                created_at
            FROM audit_log__old
        """))
        conn.execute(text('DROP TABLE audit_log__old'))


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


def ensure_snapshot_tables() -> None:
    with engine.begin() as conn:
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
        _seed_asset_class_returns(conn)


def init_db() -> None:
    if settings.db_bootstrap_schema_on_startup:
        bootstrap_sqlite_schema(db_path=settings.db_path, db_key=getattr(settings, 'db_key', None))

    Base.metadata.create_all(bind=engine)
    ensure_runtime_columns()
    ensure_snapshot_tables()
    run_risk_assessment_answer_migration(engine)
    run_advisory_log_migration(engine)
    ensure_audit_log_actions()
