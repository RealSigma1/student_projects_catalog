import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DATABASE_PATH, DATABASE_URL
from .utils import utc_now_iso


def ensure_database_schema() -> None:
    if not DATABASE_PATH.exists():
        return

    conn = sqlite3.connect(DATABASE_PATH)
    try:
        cursor = conn.cursor()
        tables = {row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        now = utc_now_iso()

        if "users" in tables:
            user_columns = {row[1] for row in cursor.execute("PRAGMA table_info(users)")}
            if {"id", "username", "hashed_password"} - user_columns:
                backup_path = DATABASE_PATH.with_name(f"{DATABASE_PATH.stem}_legacy_backup.db")
                conn.close()
                DATABASE_PATH.replace(backup_path)
                return
            for column_name in ("email", "full_name", "bio", "skills", "roles", "links", "photo_url", "created_at"):
                if column_name not in user_columns:
                    cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} TEXT")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users(email)")
            cursor.execute(
                "UPDATE users SET created_at = ? WHERE created_at IS NULL OR TRIM(created_at) = ''",
                (now,),
            )

        if "projects" in tables:
            project_columns = {row[1] for row in cursor.execute("PRAGMA table_info(projects)")}
            if {"id", "title", "description", "tags", "owner_id"} - project_columns:
                backup_path = DATABASE_PATH.with_name(f"{DATABASE_PATH.stem}_legacy_backup.db")
                conn.close()
                DATABASE_PATH.replace(backup_path)
                return
            additions = {
                "required_roles": "TEXT",
                "contact_info": "TEXT",
                "status": "TEXT",
                "applications_open": "INTEGER",
                "created_at": "TEXT",
                "updated_at": "TEXT",
            }
            for column_name, column_type in additions.items():
                if column_name not in project_columns:
                    cursor.execute(f"ALTER TABLE projects ADD COLUMN {column_name} {column_type}")
            cursor.execute("UPDATE projects SET status = 'active' WHERE status IS NULL OR TRIM(status) = ''")
            cursor.execute("UPDATE projects SET applications_open = 1 WHERE applications_open IS NULL")
            cursor.execute(
                "UPDATE projects SET created_at = ? WHERE created_at IS NULL OR TRIM(created_at) = ''",
                (now,),
            )
            cursor.execute(
                "UPDATE projects SET updated_at = created_at WHERE updated_at IS NULL OR TRIM(updated_at) = ''"
            )

        if "notifications" in tables:
            notification_columns = {row[1] for row in cursor.execute("PRAGMA table_info(notifications)")}
            additions = {
                "user_id": "INTEGER",
                "type": "TEXT",
                "title": "TEXT",
                "message": "TEXT",
                "is_read": "INTEGER",
                "related_project_id": "INTEGER",
                "related_application_id": "INTEGER",
                "created_at": "TEXT",
            }
            for column_name, column_type in additions.items():
                if column_name not in notification_columns:
                    cursor.execute(f"ALTER TABLE notifications ADD COLUMN {column_name} {column_type}")
            cursor.execute("UPDATE notifications SET is_read = 0 WHERE is_read IS NULL")
            cursor.execute(
                "UPDATE notifications SET created_at = ? WHERE created_at IS NULL OR TRIM(created_at) = ''",
                (now,),
            )

        if "applications" in tables:
            application_columns = {row[1] for row in cursor.execute("PRAGMA table_info(applications)")}
            additions = {
                "assigned_role": "TEXT",
                "requested_role": "TEXT",
            }
            for column_name, column_type in additions.items():
                if column_name not in application_columns:
                    cursor.execute(f"ALTER TABLE applications ADD COLUMN {column_name} {column_type}")

        conn.commit()
    finally:
        conn.close()


ensure_database_schema()

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
