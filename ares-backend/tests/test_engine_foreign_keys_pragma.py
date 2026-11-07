"""SEED-FK-HYGIENE (2026-11-05): jede App-Verbindung prueft Fremdschluessel.

Hintergrund: In der Live-DB entstanden 35 verwaiste Zeilen (Pseudo-Kennung in
created_by -> users.id) ueber eine Verbindung OHNE PRAGMA foreign_keys=ON. Und
die Tests sahen den Defekt nicht, weil sie nackte Engines ohne FK-Pragma
nutzten. Dieser Test laesst einen kuenftigen Pfad ohne FK auffallen:

1. Laufzeit: App-Engine (database.create_app_engine / database.engine), die
   Login-Guard-Engine und die Verbindungen nach init_db() haben
   foreign_keys=1; die Referenzdaten einer frischen Installation bestehen
   PRAGMA foreign_key_check.
2. Statisch: jede Stelle im Produktivcode, die eine eigene Engine oder rohe
   SQLite-Verbindung baut oder foreign_keys ausschaltet, muss in
   _DOCUMENTED_WINDOWS stehen -- mit Begruendung (Bootstrap-/Umbau-Fenster,
   Backup/Werkzeug). Eine neue Stelle laesst den Test scheitern.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database
from database import create_app_engine, init_db


def _fk(conn) -> int:
    return int(conn.exec_driver_sql("PRAGMA foreign_keys").scalar())


# ---------------------------------------------------------------------------
# 1. Laufzeit
# ---------------------------------------------------------------------------


def test_app_engine_factory_enables_foreign_keys_on_every_connection(tmp_path):
    eng = create_app_engine(db_path=tmp_path / "fk.db", echo=False)
    try:
        conns = [eng.connect() for _ in range(3)]
        try:
            assert [_fk(c) for c in conns] == [1, 1, 1]
        finally:
            for c in conns:
                c.close()
    finally:
        eng.dispose()


def test_module_engine_and_session_enable_foreign_keys():
    if database.engine.dialect.name != "sqlite":
        pytest.skip("PRAGMA foreign_keys betrifft nur SQLite")
    with database.engine.connect() as conn:
        assert _fk(conn) == 1
    with database.SessionLocal() as db:
        assert int(db.execute(text("PRAGMA foreign_keys")).scalar()) == 1


def test_login_guard_engine_enables_foreign_keys(tmp_path, monkeypatch):
    """Vorher baute services/login_guard.py ein nacktes create_engine ohne
    Pragmas (FK aus) -- genau die Sorte Pfad, die dieser Test finden soll."""
    from config import settings
    from services import login_guard

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "guard.db"))
    monkeypatch.setattr(login_guard, "_ENGINE_CACHE", {})
    eng = login_guard._get_guard_engine()
    try:
        if eng.dialect.name != "sqlite":
            pytest.skip("PRAGMA foreign_keys betrifft nur SQLite")
        with eng.connect() as conn:
            assert _fk(conn) == 1
    finally:
        eng.dispose()


def test_connections_after_init_db_keep_foreign_keys_and_data_is_fk_clean(tmp_path):
    """init_db() faehrt die dokumentierten Umbau-Fenster (FK kurz aus). Danach
    muss jede Verbindung -- auch die gepoolte, die das Fenster benutzt hat --
    wieder foreign_keys=1 haben, und die Seeds duerfen keinen Verstoss
    hinterlassen."""
    eng = create_app_engine(db_path=tmp_path / "boot.db", echo=False)
    try:
        init_db(eng)
        pooled = [eng.connect() for _ in range(eng.pool.size() if hasattr(eng.pool, "size") else 1)]
        try:
            assert all(_fk(c) == 1 for c in pooled)
        finally:
            for c in pooled:
                c.close()
        raw = eng.raw_connection()
        try:
            assert int(raw.cursor().execute("PRAGMA foreign_keys").fetchone()[0]) == 1
        finally:
            raw.close()
        with eng.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
            assert conn.exec_driver_sql(
                "SELECT COUNT(*) FROM jurisdiction_profiles WHERE code IN ('CH','DE')"
            ).scalar() == 2
    finally:
        eng.dispose()


# ---------------------------------------------------------------------------
# 2. Statisch: dokumentierte Fenster
# ---------------------------------------------------------------------------

# (Datei, Funktion, Art) -> Begruendung. Art: "engine" (create_engine /
# engine_from_config), "raw" (sqlite3/sqlcipher3.connect), "fk_off"
# (Zeichenkette "foreign_keys = OFF/0").
_DOCUMENTED_WINDOWS: dict[tuple[str, str, str], str] = {
    ("database.py", "create_app_engine", "engine"):
        "Die App-Engine-Fabrik selbst; haengt attach_sqlite_pragmas an (FK=ON).",
    ("database.py", "bootstrap_sqlite_schema", "raw"):
        "Bootstrap-Fenster: Rohschema per executescript, Verbindung danach geschlossen.",
    ("database.py", "bootstrap_sqlite_schema", "fk_off"):
        "Bootstrap-Fenster: FK aus fuer executescript, danach wieder ON.",
    ("database.py", "run_risk_assessment_answer_migration", "fk_off"):
        "Umbau-Fenster (Tabellen-Neuaufbau); stellt den vorherigen FK-Modus exakt wieder her.",
    ("services/sqlite_check_constraint_upgrade.py", "_ddl_parses", "raw"):
        "In-Memory-Syntaxprobe einer DDL, keine App-Daten.",
    ("services/sqlite_check_constraint_upgrade.py", "_ddl_parses", "fk_off"):
        "In-Memory-Syntaxprobe einer DDL, keine App-Daten.",
    ("services/backup.py", "_open_connection", "raw"):
        "Backup/Restore: kopiert bzw. prueft die Datei byteweise, schreibt keine App-Zeilen.",
    ("alembic/env.py", "run_migrations_online", "engine"):
        "Alembic-Migrationslauf (Postgres erzwingt FKs immer; SQLite nutzt create_all).",
    ("migrate_to_sqlcipher.py", "main", "raw"):
        "Einmal-Werkzeug: Umbau Klartext-DB -> SQLCipher (sqlcipher_export), kein App-Pfad.",
    ("scripts/restore_drill.py", "_create_sandbox_source_db", "raw"):
        "Werkzeug: Wiederherstellungsuebung in einer Sandbox-Kopie.",
    ("scripts/restore_drill.py", "_read_marker", "raw"):
        "Werkzeug: Wiederherstellungsuebung, nur lesend.",
    ("scripts/restore_drill.py", "_integrity_check", "raw"):
        "Werkzeug: Wiederherstellungsuebung, nur PRAGMA integrity_check.",
}

_FK_OFF = re.compile(r"foreign_keys\s*=\s*(off|0|false|no)\b", re.IGNORECASE)
_RAW_MODULES = {"sqlite3", "sqlcipher3", "pysqlcipher3"}
_ENGINE_FACTORIES = {"create_engine", "engine_from_config", "create_async_engine"}


def _scan_sites() -> set[tuple[str, str, str]]:
    sites: set[tuple[str, str, str]] = set()
    for path in sorted(BACKEND_ROOT.rglob("*.py")):
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        if rel.startswith(("tests/", ".venv/", "venv/")) or "/tests/" in rel:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))

        def visit(node, func: str) -> None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func = node.name
            if isinstance(node, ast.Call):
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                base = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else None
                if name in _ENGINE_FACTORIES:
                    sites.add((rel, func, "engine"))
                elif name == "connect" and base in _RAW_MODULES:
                    sites.add((rel, func, "raw"))
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and _FK_OFF.search(node.value):
                sites.add((rel, func, "fk_off"))
            for child in ast.iter_child_nodes(node):
                visit(child, func)

        visit(tree, "<module>")
    return sites


def test_every_engine_raw_connection_and_fk_off_site_is_documented():
    sites = _scan_sites()
    undocumented = sorted(sites - set(_DOCUMENTED_WINDOWS))
    assert not undocumented, (
        "Neue Stelle mit eigener Engine, roher SQLite-Verbindung oder "
        "foreign_keys=OFF. App-Pfade nutzen database.create_app_engine "
        "(FK=ON); ein echtes Bootstrap-/Umbau-Fenster mit Begruendung in "
        "_DOCUMENTED_WINDOWS eintragen:\n" + "\n".join(map(str, undocumented))
    )


def test_documented_windows_are_not_stale():
    stale = sorted(set(_DOCUMENTED_WINDOWS) - _scan_sites())
    assert not stale, "Eintrag ohne Fundstelle -- aus _DOCUMENTED_WINDOWS entfernen:\n" + "\n".join(
        map(str, stale)
    )


def test_scanner_detects_an_unpragmad_engine(tmp_path, monkeypatch):
    """Gegenprobe des Scanners: ein nacktes create_engine in einem Service
    wird gefunden (genau die fruehere login_guard-Form)."""
    fake_root = tmp_path / "backend"
    (fake_root / "services").mkdir(parents=True)
    (fake_root / "services" / "rogue.py").write_text(
        "from sqlalchemy import create_engine\n"
        "def _get():\n"
        "    return create_engine('sqlite:///x.db')\n"
        "def _off(c):\n"
        "    c.execute('PRAGMA foreign_keys = OFF')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys.modules[__name__], "BACKEND_ROOT", fake_root)
    assert _scan_sites() == {
        ("services/rogue.py", "_get", "engine"),
        ("services/rogue.py", "_off", "fk_off"),
    }
