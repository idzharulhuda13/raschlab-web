import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import check_db

APP_VERSION = "0.1.0"

app = FastAPI(
    title="RaschLab",
    docs_url="/docs" if settings.app_env.lower() == "dev" else None,
    redoc_url="/redoc" if settings.app_env.lower() == "dev" else None,
    openapi_url="/openapi.json" if settings.app_env.lower() == "dev" else None,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR = BASE_DIR / "templates"
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    if not settings.gate_open:
        return templates.TemplateResponse(request=request, name="gate.html", status_code=200)
    return RedirectResponse(url="/register", status_code=307)


@app.get("/health")
def health():
    git_commit = os.getenv("GIT_COMMIT")
    commit = git_commit[:7] if git_commit else "dev"
    return {
        "status": "ok",
        "version": APP_VERSION,
        "commit": commit,
    }


@app.get("/health/db")
def health_db():
    status, detail = check_db()
    data = {"db": status}
    if detail is not None:
        data["detail"] = detail
    return data
