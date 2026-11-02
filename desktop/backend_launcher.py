"""Bundled local Python server entry point for the Windows desktop shell.

The web entrypoint stays unchanged. Listening only on 127.0.0.1 using a
pre-bound, dynamically allocated port avoids conflict with the web server.
"""
import asyncio
from html.parser import HTMLParser
import os
from pathlib import Path
import secrets
import socket
import sys
from urllib.parse import unquote, urlsplit

READY_PREFIX = "CENTRAL_DESKTOP_READY="
SHUTDOWN_PATH = "/__desktop/shutdown"


def prepare_runtime():
    """Resolve PyInstaller resources without ever falling back to Web data."""
    frozen = bool(getattr(sys, "frozen", False))
    root = (Path(sys._MEIPASS) if frozen else Path(__file__).resolve().parent.parent).resolve()
    value = os.environ.get("CENTRAL_DATA_DIR", "")
    if not value or not Path(value).is_absolute():
        raise RuntimeError("Desktop requires an explicit absolute CENTRAL_DATA_DIR")
    data = Path(value).resolve()
    if data == root / "data" or (frozen and data.is_relative_to(root)):
        raise RuntimeError("Desktop data must be separate from Web/bundled resources")
    token = os.environ.get("CENTRAL_DESKTOP_SHUTDOWN_TOKEN")
    if token is not None and (not token.isascii() or not 32 <= len(token) <= 256):
        raise RuntimeError("Desktop shutdown token must contain 32-256 ASCII characters")
    validate_assets(root)
    # Script execution sets sys.path[0] to desktop/, not the repository root.
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.environ.update(CENTRAL_DATA_DIR=str(data), CENTRAL_DEPLOYMENT_MODE="local",
                      CENTRAL_HOST="127.0.0.1", CENTRAL_JOB_MODE="embedded")
    for key in ("CENTRAL_SECRET_KEY", "CENTRAL_PUBLIC_ORIGIN",
                "CENTRAL_ALLOW_REGISTRATION", "CENTRAL_WORKTREE_REVIEWS_ENABLED"):
        os.environ.pop(key, None)
    return root, data


def validate_assets(root):
    """Match central.main's ROOT/static mapping in source and frozen layouts."""
    static = root / "static"
    index = static / "build" / "index.html"
    if not index.is_file():
        raise RuntimeError("Desktop frontend missing: static/build/index.html")

    class References(HTMLParser):
        def handle_starttag(self, tag, attrs):
            for name, value in attrs:
                if name not in ("src", "href") or not value:
                    continue
                path = unquote(urlsplit(value).path)
                if path.startswith("/assets/"):
                    resource = (static / path[len("/assets/"):]).resolve()
                    if not resource.is_relative_to(static.resolve()) or not resource.is_file():
                        raise RuntimeError("Desktop frontend asset missing or outside static directory")

    References().feed(index.read_text(encoding="utf-8"))


class DesktopControl:
    """Desktop-only, authenticated cooperative stop; the Web app is unchanged."""

    def __init__(self, app, token, stop):
        self.app, self.token, self.stop = app, token, stop

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != SHUTDOWN_PATH or not self.token:
            return await self.app(scope, receive, send)
        from starlette.responses import JSONResponse
        headers = dict(scope.get("headers", []))
        authorized = (scope.get("client", (None,))[0] == "127.0.0.1" and
                      secrets.compare_digest(headers.get(b"x-central-desktop-token", b""),
                                             self.token.encode("ascii")))
        if not authorized:
            response = JSONResponse({"status": "forbidden"}, status_code=403)
        elif scope["method"] != "POST":
            response = JSONResponse({"status": "method_not_allowed"}, status_code=405)
        else:
            self.stop()
            response = JSONResponse({"status": "stopping"}, status_code=202)
        await response(scope, receive, send)


async def check_ready(port):
    import httpx
    async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
        origin = f"http://127.0.0.1:{port}"
        health = await client.get(origin + "/api/health/ready")
        health.raise_for_status()
        payload = health.json()
        if payload.get("status") != "ready" or payload.get("database") != "ready":
            raise RuntimeError("Desktop database is not ready")
        page = await client.get(origin + "/")
        page.raise_for_status()
        if "<html" not in page.text.lower():
            raise RuntimeError("Desktop frontend is not ready")


def reserve_loopback():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        return sock, sock.getsockname()[1]
    except BaseException:
        sock.close()
        raise


async def serve_desktop(*, startup_timeout=45, shutdown_timeout=10):
    prepare_runtime()
    import uvicorn
    from central.main import app, DB

    sock, port = reserve_loopback()
    task = None
    try:
        control = DesktopControl(app, os.environ.get("CENTRAL_DESKTOP_SHUTDOWN_TOKEN"),
                                 lambda: setattr(server, "should_exit", True))
        server = uvicorn.Server(uvicorn.Config(
            control, host="127.0.0.1", port=port, lifespan="on",
            timeout_graceful_shutdown=shutdown_timeout,
            access_log=False, log_level="warning"))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        deadline = asyncio.get_running_loop().time() + startup_timeout
        while asyncio.get_running_loop().time() < deadline:
            if task.done():
                await task
                raise RuntimeError("Desktop server exited before startup")
            if server.started:
                try:
                    await check_ready(port)
                except Exception:
                    pass
                else:
                    print(f"{READY_PREFIX}http://127.0.0.1:{port}/", flush=True)
                    # Shield preserves Uvicorn's lifespan task on cancellation.
                    await asyncio.shield(task)
                    return
            await asyncio.sleep(0.05)
        raise RuntimeError("Desktop startup timed out")
    finally:
        try:
            if task is not None and not task.done():
                server.should_exit = True
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=shutdown_timeout + 1)
                except asyncio.TimeoutError:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            elif task is not None:
                await asyncio.gather(task, return_exceptions=True)
        finally:
            sock.close()
            DB.close()


def main():
    try:
        asyncio.run(serve_desktop())
        return 0
    except KeyboardInterrupt:
        return 0
    except BaseException as exc:
        print("CENTRAL_DESKTOP_ERROR=" + type(exc).__name__,
              file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
