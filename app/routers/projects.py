from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, require_current_user
from ..database import get_db
from ..models import ApplicationModel, ProjectModel, UserModel
from ..schemas import ApplicationCreate, ApplicationStatusUpdate, ProjectPayload
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
    query = query.filter(ProjectModel.status == "active")
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
        raise HTTPException(status_code=404, detail="Project not found.")
    if not can_view_project(project, current_user):
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


@router.delete("/api/projects/{project_id}")
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


@router.post("/api/projects/{project_id}/applications")
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


@router.get("/api/projects/{project_id}/applications")
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
