"""Actual local server/lifespan in disposable source and frozen-like layouts.

The frozen-like case validates __file__/_MEIPASS layout, not a PyInstaller build.
The installer owner's smoke test must still run the actual frozen executable.
"""
import os
from pathlib import Path
from queue import Empty, Queue
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
from threading import Thread

import httpx
import pytest

from desktop.backend_launcher import READY_PREFIX, SHUTDOWN_PATH


@pytest.mark.parametrize("frozen", [False, True], ids=["script", "frozen-layout"])
def test_actual_desktop_http_assets_data_and_graceful_shutdown(tmp_path, frozen):
    repository = Path(__file__).resolve().parents[1]
    bundle = tmp_path / "bundle"
    shutil.copytree(repository / "central", bundle / "central",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (bundle / "desktop").mkdir()
    shutil.copy2(repository / "desktop" / "backend_launcher.py", bundle / "desktop" / "backend_launcher.py")
    build = bundle / "static" / "build"
    build.mkdir(parents=True)
    (build / "index.html").write_text(
        '<html><body>desktop integration<script src="/assets/build/app.js"></script></body></html>',
        encoding="utf-8")
    (build / "app.js").write_text("console.log('bundled asset')", encoding="utf-8")
    data = tmp_path / "desktop-data"
    token = secrets.token_urlsafe(36)
    env = dict(os.environ, CENTRAL_DATA_DIR=str(data), CENTRAL_DESKTOP_SHUTDOWN_TOKEN=token,
               CENTRAL_DEPLOYMENT_MODE="server", CENTRAL_HOST="0.0.0.0", CENTRAL_JOB_MODE="api",
               CENTRAL_SECRET_KEY="invalid-inherited-web-key")
    env.pop("PYTHONPATH", None)
    args = [sys.executable, "-I", str(bundle / "desktop" / "backend_launcher.py")]
    if frozen:
        args = [sys.executable, "-I", "-c",
                "import runpy,sys; sys.frozen=True; sys._MEIPASS=sys.argv[1]; "
                "runpy.run_path(sys.argv[1]+'/desktop/backend_launcher.py',run_name='__main__')", str(bundle)]
    stdout = Queue()
    with (tmp_path / "stderr.log").open("w+", encoding="utf-8") as stderr:
        process = subprocess.Popen(args, cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=stderr,
                                   text=True, encoding="utf-8",
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        def read_output():
            for line in process.stdout:
                stdout.put(line.strip())
            stdout.put(None)

        reader = Thread(target=read_output, daemon=True)
        reader.start()
        try:
            url = None
            for _ in range(40):
                try:
                    line = stdout.get(timeout=2)
                except Empty:
                    if process.poll() is not None:
                        break
                    continue
                if line is None:
                    break
                if line.startswith(READY_PREFIX):
                    url = line[len(READY_PREFIX):]
                    break
            stderr.flush()
            assert url, (tmp_path / "stderr.log").read_text(encoding="utf-8")
            assert url.startswith("http://127.0.0.1:")
            with httpx.Client(base_url=url, timeout=5, trust_env=False) as client:
                health = client.get("api/health/ready")
                assert health.status_code == 200
                assert health.json()["database"] == "ready"
                assert health.json()["job_executor"] == "embedded"
                assert "desktop integration" in client.get("/").text
                assert client.get("assets/build/app.js").text == "console.log('bundled asset')"
                assert client.post(SHUTDOWN_PATH).status_code == 403
                assert process.poll() is None
                with sqlite3.connect(data / "central.sqlite3") as db:
                    assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
                    assert db.execute("SELECT COUNT(*) FROM worker_liveness").fetchone()[0] == 1
                response = client.post(SHUTDOWN_PATH, headers={"X-Central-Desktop-Token": token})
                assert response.status_code == 202
            assert process.wait(timeout=15) == 0
            with sqlite3.connect(data / "central.sqlite3") as db:
                # The real lifespan/dispatcher cleanup removes its heartbeat.
                assert db.execute("SELECT COUNT(*) FROM worker_liveness").fetchone()[0] == 0
                assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert (data / "secret.key").is_file()
            assert not (bundle / "data").exists()
            port = int(url.rstrip("/").rsplit(":", 1)[1])
            with socket.socket() as probe:
                probe.settimeout(2)
                assert probe.connect_ex(("127.0.0.1", port)) != 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            reader.join(timeout=2)
            process.stdout.close()
