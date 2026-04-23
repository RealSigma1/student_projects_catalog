from typing import Optional

from .models import ApplicationModel, NotificationModel, ProjectModel, UserModel
from .utils import split_csv


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
