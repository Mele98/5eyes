from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, Literal
from schemas.common import BaseResponse


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str
    email: Optional[str] = None
    role: Literal["admin", "advisor", "readonly"] = "advisor"

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
    email: Optional[str] = None
    role: Optional[Literal["admin", "advisor", "readonly"]] = None
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


class UserPasswordReset(BaseModel):
    new_password: str

    @field_validator('new_password')
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 10:
            raise ValueError('password must be at least 10 characters long')
        return value


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
