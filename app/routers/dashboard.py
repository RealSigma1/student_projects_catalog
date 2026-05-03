from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from ..auth import require_current_user
from ..database import get_db
from ..models import ApplicationModel, NotificationModel, ProjectModel, UserModel
from ..serializers import (
    serialize_application,
    serialize_notification,
    serialize_project,
    serialize_user,
)
from ..utils import parse_datetime_for_sort, split_csv


router = APIRouter()


def _project_order(project: ProjectModel) -> tuple:
    return parse_datetime_for_sort(project.created_at), project.id or 0


def _application_order(application: ApplicationModel) -> tuple:
    return parse_datetime_for_sort(application.created_at), application.id or 0


def _notification_order(notification: NotificationModel) -> tuple:
    return parse_datetime_for_sort(notification.created_at), notification.id or 0


@router.get("/api/dashboard/overview")
def get_dashboard_overview(
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    owned_projects = (
        db.query(ProjectModel)
        .options(joinedload(ProjectModel.owner), joinedload(ProjectModel.applications))
        .filter(ProjectModel.owner_id == current_user.id)
        .all()
    )
    owned_projects = sorted(owned_projects, key=_project_order, reverse=True)

    incoming_applications = (
        db.query(ApplicationModel)
        .join(ApplicationModel.project)
        .options(joinedload(ApplicationModel.project), joinedload(ApplicationModel.applicant))
        .filter(ProjectModel.owner_id == current_user.id)
        .all()
    )
    incoming_applications = sorted(incoming_applications, key=_application_order, reverse=True)

    my_applications = (
        db.query(ApplicationModel)
        .options(
            joinedload(ApplicationModel.project).joinedload(ProjectModel.owner),
            joinedload(ApplicationModel.applicant),
        )
        .filter(ApplicationModel.applicant_id == current_user.id)
        .all()
    )
    my_applications = sorted(my_applications, key=_application_order, reverse=True)

    notifications = (
        db.query(NotificationModel)
        .filter(NotificationModel.user_id == current_user.id)
        .all()
    )
    notifications = sorted(notifications, key=_notification_order, reverse=True)

    active_catalog_projects = (
        db.query(ProjectModel)
        .options(joinedload(ProjectModel.owner), joinedload(ProjectModel.applications))
        .filter(ProjectModel.status == "active")
        .all()
    )
    active_catalog_projects = sorted(active_catalog_projects, key=_project_order, reverse=True)

    unread_notifications = sum(1 for notification in notifications if not notification.is_read)
    active_owned_projects = [
        project for project in owned_projects
        if project.status == "active" and bool(project.applications_open)
    ]
    closed_owned_projects = [
        project for project in owned_projects
        if project.status == "active" and not bool(project.applications_open)
    ]
    archived_owned_projects = [project for project in owned_projects if project.status == "archived"]
    new_incoming_applications = [application for application in incoming_applications if application.status == "new"]

    accepted_team_members: list[dict] = []
    team_projects: list[dict] = []
    team_projects_map: dict[int, dict] = {}

    def ensure_team_project(
        project_id: int,
        project_title: str | None,
        owner_username: str | None = None,
        owner_full_name: str | None = None,
    ) -> dict:
        if project_id not in team_projects_map:
            team_projects_map[project_id] = {
                "project_id": project_id,
                "project_title": project_title or "Проект",
                "owner_username": owner_username,
                "owner_full_name": owner_full_name,
                "members": [],
            }
            team_projects.append(team_projects_map[project_id])
        else:
            if owner_username and not team_projects_map[project_id].get("owner_username"):
                team_projects_map[project_id]["owner_username"] = owner_username
            if owner_full_name and not team_projects_map[project_id].get("owner_full_name"):
                team_projects_map[project_id]["owner_full_name"] = owner_full_name
        return team_projects_map[project_id]

    for application in incoming_applications:
        if application.status != "accepted" or not application.applicant:
            continue

        applicant_roles = split_csv(application.applicant.roles)
        member_data = {
            "id": application.applicant_id or 0,
            "username": application.applicant.username,
            "full_name": application.applicant.full_name,
            "role": application.assigned_role or (applicant_roles[0] if applicant_roles else None),
            "roles": applicant_roles,
            "project_id": application.project_id,
            "project_title": application.project.title if application.project else None,
            "is_current_user": False,
        }
        accepted_team_members.append(member_data)
        ensure_team_project(
            application.project_id or 0,
            application.project.title if application.project else None,
            current_user.username,
            current_user.full_name,
        )["members"].append(member_data)

    current_user_roles = split_csv(current_user.roles)
    for application in my_applications:
        if application.status != "accepted" or not application.project:
            continue

        owner = application.project.owner
        project_bucket = ensure_team_project(
            application.project_id or 0,
            application.project.title,
            owner.username if owner else None,
            owner.full_name if owner else None,
        )
        accepted_project_applications = (
            db.query(ApplicationModel)
            .options(joinedload(ApplicationModel.applicant))
            .filter(
                ApplicationModel.project_id == application.project_id,
                ApplicationModel.status == "accepted",
            )
            .all()
        )

        existing_member_ids = {
            member.get("id")
            for member in project_bucket["members"]
        }
        for project_application in accepted_project_applications:
            applicant = project_application.applicant
            if not applicant or applicant.id in existing_member_ids:
                continue

            applicant_roles = split_csv(applicant.roles)
            project_bucket["members"].append(
                {
                    "id": applicant.id,
                    "username": applicant.username,
                    "full_name": applicant.full_name,
                    "role": project_application.assigned_role or (applicant_roles[0] if applicant_roles else None),
                    "roles": applicant_roles,
                    "project_id": project_application.project_id,
                    "project_title": application.project.title,
                    "is_current_user": applicant.id == current_user.id,
                }
            )
            existing_member_ids.add(applicant.id)

    return {
        "user": serialize_user(current_user, include_email=True),
        "metrics": {
            "catalog_active_projects": len(active_catalog_projects),
            "my_projects_total": len(owned_projects),
            "my_projects_active": len(active_owned_projects),
            "my_projects_closed": len(closed_owned_projects),
            "my_projects_archived": len(archived_owned_projects),
            "incoming_applications_total": len(incoming_applications),
            "incoming_applications_new": len(new_incoming_applications),
            "my_applications_total": len(my_applications),
            "notifications_unread": unread_notifications,
        },
        "recent_projects": [serialize_project(project, current_user=current_user) for project in owned_projects[:6]],
        "discover_projects": [
            serialize_project(project, current_user=current_user)
            for project in active_catalog_projects[:6]
        ],
        "incoming_applications": [
            serialize_application(application) for application in incoming_applications[:6]
        ],
        "my_applications": [serialize_application(application) for application in my_applications[:6]],
        "notifications": [serialize_notification(notification) for notification in notifications[:6]],
        "team_members": accepted_team_members,
        "team_projects": team_projects,
        "sidebar_counts": {
            "projects": len(owned_projects),
            "applications": len(new_incoming_applications),
            "notifications": unread_notifications,
        },
    }
