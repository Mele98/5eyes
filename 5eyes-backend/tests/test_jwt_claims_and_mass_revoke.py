"""AF-6 (AUDIT-FIX, 2026-10-23): JWT-Claims iss/aud/kid + Massenwiderruf.

Vorher
------
- Access-Tokens trugen nur sub/tid/exp/iat. Kein ``iss``, kein ``aud``,
  kein ``kid`` -> ein mit demselben ``SECRET_KEY`` signiertes Token einer
  anderen Installation (z.B. vor einer Daten-Migration mit kopierten
  User-IDs) war hier uneingeschraenkt gueltig.
- Es gab nur den Widerruf je Benutzer (Logout, Passwortwechsel). Ein
  Massenwiderruf (alle Sessions, alle Geraete, alle Benutzer) fehlte.

Nachher
-------
- Jedes Access-Token traegt ``iss``/``aud`` (Payload) und ``kid`` (Header)
  aus den Settings; die Validierung verlangt passende Werte, ``iat`` ist
  Pflicht, ein unbekanntes ``kid`` wird abgelehnt.
- BEWUSSTE WIRKUNG: bereits ausgestellte Tokens ohne diese Claims werden
  einmalig abgelehnt -> jeder Benutzer meldet sich einmal neu an
  (``test_legacy_token_without_new_claims_forces_relogin``).
- Massenwiderruf: ``services.session_revocation.revoke_all_sessions``
  (global per CLI ``scripts/revoke_all_sessions.py`` oder je Mandant per
  ``POST /auth/admin/revoke-all-sessions``) setzt ``token_revoked_before``
  fuer alle betroffenen Benutzer, revoziert alle aktiven Refresh-Tokens
  und schreibt einen Audit-Eintrag. Zusaetzlich greift eine globale
  Untergrenze ``settings.token_revoked_before`` (Env ``TOKEN_REVOKED_BEFORE``)
  ohne DB-Schreibzugriff fuer Access- UND Refresh-Tokens.
"""
from __future__ import annotations

import datetime
import json
import sys
import time
from pathlib import Path

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import settings  # noqa: E402
from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.refresh_token import RefreshToken  # noqa: E402
from models.review import AuditLog  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import hash_password  # noqa: E402

# Default-Werte (markenneutral) -- ueber getattr, damit der Test gegen den
# alten Stand wegen des VERHALTENS rot ist, nicht wegen eines AttributeError.
ISSUER = getattr(settings, "jwt_issuer", "local-advisory-backend")
AUDIENCE = getattr(settings, "jwt_audience", "advisory-app")
KID = getattr(settings, "jwt_key_id", "k1")


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_jwt_claims.db'}",
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


def _seed_tenant(SF, tid):
    with SF() as s:
        s.add(Tenant(id=tid, display_name=tid, slug=tid, created_at=_now(), updated_at=_now()))
        s.commit()


def _seed_user(SF, uid, password="pw-123456", role="advisor", tenant_id=None):
    with SF() as s:
        s.add(User(
            id=uid, username=uid, password_hash=hash_password(password),
            full_name=uid, role=role, is_active=1, tenant_id=tenant_id,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()


def _login(client, uid, password="pw-123456"):
    r = client.post("/auth/login", json={"username": uid, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("refresh_token"), "Login muss ein Refresh-Token liefern"
    return body["access_token"], body["refresh_token"]


def _me(client, token):
    return client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})


def _refresh(client, refresh_token):
    return client.post("/auth/refresh", json={"refresh_token": refresh_token})


def _forge(payload_overrides=None, *, drop=(), headers=None, uid="u-forge"):
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": uid,
        "tid": "main",
        "iat": now,
        "exp": now + datetime.timedelta(minutes=10),
        "iss": ISSUER,
        "aud": AUDIENCE,
    }
    payload.update(payload_overrides or {})
    for key in drop:
        payload.pop(key, None)
    hdr = {"kid": KID} if headers is None else headers
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm, headers=hdr)


