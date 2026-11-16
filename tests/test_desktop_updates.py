"""Security tests for local desktop update gate (separate from the web API)."""
import asyncio
import httpx
from fastapi import FastAPI
from central import desktop_updates


class FakeDB:
    def __init__(self):
        self.active = 0

    def one(self, sql, args=()):
        assert "FROM runs" in sql
        assert len(args) == 4
        return {"count": self.active}


def test_desktop_gate_requires_local_token_and_refuses_running_jobs(monkeypatch):
    token = "abc1234567890" * 5
    monkeypatch.setenv("CENTRAL_DESKTOP_UPDATE_TOKEN", token)
    monkeypatch.setattr(desktop_updates, "_preparing", False)
    app = FastAPI()
    db = FakeDB()
    desktop_updates.install_desktop_update_routes(app, db)

    @app.post("/api/runs")
    def run():
        return {"started": True}

    async def simulate():
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            path = "/api/internal/desktop-update/"
            auth = {"x-central-desktop-token": token}
            assert (await client.get(path + "status")).status_code == 404
            assert (await client.get(path + "status", headers=auth)).json()["safe"] is True
            db.active = 1
            response = await client.post(path + "prepare", headers=auth)
            assert response.status_code == 409
            assert (await client.post("/api/runs")).status_code == 200
            db.active = 0
            assert (await client.post(path + "prepare", headers=auth)).status_code == 200
            assert (await client.post("/api/runs")).status_code == 503
            assert (await client.post(path + "cancel", headers=auth)).status_code == 200
            assert (await client.post("/api/runs")).status_code == 200

    asyncio.run(simulate())


def test_web_only_deployments_have_no_desktop_update_endpoint(monkeypatch):
    monkeypatch.delenv("CENTRAL_DESKTOP_UPDATE_TOKEN", raising=False)
    app = FastAPI()
    desktop_updates.install_desktop_update_routes(app, FakeDB())

    async def simulate():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/api/internal/desktop-update/status")).status_code == 404

    asyncio.run(simulate())
