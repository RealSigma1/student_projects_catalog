import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _clear_app_modules() -> None:
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app.") or module_name == "main":
            sys.modules.pop(module_name, None)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("APP_DATA_DIR", str(runtime_dir))
    monkeypatch.setenv("DATABASE_PATH", str(runtime_dir / "projects.db"))
    monkeypatch.setenv("MEDIA_DIR", str(runtime_dir / "media"))
    monkeypatch.setenv("APP_SECRET", "test-secret")
    monkeypatch.setenv("ACCESS_TOKEN_TTL_HOURS", "72")
    monkeypatch.setenv("COOKIE_SECURE", "false")

    _clear_app_modules()
    app_module = importlib.import_module("app")

    with TestClient(app_module.app) as test_client:
        yield test_client

    _clear_app_modules()
