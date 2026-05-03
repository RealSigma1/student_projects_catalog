from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, require_current_user
from ..database import get_db
from ..models import ApplicationModel, ProjectModel, UserModel
from ..schemas import (
    ApplicationCreate,
    ApplicationRoleRequest,
    ApplicationRoleRequestDecision,
    ApplicationStatusUpdate,
    ProjectPayload,
)
from ..serializers import serialize_application, serialize_project
from ..services import can_view_project, create_notification
from ..utils import join_csv, project_sort_key, split_csv, utc_now_iso


router = APIRouter()


@router.get("/api/projects")
def list_projects(
    search: Optional[str] = Query(default=None),
    tags: Optional[str] = Query(default=None),
    roles: Optional[str] = Query(default=None),
    status_filter: Literal["all", "active", "archived"] = Query(default="active"),
    sort_order: Literal["newest", "oldest"] = Query(default="newest"),
    owner: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=6, ge=1, le=50),
    current_user: UserModel | None = Depends(get_current_user),
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

    all_items = query.all()
    reverse = sort_order == "newest"
    sorted_items = sorted(all_items, key=project_sort_key, reverse=reverse)
    total = len(sorted_items)
    start = (page - 1) * page_size
    end = start + page_size
    items = sorted_items[start:end]
    return {
        "items": [serialize_project(project, current_user=current_user) for project in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.post("/api/projects")
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
        applications_open=payload.applications_open,
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
    return {"message": "Проект создан.", "project": serialize_project(project, current_user=current_user)}


@router.get("/api/projects/{project_id}")
def get_project(
    project_id: int,
    current_user: UserModel | None = Depends(get_current_user),
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
        raise HTTPException(status_code=404, detail="Проект не найден.")
    if not can_view_project(project, current_user):
        raise HTTPException(status_code=404, detail="Проект не найден.")

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


@router.put("/api/projects/{project_id}")
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
        raise HTTPException(status_code=404, detail="Проект не найден.")
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Только автор проекта может его редактировать.")

    project.title = payload.title
    project.description = payload.description
    project.tags = join_csv(payload.tags)
    project.required_roles = join_csv(payload.required_roles)
    project.github_url = payload.github_url
    project.demo_url = payload.demo_url
    project.contact_info = payload.contact_info
    project.status = payload.status
    project.applications_open = payload.applications_open
    project.updated_at = utc_now_iso()
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"message": "Проект обновлён.", "project": serialize_project(project, current_user=current_user)}


@router.delete("/api/projects/{project_id}")
def delete_project(
    project_id: int,
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден.")
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Только автор проекта может его удалить.")
    db.delete(project)
    db.commit()
    return {"message": "Проект удалён."}


@router.post("/api/projects/{project_id}/applications")
def create_application(
    project_id: int,
    payload: ApplicationCreate,
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = db.query(ProjectModel).options(joinedload(ProjectModel.owner)).filter(ProjectModel.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден.")
    if project.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя откликнуться на собственный проект.")
    if project.status != "active":
        raise HTTPException(status_code=400, detail="Отклики на архивный проект закрыты.")
    if not project.applications_open:
        raise HTTPException(status_code=400, detail="Набор в этот проект сейчас закрыт.")

    existing_application = (
        db.query(ApplicationModel)
        .filter(ApplicationModel.project_id == project_id, ApplicationModel.applicant_id == current_user.id)
        .first()
    )
    if existing_application:
        raise HTTPException(status_code=400, detail="Вы уже откликались на этот проект.")

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
        title="Новый отклик на проект",
        message=f"{applicant_name} откликнулся на ваш проект «{project.title}».",
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
    return {"message": "Отклик отправлен.", "application": serialize_application(application)}


@router.get("/api/projects/{project_id}/applications")
def list_project_applications(
    project_id: int,
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден.")
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Только автор проекта может смотреть отклики.")

    applications = (
        db.query(ApplicationModel)
        .options(joinedload(ApplicationModel.applicant), joinedload(ApplicationModel.project))
        .filter(ApplicationModel.project_id == project_id)
        .order_by(ApplicationModel.created_at.desc(), ApplicationModel.id.desc())
        .all()
    )
    return {"items": [serialize_application(application) for application in applications]}


@router.patch("/api/applications/{application_id}")
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
        raise HTTPException(status_code=404, detail="Отклик не найден.")
    if application.project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Только автор проекта может менять статус отклика.")
    if application.status != "new":
        raise HTTPException(status_code=400, detail="Этот отклик уже обработан, его статус нельзя изменить повторно.")

    application.status = payload.status
    if payload.status == "accepted":
        applicant_roles = split_csv(application.applicant.roles if application.applicant else "")
        assigned_role = payload.assigned_role or (applicant_roles[0] if applicant_roles else None)
        if not assigned_role:
            raise HTTPException(
                status_code=400,
                detail="Перед принятием отклика нужно указать роль в проекте, если в профиле участника роль не заполнена.",
            )
        application.assigned_role = assigned_role
        application.requested_role = None
    elif payload.status == "rejected":
        application.requested_role = None

    db.add(application)
    create_notification(
        db,
        user_id=application.applicant_id,
        type="application_status",
        title="Статус отклика обновлён",
        message=(
            f"Ваш отклик на проект «{application.project.title}» принят на роль «{application.assigned_role}»."
            if payload.status == "accepted"
            else f"Ваш отклик на проект «{application.project.title}» отклонён."
        ),
        related_project_id=application.project_id,
        related_application_id=application.id,
    )
    db.commit()
    db.refresh(application)
    return {"message": "Статус отклика обновлён.", "application": serialize_application(application)}


@router.post("/api/applications/{application_id}/remove")
def remove_team_member(
    application_id: int,
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
        raise HTTPException(status_code=404, detail="Отклик не найден.")
    if application.project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Только автор проекта может убирать участников из команды.")
    if application.status != "accepted":
        raise HTTPException(status_code=400, detail="Убрать из команды можно только принятого участника.")

    application.status = "removed"
    db.add(application)
    create_notification(
        db,
        user_id=application.applicant_id,
        type="application_status",
        title="Статус отклика обновлён",
        message=f"Вас убрали из команды проекта «{application.project.title}».",
        related_project_id=application.project_id,
        related_application_id=application.id,
    )
    db.commit()
    db.refresh(application)
    return {"message": "Участник убран из команды.", "application": serialize_application(application)}


@router.post("/api/applications/{application_id}/role-request")
def request_role_change(
    application_id: int,
    payload: ApplicationRoleRequest,
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
        raise HTTPException(status_code=404, detail="Отклик не найден.")
    if application.applicant_id != current_user.id:
        raise HTTPException(status_code=403, detail="Только сам участник может запросить смену роли.")
    if application.status != "accepted":
        raise HTTPException(status_code=400, detail="Смену роли можно запросить только для принятого участника.")
    if payload.requested_role == application.assigned_role:
        raise HTTPException(status_code=400, detail="Эта роль уже указана у вас в проекте.")

    application.requested_role = payload.requested_role
    db.add(application)
    create_notification(
        db,
        user_id=application.project.owner_id,
        type="role_change_request",
        title="Запрос на смену роли",
        message=(
            f"{current_user.full_name or current_user.username} запросил роль "
            f"«{payload.requested_role}» в проекте «{application.project.title}»."
        ),
        related_project_id=application.project_id,
        related_application_id=application.id,
    )
    db.commit()
    db.refresh(application)
    return {"message": "Запрос на смену роли отправлен.", "application": serialize_application(application)}


@router.patch("/api/applications/{application_id}/role-request")
def resolve_role_change_request(
    application_id: int,
    payload: ApplicationRoleRequestDecision,
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
        raise HTTPException(status_code=404, detail="Отклик не найден.")
    if application.project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Только автор проекта может рассматривать запросы на смену роли.")
    if application.status != "accepted":
        raise HTTPException(status_code=400, detail="Менять роль можно только у принятого участника.")
    if not application.requested_role:
        raise HTTPException(status_code=400, detail="У этого участника нет активного запроса на смену роли.")

    requested_role = application.requested_role
    if payload.decision == "approved":
        approved_role = payload.assigned_role or requested_role
        if not approved_role:
            raise HTTPException(status_code=400, detail="Нужно указать утверждённую роль в проекте.")
        application.assigned_role = approved_role
        notification_message = (
            f"Владелец проекта «{application.project.title}» утвердил вашу новую роль «{approved_role}»."
        )
    else:
        notification_message = (
            f"Владелец проекта «{application.project.title}» отклонил запрос на роль «{requested_role}»."
        )

    application.requested_role = None
    db.add(application)
    create_notification(
        db,
        user_id=application.applicant_id,
        type="role_change_request",
        title="Решение по запросу роли",
        message=notification_message,
        related_project_id=application.project_id,
        related_application_id=application.id,
    )
    db.commit()
    db.refresh(application)
    return {"message": "Запрос на смену роли обработан.", "application": serialize_application(application)}


@router.get("/api/applications/me")
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
