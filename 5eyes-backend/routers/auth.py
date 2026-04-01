import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from database import get_db, new_uuid
from models.users import User, AdviserRegistration
from schemas.users import (
    AdviserRegistrationCreate, AdviserRegistrationResponse, BootstrapAdminRequest,
    BootstrapStatusResponse, LoginRequest, TokenResponse, UserCreate, UserPasswordReset,
    UserUpdate, UserResponse,
)
from services.auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, require_admin
)
from services.login_guard import login_attempt_guard
from services.audit import log

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


def _issue_token_response(user: User) -> TokenResponse:
    token = create_access_token({"sub": user.id})
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))

# ── Auth ───────────────────────────────────────────────────────────────────────


@router.get('/bootstrap-status', response_model=BootstrapStatusResponse)
def bootstrap_status(db: Session = Depends(get_db)):
    required = _bootstrap_required(db)
    return BootstrapStatusResponse(setup_required=required, can_create_admin=required)


@router.post('/bootstrap-admin', response_model=TokenResponse, status_code=201)
def bootstrap_admin(body: BootstrapAdminRequest, db: Session = Depends(get_db)):
    if not _bootstrap_required(db):
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
    db.commit()
    db.refresh(admin)
    logger.info('Bootstrap admin created | username=%s', admin.username)
    return _issue_token_response(admin)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    decision = login_attempt_guard.check(body.username)
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
        failure = login_attempt_guard.register_failure(body.username)
        logger.warning(
            "Login failed | username=%s request_id=%s retry_after=%s",
            body.username,
            getattr(request.state, 'request_id', 'n/a'),
            failure.retry_after_seconds,
        )
        headers = {"Retry-After": str(failure.retry_after_seconds)} if failure.retry_after_seconds else None
        raise HTTPException(status_code=401, detail="Benutzername oder Passwort falsch", headers=headers)
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Konto deaktiviert")

    login_attempt_guard.register_success(body.username)
    user.last_login_at = _now()
    db.commit()
    db.refresh(user)

    log(db, user_id=user.id, user_name=user.full_name,
        table_name="users", record_id=user.id, action="LOGIN")
    db.commit()

    return _issue_token_response(user)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/logout")
def logout(current_user: User = Depends(get_current_user)):
    return {"message": "Erfolgreich abgemeldet"}


# ── Users ──────────────────────────────────────────────────────────────────────

@users_router.get("", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    return db.query(User).filter(User.deleted_at.is_(None)).all()


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
    user = User(
        id=new_uuid(),
        username=body.username,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        email=body.email,
        role=body.role,
        is_active=1,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="users", record_id=user.id, action="CREATE")
    db.commit()
    db.refresh(user)
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
    if user_id == current_user.id:
        if body.is_active is not None and not body.is_active:
            raise HTTPException(status_code=400, detail="Eigenes Konto kann nicht deaktiviert werden")
        if body.role is not None:
            raise HTTPException(status_code=400, detail="Eigene Rolle kann nicht geändert werden")
    for field, value in body.model_dump(exclude_none=True).items():
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
    current_user: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    user.password_hash = hash_password(body.new_password)
    user.updated_at = _now()
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


@users_router.get("/{user_id}/adviser-registration", response_model=AdviserRegistrationResponse)
def get_adviser_registration(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin" and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Nur eigene Beraterregistrierung einsehbar")
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
