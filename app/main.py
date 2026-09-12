"""FastAPI application factory.

Wiring only: build dependencies, mount routers and middleware.
No business logic lives here.
"""
import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.auth_router import router as auth_router
from app.api.conversation_router import router as conversation_router
from app.config import get_settings


def setup_logging() -> None:
    """Flow logging for the whole app under the 'insureagent.*' hierarchy.

    One knob: logging.getLogger('insureagent').setLevel(...) — INFO narrates
    every step (supervisor decisions, agent runs, tool calls, LLM calls).
    """
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%H:%M:%S")
    )
    root = logging.getLogger("insureagent")
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(logging.INFO)
    root.propagate = False
    # Route the gateway loggers into the same hierarchy/handler
    for legacy in ("llm_gateway", "tool_gateway"):
        lg = logging.getLogger(legacy)
        if not lg.handlers:
            lg.addHandler(handler)
        lg.setLevel(logging.INFO)
        lg.propagate = False


def create_app() -> FastAPI:
    setup_logging()
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
