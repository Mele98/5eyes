import hashlib
import logging
import secrets
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from database import get_db, new_uuid
from models.tenant import Tenant
from models.users import User, AdviserRegistration
from schemas.users import (
    AdviserRegistrationCreate, AdviserRegistrationResponse, BootstrapAdminRequest,
    BootstrapStatusResponse, InviteAccept, InviteCreate, InvitePreview, InviteResponse,
    LoginRequest, TokenResponse, UserCreate, UserPasswordReset,
    UserUpdate, UserResponse,
)
from services.auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, require_admin,
    _effective_strict_tenant_isolation, tenant_access_block_reason,
)
from services.login_guard import login_attempt_guard
from services.audit import log
from services.totp import (
    generate_secret, provisioning_uri, qr_svg_data_uri, verify as totp_verify,
    _PERIOD as _TOTP_PERIOD_SECONDS,
)
from services.mailer import send_invite_email, send_password_reset_email
from services.quota import assert_within_quota
from services.account_recovery import (
    ensure_account_recovery_columns, generate_recovery_codes, consume_recovery_code,
    remaining_recovery_codes, issue_reset_token, reset_token_valid, clear_reset_token,
)
from sqlalchemy import or_
from pydantic import BaseModel as _BaseModel


class _TwoFACodeRequest(_BaseModel):
    code: str


router = APIRouter(prefix="/auth", tags=["Auth"])
users_router = APIRouter(prefix="/users", tags=["Benutzer"])


logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"




def _bootstrap_required(db: Session) -> bool:
    existing_user = (
        db.query(User.id)
        .filter(User.deleted_at.is_(None))
        .limit(1)
        .first()
    )
    return existing_user is None


# AUTH-05 (Mega-Audit 2026-08-04): TOCTOU-Race fuer "genau 1 Bootstrap-Admin".
# _bootstrap_required() (Check) und das anschliessende db.add(admin)+commit()
# (Write) sind zwei getrennte Schritte -- zwei nahezu gleichzeitige POST
# /auth/bootstrap-admin-Requests koennten beide den Check bestehen, bevor
# irgendeiner committet, und wuerden dann zwei "erste" Admins anlegen. Dieser
# Lock serialisiert den Check+Write-Block INNERHALB eines Prozesses (Tier-1:
# Electron spawnt genau einen Backend-Prozess -- deckt den realistischen Fall
# vollstaendig ab). Deckt NICHT mehrere Worker-Prozesse hinter einem
# Load-Balancer ab (Tier-2/3) -- dort muesste zusaetzlich ein DB-seitiger
# Singleton-Constraint eingefuehrt werden, was eine Schema-Migration braucht
# und bewusst nicht Teil dieses Fixes ist (Ersteinrichtung findet in der
# Praxis typischerweise vor dem Hochskalieren auf mehrere Worker statt).
_bootstrap_admin_lock = threading.Lock()


def _issue_token_response(user: User, db: Session | None = None) -> TokenResponse:
    # Sprint T2 (2026-06-08): Token enthaelt jetzt tid-Claim via
    # issue_token_for_user. Backwards-Compat: User ohne tenant_id bekommt
    # tid='main'.
    from services.auth import issue_token_for_user
    token = issue_token_for_user(user)
    # 2026-08-02 (HUD-Polish): Firmen-Default fuer die UI-"Maske" wird bei
    # JEDEM Login mitgeliefert (nicht nur admin/super_admin via GET
    # /tenants/me), siehe schemas/users.py::TokenResponse. Best-effort --
    # fehlt der Tenant (sollte nie passieren), bleibt das Feld None
    # ("wealthmanagement"-Default, unveraendertes Verhalten).
    tenant_mode = None
    if db is not None:
        from models.tenant import DEFAULT_TENANT_ID, Tenant
        tenant_id = getattr(user, "tenant_id", None) or DEFAULT_TENANT_ID
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if tenant is not None:
            tenant_mode = tenant.default_presentation_mode
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
        tenant_default_presentation_mode=tenant_mode,
    )


