"""SQLCIPHER-ENGINE-POOL-001 (Pruefrunde #861, N-861-6): echter SQLCipher-Engine-Aufbau.

Befund: ``database.create_app_engine`` uebergab immer ``pool_timeout=30``. Der
pysqlcipher-Dialekt von SQLAlchemy 2.0 waehlt aber SingletonThreadPool, der
dieses Argument nicht kennt -> ``TypeError: Invalid argument(s) 'pool_timeout'``
schon beim Import von ``database`` (Modul-Engine). Mit ``DB_USE_SQLCIPHER=true``
startete das Backend also nie. Die Suite merkte es nicht, weil ``sqlcipher3`` in
requirements.txt auskommentiert ist und es keinen Test mit dem echten Treiber gab
(``test_backup_sqlcipher_support.py`` arbeitet mit einem Fake-Treiber).

Diese Tests laufen gegen die echte Bibliothek und eine Wegwerf-DB in ``tmp_path``.
Der Schluessel wird pro Test zufaellig erzeugt. Ohne ``sqlcipher3`` werden sie
uebersprungen -- ausser ``ARES_REQUIRE_SQLCIPHER=1`` ist gesetzt (CI-Job
"SQLCipher (echte Verschluesselung)"): dann ist ein fehlender Treiber ein Fehler,
damit der Pflicht-Check nie still gruen wird.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.pool import QueuePool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

try:
    import sqlcipher3  # type: ignore
except ImportError:  # pragma: no cover - Umgebung ohne Treiber
    sqlcipher3 = None

if sqlcipher3 is None:
    if os.environ.get("ARES_REQUIRE_SQLCIPHER") == "1":
        raise RuntimeError("ARES_REQUIRE_SQLCIPHER=1, aber sqlcipher3 ist nicht installiert")
    pytest.skip("sqlcipher3 nicht installiert (CI-Job 'SQLCipher' fuehrt diese Tests aus)", allow_module_level=True)

import database  # noqa: E402

# Dieselbe Reihenfolge wie database.bootstrap_sqlite_schema, services/backup.py
# und der Migrator-Codec: Schluessel zuerst, dann die Cipher-Parameter.
CIPHER_PRAGMAS = (
    "PRAGMA cipher_page_size = 4096",
    "PRAGMA kdf_iter = 256000",
    "PRAGMA cipher_hmac_algorithm = HMAC_SHA512",
    "PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512",
)


def _new_key() -> str:
    return secrets.token_hex(32)


@pytest.fixture
def sqlcipher_on(monkeypatch):
    monkeypatch.setattr(database.settings, "db_use_sqlcipher", True)
    monkeypatch.setattr(database.settings, "database_url", None)


def _raw_open(path: Path, key: str):
    # Bewusst unabhaengig von database.apply_sqlcipher_key: Literal-Form wie der
    # Migrator-Codec (ares_migrator/codec.py), damit der Test die Kompatibilitaet
    # mit einem fremden Oeffner prueft und nicht die eigene Hilfsfunktion.
    conn = sqlcipher3.connect(str(path))
    conn.execute("PRAGMA key = '" + key.replace("'", "''") + "'")
    for pragma in CIPHER_PRAGMAS:
        conn.execute(pragma)
    return conn


def test_engine_builds_with_same_pool_as_plain_sqlite_file(sqlcipher_on, tmp_path):
    key = _new_key()
    engine = database.create_app_engine(db_path=tmp_path / "enc.db", db_key=key)
    try:
        assert engine.dialect.name == "sqlite"
        assert engine.dialect.dbapi is sqlcipher3
        # S-1: ein einziger Schluesselweg -- der Schluessel steht nicht in der URL.
        assert engine.url.password is None
        assert key not in engine.url.render_as_string(hide_password=False)
        # Gleiche Pool-Semantik wie der Klartext-Pfad (pysqlite -> QueuePool fuer Datei-DBs).
        assert isinstance(engine.pool, QueuePool)
        assert engine.pool._timeout == 30
    finally:
        engine.dispose()


def test_plain_sqlite_path_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(database.settings, "db_use_sqlcipher", False)
    monkeypatch.setattr(database.settings, "database_url", None)
    engine = database.create_app_engine(db_path=tmp_path / "plain.db", db_key=None)
    try:
        assert engine.dialect.driver == "pysqlite"
        assert isinstance(engine.pool, QueuePool)
        assert engine.pool._timeout == 30
    finally:
        engine.dispose()


def test_write_read_roundtrip_is_encrypted_and_compatible(sqlcipher_on, tmp_path):
    db_file = tmp_path / "enc.db"
    key = _new_key()
    engine = database.create_app_engine(db_path=db_file, db_key=key)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE probe (id INTEGER PRIMARY KEY, val TEXT NOT NULL)"))
            conn.execute(text("INSERT INTO probe (id, val) VALUES (1, 'geheim-ä')"))
        with engine.connect() as conn:
            assert conn.execute(text("SELECT val FROM probe WHERE id = 1")).scalar_one() == "geheim-ä"
            assert conn.execute(text("PRAGMA journal_mode")).scalar_one().lower() == "wal"
            assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            assert conn.execute(text("PRAGMA cipher_version")).scalar_one()
    finally:
        engine.dispose()

    # Neue Engine mit demselben Schluessel liest die Daten.
    engine2 = database.create_app_engine(db_path=db_file, db_key=key)
    try:
        with engine2.connect() as conn:
            assert conn.execute(text("SELECT val FROM probe")).scalars().all() == ["geheim-ä"]
    finally:
        engine2.dispose()

    # Datei ist wirklich verschluesselt: kein SQLite-Header, Klartext-sqlite3 scheitert.
    assert db_file.read_bytes()[:16] != b"SQLite format 3\x00"
    plain = sqlite3.connect(str(db_file))
    try:
        with pytest.raises(sqlite3.DatabaseError):
            plain.execute("SELECT * FROM probe").fetchall()
    finally:
        plain.close()

    # Kompatibel mit dem Roh-Zugriff (Bootstrap, Backup, Migrator-Codec).
    raw = _raw_open(db_file, key)
    try:
        assert raw.execute("SELECT val FROM probe").fetchall() == [("geheim-ä",)]
    finally:
        raw.close()


def test_wrong_key_fails_loudly(sqlcipher_on, tmp_path):
    db_file = tmp_path / "enc.db"
    key = _new_key()
    engine = database.create_app_engine(db_path=db_file, db_key=key)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE probe (id INTEGER PRIMARY KEY)"))
    finally:
        engine.dispose()

    wrong = _new_key()
    assert wrong != key
    bad = database.create_app_engine(db_path=db_file, db_key=wrong)
    try:
        with pytest.raises(DatabaseError, match="not a database"):
            with bad.connect() as conn:
                conn.execute(text("SELECT count(*) FROM probe")).scalar_one()
    finally:
        bad.dispose()


def test_init_db_full_schema_on_sqlcipher(sqlcipher_on, monkeypatch, tmp_path):
    """Der Produktions-Startpfad (init_db: Rohschema-Bootstrap + create_all +
    Legacy-Wartung + Stammdaten) laeuft vollstaendig auf der verschluesselten DB."""
    db_file = tmp_path / "enc.db"
    key = _new_key()
    monkeypatch.setattr(database.settings, "db_key", key)
    engine = database.create_app_engine(db_path=db_file, db_key=key)
    try:
        database.init_db(engine)
        with engine.connect() as conn:
            tables = set(conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars())
            assert {"tenants", "users", "clients", "mandates", "audit_log"} <= tables
            assert conn.execute(text("SELECT count(*) FROM tenants")).scalar_one() >= 1
    finally:
        engine.dispose()
    assert db_file.read_bytes()[:16] != b"SQLite format 3\x00"


def test_backend_module_import_starts_with_sqlcipher_env(tmp_path):
    """Wie der echte Start: frischer Prozess, Konfiguration nur ueber die Umgebung
    (DB_USE_SQLCIPHER=true + DB_KEY), ``import main`` + ``init_db()`` wie im Lifespan.
    Vor dem Fix scheiterte schon ``import database`` (Modul-Engine)."""
    key = _new_key()
    home = tmp_path / "home"
    for sub in ("AppData/Roaming", "AppData/Local"):
        (home / sub).mkdir(parents=True)
    (tmp_path / "tmp").mkdir()
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("TENANT_MASTER_KEK", "DATABASE_URL", "DB_"))}
    env.update({
        "HOME": str(home),
        "USERPROFILE": str(home),
        "APPDATA": str(home / "AppData" / "Roaming"),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "TEMP": str(tmp_path / "tmp"),
        "TMP": str(tmp_path / "tmp"),
        "APP_ENV": "development",
        "DB_PATH": str(tmp_path / "enc.db"),
        "DB_USE_SQLCIPHER": "true",
        "DB_KEY": key,
        "BACKUP_DIR": str(tmp_path / "backups"),
        "LOG_DIR": str(tmp_path / "logs"),
    })
    script = textwrap.dedent(
        """
        import main  # noqa: F401  -- wie der echte Start: App, Router, alle Modelle
        import database
        from sqlalchemy import text
        import sqlcipher3
        assert database.engine.dialect.dbapi is sqlcipher3, database.engine.dialect.dbapi
        database.init_db()
        with database.SessionLocal() as db:
            print("tenants", db.execute(text("SELECT count(*) FROM tenants")).scalar_one())
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(tmp_path),
        env={**env, "PYTHONPATH": str(BACKEND_ROOT)},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    assert "tenants " in result.stdout
    assert (tmp_path / "enc.db").read_bytes()[:16] != b"SQLite format 3\x00"


