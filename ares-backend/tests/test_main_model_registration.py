"""K-2: ``import main`` registriert ``users`` auch ohne Direktimport (B-16).

K-2 hat den redundanten Direktimport ``import models.users`` aus ``main.py``
entfernt (Fan-out-Ratsche). Die Tabelle ``users`` wird seitdem ueber Router
registriert, die ``main`` auf Modulebene vor der App-Erzeugung importiert
(``routers.auth`` u. a.). Damit ein kuenftiger Router-Umbau die Registrierung
nicht still verliert, prueft dieser Test in einem frischen Interpreter:

1. Nach ``import main`` steht ``users`` in ``Base.metadata.tables``.
2. ``Base.metadata.sorted_tables`` (Tabellennamen in Reihenfolge) und
   ``app.openapi()`` (kanonisches JSON) haben exakt den Stand vor K-2
   (Golden-Hashes, berechnet auf ``origin/develop`` 9e6b7dd9 und auf dem
   K-2-Head identisch). Aendert eine legitime Schema-/API-Aenderung einen
   Hash, wird der Golden-Wert bewusst im selben Commit nachgefuehrt.

Negativkontrolle: ``database`` allein registriert ``users`` nicht -- die
Pruefung ist also nicht trivial erfuellt.

Frischer Interpreter, damit bereits importierte Module anderer Tests das
Ergebnis nicht faerben; eigene ``DB_PATH`` unter ``tmp_path`` (der Import
oeffnet keine Datenbank, siehe test_openapi_artifact.py).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

GOLDEN_SORTED_TABLES_SHA256 = "3489953a3923c0b020c0d41901d8bc2a9df7556270c387caf7523653a10377b3"
GOLDEN_OPENAPI_SHA256 = "77a150f2a1b5d666ba61a88c007c7365fb90743d5d0cba826c2fde5237cc4314"

_PROBE = """
import hashlib, json
{imports}
from database import Base
tables = Base.metadata.tables
out = {{"users": "users" in tables, "count": len(tables)}}
if {with_app}:
    out["sorted_tables"] = hashlib.sha256(
        "\\n".join(t.name for t in Base.metadata.sorted_tables).encode("utf-8")
    ).hexdigest()
    out["openapi"] = hashlib.sha256(
        json.dumps(main.app.openapi(), sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()
print("PROBE=" + json.dumps(out))
"""


def _isolated_env(db_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["DB_PATH"] = str(db_path)
    for key in ("DATABASE_URL", "DB_KEY", "DB_USE_SQLCIPHER"):
        env.pop(key, None)
    return env


def _probe(tmp_path: Path, imports: str, with_app: bool) -> dict:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(imports=imports, with_app=with_app)],
        cwd=BACKEND_DIR,
        env=_isolated_env(tmp_path / "probe.db"),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    line = [ln for ln in result.stdout.splitlines() if ln.startswith("PROBE=")][-1]
    return json.loads(line[len("PROBE="):])


def test_import_main_registers_users_and_keeps_pre_k2_schema(tmp_path):
    out = _probe(tmp_path, "import main", with_app=True)
    assert out["users"], "Tabelle users nach import main nicht registriert"
    assert out["sorted_tables"] == GOLDEN_SORTED_TABLES_SHA256, (
        "Base.metadata.sorted_tables weicht vom Stand vor K-2 ab"
    )
    assert out["openapi"] == GOLDEN_OPENAPI_SHA256, "app.openapi() weicht vom Stand vor K-2 ab"


def test_negative_control_database_alone_does_not_register_users(tmp_path):
    out = _probe(tmp_path, "", with_app=False)
    assert out["users"] is False, "users waere auch ohne main registriert -- Test waere trivial"
