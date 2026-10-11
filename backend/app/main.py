import json
import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .config import get_settings
from .db import engine
from .routers import (alerts, audit_r, auth, clients, cloud, dashboard, events, finance, navi_r, ops, portal, protection, push, reports, routines, settings_r, users,
                      webhook, zabbix_r)
from .security import api_limiter, client_ip

st = get_settings()
BASE = st.NAVI_BASE_PATH.rstrip("/")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="NAVI — Orca TI", docs_url=None, redoc_url=None, openapi_url=None)

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.url.path.startswith(f"{BASE}/api/") and not request.url.path.endswith("/webhook/zabbix"):
        key = "api|" + client_ip(request)
        if api_limiter.blocked(key):
            return JSONResponse({"detail": "Limite de requisições excedido"}, status_code=429)
        api_limiter.hit(key)
    t0 = time.monotonic()
    resp = await call_next(request)
    dt = time.monotonic() - t0
    if dt > 2.0 and request.url.path.startswith(f"{BASE}/api/"):
        logging.getLogger("navi.slow").warning("requisicao lenta: %s %s levou %.1fs", request.method, request.url.path, dt)
    resp.headers.update({
        "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin",
        "Content-Security-Policy": CSP, "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains"})
    if request.url.path.startswith(f"{BASE}/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


for r in (auth, users, clients, zabbix_r, events, alerts, reports, routines, dashboard, settings_r, navi_r, audit_r, webhook, ops, portal, protection, finance, cloud, push):
    app.include_router(r.router, prefix=f"{BASE}/api")


@app.get(f"{BASE}/api/health")
def health():
    with engine.connect() as c:
        c.execute(text("select 1"))
    return {"status": "ok"}


@app.get(f"{BASE}/app/navi.apk")
def apk_download():
    f = Path(st.NAVI_STORAGE) / "app" / "navi.apk"
    if not f.is_file():
        return JSONResponse({"detail": "APK ainda não publicado"}, status_code=404)
    return FileResponse(f, media_type="application/vnd.android.package-archive", filename="NAVI.apk", headers={"Cache-Control": "no-cache"})


@app.get(f"{BASE}/app/version")
def apk_version():
    f = Path(st.NAVI_STORAGE) / "app" / "version.json"
    try:
        return JSONResponse(json.loads(f.read_text()), headers={"Cache-Control": "no-cache"})
    except Exception:  # noqa: BLE001
        return JSONResponse({"code": 0, "name": ""}, headers={"Cache-Control": "no-cache"})


STATIC = Path(__file__).resolve().parent.parent / "static"
if STATIC.exists():
    app.mount(f"{BASE}/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get(BASE)
    @app.get(f"{BASE}/{{path:path}}")
    def spa(path: str = ""):
        f = (STATIC / path).resolve()
        if path and f.is_file() and STATIC in f.parents:
            return FileResponse(f)
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
