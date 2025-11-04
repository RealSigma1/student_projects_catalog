from fastapi import FastAPI, Depends, HTTPException, status, Query, Response, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.orm import joinedload
import bcrypt
from uuid import uuid4
import os

# =========================
# ⚙️ Настройка базы данных
# =========================
DATABASE_URL = "sqlite:///./projects.db"

if os.path.exists("projects.db"):
    engine_check = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    inspector = inspect(engine_check)
    columns = [col["name"] for col in inspector.get_columns("projects")] if inspector.has_table("projects") else []
    if "owner_id" not in columns:
        print("⚠️ Старый формат базы данных найден — пересоздаём projects.db...")
        os.remove("projects.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# =========================
# 🧍 Модель пользователя
# =========================
class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    projects = relationship("ProjectModel", back_populates="owner")


# =========================
# 💼 Модель проекта
# =========================
class ProjectModel(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(Text)
    tags = Column(String)
    github_url = Column(String)
    demo_url = Column(String)
    owner_id = Column(Integer, ForeignKey("users.id"))

    owner = relationship("UserModel", back_populates="projects")


Base.metadata.create_all(bind=engine)


# =========================
# 📦 Pydantic модели
# =========================
class UserCreate(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    username: str

    class Config:
        orm_mode = True


class ProjectCreate(BaseModel):
    title: str
    description: str
    tags: List[str]
    github_url: str
    demo_url: Optional[str] = None


class ProjectResponse(BaseModel):
    id: int
    title: str
    description: str
    tags: List[str]
    github_url: str
    demo_url: Optional[str] = None
    owner_username: str

    class Config:
        orm_mode = True


class ProfileResponse(BaseModel):
    username: str
    project_count: int
    projects: List[ProjectResponse]

    class Config:
        orm_mode = True


# =========================
# 🚀 Инициализация приложения
# =========================
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")


# =========================
# 🔑 Работа с паролями
# =========================
def get_password_hash(password: str) -> str:
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


# =========================
# 🧩 Зависимости
# =========================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================
# 🍪 Сессии (in-memory)
# =========================
_sessions = {}


def create_session(response: Response, user_id: int):
    session_id = str(uuid4())
    _sessions[session_id] = user_id
    response.set_cookie(key="session_id", value=session_id, httponly=True, samesite="lax")
    return session_id


def get_current_user(session_id: str = Cookie(None), db: Session = Depends(get_db)):
    if not session_id or session_id not in _sessions:
        return None
    user_id = _sessions[session_id]
    return db.query(UserModel).filter(UserModel.id == user_id).first()


# =========================
# 🌐 Роуты HTML
# =========================
@app.get("/", response_class=HTMLResponse)
async def read_root(current_user: UserModel = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/login")
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/register", response_class=HTMLResponse)
async def register_page():
    with open("static/register.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    with open("static/login.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/profile/me", response_class=HTMLResponse)
async def profile_me_page(current_user: UserModel = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/login")
    with open("static/profile.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/profile/{username}", response_class=HTMLResponse)
async def profile_page(username: str):
    with open("static/profile.html", "r", encoding="utf-8") as f:
        return f.read()


# =========================
# 👤 Аутентификация
# =========================
@app.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(UserModel).filter(UserModel.username == user.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    hashed_password = get_password_hash(user.password)
    new_user = UserModel(username=user.username, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.post("/login")
def login(user: UserLogin, response: Response, db: Session = Depends(get_db)):
    db_user = db.query(UserModel).filter(UserModel.username == user.username).first()
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    create_session(response, db_user.id)
    return {"message": "Login successful"}


@app.post("/logout")
def logout(response: Response, session_id: str = Cookie(None)):
    if session_id and session_id in _sessions:
        del _sessions[session_id]
    response.delete_cookie("session_id")
    return {"message": "Logout successful"}


@app.get("/me", response_model=UserResponse)
def get_me(current_user: UserModel = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return current_user


# =========================
# 💡 Проекты и профили (API)
# =========================
@app.post("/projects/", response_model=ProjectResponse)
def create_project(project: ProjectCreate, current_user: UserModel = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    if not current_user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    db_project = ProjectModel(
        title=project.title,
        description=project.description,
        tags=",".join(project.tags),
        github_url=project.github_url,
        demo_url=project.demo_url,
        owner_id=current_user.id
    )
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return ProjectResponse(
        id=db_project.id,
        title=db_project.title,
        description=db_project.description,
        tags=db_project.tags.split(",") if db_project.tags else [],
        github_url=db_project.github_url,
        demo_url=db_project.demo_url,
        owner_username=db_project.owner.username
    )


@app.get("/projects/", response_model=List[ProjectResponse])
def search_projects(tags: Optional[List[str]] = Query(None), db: Session = Depends(get_db)):
    query = db.query(ProjectModel).options(joinedload(ProjectModel.owner))
    if tags:
        for tag in tags:
            query = query.filter(ProjectModel.tags.contains(tag))
    projects = query.all()
    return [
        ProjectResponse(
            id=p.id,
            title=p.title,
            description=p.description,
            tags=p.tags.split(",") if p.tags else [],
            github_url=p.github_url,
            demo_url=p.demo_url,
            owner_username=p.owner.username if p.owner else "Unknown"
        )
        for p in projects
    ]


@app.get("/projects/all", response_model=List[ProjectResponse])
def get_all_projects(db: Session = Depends(get_db)):
    projects = db.query(ProjectModel).options(joinedload(ProjectModel.owner)).all()
    return [
        ProjectResponse(
            id=p.id,
            title=p.title,
            description=p.description,
            tags=p.tags.split(",") if p.tags else [],
            github_url=p.github_url,
            demo_url=p.demo_url,
            owner_username=p.owner.username if p.owner else "Unknown"
        )
        for p in projects
    ]


@app.get("/api/profile/me", response_model=ProfileResponse)
def get_my_profile(current_user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    projects = db.query(ProjectModel).options(joinedload(ProjectModel.owner)).filter(ProjectModel.owner_id == current_user.id).all()
    return ProfileResponse(
        username=current_user.username,
        project_count=len(projects),
        projects=[
            ProjectResponse(
                id=p.id,
                title=p.title,
                description=p.description,
                tags=p.tags.split(",") if p.tags else [],
                github_url=p.github_url,
                demo_url=p.demo_url,
                owner_username=p.owner.username if p.owner else "Unknown"
            )
            for p in projects
        ]
    )


@app.get("/api/profile/{username}", response_model=ProfileResponse)
def get_user_profile(username: str, db: Session = Depends(get_db)):
    user = db.query(UserModel).filter(UserModel.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    projects = db.query(ProjectModel).options(joinedload(ProjectModel.owner)).filter(ProjectModel.owner_id == user.id).all()
    return ProfileResponse(
        username=user.username,
        project_count=len(projects),
        projects=[
            ProjectResponse(
                id=p.id,
                title=p.title,
                description=p.description,
                tags=p.tags.split(",") if p.tags else [],
                github_url=p.github_url,
                demo_url=p.demo_url,
                owner_username=p.owner.username if p.owner else "Unknown"
            )
            for p in projects
        ]
    )