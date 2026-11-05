"""N-865-2 (Pruefrunde #865): audit_log hat genau EINEN Schreiber.

Zwei Backfill-Endpunkte in ``routers/system.py`` schrieben ihr Audit per
``db.add(AuditLog(...))`` an ``services.audit.log()`` vorbei -- ohne
sequence/previous_hash/integrity_hash und ohne tenant_id. Solche Zeilen
stehen ausserhalb der Hash-Kette; eine Manipulation (z.B. beim Ueberschreiben
globaler Referenzdaten) waere nicht nachweisbar.

1. Architektur-Test (AST, kein grep auf Kommentare): ausserhalb von
   ``services/audit.py`` darf kein Produktivcode eine ``AuditLog``-Zeile
   konstruieren oder per Core-/Bulk-API bzw. Roh-SQL in ``audit_log``
   einfuegen. Einzige Ausnahme fuer Roh-SQL ist der SQLite-Neuaufbau in
   ``database.py::ensure_audit_log_actions`` (kopiert bestehende Zeilen 1:1,
   siehe H-865-1).
2. Endpoint-Test: beide Backfill-Pfade schreiben ihren BACKFILL-Eintrag in
   die Kette; ``verify_audit_chain()`` bleibt ok.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _path in (BACKEND_ROOT, TESTS_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from database import get_db  # noqa: E402
from main import app  # noqa: E402
from models.review import AuditLog  # noqa: E402
from services.audit import verify_audit_chain  # noqa: E402
from services.auth import get_current_user, require_admin, require_advisor  # noqa: E402
from test_optimizer_shadow_mode import session_factory  # noqa: E402,F401

# Der einzige erlaubte Konstruktor einer AuditLog-Zeile.
_ALLOWED_CONSTRUCTOR = {"services/audit.py"}
# Roh-SQL "INSERT INTO audit_log": nur der 1:1-Kopierschritt des SQLite-
# Neuaufbaus (ensure_audit_log_actions) -- er erzeugt keine neuen Eintraege.
_ALLOWED_RAW_INSERT = {"database.py"}
_EXCLUDED_DIRS = {"tests", "__pycache__", ".venv", "venv", "node_modules", "build", "dist"}
_BULK_APIS = {"insert", "bulk_insert_mappings", "bulk_save_objects", "add_all"}
_RAW_INSERT = re.compile(r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+[\"`]?audit_log[\"`]?\s*[\(\s]", re.IGNORECASE)


def _production_files() -> list[Path]:
    files: list[Path] = []
    for path in BACKEND_ROOT.rglob("*.py"):
        rel = path.relative_to(BACKEND_ROOT)
        if any(part in _EXCLUDED_DIRS for part in rel.parts):
            continue
        files.append(path)
    return files


def _is_auditlog_ref(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "AuditLog"
    if isinstance(node, ast.Attribute):
        return node.attr == "AuditLog"
    return False


def find_audit_log_writers(source: str) -> list[tuple[int, str]]:
    """Liefert (Zeile, Art) fuer jeden AuditLog-Schreibzugriff im Quelltext."""
    tree = ast.parse(source)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if _is_auditlog_ref(node.func):
                hits.append((node.lineno, "AuditLog(...)"))
                continue
            func_name = (
                node.func.attr if isinstance(node.func, ast.Attribute)
                else node.func.id if isinstance(node.func, ast.Name) else ""
            )
            if func_name in _BULK_APIS and any(_is_auditlog_ref(arg) for arg in node.args):
                hits.append((node.lineno, f"{func_name}(AuditLog)"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _RAW_INSERT.search(node.value):
                hits.append((node.lineno, "INSERT INTO audit_log"))
    return hits


def test_detector_finds_known_bypass_patterns():
    """Positivkontrolle: der Detektor erkennt die Muster, die er verbieten soll
    -- sonst waere der Architektur-Test aus dem falschen Grund gruen."""
    sample = (
        "from models.review import AuditLog\n"
        "import models.review as mr\n"
        "db.add(AuditLog(id='x'))\n"
        "db.add(mr.AuditLog(id='y'))\n"
        "db.execute(insert(AuditLog).values(id='z'))\n"
        "db.bulk_insert_mappings(AuditLog, [{}])\n"
        "db.execute(text('INSERT INTO audit_log (id) VALUES (1)'))\n"
        "# AuditLog(...) im Kommentar ist kein Schreibzugriff\n"
        "class AuditLog(Base):\n    pass\n"
        "db.query(AuditLog).filter(AuditLog.id == 1)\n"
        "db.execute(text('INSERT INTO audit_log_sequence_counter (id) VALUES (1)'))\n"
    )
    kinds = [kind for _, kind in find_audit_log_writers(sample)]
    assert kinds.count("AuditLog(...)") == 2
    assert "insert(AuditLog)" in kinds
    assert "bulk_insert_mappings(AuditLog)" in kinds
    assert kinds.count("INSERT INTO audit_log") == 1
    assert len(kinds) == 5


def test_no_audit_log_rows_constructed_outside_audit_service():
    offenders: list[str] = []
    for path in _production_files():
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        if "AuditLog" not in source and "audit_log" not in source.lower():
            continue
        for lineno, kind in find_audit_log_writers(source):
            if kind == "INSERT INTO audit_log" and rel in _ALLOWED_RAW_INSERT:
                continue
            if kind != "INSERT INTO audit_log" and rel in _ALLOWED_CONSTRUCTOR:
                continue
            offenders.append(f"{rel}:{lineno} {kind}")
    assert not offenders, (
        "audit_log-Zeilen duerfen nur ueber services.audit.log() entstehen "
        "(sequence/previous_hash/integrity_hash/tenant_id), gefunden:\n  "
        + "\n  ".join(offenders)
    )


def test_audit_service_itself_is_seen_by_the_scan():
    """Gegenkontrolle: der Scan erfasst services/audit.py wirklich (sonst
    bewiese der leere Befund oben nichts)."""
    source = (BACKEND_ROOT / "services" / "audit.py").read_text(encoding="utf-8")
    assert find_audit_log_writers(source), "services/audit.py muss den einzigen Konstruktor enthalten"
    assert BACKEND_ROOT / "services" / "audit.py" in _production_files()
    assert BACKEND_ROOT / "routers" / "system.py" in _production_files()


# ---------------------------------------------------------------------------
# Endpoint-Test: BACKFILL landet in der Kette
# ---------------------------------------------------------------------------

def _client(session_factory) -> TestClient:
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    admin_user = SimpleNamespace(
        id="admin-n865", full_name="Admin N865", email="admin@example.test",
        role="admin", tenant_id=None,
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin_user
    app.dependency_overrides[require_advisor] = lambda: admin_user
    app.dependency_overrides[get_current_user] = lambda: admin_user
    return TestClient(app)


_FAKE_RESULT = {"summary": {"rows_written": 7, "error_count": 0}}


@pytest.mark.parametrize(
    ("endpoint", "backfill_target", "table_name"),
    [
        (
            "/admin/system/annual-returns/backfill",
            "services.market_data.annual_returns_backfill.backfill_annual_returns",
            "asset_class_annual_returns",
        ),
        (
            "/admin/system/asset-class-prices/backfill",
            "services.market_data.asset_class_price_backfill.backfill_asset_class_prices",
            "asset_class_price_history",
        ),
    ],
)
def test_backfill_audit_entry_is_part_of_the_hash_chain(
    session_factory, monkeypatch, endpoint, backfill_target, table_name
):
    monkeypatch.setattr("services.market_data.factory.build_default_aggregator", lambda: object())
    monkeypatch.setattr(backfill_target, lambda *a, **k: _FAKE_RESULT)
    try:
        client = _client(session_factory)
        # Zwei Laeufe: der zweite muss an den ersten anschliessen.
        for _ in range(2):
            resp = client.post(f"{endpoint}?from_year=2020&to_year=2021")
            assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()

    with session_factory() as s:
        rows = (
            s.query(AuditLog)
            .filter(AuditLog.action == "BACKFILL", AuditLog.table_name == table_name)
            .order_by(AuditLog.sequence.asc())
            .all()
        )
        assert len(rows) == 2
        for row in rows:
            assert row.sequence is not None, "BACKFILL-Eintrag steht ausserhalb der Kette"
            assert row.integrity_hash and len(row.integrity_hash) == 64
            assert row.created_at.endswith("Z")
            assert row.record_id == "2020-2021"
            assert row.new_value == "rows_written=7 errors=0"
        assert rows[1].previous_hash == rows[0].integrity_hash
        result = verify_audit_chain(s)
    assert result["ok"], result["errors"]
    assert result["checked"] >= 2
