import base64
import binascii
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, require_current_user
from ..config import ALLOWED_PROFILE_PHOTO_TYPES, MAX_PROFILE_PHOTO_BYTES, PROFILE_PHOTOS_DIR
from ..database import get_db
from ..models import ApplicationModel, ProjectModel, UserModel
from ..schemas import ProfilePhotoUpload, ProfileUpdate
from ..serializers import serialize_application, serialize_project, serialize_user
from ..services import remove_local_profile_photo
from ..utils import join_csv, project_sort_key


router = APIRouter()


@router.get("/api/profile/me")
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
    projects = sorted(user.projects, key=project_sort_key, reverse=True)
    applications = sorted(user.applications, key=lambda item: (item.created_at or "", item.id), reverse=True)
    return {
        "user": serialize_user(user, include_email=True),
        "is_current_user": True,
        "project_count": len(projects),
        "projects": [serialize_project(project, current_user=user) for project in projects],
        "applications": [serialize_application(application) for application in applications],
    }


@router.put("/api/profile/me")
def update_my_profile(
    payload: ProfileUpdate,
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    previous_photo_url = current_user.photo_url
    current_user.full_name = payload.full_name
    current_user.bio = payload.bio
    current_user.photo_url = payload.photo_url
    current_user.skills = join_csv(payload.skills)
    current_user.roles = join_csv(payload.roles)
    current_user.links = join_csv(payload.links)
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    if previous_photo_url != current_user.photo_url and not current_user.photo_url:
        remove_local_profile_photo(previous_photo_url)
    return {"message": "Профиль обновлён.", "user": serialize_user(current_user, include_email=True)}


@router.post("/api/profile/me/photo")
def upload_my_profile_photo(
    payload: ProfilePhotoUpload,
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        raw_bytes = base64.b64decode(payload.content_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Некорректные данные изображения.") from exc

    if len(raw_bytes) > MAX_PROFILE_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="Размер изображения не должен превышать 5 МБ.")

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
        "message": "Фото профиля загружено.",
        "photo_url": current_user.photo_url,
        "user": serialize_user(current_user, include_email=True),
    }


@router.delete("/api/profile/me/photo")
def delete_my_profile_photo(
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    previous_photo_url = current_user.photo_url
    current_user.photo_url = None
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    remove_local_profile_photo(previous_photo_url)
    return {
        "message": "Фото профиля удалено.",
        "user": serialize_user(current_user, include_email=True),
    }


@router.get("/api/profile/{username}")
def get_public_profile(
    username: str,
    current_user: UserModel | None = Depends(get_current_user),
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
        raise HTTPException(status_code=404, detail="Пользователь не найден.")

    is_current_user = bool(current_user and current_user.id == user.id)
    visible_projects = user.projects if is_current_user else [project for project in user.projects if project.status == "active"]
    projects = sorted(visible_projects, key=project_sort_key, reverse=True)
    return {
        "user": serialize_user(user, include_email=is_current_user),
        "is_current_user": is_current_user,
        "project_count": len(projects),
        "projects": [serialize_project(project, current_user=current_user) for project in projects],
    }
