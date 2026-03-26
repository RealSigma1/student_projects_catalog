import base64
import bcrypt
import binascii
import hashlib
import hmac
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, or_
from sqlalchemy.orm import Session, declarative_base, joinedload, relationship, sessionmaker


BASE_DIR = Path(__file__).resolve().parent


def load_env_file() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env_file()

APP_DATA_DIR = Path(os.getenv("APP_DATA_DIR", str(BASE_DIR))).resolve()
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(APP_DATA_DIR / "projects.db"))).resolve()
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", str(APP_DATA_DIR / "media"))).resolve()
PROFILE_PHOTOS_DIR = MEDIA_DIR / "profile_photos"
PROFILE_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

SECRET_KEY = os.getenv("APP_SECRET", "change-me-in-env")
ACCESS_TOKEN_TTL_HOURS = int(os.getenv("ACCESS_TOKEN_TTL_HOURS", "72"))
MAX_PROFILE_PHOTO_BYTES = int(os.getenv("MAX_PROFILE_PHOTO_BYTES", str(5 * 1024 * 1024)))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")
ALLOWED_PROFILE_PHOTO_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def split_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def join_csv(values: list[str]) -> str:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = value.strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    return ",".join(cleaned)


def normalize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def ensure_database_schema() -> None:
    if not DATABASE_PATH.exists():
        return

    conn = sqlite3.connect(DATABASE_PATH)
    try:
        cursor = conn.cursor()
        tables = {row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        now = utc_now_iso()

        if "users" in tables:
            user_columns = {row[1] for row in cursor.execute("PRAGMA table_info(users)")}
            if {"id", "username", "hashed_password"} - user_columns:
                backup_path = DATABASE_PATH.with_name(f"{DATABASE_PATH.stem}_legacy_backup.db")
                conn.close()
                DATABASE_PATH.replace(backup_path)
                return
            for column_name in ("email", "full_name", "bio", "skills", "roles", "links", "photo_url", "created_at"):
                if column_name not in user_columns:
                    cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} TEXT")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users(email)")
            cursor.execute(
                "UPDATE users SET created_at = ? WHERE created_at IS NULL OR TRIM(created_at) = ''",
                (now,),
            )

        if "projects" in tables:
            project_columns = {row[1] for row in cursor.execute("PRAGMA table_info(projects)")}
            if {"id", "title", "description", "tags", "owner_id"} - project_columns:
                backup_path = DATABASE_PATH.with_name(f"{DATABASE_PATH.stem}_legacy_backup.db")
                conn.close()
                DATABASE_PATH.replace(backup_path)
                return
            additions = {
                "required_roles": "TEXT",
                "contact_info": "TEXT",
                "status": "TEXT",
                "created_at": "TEXT",
                "updated_at": "TEXT",
            }
            for column_name, column_type in additions.items():
                if column_name not in project_columns:
                    cursor.execute(f"ALTER TABLE projects ADD COLUMN {column_name} {column_type}")
            cursor.execute("UPDATE projects SET status = 'active' WHERE status IS NULL OR TRIM(status) = ''")
            cursor.execute(
                "UPDATE projects SET created_at = ? WHERE created_at IS NULL OR TRIM(created_at) = ''",
                (now,),
            )
            cursor.execute(
                "UPDATE projects SET updated_at = created_at WHERE updated_at IS NULL OR TRIM(updated_at) = ''"
            )

        if "notifications" in tables:
            notification_columns = {row[1] for row in cursor.execute("PRAGMA table_info(notifications)")}
            additions = {
                "user_id": "INTEGER",
                "type": "TEXT",
                "title": "TEXT",
                "message": "TEXT",
                "is_read": "INTEGER",
                "related_project_id": "INTEGER",
                "related_application_id": "INTEGER",
                "created_at": "TEXT",
            }
            for column_name, column_type in additions.items():
                if column_name not in notification_columns:
                    cursor.execute(f"ALTER TABLE notifications ADD COLUMN {column_name} {column_type}")
            cursor.execute("UPDATE notifications SET is_read = 0 WHERE is_read IS NULL")
            cursor.execute(
                "UPDATE notifications SET created_at = ? WHERE created_at IS NULL OR TRIM(created_at) = ''",
                (now,),
            )

        conn.commit()
    finally:
        conn.close()


