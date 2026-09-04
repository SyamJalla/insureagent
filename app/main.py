"""FastAPI application factory.

Wiring only: build dependencies, mount routers and middleware.
No business logic lives here.
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.auth_router import router as auth_router
from app.api.conversation_router import router as conversation_router
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="InsureAgent", version="0.1.0")
    app.include_router(auth_router)
    app.include_router(conversation_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Routers mounted here as they are built (auth, conversations).
    # Guardrails middleware (Krishna) slots in here, after auth.
    app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
    return app


app = create_app()
