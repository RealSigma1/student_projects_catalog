from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, MEDIA_DIR
from .database import init_db
from .errors import validation_exception_handler
from .routers.auth import router as auth_router
from .routers.notifications import router as notifications_router
from .routers.pages import router as pages_router
from .routers.profile import router as profile_router
from .routers.projects import router as projects_router


def create_app() -> FastAPI:
    init_db()

    app = FastAPI(title="Collaborative Platform for Student Projects")
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")

    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    app.include_router(auth_router)
    app.include_router(notifications_router)
    app.include_router(profile_router)
    app.include_router(projects_router)
    app.include_router(pages_router)
    return app


app = create_app()
