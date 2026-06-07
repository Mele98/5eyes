from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt as _bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database import get_db
from models.clients import Client
from models.mandates import Mandate
from models.users import User
from config import settings

bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Erzeugt ein JWT-Access-Token.

    Sprint T2 (2026-06-08): Falls 'tid' (tenant_id) nicht im data-Dict ist,
    wird kein Tenant-Claim hinzugefuegt — der Aufrufer (typischerweise der
    Login-Endpoint) ist verantwortlich tid mitzugeben. Wenn das Token KEIN
    tid hat, faellt get_current_tenant_id auf 'main' zurueck (Backwards-
    Compat fuer existierende Tokens).
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode["exp"] = expire
    to_encode["iat"] = now
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def _resolve_tenant_id_for_user(user: User) -> str:
    """Sprint T2 (2026-06-08): Liefert die effektive tenant_id eines Users.

    Reihenfolge:
    1. user.tenant_id wenn gesetzt
    2. DEFAULT_TENANT_ID ('main') als Fallback (Backwards-Compat)

    Diese Funktion wird beim Login + bei Token-Validation aufgerufen.
    """
    from models.tenant import DEFAULT_TENANT_ID
    raw = getattr(user, "tenant_id", None)
    if raw and isinstance(raw, str) and raw.strip():
        return raw.strip()
    return DEFAULT_TENANT_ID


def issue_token_for_user(user: User, expires_delta: Optional[timedelta] = None) -> str:
    """Sprint T2 (2026-06-08): Convenience-Wrapper der ein Token mit
    tenant_id-Claim ausstellt. Login-Endpoint nutzt das.
    """
    tid = _resolve_tenant_id_for_user(user)
    return create_access_token({"sub": user.id, "tid": tid}, expires_delta=expires_delta)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token ungültig oder abgelaufen",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
            options={"verify_exp": False},
        )
        try:
            exp_ts = float(payload.get("exp"))
        except (TypeError, ValueError):
            raise credentials_exception
        if exp_ts <= datetime.now(timezone.utc).timestamp():
            raise credentials_exception
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if user is None or not user.is_active:
        raise credentials_exception
    # Sprint T2 (2026-06-08): Tenant-Cross-Check.
    # Wenn das Token einen tid-Claim enthaelt und der User in der DB einen
    # festen tenant_id hat: beide MUESSEN matchen, sonst 401 (Sicherheits-
    # Constraint — Token darf nicht 'wandern').
    # Wenn Token kein tid hat (Legacy-Token): erlaubt (Backwards-Compat).
    # Wenn User keine tenant_id in DB hat: ebenfalls erlaubt (Pre-T1-User).
    token_tid = payload.get("tid")
    user_tid = getattr(user, "tenant_id", None)
    if token_tid and user_tid and str(token_tid).strip() != str(user_tid).strip():
        raise credentials_exception
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Nur für Administratoren")
    return current_user


