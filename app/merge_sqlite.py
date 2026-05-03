from __future__ import annotations

import hashlib
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .utils import join_csv, normalize_text, parse_datetime_for_sort, split_csv, utc_now_iso


STATUS_PRIORITY = {
    "new": 0,
    "accepted": 2,
    "rejected": 2,
    "removed": 2,
}


@dataclass
class MergeStats:
    users_inserted: int = 0
    users_updated: int = 0
    projects_inserted: int = 0
    projects_updated: int = 0
    applications_inserted: int = 0
    applications_updated: int = 0
    notifications_inserted: int = 0
    media_copied: int = 0


def backup_database(target_db: Path, backup_dir: Path | None = None) -> Path:
    backup_dir = backup_dir or (target_db.parent / "backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{target_db.stem}_backup_{utc_now_iso().replace(':', '-').replace('.', '-')}{target_db.suffix}"
    shutil.copy2(target_db, backup_path)
    return backup_path


def merge_sqlite_data(
    *,
    source_db: Path,
    target_db: Path,
    source_media_dir: Path | None = None,
    target_media_dir: Path | None = None,
) -> MergeStats:
    source_db = source_db.resolve()
    target_db = target_db.resolve()
    if source_db == target_db:
        raise ValueError("Исходная и целевая базы должны быть разными файлами.")

    target_db.parent.mkdir(parents=True, exist_ok=True)
    if not target_db.exists():
        shutil.copy2(source_db, target_db)
        stats = MergeStats()
        if source_media_dir and target_media_dir:
            target_media_dir.mkdir(parents=True, exist_ok=True)
            stats.media_copied = _copy_tree(source_media_dir, target_media_dir)
        return stats

    source_media_dir = source_media_dir.resolve() if source_media_dir else None
    target_media_dir = target_media_dir.resolve() if target_media_dir else None
    media_mapper = MediaMapper(source_media_dir, target_media_dir)

    source_conn = sqlite3.connect(source_db)
    target_conn = sqlite3.connect(target_db)
    source_conn.row_factory = sqlite3.Row
    target_conn.row_factory = sqlite3.Row

    try:
        ensure_schema(source_conn)
        ensure_schema(target_conn)
        stats = MergeStats()

        user_map = merge_users(source_conn, target_conn, media_mapper, stats)
        project_map = merge_projects(source_conn, target_conn, user_map, stats)
        application_map = merge_applications(source_conn, target_conn, user_map, project_map, stats)
        merge_notifications(source_conn, target_conn, user_map, project_map, application_map, stats)

        target_conn.commit()
        stats.media_copied += media_mapper.copied_files
        return stats
    finally:
        source_conn.close()
        target_conn.close()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            email TEXT UNIQUE,
            hashed_password TEXT NOT NULL,
            full_name TEXT,
            bio TEXT,
            skills TEXT DEFAULT '',
            roles TEXT DEFAULT '',
            links TEXT DEFAULT '',
            photo_url TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            tags TEXT DEFAULT '',
            required_roles TEXT DEFAULT '',
            github_url TEXT,
            demo_url TEXT,
            contact_info TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            applications_open INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            owner_id INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            applicant_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new',
            assigned_role TEXT,
            requested_role TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(project_id, applicant_id)
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            related_project_id INTEGER,
            related_application_id INTEGER,
            created_at TEXT NOT NULL
        );
        """
    )

    add_columns_if_missing(
        conn,
        "users",
        {
            "email": "TEXT",
            "full_name": "TEXT",
            "bio": "TEXT",
            "skills": "TEXT DEFAULT ''",
            "roles": "TEXT DEFAULT ''",
            "links": "TEXT DEFAULT ''",
            "photo_url": "TEXT",
            "created_at": "TEXT",
        },
    )
    add_columns_if_missing(
        conn,
        "projects",
        {
            "required_roles": "TEXT DEFAULT ''",
            "github_url": "TEXT",
            "demo_url": "TEXT",
            "contact_info": "TEXT",
            "status": "TEXT DEFAULT 'active'",
            "applications_open": "INTEGER DEFAULT 1",
            "created_at": "TEXT",
            "updated_at": "TEXT",
        },
    )
    add_columns_if_missing(
        conn,
        "applications",
        {
            "assigned_role": "TEXT",
            "requested_role": "TEXT",
        },
    )
    add_columns_if_missing(
        conn,
        "notifications",
        {
            "is_read": "INTEGER DEFAULT 0",
            "related_project_id": "INTEGER",
            "related_application_id": "INTEGER",
            "created_at": "TEXT",
        },
    )

    now = utc_now_iso()
    conn.execute("UPDATE users SET created_at = COALESCE(NULLIF(TRIM(created_at), ''), ?) WHERE created_at IS NULL OR TRIM(created_at) = ''", (now,))
    conn.execute("UPDATE projects SET status = COALESCE(NULLIF(TRIM(status), ''), 'active')")
    conn.execute("UPDATE projects SET applications_open = COALESCE(applications_open, 1)")
    conn.execute("UPDATE projects SET created_at = COALESCE(NULLIF(TRIM(created_at), ''), ?) WHERE created_at IS NULL OR TRIM(created_at) = ''", (now,))
    conn.execute("UPDATE projects SET updated_at = COALESCE(NULLIF(TRIM(updated_at), ''), created_at) WHERE updated_at IS NULL OR TRIM(updated_at) = ''")
    conn.execute("UPDATE notifications SET is_read = COALESCE(is_read, 0)")
    conn.execute("UPDATE notifications SET created_at = COALESCE(NULLIF(TRIM(created_at), ''), ?) WHERE created_at IS NULL OR TRIM(created_at) = ''", (now,))
    conn.commit()


def add_columns_if_missing(conn: sqlite3.Connection, table_name: str, additions: dict[str, str]) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}
    for column_name, definition in additions.items():
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def merge_users(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    media_mapper: "MediaMapper",
    stats: MergeStats,
) -> dict[int, int]:
    target_users = list(target_conn.execute("SELECT * FROM users ORDER BY id"))
    by_username = {row["username"].strip().lower(): row for row in target_users if row["username"]}
    by_email = {row["email"].strip().lower(): row for row in target_users if row["email"]}

    user_map: dict[int, int] = {}
    for source_user in source_conn.execute("SELECT * FROM users ORDER BY id"):
        username_key = source_user["username"].strip().lower()
        email_key = source_user["email"].strip().lower() if source_user["email"] else None
        target_user = by_username.get(username_key) or (by_email.get(email_key) if email_key else None)
        source_photo = media_mapper.import_photo(source_user["photo_url"], source_user["username"])

        if target_user:
            updates: dict[str, Any] = {}

            if not target_user["email"] and source_user["email"]:
                updates["email"] = source_user["email"]
            if not target_user["hashed_password"] and source_user["hashed_password"]:
                updates["hashed_password"] = source_user["hashed_password"]
            if not normalize_text(target_user["full_name"]) and normalize_text(source_user["full_name"]):
                updates["full_name"] = source_user["full_name"]
            if not normalize_text(target_user["bio"]) and normalize_text(source_user["bio"]):
                updates["bio"] = source_user["bio"]
            merged_skills = merge_csv_text(target_user["skills"], source_user["skills"])
            merged_roles = merge_csv_text(target_user["roles"], source_user["roles"])
            merged_links = merge_csv_text(target_user["links"], source_user["links"])
            if merged_skills != (target_user["skills"] or ""):
                updates["skills"] = merged_skills
            if merged_roles != (target_user["roles"] or ""):
                updates["roles"] = merged_roles
            if merged_links != (target_user["links"] or ""):
                updates["links"] = merged_links
            if not normalize_text(target_user["photo_url"]) and source_photo:
                updates["photo_url"] = source_photo
            if parse_datetime_for_sort(source_user["created_at"]) < parse_datetime_for_sort(target_user["created_at"]):
                updates["created_at"] = source_user["created_at"]

            if updates:
                assignment = ", ".join(f"{column} = ?" for column in updates)
                target_conn.execute(
                    f"UPDATE users SET {assignment} WHERE id = ?",
                    (*updates.values(), target_user["id"]),
                )
                refreshed = dict(target_user)
                refreshed.update(updates)
                target_user = refreshed
                stats.users_updated += 1

            user_map[source_user["id"]] = int(target_user["id"])
            by_username[username_key] = target_user
            if target_user["email"]:
                by_email[target_user["email"].strip().lower()] = target_user
            continue

        cursor = target_conn.execute(
            """
            INSERT INTO users (username, email, hashed_password, full_name, bio, skills, roles, links, photo_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_user["username"],
                source_user["email"],
                source_user["hashed_password"],
                source_user["full_name"],
                source_user["bio"],
                source_user["skills"] or "",
                source_user["roles"] or "",
                source_user["links"] or "",
                source_photo,
                source_user["created_at"] or utc_now_iso(),
            ),
        )
        target_id = int(cursor.lastrowid)
        user_map[source_user["id"]] = target_id
        inserted_row = dict(source_user)
        inserted_row["id"] = target_id
        inserted_row["photo_url"] = source_photo
        by_username[username_key] = inserted_row
        if source_user["email"]:
            by_email[source_user["email"].strip().lower()] = inserted_row
        stats.users_inserted += 1
    return user_map


