"""Private localhost handshake for safe desktop upgrades.

No route is exposed at all unless Electron supplied a per-process secret.
This secret never reaches the browser/preload or a static file.
"""
import os
import secrets
import threading
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

ACTIVE = ("queued", "running", "awaiting_approval", "awaiting_integration")
_lock = threading.RLock()
_preparing = False


def install_desktop_update_routes(app, db):
    token = os.environ.get("CENTRAL_DESKTOP_UPDATE_TOKEN", "")
    if not token or len(token) < 32:
        return

    def authorize(request: Request):
        address = request.client.host if request.client else ""
        received = request.headers.get("x-central-desktop-token", "")
        if address not in ("127.0.0.1", "::1") or not secrets.compare_digest(received, token):
            # Keep this endpoint indistinguishable from nonexistent paths.
            raise HTTPException(404, "Not Found")

    def count_active():
        return db.one(
            "SELECT COUNT(*) AS count FROM runs WHERE status IN (?,?,?,?)",
            ACTIVE,
        )["count"]

    @app.middleware("http")
    async def desktop_update_write_guard(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if not request.url.path.startswith("/api/internal/desktop-update/"):
                with _lock:
                    if _preparing:
                        return JSONResponse({"detail": "Atualização do desktop em preparação."}, status_code=503)
        return await call_next(request)

    @app.get("/api/internal/desktop-update/status", include_in_schema=False)
    def desktop_update_status(request: Request):
        authorize(request)
        with _lock:
            count = count_active()
            return {"safe": count == 0 and not _preparing, "active": count, "preparing": _preparing}

    @app.post("/api/internal/desktop-update/prepare", include_in_schema=False)
    def desktop_update_prepare(request: Request):
        authorize(request)
        global _preparing
        with _lock:
            count = count_active()
            if count:
                raise HTTPException(409, f"Há {count} tarefa(s) ativas ou aguardando aprovação.")
            _preparing = True
            return {"safe": True}

    @app.post("/api/internal/desktop-update/cancel", include_in_schema=False)
    def desktop_update_cancel(request: Request):
        authorize(request)
        global _preparing
        with _lock:
            _preparing = False
        return {"ok": True}
