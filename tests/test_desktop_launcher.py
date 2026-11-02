"""Desktop must reserve a loopback-only port without disturbing web 8765."""
import asyncio
import os
import socket
import sys
from types import SimpleNamespace

import httpx
import pytest

from desktop import backend_launcher as launcher
from desktop.backend_launcher import READY_PREFIX, reserve_loopback


def test_desktop_listener_is_loopback():
    listener, port = reserve_loopback()
    try:
        assert listener.getsockname()[0] == "127.0.0.1"
        assert 0 < port < 65536
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass
    finally:
        listener.close()


def test_two_instances_cannot_claim_the_same_bound_port():
    a, first = reserve_loopback()
    b, second = reserve_loopback()
    try:
        assert first != second
        assert READY_PREFIX == "CENTRAL_DESKTOP_READY="
    finally:
        a.close()
        b.close()


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    build = root / "static" / "build"
    build.mkdir(parents=True)
    (build / "app.js").write_text("console.log('desktop')", encoding="utf-8")
    (build / "index.html").write_text(
        '<html><script src="/assets/build/app.js"></script></html>', encoding="utf-8")
    studio = root / "static" / "motion-studio"
    (studio / "assets").mkdir(parents=True)
    (studio / "assets" / "app.js").write_text("console.log('motion-studio')", encoding="utf-8")
    (studio / "index.html").write_text(
        '<html><script src="/motion-studio/assets/app.js"></script></html>', encoding="utf-8")
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(launcher, "__file__", str(root / "desktop" / "backend_launcher.py"))
    monkeypatch.setenv("CENTRAL_DATA_DIR", str(tmp_path / "desktop-data"))
    monkeypatch.delenv("CENTRAL_DESKTOP_SHUTDOWN_TOKEN", raising=False)
    return root


@pytest.mark.parametrize("frozen", [False, True])
def test_source_and_frozen_layouts_resolve_assets_and_isolate_environment(runtime, monkeypatch, frozen):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(runtime), raising=False)
    for key in ("CENTRAL_SECRET_KEY", "CENTRAL_PUBLIC_ORIGIN",
                "CENTRAL_ALLOW_REGISTRATION", "CENTRAL_WORKTREE_REVIEWS_ENABLED"):
        monkeypatch.setenv(key, "inherited-web-setting")
    monkeypatch.setenv("CENTRAL_DEPLOYMENT_MODE", "server")
    monkeypatch.setenv("CENTRAL_JOB_MODE", "api")
    root, data = launcher.prepare_runtime()
    assert root == runtime
    assert str(root) in sys.path
    assert data != root / "data" and not data.exists()
    assert os.environ["CENTRAL_DEPLOYMENT_MODE"] == "local"
    assert os.environ["CENTRAL_JOB_MODE"] == "embedded"
    assert os.environ["CENTRAL_HOST"] == "127.0.0.1"
    assert "CENTRAL_SECRET_KEY" not in os.environ
    assert "CENTRAL_PUBLIC_ORIGIN" not in os.environ


@pytest.mark.parametrize("data", [None, "", "relative-data", "web-data"])
def test_invalid_or_web_data_directory_fails_before_import(runtime, monkeypatch, data):
    if data is None:
        monkeypatch.delenv("CENTRAL_DATA_DIR")
    else:
        monkeypatch.setenv("CENTRAL_DATA_DIR", str(runtime / "data") if data == "web-data" else data)
    with pytest.raises(RuntimeError, match="data|DATA_DIR"):
        launcher.prepare_runtime()
    assert not (runtime / "data").exists()


def test_frozen_data_cannot_be_written_into_bundle(runtime, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(runtime), raising=False)
    monkeypatch.setenv("CENTRAL_DATA_DIR", str(runtime / "elsewhere"))
    with pytest.raises(RuntimeError, match="separate"):
        launcher.prepare_runtime()


@pytest.mark.parametrize("missing", ["index.html", "app.js", "studio-index.html", "studio-app.js"])
def test_missing_packaged_assets_fail_before_startup(runtime, missing):
    if missing.startswith("studio-"):
        asset = missing.removeprefix("studio-")
        path = runtime / "static" / "motion-studio" / ("assets" if asset == "app.js" else "") / asset
    else:
        path = runtime / "static" / "build" / missing
    path.unlink()
    with pytest.raises(RuntimeError, match="frontend"):
        launcher.prepare_runtime()


def test_cooperative_shutdown_requires_loopback_token_and_post():
    async def scenario():
        stops = []

        async def web_app(scope, receive, send):
            from starlette.responses import Response
            await Response(status_code=404)(scope, receive, send)

        control = launcher.DesktopControl(web_app, "x" * 48, lambda: stops.append(True))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=control),
                                     base_url="http://127.0.0.1") as client:
            assert (await client.post(launcher.SHUTDOWN_PATH)).status_code == 403
            headers = {"X-Central-Desktop-Token": "x" * 48}
            assert (await client.get(launcher.SHUTDOWN_PATH, headers=headers)).status_code == 405
            assert (await client.post(launcher.SHUTDOWN_PATH, headers=headers)).status_code == 202
            assert stops == [True]
        remote = httpx.ASGITransport(app=control, client=("192.0.2.1", 1000))
        async with httpx.AsyncClient(transport=remote, base_url="http://127.0.0.1") as client:
            assert (await client.post(launcher.SHUTDOWN_PATH, headers=headers)).status_code == 403
        assert stops == [True]

    asyncio.run(scenario())


@pytest.mark.parametrize("stop", ["timeout", "cancel", "early_exit"])
def test_server_failures_and_cancellation_stop_owned_task_and_close_database(
        runtime, monkeypatch, capsys, stop):
    import uvicorn

    events = []
    monkeypatch.setitem(sys.modules, "central.main", SimpleNamespace(
        app=object(), DB=SimpleNamespace(close=lambda: events.append("db_closed"))))

    class Server:
        def __init__(self, config):
            self.started = False
            self.should_exit = False

        async def serve(self, sockets):
            self.started = True
            try:
                if stop == "early_exit":
                    return
                while not self.should_exit:
                    await asyncio.sleep(0.001)
            finally:
                events.append("server_stopped")

    monkeypatch.setattr(uvicorn, "Server", Server)

    async def scenario():
        checked = asyncio.Event()

        async def ready(port):
            checked.set()
            if stop == "timeout":
                raise RuntimeError("unhealthy database")

        monkeypatch.setattr(launcher, "check_ready", ready)
        task = asyncio.create_task(launcher.serve_desktop(startup_timeout=0.15, shutdown_timeout=0.1))
        if stop == "cancel":
            await asyncio.wait_for(checked.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(RuntimeError, match="timed out|before startup"):
                await task
        assert events == ["server_stopped", "db_closed"]
        if stop != "cancel":
            assert READY_PREFIX not in capsys.readouterr().out

    asyncio.run(scenario())
