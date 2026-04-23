from typing import Literal, Optional

from pydantic import BaseModel, Field, validator

from .config import ALLOWED_PROFILE_PHOTO_TYPES, EMAIL_RE, USERNAME_RE
from .utils import normalize_text


class UserRegister(BaseModel):
    username: str
    email: str
    password: str
    full_name: Optional[str] = None

    @validator("username")
    def validate_username(cls, value: str) -> str:
        cleaned = value.strip()
        if not USERNAME_RE.fullmatch(cleaned):
            raise ValueError("Username must be 3-32 chars and use only letters, digits, dots, dashes or underscores.")
        return cleaned

    @validator("email")
    def validate_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not EMAIL_RE.fullmatch(cleaned):
            raise ValueError("Invalid email address.")
        return cleaned

    @validator("password")
    def validate_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must contain at least 8 characters.")
        if len(value) > 72:
            raise ValueError("Password must not exceed 72 characters.")
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
            raise ValueError("Login is required.")
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
            raise ValueError("Only JPG, PNG, WEBP or GIF images are supported.")
        return cleaned

    @validator("content_base64")
    def validate_content(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Image content is required.")
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

    @validator("title", "description")
    def require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field is required.")
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
            raise ValueError("Application message must be at least 10 characters long.")
        return cleaned


class ApplicationStatusUpdate(BaseModel):
    status: Literal["new", "accepted", "rejected"]
