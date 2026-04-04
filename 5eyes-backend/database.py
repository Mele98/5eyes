import sqlite3
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
    return {'check_same_thread': False}


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
            _key = (db_key or settings.db_key or '').replace("'", "''")
            conn.execute(f"PRAGMA key = '{_key}'")
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


def ensure_runtime_columns() -> None:
    additive_columns: dict[str, list[tuple[str, str]]] = {
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
                conn.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}'))
                existing.add(column_name)


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


def ensure_audit_log_actions(target_engine: Engine = engine) -> None:
    inspector = inspect(target_engine)
    if not inspector.has_table('audit_log'):
        return

    with target_engine.begin() as conn:
        ddl = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='audit_log'")
        ).scalar()
        ddl_text = str(ddl or '').upper()
        if 'PASSWORD_RESET' in ddl_text:
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
                created_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            INSERT INTO audit_log (
                id, user_id, user_name, table_name, record_id, action,
                field_name, old_value, new_value, mandate_id, client_id, created_at
            )
            SELECT
                id, user_id, user_name, table_name, record_id, action,
                field_name, old_value, new_value, mandate_id, client_id, created_at
            FROM audit_log__old
        """))
        conn.execute(text('DROP TABLE audit_log__old'))


def init_db() -> None:
    if settings.db_bootstrap_schema_on_startup:
        bootstrap_sqlite_schema(db_path=settings.db_path, db_key=getattr(settings, 'db_key', None))

    Base.metadata.create_all(bind=engine)
    ensure_runtime_columns()
    run_advisory_log_migration(engine)
    ensure_audit_log_actions()