ensure_database_schema()

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    bio = Column(Text)
    skills = Column(Text, default="")
    roles = Column(Text, default="")
    links = Column(Text, default="")
    photo_url = Column(Text)
    created_at = Column(String, default=utc_now_iso, nullable=False)

    projects = relationship("ProjectModel", back_populates="owner", cascade="all, delete-orphan")
    applications = relationship("ApplicationModel", back_populates="applicant", cascade="all, delete-orphan")
    notifications = relationship("NotificationModel", back_populates="user", cascade="all, delete-orphan")


class ProjectModel(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    description = Column(Text, nullable=False)
    tags = Column(Text, default="")
    required_roles = Column(Text, default="")
    github_url = Column(String)
    demo_url = Column(String)
    contact_info = Column(Text)
    status = Column(String, default="active", nullable=False)
    created_at = Column(String, default=utc_now_iso, nullable=False)
    updated_at = Column(String, default=utc_now_iso, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    owner = relationship("UserModel", back_populates="projects")
    applications = relationship("ApplicationModel", back_populates="project", cascade="all, delete-orphan")


class ApplicationModel(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("project_id", "applicant_id", name="uq_project_applicant"),)

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    applicant_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String, default="new", nullable=False)
    created_at = Column(String, default=utc_now_iso, nullable=False)

    project = relationship("ProjectModel", back_populates="applications")
    applicant = relationship("UserModel", back_populates="applications")


class NotificationModel(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)
    related_project_id = Column(Integer)
    related_application_id = Column(Integer)
    created_at = Column(String, default=utc_now_iso, nullable=False)

    user = relationship("UserModel", back_populates="notifications")


Base.metadata.create_all(bind=engine)


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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def create_access_token(user: UserModel) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_TTL_HOURS)).timestamp()),
    }
    encoded_header = b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = hmac.new(SECRET_KEY.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    return f"{signing_input}.{b64url_encode(signature)}"


def decode_access_token(token: str) -> dict:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid authentication token.") from exc

    signing_input = f"{encoded_header}.{encoded_payload}"
    expected_signature = hmac.new(SECRET_KEY.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    received_signature = b64url_decode(encoded_signature)
    if not hmac.compare_digest(expected_signature, received_signature):
        raise HTTPException(status_code=401, detail="Invalid authentication token.")

    payload = json.loads(b64url_decode(encoded_payload).decode("utf-8"))
    if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
        raise HTTPException(status_code=401, detail="Authentication token has expired.")
    return payload


def set_auth_cookie(response: Response, user: UserModel) -> None:
    token = create_access_token(user)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=ACCESS_TOKEN_TTL_HOURS * 3600,
        secure=COOKIE_SECURE,
    )


def get_current_user(access_token: Optional[str] = Cookie(default=None), db: Session = Depends(get_db)) -> Optional[UserModel]:
    if not access_token:
        return None
    try:
        payload = decode_access_token(access_token)
    except HTTPException:
        return None
    return db.query(UserModel).filter(UserModel.id == int(payload["sub"])).first()


def require_current_user(current_user: Optional[UserModel] = Depends(get_current_user)) -> UserModel:
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return current_user


def serialize_user(user: UserModel, include_email: bool = False) -> dict:
    data = {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "bio": user.bio,
        "photo_url": user.photo_url,
        "skills": split_csv(user.skills),
        "roles": split_csv(user.roles),
        "links": split_csv(user.links),
        "created_at": user.created_at,
    }
    if include_email:
        data["email"] = user.email
    return data


def serialize_project(project: ProjectModel, current_user: Optional[UserModel] = None) -> dict:
    applicant_ids = {application.applicant_id for application in project.applications}
    is_owner = bool(current_user and current_user.id == project.owner_id)
    has_applied = bool(current_user and current_user.id in applicant_ids)
    return {
        "id": project.id,
        "title": project.title,
        "description": project.description,
        "tags": split_csv(project.tags),
        "required_roles": split_csv(project.required_roles),
        "github_url": project.github_url,
        "demo_url": project.demo_url,
        "contact_info": project.contact_info,
        "status": project.status,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "owner_id": project.owner_id,
        "owner_username": project.owner.username if project.owner else None,
        "owner_full_name": project.owner.full_name if project.owner else None,
        "applications_count": len(project.applications),
        "is_owner": is_owner,
        "has_applied": has_applied,
        "can_apply": bool(current_user and not is_owner and not has_applied and project.status == "active"),
    }


def serialize_application(application: ApplicationModel) -> dict:
    return {
        "id": application.id,
        "project_id": application.project_id,
        "message": application.message,
        "status": application.status,
        "created_at": application.created_at,
        "applicant_id": application.applicant_id,
        "applicant_username": application.applicant.username if application.applicant else None,
        "applicant_full_name": application.applicant.full_name if application.applicant else None,
        "applicant_roles": split_csv(application.applicant.roles if application.applicant else ""),
        "project_title": application.project.title if application.project else None,
    }


def serialize_notification(notification: NotificationModel) -> dict:
    action_url = "/profile/me"
    if notification.related_project_id:
        action_url = f"/project/{notification.related_project_id}"
    return {
        "id": notification.id,
        "type": notification.type,
        "title": notification.title,
        "message": notification.message,
        "is_read": bool(notification.is_read),
        "created_at": notification.created_at,
        "related_project_id": notification.related_project_id,
        "related_application_id": notification.related_application_id,
        "action_url": action_url,
    }


def create_notification(
    db: Session,
    *,
    user_id: int,
    type: str,
    title: str,
    message: str,
    related_project_id: Optional[int] = None,
    related_application_id: Optional[int] = None,
) -> NotificationModel:
    notification = NotificationModel(
        user_id=user_id,
        type=type,
        title=title,
        message=message,
        is_read=False,
        related_project_id=related_project_id,
        related_application_id=related_application_id,
        created_at=utc_now_iso(),
    )
    db.add(notification)
    db.flush()
    return notification


def read_static_file(filename: str) -> str:
    return (BASE_DIR / "static" / filename).read_text(encoding="utf-8")


def remove_local_profile_photo(photo_url: Optional[str]) -> None:
    prefix = "/media/profile_photos/"
    if not photo_url or not photo_url.startswith(prefix):
        return
    file_name = photo_url[len(prefix):].strip()
    if not file_name:
        return
    target_path = (PROFILE_PHOTOS_DIR / file_name).resolve()
    if PROFILE_PHOTOS_DIR.resolve() not in target_path.parents:
        return
    if target_path.exists() and target_path.is_file():
        target_path.unlink()


app = FastAPI(title="Collaborative Platform for Student Projects")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    messages = []
    for error in exc.errors():
        field = " -> ".join(str(item) for item in error.get("loc", [])[1:])
        message = error.get("msg", "Validation error")
        messages.append(f"{field}: {message}" if field else message)
    return JSONResponse(status_code=422, content={"detail": "; ".join(messages)})


@app.get("/api/health")
def healthcheck() -> dict:
    return {"status": "ok"}


@app.post("/api/auth/register")
def register(user: UserRegister, db: Session = Depends(get_db)) -> dict:
    if db.query(UserModel).filter(UserModel.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username is already taken.")
    if db.query(UserModel).filter(UserModel.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email is already registered.")

    db_user = UserModel(
        username=user.username,
        email=user.email,
        hashed_password=get_password_hash(user.password),
        full_name=user.full_name,
        created_at=utc_now_iso(),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return {"message": "Registration successful.", "user": serialize_user(db_user, include_email=True)}


@app.post("/api/auth/login")
def login(user: UserLogin, response: Response, db: Session = Depends(get_db)) -> dict:
    login_value = user.login.strip()
    db_user = db.query(UserModel).filter(
        or_(UserModel.username == login_value, UserModel.email == login_value.lower())
    ).first()
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid login or password.")

    set_auth_cookie(response, db_user)
    return {"message": "Login successful.", "user": serialize_user(db_user, include_email=True)}


@app.post("/api/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie("access_token")
    return {"message": "Logout successful."}


@app.get("/api/me")
def get_me(current_user: UserModel = Depends(require_current_user)) -> dict:
    return serialize_user(current_user, include_email=True)


@app.get("/api/notifications")
def list_notifications(
    limit: int = Query(default=12, ge=1, le=100),
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    notifications = (
        db.query(NotificationModel)
        .filter(NotificationModel.user_id == current_user.id)
        .order_by(NotificationModel.created_at.desc(), NotificationModel.id.desc())
        .limit(limit)
        .all()
    )
    unread_count = (
        db.query(NotificationModel)
        .filter(NotificationModel.user_id == current_user.id, NotificationModel.is_read.is_(False))
        .count()
    )
    return {
        "items": [serialize_notification(notification) for notification in notifications],
        "unread_count": unread_count,
    }


@app.post("/api/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    notification = (
        db.query(NotificationModel)
        .filter(NotificationModel.id == notification_id, NotificationModel.user_id == current_user.id)
        .first()
    )
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found.")

    if not notification.is_read:
        notification.is_read = True
        db.add(notification)
        db.commit()
        db.refresh(notification)

    return {"message": "Notification marked as read.", "notification": serialize_notification(notification)}


@app.get("/api/profile/me")
def get_my_profile(current_user: UserModel = Depends(require_current_user), db: Session = Depends(get_db)) -> dict:
    user = (
        db.query(UserModel)
        .options(
            joinedload(UserModel.projects).joinedload(ProjectModel.owner),
            joinedload(UserModel.projects).joinedload(ProjectModel.applications),
            joinedload(UserModel.applications).joinedload(ApplicationModel.project),
            joinedload(UserModel.applications).joinedload(ApplicationModel.applicant),
        )
        .filter(UserModel.id == current_user.id)
        .first()
    )
    projects = sorted(user.projects, key=lambda project: (project.created_at or "", project.id), reverse=True)
    applications = sorted(user.applications, key=lambda item: (item.created_at or "", item.id), reverse=True)
    return {
        "user": serialize_user(user, include_email=True),
        "is_current_user": True,
        "project_count": len(projects),
        "projects": [serialize_project(project, current_user=user) for project in projects],
        "applications": [serialize_application(application) for application in applications],
    }


@app.put("/api/profile/me")
def update_my_profile(
    payload: ProfileUpdate,
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    current_user.full_name = payload.full_name
    current_user.bio = payload.bio
    current_user.photo_url = payload.photo_url
    current_user.skills = join_csv(payload.skills)
    current_user.roles = join_csv(payload.roles)
    current_user.links = join_csv(payload.links)
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return {"message": "Profile updated.", "user": serialize_user(current_user, include_email=True)}


@app.post("/api/profile/me/photo")
def upload_my_profile_photo(
    payload: ProfilePhotoUpload,
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        raw_bytes = base64.b64decode(payload.content_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Invalid image payload.") from exc

    if len(raw_bytes) > MAX_PROFILE_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="Image must not exceed 5 MB.")

    extension = ALLOWED_PROFILE_PHOTO_TYPES[payload.mime_type]
    file_name = f"user_{current_user.id}_{uuid4().hex}{extension}"
    target_path = PROFILE_PHOTOS_DIR / file_name
    target_path.write_bytes(raw_bytes)

    previous_photo_url = current_user.photo_url
    current_user.photo_url = f"/media/profile_photos/{file_name}"
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    remove_local_profile_photo(previous_photo_url)
    return {
        "message": "Profile photo uploaded.",
        "photo_url": current_user.photo_url,
        "user": serialize_user(current_user, include_email=True),
    }


@app.get("/api/profile/{username}")
def get_public_profile(
    username: str,
    current_user: Optional[UserModel] = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    user = (
        db.query(UserModel)
        .options(
            joinedload(UserModel.projects).joinedload(ProjectModel.owner),
            joinedload(UserModel.projects).joinedload(ProjectModel.applications),
        )
        .filter(UserModel.username == username)
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    projects = sorted(user.projects, key=lambda project: (project.created_at or "", project.id), reverse=True)
    return {
        "user": serialize_user(user, include_email=bool(current_user and current_user.id == user.id)),
        "is_current_user": bool(current_user and current_user.id == user.id),
        "project_count": len(projects),
        "projects": [serialize_project(project, current_user=current_user) for project in projects],
    }


@app.get("/api/projects")
def list_projects(
    search: Optional[str] = Query(default=None),
    tags: Optional[str] = Query(default=None),
    roles: Optional[str] = Query(default=None),
    status_filter: Literal["all", "active", "archived"] = Query(default="active"),
    owner: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=6, ge=1, le=50),
    current_user: Optional[UserModel] = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(ProjectModel).options(joinedload(ProjectModel.owner), joinedload(ProjectModel.applications))

    if status_filter != "all":
        query = query.filter(ProjectModel.status == status_filter)
    if owner:
        query = query.join(ProjectModel.owner).filter(UserModel.username == owner)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                ProjectModel.title.ilike(term),
                ProjectModel.description.ilike(term),
                ProjectModel.tags.ilike(term),
                ProjectModel.required_roles.ilike(term),
            )
        )
    for tag in split_csv(tags):
        query = query.filter(ProjectModel.tags.ilike(f"%{tag}%"))
    for role in split_csv(roles):
        query = query.filter(ProjectModel.required_roles.ilike(f"%{role}%"))

    total = query.count()
    items = (
        query.order_by(ProjectModel.created_at.desc(), ProjectModel.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [serialize_project(project, current_user=current_user) for project in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@app.post("/api/projects")
def create_project(
    payload: ProjectPayload,
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    now = utc_now_iso()
    project = ProjectModel(
        title=payload.title,
        description=payload.description,
        tags=join_csv(payload.tags),
        required_roles=join_csv(payload.required_roles),
        github_url=payload.github_url,
        demo_url=payload.demo_url,
        contact_info=payload.contact_info,
        status=payload.status,
        created_at=now,
        updated_at=now,
        owner_id=current_user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    project = (
        db.query(ProjectModel)
        .options(joinedload(ProjectModel.owner), joinedload(ProjectModel.applications))
        .filter(ProjectModel.id == project.id)
        .first()
    )
    return {"message": "Project created.", "project": serialize_project(project, current_user=current_user)}


@app.get("/api/projects/{project_id}")
def get_project(
    project_id: int,
    current_user: Optional[UserModel] = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = (
        db.query(ProjectModel)
        .options(
            joinedload(ProjectModel.owner),
            joinedload(ProjectModel.applications).joinedload(ApplicationModel.applicant),
        )
        .filter(ProjectModel.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    applications = []
    if current_user and current_user.id == project.owner_id:
        applications = [serialize_application(application) for application in project.applications]

    current_user_application = None
    if current_user:
        for application in project.applications:
            if application.applicant_id == current_user.id:
                current_user_application = serialize_application(application)
                break

    return {
        "project": serialize_project(project, current_user=current_user),
        "applications": applications,
        "current_user_application": current_user_application,
    }


@app.put("/api/projects/{project_id}")
def update_project(
    project_id: int,
    payload: ProjectPayload,
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = (
        db.query(ProjectModel)
        .options(joinedload(ProjectModel.owner), joinedload(ProjectModel.applications))
        .filter(ProjectModel.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the project owner can edit this project.")

    project.title = payload.title
    project.description = payload.description
    project.tags = join_csv(payload.tags)
    project.required_roles = join_csv(payload.required_roles)
    project.github_url = payload.github_url
    project.demo_url = payload.demo_url
    project.contact_info = payload.contact_info
    project.status = payload.status
    project.updated_at = utc_now_iso()
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"message": "Project updated.", "project": serialize_project(project, current_user=current_user)}


@app.delete("/api/projects/{project_id}")
def delete_project(
    project_id: int,
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the project owner can delete this project.")
    db.delete(project)
    db.commit()
    return {"message": "Project deleted."}


@app.post("/api/projects/{project_id}/applications")
def create_application(
    project_id: int,
    payload: ApplicationCreate,
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = db.query(ProjectModel).options(joinedload(ProjectModel.owner)).filter(ProjectModel.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    if project.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot apply to your own project.")
    if project.status != "active":
        raise HTTPException(status_code=400, detail="Applications are closed for archived projects.")

    existing_application = (
        db.query(ApplicationModel)
        .filter(ApplicationModel.project_id == project_id, ApplicationModel.applicant_id == current_user.id)
        .first()
    )
    if existing_application:
        raise HTTPException(status_code=400, detail="You have already applied to this project.")

    application = ApplicationModel(
        project_id=project_id,
        applicant_id=current_user.id,
        message=payload.message,
        status="new",
        created_at=utc_now_iso(),
    )
    db.add(application)
    db.flush()
    applicant_name = current_user.full_name or current_user.username
    create_notification(
        db,
        user_id=project.owner_id,
        type="new_application",
        title="New application received",
        message=f"{applicant_name} responded to your project '{project.title}'.",
        related_project_id=project.id,
        related_application_id=application.id,
    )
    db.commit()
    db.refresh(application)
    application = (
        db.query(ApplicationModel)
        .options(joinedload(ApplicationModel.project), joinedload(ApplicationModel.applicant))
        .filter(ApplicationModel.id == application.id)
        .first()
    )
    return {"message": "Application submitted.", "application": serialize_application(application)}


@app.get("/api/projects/{project_id}/applications")
def list_project_applications(
    project_id: int,
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the project owner can view applications.")

    applications = (
        db.query(ApplicationModel)
        .options(joinedload(ApplicationModel.applicant), joinedload(ApplicationModel.project))
        .filter(ApplicationModel.project_id == project_id)
        .order_by(ApplicationModel.created_at.desc(), ApplicationModel.id.desc())
        .all()
    )
    return {"items": [serialize_application(application) for application in applications]}


@app.patch("/api/applications/{application_id}")
def update_application_status(
    application_id: int,
    payload: ApplicationStatusUpdate,
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    application = (
        db.query(ApplicationModel)
        .options(joinedload(ApplicationModel.project), joinedload(ApplicationModel.applicant))
        .filter(ApplicationModel.id == application_id)
        .first()
    )
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")
    if application.project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the project owner can update application status.")
    if application.status != "new":
        raise HTTPException(
            status_code=400,
            detail="This application has already been processed and its status cannot be changed again.",
        )

    application.status = payload.status
    db.add(application)
    status_text = "accepted" if payload.status == "accepted" else "rejected"
    create_notification(
        db,
        user_id=application.applicant_id,
        type="application_status",
        title="Application status updated",
        message=f"Your application to '{application.project.title}' was {status_text}.",
        related_project_id=application.project_id,
        related_application_id=application.id,
    )
    db.commit()
    db.refresh(application)
    return {"message": "Application status updated.", "application": serialize_application(application)}


@app.get("/api/applications/me")
def list_my_applications(
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    applications = (
        db.query(ApplicationModel)
        .options(joinedload(ApplicationModel.project), joinedload(ApplicationModel.applicant))
        .filter(ApplicationModel.applicant_id == current_user.id)
        .order_by(ApplicationModel.created_at.desc(), ApplicationModel.id.desc())
        .all()
    )
    return {"items": [serialize_application(application) for application in applications]}


@app.post("/register")
def register_compat(user: UserRegister, db: Session = Depends(get_db)) -> dict:
    return register(user, db)


@app.post("/login")
def login_compat(user: UserLogin, response: Response, db: Session = Depends(get_db)) -> dict:
    return login(user, response, db)


@app.post("/logout")
def logout_compat(response: Response) -> dict:
    return logout(response)


@app.get("/me")
def me_compat(current_user: UserModel = Depends(require_current_user)) -> dict:
    return get_me(current_user)


@app.get("/", response_class=HTMLResponse)
def read_root(current_user: Optional[UserModel] = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    return HTMLResponse(read_static_file("index.html"))


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return HTMLResponse(read_static_file("login.html"))


@app.get("/register", response_class=HTMLResponse)
def register_page():
    return HTMLResponse(read_static_file("register.html"))


@app.get("/profile/me", response_class=HTMLResponse)
def my_profile_page(current_user: Optional[UserModel] = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    return HTMLResponse(read_static_file("profile.html"))


@app.get("/profile/{username}", response_class=HTMLResponse)
def public_profile_page(username: str):
    return HTMLResponse(read_static_file("profile.html"))


@app.get("/project/{project_id}", response_class=HTMLResponse)
def project_page(project_id: int):
    return HTMLResponse(read_static_file("project.html"))


@app.get("/projects/new", response_class=HTMLResponse)
def create_project_page(current_user: Optional[UserModel] = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    return HTMLResponse(read_static_file("create_project.html"))
