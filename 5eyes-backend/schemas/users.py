from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, Literal
from schemas.common import BaseResponse


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str
    email: Optional[EmailStr] = None
    role: Literal["admin", "advisor", "readonly", "portfolio_management"] = "advisor"

    @field_validator('username', 'full_name')
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError('value must not be empty')
        return normalized

    @field_validator('password')
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 10:
            raise ValueError('password must be at least 10 characters long')
        return value


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[Literal["admin", "advisor", "readonly", "portfolio_management"]] = None
    is_active: Optional[bool] = None


class UserResponse(BaseResponse):
    id: str
    username: str
    full_name: str
    email: Optional[str]
    role: str
    is_active: int
    last_login_at: Optional[str]
    created_at: str
    # E1 (2026-06-14): Frontend erzwingt Passwortwechsel beim ersten Login.
    must_change_password: int = 0
    totp_enabled: int = 0
    # E1 (2026-06-14): offene Einladung (Account noch nicht aktiviert) — Team-UI.
    invite_pending: bool = False

    @field_validator('must_change_password', 'totp_enabled', mode='before')
    @classmethod
    def normalize_legacy_nullable_security_flags(cls, value):
        """Legacy users predate these columns and may still contain NULL."""
        return 0 if value is None else value


class AdviserRegistrationCreate(BaseModel):
    register_body: str = "FINMA Beraterregister"
    register_number: Optional[str] = None
    register_status: str = "Aktiv"
    registered_at: Optional[str] = None
    register_valid_until: Optional[str] = None
    ombudsman_body: Optional[str] = None
    ombudsman_affiliated_since: Optional[str] = None
    ombudsman_membership_number: Optional[str] = None
    qualifications_json: Optional[str] = None
    notes: Optional[str] = None


class AdviserRegistrationResponse(BaseResponse):
    id: str
    user_id: str
    register_body: str
    register_number: Optional[str]
    register_status: str
    registered_at: Optional[str]
    register_valid_until: Optional[str]
    ombudsman_body: Optional[str]
    ombudsman_affiliated_since: Optional[str]
    ombudsman_membership_number: Optional[str]
    notes: Optional[str]
    created_at: str


class BootstrapStatusResponse(BaseModel):
    setup_required: bool
    can_create_admin: bool


class BootstrapAdminRequest(BaseModel):
    username: str
    password: str
    full_name: str
    email: Optional[str] = None
    # 2026-08-01 (Onboarding, Entscheid Auftraggeber): Firmenidentitaet/
    # -Standort werden bei der Ersteinrichtung erfasst, weil bis dahin die
    # Default-Tenant-Zeile ("Default Tenant", NULL-Jurisdiktion) sonst
    # dauerhaft ungepflegt bliebe -- siehe routers/auth.py::bootstrap_admin.
    # Beide optional (Ersteinrichtung darf nicht daran scheitern, dass ein
    # Feld vergessen wurde; Nachpflege ist ueber PUT /tenants/me moeglich).
    company_name: Optional[str] = None
    home_jurisdiction: Optional[str] = None

    @field_validator('username', 'full_name')
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError('value must not be empty')
        return normalized

    @field_validator('password')
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 10:
            raise ValueError('password must be at least 10 characters long')
        return value


class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: str | None = None   # E1: 2FA-Code, falls fuer den User aktiv


class UserPasswordReset(BaseModel):
    new_password: str

    @field_validator('new_password')
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 10:
            raise ValueError('password must be at least 10 characters long')
        return value


class InviteCreate(BaseModel):
    """Admin legt einen Mitarbeiter-Account OHNE Passwort an; der Mitarbeiter
    setzt es selbst per Einladungslink (E1, 2026-06-14)."""
    username: str
    full_name: str
    email: Optional[EmailStr] = None
    role: Literal["admin", "advisor", "readonly", "portfolio_management"] = "advisor"

    @field_validator('username', 'full_name')
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError('value must not be empty')
        return normalized


class InviteResponse(BaseModel):
    user_id: str
    username: str
    invite_token: str          # nur EINMALIG im Klartext (danach nur Hash gespeichert)
    invite_expires_at: str
    email_sent: bool = False   # True, wenn die Einladung per E-Mail verschickt wurde


class InvitePreview(BaseModel):
    username: str
    full_name: str


class InviteAccept(BaseModel):
    token: str
    password: str

    @field_validator('password')
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 10:
            raise ValueError('password must be at least 10 characters long')
        return value


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
