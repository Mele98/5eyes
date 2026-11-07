"""K-2: ``import main`` registriert ``users`` (B-16).

K-2 hatte den Direktimport ``import models.users`` zunaechst aus ``main.py``
entfernt; seit K-2-Review M1 (``e101ed7d``) steht er dort wieder explizit.
Zusaetzlich registrieren Router, die ``main`` auf Modulebene vor der
App-Erzeugung importiert (``routers.auth`` u. a.), die Tabelle ``users``.
Damit weder ein kuenftiger Umbau von ``main.py`` noch ein Router-Umbau die
Registrierung still verliert, prueft dieser Test in einem frischen Interpreter:

1. Nach ``import main`` steht ``users`` in ``Base.metadata.tables``.
2. ``Base.metadata.sorted_tables`` (Tabellennamen in Reihenfolge) und
   ``app.openapi()`` (kanonisches JSON) haben exakt den Stand vor K-2
   (Golden-Hashes, berechnet auf ``origin/develop`` 1730911e und auf dem
   K-2-Head identisch; ``sorted_tables`` unveraendert seit 9e6b7dd9, der
   OpenAPI-Hash wurde beim Rebase auf 1730911e und mit OF-1 (Audit 2026-11/06,
   neue Felder exchange_code/exchange_code_status/candidates) nachgefuehrt). Aendert eine legitime Schema-/API-Aenderung einen
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

# H-144 (F6): + audit_chain_verification_status (einzige Abweichung der
# Tabellenliste gegenueber 2e5dfcc3, per Diff der sorted_tables geprueft).
GOLDEN_SORTED_TABLES_SHA256 = "119de678ec42d2944c9871dc23e8054a527ced25cb6ee447d6d089e9e892a40b"
# N-869-0 (Pruefrunde #869): nachgefuehrt fuer GET /admin/system/audit-log/verify
# und die Schemas AuditChainGap/AuditChainSection/AuditChainVerification/
# AuditLegacySection (H-865-2). Kein bestehender Pfad, kein bestehendes Schema
# geaendert (Feld-Diff von api/openapi.json, vom Pruefer bestaetigt).
# N-869-2: AuditLegacySection + ambiguous/ambiguous_ids/unexpected_unhashed/
# unexpected_unhashed_ids (nur dieses Schema, Feld-Diff geprueft).
# N-869-4: nur die description von GET /admin/system/audit-log/verify
# (Docstring: Operator-Bypass unter PG-RLS), Feld-Diff geprueft.
# N-869-6: AuditChainSection + ambiguous/ambiguous_count, AuditLegacySection
# + field_shift/field_shift_ids (nur additiv, Feld-Diff geprueft).
# Bestandssiegel: AuditLegacySection + seal_present/seal_ok/seal_sequence/
# seal_count (nur additiv, Feld-Diff geprueft).
# N-869-8: AuditLegacySection + seal_missing (nur additiv, Feld-Diff geprueft).
# Integrationsprobe 2026-11-07: Pins aus #856, #862, #868 und #869 zusammen-
# gefuehrt; api/openapi.json (Git-Merge ohne Konflikt) besteht
# scripts/export_openapi.py --check.
# H-144 (F4/F6): neue Pfade GET /admin/system/audit-log/verification-status,
# POST .../anchor/export und .../anchor/verify, neue Schemas AuditAnchor*,
# AuditChainVerificationStatusOut, AuditVerificationFindings. Kein bestehender
# Pfad, kein bestehendes Schema geaendert (Diff gegen 2e5dfcc3 geprueft).
# Pruefrunde H4: AuditAnchorVerifyRequest + allow_unsigned, AuditAnchorVerification
# + unsigned_accepted/signature "missing" (nur die neuen Schemas).
GOLDEN_OPENAPI_SHA256 = "0e973cc87685937ef40e46d9400ff055cb3a2136bebd4ca8d66fec90b77f83dc"

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
