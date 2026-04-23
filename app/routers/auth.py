from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..auth import (
    clear_auth_cookie,
    create_access_token,
    get_password_hash,
    require_current_user,
    set_auth_cookie,
    verify_password,
)
from ..database import get_db
from ..models import UserModel
from ..schemas import UserLogin, UserRegister
from ..serializers import serialize_user
from ..utils import utc_now_iso


router = APIRouter()


def authenticate_user(login_value: str, password: str, db: Session) -> UserModel:
    db_user = db.query(UserModel).filter(
        or_(UserModel.username == login_value, UserModel.email == login_value.lower())
    ).first()
    if not db_user or not verify_password(password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid login or password.")
    return db_user


@router.get("/api/health")
def healthcheck() -> dict:
    return {"status": "ok"}


@router.post("/api/auth/register")
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


@router.post("/api/auth/login")
def login(user: UserLogin, response: Response, db: Session = Depends(get_db)) -> dict:
    login_value = user.login.strip()
    db_user = authenticate_user(login_value, user.password, db)
    access_token = create_access_token(db_user)
    set_auth_cookie(response, db_user)
    return {
        "message": "Login successful.",
        "access_token": access_token,
        "token_type": "bearer",
        "user": serialize_user(db_user, include_email=True),
    }


@router.post("/api/auth/token")
def issue_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> dict:
    db_user = authenticate_user(form_data.username.strip(), form_data.password, db)
    return {
        "access_token": create_access_token(db_user),
        "token_type": "bearer",
    }


@router.post("/api/auth/logout")
def logout(response: Response) -> dict:
    clear_auth_cookie(response)
    return {"message": "Logout successful."}


@router.get("/api/me")
def get_me(current_user: UserModel = Depends(require_current_user)) -> dict:
    return serialize_user(current_user, include_email=True)


@router.post("/register")
def register_compat(user: UserRegister, db: Session = Depends(get_db)) -> dict:
    return register(user, db)


@router.post("/login")
def login_compat(user: UserLogin, response: Response, db: Session = Depends(get_db)) -> dict:
    return login(user, response, db)


@router.post("/logout")
def logout_compat(response: Response) -> dict:
    return logout(response)


@router.get("/me")
def me_compat(current_user: UserModel = Depends(require_current_user)) -> dict:
    return get_me(current_user)
