import os
import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env_file()

APP_DATA_DIR = Path(os.getenv("APP_DATA_DIR", str(BASE_DIR))).resolve()
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(APP_DATA_DIR / "projects.db"))).resolve()
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", str(APP_DATA_DIR / "media"))).resolve()
PROFILE_PHOTOS_DIR = MEDIA_DIR / "profile_photos"
PROFILE_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

SECRET_KEY = os.getenv("APP_SECRET", "change-me-in-env")
ACCESS_TOKEN_TTL_HOURS = int(os.getenv("ACCESS_TOKEN_TTL_HOURS", "72"))
MAX_PROFILE_PHOTO_BYTES = int(os.getenv("MAX_PROFILE_PHOTO_BYTES", str(5 * 1024 * 1024)))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")

ALLOWED_PROFILE_PHOTO_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
