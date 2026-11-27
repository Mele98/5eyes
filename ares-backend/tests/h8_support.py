"""H8: gemeinsame Testbasis (Mandant, Benutzer, Kunde, Mandat) fuer die
H8-Testdateien test_h8_c2_*/c5_*/l7_*/l10_*."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from models import (  # noqa: E402,F401 -- registriert alle Mapper
    allocation, client_login, clients, mandates, profiling, protocol_bausteine,
    refresh_token, review, snapshots, tenant, users, wealth,
)
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.users import User  # noqa: E402
from services import recommendation_release_gate as gate  # noqa: E402

NOW = "2026-11-07T09:00:00.000Z"
TENANT = "t-h8"


class Req:
    headers: dict = {}
    client = None


@pytest.fixture()
def sf(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'h8.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    with factory() as db:
        db.add(Tenant(id=TENANT, display_name="Tenant H8", slug="t-h8", created_at=NOW, updated_at=NOW))
        for uid, role in (("adv-1", "advisor"), ("adm-1", "admin"), ("adm-2", "admin")):
            db.add(User(id=uid, username=uid, password_hash="x", full_name=uid.upper(), role=role,
                        is_active=1, tenant_id=TENANT, created_at=NOW, updated_at=NOW))
        db.add(Client(id="c-1", tenant_id=TENANT, client_number="K-1", first_name="Eva", last_name="Muster",
                      advisor_id="adv-1", created_at=NOW, updated_at=NOW))
        db.add(Mandate(id="m-1", tenant_id=TENANT, client_id="c-1", mandate_number="M-1",
                       mandate_type="Anlageberatung", opened_at=NOW, created_at=NOW, updated_at=NOW))
        db.commit()
    try:
        yield factory
    finally:
        engine.dispose()


def user(db, uid):
    return db.query(User).filter(User.id == uid).first()


def mandate(db):
    return db.query(Mandate).filter(Mandate.id == "m-1").first()


def codes(db):
    return [f["reason_code"] for f in gate.client_onboarding_findings(db, mandate(db))]


def alembic_cfg(url: str, buffer=None):
    from alembic.config import Config

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"), output_buffer=buffer)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def h8_postgres_ddl() -> str:
    import io

    from alembic import command

    up = io.StringIO()
    command.upgrade(alembic_cfg("postgresql://u:p@localhost/db", up), "e1c6a7d4b2f9:d8e4b2a6c1f9", sql=True)
    return up.getvalue()