def require_advisor(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ("admin", "advisor"):
        raise HTTPException(status_code=403, detail="Keine Schreibberechtigung")
    return current_user


def has_global_client_access(current_user: User) -> bool:
    return current_user.role == "admin"


def get_client_for_user_or_404(client_id: str, db: Session, current_user: User) -> Client:
    query = db.query(Client).filter(
        Client.id == client_id,
        Client.deleted_at.is_(None),
    )
    if not has_global_client_access(current_user):
        query = query.filter(Client.advisor_id == current_user.id)
    client = query.first()
    if not client:
        raise HTTPException(status_code=404, detail="Kunde nicht gefunden")
    return client


def get_accessible_client_ids(db: Session, current_user: User) -> list[str]:
    query = db.query(Client.id).filter(Client.deleted_at.is_(None))
    if not has_global_client_access(current_user):
        query = query.filter(Client.advisor_id == current_user.id)
    return [row[0] for row in query.all()]


def get_mandate_for_user_or_404(mandate_id: str, db: Session, current_user: User) -> Mandate:
    query = (
        db.query(Mandate)
        .join(Client, Client.id == Mandate.client_id)
        .filter(
            Mandate.id == mandate_id,
            Mandate.deleted_at.is_(None),
            Client.deleted_at.is_(None),
        )
    )
    if not has_global_client_access(current_user):
        query = query.filter(Client.advisor_id == current_user.id)
    mandate = query.first()
    if not mandate:
        raise HTTPException(status_code=404, detail="Mandat nicht gefunden")
    return mandate


def get_accessible_mandate_ids(db: Session, current_user: User) -> list[str]:
    query = (
        db.query(Mandate.id)
        .join(Client, Client.id == Mandate.client_id)
        .filter(
            Mandate.deleted_at.is_(None),
            Client.deleted_at.is_(None),
        )
    )
    if not has_global_client_access(current_user):
        query = query.filter(Client.advisor_id == current_user.id)
    return [row[0] for row in query.all()]


# ---------------------------------------------------------------------------
# Sprint T2 (2026-06-08): Tenant-Aware Auth-Helpers.
# ---------------------------------------------------------------------------


def get_current_tenant_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    """Sprint T2 (2026-06-08): Extrahiert tenant_id aus dem JWT-Claim.

    Reihenfolge:
    1. JWT-Claim 'tid' (gesetzt durch issue_token_for_user)
    2. Fallback: 'main' (Backwards-Compat fuer Tokens ohne tid)

    Validiert die JWT-Signatur + Expiration. Bei ungueltigem Token: 401.

    Verwendung in Routern wenn DIREKT die Tenant-ID gebraucht wird ohne
    das volle User-Objekt zu laden — z.B. fuer Cross-Tenant-Leak-Tests
    oder Admin-Endpoints.

    Normalweise reicht `Depends(get_current_user)` und dann auf
    `_resolve_tenant_id_for_user(user)` zugreifen.
    """
    from models.tenant import DEFAULT_TENANT_ID

    token = credentials.credentials
    try:
        payload = jwt.decode(
            token, settings.secret_key,
            algorithms=[settings.algorithm],
            options={"verify_exp": False},
        )
        try:
            exp_ts = float(payload.get("exp"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Token ungültig")
        if exp_ts <= datetime.now(timezone.utc).timestamp():
            raise HTTPException(status_code=401, detail="Token abgelaufen")
        tid = payload.get("tid")
        if tid and isinstance(tid, str) and tid.strip():
            return tid.strip()
        return DEFAULT_TENANT_ID
    except JWTError:
        raise HTTPException(status_code=401, detail="Token ungültig")


def user_tenant_id(user: User) -> str:
    """Convenience: tenant_id eines Users (mit 'main'-Fallback).

    Identisch zu _resolve_tenant_id_for_user aber als Public-API
    fuer Repository-Layer (Sprint T3).
    """
    return _resolve_tenant_id_for_user(user)


# ---------------------------------------------------------------------------
# Sprint U-36 (2026-06-06): Client-Portal Auth-Layer.
# ---------------------------------------------------------------------------

def require_client(current_user: User = Depends(get_current_user)) -> User:
    """Akzeptiert NUR role='client' (Kunden-Login). Verweigert advisor/admin.

    Genutzt vom /client-portal-Router damit Advisor/Admins nicht
    versehentlich den Read-Only-Kunden-Pfad ausprobieren — die echte
    Berater-Sicht hat ihren eigenen Endpoint-Stack.
    """
    if current_user.role != "client":
        raise HTTPException(
            status_code=403,
            detail="Dieser Endpoint ist nur fuer Kunden-Logins erreichbar.",
        )
    return current_user


def get_linked_client_for_user_or_404(user: User, db: Session) -> Client:
    """Fetcht den 1:1-verlinkten Client fuer einen role='client'-User.

    Raises 404 wenn keine Linkage existiert oder der Client geloescht
    wurde — dann sieht der Client-User absichtlich nichts (kein Leak
    durch fehlerhafte Linkage).
    """
    from models.client_login import ClientLogin

    link = (
        db.query(ClientLogin)
        .filter(
            ClientLogin.user_id == user.id,
            ClientLogin.is_active == 1,
        )
        .first()
    )
    if not link:
        raise HTTPException(
            status_code=404,
            detail="Kein Kunden-Datensatz mit diesem Login verknuepft.",
        )
    client = (
        db.query(Client)
        .filter(
            Client.id == link.client_id,
            Client.deleted_at.is_(None),
        )
        .first()
    )
    if not client:
        raise HTTPException(
            status_code=404,
            detail="Kunden-Datensatz nicht mehr verfuegbar.",
        )
    return client