def merge_projects(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    user_map: dict[int, int],
    stats: MergeStats,
) -> dict[int, int]:
    target_projects = list(target_conn.execute("SELECT * FROM projects ORDER BY id"))
    projects_by_owner: dict[int, list[sqlite3.Row | dict[str, Any]]] = {}
    for row in target_projects:
        projects_by_owner.setdefault(int(row["owner_id"]), []).append(row)

    project_map: dict[int, int] = {}
    for source_project in source_conn.execute("SELECT * FROM projects ORDER BY id"):
        mapped_owner_id = user_map.get(source_project["owner_id"])
        if not mapped_owner_id:
            continue

        owner_projects = projects_by_owner.setdefault(mapped_owner_id, [])
        target_project = find_matching_project(owner_projects, source_project)

        if target_project:
            updates: dict[str, Any] = {}
            merged_tags = merge_csv_text(target_project["tags"], source_project["tags"])
            merged_roles = merge_csv_text(target_project["required_roles"], source_project["required_roles"])
            if merged_tags != (target_project["tags"] or ""):
                updates["tags"] = merged_tags
            if merged_roles != (target_project["required_roles"] or ""):
                updates["required_roles"] = merged_roles
            for column in ("description", "github_url", "demo_url", "contact_info"):
                if not normalize_text(target_project[column]) and normalize_text(source_project[column]):
                    updates[column] = source_project[column]
            if target_project["status"] == "new" and source_project["status"] != "new":
                updates["status"] = source_project["status"]
            if not target_project["applications_open"] and source_project["applications_open"]:
                updates["applications_open"] = int(source_project["applications_open"])
            if parse_datetime_for_sort(source_project["created_at"]) < parse_datetime_for_sort(target_project["created_at"]):
                updates["created_at"] = source_project["created_at"]
            if parse_datetime_for_sort(source_project["updated_at"]) > parse_datetime_for_sort(target_project["updated_at"]):
                updates["updated_at"] = source_project["updated_at"]

            if updates:
                assignment = ", ".join(f"{column} = ?" for column in updates)
                target_conn.execute(
                    f"UPDATE projects SET {assignment} WHERE id = ?",
                    (*updates.values(), target_project["id"]),
                )
                refreshed = dict(target_project)
                refreshed.update(updates)
                target_project = refreshed
                owner_projects[:] = [target_project if int(row["id"]) == int(target_project["id"]) else row for row in owner_projects]
                stats.projects_updated += 1

            project_map[source_project["id"]] = int(target_project["id"])
            continue

        cursor = target_conn.execute(
            """
            INSERT INTO projects (
                title, description, tags, required_roles, github_url, demo_url, contact_info,
                status, applications_open, created_at, updated_at, owner_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_project["title"],
                source_project["description"],
                source_project["tags"] or "",
                source_project["required_roles"] or "",
                source_project["github_url"],
                source_project["demo_url"],
                source_project["contact_info"],
                source_project["status"] or "active",
                int(source_project["applications_open"]) if source_project["applications_open"] is not None else 1,
                source_project["created_at"] or utc_now_iso(),
                source_project["updated_at"] or source_project["created_at"] or utc_now_iso(),
                mapped_owner_id,
            ),
        )
        target_id = int(cursor.lastrowid)
        project_map[source_project["id"]] = target_id
        inserted_row = dict(source_project)
        inserted_row["id"] = target_id
        inserted_row["owner_id"] = mapped_owner_id
        owner_projects.append(inserted_row)
        stats.projects_inserted += 1

    return project_map


def merge_applications(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    user_map: dict[int, int],
    project_map: dict[int, int],
    stats: MergeStats,
) -> dict[int, int]:
    target_apps = list(target_conn.execute("SELECT * FROM applications ORDER BY id"))
    by_key = {(int(row["project_id"]), int(row["applicant_id"])): row for row in target_apps}

    application_map: dict[int, int] = {}
    for source_application in source_conn.execute("SELECT * FROM applications ORDER BY id"):
        mapped_project_id = project_map.get(source_application["project_id"])
        mapped_applicant_id = user_map.get(source_application["applicant_id"])
        if not mapped_project_id or not mapped_applicant_id:
            continue

        key = (mapped_project_id, mapped_applicant_id)
        target_application = by_key.get(key)

        if target_application:
            updates: dict[str, Any] = {}
            if status_priority(source_application["status"]) > status_priority(target_application["status"]):
                updates["status"] = source_application["status"]
            if not normalize_text(target_application["assigned_role"]) and normalize_text(source_application["assigned_role"]):
                updates["assigned_role"] = source_application["assigned_role"]
            if not normalize_text(target_application["requested_role"]) and normalize_text(source_application["requested_role"]):
                updates["requested_role"] = source_application["requested_role"]
            if not normalize_text(target_application["message"]) and normalize_text(source_application["message"]):
                updates["message"] = source_application["message"]
            if parse_datetime_for_sort(source_application["created_at"]) < parse_datetime_for_sort(target_application["created_at"]):
                updates["created_at"] = source_application["created_at"]

            if updates:
                assignment = ", ".join(f"{column} = ?" for column in updates)
                target_conn.execute(
                    f"UPDATE applications SET {assignment} WHERE id = ?",
                    (*updates.values(), target_application["id"]),
                )
                refreshed = dict(target_application)
                refreshed.update(updates)
                target_application = refreshed
                by_key[key] = target_application
                stats.applications_updated += 1

            application_map[source_application["id"]] = int(target_application["id"])
            continue

        cursor = target_conn.execute(
            """
            INSERT INTO applications (project_id, applicant_id, message, status, assigned_role, requested_role, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mapped_project_id,
                mapped_applicant_id,
                source_application["message"],
                source_application["status"] or "new",
                source_application["assigned_role"],
                source_application["requested_role"],
                source_application["created_at"] or utc_now_iso(),
            ),
        )
        target_id = int(cursor.lastrowid)
        application_map[source_application["id"]] = target_id
        inserted_row = dict(source_application)
        inserted_row["id"] = target_id
        inserted_row["project_id"] = mapped_project_id
        inserted_row["applicant_id"] = mapped_applicant_id
        by_key[key] = inserted_row
        stats.applications_inserted += 1

    return application_map


