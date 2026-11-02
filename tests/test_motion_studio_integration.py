import re
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from central.main import SEC, app
from desktop.motion_studio.apps.api.main import create_app


def test_motion_studio_api_is_mounted_inside_central_and_requires_login(monkeypatch):
    with TestClient(app) as client:
        unauthorized = client.get("/api/motion-studio/api/health")
    assert unauthorized.status_code == 401

    monkeypatch.setattr(SEC, "user", lambda _request: {"id": "test", "email": "test@example.test"})
    with TestClient(app) as client:
        response = client.get("/api/motion-studio/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ready"}


def test_motion_studio_project_api_works_at_embedded_prefix():
    with TemporaryDirectory() as directory:
        root = FastAPI()
        root.mount(
            "/api/motion-studio",
            create_app(database=Path(directory) / "studio.sqlite3"),
        )
        with TestClient(root) as client:
            created = client.post(
                "/api/motion-studio/api/projects",
                json={"title": "Embedded smoke", "summary": ""},
            )
            assert created.status_code == 201
            project = created.json()

            response = client.get(
                f"/api/motion-studio/api/projects/{project['id']}"
            )

    assert response.status_code == 200
    assert response.json()["title"] == "Embedded smoke"


def test_motion_studio_built_assets_are_served_from_embedded_path():
    index = Path(__file__).resolve().parents[1] / "static" / "motion-studio" / "index.html"
    if not index.is_file():
        pytest.skip("Run npm run build to create the embedded Motion Studio frontend.")

    with TestClient(app) as client:
        response = client.get("/motion-studio/")
        assert response.status_code == 200
        assets = re.findall(r'(?:src|href)="(/motion-studio/assets/[^"]+)"', response.text)
        assert assets
        for asset in assets:
            assert client.get(asset).status_code == 200