# ---------------------------------------------------------------------------
# Positivkontrolle
# ---------------------------------------------------------------------------

def test_positive_control_login_me_refresh(client, session_factory):
    _seed_user(session_factory, "u-pos")
    access, refresh = _login(client, "u-pos")
    assert _me(client, access).status_code == 200
    r = _refresh(client, refresh)
    assert r.status_code == 200, r.text
    assert _me(client, r.json()["access_token"]).status_code == 200


def test_issued_access_token_carries_iss_aud_kid(client, session_factory):
    _seed_user(session_factory, "u-claims")
    access, _ = _login(client, "u-claims")
    header = jwt.get_unverified_header(access)
    payload = jwt.decode(access, options={"verify_signature": False})
    assert header.get("kid") == KID
    assert payload.get("iss") == ISSUER
    assert payload.get("aud") == AUDIENCE
    assert "iat" in payload


def test_forged_token_with_correct_claims_is_accepted(client, session_factory):
    """Kontrolle fuer die Negativtests unten: dasselbe Schmiede-Rezept MIT
    allen korrekten Claims wird akzeptiert -- die Ablehnungen unten liegen
    also wirklich am jeweils fehlenden/falschen Claim."""
    _seed_user(session_factory, "u-forge")
    assert _me(client, _forge()).status_code == 200


# ---------------------------------------------------------------------------
# iss / aud / kid
# ---------------------------------------------------------------------------

def test_token_without_aud_rejected(client, session_factory):
    _seed_user(session_factory, "u-forge")
    assert _me(client, _forge(drop=("aud",))).status_code == 401


def test_token_with_wrong_aud_rejected(client, session_factory):
    _seed_user(session_factory, "u-forge")
    assert _me(client, _forge({"aud": "other-app"})).status_code == 401


def test_token_with_wrong_iss_rejected(client, session_factory):
    _seed_user(session_factory, "u-forge")
    assert _me(client, _forge({"iss": "some-other-installation"})).status_code == 401


def test_token_without_iss_rejected(client, session_factory):
    _seed_user(session_factory, "u-forge")
    assert _me(client, _forge(drop=("iss",))).status_code == 401


def test_token_with_unknown_kid_rejected(client, session_factory):
    _seed_user(session_factory, "u-forge")
    assert _me(client, _forge(headers={"kid": "k-unknown"})).status_code == 401


def test_token_without_kid_rejected(client, session_factory):
    _seed_user(session_factory, "u-forge")
    assert _me(client, _forge(headers={})).status_code == 401


def test_token_without_iat_rejected(client, session_factory):
    """Ohne iat liesse sich kein Widerruf pruefen -> Pflicht-Claim."""
    _seed_user(session_factory, "u-forge")
    assert _me(client, _forge(drop=("iat",))).status_code == 401


def test_legacy_token_without_new_claims_forces_relogin(client, session_factory):
    """Bewusste Wirkung: ein Token im bisherigen Format (sub/tid/exp/iat, kein
    iss/aud/kid) wird einmalig abgelehnt; ein frischer Login funktioniert."""
    _seed_user(session_factory, "u-forge")
    now = datetime.datetime.now(datetime.UTC)
    legacy = jwt.encode(
        {"sub": "u-forge", "tid": "main", "iat": now, "exp": now + datetime.timedelta(minutes=10)},
        settings.secret_key,
        algorithm=settings.algorithm,
    )
    assert _me(client, legacy).status_code == 401
    fresh, _ = _login(client, "u-forge")
    assert _me(client, fresh).status_code == 200


def test_tenant_id_dependency_also_validates_claims():
    """Zweiter Decode-Pfad (get_current_tenant_id) muss dieselben Claims
    verlangen -- sonst waere er ein Umgehungsweg."""
    from services.auth import get_current_tenant_id

    ok = _forge({"tid": "tenant-x"})
    assert get_current_tenant_id(HTTPAuthorizationCredentials(scheme="Bearer", credentials=ok)) == "tenant-x"
    for bad in (
        _forge(drop=("aud",)),
        _forge({"iss": "other"}),
        _forge(headers={"kid": "k-unknown"}),
    ):
        with pytest.raises(HTTPException) as exc:
            get_current_tenant_id(HTTPAuthorizationCredentials(scheme="Bearer", credentials=bad))
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# Massenwiderruf
# ---------------------------------------------------------------------------

