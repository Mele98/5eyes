"""C-890-01 N-897-15: jede im Backend protokollierte Audit-Aktion ist im
``audit_log.action``-CHECK erlaubt -- im Rohschema (``ares_schema.sql``), im
SQLite-Neuaufbau (``database._AUDIT_LOG_REBUILT_DDL``) und im PostgreSQL-CHECK
der Alembic-Kette. Anlass: ``POST /users/{id}/compromise`` lieferte auf einer
echten Installation 500 (CHECK kannte 'COMPROMISE' nicht); ``create_all``-
Tests sehen keine CHECKs. Deshalb zusaetzlich ein Lauf auf einer DB aus
``init_db`` (echter Startpfad).
"""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_LOG_FUNCS = {"log", "audit_log", "_audit_log"}


def _call_name(node: ast.Call) -> str:
    func = node.func
    return func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else "")


def _strings(node: ast.AST) -> set[str]:
    return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def backend_audit_actions() -> dict[str, set[str]]:
    """Alle Audit-Aktionen: Literale in ``log(..., action=...)`` sowie die
    Literale, die einer als ``action=`` weitergereichten Variablen in derselben
    Funktion zugewiesen werden."""
    found: dict[str, set[str]] = {}
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.startswith(("tests/", "alembic/", "scripts/", "migrations/", "venv/", ".venv/")):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(func):
                if not (isinstance(call, ast.Call) and _call_name(call) in _LOG_FUNCS):
                    continue
                for kw in call.keywords:
                    if kw.arg != "action":
                        continue
                    if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        found.setdefault(kw.value.value, set()).add(rel)
                    elif isinstance(kw.value, ast.Name):
                        for assign in ast.walk(func):
                            if isinstance(assign, ast.Assign) and any(
                                    isinstance(t, ast.Name) and t.id == kw.value.id for t in assign.targets):
                                for value in _strings(assign.value):
                                    if re.fullmatch(r"[A-Za-z0-9_]+", value) and value.upper() == value:
                                        found.setdefault(value, set()).add(rel)
    return found


def _check_list(sql: str) -> set[str]:
    # SQL-Kommentare entfernen: ein Kommentar wie "-- 'COMPROMISE' (...)" darf
    # einen fehlenden CHECK-Eintrag nicht verdecken (Mutationsbefund).
    sql = re.sub(r"--[^\n]*", "", sql)
    block = sql[sql.index("action") :]
    block = block[block.index("CHECK(action IN (") : block.index("))")]
    return set(re.findall(r"'([A-Za-z0-9_]+)'", block))


def schema_actions() -> set[str]:
    sql = (BACKEND / "ares_schema.sql").read_text(encoding="utf-8")
    table = sql[sql.index("CREATE TABLE IF NOT EXISTS audit_log"):]
    return _check_list(table)


def rebuilt_actions() -> set[str]:
    import database

    return _check_list(database._AUDIT_LOG_REBUILT_DDL)


def postgres_actions() -> set[str]:
    path = BACKEND / "alembic" / "versions" / "d66fbf0588e3_reviewer_provenance_and_kyc_decisions.py"
    spec = importlib.util.spec_from_file_location("c890_rev", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return set(module.AUDIT_ACTIONS)


def test_every_backend_audit_action_is_allowed_everywhere():
    used = backend_audit_actions()
    assert {"COMPROMISE", "INVITE", "INVITE_ACCEPT", "2FA_ENABLE", "CREATE", "UPDATE", "INSERT"} <= set(used)
    for name, allowed in (("ares_schema.sql", schema_actions()), ("database._AUDIT_LOG_REBUILT_DDL", rebuilt_actions()),
                          ("PostgreSQL ck_audit_log_action_allowed", postgres_actions())):
        missing = {a: sorted(files) for a, files in used.items() if a not in allowed}
        assert missing == {}, f"{name}: {missing}"


def test_the_three_check_lists_are_identical():
    assert schema_actions() == rebuilt_actions() == postgres_actions()


def test_comment_mentioning_an_action_does_not_count_as_allowed():
    ddl = "CREATE TABLE audit_log (action TEXT CHECK(action IN (\n 'CREATE','UPDATE'\n -- 'COMPROMISE' fehlt absichtlich\n)))"
    assert _check_list(ddl) == {"CREATE", "UPDATE"}


def test_negative_control_detects_a_missing_action(tmp_path):
    """Ein neues log(action=...) ohne CHECK-Eintrag faellt auf."""
    tree = ast.parse('def f(db):\n    log(db, action="TOTALLY_NEW")\n')
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    assert _call_name(call) == "log" and call.keywords[0].value.value not in schema_actions()


@pytest.fixture()
def real_install(tmp_path, monkeypatch):
    """DB aus dem echten Startpfad (init_db: Rohschema + create_all + Runtime-Patch)."""
    import database as db_module

    engine = create_engine(f"sqlite:///{tmp_path / 'real_install.db'}", connect_args={"check_same_thread": False})
    db_module.init_db(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    try:
        yield factory
    finally:
        engine.dispose()


def test_every_action_is_insertable_on_a_real_install(real_install):
    from services.audit import log

    with real_install() as db:
        for action in sorted(backend_audit_actions()):
            log(db, user_id="system", user_name="Test", table_name="users", record_id="r1", action=action)
        db.commit()
        stored = {r[0] for r in db.execute(text("SELECT DISTINCT action FROM audit_log"))}
    assert set(backend_audit_actions()) <= stored


def test_compromise_route_works_on_a_real_install(real_install):
    from fastapi.testclient import TestClient

    from database import get_db
    from main import app
    from models.tenant import Tenant
    from models.users import User
    from services.auth import create_access_token, hash_password

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    with real_install() as db:
        if db.get(Tenant, "t-real") is None:
            db.add(Tenant(id="t-real", display_name="Real", slug="t-real", max_users=10, created_at=now, updated_at=now))
        for uid, role in (("adm-real", "admin"), ("rev-real", "compliance_reviewer")):
            db.add(User(id=uid, username=uid, password_hash=hash_password("Testpasswort-C890-1"), full_name=uid,
                        role=role, is_active=1, tenant_id="t-real", created_at=now, updated_at=now,
                        activated_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
                        if role == "compliance_reviewer" else None))
        db.commit()

    def override_db():
        with real_install() as s:
            yield s

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer " + create_access_token({"sub": "adm-real", "tid": "t-real"})}
            since = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
            r = client.post("/users/rev-real/compromise", headers=headers,
                            json={"reason": "Verdacht auf Missbrauch (Test real)", "compromised_since": since})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    with real_install() as db:
        assert db.execute(text("SELECT COUNT(*) FROM audit_log WHERE action = 'COMPROMISE'")).scalar() == 1
