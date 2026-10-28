"""DB-ENGINE-DEFAULT-BINDING-001: Schema-Schritte binden ihre Engine zur Aufrufzeit.

Befund: ``ensure_audit_log_actions``/``_indexes``/``_triggers`` (und vier
weitere Migrationsschritte in ``database.py``) hatten ``target_engine=engine``
als Default-Argument. Python wertet Defaults beim IMPORT aus -- der Default
war also fuer immer die Engine, auf die ``DB_PATH`` beim ersten Import zeigte.
``init_db()`` rief die drei audit_log-Schritte ohne Argument auf: wurde die
Modul-Engine danach umgebogen (Tests, Werkzeuge), migrierte ``init_db()`` die
audit_log-Tabelle der FALSCHEN Datenbank und liess die Ziel-DB ohne
Unveraenderlichkeits-Trigger. Gleiche Fehlerklasse wie der Incident vom
2026-10-15 (Tests veraenderten eine fremde DB).

Beide Szenarien laufen in einem frischen Prozess: nur dort ist die beim
Import gebundene Engine eine eigens angelegte Wegwerf-DB "A" (statt der
Session-DB des conftest), sodass eine Veraenderung von A messbar ist.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]

_CHILD = r'''
import hashlib, importlib, json, pkgutil, sqlite3, sys
from pathlib import Path

backend, path_a, path_b, mode = sys.argv[1:5]
sys.path.insert(0, backend)
schema = Path(backend) / "5eyes_schema_v4.0_FINAL.sql"

import database
import models
for mod in pkgutil.iter_modules(models.__path__):
    importlib.import_module(f"models.{mod.name}")
from sqlalchemy import create_engine

def schema_hash(path):
    con = sqlite3.connect(path)
    try:
        rows = sorted(
            con.execute(
                "SELECT type, name, COALESCE(sql, '') FROM sqlite_master"
            ).fetchall()
        )
    finally:
        con.close()
    return hashlib.sha256(json.dumps(rows).encode("utf-8")).hexdigest()

def audit_state(path):
    con = sqlite3.connect(path)
    try:
        names = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE tbl_name = 'audit_log'"
            )
        }
        ddl = con.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='audit_log'"
        ).fetchone()[0]
    finally:
        con.close()
    return {
        "has_no_update_trigger": "trg_audit_log_no_update" in names,
        "has_no_delete_trigger": "trg_audit_log_no_delete" in names,
        "has_mandate_table_index": "idx_audit_mandate_table" in names,
        "has_integrity_hash": "INTEGRITY_HASH" in ddl.upper(),
    }

assert Path(database.engine.url.database).resolve() == Path(path_a).resolve()
database.bootstrap_sqlite_schema(db_path=path_a, schema_path=schema)
hash_a_before = schema_hash(path_a)
engine_b = create_engine(f"sqlite:///{path_b}")

if mode == "patched_module_engine":
    # Etabliertes Testmuster: Modul-Engine + db_path umbiegen, init_db() ohne Argument.
    database.engine = engine_b
    database.settings.db_path = path_b
    database.init_db()
elif mode == "explicit_engine":
    database.init_db(engine_b)
else:
    raise SystemExit(f"unknown mode {mode}")

engine_b.dispose()
database.engine.dispose()
print(json.dumps({
    "a_unchanged": schema_hash(path_a) == hash_a_before,
    "a": audit_state(path_a),
    "b": audit_state(path_b),
}))
'''


def _run_child(tmp_path: Path, mode: str) -> dict:
    path_a = tmp_path / "global_a.db"
    path_b = tmp_path / "target_b.db"
    env = dict(os.environ)
    env["DB_PATH"] = str(path_a)
    env.pop("DATABASE_URL", None)
    env.pop("PYTEST_XDIST_WORKER", None)
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, str(BACKEND_ROOT), str(path_a), str(path_b), mode],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


_EXPECTED_MIGRATED = {
    "has_no_update_trigger": True,
    "has_no_delete_trigger": True,
    "has_mandate_table_index": True,
    "has_integrity_hash": True,
}


@pytest.mark.parametrize("mode", ["patched_module_engine", "explicit_engine"])
def test_init_db_migrates_only_the_target_database(tmp_path, mode):
    result = _run_child(tmp_path, mode)

    assert result["a_unchanged"], f"init_db hat die beim Import gebundene DB A veraendert: {result}"
    assert result["b"] == _EXPECTED_MIGRATED, result


def test_schema_steps_have_no_import_time_engine_default():
    import inspect as pyinspect

    import database

    for name in (
        "ensure_audit_log_actions",
        "ensure_audit_log_indexes",
        "ensure_audit_log_triggers",
        "ensure_purge_history_table",
        "run_risk_assessment_answer_migration",
        "run_advisory_log_migration",
        "migrate_advisory_log_hash_scheme_cost_disclosure_snapshot",
    ):
        param = pyinspect.signature(getattr(database, name)).parameters["target_engine"]
        assert param.default is None, name
