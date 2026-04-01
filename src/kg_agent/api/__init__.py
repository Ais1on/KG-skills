from fastapi import FastAPI

from .agents import router as agents_router
from .chat import router as chat_router
from .conversations import router as conversations_router
from .governance import router as governance_router
from .memory import router as memory_router
from .meta import router as meta_router
from .sandbox import router as sandbox_router
from .sessions import router as sessions_router
from .templates import router as templates_router


def register_api_routes(app: FastAPI) -> None:
    app.include_router(meta_router)
    app.include_router(agents_router)
    app.include_router(sessions_router)
    app.include_router(conversations_router)
    app.include_router(templates_router)
    app.include_router(governance_router)
    app.include_router(memory_router)
    app.include_router(sandbox_router)
    app.include_router(chat_router)
