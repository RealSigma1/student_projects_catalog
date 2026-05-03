from typing import Literal, Optional

from pydantic import BaseModel, Field, validator

from .config import ALLOWED_PROFILE_PHOTO_TYPES, EMAIL_RE, USERNAME_RE
from .utils import normalize_text


MAX_ROLE_LENGTH = 40


def validate_role_value(value: Optional[str], *, required: bool) -> Optional[str]:
    cleaned = normalize_text(value)
    if not cleaned:
        if required:
            raise ValueError("Нужно указать роль.")
        return None
    if len(cleaned) > MAX_ROLE_LENGTH:
        raise ValueError(f"Роль должна быть короткой: не длиннее {MAX_ROLE_LENGTH} символов.")
    return cleaned


class UserRegister(BaseModel):
    username: str
    email: str
    password: str
    full_name: Optional[str] = None

    @validator("username")
    def validate_username(cls, value: str) -> str:
        cleaned = value.strip()
        if not USERNAME_RE.fullmatch(cleaned):
            raise ValueError("Логин должен содержать от 3 до 32 символов: буквы, цифры, точки, дефисы или подчёркивания.")
        return cleaned

    @validator("email")
    def validate_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not EMAIL_RE.fullmatch(cleaned):
            raise ValueError("Некорректный email.")
        return cleaned

    @validator("password")
    def validate_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Пароль должен содержать минимум 8 символов.")
        if len(value) > 72:
            raise ValueError("Пароль не должен превышать 72 символа.")
        return value

    @validator("full_name")
    def normalize_full_name(cls, value: Optional[str]) -> Optional[str]:
        return normalize_text(value)


class UserLogin(BaseModel):
    login: str
    password: str

    @validator("login")
    def normalize_login(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Логин или email обязателен.")
        return cleaned


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    bio: Optional[str] = None
    photo_url: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)

    @validator("full_name", "bio", "photo_url")
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return normalize_text(value)

    @validator("skills", "roles", "links", pre=True)
    def coerce_lists(cls, value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return [str(part).strip() for part in value if str(part).strip()]


class ProfilePhotoUpload(BaseModel):
    file_name: Optional[str] = None
    mime_type: str
    content_base64: str

    @validator("mime_type")
    def validate_mime_type(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in ALLOWED_PROFILE_PHOTO_TYPES:
            raise ValueError("Поддерживаются только изображения JPG, PNG, WEBP или GIF.")
        return cleaned

    @validator("content_base64")
    def validate_content(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Необходимо передать содержимое изображения.")
        return cleaned


class ProjectPayload(BaseModel):
    title: str
    description: str
    tags: list[str] = Field(default_factory=list)
    required_roles: list[str] = Field(default_factory=list)
    github_url: Optional[str] = None
    demo_url: Optional[str] = None
    contact_info: Optional[str] = None
    status: Literal["active", "archived"] = "active"
    applications_open: bool = True

    @validator("title", "description")
    def require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Поле обязательно.")
        return cleaned

    @validator("github_url", "demo_url", "contact_info")
    def normalize_links(cls, value: Optional[str]) -> Optional[str]:
        return normalize_text(value)

    @validator("tags", "required_roles", pre=True)
    def clean_lists(cls, value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return [str(part).strip() for part in value if str(part).strip()]


class ApplicationCreate(BaseModel):
    message: str

    @validator("message")
    def require_message(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 10:
            raise ValueError("Текст отклика должен содержать минимум 10 символов.")
        return cleaned


class ApplicationStatusUpdate(BaseModel):
    status: Literal["new", "accepted", "rejected", "removed"]
    assigned_role: Optional[str] = None

    @validator("assigned_role")
    def normalize_assigned_role(cls, value: Optional[str]) -> Optional[str]:
        return validate_role_value(value, required=False)


class ApplicationRoleRequest(BaseModel):
    requested_role: str

    @validator("requested_role")
    def require_requested_role(cls, value: str) -> str:
        return validate_role_value(value, required=True)


class ApplicationRoleRequestDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    assigned_role: Optional[str] = None

    @validator("assigned_role")
    def normalize_decision_role(cls, value: Optional[str]) -> Optional[str]:
        return validate_role_value(value, required=False)
