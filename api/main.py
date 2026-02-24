"""Lightweight Jump Test API - FastAPI app entry point."""
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.config import BASE_PATH
from api.db import init_db
from api.routers import auth, jump_tests, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Jump Test API",
    description="Submit jump test data (CMJ/DJ/SJ), get analysis results, and view historical data. User CRUD and MongoDB storage.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(jump_tests.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/admin", response_class=HTMLResponse)
def admin_panel():
    """Admin panel: create and manage users (CRUD) in real time."""
    path = Path(__file__).resolve().parent / "static" / "admin.html"
    return path.read_text(encoding="utf-8")


def _viewer_html() -> str:
    """Serve viewer with data-api-base so ?test_id= works."""
    path = Path(__file__).resolve().parent.parent / "web" / "viewer.html"
    html = path.read_text(encoding="utf-8")
    api_base = f"{BASE_PATH}/jump-tests"
    inject = (
        f'<div id="viewerContainer" data-api-base="{api_base}" style="display:none"></div>\n'
        '<script>(function(){ var c = document.getElementById("viewerContainer"); '
        f'if (!c) {{ c = document.createElement("div"); c.id = "viewerContainer"; '
        f'c.setAttribute("data-api-base", "{api_base}"); c.style.display = "none"; '
        'document.body.insertBefore(c, document.body.firstChild); } })();</script>\n  '
    )
    if "viewerContainer" not in html or f'data-api-base="{api_base}"' not in html:
        html = re.sub(r"<body(\s[^>]*)?>", r"<body\1>\n  " + inject, html, count=1)
    return html


@app.get("/viewer", response_class=HTMLResponse)
def viewer():
    """Jump test viewer. Use ?test_id=<id> to load a test from the API."""
    return _viewer_html()


@app.get("/my-tests", response_class=HTMLResponse)
def my_tests():
    """User-facing page: list jump tests for user_id (query param) with links to viewer."""
    path = Path(__file__).resolve().parent / "static" / "my-tests.html"
    html = path.read_text(encoding="utf-8")
    script = f'<script>window.__BASE_PATH__="{BASE_PATH}";</script>'
    html = html.replace("</head>", script + "\n</head>", 1)
    return html


# MkDocs documentation (build with: mkdocs build)
_site_dir = Path(__file__).resolve().parent.parent / "site"
if _site_dir.is_dir():
    @app.get("/documentation", include_in_schema=False)
    def _doc_redirect():
        return RedirectResponse(url="/documentation/index.html", status_code=302)
    app.mount("/documentation", StaticFiles(directory=str(_site_dir), html=True), name="documentation")
else:
    @app.get("/documentation")
    @app.get("/documentation/")
    def _doc_placeholder():
        return HTMLResponse(
            "<p>Documentation not built. Run <code>mkdocs build</code> in the project root, then restart the API.</p>",
            status_code=404,
        )
