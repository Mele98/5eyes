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
from main import app  # noqa: F401  register all models
from models.clients import Client
from models.mandates import Mandate
from models.tenant import Tenant
from models.users import User
from routers.auth import create_user
from routers.mandates import create_mandate
from schemas.mandates import MandateCreate
from schemas.users import UserCreate


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tenant_quota.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _tenant(
    tenant_id: str,
    *,
    max_users: int | None = 10,
    max_mandates: int | None = None,
) -> Tenant:
    return Tenant(
        id=tenant_id,
        display_name=f"Tenant {tenant_id}",
        slug=tenant_id.lower(),
        hosting_tier="tier2",
        license_status="active",
        max_users=max_users,
        max_mandates=max_mandates,
        is_active=1,
        created_at=_now(),
        updated_at=_now(),
    )


def _admin(uid: str, tenant_id: str) -> User:
    return User(
        id=uid,
        username=uid,
        password_hash="h",
        full_name=uid,
        role="admin",
        is_active=1,
        tenant_id=tenant_id,
        created_at=_now(),
        updated_at=_now(),
    )


def _client(cid: str, advisor_id: str, tenant_id: str) -> Client:
    return Client(
        id=cid,
        client_number=cid,
        first_name=cid,
        last_name="Client",
        advisor_id=advisor_id,
        tenant_id=tenant_id,
        household_type="Einzelperson",
        client_classification="Privatkunde",
        country_of_residence="CH",
        language="DE",
        created_at=_now(),
        updated_at=_now(),
    )


def _user_body(username: str) -> UserCreate:
    return UserCreate(
        username=username,
        password="pw1234567890",
        full_name=f"User {username}",
        role="advisor",
    )


def test_user_under_quota_can_be_created(session_factory):
    with session_factory() as db:
        tenant = _tenant("firm-A", max_users=2)
        admin = _admin("admin-a", "firm-A")
        db.add_all([tenant, admin])
        db.commit()

        user = create_user(_user_body("employee-a"), db=db, current_user=admin)

        assert user.tenant_id == "firm-A"
        assert db.query(User).filter(User.tenant_id == "firm-A").count() == 2


def test_user_at_quota_is_rejected_with_409(session_factory):
    with session_factory() as db:
        tenant = _tenant("firm-A", max_users=1)
        admin = _admin("admin-a", "firm-A")
        db.add_all([tenant, admin])
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_user(_user_body("employee-a"), db=db, current_user=admin)

        assert exc.value.status_code == 409
        assert "max_users" in str(exc.value.detail)


def test_user_quota_is_counted_per_tenant(session_factory):
    with session_factory() as db:
        db.add_all([
            _tenant("firm-A", max_users=2),
            _tenant("firm-B", max_users=1),
            _admin("admin-a", "firm-A"),
            _admin("admin-b", "firm-B"),
            User(
                id="legacy-b",
                username="legacy-b",
                password_hash="h",
                full_name="Legacy B",
                role="advisor",
                is_active=1,
                tenant_id="firm-B",
                created_at=_now(),
                updated_at=_now(),
            ),
        ])
        db.commit()

        user = create_user(_user_body("employee-a"), db=db, current_user=db.get(User, "admin-a"))

        assert user.tenant_id == "firm-A"


def test_zero_user_quota_means_unlimited(session_factory):
    with session_factory() as db:
        tenant = _tenant("firm-A", max_users=0)
        admin = _admin("admin-a", "firm-A")
        db.add_all([tenant, admin])
        db.commit()

        user = create_user(_user_body("employee-a"), db=db, current_user=admin)

        assert user.username == "employee-a"


def test_mandate_at_quota_is_rejected_with_409(session_factory):
    with session_factory() as db:
        tenant = _tenant("firm-A", max_mandates=1)
        admin = _admin("admin-a", "firm-A")
        client = _client("client-a", "admin-a", "firm-A")
        existing = Mandate(
            id="mandate-existing",
            client_id=client.id,
            tenant_id="firm-A",
            mandate_number="M-EXISTING",
            mandate_type="Anlageberatung",
            opened_at=_now(),
            created_at=_now(),
            updated_at=_now(),
        )
        db.add_all([tenant, admin, client, existing])
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_mandate(
                client_id=client.id,
                body=MandateCreate(mandate_number="M-NEW"),
                db=db,
                current_user=admin,
            )

        assert exc.value.status_code == 409
        assert "max_mandates" in str(exc.value.detail)


def test_null_mandate_quota_means_unlimited_and_is_tenant_isolated(session_factory):
    with session_factory() as db:
        db.add_all([
            _tenant("firm-A", max_mandates=None),
            _tenant("firm-B", max_mandates=1),
            _admin("admin-a", "firm-A"),
            _admin("admin-b", "firm-B"),
            _client("client-a", "admin-a", "firm-A"),
            _client("client-b", "admin-b", "firm-B"),
            Mandate(
                id="mandate-b",
                client_id="client-b",
                tenant_id="firm-B",
                mandate_number="M-B",
                mandate_type="Anlageberatung",
                opened_at=_now(),
                created_at=_now(),
                updated_at=_now(),
            ),
        ])
        db.commit()

        mandate = create_mandate(
            client_id="client-a",
            body=MandateCreate(mandate_number="M-A"),
            db=db,
            current_user=db.get(User, "admin-a"),
        )

        assert mandate.tenant_id == "firm-A"