def test_bootstrap_schema_with_real_sqlcipher(sqlcipher_on, tmp_path):
    """bootstrap_sqlite_schema (laeuft bei jedem Start, db_bootstrap_schema_on_startup)
    setzte ``PRAGMA key = ?`` -> mit echtem sqlcipher3 ``near "?": syntax error``."""
    db_file = tmp_path / "boot.db"
    schema = tmp_path / "schema.sql"
    schema.write_text("CREATE TABLE IF NOT EXISTS boot (id INTEGER PRIMARY KEY);", encoding="utf-8")
    key = _new_key()
    database.bootstrap_sqlite_schema(db_path=db_file, schema_path=schema, db_key=key)
    raw = _raw_open(db_file, key)
    try:
        assert raw.execute("SELECT name FROM sqlite_master WHERE name = 'boot'").fetchall() == [("boot",)]
    finally:
        raw.close()


def test_backup_and_restore_with_real_sqlcipher(sqlcipher_on, monkeypatch, tmp_path):
    import services.backup as backup_mod

    key = _new_key()
    monkeypatch.setattr(database.settings, "db_key", key)
    src = tmp_path / "src.db"
    engine = database.create_app_engine(db_path=src, db_key=key)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)"))
            conn.execute(text("INSERT INTO t VALUES (1, 'alpha'), (2, 'beta')"))
    finally:
        engine.dispose()

    result = backup_mod.backup_database(target_dir=tmp_path / "backups", source_db_path=src, retain_days=0)
    assert result.path.read_bytes()[:16] != b"SQLite format 3\x00"
    restored = tmp_path / "restored.db"
    restore_result = backup_mod.restore_database(backup_path=result.path, target_db_path=restored)
    assert restore_result.hash_verified is True
    raw = _raw_open(restored, key)
    try:
        assert raw.execute("SELECT id, val FROM t ORDER BY id").fetchall() == [(1, "alpha"), (2, "beta")]
    finally:
        raw.close()


