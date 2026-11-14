"""RC-CH-1 Teil 2b (Integration E2 x H7 N-884-09): Audit-Callbacks der
Freigabe-Gates stellen den Tenant-Kontext nach dem Rollback wieder her.

``services.audit.gate_block_audit`` (E2: Untergrenze/Erfassung/Nachweis der
Nachhaltigkeitspraeferenz in Kunden-PDF, Finalisierung, Signatur, Vor-Ort,
Handoff, manueller Allokation) verwirft offene Aenderungen per Rollback und
schreibt danach den Audit-Eintrag -- dasselbe Muster wie
``release_block_audit`` (H7). Unter PostgreSQL macht der Rollback den Tenant-
Kontext rueckgaengig; ohne Wiederherstellung scheitert der Insert an RLS
(Live-Beleg: test_postgres_gate_block_audit_rls_live.py).

Hier ohne Datenbank:
- Waechter: JEDER Aufruf von gate_block_audit/release_block_audit im
  Produktcode uebergibt ``set_tenant_context`` (sonst rot, mit Fundstelle).
- Verhalten: der Callback setzt den Kontext NACH dem Rollback und VOR dem
  Audit-Insert, mit dem Tenant der Session.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
CALLBACKS = {"gate_block_audit", "release_block_audit"}
EXCLUDED = {"tests", "alembic", "scripts", "migrations", ".venv", "venv", "node_modules", "__pycache__"}


def _calls_without_tenant_restore(root: Path = BACKEND) -> list[str]:
    bad = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if any(part in EXCLUDED for part in rel.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in CALLBACKS:
                continue
            kw = {k.arg: k.value for k in node.keywords}
            value = kw.get("set_tenant_context")
            if value is None or (isinstance(value, ast.Constant) and value.value is None):
                bad.append(f"{rel.as_posix()}:{node.lineno} {name}")
    return bad


def test_every_gate_audit_callback_restores_the_tenant_context():
    bad = _calls_without_tenant_restore()
    assert bad == [], "Audit-Callback ohne set_tenant_context (RLS nach Rollback):\n" + "\n".join(bad)


def test_guard_detects_a_call_without_restore(tmp_path):
    (tmp_path / "routers").mkdir()
    (tmp_path / "routers" / "x.py").write_text(
        "def f(db, u, m):\n"
        "    return gate_block_audit(db, user=u, mandate=m, ip_address=None,\n"
        "                            table_name='t', field_name='f')\n",
        encoding="utf-8",
    )
    assert _calls_without_tenant_restore(tmp_path) == ["routers/x.py:2 gate_block_audit"]


class _Session:
    def __init__(self, tenant_id):
        self.info = {"tenant_id": tenant_id}
        self.events = []

    def rollback(self):
        self.events.append("rollback")

    def commit(self):
        self.events.append("commit")


def test_gate_block_audit_sets_tenant_after_rollback_before_insert(monkeypatch):
    import services.audit as audit

    session = _Session("tenant-x")

    def fake_log(db, **kwargs):
        db.events.append(("log", kwargs["field_name"], kwargs["new_value"]))

    monkeypatch.setattr(audit, "log", fake_log)
    callback = audit.gate_block_audit(
        session, user=SimpleNamespace(id="u1", full_name="Berater"),
        mandate=SimpleNamespace(id="m1", client_id="c1"), ip_address=None,
        table_name="investment_preference_decisions", field_name="sustainability_floor_blocked",
        set_tenant_context=lambda db, tid: db.events.append(("tenant", tid)),
    )
    callback('{"x":1}', {"decision_id": "d1"})
    assert session.events == [
        "rollback",
        ("tenant", "tenant-x"),
        ("log", "sustainability_floor_blocked", '{"x":1}'),
        "commit",
    ]
