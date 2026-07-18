from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt as _bcrypt
# Migration jose -> PyJWT (2026-07-18): python-jose 3.3.0 ist unmaintained und
# CVE-behaftet (Algorithm-Confusion). PyJWT verlangt algorithms= beim decode
# (bereits vorhanden) und schliesst damit alg-Confusion. Nur HS256 (symmetrisch),
# kein JWE -> Wechsel ist verhaltensneutral.
import jwt
from jwt import PyJWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database import get_db
from models.clients import Client
from models.mandates import Mandate
from models.users import User
from config import settings
from services.tenant_context import set_tenant_context

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
    except PyJWTError:
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
    if user.role == "super_admin":
        # Super-admins are unscoped by default: RLS sees no tenant and returns
        # no tenant-owned rows unless an operator path explicitly enables bypass.
        set_tenant_context(db, None)
    else:
        set_tenant_context(db, token_tid or _resolve_tenant_id_for_user(user))
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    # Sprint T4 (2026-06-08): super_admin schluckt auch admin-Pfade
    # (Super-Admin ist eine Erweiterung von Admin).
    if current_user.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Nur für Administratoren")
    return current_user


def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    """Sprint T4 (2026-06-08): Schutz fuer Tenant-Admin-Endpoints.

    Nur 'super_admin'-Role darf andere Tenants erstellen/verwalten.
    In Tier 1 + 3 ist dieser Endpoint deaktiviert via
    settings.tenant_admin_ui_enabled — siehe routers/tenants.py.
    """
    if current_user.role != "super_admin":
        raise HTTPException(
            status_code=403,
            detail="Nur fuer Super-Administratoren (Tier-2-Operator)",
        )
    return current_user


def require_advisor(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ("admin", "advisor"):
        raise HTTPException(status_code=403, detail="Keine Schreibberechtigung")
    return current_user


def has_global_client_access(current_user: User) -> bool:
    return current_user.role == "admin"


def _apply_tenant_filter_to_client_query(query, current_user: User):
    """Sprint T3 (2026-06-08): Erweitert eine Client-Query um tenant_id-Filter.

    Backwards-Compat-Regeln:
    - User OHNE tenant_id (Legacy): KEIN Filter (alte Behavior)
    - User MIT tenant_id: Filter auf gleichen tenant_id ODER Client.tenant_id IS NULL
      (Pre-T1-Daten ohne Tenant gelten als 'main', siehe T2)

    Damit ist Tier 2 (Shared-Cloud) sicher: Berater aus Firma A sieht nie
    Clients von Firma B. Tier 1 (Self-Hosted) wo nur ein Tenant 'main'
    existiert: kein Sicherheits-Verlust.
    """
    user_tid = getattr(current_user, "tenant_id", None)
    if not user_tid or not str(user_tid).strip():
        return query  # Legacy-User: kein Filter
    user_tid_clean = str(user_tid).strip()
    from sqlalchemy import or_
    from config import settings as _settings
    # E1 (2026-06-14): Strict-Modus -> NUR exakter Tenant-Match (NULL unsichtbar).
    if getattr(_settings, "strict_tenant_isolation", False):
        return query.filter(Client.tenant_id == user_tid_clean)
    # BC: Client.tenant_id == user_tid OR Client.tenant_id IS NULL (Pre-T1 = 'main').
    return query.filter(
        or_(Client.tenant_id == user_tid_clean, Client.tenant_id.is_(None))
    )


def _apply_tenant_filter_to_mandate_query(query, current_user: User):
    """Sprint T3 (2026-06-08): Erweitert eine Mandate-Query um tenant_id-Filter.

    Mandate-Query MUSS bereits einen JOIN auf Client haben (siehe
    get_mandate_for_user_or_404). Filter wird auf Mandate.tenant_id
    angewendet — Mandate IST die Authoritative-Tenant-Ebene fuer Daten.
    """
    user_tid = getattr(current_user, "tenant_id", None)
    if not user_tid or not str(user_tid).strip():
        return query
    user_tid_clean = str(user_tid).strip()
    from sqlalchemy import or_
    from config import settings as _settings
    if getattr(_settings, "strict_tenant_isolation", False):
        return query.filter(Mandate.tenant_id == user_tid_clean)
    return query.filter(
        or_(Mandate.tenant_id == user_tid_clean, Mandate.tenant_id.is_(None))
    )


def get_client_for_user_or_404(client_id: str, db: Session, current_user: User) -> Client:
    query = db.query(Client).filter(
        Client.id == client_id,
        Client.deleted_at.is_(None),
    )
    if not has_global_client_access(current_user):
        query = query.filter(Client.advisor_id == current_user.id)
    # Sprint T3: Tenant-Scoping (zusaetzlich zum advisor_id-Filter)
    query = _apply_tenant_filter_to_client_query(query, current_user)
    client = query.first()
    if not client:
        raise HTTPException(status_code=404, detail="Kunde nicht gefunden")
    return client


def get_accessible_client_ids(db: Session, current_user: User) -> list[str]:
    query = db.query(Client.id).filter(Client.deleted_at.is_(None))
    if not has_global_client_access(current_user):
        query = query.filter(Client.advisor_id == current_user.id)
    # Sprint T3: Tenant-Scoping
    query = _apply_tenant_filter_to_client_query(query, current_user)
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
    # Sprint T3: Tenant-Scoping auf Mandate-Ebene (Authoritative)
    query = _apply_tenant_filter_to_mandate_query(query, current_user)
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
    # Sprint T3: Tenant-Scoping
    query = _apply_tenant_filter_to_mandate_query(query, current_user)
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
    except PyJWTError:
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
    # E1 (2026-06-14): Defense-in-depth — die 1:1-Linkage allein darf NICHT
    # genuegen. Wenn die tenant_id des Client-Users und des Clients beide
    # gesetzt sind und sich unterscheiden, ist das eine tenant-uebergreifende
    # (fehlerhafte/boesartige) Verknuepfung -> 404 statt Leak. Im Strict-Modus
    # wird die Trennung zusaetzlich strikt verlangt.
    _utid = getattr(user, "tenant_id", None)
    _ctid = getattr(client, "tenant_id", None)
    _utid_s = str(_utid).strip() if _utid is not None else ""
    _ctid_s = str(_ctid).strip() if _ctid is not None else ""
    if _utid_s and _ctid_s and _utid_s != _ctid_s:
        raise HTTPException(status_code=404, detail="Kunden-Datensatz nicht verfuegbar.")
    try:
        from config import settings as _settings
        if getattr(_settings, "strict_tenant_isolation", False) and _utid_s and _utid_s != _ctid_s:
            raise HTTPException(status_code=404, detail="Kunden-Datensatz nicht verfuegbar.")
    except HTTPException:
        raise
    except Exception:
        pass
    return client
