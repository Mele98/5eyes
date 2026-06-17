"""E1 (External-Access-Rollout): tenant_id-Backfill NULL -> 'main'.

Sichert, dass Bestands-Rows ohne tenant_id dem Default-Tenant zugewiesen werden,
fremde tenant_id unangetastet bleiben, und der Lauf idempotent ist.
"""
from __future__ import annotations
import sys
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, ensure_tenant_backfill
from main import app  # noqa: F401  (registriert ALLE Models/Tabellen + FK-Ziele)
from models.clients import Client
from models.tenant import DEFAULT_TENANT_ID


def _engine(tmp_path):
    eng = create_engine(
        f"sqlite:///{tmp_path / 'test_backfill.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=eng)
    return eng


def _add_client(SF, cid, tenant_id):
    with SF() as s:
        s.add(Client(
            id=cid, client_number="BF-" + cid, first_name="T", last_name="X",
            advisor_id="adv-1", tenant_id=tenant_id,
            created_at="2026-06-12T00:00:00.000Z", updated_at="2026-06-12T00:00:00.000Z",
        ))
        s.commit()


def test_backfill_assigns_main_to_null_rows(tmp_path):
    eng = _engine(tmp_path)
    SF = sessionmaker(bind=eng, expire_on_commit=False)
    _add_client(SF, "null-client", None)
    _add_client(SF, "firma-a-client", "firma-a")

    ensure_tenant_backfill(eng)

    with eng.connect() as c:
        rows = dict(c.execute(text("SELECT id, tenant_id FROM clients")).fetchall())
    assert rows["null-client"] == DEFAULT_TENANT_ID
    # Fremder Tenant bleibt unangetastet.
    assert rows["firma-a-client"] == "firma-a"


def test_backfill_is_idempotent(tmp_path):
    eng = _engine(tmp_path)
    SF = sessionmaker(bind=eng, expire_on_commit=False)
    _add_client(SF, "null-client", None)
    ensure_tenant_backfill(eng)
    # Zweiter Lauf trifft 0 NULL-Rows, darf nicht fehlschlagen.
    ensure_tenant_backfill(eng)
    with eng.connect() as c:
        tid = c.execute(text("SELECT tenant_id FROM clients WHERE id='null-client'")).scalar()
    assert tid == DEFAULT_TENANT_ID


def test_backfill_tolerates_missing_table(tmp_path):
    # Leere DB ohne create_all der Datentabellen -> darf nicht crashen.
    eng = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    ensure_tenant_backfill(eng)  # keine Exception
