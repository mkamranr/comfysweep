"""ComfySweep web application."""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import APP_NAME, __version__, auth, bootstrap, db, logbus, scheduler, settings
from .api import auth_routes, ops_routes, settings_routes

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
log = logging.getLogger("comfysweep")


def boot(start_scheduler=True):
    logbus.setup()
    db.connect().close()
    s = settings.load()
    logbus.set_keep(s.safety.log_keep)
    log.info("%s %s starting -- data=%s host=%s", APP_NAME, __version__,
             bootstrap.DATA_DIR, bootstrap.HOST_ROOT)
    if not os.path.isdir(bootstrap.HOST_ROOT):
        log.warning("host folder %s is not mounted -- add it in docker-compose.yml",
                    bootstrap.HOST_ROOT)
    if start_scheduler:
        scheduler.start()


@asynccontextmanager
async def lifespan(app):
    boot(start_scheduler=os.environ.get("COMFYSWEEP_NO_SCHEDULER") != "1")
    yield
    scheduler.stop()


app = FastAPI(title=APP_NAME, version=__version__, lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


app.include_router(ops_routes.router)
app.include_router(auth_routes.router)
app.include_router(settings_routes.router)


@app.get("/api/docs", include_in_schema=False)
def api_docs(user=Depends(auth.require_user)):
    return get_swagger_ui_html(openapi_url="/api/openapi.json",
                               title=APP_NAME + " API")


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api/"):
        detail = getattr(exc, "detail", "not found")
        return JSONResponse({"detail": detail}, status_code=404)
    return FileResponse(os.path.join(WEB, "index.html"))


if os.path.isdir(WEB):
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