# --- SQLCIPHER-SINGLE-KEY-PATH-001 (Pruefrunde #864, S-1) ----------------------
# Ein einziger Schluesselweg: Engine (connect-Event), Rohschema-Bootstrap und
# Backup setzen denselben Schluessel ueber database.apply_sqlcipher_key. Frueher
# lief die Engine ueber die URL (quote_plus/unquote) + Dialekt-``pragma key="..."``:
# ein Leerzeichen wurde still zu "+", ein ``"`` brach die Engine ab.

_ALLOWED_KEYS = [
    "aZ09._~-" * 4,          # jedes erlaubte Sonderzeichen
    "~" + "-" * 30 + ".",    # nur Sonderzeichen am Rand
    "k" * 512,               # Maximallaenge
]


@pytest.mark.parametrize("key", _ALLOWED_KEYS)
def test_engine_bootstrap_and_backup_use_identical_key_bytes(sqlcipher_on, monkeypatch, tmp_path, key):
    import services.backup as backup_mod

    monkeypatch.setattr(database.settings, "db_key", key)
    db_file = tmp_path / "enc.db"
    schema = tmp_path / "schema.sql"
    schema.write_text("CREATE TABLE IF NOT EXISTS boot (id INTEGER PRIMARY KEY, val TEXT);", encoding="utf-8")

    # 1) Bootstrap schreibt, 2) Engine liest und schreibt, 3) Backup-Oeffner und
    # unabhaengiger Roh-Oeffner lesen -- alles mit demselben Schluessel.
    database.bootstrap_sqlite_schema(db_path=db_file, schema_path=schema, db_key=key)
    engine = database.create_app_engine(db_path=db_file, db_key=key)
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO boot (id, val) VALUES (1, 'engine')"))
    finally:
        engine.dispose()
    backup_conn = backup_mod._open_connection(str(db_file), uri=False, db_key=key)
    try:
        assert backup_conn.execute("SELECT val FROM boot").fetchall() == [("engine",)]
        backup_conn.execute("INSERT INTO boot (id, val) VALUES (2, 'backup')")
        backup_conn.commit()
    finally:
        backup_conn.close()
    raw = _raw_open(db_file, key)
    try:
        assert raw.execute("SELECT val FROM boot ORDER BY id").fetchall() == [("engine",), ("backup",)]
    finally:
        raw.close()
    engine2 = database.create_app_engine(db_path=db_file, db_key=key)
    try:
        with engine2.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM boot")).scalar_one() == 2
    finally:
        engine2.dispose()


