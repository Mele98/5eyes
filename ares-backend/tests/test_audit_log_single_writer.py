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

# Erlaubte Schreibstellen, eingeengt auf die FUNKTION (N-869-3): der einzige
# Konstruktor ist services.audit.log(); Roh-SQL "INSERT INTO audit_log" nur im
# 1:1-Kopierschritt des SQLite-Neuaufbaus (erzeugt keine neuen Eintraege).
_ALLOWED = {
    ("services/audit.py", "log", "AuditLog(...)"),
    ("database.py", "_rebuild_audit_log_from_old", "INSERT INTO audit_log"),
}
_EXCLUDED_DIRS = {"tests", "__pycache__", ".venv", "venv", "node_modules", "build", "dist"}
_BULK_APIS = {"insert", "bulk_insert_mappings", "bulk_save_objects", "add_all", "insert_many"}
_SQL_VERB = r"(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|REPLACE\s+INTO|COPY)\s+"
# Optionales Schema-Praefix und Quotes; audit_log_sequence_counter und
# audit_log__old sind ausdruecklich NICHT gemeint.
_SQL_WRITE = re.compile(_SQL_VERB + r"(?:[\"`]?\w+[\"`]?\.)?[\"`]?audit_log[\"`]?(?!\w)", re.IGNORECASE)
# Tabellenname dynamisch eingesetzt (f-String, %, .format, Verkettung).
_SQL_WRITE_DYNAMIC = re.compile(_SQL_VERB + r"(?:\{\}|%s|%\(\w+\)s|\{\w*\})", re.IGNORECASE)
_TABLE_NAME = re.compile(r"^(?:\w+\.)?audit_log$")


def _production_files() -> list[Path]:
    files: list[Path] = []
    for path in BACKEND_ROOT.rglob("*.py"):
        rel = path.relative_to(BACKEND_ROOT)
        if any(part in _EXCLUDED_DIRS for part in rel.parts):
            continue
        files.append(path)
    return files


