"""Archiviator FastAPI application factory and uvicorn entry point."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.config import get_settings
from app.database import run_migrations
from app.routers import auth, entities

BACKEND_DIR = Path(__file__).resolve().parent.parent


class SPAStaticFiles(StaticFiles):
    """Static files with index.html fallback for client-side (SPA) routes."""

    async def get_response(self, path: str, scope):
        # Unknown /api paths must stay JSON 404s, never fall back to the SPA shell.
        # StaticFiles runs the path through os.path.normpath, so on Windows the
        # separator is "\" — normalize before inspecting the first segment.
        is_api = path.replace("\\", "/").split("/", 1)[0] == "api"
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not is_api:
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404 and not is_api:
            response = await super().get_response("index.html", scope)
        return response


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        run_migrations()
        yield

    app = FastAPI(
        title="Archiviator",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'"
        )
        return response

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok", "app": "archiviator", "version": __version__}

    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(entities.router, prefix="/api/v1/entities", tags=["entities"])

    # Production: serve the built frontend as an SPA (non-/api paths fall back to index.html).
    frontend_dist = BACKEND_DIR.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", SPAStaticFiles(directory=str(frontend_dist), html=True), name="spa")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port)
