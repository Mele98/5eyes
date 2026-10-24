"""Kompatibilitäts-Wrapper.

Die SQLCipher-Logik liegt jetzt zentral in database.py und wird über
DB_USE_SQLCIPHER=true plus DB_KEY aktiviert. Dieses Modul bleibt nur bestehen,
damit ältere Imports nicht brechen.
"""

from database import (  # noqa: F401
    Base,
    SessionLocal,
    bootstrap_sqlite_schema,
    build_connect_args,
    build_database_url,
    create_app_engine,
    database_healthcheck,
    engine,
    get_db,
    init_db,
    new_uuid,
    resolve_db_file,
    resolve_schema_path,
)