def test_global_mass_revoke_rejects_old_access_and_refresh(client, session_factory):
    from services.session_revocation import revoke_all_sessions

    _seed_tenant(session_factory, "t-a")
    _seed_tenant(session_factory, "t-b")
    _seed_user(session_factory, "u-a", tenant_id="t-a")
    _seed_user(session_factory, "u-b", tenant_id="t-b")
    access_a, refresh_a = _login(client, "u-a")
    access_b, refresh_b = _login(client, "u-b")
    assert _me(client, access_a).status_code == 200
    assert _me(client, access_b).status_code == 200

    with session_factory() as s:
        result = revoke_all_sessions(s, actor_user_id="cli-operator", actor_name="cli-operator")
        s.commit()
    assert result.users == 2
    assert result.refresh_tokens == 2

    for access, refresh in ((access_a, refresh_a), (access_b, refresh_b)):
        assert _me(client, access).status_code == 401
        assert _refresh(client, refresh).status_code == 401

    # Refresh-Zeilen bleiben erhalten (Reuse-Detection-Historie), nur revoziert.
    with session_factory() as s:
        rows = s.query(RefreshToken).all()
        assert len(rows) == 2
        assert all(r.revoked_at for r in rows)
        audit = s.query(AuditLog).filter(AuditLog.field_name == "token_revoked_before").all()
        assert len(audit) == 1
        detail = json.loads(audit[0].new_value)
        assert detail["scope"] == "global"
        assert detail["users"] == 2 and detail["refresh_tokens"] == 2

    time.sleep(1.1)  # JWT-iat hat Sekunden-Aufloesung (siehe test_auth04).
    new_access, new_refresh = _login(client, "u-a")
    assert _me(client, new_access).status_code == 200
    r = _refresh(client, new_refresh)
    assert r.status_code == 200, r.text
    assert _me(client, r.json()["access_token"]).status_code == 200


def test_per_user_revocation_also_blocks_refresh_issued_before(client, session_factory):
    """token_revoked_before je Benutzer gilt jetzt auch fuer Refresh-Tokens,
    selbst wenn ein Pfad vergessen haette, revoke_all_for_user aufzurufen."""
    _seed_user(session_factory, "u-pu")
    _, refresh = _login(client, "u-pu")
    time.sleep(0.05)
    with session_factory() as s:
        u = s.get(User, "u-pu")
        u.token_revoked_before = _now()
        s.commit()
    assert _refresh(client, refresh).status_code == 401


def test_settings_floor_rejects_old_access_and_refresh(client, session_factory, monkeypatch):
    _seed_user(session_factory, "u-floor")
    access, refresh = _login(client, "u-floor")
    assert _me(client, access).status_code == 200
    time.sleep(0.05)
    monkeypatch.setattr(settings, "token_revoked_before", _now(), raising=False)
    assert _me(client, access).status_code == 401
    assert _refresh(client, refresh).status_code == 401
    time.sleep(1.1)
    fresh_access, fresh_refresh = _login(client, "u-floor")
    assert _me(client, fresh_access).status_code == 200
    assert _refresh(client, fresh_refresh).status_code == 200


def test_settings_floor_rejects_unparseable_value(monkeypatch):
    from config import Settings

    monkeypatch.setenv("TOKEN_REVOKED_BEFORE", "not-a-date")
    with pytest.raises(Exception):
        Settings()


