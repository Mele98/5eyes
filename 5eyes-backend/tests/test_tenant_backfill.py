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


# ── 2026-07-25 (Generalaudit): in tenancy_mode="multi" (Tier 2, mehrere echte
# Firmen) ist die pauschale 'main'-Zuweisung fachlich FALSCH fuer eine Zeile,
# die eigentlich zu einer anderen Firma gehoert -- Bruch der Mandantentrennung
# durch die Migration selbst. NULL muss NULL bleiben (bereits bekanntes,
# dokumentiertes Verhalten der Isolation-Klausel), statt falsch gelabelt zu werden.

def test_backfill_skips_blanket_main_assignment_in_multi_tenant_mode(tmp_path, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "tenancy_mode", "multi", raising=False)

    eng = _engine(tmp_path)
    SF = sessionmaker(bind=eng, expire_on_commit=False)
    _add_client(SF, "null-client-multi", None)
    _add_client(SF, "firma-a-client-multi", "firma-a")

    ensure_tenant_backfill(eng)

    with eng.connect() as c:
        rows = dict(c.execute(text("SELECT id, tenant_id FROM clients")).fetchall())
    # NULL bleibt NULL -- wird NICHT faelschlich 'main' zugewiesen.
    assert rows["null-client-multi"] is None
    assert rows["firma-a-client-multi"] == "firma-a"


def test_backfill_still_assigns_main_in_single_tenant_mode(tmp_path, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "tenancy_mode", "single", raising=False)

    eng = _engine(tmp_path)
    SF = sessionmaker(bind=eng, expire_on_commit=False)
    _add_client(SF, "null-client-single", None)

    ensure_tenant_backfill(eng)

    with eng.connect() as c:
        tid = c.execute(text("SELECT tenant_id FROM clients WHERE id='null-client-single'")).scalar()
    assert tid == DEFAULT_TENANT_ID
