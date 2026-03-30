from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database import get_db
from models.clients import Client
from models.mandates import Mandate
from models.users import User
from config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


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
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if user is None or not user.is_active:
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
