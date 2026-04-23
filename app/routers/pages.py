from fastapi import APIRouter, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse

from ..auth import get_current_user
from ..models import UserModel
from ..services import read_static_file


router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def read_root(current_user: UserModel | None = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    return HTMLResponse(read_static_file("index.html"))


@router.get("/login", response_class=HTMLResponse)
def login_page():
    return HTMLResponse(read_static_file("login.html"))


@router.get("/register", response_class=HTMLResponse)
def register_page():
    return HTMLResponse(read_static_file("register.html"))


@router.get("/profile/me", response_class=HTMLResponse)
def my_profile_page(current_user: UserModel | None = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    return HTMLResponse(read_static_file("profile.html"))


@router.get("/profile/{username}", response_class=HTMLResponse)
def public_profile_page(username: str):
    return HTMLResponse(read_static_file("profile.html"))


@router.get("/project/{project_id}", response_class=HTMLResponse)
def project_page(project_id: int):
    return HTMLResponse(read_static_file("project.html"))


@router.get("/projects/new", response_class=HTMLResponse)
def create_project_page(current_user: UserModel | None = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    return HTMLResponse(read_static_file("create_project.html"))
