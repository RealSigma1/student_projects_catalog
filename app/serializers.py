import re
from typing import Optional

from .models import ApplicationModel, NotificationModel, ProjectModel, UserModel
from .utils import split_csv


def _localize_notification(notification: NotificationModel) -> tuple[str, str]:
    title = notification.title or ""
    message = notification.message or ""

    if title == "New application received":
        title = "Новый отклик на проект"
    elif title == "Application status updated":
        title = "Статус отклика обновлён"
    elif title == "Role change request":
        title = "Запрос на смену роли"
    elif title == "Role change request resolved":
        title = "Решение по запросу роли"

    new_application_match = re.fullmatch(r"(.+?) responded to your project '(.+)'\.", message)
    if new_application_match:
        applicant_name, project_title = new_application_match.groups()
        return title, f"{applicant_name} откликнулся на ваш проект «{project_title}»."

    accepted_match = re.fullmatch(r"Your application to '(.+)' was accepted for the role '(.+)'\.", message)
    if accepted_match:
        project_title, assigned_role = accepted_match.groups()
        return title, f"Ваш отклик на проект «{project_title}» принят на роль «{assigned_role}»."

    rejected_match = re.fullmatch(r"Your application to '(.+)' was rejected\.", message)
    if rejected_match:
        project_title = rejected_match.group(1)
        return title, f"Ваш отклик на проект «{project_title}» отклонён."

    removed_match = re.fullmatch(r"You were removed from the team of project '(.+)'\.", message)
    if removed_match:
        project_title = removed_match.group(1)
        return title, f"Вас убрали из команды проекта «{project_title}»."

    role_request_match = re.fullmatch(r"(.+?) requested the role '(.+?)' in project '(.+)'\.", message)
    if role_request_match:
        applicant_name, requested_role, project_title = role_request_match.groups()
        return title, f"{applicant_name} запросил роль «{requested_role}» в проекте «{project_title}»."

    role_request_approved_match = re.fullmatch(
        r"The owner of project '(.+)' approved your new role '(.+)'\.",
        message,
    )
    if role_request_approved_match:
        project_title, approved_role = role_request_approved_match.groups()
        return title, f"Владелец проекта «{project_title}» утвердил вашу новую роль «{approved_role}»."

    role_request_rejected_match = re.fullmatch(
        r"The owner of project '(.+)' rejected your request for role '(.+)'\.",
        message,
    )
    if role_request_rejected_match:
        project_title, requested_role = role_request_rejected_match.groups()
        return title, f"Владелец проекта «{project_title}» отклонил запрос на роль «{requested_role}»."

    return title, message


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
        "applications_open": bool(project.applications_open),
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "owner_id": project.owner_id,
        "owner_username": project.owner.username if project.owner else None,
        "owner_full_name": project.owner.full_name if project.owner else None,
        "applications_count": len(project.applications),
        "is_owner": is_owner,
        "has_applied": has_applied,
        "can_apply": bool(
            current_user
            and not is_owner
            and not has_applied
            and project.status == "active"
            and bool(project.applications_open)
        ),
    }


def serialize_application(application: ApplicationModel) -> dict:
    return {
        "id": application.id,
        "project_id": application.project_id,
        "message": application.message,
        "status": application.status,
        "assigned_role": application.assigned_role,
        "requested_role": application.requested_role,
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
    title, message = _localize_notification(notification)
    return {
        "id": notification.id,
        "type": notification.type,
        "title": title,
        "message": message,
        "is_read": bool(notification.is_read),
        "created_at": notification.created_at,
        "related_project_id": notification.related_project_id,
        "related_application_id": notification.related_application_id,
        "action_url": action_url,
    }