def _static_text(node: ast.AST) -> str | None:
    """Rekonstruiert SQL-Text aus Literal, f-String, Verkettung oder %-Format;
    nicht-statische Teile werden zu '{}'."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "{}"
            for v in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        left = _static_text(node.left)
        if isinstance(node.op, ast.Mod):
            return left
        right = _static_text(node.right)
        if left is None and right is None:
            return None
        return (left if left is not None else "{}") + (right if right is not None else "{}")
    return None


class _WriterScan(ast.NodeVisitor):
    def __init__(self) -> None:
        self.hits: set[tuple[int, str, str]] = set()
        self.func_stack: list[str] = []
        self.auditlog_names = {"AuditLog"}
        self.table_literal_scopes: set[str] = set()
        self.dynamic_sql: list[tuple[int, str]] = []

    @property
    def scope(self) -> str:
        return self.func_stack[-1] if self.func_stack else "<module>"

    def _hit(self, node: ast.AST, kind: str) -> None:
        self.hits.add((node.lineno, kind, self.scope))

    def is_ref(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.auditlog_names
        if isinstance(node, ast.Attribute):
            return node.attr == "AuditLog"
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
            and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "AuditLog"
        ):
            return True
        return False

    def _visit_function(self, node) -> None:
        self.func_stack.append(node.name)
        self.generic_visit(node)
        self.func_stack.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "AuditLog" and alias.asname:
                self.auditlog_names.add(alias.asname)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if self.is_ref(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.auditlog_names.add(target.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "__table__" and self.is_ref(node.value):
            self._hit(node, "AuditLog.__table__")
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if (
            isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)
            and _TABLE_NAME.match(node.slice.value)
        ):
            self._hit(node, "tables['audit_log']")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func_name = (
            node.func.attr if isinstance(node.func, ast.Attribute)
            else node.func.id if isinstance(node.func, ast.Name) else ""
        )
        if self.is_ref(node.func):
            self._hit(node, "AuditLog(...)")
        elif func_name in _BULK_APIS and any(self.is_ref(arg) for arg in node.args):
            self._hit(node, f"{func_name}(AuditLog)")
        elif (
            func_name == "Table" and node.args and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str) and _TABLE_NAME.match(node.args[0].value)
        ):
            self._hit(node, "Table('audit_log')")
        self.generic_visit(node)

    def _check_text(self, node: ast.AST) -> None:
        text_value = _static_text(node)
        if text_value is None:
            return
        if _SQL_WRITE.search(text_value):
            self._hit(node, "INSERT INTO audit_log")
        elif _SQL_WRITE_DYNAMIC.search(text_value):
            self.dynamic_sql.append((node.lineno, self.scope))

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            if _TABLE_NAME.match(node.value):
                self.table_literal_scopes.add(self.scope)
            self._check_text(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        self._check_text(node)
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        self._check_text(node)
        self.generic_visit(node)


def find_audit_log_writers(source: str) -> list[tuple[int, str, str]]:
    """Liefert (Zeile, Art, Funktion) fuer jeden audit_log-Schreibzugriff.

    N-869-3 (Pruefrunde #869): erkennt neben AuditLog(...) und
    insert/bulk_*(AuditLog) auch Alias-Importe, Zuweisungen,
    getattr(..., 'AuditLog'), AuditLog.__table__ (insert()/insert(table)),
    Table('audit_log', ...) und metadata.tables['audit_log'] (Reflection),
    Roh-SQL mit Schema-Praefix/Quotes/COPY sowie dynamisch gebautes SQL
    (Tabellenname per f-String/%/Verkettung), wenn in derselben Funktion
    das Literal 'audit_log' vorkommt. Der eigentliche Schutz ist der
    DB-Trigger trg_audit_log_require_chain (siehe database.py); dieser Test
    faengt versehentliche Umgehungen schon im Review ab.
    """
    scan = _WriterScan()
    scan.visit(ast.parse(source))
    hits = set(scan.hits)
    for lineno, scope in scan.dynamic_sql:
        if scope in scan.table_literal_scopes:
            hits.add((lineno, "dynamisches INSERT (audit_log)", scope))
    return sorted(hits)


def test_detector_finds_known_bypass_patterns():
    """Positivkontrolle: der Detektor erkennt die Muster, die er verbieten soll
    -- sonst waere der Architektur-Test aus dem falschen Grund gruen. Enthaelt
    alle Umgehungen, die die Pruefrunde #869 gefunden hat."""
    sample = (
        "from models.review import AuditLog\n"
        "from models.review import AuditLog as AL\n"
        "import models.review as mr\n"
        "db.add(AuditLog(id='x'))\n"                                   # 4
        "db.add(mr.AuditLog(id='y'))\n"                                # 5
        "db.execute(insert(AuditLog).values(id='z'))\n"                # 6
        "db.bulk_insert_mappings(AuditLog, [{}])\n"                    # 7
        "db.execute(text('INSERT INTO audit_log (id) VALUES (1)'))\n"  # 8
        "db.add(AL(id='a'))\n"                                         # 9
        "M = AuditLog\n"
        "db.add(M(id='m'))\n"                                          # 11
        "db.add(getattr(mr, 'AuditLog')(id='g'))\n"                    # 12
        "db.execute(AuditLog.__table__.insert())\n"                    # 13
        "db.execute(insert(AuditLog.__table__))\n"                     # 14
        "t = Table('audit_log', md, autoload_with=engine)\n"           # 15
        "t2 = md.tables['audit_log']\n"                                # 16
        "db.execute(text('INSERT INTO public.audit_log (id) VALUES (1)'))\n"  # 17
        "cur.copy_expert('COPY \"audit_log\" FROM STDIN', f)\n"        # 18
        "def dyn(name='audit_log'):\n"
        "    db.execute(text(f'INSERT INTO {name} (id) VALUES (1)'))\n"  # 20
        "def concat():\n"
        "    db.execute(text('INSERT INTO ' + 'audit_log' + ' (id) VALUES (1)'))\n"  # 22
        "# AuditLog(...) im Kommentar ist kein Schreibzugriff\n"
        "class AuditLog(Base):\n    pass\n"
        "db.query(AuditLog).filter(AuditLog.id == 1)\n"
        "isinstance(obj, AuditLog)\n"
        "db.execute(text('INSERT INTO audit_log_sequence_counter (id) VALUES (1)'))\n"
        "def generic(table):\n"
        "    db.execute(text(f'INSERT INTO {table} SELECT * FROM x'))\n"
    )
    lines = {lineno for lineno, _, _ in find_audit_log_writers(sample)}
    assert lines == {4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 20, 22}, sorted(lines)


def test_no_audit_log_rows_constructed_outside_audit_service():
    offenders: list[str] = []
    for path in _production_files():
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        if "AuditLog" not in source and "audit_log" not in source.lower():
            continue
        for lineno, kind, scope in find_audit_log_writers(source):
            if (rel, scope, kind) in _ALLOWED:
                continue
            offenders.append(f"{rel}:{lineno} {kind} (in {scope})")
    assert not offenders, (
        "audit_log-Zeilen duerfen nur ueber services.audit.log() entstehen "
        "(sequence/previous_hash/integrity_hash/tenant_id), gefunden:\n  "
        + "\n  ".join(offenders)
    )


def test_allowlist_entries_are_still_present():
    """Jede Ausnahme muss genau an ihrer Stelle noch vorkommen -- eine
    verwaiste Ausnahme waere eine stille Erweiterung des Erlaubten."""
    found = set()
    for rel, scope, kind in _ALLOWED:
        source = (BACKEND_ROOT / rel).read_text(encoding="utf-8")
        if any(k == kind and s == scope for _, k, s in find_audit_log_writers(source)):
            found.add((rel, scope, kind))
    assert found == _ALLOWED


def test_audit_service_itself_is_seen_by_the_scan():
    """Gegenkontrolle: der Scan erfasst die relevanten Dateien wirklich (sonst
    bewiese der leere Befund oben nichts)."""
    assert BACKEND_ROOT / "services" / "audit.py" in _production_files()
    assert BACKEND_ROOT / "routers" / "system.py" in _production_files()
    assert BACKEND_ROOT / "database.py" in _production_files()


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
