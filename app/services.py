from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from .config import BASE_DIR, PROFILE_PHOTOS_DIR
from .models import NotificationModel, ProjectModel, UserModel
from .utils import utc_now_iso


def can_view_project(project: ProjectModel, current_user: Optional[UserModel]) -> bool:
    if project.status == "active":
        return True
    return bool(current_user and current_user.id == project.owner_id)


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
