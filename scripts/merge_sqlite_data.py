from __future__ import annotations

import argparse
from pathlib import Path

from app.merge_sqlite import backup_database, merge_sqlite_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge a local and a server SQLite database for StudCollab without dropping existing data.",
    )
    parser.add_argument("--source-db", required=True, help="Path to the source database.")
    parser.add_argument("--target-db", required=True, help="Path to the target database.")
    parser.add_argument("--source-media", help="Source media directory.")
    parser.add_argument("--target-media", help="Target media directory.")
    parser.add_argument("--backup-dir", help="Directory for target database backups.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_db = Path(args.source_db)
    target_db = Path(args.target_db)
    source_media = Path(args.source_media) if args.source_media else None
    target_media = Path(args.target_media) if args.target_media else None
    backup_dir = Path(args.backup_dir) if args.backup_dir else None

    if not source_db.exists():
        raise SystemExit(f"Source database not found: {source_db}")
    if not target_db.exists():
        raise SystemExit(f"Target database not found: {target_db}")

    backup_path = backup_database(target_db, backup_dir)
    stats = merge_sqlite_data(
        source_db=source_db,
        target_db=target_db,
        source_media_dir=source_media,
        target_media_dir=target_media,
    )

    print("Merge completed.")
    print(f"Database backup: {backup_path}")
    print(
        "Users: +{0.users_inserted}, updated {0.users_updated}\n"
        "Projects: +{0.projects_inserted}, updated {0.projects_updated}\n"
        "Applications: +{0.applications_inserted}, updated {0.applications_updated}\n"
        "Notifications: +{0.notifications_inserted}\n"
        "Media files copied: {0.media_copied}".format(stats)
    )


if __name__ == "__main__":
    main()
