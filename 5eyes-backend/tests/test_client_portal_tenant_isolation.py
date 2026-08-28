"""E1: Client-Portal Defense-in-depth — eine tenant-uebergreifende ClientLogin-
Linkage darf NICHT zur Datenfreigabe fuehren.

Die 1:1-Verknuepfung (ClientLogin.user_id -> client_id) allein genuegt nicht:
Wenn ein role='client'-User (tenant firm-A) faelschlich/boesartig mit einem
Client aus tenant firm-B verlinkt ist, muss get_linked_client_for_user_or_404
mit 404 abweisen statt fremde Stammdaten zu liefern.
"""
from __future__ import annotations
import datetime
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from main import app  # noqa: F401  (registriert alle Models)
from models.users import User
from models.clients import Client
from models.client_login import ClientLogin
from services.auth import get_linked_client_for_user_or_404
from config import settings


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'portaliso.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _client(cid, tid):
    return Client(
        id=cid, client_number=cid, first_name=cid, last_name="T", advisor_id="adv",
        tenant_id=tid, household_type="Einzelperson", client_classification="Privatkunde",
        country_of_residence="CH", language="DE", created_at=_now(), updated_at=_now(),
    )


def _seed(db, user_tid, client_tid):
    user = User(id="cu", username="cu", password_hash="h", full_name="C", role="client",
                is_active=1, tenant_id=user_tid, created_at=_now(), updated_at=_now())
    db.add_all([
        user,
        _client("c-target", client_tid),
        ClientLogin(id="lnk", user_id="cu", client_id="c-target", is_active=1,
                    created_by="adv", created_at=_now()),
    ])
    db.commit()
    return user


def test_cross_tenant_linkage_blocked(session_factory):
    with session_factory() as db:
        user = _seed(db, user_tid="firm-A", client_tid="firm-B")
        with pytest.raises(HTTPException) as ei:
            get_linked_client_for_user_or_404(user, db)
        assert ei.value.status_code == 404


def test_same_tenant_linkage_ok(session_factory):
    with session_factory() as db:
        user = _seed(db, user_tid="firm-A", client_tid="firm-A")
        client = get_linked_client_for_user_or_404(user, db)
        assert client.id == "c-target"


def test_legacy_null_tenant_linkage_ok_in_bc(session_factory, monkeypatch):
    """BC: beide tenant_id NULL -> kein Mismatch, Zugriff erlaubt (Default-Modus)."""
    monkeypatch.setattr(settings, "strict_tenant_isolation", False)
    with session_factory() as db:
        user = _seed(db, user_tid=None, client_tid=None)
        client = get_linked_client_for_user_or_404(user, db)
        assert client.id == "c-target"


def test_strict_mode_requires_matching_tenant(session_factory, monkeypatch):
    """Strict: User mit tenant_id, Client ohne -> abgewiesen (keine NULL-Bruecke)."""
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    with session_factory() as db:
        user = _seed(db, user_tid="firm-A", client_tid=None)
        with pytest.raises(HTTPException) as ei:
            get_linked_client_for_user_or_404(user, db)
        assert ei.value.status_code == 404


def test_strict_mode_user_ohne_tenant_id_blockiert_fremden_client(session_factory, monkeypatch):
    """TEN-COMP-001 (Codex-Audit 2026-08-27): der urspruengliche Bug --
    ein Client-Portal-User OHNE tenant_id (leer/NULL) umging im Strict-Modus
    die Trennung komplett, weil der Check nur bei WAHRER User-tenant_id
    griff. Muss jetzt genauso fail-closed sein wie ein User MIT tenant_id."""
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    with session_factory() as db:
        user = _seed(db, user_tid=None, client_tid="firm-B")
        with pytest.raises(HTTPException) as ei:
            get_linked_client_for_user_or_404(user, db)
        assert ei.value.status_code == 404


def test_strict_mode_both_null_tenant_still_blocked(session_factory, monkeypatch):
    """Strict-Modus: 'NULL unsichtbar' gilt konsistent -- auch wenn BEIDE
    Seiten (User und Client) tenant_id=NULL haben, gibt es im Strict-Modus
    keine legitime NULL-Tenant-Entitaet (anders als im Default-BC-Modus,
    siehe test_legacy_null_tenant_linkage_ok_in_bc)."""
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    with session_factory() as db:
        user = _seed(db, user_tid=None, client_tid=None)
        with pytest.raises(HTTPException) as ei:
            get_linked_client_for_user_or_404(user, db)
        assert ei.value.status_code == 404
