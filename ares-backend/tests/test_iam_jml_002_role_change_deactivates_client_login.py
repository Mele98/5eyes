"""IAM-JML-002 (B2B-Trust-Audit Runde 2, 2026-10-05): routers/auth.py::update_user
changed a user's role (e.g. client -> advisor) and revoked their sessions, but
never deactivated an existing ClientLogin linkage. A promoted ex-client user
therefore kept a standing, is_active=1, 1:1 ClientLogin row pointing at their
former client record -- even though services/auth.py::get_linked_client_for_user_or_404
and routers/clients.py::create_client_login's own duplicate-guard both treat
"ClientLogin.is_active == 1" as the live-linkage signal, and routers/tenants.py's
tenant-reassignment path already independently guards against exactly this
state (an active ClientLogin blocks a tenant move with 409) -- proving the
project itself already treats "role changed away from client while an active
ClientLogin survives" as an invariant that must not happen, just not on this
code path.

See docs/audits/2026-10-05-b2b-iam-lifecycle-privileged-access-audit.md.
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
from main import app
from models.clients import Client
from models.client_login import ClientLogin
from models.users import User
from services.auth import get_current_user, hash_password


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'iam_jml_002.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(session_factory):
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_admin_and_client_login(SF):
    """Seeds an admin (acting user) plus a real client+client-user+ClientLogin
    linkage, exactly as routers/clients.py::create_client_login would produce
    it, so the test exercises the real invariant the project already
    maintains elsewhere (routers/tenants.py)."""
    now = _now()
    with SF() as s:
        admin = User(
            id="jml002-admin", username="jml002-admin", password_hash=hash_password("x"),
            full_name="Admin", role="admin", is_active=1,
            created_at=now, updated_at=now,
        )
        s.add(admin)

        real_client = Client(
            id="jml002-client-rec", client_number="C-JML-002",
            first_name="Kundin", last_name="Test",
            country_of_residence="CH",
            advisor_id="jml002-admin",
            created_at=now, updated_at=now,
        )
        s.add(real_client)

        client_user = User(
            id="jml002-client-user", username="jml002-client-user",
            password_hash=hash_password("x"), full_name="Kundin Test",
            role="client", is_active=1,
            created_at=now, updated_at=now,
        )
        s.add(client_user)
        s.flush()

        link = ClientLogin(
            id="jml002-link", user_id=client_user.id, client_id=real_client.id,
            created_by="jml002-admin", created_at=now, is_active=1,
        )
        s.add(link)
        s.commit()
    return admin


def test_promoting_client_user_to_advisor_deactivates_stale_client_login(client, session_factory):
    """A real exploit/data-hygiene path: an admin promotes a former client-
    portal user to 'advisor' via the generic PUT /users/{id} endpoint. The
    user's role changes and their sessions are revoked (existing, correct
    behavior) -- but the ClientLogin row linking them to their former client
    record must ALSO be deactivated, exactly like routers/tenants.py already
    requires before a tenant reassignment is allowed."""
    admin = _seed_admin_and_client_login(session_factory)
    app.dependency_overrides[get_current_user] = lambda: admin

    resp = client.put(
        "/users/jml002-client-user",
        json={"role": "advisor"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "advisor"

    with session_factory() as s:
        link = s.query(ClientLogin).filter(ClientLogin.user_id == "jml002-client-user").one()
        assert link.is_active == 0, (
            "ClientLogin stayed active (is_active=1) after the linked user's "
            "role was changed away from 'client' -- the stale 1:1 client "
            "linkage survives the promotion, contradicting the same "
            "invariant routers/tenants.py already enforces before a tenant "
            "reassignment"
        )


def test_positive_control_role_change_away_from_non_client_role_is_unaffected(client, session_factory):
    """Positive control: changing an advisor's role (no ClientLogin involved
    at all) must keep working exactly as before -- this fix must not touch
    users who never had a client linkage."""
    now = _now()
    with session_factory() as s:
        admin = User(
            id="jml002-admin2", username="jml002-admin2", password_hash=hash_password("x"),
            full_name="Admin2", role="admin", is_active=1,
            created_at=now, updated_at=now,
        )
        advisor = User(
            id="jml002-advisor-plain", username="jml002-advisor-plain",
            password_hash=hash_password("x"), full_name="Plain Advisor",
            role="advisor", is_active=1,
            created_at=now, updated_at=now,
        )
        s.add(admin)
        s.add(advisor)
        s.commit()

    app.dependency_overrides[get_current_user] = lambda: admin

    resp = client.put(
        "/users/jml002-advisor-plain",
        json={"role": "portfolio_management"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "portfolio_management"
