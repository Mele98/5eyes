from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt as _bcrypt
# Migration jose -> PyJWT (2026-07-18): python-jose 3.3.0 ist unmaintained und
# CVE-behaftet (Algorithm-Confusion). PyJWT verlangt algorithms= beim decode
# (bereits vorhanden) und schliesst damit alg-Confusion. Nur HS256 (symmetrisch),
# kein JWE -> Wechsel ist verhaltensneutral.
import jwt
from jwt import PyJWTError
from fastapi import Depends, HTTPException, status, Request
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


def _parse_iso_timestamp(value) -> Optional[float]:
    """AUTH-04: parst die ISO-Timestamps dieser Codebase (ms-Praezision, ggf.
    'Z'-Suffix) in Unix-Epoch-Sekunden (float). None bei Unparsbarem statt
    Exception -> ein defektes/leeres Feld darf den Auth-Pfad nicht crashen."""
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1]
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def issue_token_for_user(user: User, expires_delta: Optional[timedelta] = None) -> str:
    """Sprint T2 (2026-06-08): Convenience-Wrapper der ein Token mit
    tenant_id-Claim ausstellt. Login-Endpoint nutzt das.
    """
    tid = _resolve_tenant_id_for_user(user)
    return create_access_token({"sub": user.id, "tid": tid}, expires_delta=expires_delta)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    request: Request = None,
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
    # AUTH-04 (2026-07-22): Token-Revocation. /auth/logout setzt
    # token_revoked_before = now; jedes Token, das VOR diesem Zeitpunkt
    # ausgestellt wurde (iat < revoked_before), ist ab sofort ungueltig —
    # unabhaengig von seiner exp. Pragmatisch ohne jti/Blacklist-Tabelle.
    revoked_before_ts = _parse_iso_timestamp(getattr(user, "token_revoked_before", None))
    if revoked_before_ts is not None:
        try:
            iat_ts = float(payload.get("iat"))
        except (TypeError, ValueError):
            iat_ts = None
        if iat_ts is not None and iat_ts < revoked_before_ts:
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
    # AUTH-02 (2026-07-19): must_change_password serverseitig erzwingen. Ein User
    # mit gesetztem Flag darf NUR den Passwortwechsel + /me + /logout aufrufen,
    # bis er das Passwort geaendert hat -> sonst 403. 'request' ist optional
    # (direkte get_current_user-Aufrufe in Tests umgehen das Gate; ueber FastAPI
    # wird es injiziert). Verhindert das Aussperren (change-password bleibt offen).
    #
    # A2-Smoke-Test-Fund (2026-07-22): das bestehende Frontend-Modal fuer den
    # erzwungenen Erst-Passwortwechsel ruft NICHT den neuen /auth/change-password-
    # Endpoint, sondern den bereits vorhandenen Self-Service-Pfad
    # PUT /users/{eigene_id}/password (routers/auth.py:reset_user_password,
    # is_self=True -> Flag wird geloescht). Ohne diese Ausnahme waere JEDER
    # frisch angelegte User permanent ausgesperrt (der einzige UI-Weg zum
    # Passwortwechsel selbst wird geblockt). Bewusst NUR fuer PUT auf die EIGENE
    # user_id -> ein gesperrter Admin kann weiterhin NICHT das Passwort anderer
    # User zuruecksetzen, waehrend sein eigenes offen ist.
    if getattr(user, "must_change_password", 0) and request is not None:
        path = (getattr(getattr(request, "url", None), "path", "") or "").rstrip("/")
        method = str(getattr(request, "method", "") or "").upper()
        is_self_password_reset = (
            method == "PUT"
            and path.endswith("/password")
            and path.rsplit("/", 2)[-2:-1] == [str(user.id)]
        )
        if not (
            path.endswith(("/auth/change-password", "/auth/me", "/auth/logout"))
            or is_self_password_reset
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=("Passwort muss geaendert werden, bevor weitere Aktionen "
                        "moeglich sind (must_change_password)."),
            )
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


def _effective_strict_tenant_isolation(settings_obj) -> bool:
    """rls-1 (2026-07-19): effektive strikte Mandanten-Trennung. True wenn der
    Flag explizit gesetzt ist ODER das Deployment mandantenfaehig ist
    (deployment_tier=='tier2' bzw. tenancy_mode=='multi') — damit ein Multi-
    Tenant-Setup NIE versehentlich ohne Strict-Isolation laeuft (auch ausserhalb
    staging/production, wo der config-Validator es ohnehin erzwingt). Tier1 /
    single-tenant bleibt unveraendert (kein Zwang, BC fuer NULL-tenant-Rows)."""
    if getattr(settings_obj, "strict_tenant_isolation", False):
        return True
    tier = str(getattr(settings_obj, "deployment_tier", "") or "").strip().lower()
    mode = str(getattr(settings_obj, "tenancy_mode", "") or "").strip().lower()
    return tier == "tier2" or mode == "multi"


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
    if _effective_strict_tenant_isolation(_settings):
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
    if _effective_strict_tenant_isolation(_settings):
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

    ⚠️ WARNUNG (2026-07-25, Generalaudit, Wave 11 JWT-Fork): diese Funktion
    laedt den User NICHT aus der DB — sie prueft daher WEDER
    `token_revoked_before` (Logout-/Passwortwechsel-Widerruf, AUTH-04) NOCH
    `is_active`/`deleted_at`. NIEMALS als alleinige Auth-Dependency eines
    Endpoints verwenden (`Depends(get_current_tenant_id)` statt
    `Depends(get_current_user)`) — das wuerde die gesamte Revocation-
    Mechanik lautlos umgehen (ein per Logout widerrufenes Token bliebe
    bis zum Ablauf gueltig). Aktuell (Stand Audit) wird diese Funktion in
    KEINEM Router als Dependency genutzt — nur fuer Faelle, wo zusaetzlich
    zu `get_current_user` bereits geprueft wurde.
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
        if _effective_strict_tenant_isolation(_settings) and _utid_s and _utid_s != _ctid_s:
            raise HTTPException(status_code=404, detail="Kunden-Datensatz nicht verfuegbar.")
    except HTTPException:
        raise
    except Exception:
        pass
    return client
