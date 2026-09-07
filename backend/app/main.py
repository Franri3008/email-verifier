from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.exceptions.handlers import register_exception_handlers
from app.routes.api import router
from app.routes.accounts import router as accounts_router
from app.core.database import initialize
from app.core.security import cipher
from app.core.middleware import RequestProtection


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging(settings.log_level)
    cipher()
    if settings.production:
        if not settings.secure_cookies or not settings.public_url.startswith(
            "https://"
        ):
            raise RuntimeError(
                "Production requires HTTPS PUBLIC_URL and SECURE_COOKIES=true."
            )
        if not settings.database_url.startswith(
            ("postgres://", "postgresql://", "postgresql+psycopg://")
        ):
            raise RuntimeError("Production requires PostgreSQL.")
    initialize()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Email discovery and Verifalia verification API.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_exception_handlers(app)
app.add_middleware(RequestProtection)
app.include_router(router)
app.include_router(accounts_router)
if settings.static_dir:
    app.mount(
        "/",
        StaticFiles(directory=Path(settings.static_dir), html=True),
        name="frontend",
    )
