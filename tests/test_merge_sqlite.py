import sqlite3
from pathlib import Path

from app.merge_sqlite import merge_sqlite_data


def setup_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE users (
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

        CREATE TABLE projects (
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

        CREATE TABLE applications (
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

        CREATE TABLE notifications (
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
    return conn


def test_merge_sqlite_data_preserves_target_and_imports_local_data(tmp_path: Path):
    source_db = tmp_path / "source.db"
    target_db = tmp_path / "target.db"
    source_media = tmp_path / "source_media"
    target_media = tmp_path / "target_media"
    (source_media / "profile_photos").mkdir(parents=True)
    target_media.mkdir(parents=True)
    (source_media / "profile_photos" / "alice.png").write_bytes(b"alice-photo")

    source_conn = setup_db(source_db)
    target_conn = setup_db(target_db)

    target_conn.execute(
        """
        INSERT INTO users (id, username, email, hashed_password, full_name, bio, skills, roles, links, photo_url, created_at)
        VALUES (1, 'alice', 'alice@example.com', 'hash-a', 'Alice Server', NULL, 'backend', '', '', NULL, '2026-05-01T00:00:00+00:00')
        """
    )
    target_conn.execute(
        """
        INSERT INTO users (id, username, email, hashed_password, full_name, bio, skills, roles, links, photo_url, created_at)
        VALUES (2, 'bob', 'bob@example.com', 'hash-b', NULL, NULL, '', '', '', NULL, '2026-05-01T00:00:00+00:00')
        """
    )
    target_conn.execute(
        """
        INSERT INTO projects (
            id, title, description, tags, required_roles, github_url, demo_url, contact_info,
            status, applications_open, created_at, updated_at, owner_id
        )
        VALUES (1, 'Shared Project', 'server desc', 'api', 'backend', NULL, NULL, NULL, 'active', 1,
            '2026-05-01T00:00:00+00:00', '2026-05-01T00:00:00+00:00', 1)
        """
    )
    target_conn.execute(
        """
        INSERT INTO projects (
            id, title, description, tags, required_roles, github_url, demo_url, contact_info,
            status, applications_open, created_at, updated_at, owner_id
        )
        VALUES (2, 'Server Only', 'server only project', '', '', NULL, NULL, NULL, 'active', 1,
            '2026-05-02T00:00:00+00:00', '2026-05-02T00:00:00+00:00', 1)
        """
    )
    target_conn.execute(
        """
        INSERT INTO applications (id, project_id, applicant_id, message, status, assigned_role, requested_role, created_at)
        VALUES (1, 1, 2, 'server draft', 'new', NULL, NULL, '2026-05-02T12:00:00+00:00')
        """
    )
    target_conn.commit()

    source_conn.execute(
        """
        INSERT INTO users (id, username, email, hashed_password, full_name, bio, skills, roles, links, photo_url, created_at)
        VALUES (1, 'alice', 'alice@example.com', 'hash-a2', 'Alice Local', 'Bio', 'design', 'lead', 'https://t.me/alice',
            '/media/profile_photos/alice.png', '2026-05-02T00:00:00+00:00')
        """
    )
    source_conn.execute(
        """
        INSERT INTO users (id, username, email, hashed_password, full_name, bio, skills, roles, links, photo_url, created_at)
        VALUES (2, 'bob', 'bob@example.com', 'hash-b2', 'Bob Local', NULL, '', '', '', NULL, '2026-05-02T00:00:00+00:00')
        """
    )
    source_conn.execute(
        """
        INSERT INTO projects (
            id, title, description, tags, required_roles, github_url, demo_url, contact_info,
            status, applications_open, created_at, updated_at, owner_id
        )
        VALUES (1, 'Shared Project', 'source desc', 'design', 'frontend', NULL, NULL, '@alice', 'archived', 0,
            '2026-05-01T00:00:00+00:00', '2026-05-03T00:00:00+00:00', 1)
        """
    )
    source_conn.execute(
        """
        INSERT INTO projects (
            id, title, description, tags, required_roles, github_url, demo_url, contact_info,
            status, applications_open, created_at, updated_at, owner_id
        )
        VALUES (2, 'Local Only', 'new local project', 'ml', 'analyst', NULL, NULL, '@alice', 'active', 1,
            '2026-05-03T00:00:00+00:00', '2026-05-03T00:00:00+00:00', 1)
        """
    )
    source_conn.execute(
        """
        INSERT INTO applications (id, project_id, applicant_id, message, status, assigned_role, requested_role, created_at)
        VALUES (1, 1, 2, 'join source', 'accepted', 'frontend', 'frontend', '2026-05-02T12:00:00+00:00')
        """
    )
    source_conn.execute(
        """
        INSERT INTO notifications (
            id, user_id, type, title, message, is_read, related_project_id, related_application_id, created_at
        )
        VALUES (1, 1, 'new_application', 'Новый отклик', 'Появился отклик', 0, 1, 1, '2026-05-03T12:00:00+00:00')
        """
    )
    source_conn.commit()
    source_conn.close()
    target_conn.close()

    stats = merge_sqlite_data(
        source_db=source_db,
        target_db=target_db,
        source_media_dir=source_media,
        target_media_dir=target_media,
    )

    merged = sqlite3.connect(target_db)
    merged.row_factory = sqlite3.Row

    users = list(merged.execute("SELECT * FROM users ORDER BY id"))
    assert len(users) == 2
    alice = merged.execute("SELECT * FROM users WHERE username = 'alice'").fetchone()
    assert alice["full_name"] == "Alice Server"
    assert set(alice["skills"].split(",")) == {"backend", "design"}
    assert set(alice["roles"].split(",")) == {"lead"}
    assert alice["photo_url"].startswith("/media/profile_photos/")
    assert (target_media / Path(alice["photo_url"].removeprefix("/media/"))).exists()

    projects = list(merged.execute("SELECT * FROM projects ORDER BY id"))
    assert len(projects) == 3
    shared = merged.execute("SELECT * FROM projects WHERE title = 'Shared Project'").fetchone()
    assert shared["status"] == "active"
    assert set(shared["tags"].split(",")) == {"api", "design"}
    assert set(shared["required_roles"].split(",")) == {"backend", "frontend"}
    assert shared["contact_info"] == "@alice"
    assert merged.execute("SELECT COUNT(*) FROM projects WHERE title = 'Local Only'").fetchone()[0] == 1
    assert merged.execute("SELECT COUNT(*) FROM projects WHERE title = 'Server Only'").fetchone()[0] == 1

    applications = list(merged.execute("SELECT * FROM applications"))
    assert len(applications) == 1
    assert applications[0]["status"] == "accepted"
    assert applications[0]["assigned_role"] == "frontend"
    assert applications[0]["message"] == "server draft"

    notifications = list(merged.execute("SELECT * FROM notifications"))
    assert len(notifications) == 1
    assert notifications[0]["title"] == "Новый отклик"

    assert stats.users_updated == 2
    assert stats.projects_inserted == 1
    assert stats.applications_updated == 1
    assert stats.notifications_inserted == 1
    assert stats.media_copied == 1
