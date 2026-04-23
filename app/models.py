from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from .database import Base
from .utils import utc_now_iso


class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    bio = Column(Text)
    skills = Column(Text, default="")
    roles = Column(Text, default="")
    links = Column(Text, default="")
    photo_url = Column(Text)
    created_at = Column(String, default=utc_now_iso, nullable=False)

    projects = relationship("ProjectModel", back_populates="owner", cascade="all, delete-orphan")
    applications = relationship("ApplicationModel", back_populates="applicant", cascade="all, delete-orphan")
    notifications = relationship("NotificationModel", back_populates="user", cascade="all, delete-orphan")


class ProjectModel(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    description = Column(Text, nullable=False)
    tags = Column(Text, default="")
    required_roles = Column(Text, default="")
    github_url = Column(String)
    demo_url = Column(String)
    contact_info = Column(Text)
    status = Column(String, default="active", nullable=False)
    created_at = Column(String, default=utc_now_iso, nullable=False)
    updated_at = Column(String, default=utc_now_iso, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    owner = relationship("UserModel", back_populates="projects")
    applications = relationship("ApplicationModel", back_populates="project", cascade="all, delete-orphan")


class ApplicationModel(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("project_id", "applicant_id", name="uq_project_applicant"),)

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    applicant_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String, default="new", nullable=False)
    created_at = Column(String, default=utc_now_iso, nullable=False)

    project = relationship("ProjectModel", back_populates="applications")
    applicant = relationship("UserModel", back_populates="applications")


class NotificationModel(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)
    related_project_id = Column(Integer)
    related_application_id = Column(Integer)
    created_at = Column(String, default=utc_now_iso, nullable=False)

    user = relationship("UserModel", back_populates="notifications")
