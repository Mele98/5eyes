"""W4-b: Datenpfade des Produkts == Ziel-Layout des Migrators.

Der externe Einmal-Migrator schreibt die Bestandsdaten in ein festes
Ziel-Layout und eine Zielkonfiguration. Das Produkt muss genau dieses Layout
als Default kennen, sonst startet eine migrierte Installation gegen eine
leere Datenbank oder findet ihre Sicherungen nicht. Die Sollwerte unten sind
die im Migrator dokumentierten Zielwerte (README "Zielkonfiguration",
``target_identity``); der Migrator selbst gehoert nie ins Produkt und wird
deshalb hier nicht importiert:

* Datenbank            ``~/ares/ares.db``
* Backup-Verzeichnis   ``<db-verzeichnis>/backups``
* Log-Verzeichnis      ``<db-verzeichnis>/logs``
* Sicherungen          ``ares-backup-<YYYYMMDD-HHMMSS>.db`` mit ``.sha256``
  und ``.hmac256`` daneben

Dazu die uebrigen Produkt-Praefixe (Support-Bundle, Log-Datei,
Check-Upgrade-Sicherung, Restore-Drill) und der Live-DB-Waechter: Er leitet
den Produktivpfad aus derselben Quelle ab und blockiert damit genau den neuen
Default. Einen zweiten, alten Pfad kennt das Produkt nicht.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = BACKEND_ROOT / "tests"
DB_LOCATION = BACKEND_ROOT / "core" / "db_location.py"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Dokumentierte Zielwerte des Migrators (Abgleich, kein Import).
TARGET_DIRNAME = "ares"
TARGET_DB_FILENAME = "ares.db"
TARGET_BACKUP_DIRNAME = "backups"
TARGET_LOG_DIRNAME = "logs"
TARGET_BACKUP_PREFIX = "ares-backup-"
SHA256_SIDECAR_SUFFIX = ".sha256"
HMAC_SIDECAR_SUFFIX = ".hmac256"


def _env(home: Path, **extra: str) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items()
        if k not in {"DB_PATH", "DATABASE_URL", "BACKUP_DIR", "LOG_DIR",
                     "PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT"}
    }
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(extra)
    return env


_SETTINGS_PROBE = textwrap.dedent(
    """
    import json, sys
    sys.path.insert(0, {backend!r})
    import core.db_location as loc
    from config import Settings
    s = Settings(_env_file=None)
    print("PROBE=" + json.dumps({{
        "live": str(loc.default_db_path()),
        "db_path": s.db_path,
        "backup_dir": s.backup_dir,
    }}))
    """
)


def _probe_defaults(home: Path, tmp_path: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", _SETTINGS_PROBE.format(backend=str(BACKEND_ROOT))],
        cwd=str(tmp_path), env=_env(home), capture_output=True, text=True, timeout=120,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("PROBE=")]
    assert proc.returncode == 0 and lines, (proc.stdout[-2000:], proc.stderr[-2000:])
    return json.loads(lines[-1][len("PROBE="):])


def test_default_db_path_backup_dir_and_log_dir_match_migrator_layout(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    got = _probe_defaults(home, tmp_path)
    expected_db = home / TARGET_DIRNAME / TARGET_DB_FILENAME
    assert Path(got["live"]) == expected_db
    assert Path(got["db_path"]) == expected_db
    # Backup-Verzeichnis = Geschwister der DB (Migrator: target_db.parent / "backups").
    assert Path(got["backup_dir"]) == expected_db.parent / TARGET_BACKUP_DIRNAME

    # Log-Verzeichnis ohne LOG_DIR = <db-verzeichnis>/logs (Migrator: "logs").
    import core.logging_setup as logging_setup
    from config import settings

    db_file = tmp_path / "layout" / TARGET_DB_FILENAME
    monkeypatch.setattr(settings, "db_path", str(db_file))
    monkeypatch.setattr(settings, "log_dir", "")
    assert logging_setup.resolve_log_dir() == (db_file.parent / TARGET_LOG_DIRNAME).resolve()
    assert logging_setup.LOG_FILE_NAME == "ares-app.log"


def test_backup_names_and_sidecars_match_migrator_layout():
    import services.backup as backup

    assert backup._BACKUP_FILENAME_PATTERN == TARGET_BACKUP_PREFIX + "{ts}.db"
    assert backup._BACKUP_FILENAME_GLOB == TARGET_BACKUP_PREFIX + "*.db"
    assert backup._HMAC_SIDECAR_SUFFIX == HMAC_SIDECAR_SUFFIX


def test_backup_written_by_the_product_is_found_by_the_migrator_glob(tmp_path, monkeypatch):
    """Ende-zu-Ende: eine echte Sicherung hat Ziel-Praefix und beide Sidecars."""
    import sqlite3

    import services.backup as backup
    from config import settings

    source = tmp_path / "src" / TARGET_DB_FILENAME
    source.parent.mkdir()
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
    monkeypatch.setattr(settings, "backup_hmac_key", "layout-test-hmac-key", raising=False)
    result = backup.backup_database(tmp_path / TARGET_BACKUP_DIRNAME, source_db_path=source)
    name = result.path.name
    assert name.startswith(TARGET_BACKUP_PREFIX) and name.endswith(".db")
    assert result.path.with_name(name + SHA256_SIDECAR_SUFFIX).is_file()
    assert result.path.with_name(name + HMAC_SIDECAR_SUFFIX).is_file()
    assert [p.name for p in backup.list_backups(tmp_path / TARGET_BACKUP_DIRNAME)] == [name]


def test_other_product_prefixes():
    import services.sqlite_check_constraint_upgrade as check_upgrade

    assert check_upgrade.BACKUP_PREFIX == "ares_pre_check_upgrade_"
    maintenance_src = (BACKEND_ROOT / "services" / "maintenance.py").read_text(encoding="utf-8")
    assert "f'ares-support-{stamp}.zip'" in maintenance_src
    assert "glob('ares-backup-*.db.json')" in maintenance_src
    drill_src = (BACKEND_ROOT / "scripts" / "restore_drill.py").read_text(encoding="utf-8")
    assert 'prefix="ares-restore-drill-"' in drill_src


_CONFTEST_PROBE = textwrap.dedent(
    """
    import json, sys
    sys.path[:0] = [{tests!r}, {backend!r}]
    import conftest
    from config import settings
    result = {{"db_path": settings.db_path, "exit": None, "forced_exit": None}}
    try:
        conftest.pytest_sessionstart(None)
    except BaseException as exc:
        result["exit"] = getattr(exc, "returncode", repr(exc))
    # Faellt die Umlenkung weg und zeigt die Session doch auf den neuen
    # Default, muss der Waechter die Session abbrechen.
    settings.db_path = {live!r}
    try:
        conftest.pytest_sessionstart(None)
    except BaseException as exc:
        result["forced_exit"] = getattr(exc, "returncode", repr(exc))
    print("PROBE=" + json.dumps(result))
    """
)


def test_test_session_on_the_new_default_is_redirected_or_aborted(tmp_path):
    home = tmp_path / "home"
    live = home / TARGET_DIRNAME / TARGET_DB_FILENAME
    live.parent.mkdir(parents=True)
    live.write_bytes(b"")
    code = _CONFTEST_PROBE.format(tests=str(TESTS_DIR), backend=str(BACKEND_ROOT), live=str(live))
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=str(tmp_path),
        env=_env(home, DB_PATH=str(live)), capture_output=True, text=True, timeout=120,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("PROBE=")]
    assert proc.returncode == 0 and lines, (proc.stdout[-2000:], proc.stderr[-2000:])
    result = json.loads(lines[-1][len("PROBE="):])
    assert Path(result["db_path"]).resolve() != live.resolve()
    assert result["exit"] is None
    assert result["forced_exit"] == 3
    assert live.read_bytes() == b""


def test_db_location_cli_and_staging_tools_refuse_the_new_default(tmp_path):
    home = tmp_path / "home"
    live = home / TARGET_DIRNAME / TARGET_DB_FILENAME
    live.parent.mkdir(parents=True)
    live.write_bytes(b"")

    out = subprocess.run(
        [sys.executable, str(DB_LOCATION), "live-path"],
        env=_env(home), capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0 and Path(out.stdout.strip()) == live
    check = subprocess.run(
        [sys.executable, str(DB_LOCATION), "check", str(live)],
        env=_env(home), capture_output=True, text=True, timeout=60,
    )
    assert check.returncode == 3

    for tool in ("seed_external_demo.py", "make_demo_accounts_easy.py"):
        proc = subprocess.run(
            [sys.executable, str(BACKEND_ROOT / tool), str(live)],
            cwd=str(BACKEND_ROOT), env=_env(home), capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode != 0, tool
        assert "produktive Datenbank" in proc.stderr, (tool, proc.stderr[-2000:])
    assert live.read_bytes() == b""


def test_staging_tools_default_to_a_separate_file_next_to_the_live_db():
    for tool in ("seed_external_demo.py", "make_demo_accounts_easy.py"):
        src = (BACKEND_ROOT / tool).read_text(encoding="utf-8")
        assert '_default = str(Path.home() / "ares" / "ares-staging.db")' in src, tool


def test_server_unit_and_staging_env_use_the_target_layout():
    deploy = BACKEND_ROOT.parent / "docs" / "deploy"
    unit = (deploy / "ares.service").read_text(encoding="utf-8")
    for line in (
        "User=ares", "Group=ares",
        "WorkingDirectory=/opt/ares/ares-backend",
        "EnvironmentFile=/etc/ares/ares.env",
        "StateDirectory=ares", "LogsDirectory=ares", "ConfigurationDirectory=ares",
        "ReadWritePaths=/var/lib/ares /var/log/ares",
    ):
        assert line in unit.splitlines(), line
    assert "ExecStart=/opt/ares/ares-backend/.venv/bin/gunicorn main:app \\" in unit.splitlines()
    env_example = (deploy / ".env.staging.example").read_text(encoding="utf-8").splitlines()
    for line in ("DB_PATH=/var/lib/ares/ares.db", "BACKUP_DIR=/var/lib/ares/backups", "LOG_DIR=/var/log/ares"):
        assert line in env_example, line
    caddy = (deploy / "Caddyfile").read_text(encoding="utf-8")
    assert "output file /var/log/caddy/ares-access.log" in caddy
