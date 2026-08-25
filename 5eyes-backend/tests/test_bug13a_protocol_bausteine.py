"""Bug-#13a (2026-06-07): Backend-Tests fuer Beratungsprotokoll-Baustein-CRUD.

Deckt Bibliotheks-CRUD + Mandate-Selektions-Replace ab. Frontend
(Library-Verwaltung + Auswahl-Modal) folgt in separater PR.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
import models.allocation  # noqa: F401
import models.clients  # noqa: F401
import models.client_login  # noqa: F401
import models.fx_rate  # noqa: F401
import models.mandates  # noqa: F401
import models.profiling  # noqa: F401
import models.protocol_bausteine  # noqa: F401
import models.review  # noqa: F401
import models.snapshots  # noqa: F401
import models.tenant  # noqa: F401
import models.users  # noqa: F401
import models.wealth  # noqa: F401

from main import app
from models.clients import Client
from models.mandates import Mandate
from models.protocol_bausteine import (
    MandateBausteinSelection,
    ProtocolBaustein,
)
from models.review import AuditLog
from models.users import User
from services.auth import get_current_user


def _utc_now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'bug13a.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="advisor-1",
        username="advisor-1",
        password_hash="h",
        full_name="Advisor One",
        role="advisor",
        is_active=1,
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )


@pytest.fixture()
def other_advisor_user():
    return User(
        id="advisor-2",
        username="advisor-2",
        password_hash="h",
        full_name="Advisor Two",
        role="advisor",
        is_active=1,
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )


@pytest.fixture()
def admin_user():
    return User(
        id="admin-1",
        username="admin-1",
        password_hash="h",
        full_name="Admin",
        role="admin",
        is_active=1,
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )


def _client_for(session_factory, user):
    def override_db():
        with session_factory() as session:
            yield session
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


# ---------------------------------------------------------------------------
# Bibliotheks-CRUD
# ---------------------------------------------------------------------------


def test_baustein_anlegen_als_advisor(session_factory, advisor_user):
    with _client_for(session_factory, advisor_user) as c:
        resp = c.post(
            "/protocol-bausteine",
            json={
                "title": "Risikoaufklaerung Standard",
                "content_md": "## Risiko\nText",
                "category": "Risikoaufklaerung",
                "sort_order": 10,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["title"] == "Risikoaufklaerung Standard"
        assert body["advisor_id"] == advisor_user.id
        assert body["is_active"] == 1
    app.dependency_overrides.clear()


def test_baustein_liste_zeigt_eigene_plus_global(session_factory, advisor_user, other_advisor_user):
    # Baustein von advisor-2 + ein globaler Baustein (advisor_id=None)
    with session_factory() as db:
        db.add(advisor_user)
        db.add(other_advisor_user)
        db.add(ProtocolBaustein(
            id="b-other", advisor_id="advisor-2", title="Andere", content_md="",
            sort_order=0, is_active=1, created_at=_utc_now(), updated_at=_utc_now(),
        ))
        db.add(ProtocolBaustein(
            id="b-global", advisor_id=None, title="Global", content_md="",
            sort_order=0, is_active=1, created_at=_utc_now(), updated_at=_utc_now(),
        ))
        db.add(ProtocolBaustein(
            id="b-mine", advisor_id="advisor-1", title="Meiner", content_md="",
            sort_order=0, is_active=1, created_at=_utc_now(), updated_at=_utc_now(),
        ))
        db.commit()

    with _client_for(session_factory, advisor_user) as c:
        resp = c.get("/protocol-bausteine")
        assert resp.status_code == 200
        titles = [b["title"] for b in resp.json()]
        assert "Meiner" in titles
        assert "Global" in titles
        assert "Andere" not in titles  # Cross-Advisor-Leak verhindert
    app.dependency_overrides.clear()


def test_baustein_update_fremder_eintrag_403(session_factory, advisor_user, other_advisor_user):
    with session_factory() as db:
        db.add(advisor_user)
        db.add(other_advisor_user)
        db.add(ProtocolBaustein(
            id="b-other", advisor_id="advisor-2", title="Andere", content_md="",
            sort_order=0, is_active=1, created_at=_utc_now(), updated_at=_utc_now(),
        ))
        db.commit()
    with _client_for(session_factory, advisor_user) as c:
        resp = c.put("/protocol-bausteine/b-other", json={"title": "Hijacked"})
        assert resp.status_code == 403
    app.dependency_overrides.clear()


def test_baustein_update_eigener_eintrag_funktioniert(session_factory, advisor_user):
    with session_factory() as db:
        db.add(advisor_user)
        db.add(ProtocolBaustein(
            id="b-mine", advisor_id="advisor-1", title="Original",
            content_md="alter Text", sort_order=0, is_active=1,
            created_at=_utc_now(), updated_at=_utc_now(),
        ))
        db.commit()
    with _client_for(session_factory, advisor_user) as c:
        resp = c.put(
            "/protocol-bausteine/b-mine",
            json={"title": "Neu", "content_md": "neuer Text"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Neu"
    app.dependency_overrides.clear()


def test_baustein_admin_darf_globalen_editieren(session_factory, admin_user):
    with session_factory() as db:
        db.add(admin_user)
        db.add(ProtocolBaustein(
            id="b-global", advisor_id=None, title="Global",
            content_md="", sort_order=0, is_active=1,
            created_at=_utc_now(), updated_at=_utc_now(),
        ))
        db.commit()
    with _client_for(session_factory, admin_user) as c:
        resp = c.put("/protocol-bausteine/b-global", json={"title": "Global Renamed"})
        assert resp.status_code == 200
    app.dependency_overrides.clear()


def test_baustein_delete_macht_soft_delete(session_factory, advisor_user):
    with session_factory() as db:
        db.add(advisor_user)
        db.add(ProtocolBaustein(
            id="b-1", advisor_id="advisor-1", title="X", content_md="",
            sort_order=0, is_active=1, created_at=_utc_now(), updated_at=_utc_now(),
        ))
        db.commit()
    with _client_for(session_factory, advisor_user) as c:
        resp = c.delete("/protocol-bausteine/b-1")
        assert resp.status_code == 204
    with session_factory() as db:
        row = db.query(ProtocolBaustein).filter(ProtocolBaustein.id == "b-1").first()
        assert row.deleted_at is not None
        assert row.is_active == 0
    app.dependency_overrides.clear()


def test_baustein_audit_log_eintrag(session_factory, advisor_user):
    with _client_for(session_factory, advisor_user) as c:
        c.post("/protocol-bausteine", json={"title": "Audit-Check"})
    with session_factory() as db:
        rows = db.query(AuditLog).filter(
            AuditLog.table_name == "protocol_bausteine",
            AuditLog.action == "CREATE",
        ).all()
        assert len(rows) == 1
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Mandate-Selektion
# ---------------------------------------------------------------------------


def _seed_mandate(session_factory, advisor_user) -> str:
    with session_factory() as db:
        db.add(advisor_user)
        db.add(Client(
            id="cli-1", client_number="C-1", first_name="A", last_name="B",
            country_of_residence="CH", language="DE", household_type="Einzelperson",
            client_classification="Privatkunde", is_professional_opt_out=0,
            is_qualified_investor=0, advisor_id=advisor_user.id,
            created_at=_utc_now(), updated_at=_utc_now(),
        ))
        db.add(Mandate(
            id="mdt-1", client_id="cli-1", mandate_number="M-1",
            mandate_type="Anlageberatung", status="Aktiv", base_currency="CHF",
            advisory_language="DE", opened_at="2026-06-07",
            created_at=_utc_now(), updated_at=_utc_now(),
        ))
        db.commit()
    return "mdt-1"


def test_mandate_selektion_replace_und_list(session_factory, advisor_user):
    mandate_id = _seed_mandate(session_factory, advisor_user)
    with session_factory() as db:
        db.add(ProtocolBaustein(
            id="b-A", advisor_id="advisor-1", title="A", content_md="aa",
            sort_order=0, is_active=1, created_at=_utc_now(), updated_at=_utc_now(),
        ))
        db.add(ProtocolBaustein(
            id="b-B", advisor_id=None, title="B-global", content_md="bb",
            sort_order=0, is_active=1, created_at=_utc_now(), updated_at=_utc_now(),
        ))
        db.commit()

    with _client_for(session_factory, advisor_user) as c:
        resp = c.put(
            f"/mandates/{mandate_id}/protocol-bausteine",
            json={"selections": [
                {"baustein_id": "b-A", "sort_order": 0},
                {"baustein_id": "b-B", "sort_order": 1, "custom_override_md": "Lokal angepasst"},
            ]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body) == 2
        assert body[0]["baustein_id"] == "b-A"
        assert body[1]["custom_override_md"] == "Lokal angepasst"
        # Convenience-Felder gefuellt
        assert body[0]["title"] == "A"
        assert body[1]["title"] == "B-global"

        # Erneutes PUT replact (Idempotenz mit weniger Items)
        resp2 = c.put(
            f"/mandates/{mandate_id}/protocol-bausteine",
            json={"selections": [{"baustein_id": "b-A", "sort_order": 0}]},
        )
        assert resp2.status_code == 200
        assert len(resp2.json()) == 1
    app.dependency_overrides.clear()


def test_mandate_selektion_blockt_fremden_baustein(session_factory, advisor_user, other_advisor_user):
    mandate_id = _seed_mandate(session_factory, advisor_user)
    with session_factory() as db:
        db.add(other_advisor_user)
        db.add(ProtocolBaustein(
            id="b-other", advisor_id="advisor-2", title="Fremd", content_md="",
            sort_order=0, is_active=1, created_at=_utc_now(), updated_at=_utc_now(),
        ))
        db.commit()
    with _client_for(session_factory, advisor_user) as c:
        resp = c.put(
            f"/mandates/{mandate_id}/protocol-bausteine",
            json={"selections": [{"baustein_id": "b-other"}]},
        )
        assert resp.status_code == 403
    app.dependency_overrides.clear()


def test_mandate_selektion_400_bei_unbekannter_id(session_factory, advisor_user):
    mandate_id = _seed_mandate(session_factory, advisor_user)
    with _client_for(session_factory, advisor_user) as c:
        resp = c.put(
            f"/mandates/{mandate_id}/protocol-bausteine",
            json={"selections": [{"baustein_id": "nope"}]},
        )
        assert resp.status_code == 400
    app.dependency_overrides.clear()
