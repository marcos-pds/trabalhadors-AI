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


def test_motion_projects_are_isolated_between_authenticated_accounts():
    with TemporaryDirectory() as directory:
        studio=create_app(database=Path(directory)/'studio.sqlite3')
        @studio.middleware('http')
        async def owner(request,call_next):
            request.state.motion_owner=request.headers.get('x-test-owner')
            return await call_next(request)
        root=FastAPI()
        root.mount('/api/motion-studio',studio)
        with TestClient(root) as client:
            first=client.post('/api/motion-studio/api/projects',headers={'x-test-owner':'alice'},
                              json={'title':'Projeto da Alice'}).json()
            second=client.post('/api/motion-studio/api/projects',headers={'x-test-owner':'bob'},
                               json={'title':'Projeto do Bob'}).json()
            alice={'x-test-owner':'alice'}
            bob={'x-test-owner':'bob'}
            assert [item['id'] for item in client.get('/api/motion-studio/api/projects',headers=alice).json()]==[first['id']]
            assert [item['id'] for item in client.get('/api/motion-studio/api/projects',headers=bob).json()]==[second['id']]
            assert client.get(f"/api/motion-studio/api/projects/{first['id']}",headers=bob).status_code==404
            assert client.put(f"/api/motion-studio/api/projects/{first['id']}",headers=bob,
                              json={'title':'Tomado','timeline':first['timeline']}).status_code==404


def test_storyboard_references_survive_project_save_and_reload():
    with TemporaryDirectory() as directory:
        root = FastAPI()
        root.mount("/api/motion-studio", create_app(database=Path(directory) / "studio.sqlite3"))
        with TestClient(root) as client:
            project = client.post("/api/motion-studio/api/projects", json={"title": "Série Lara"}).json()
            timeline = project["timeline"]
            timeline["storyboard"] = {
                "theme": "Lara recebe uma ligação misteriosa",
                "scenes": [{"scene": 1, "title": "O telefone", "prompt": "Vertical cinematic close-up"}],
                "references": [{"id": "lara", "kind": "character", "name": "Lara",
                                "prompt": "Character sheet", "source": "generated_brief"}],
                "episode_status": "draft",
            }
            response = client.put(f"/api/motion-studio/api/projects/{project['id']}",
                                  json={"title": project["title"], "summary": "", "timeline": timeline})
            assert response.status_code == 200, response.text
            loaded = client.get(f"/api/motion-studio/api/projects/{project['id']}").json()
            assert loaded["timeline"]["storyboard"]["references"][0]["name"] == "Lara"
            assert loaded["timeline"]["storyboard"]["scenes"][0]["scene"] == 1


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
