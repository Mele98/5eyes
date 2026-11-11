"""H10 (DSG-Technikaudit 2026-11-11): gemeinsame Test-Hilfen.

API-Harness auf einer frischen SQLite-Datei. Anders als der PRIVACY-001-
Harness werden ``require_admin``/``require_advisor`` NICHT ueberschrieben:
nur ``get_current_user``. Damit greifen die echten Rollenpruefungen (RBAC).

Alle Owner-Werte in diesen Tests sind klar markierte Testwerte
(``TESTWERT ...``), keine fachlichen Vorgaben.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database import Base, get_db
from main import app
from models.clients import Client
from models.users import User
from services.auth import get_current_user
from tests.test_endpoint_query_budgets import _ADMIN_ID, _CLIENT_ID, _MANDATE_ID, _NOW, _seed_base

TENANT = "main"
OTHER_TENANT = "t-b"
ADMIN_ID = _ADMIN_ID
CLIENT_ID = _CLIENT_ID
MANDATE_ID = _MANDATE_ID
OTHER_CLIENT_ID = "h10-client-b"


def user(uid: str, *, tenant: str = TENANT, role: str = "admin") -> User:
    return User(id=uid, username=uid, password_hash="h", full_name=uid, role=role, tenant_id=tenant,
                is_active=1, created_at=_NOW, updated_at=_NOW)


def sample_value(key: str) -> str:
    return f"TESTWERT {key}"


@contextmanager
def api(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'h10.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    with factory() as s:
        _seed_base(s)
        for uid, role in (("advisor-1", "advisor"), ("priv-1", "admin"), ("admin-2", "admin")):
            s.add(user(uid, role=role))
        s.add(user("admin-b", tenant=OTHER_TENANT))
        s.commit()
        for table in ("users", "clients", "mandates"):
            s.execute(text(f"UPDATE {table} SET tenant_id = :t WHERE tenant_id IS NULL"), {"t": TENANT})
        s.add(Client(id=OTHER_CLIENT_ID, client_number="B-1", first_name="Fremd", last_name="Kunde",
                     date_of_birth="1980-01-01", advisor_id="admin-b", country_of_residence="CH",
                     tenant_id=OTHER_TENANT, created_at=_NOW, updated_at=_NOW))
        s.commit()

    def override_get_db():
        with factory() as session:
            yield session

    current = {"user": user(ADMIN_ID)}
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    try:
        yield TestClient(app), current, factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def confirm_all_owner_fields(client: TestClient, *, only_blocking: bool = False) -> None:
    for field in client.get("/privacy/owner-fields").json():
        if only_blocking and field["blocking"] == "informational":
            continue
        value = "24" if field["kind"] == "hours" else sample_value(field["key"])
        response = client.put(f"/privacy/owner-fields/{field['key']}", json={"value": value})
        assert response.status_code == 200, response.text


def reason(response) -> str:
    detail = response.json().get("detail")
    if isinstance(detail, dict):
        return detail.get("reason_code") or detail.get("code") or ""
    return ""


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def alembic_cfg(db_url: str):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def assert_single_head_contains(revision: str, down_revision: str) -> None:
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert revision in chain
    assert script.get_revision(revision).down_revision == down_revision


def assert_sqlite_upgrade_downgrade_upgrade(tmp_path: Path, revision: str, models: dict) -> None:
    """Upgrade bis ``revision`` (Spalten = ORM), Downgrade um eins (Tabellen
    weg), erneutes Upgrade (Tabellen wieder da)."""
    from alembic import command
    from sqlalchemy import inspect

    db_path = tmp_path / "alembic.db"
    cfg = alembic_cfg(f"sqlite:///{db_path}")

    def tables_now() -> dict[str, set[str]]:
        engine = create_engine(f"sqlite:///{db_path}")
        try:
            inspector = inspect(engine)
            names = set(inspector.get_table_names())
            return {t: {c["name"] for c in inspector.get_columns(t)} for t in models if t in names}
        finally:
            engine.dispose()

    expected = {t: {c.name for c in m.__table__.columns} for t, m in models.items()}
    command.upgrade(cfg, revision)
    assert tables_now() == expected
    command.downgrade(cfg, f"{revision}-1")
    assert tables_now() == {}
    command.upgrade(cfg, revision)
    assert tables_now() == expected


def postgres_offline_ddl(down_revision: str, revision: str) -> str:
    import io

    from alembic import command

    buffer = io.StringIO()
    cfg = alembic_cfg("postgresql://u:p@localhost/db")
    cfg.output_buffer = buffer
    command.upgrade(cfg, f"{down_revision}:{revision}", sql=True)
    return buffer.getvalue()