def _totp_replay_check_and_record(user: User) -> bool:
    """AUTH-06: Anti-Replay fuer TOTP-Login. services/totp.verify() prueft nur,
    ob der Code zum aktuellen Zeitfenster (+/-1 Zeitschritt) passt — ohne
    Gedaechtnis kann derselbe (mitgelesene) Code beliebig oft im selben
    Zeitfenster wiederverwendet werden. Diese Funktion haelt den zuletzt
    akzeptierten HOTP-Zeitschritt am User fest (totp_last_counter) und liefert
    True, wenn der aktuelle Zeitschritt bereits verwendet wurde (Replay) — der
    Aufrufer MUSS den Login dann verweigern. Sonst wird der Zeitschritt als
    'zuletzt akzeptiert' auf dem (noch nicht committeten) User-Objekt vermerkt.
    services/totp.py bleibt unveraendert."""
    counter = int(time.time() // _TOTP_PERIOD_SECONDS)
    raw_last = getattr(user, "totp_last_counter", None)
    try:
        last = int(raw_last) if raw_last is not None else None
    except (TypeError, ValueError):
        last = None
    if last is not None and counter <= last:
        return True
    user.totp_last_counter = str(counter)
    return False


def _extract_client_ip(request: Request) -> str:
    """AUTH-03 (Mega-Audit 2026-08-04): liefert die vertrauenswuerdige
    Client-IP fuer Rate-Limit-Guard-Keys. Ohne konfigurierten Reverse-Proxy
    (trusted_proxy_count=0, Default) wird X-Forwarded-For komplett ignoriert
    -- der Header ist sonst clientseitig frei waehlbar und erlaubt jedem
    Angreifer, sich pro Request einen frischen Guard-Key zu erschleichen
    (voller Rate-Limit-Bypass). Bei trusted_proxy_count=N (Tier-2/3 hinter N
    eigenen Reverse-Proxies) wird der N-te Hop von RECHTS genommen -- alles
    rechts davon haben die eigenen, vertrauenswuerdigen Proxies angehaengt.
    """
    from config import settings as _settings
    proxy_count = int(getattr(_settings, "trusted_proxy_count", 0) or 0)
    if proxy_count > 0:
        forwarded_for = str(request.headers.get("x-forwarded-for") or "").strip()
        if forwarded_for:
            hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
            if len(hops) >= proxy_count:
                candidate = hops[-proxy_count]
                if candidate:
                    return candidate
    if request.client and request.client.host:
        return str(request.client.host)
    return ""


def _login_guard_key(request: Request, username: str) -> str:
    client_ip = _extract_client_ip(request)
    if client_ip:
        return client_ip
    return username

# ── Auth ───────────────────────────────────────────────────────────────────────


@router.get('/bootstrap-status', response_model=BootstrapStatusResponse)
def bootstrap_status(db: Session = Depends(get_db)):
    required = _bootstrap_required(db)
    return BootstrapStatusResponse(setup_required=required, can_create_admin=required)


def _bootstrap_guard_key(request: Request) -> str:
    """AUTH-05: IP-basierter Guard-Key fuer den OEFFENTLICHEN Bootstrap-Endpoint —
    ohne Limit koennte er als Brute-Force/DoS-Vektor gegen die Ersteinrichtung
    missbraucht werden (Anlegen-Race + wiederholte 409-Anfragen)."""
    return "bootstrap-admin:" + _login_guard_key(request, "bootstrap")


@router.post('/bootstrap-admin', response_model=TokenResponse, status_code=201)
def bootstrap_admin(body: BootstrapAdminRequest, request: Request, db: Session = Depends(get_db)):
    guard_key = _bootstrap_guard_key(request)
    decision = login_attempt_guard.check(guard_key)
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail=decision.reason or "Zu viele Versuche. Bitte später erneut versuchen.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )

    # AUTH-05: Check (_bootstrap_required) und Write (add+commit) muessen
    # atomar wirken -- siehe Kommentar bei _bootstrap_admin_lock oben.
    with _bootstrap_admin_lock:
        if not _bootstrap_required(db):
            failure = login_attempt_guard.register_failure(guard_key)
            if not failure.allowed:
                raise HTTPException(
                    status_code=429,
                    detail=failure.reason or "Zu viele Versuche. Bitte später erneut versuchen.",
                    headers={"Retry-After": str(failure.retry_after_seconds)},
                )
            raise HTTPException(status_code=409, detail='Ersteinrichtung bereits abgeschlossen')

        now = _now()
        admin = User(
            id=new_uuid(),
            username=body.username.strip(),
            password_hash=hash_password(body.password),
            full_name=body.full_name.strip(),
            email=(body.email or None),
            role='admin',
            is_active=1,
            created_at=now,
            updated_at=now,
        )
        db.add(admin)
        # 2026-08-01 (Onboarding, Entscheid Auftraggeber): Firmenidentitaet/
        # -Standort der Default-Tenant-Zeile ('main', von database.py::
        # ensure_default_tenant() bereits beim Boot angelegt) hier mitpflegen,
        # falls angegeben -- sonst bliebe sie dauerhaft "Default Tenant" mit
        # NULL-Jurisdiktion. Bewusst optional/best-effort: die Ersteinrichtung
        # darf nicht am Tenant-Update scheitern, und eine spaetere Korrektur ist
        # jederzeit ueber PUT /tenants/me moeglich.
        if body.company_name or body.home_jurisdiction or body.default_presentation_mode:
            from models.tenant import DEFAULT_TENANT_ID
            tenant = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first()
            if tenant is not None:
                if body.company_name:
                    tenant.display_name = body.company_name.strip()
                if body.home_jurisdiction:
                    tenant.home_jurisdiction = body.home_jurisdiction.strip()
                if body.default_presentation_mode:
                    tenant.default_presentation_mode = body.default_presentation_mode
                tenant.updated_at = now
        db.commit()
        db.refresh(admin)
    login_attempt_guard.register_success(guard_key)
    logger.info('Bootstrap admin created | username=%s', admin.username)
    return _issue_token_response(admin, db)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    guard_key = _login_guard_key(request, body.username)
    decision = login_attempt_guard.check(guard_key)
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail=decision.reason or "Zu viele Fehlversuche. Bitte später erneut versuchen.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )

    user = db.query(User).filter(
        User.username == body.username,
        User.deleted_at.is_(None)
    ).first()
    if not user or not verify_password(body.password, user.password_hash):
        failure = login_attempt_guard.register_failure(guard_key)
        logger.warning(
            "Login failed | username=%s guard_key=%s request_id=%s retry_after=%s",
            body.username,
            guard_key,
            getattr(request.state, 'request_id', 'n/a'),
            failure.retry_after_seconds,
        )
        headers = {"Retry-After": str(failure.retry_after_seconds)} if failure.retry_after_seconds else None
        raise HTTPException(status_code=401, detail="Benutzername oder Passwort falsch", headers=headers)
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Konto deaktiviert")
    # 2026-07-25 (Generalaudit, Wave 13): siehe tenant_access_block_reason()
    # in services/auth.py -- ohne diesen Check konnte sich ein User auch
    # nach Tenant-Deaktivierung/Lizenz-Sperre weiterhin frisch einloggen.
    tenant_block_reason = tenant_access_block_reason(db, getattr(user, "tenant_id", None))
    if tenant_block_reason is not None:
        raise HTTPException(status_code=403, detail=tenant_block_reason)

    # E1 (2026-06-13): 2FA-Gate — fuer externe Logins. Ist 2FA aktiv, muss nach
    # korrektem Passwort ein gueltiger TOTP-Code vorliegen.
    if getattr(user, "totp_enabled", 0):
        code = (body.totp_code or "").strip()
        if not code:
            raise HTTPException(
                status_code=401, detail="2FA-Code erforderlich",
                headers={"X-2FA-Required": "1"},
            )
        if not totp_verify(user.totp_secret or "", code):
            # #25 Fallback: 2FA-Recovery-Code (Backup, falls Authenticator weg).
            # Single-use — verbrauchter Code wird entfernt + persistiert.
            ensure_account_recovery_columns(db)
            if consume_recovery_code(user, code):
                db.commit()
                log(db, user_id=user.id, user_name=user.full_name,
                    table_name="users", record_id=user.id, action="2FA_RECOVERY_USED",
                    ip_address=_extract_client_ip(request))
                db.commit()
            else:
                failure = login_attempt_guard.register_failure(guard_key)
                headers = {"Retry-After": str(failure.retry_after_seconds)} if failure.retry_after_seconds else None
                raise HTTPException(status_code=401, detail="2FA-Code falsch", headers=headers)
        else:
            # AUTH-06: gueltiger TOTP-Code — aber schon in diesem/einem
            # frueheren Zeitschritt verwendet (Replay, z.B. mitgelesener Code)?
            if _totp_replay_check_and_record(user):
                failure = login_attempt_guard.register_failure(guard_key)
                headers = {"Retry-After": str(failure.retry_after_seconds)} if failure.retry_after_seconds else None
                raise HTTPException(status_code=401, detail="2FA-Code bereits verwendet", headers=headers)

    login_attempt_guard.register_success(guard_key)
    user.last_login_at = _now()
    db.commit()
    db.refresh(user)

    log(db, user_id=user.id, user_name=user.full_name,
        table_name="users", record_id=user.id, action="LOGIN",
        ip_address=_extract_client_ip(request))
    db.commit()

    return _issue_token_response(user, db)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/logout")
def logout(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AUTH-04 (2026-07-22): Logout war bisher ein No-op — ein gestohlenes
    Token blieb bis zum Ablauf gueltig. Setzt token_revoked_before = jetzt;
    get_current_user verweigert danach jedes Token mit iat < diesem Zeitpunkt
    (401), unabhaengig von dessen exp."""
    current_user.token_revoked_before = _now()
    current_user.updated_at = _now()
    db.commit()
    return {"message": "Erfolgreich abgemeldet"}


class _ChangePassword(_BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(
    body: _ChangePassword,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AUTH-02 (2026-07-19): Authentifizierter Passwortwechsel des eingeloggten
    Users. Verifiziert das aktuelle Passwort, setzt das neue (>=8 Zeichen,
    verschieden) und loescht must_change_password. Bleibt bei gesetztem
    must_change_password ERREICHBAR (Ausnahme im get_current_user-Gate), damit
    sich niemand aussperrt."""
    if not verify_password(body.current_password or "", current_user.password_hash or ""):
        raise HTTPException(status_code=400, detail="Aktuelles Passwort ist falsch.")
    if len(body.new_password or "") < 8:
        raise HTTPException(status_code=422, detail="Neues Passwort muss mindestens 8 Zeichen haben.")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=422, detail="Neues Passwort muss sich vom aktuellen unterscheiden.")
    # 2026-07-25 (Generalaudit): analog zu AUTH-04 (Logout) -- ein bereits
    # gestohlenes/kompromittiertes Token blieb bisher bis zu 8h (Access-
    # Token-TTL) gueltig, selbst NACH einem Passwortwechsel. ABER: bei einem
    # ERZWUNGENEN Erst-Passwortwechsel (must_change_password=1, z.B. frisch
    # eingeladener User) ist "sofort abmelden" die falsche UX -- das
    # bestehende Frontend-Modal + test_after_change_flag_cleared_and_
    # access_restored erwarten explizit nahtlosen Weiterzugriff mit
    # demselben Token, sonst waere jeder frisch onboardete User sofort
    # wieder ausgesperrt. Revocation nur fuer den REGULAEREN (nicht
    # erzwungenen) Passwortwechsel -- da ist "Session sofort beenden" das
    # sicherheitskonform erwartete Verhalten.
    was_forced_change = bool(current_user.must_change_password)
    current_user.password_hash = hash_password(body.new_password)
    current_user.must_change_password = 0
    current_user.updated_at = _now()
    if not was_forced_change:
        current_user.token_revoked_before = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="users", record_id=current_user.id, action="PASSWORD_CHANGE",
        ip_address=_extract_client_ip(request))
    db.commit()
    return {"message": "Passwort erfolgreich geaendert."}