def test_engine_written_db_roundtrips_through_backup_and_restore(sqlcipher_on, monkeypatch, tmp_path):
    import services.backup as backup_mod

    key = "aZ09._~-" * 8
    monkeypatch.setattr(database.settings, "db_key", key)
    src = tmp_path / "src.db"
    engine = database.create_app_engine(db_path=src, db_key=key)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)"))
            conn.execute(text("INSERT INTO t VALUES (1, 'alpha')"))
    finally:
        engine.dispose()
    result = backup_mod.backup_database(target_dir=tmp_path / "backups", source_db_path=src, retain_days=0)
    restored = tmp_path / "restored.db"
    backup_mod.restore_database(backup_path=result.path, target_db_path=restored)
    engine2 = database.create_app_engine(db_path=restored, db_key=key)
    try:
        with engine2.connect() as conn:
            assert conn.execute(text("SELECT val FROM t")).scalar_one() == "alpha"
    finally:
        engine2.dispose()


@pytest.mark.parametrize("bad", ["Zq7Mark-" + "a" * 20 + " " + "b" * 20, "Zq7Mark-" + "a" * 20 + '"' + "b" * 20])
def test_invalid_key_never_reaches_the_database_and_is_not_leaked(sqlcipher_on, monkeypatch, tmp_path, bad):
    """Auch an der Konfiguration vorbei (expliziter db_key) setzt kein Weg einen
    Schluessel ausserhalb des Formats; die Meldung nennt ihn nicht."""
    import services.backup as backup_mod

    db_file = tmp_path / "enc.db"
    schema = tmp_path / "schema.sql"
    schema.write_text("CREATE TABLE IF NOT EXISTS boot (id INTEGER PRIMARY KEY);", encoding="utf-8")
    engine = database.create_app_engine(db_path=db_file, db_key=bad)
    try:
        with pytest.raises(Exception) as excinfo:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
    finally:
        engine.dispose()
    assert isinstance(excinfo.value, ValueError) or isinstance(getattr(excinfo.value, "orig", None), ValueError)
    with pytest.raises(ValueError) as boot_exc:
        database.bootstrap_sqlite_schema(db_path=db_file, schema_path=schema, db_key=bad)
    with pytest.raises(ValueError) as backup_exc:
        backup_mod._open_connection(str(db_file), uri=False, db_key=bad)
    for exc in (excinfo.value, boot_exc.value, backup_exc.value):
        assert bad not in str(exc) and "Zq7Mark" not in str(exc)
