from __future__ import annotations

import argparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import register_api_routes
from .app_state import FRONTEND_ASSETS, FRONTEND_DIST, LEGACY_INDEX_HTML
from .services import init_conversation_db, load_dotenv

app = FastAPI(title="KG Agent Manager", version="0.4.0")

if FRONTEND_ASSETS.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_ASSETS)), name="frontend-assets")

init_conversation_db()
register_api_routes(app)


@app.get("/")
def index() -> FileResponse:
    dist_index = FRONTEND_DIST / "index.html"
    if dist_index.exists():
        return FileResponse(dist_index)

    if LEGACY_INDEX_HTML.exists():
        return FileResponse(LEGACY_INDEX_HTML)

    raise HTTPException(status_code=500, detail="frontend index not found")


@app.get("/{file_path:path}")
def frontend_static(file_path: str) -> FileResponse:
    if not file_path or file_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="not found")

    candidate = FRONTEND_DIST / file_path
    if FRONTEND_DIST.exists() and candidate.exists() and candidate.is_file():
        return FileResponse(candidate)

    raise HTTPException(status_code=404, detail="not found")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FastAPI server for KG Agent Manager")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()

    load_dotenv(args.env_file)

    import uvicorn

    uvicorn.run("kg_agent.webapp:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