# ── 2FA / TOTP (E1, externe Logins) ─────────────────────────────────────────────

@router.get("/2fa/status")
def twofa_status(current_user: User = Depends(get_current_user)):
    from config import settings as _settings
    return {
        "enabled": bool(getattr(current_user, "totp_enabled", 0)),
        "required": bool(getattr(_settings, "require_2fa", False)),
    }


@router.post("/2fa/setup")
def twofa_setup(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Erzeugt ein neues TOTP-Secret (noch NICHT aktiv) + otpauth-URI fuer den QR-Code."""
    if getattr(current_user, "totp_enabled", 0):
        raise HTTPException(status_code=409, detail="2FA ist bereits aktiv. Zuerst deaktivieren.")
    secret = generate_secret()
    current_user.totp_secret = secret
    current_user.updated_at = _now()
    db.commit()
    uri = provisioning_uri(secret, current_user.username or current_user.id, issuer="5eyes")
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": qr_svg_data_uri(uri)}


def _twofa_mgmt_guard_key(user_id: str) -> str:
    """2026-07-25 (Generalaudit): Guard-Key fuer /2fa/enable + /2fa/disable,
    keyed nach user_id (nicht IP) -- das relevante Angriffsszenario ist ein
    GESTOHLENES Bearer-Token (XSS/Log-Leak), nicht Credential-Stuffing von
    einer IP. Ein Angreifer mit gueltigem Token aber ohne TOTP-Secret soll den
    6-stelligen Code nicht unbegrenzt raten koennen, um 2FA zu deaktivieren."""
    return "2fa-mgmt:" + str(user_id)


@router.post("/2fa/enable")
def twofa_enable(body: _TwoFACodeRequest, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    """Aktiviert 2FA nach Bestaetigung eines gueltigen Codes aus dem Authenticator."""
    if not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="Kein 2FA-Setup ausstehend. Zuerst /auth/2fa/setup.")
    guard_key = _twofa_mgmt_guard_key(current_user.id)
    decision = login_attempt_guard.check(guard_key)
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail=decision.reason or "Zu viele Fehlversuche. Bitte später erneut versuchen.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )
    if not totp_verify(current_user.totp_secret, body.code):
        failure = login_attempt_guard.register_failure(guard_key)
        headers = {"Retry-After": str(failure.retry_after_seconds)} if failure.retry_after_seconds else None
        raise HTTPException(status_code=401, detail="2FA-Code falsch", headers=headers)
    login_attempt_guard.register_success(guard_key)
    current_user.totp_enabled = 1
    current_user.updated_at = _now()
    # #25: Recovery-Codes erzeugen und EINMALIG zurueckgeben (nur Hashes gespeichert).
    ensure_account_recovery_columns(db)
    codes, blob = generate_recovery_codes()
    current_user.totp_recovery_codes = blob
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="users", record_id=current_user.id, action="2FA_ENABLE")
    db.commit()
    return {"enabled": True, "recovery_codes": codes, "recovery_codes_count": len(codes)}


@router.post("/2fa/disable")
def twofa_disable(body: _TwoFACodeRequest, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    """Deaktiviert 2FA (erfordert einen gueltigen Code) und loescht das Secret."""
    if not getattr(current_user, "totp_enabled", 0):
        return {"enabled": False}
    guard_key = _twofa_mgmt_guard_key(current_user.id)
    decision = login_attempt_guard.check(guard_key)
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail=decision.reason or "Zu viele Fehlversuche. Bitte später erneut versuchen.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )
    if not totp_verify(current_user.totp_secret or "", body.code):
        failure = login_attempt_guard.register_failure(guard_key)
        headers = {"Retry-After": str(failure.retry_after_seconds)} if failure.retry_after_seconds else None
        raise HTTPException(status_code=401, detail="2FA-Code falsch", headers=headers)
    login_attempt_guard.register_success(guard_key)
    current_user.totp_enabled = 0
    current_user.totp_secret = None
    current_user.totp_recovery_codes = None  # #25: Backup-Codes mit-entwerten
    current_user.updated_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="users", record_id=current_user.id, action="2FA_DISABLE")
    db.commit()
    return {"enabled": False}


# ── 2FA Recovery-Codes (#25) ─────────────────────────────────────────────────

@router.get("/2fa/recovery/status")
def twofa_recovery_status(current_user: User = Depends(get_current_user)):
    return {
        "enabled": bool(getattr(current_user, "totp_enabled", 0)),
        "remaining": remaining_recovery_codes(current_user),
    }


@router.post("/2fa/recovery/regenerate")
def twofa_recovery_regenerate(db: Session = Depends(get_db),
                              current_user: User = Depends(get_current_user)):
    """Erzeugt einen NEUEN Satz Recovery-Codes (alte werden ungueltig). 2FA muss aktiv sein."""
    if not getattr(current_user, "totp_enabled", 0):
        raise HTTPException(status_code=400, detail="2FA ist nicht aktiv.")
    ensure_account_recovery_columns(db)
    codes, blob = generate_recovery_codes()
    current_user.totp_recovery_codes = blob
    current_user.updated_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="users", record_id=current_user.id, action="2FA_RECOVERY_REGEN")
    db.commit()
    return {"recovery_codes": codes, "recovery_codes_count": len(codes)}


# ── Passwort-Reset (#27, Self-Service) ───────────────────────────────────────

class _PasswordResetRequest(_BaseModel):
    username: str | None = None
    email: str | None = None


class _PasswordResetConfirm(_BaseModel):
    token: str
    new_password: str


def _trusted_public_base_url() -> str | None:
    """2026-07-25 (Generalaudit): ist public_base_url konfiguriert, wird sie
    IMMER bevorzugt und der (Client-kontrollierte!) Host/X-Forwarded-Host-
    Header komplett ignoriert -- schliesst Host-Header-Injection auf den
    versendeten Reset-/Invite-Links. Siehe config.py::public_base_url."""
    from config import settings as _settings
    configured = str(getattr(_settings, "public_base_url", None) or "").strip()
    return configured.rstrip("/") if configured else None


def _reset_link_for(request: Request, token: str) -> str:
    base = _trusted_public_base_url()
    if base is None:
        base = str(request.base_url).rstrip("/") if request else ""
    return f"{base}/app/5eyes_v2.html?reset={token}"


@router.post("/password-reset/request")
def password_reset_request(body: _PasswordResetRequest, request: Request,
                           db: Session = Depends(get_db)):
    """Startet einen Passwort-Reset. Antwortet IMMER generisch (keine Konto-
    Enumeration). Versendet bei konfiguriertem SMTP eine Mail; sonst kein Leak."""
    # Rate-Limit gegen Reset-Spam (Wiederverwendung des Login-Guards).
    ident = (body.username or body.email or "").strip()
    guard_key = "pwreset:" + _login_guard_key(request, ident or "anon")
    decision = login_attempt_guard.check(guard_key)
    if not decision.allowed:
        raise HTTPException(status_code=429, detail=decision.reason or "Zu viele Anfragen.",
                            headers={"Retry-After": str(decision.retry_after_seconds)})
    login_attempt_guard.register_failure(guard_key)  # jeder Versuch zaehlt zum Limit

    generic = {"message": "Falls ein Konto existiert, wurde eine Reset-Anleitung an die hinterlegte E-Mail gesendet."}
    if not ident:
        return generic
    ensure_account_recovery_columns(db)
    user = db.query(User).filter(
        User.deleted_at.is_(None),
        or_(User.username == ident, User.email == ident),
    ).first()
    if not user or not user.is_active:
        return generic
    token = issue_reset_token(user)
    user.updated_at = _now()
    db.commit()
    send_password_reset_email(user.email, user.full_name, _reset_link_for(request, token))
    log(db, user_id=user.id, user_name=user.full_name,
        table_name="users", record_id=user.id, action="PASSWORD_RESET_REQUEST",
        ip_address=_extract_client_ip(request))
    db.commit()
    return generic


@router.post("/password-reset/confirm")
def password_reset_confirm(body: _PasswordResetConfirm, request: Request, db: Session = Depends(get_db)):
    """Setzt das Passwort per gueltigem, nicht abgelaufenem, einmaligem Token."""
    if len((body.new_password or "")) < 8:
        raise HTTPException(status_code=400, detail="Passwort muss mindestens 8 Zeichen haben.")
    ensure_account_recovery_columns(db)
    token_hash = hashlib.sha256((body.token or "").strip().encode("utf-8")).hexdigest()
    user = db.query(User).filter(
        User.reset_token_hash == token_hash,
        User.deleted_at.is_(None),
    ).first()
    if not user or not reset_token_valid(user, body.token):
        raise HTTPException(status_code=400, detail="Ungueltiger oder abgelaufener Reset-Link.")
    user.password_hash = hash_password(body.new_password)
    clear_reset_token(user)
    user.must_change_password = 0
    user.updated_at = _now()
    # 2026-07-25 (Generalaudit, Wave 12): fehlte hier -- anders als der bereits
    # gefixte change_password-Endpoint (AUTH-02-Folgefund). Passwort-Reset ist
    # der dedizierte Account-Recovery-Pfad fuer vermutete Kompromittierung --
    # ohne Revocation bliebe ein bereits gestohlenes Token trotz Reset bis zu
    # 8h gueltig, genau der Angreifer bliebe drin, den der Reset aussperren soll.
    # Anders als change_password (dort Ausnahme fuer erzwungenen Erst-Wechsel)
    # gibt es hier KEINE Ausnahme -- Reset ist immer ein bewusster, expliziter
    # Vorgang ueber einen separaten E-Mail-Link, nie ein Onboarding-Zwischenschritt.
    user.token_revoked_before = _now()
    log(db, user_id=user.id, user_name=user.full_name,
        table_name="users", record_id=user.id, action="PASSWORD_RESET_CONFIRM",
        ip_address=_extract_client_ip(request))
    db.commit()
    return {"message": "Passwort erfolgreich gesetzt. Sie koennen sich jetzt anmelden."}


# ── Users ──────────────────────────────────────────────────────────────────────

@users_router.get("", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    # E1 (2026-06-14): Mandanten-Trennung — super_admin (Operator) sieht ALLE
    # User; ein Firmen-Admin NUR User des eigenen Tenants. Vorher: alle Tenants
    # sichtbar (Cross-Tenant-Leak). Strict/BC-Logik wie bei Client/Mandate.
    q = db.query(User).filter(User.deleted_at.is_(None))
    if getattr(current_user, "role", None) != "super_admin":
        utid = getattr(current_user, "tenant_id", None)
        if utid and str(utid).strip():
            from sqlalchemy import or_
            from config import settings as _settings
            utid_clean = str(utid).strip()
            if getattr(_settings, "strict_tenant_isolation", False):
                q = q.filter(User.tenant_id == utid_clean)
            else:
                q = q.filter(or_(User.tenant_id == utid_clean, User.tenant_id.is_(None)))
    return q.all()


@users_router.post("", response_model=UserResponse, status_code=201)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    existing = db.query(User).filter(
        User.username == body.username,
        User.deleted_at.is_(None)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Benutzername bereits vergeben")
    now = _now()
    tenant_id = getattr(current_user, "tenant_id", None)
    assert_within_quota(db, tenant_id, "users")
    user = User(
        id=new_uuid(),
        username=body.username,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        email=body.email,
        role=body.role,
        is_active=1,
        # E1 (2026-06-13): Mitarbeiter erbt den Tenant des anlegenden Admins ->
        # NIE NULL-tenant_id, harte Firmen-Trennung. Cross-Tenant-Zuweisung macht
        # der super_admin ueber die Tenant-Admin-API (assign).
        tenant_id=tenant_id,
        # E1 (2026-06-14): vom Admin angelegter Account -> Initial-Passwort muss
        # beim ersten Login geaendert werden.
        must_change_password=1,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="users", record_id=user.id, action="CREATE")
    db.commit()
    db.refresh(user)
    return user


def _hash_invite_token(token: str) -> str:
    """sha256-Hex des Einladungs-Tokens — nur der Hash wird gespeichert."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


_INVITE_TTL_DAYS = 7


def _invite_link_for(request: Request, token: str) -> str:
    """Baut den Einladungslink aus der OEFFENTLICHEN Origin. Bevorzugt IMMER
    das vertrauenswuerdige config.public_base_url (siehe _trusted_public_base_url).

    Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): der fruehere Fallback las
    X-Forwarded-Host/-Proto UNBEDINGT (kein trusted_proxy_count-Check) --
    exakt dieselbe Schwaeche wie der urspruengliche AUTH-03-Fund (Client-
    kontrollierbare Header ohne konfigurierten Reverse-Proxy). Fallback jetzt
    identisch zu _reset_link_for: reines request.base_url (respektiert KEINE
    Forwarded-Header), damit ein Angreifer den in der Einladungs-E-Mail
    versendeten Link nicht auf eine fremde Domain umleiten kann, solange
    public_base_url nicht konfiguriert ist."""
    trusted = _trusted_public_base_url()
    base = trusted if trusted is not None else str(request.base_url).rstrip("/")
    return f"{base}/app/5eyes_v2.html?invite={token}"


@users_router.post("/invite", response_model=InviteResponse, status_code=201)
def invite_user(
    body: InviteCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """E1 (2026-06-14): Mitarbeiter-Onboarding per Einladungslink.

    Legt einen Account OHNE nutzbares Passwort an (Mitarbeiter setzt es selbst
    via Token). Tenant wird vom anlegenden Admin geerbt -> harte Firmen-Trennung.
    Der Klartext-Token wird NUR EINMAL zurueckgegeben (gespeichert wird nur der Hash).
    Nach Annahme erzwingt das 2FA-Hard-Gate beim ersten Login das Enrollment.
    """
    existing = db.query(User).filter(
        User.username == body.username,
        User.deleted_at.is_(None),
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Benutzername bereits vergeben")
    now = _now()
    tenant_id = getattr(current_user, "tenant_id", None)
    assert_within_quota(db, tenant_id, "users")
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=_INVITE_TTL_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"
    user = User(
        id=new_uuid(),
        username=body.username,
        # Kein nutzbares Passwort bis zur Annahme — zufaelliger, nie kommunizierter Hash.
        password_hash=hash_password(secrets.token_urlsafe(32)),
        full_name=body.full_name,
        email=body.email,
        role=body.role,
        is_active=1,
        tenant_id=tenant_id,
        must_change_password=0,            # Mitarbeiter setzt das Passwort selbst
        invite_token_hash=_hash_invite_token(token),
        invite_expires_at=expires_at,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="users", record_id=user.id, action="INVITE")
    db.commit()
    db.refresh(user)
    # E-Mail-Versand (best effort, config-gated) — bei Fehlschlag/aus: Link-Copy.
    email_sent = send_invite_email(body.email, body.full_name, _invite_link_for(request, token))
    return InviteResponse(
        user_id=user.id, username=user.username,
        invite_token=token, invite_expires_at=expires_at, email_sent=email_sent,
    )


def _invite_guard_key(request: Request) -> str:
    """IP-basierter Guard-Key fuer die OEFFENTLICHEN Invite-Endpoints — drosselt
    Token-Enumeration / Brute-Force / DoS (Token ist 256-bit, aber Defense-in-depth)."""
    return "invite:" + _login_guard_key(request, "invite")


def _resolve_invite_guarded(db: Session, token: str, request: Request) -> User:
    """Wie _resolve_invite, aber mit IP-Rate-Limit: Lockout nach zu vielen
    ungueltigen/abgelaufenen Token-Versuchen von derselben Quelle (429)."""
    key = _invite_guard_key(request)
    decision = login_attempt_guard.check(key)
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail=decision.reason or "Zu viele Versuche. Bitte später erneut versuchen.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )
    try:
        user = _resolve_invite(db, token)
    except HTTPException as exc:
        if exc.status_code in (404, 410):
            login_attempt_guard.register_failure(key)
        raise
    login_attempt_guard.register_success(key)
    return user


@router.get("/invite/{token}", response_model=InvitePreview)
def invite_preview(token: str, request: Request, db: Session = Depends(get_db)):
    """Public: validiert den Token und liefert Anzeige-Infos fuer die Set-Passwort-Maske."""
    user = _resolve_invite_guarded(db, token, request)
    return InvitePreview(username=user.username, full_name=user.full_name)


@router.post("/invite/accept", response_model=TokenResponse)
def invite_accept(body: InviteAccept, request: Request, db: Session = Depends(get_db)):
    """Public: Mitarbeiter setzt sein Passwort per Token. Token wird verbraucht.
    Loggt direkt ein -> beim ersten Login erzwingt das 2FA-Gate das Enrollment."""
    user = _resolve_invite_guarded(db, body.token, request)
    user.password_hash = hash_password(body.password)
    user.invite_token_hash = None
    user.invite_expires_at = None
    user.must_change_password = 0
    user.updated_at = _now()
    log(db, user_id=user.id, user_name=user.full_name,
        table_name="users", record_id=user.id, action="INVITE_ACCEPT")
    db.commit()
    db.refresh(user)
    return _issue_token_response(user, db)


def _resolve_invite(db: Session, token: str) -> User:
    """Findet den User zum (gueltigen, nicht abgelaufenen) Invite-Token oder 404/410."""
    if not token or not str(token).strip():
        raise HTTPException(status_code=404, detail="Ungueltiger Einladungslink.")
    token_hash = _hash_invite_token(str(token).strip())
    user = db.query(User).filter(
        User.invite_token_hash == token_hash,
        User.deleted_at.is_(None),
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Einladungslink ungueltig oder bereits verwendet.")
    exp = getattr(user, "invite_expires_at", None)
    if exp and str(exp).strip() and _now() > str(exp).strip():
        raise HTTPException(status_code=410, detail="Einladungslink abgelaufen. Bitte neue Einladung anfordern.")
    return user


@users_router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    body: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    # E1 (2026-06-14): Mandanten-Trennung — Firmen-Admin darf nur User des eigenen
    # Tenants aendern (spiegelt die List-Sichtbarkeit). super_admin = alle. 404 statt
    # 403, damit die Existenz fremder User nicht geleakt wird.
    if getattr(current_user, "role", None) != "super_admin":
        utid = (getattr(current_user, "tenant_id", None) or "").strip()
        from config import settings as _settings
        strict = getattr(_settings, "strict_tenant_isolation", False)
        if utid:
            ttid = (getattr(user, "tenant_id", None) or "").strip()
            visible = (ttid == utid) or ((not strict) and ttid == "")
            if not visible:
                raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
        elif _effective_strict_tenant_isolation(_settings):
            # SEC-2 (2026-07-23): siehe _assert_user_visible_to -- selbe Ausnahme
            # fuer den Mutations-Pfad (nicht nur die Sichtbarkeits-Liste).
            ttid = (getattr(user, "tenant_id", None) or "").strip()
            if ttid:
                raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    if user_id == current_user.id:
        if body.is_active is not None and not body.is_active:
            raise HTTPException(status_code=400, detail="Eigenes Konto kann nicht deaktiviert werden")
        if body.role is not None:
            raise HTTPException(status_code=400, detail="Eigene Rolle kann nicht geändert werden")
    _ALLOWED_USER_UPDATE_FIELDS = {"full_name", "email", "role", "is_active"}
    for field, value in body.model_dump(exclude_none=True).items():
        if field not in _ALLOWED_USER_UPDATE_FIELDS:
            continue
        if field == "is_active":
            setattr(user, field, 1 if value else 0)
        else:
            setattr(user, field, value)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="users", record_id=user_id, action="UPDATE")
    db.commit()
    db.refresh(user)
    return user


@users_router.put("/{user_id}/password", response_model=UserResponse)
def reset_user_password(
    user_id: str,
    body: UserPasswordReset,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # E1 (2026-06-14): Self-Service (eigenes Passwort) ODER Admin-Reset (fremdes).
    is_self = (current_user.id == user_id)
    if not is_self and getattr(current_user, "role", None) not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Nur das eigene Passwort oder als Admin aenderbar")
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    # SEC (2026-07-23, unabhaengiges Audit): Mandanten-Trennung fuer den Admin-
    # Reset-Zweig. Ohne diesen Check konnte ein tenant-gebundener Firmen-Admin
    # (role='admin') das Passwort JEDES Users setzen -- auch von Usern eines
    # fremden Tenants -- weil hier (im Unterschied zu resend_invite/revoke_invite/
    # update_user) nie ein Tenant-Sichtbarkeits-Check stattfand. 404 statt 403,
    # damit die Existenz eines fremden Users nicht geleakt wird (siehe
    # _assert_user_visible_to).
    if not is_self:
        _assert_user_visible_to(current_user, user)
    # 2026-07-25 (Generalaudit): siehe change_password oben -- Self-Zweig
    # braucht dieselbe Ausnahme fuer den erzwungenen Erst-Passwortwechsel
    # (dieser Endpoint wird laut test_self_service_password_endpoint_
    # reachable_when_must_change GENAU DAFUER vom Frontend-Modal genutzt --
    # nahtloser Weiterzugriff erwartet). Der ADMIN-Reset-Zweig (not is_self)
    # bekommt die Ausnahme NICHT -- das ist genau der Account-Takeover-
    # Remediation-Fall, wo ein bereits gestohlenes Token des FREMDEN Users
    # sofort (nicht erst nach bis zu 8h) sterben muss.
    was_forced_change = bool(user.must_change_password)
    user.password_hash = hash_password(body.new_password)
    # Self -> Flag loeschen (erledigt). Admin-Reset -> Flag setzen (Mitarbeiter
    # muss das vom Admin gesetzte Passwort beim naechsten Login aendern).
    user.must_change_password = 0 if is_self else 1
    user.updated_at = _now()
    if not is_self or not was_forced_change:
        user.token_revoked_before = _now()
    log(
        db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        table_name="users",
        record_id=user_id,
        action="PASSWORD_RESET",
    )
    db.commit()
    db.refresh(user)
    return user


def _assert_user_visible_to(current_user: User, user: User) -> None:
    """Mandanten-Trennung: Firmen-Admin darf nur eigene-Tenant-User sehen/ändern.
    super_admin alle. 404 (nicht 403), damit fremde Existenz nicht leakt."""
    if getattr(current_user, "role", None) == "super_admin":
        return
    utid = (getattr(current_user, "tenant_id", None) or "").strip()
    from config import settings as _settings
    strict = getattr(_settings, "strict_tenant_isolation", False)
    if not utid:
        # SEC-2 (2026-07-23): Ein tenant-loser Firmen-Admin sah bisher IMMER
        # alle User (auch fremder Tenants) -- unrestricted statt restricted.
        # Fix nur im effektiv strikten/Multi-Tenant-Kontext (_effective_strict_
        # tenant_isolation, Tier2/Shared-Cloud): dort ist ein tenant-loser Admin
        # ein Konfigurationsfehler und darf NICHT global sichtbar sein. Tier1/
        # Single-Tenant-BC (die ueberwiegende Mehrheit) bleibt unveraendert
        # (kein tenant_id gesetzt = alte Behavior), da dort tenant-lose Admins
        # das gewollte Legacy-Setup sind.
        if _effective_strict_tenant_isolation(_settings):
            ttid = (getattr(user, "tenant_id", None) or "").strip()
            if ttid:
                raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
        return
    ttid = (getattr(user, "tenant_id", None) or "").strip()
    visible = (ttid == utid) or ((not strict) and ttid == "")
    if not visible:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")


@users_router.post("/{user_id}/invite/resend", response_model=InviteResponse)
def resend_invite(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """E1 (2026-06-14): Einladung erneut senden — neuer Token + Ablauf für einen
    noch NICHT aktivierten Account (z.B. Link verloren / abgelaufen)."""
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    _assert_user_visible_to(current_user, user)
    if not getattr(user, "invite_token_hash", None):
        raise HTTPException(status_code=409, detail="Konto ist bereits aktiviert — keine offene Einladung.")
    # E1 (2026-06-14, #107): Resend-Anti-Abuse — pro Ziel-User drosseln (wiederverwendeter
    # Guard). Verhindert Mail-Spam / Token-Rotation-Flut bei wiederholtem Klick.
    _resend_key = f"invite-resend:{user_id}"
    _resend_decision = login_attempt_guard.check(_resend_key)
    if not _resend_decision.allowed:
        raise HTTPException(
            status_code=429,
            detail=_resend_decision.reason or "Zu viele Einladungs-Versände. Bitte später erneut.",
            headers={"Retry-After": str(_resend_decision.retry_after_seconds)},
        )
    login_attempt_guard.register_failure(_resend_key)
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=_INVITE_TTL_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"
    user.invite_token_hash = _hash_invite_token(token)
    user.invite_expires_at = expires_at
    user.updated_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="users", record_id=user.id, action="INVITE_RESEND")
    db.commit()
    db.refresh(user)
    email_sent = send_invite_email(getattr(user, "email", None), user.full_name, _invite_link_for(request, token))
    return InviteResponse(
        user_id=user.id, username=user.username,
        invite_token=token, invite_expires_at=expires_at, email_sent=email_sent,
    )


@users_router.delete("/{user_id}/invite", status_code=200)
def revoke_invite(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """E1 (2026-06-14): Offene Einladung zurückziehen. Der noch nie aktivierte
    Account wird soft-gelöscht (Link tot, kein verwaister Account)."""
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    _assert_user_visible_to(current_user, user)
    if not getattr(user, "invite_token_hash", None):
        raise HTTPException(status_code=409, detail="Konto ist bereits aktiviert — Einladung kann nicht zurückgezogen werden.")
    user.invite_token_hash = None
    user.invite_expires_at = None
    user.is_active = 0
    user.deleted_at = _now()
    user.updated_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="users", record_id=user.id, action="INVITE_REVOKE")
    db.commit()
    return {"revoked": True, "user_id": user_id}


@users_router.get("/{user_id}/adviser-registration", response_model=AdviserRegistrationResponse)
def get_adviser_registration(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ("admin", "super_admin") and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Nur eigene Beraterregistrierung einsehbar")
    # SEC (2026-07-23, unabhaengiges Audit): Mandanten-Trennung -- ohne diesen
    # Check konnte ein tenant-gebundener Firmen-Admin die FINMA-Registrierungs-
    # daten (Registernummer, Ombudsstelle) eines Users eines FREMDEN Tenants
    # einsehen, weil hier nie ein Tenant-Sichtbarkeits-Check stattfand.
    if current_user.id != user_id:
        target_user = db.query(User).filter(
            User.id == user_id, User.deleted_at.is_(None),
        ).first()
        if target_user is not None:
            _assert_user_visible_to(current_user, target_user)
    reg = db.query(AdviserRegistration).filter(
        AdviserRegistration.user_id == user_id,
        AdviserRegistration.deleted_at.is_(None)
    ).first()
    if not reg:
        raise HTTPException(status_code=404, detail="Keine Beraterregistrierung gefunden")
    return reg


@users_router.put("/{user_id}/adviser-registration", response_model=AdviserRegistrationResponse)
def upsert_adviser_registration(
    user_id: str,
    body: AdviserRegistrationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    # SEC (2026-07-23, unabhaengiges Audit): Mandanten-Trennung -- ohne diesen
    # Check konnte ein tenant-gebundener Firmen-Admin die FINMA-Registrierungs-
    # daten eines Users eines FREMDEN Tenants anlegen/ueberschreiben, weil hier
    # (require_admin allein) nie ein Tenant-Sichtbarkeits-Check stattfand.
    target_user = db.query(User).filter(
        User.id == user_id, User.deleted_at.is_(None),
    ).first()
    if target_user is not None:
        _assert_user_visible_to(current_user, target_user)
    now = _now()
    reg = db.query(AdviserRegistration).filter(
        AdviserRegistration.user_id == user_id,
        AdviserRegistration.deleted_at.is_(None)
    ).first()
    if reg:
        for field, value in body.model_dump(exclude_none=True).items():
            setattr(reg, field, value)
        reg.updated_at = now
        action = "UPDATE"
    else:
        reg = AdviserRegistration(
            id=new_uuid(), user_id=user_id,
            created_at=now, updated_at=now, **body.model_dump()
        )
        db.add(reg)
        action = "CREATE"
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="adviser_registrations", record_id=reg.id, action=action)
    db.commit()
    db.refresh(reg)
    return reg
