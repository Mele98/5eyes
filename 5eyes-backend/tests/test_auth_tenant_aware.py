"""Sprint T2 (2026-06-08): Tenant-Aware JWT-Tests.

Verifiziert:
1. issue_token_for_user setzt tid-Claim
2. _resolve_tenant_id_for_user mit User-tenant_id / ohne / leer
3. get_current_tenant_id extrahiert aus JWT
4. get_current_user Cross-Tenant-Check (Token-Wandering verhindert)
5. Backwards-Compat: Legacy-Token ohne tid akzeptiert mit 'main'-Fallback
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import settings
from database import Base
import models.allocation  # noqa: F401
import models.clients  # noqa: F401
import models.client_login  # noqa: F401
import models.fx_rate  # noqa: F401
import models.mandates  # noqa: F401
import models.profiling  # noqa: F401
import models.review  # noqa: F401
import models.snapshots  # noqa: F401
import models.tenant  # noqa: F401
import models.users  # noqa: F401
import models.wealth  # noqa: F401
from models.tenant import DEFAULT_TENANT_ID
from models.users import User
from services.auth import (
    _resolve_tenant_id_for_user,
    create_access_token,
    get_current_tenant_id,
    get_current_user,
    issue_token_for_user,
    user_tenant_id,
)


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _make_creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tenant_auth.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# ===========================================================================
# 1. _resolve_tenant_id_for_user
# ===========================================================================


def test_resolve_tenant_id_mit_user_tenant_id():
    user = User(
        id="u1", username="u1", password_hash="h", full_name="Test",
        role="advisor", is_active=1,
        created_at=_utc_now_iso(), updated_at=_utc_now_iso(),
        tenant_id="firm-mueller",
    )
    assert _resolve_tenant_id_for_user(user) == "firm-mueller"


def test_resolve_tenant_id_ohne_user_tenant_id_default_main():
    user = User(
        id="u2", username="u2", password_hash="h", full_name="Legacy",
        role="advisor", is_active=1,
        created_at=_utc_now_iso(), updated_at=_utc_now_iso(),
        tenant_id=None,
    )
    assert _resolve_tenant_id_for_user(user) == DEFAULT_TENANT_ID


def test_resolve_tenant_id_leer_string_default_main():
    user = User(
        id="u3", username="u3", password_hash="h", full_name="EmptyTid",
        role="advisor", is_active=1,
        created_at=_utc_now_iso(), updated_at=_utc_now_iso(),
        tenant_id="   ",
    )
    assert _resolve_tenant_id_for_user(user) == DEFAULT_TENANT_ID


def test_user_tenant_id_als_public_api():
    user = User(
        id="u4", username="u4", password_hash="h", full_name="Pub",
        role="advisor", is_active=1,
        created_at=_utc_now_iso(), updated_at=_utc_now_iso(),
        tenant_id="acme-corp",
    )
    assert user_tenant_id(user) == "acme-corp"


# ===========================================================================
# 2. issue_token_for_user setzt tid-Claim
# ===========================================================================


def test_issue_token_enthaelt_tid_claim_main():
    user = User(
        id="u5", username="u5", password_hash="h", full_name="Default",
        role="advisor", is_active=1,
        created_at=_utc_now_iso(), updated_at=_utc_now_iso(),
        tenant_id=None,
    )
    token = issue_token_for_user(user)
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    assert payload["sub"] == "u5"
    assert payload["tid"] == DEFAULT_TENANT_ID


def test_issue_token_enthaelt_tid_claim_specific_tenant():
    user = User(
        id="u6", username="u6", password_hash="h", full_name="Multi-Tenant",
        role="advisor", is_active=1,
        created_at=_utc_now_iso(), updated_at=_utc_now_iso(),
        tenant_id="firm-XYZ",
    )
    token = issue_token_for_user(user)
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    assert payload["tid"] == "firm-XYZ"


# ===========================================================================
# 3. get_current_user Cross-Tenant-Check (Direct-Call)
# ===========================================================================


def test_get_current_user_token_tid_matches_user_tid(session_factory):
    """User mit tenant_id='A' + Token mit tid='A' → OK."""
    with session_factory() as db:
        u = User(
            id="u-match", username="match", password_hash="h", full_name="OK",
            role="advisor", is_active=1,
            created_at=_utc_now_iso(), updated_at=_utc_now_iso(),
            tenant_id="firm-A",
        )
        db.add(u)
        db.commit()
        token = create_access_token({"sub": "u-match", "tid": "firm-A"})
        user = get_current_user(credentials=_make_creds(token), db=db)
        assert user.id == "u-match"


def test_get_current_user_token_tid_mismatch_user_tid_401(session_factory):
    """User tenant_id='A' + Token tid='B' → 401 (Token-Wandering verhindert)."""
    with session_factory() as db:
        u = User(
            id="u-mismatch", username="mismatch", password_hash="h",
            full_name="Bad", role="advisor", is_active=1,
            created_at=_utc_now_iso(), updated_at=_utc_now_iso(),
            tenant_id="firm-A",
        )
        db.add(u)
        db.commit()
        token = create_access_token({"sub": "u-mismatch", "tid": "firm-B"})
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(credentials=_make_creds(token), db=db)
        assert exc_info.value.status_code == 401


def test_get_current_user_legacy_token_ohne_tid_akzeptiert(session_factory):
    """Token OHNE tid-Claim (Legacy) → akzeptiert (Backwards-Compat)."""
    with session_factory() as db:
        u = User(
            id="u-legacy", username="legacy", password_hash="h",
            full_name="Legacy", role="advisor", is_active=1,
            created_at=_utc_now_iso(), updated_at=_utc_now_iso(),
            tenant_id=None,
        )
        db.add(u)
        db.commit()
        token = create_access_token({"sub": "u-legacy"})
        user = get_current_user(credentials=_make_creds(token), db=db)
        assert user.id == "u-legacy"


def test_get_current_user_token_tid_user_no_tid_akzeptiert(session_factory):
    """Token MIT tid + User OHNE tid in DB → akzeptiert (Migration-Pfad)."""
    with session_factory() as db:
        u = User(
            id="u-mig", username="mig", password_hash="h",
            full_name="Mig", role="advisor", is_active=1,
            created_at=_utc_now_iso(), updated_at=_utc_now_iso(),
            tenant_id=None,
        )
        db.add(u)
        db.commit()
        token = create_access_token({"sub": "u-mig", "tid": "firm-Z"})
        user = get_current_user(credentials=_make_creds(token), db=db)
        assert user.id == "u-mig"


# ===========================================================================
# 4. get_current_tenant_id Helper
# ===========================================================================


def test_get_current_tenant_id_aus_jwt_claim():
    token = create_access_token({"sub": "x", "tid": "firm-XYZ"})
    tid = get_current_tenant_id(credentials=_make_creds(token))
    assert tid == "firm-XYZ"


def test_get_current_tenant_id_fallback_main_ohne_tid():
    token = create_access_token({"sub": "x"})
    tid = get_current_tenant_id(credentials=_make_creds(token))
    assert tid == DEFAULT_TENANT_ID


def test_get_current_tenant_id_invalid_token_401():
    creds = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials="this-is-not-a-jwt",
    )
    with pytest.raises(HTTPException) as exc_info:
        get_current_tenant_id(credentials=creds)
    assert exc_info.value.status_code == 401


# ===========================================================================
# 5. Backwards-Compat
# ===========================================================================


def test_legacy_create_access_token_ohne_tid_funktioniert():
    """create_access_token({sub: x}) ohne tid liefert valides Token (Legacy)."""
    token = create_access_token({"sub": "old-user"})
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    assert payload["sub"] == "old-user"
    assert "tid" not in payload