def test_admin_endpoint_revokes_only_own_tenant(client, session_factory):
    _seed_tenant(session_factory, "t-a")
    _seed_tenant(session_factory, "t-b")
    _seed_user(session_factory, "admin-a", role="admin", tenant_id="t-a")
    _seed_user(session_factory, "u-a2", tenant_id="t-a")
    _seed_user(session_factory, "u-b2", tenant_id="t-b")
    admin_access, _ = _login(client, "admin-a")
    a_access, a_refresh = _login(client, "u-a2")
    b_access, b_refresh = _login(client, "u-b2")

    r = client.post(
        "/auth/admin/revoke-all-sessions",
        headers={"Authorization": f"Bearer {admin_access}"},
        json={},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "t-a"
    assert body["users"] == 2  # admin-a + u-a2

    assert _me(client, a_access).status_code == 401
    assert _refresh(client, a_refresh).status_code == 401
    # Eigenes Token des Admins ist ebenfalls widerrufen (bewusst).
    assert _me(client, admin_access).status_code == 401
    # Anderer Mandant unberuehrt.
    assert _me(client, b_access).status_code == 200
    assert _refresh(client, b_refresh).status_code == 200


def test_admin_endpoint_rejects_foreign_tenant(client, session_factory):
    _seed_tenant(session_factory, "t-a")
    _seed_tenant(session_factory, "t-b")
    _seed_user(session_factory, "admin-a3", role="admin", tenant_id="t-a")
    _seed_user(session_factory, "u-b3", tenant_id="t-b")
    admin_access, _ = _login(client, "admin-a3")
    b_access, _ = _login(client, "u-b3")
    r = client.post(
        "/auth/admin/revoke-all-sessions",
        headers={"Authorization": f"Bearer {admin_access}"},
        json={"tenant_id": "t-b"},
    )
    assert r.status_code == 403
    assert _me(client, b_access).status_code == 200


def test_admin_endpoint_requires_admin(client, session_factory):
    _seed_user(session_factory, "u-plain")
    access, _ = _login(client, "u-plain")
    r = client.post(
        "/auth/admin/revoke-all-sessions",
        headers={"Authorization": f"Bearer {access}"},
        json={},
    )
    assert r.status_code == 403
    assert _me(client, access).status_code == 200


def test_cli_revokes_all_sessions(client, session_factory, monkeypatch, capsys):
    import database
    sys.path.insert(0, str(BACKEND_ROOT / "scripts"))
    import revoke_all_sessions as cli

    _seed_user(session_factory, "u-cli")
    access, refresh = _login(client, "u-cli")
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    assert cli.main(["--yes"]) == 0
    out = capsys.readouterr().out
    assert "users=1" in out and "refresh_tokens=1" in out
    assert _me(client, access).status_code == 401
    assert _refresh(client, refresh).status_code == 401


def test_cli_requires_confirmation(session_factory, monkeypatch):
    import database
    sys.path.insert(0, str(BACKEND_ROOT / "scripts"))
    import revoke_all_sessions as cli

    monkeypatch.setattr(database, "SessionLocal", session_factory)
    assert cli.main([]) == 2


# ---------------------------------------------------------------------------
# Grund der Ablehnung exakt pruefen (nicht nur "401 aus irgendeinem Grund")
# ---------------------------------------------------------------------------

def test_decode_rejects_wrong_iss_with_issuer_error():
    from services.auth import decode_access_token

    with pytest.raises(jwt.InvalidIssuerError):
        decode_access_token(_forge({"iss": "some-other-installation"}))


def test_decode_rejects_missing_or_wrong_aud_with_audience_error():
    from services.auth import decode_access_token

    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_access_token(_forge(drop=("aud",)))
    with pytest.raises(jwt.InvalidAudienceError):
        decode_access_token(_forge({"aud": "other-app"}))


def test_decode_rejects_unknown_kid_before_signature_check():
    from services.auth import UnknownKeyIdError, decode_access_token

    with pytest.raises(UnknownKeyIdError):
        decode_access_token(_forge(headers={"kid": "k-unknown"}))
    with pytest.raises(UnknownKeyIdError):
        decode_access_token(_forge(headers={}))
    # Kontrolle: korrektes Token dekodiert, Claims vorhanden.
    payload = decode_access_token(_forge())
    assert payload["iss"] == ISSUER and payload["aud"] == AUDIENCE