def merge_notifications(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    user_map: dict[int, int],
    project_map: dict[int, int],
    application_map: dict[int, int],
    stats: MergeStats,
) -> None:
    target_notifications = list(target_conn.execute("SELECT * FROM notifications ORDER BY id"))
    signatures = {
        notification_signature(row["user_id"], row["type"], row["title"], row["message"], row["is_read"], row["related_project_id"], row["related_application_id"], row["created_at"])
        for row in target_notifications
    }

    for source_notification in source_conn.execute("SELECT * FROM notifications ORDER BY id"):
        mapped_user_id = user_map.get(source_notification["user_id"])
        if not mapped_user_id:
            continue
        mapped_project_id = project_map.get(source_notification["related_project_id"]) if source_notification["related_project_id"] else None
        mapped_application_id = application_map.get(source_notification["related_application_id"]) if source_notification["related_application_id"] else None
        signature = notification_signature(
            mapped_user_id,
            source_notification["type"],
            source_notification["title"],
            source_notification["message"],
            source_notification["is_read"],
            mapped_project_id,
            mapped_application_id,
            source_notification["created_at"],
        )
        if signature in signatures:
            continue

        target_conn.execute(
            """
            INSERT INTO notifications (
                user_id, type, title, message, is_read, related_project_id, related_application_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mapped_user_id,
                source_notification["type"],
                source_notification["title"],
                source_notification["message"],
                int(source_notification["is_read"] or 0),
                mapped_project_id,
                mapped_application_id,
                source_notification["created_at"] or utc_now_iso(),
            ),
        )
        signatures.add(signature)
        stats.notifications_inserted += 1


def merge_csv_text(target_value: str | None, source_value: str | None) -> str:
    return join_csv(split_csv(target_value) + split_csv(source_value))


def find_matching_project(owner_projects: list[sqlite3.Row | dict[str, Any]], source_project: sqlite3.Row) -> sqlite3.Row | dict[str, Any] | None:
    exact_matches = [
        row for row in owner_projects
        if normalize_text(row["title"]) == normalize_text(source_project["title"])
        and normalize_text(row["created_at"]) == normalize_text(source_project["created_at"])
    ]
    if exact_matches:
        return exact_matches[0]

    title_matches = [
        row for row in owner_projects
        if normalize_text(row["title"]) == normalize_text(source_project["title"])
    ]
    if len(title_matches) == 1:
        return title_matches[0]
    return None


def status_priority(status: str | None) -> int:
    return STATUS_PRIORITY.get((status or "new").strip().lower(), 0)


def notification_signature(
    user_id: int | None,
    notification_type: str | None,
    title: str | None,
    message: str | None,
    is_read: int | bool | None,
    related_project_id: int | None,
    related_application_id: int | None,
    created_at: str | None,
) -> tuple[Any, ...]:
    return (
        int(user_id) if user_id is not None else None,
        normalize_text(notification_type),
        normalize_text(title),
        normalize_text(message),
        int(bool(is_read)),
        int(related_project_id) if related_project_id is not None else None,
        int(related_application_id) if related_application_id is not None else None,
        normalize_text(created_at),
    )


def _copy_tree(source_dir: Path, target_dir: Path) -> int:
    if not source_dir.exists():
        return 0
    copied = 0
    for source_file in source_dir.rglob("*"):
        if source_file.is_dir():
            continue
        relative_path = source_file.relative_to(source_dir)
        target_file = target_dir / relative_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if target_file.exists() and file_hash(source_file) == file_hash(target_file):
            continue
        shutil.copy2(source_file, target_file)
        copied += 1
    return copied


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class MediaMapper:
    def __init__(self, source_media_dir: Path | None, target_media_dir: Path | None):
        self.source_media_dir = source_media_dir
        self.target_media_dir = target_media_dir
        self.copied_files = 0
        self._cache: dict[str, str] = {}

    def import_photo(self, photo_url: str | None, username: str | None) -> str | None:
        if not photo_url or not self.source_media_dir or not self.target_media_dir:
            return photo_url
        if photo_url in self._cache:
            return self._cache[photo_url]
        if not photo_url.startswith("/media/"):
            self._cache[photo_url] = photo_url
            return photo_url

        relative_path = Path(photo_url.removeprefix("/media/"))
        source_file = self.source_media_dir / relative_path
        if not source_file.exists():
            self._cache[photo_url] = photo_url
            return photo_url

        target_file = self.target_media_dir / relative_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if not target_file.exists():
            shutil.copy2(source_file, target_file)
            self.copied_files += 1
            mapped_url = f"/media/{relative_path.as_posix()}"
            self._cache[photo_url] = mapped_url
            return mapped_url

        if file_hash(source_file) == file_hash(target_file):
            mapped_url = f"/media/{relative_path.as_posix()}"
            self._cache[photo_url] = mapped_url
            return mapped_url

        stem = normalize_text(username) or relative_path.stem or "photo"
        candidate_name = f"{stem}_{source_file.stem}{source_file.suffix}"
        candidate_relative = relative_path.with_name(candidate_name)
        candidate_target = self.target_media_dir / candidate_relative
        counter = 1
        while candidate_target.exists():
            if file_hash(source_file) == file_hash(candidate_target):
                mapped_url = f"/media/{candidate_relative.as_posix()}"
                self._cache[photo_url] = mapped_url
                return mapped_url
            candidate_relative = relative_path.with_name(f"{stem}_{source_file.stem}_{counter}{source_file.suffix}")
            candidate_target = self.target_media_dir / candidate_relative
            counter += 1

        shutil.copy2(source_file, candidate_target)
        self.copied_files += 1
        mapped_url = f"/media/{candidate_relative.as_posix()}"
        self._cache[photo_url] = mapped_url
        return mapped_url
