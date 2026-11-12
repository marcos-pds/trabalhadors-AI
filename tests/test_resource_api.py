"""API smoke coverage for authenticated read-only host diagnostics."""
import uuid

from fastapi.testclient import TestClient

from central.main import app
from central import resource_telemetry


def test_local_resources_require_login_and_return_no_paths(monkeypatch):
    monkeypatch.setenv("CENTRAL_MOTION_WORKER", "0")
    def fake_snapshot(data_dir, *, reservations=None):
        assert reservations is not None
        return {
            "scope": "host_snapshot",
            "ram": {"status": "available", "total_mib": 16000, "available_mib": 8000},
            "gpu": {"status": "unavailable", "devices": []},
            "disk": {"status": "unavailable"},
            "reservations": reservations.snapshot(),
        }
    monkeypatch.setattr(resource_telemetry, "host_resource_snapshot", fake_snapshot)
    with TestClient(app) as client:
        anon = client.get("/api/system/resources")
        assert anon.status_code in (401, 403)
        create = client.post("/api/register",
            headers={"X-Central-Request": "1"},
            json={"email": f"{uuid.uuid4().hex}@example.test",
                  "password": "LocalTestPassword123!"})
        assert create.status_code == 200, create.text
        response = client.get("/api/system/resources")
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["ram"]["total_mib"] == 16000
        assert result["gpu"]["status"] == "unavailable"
        assert result["reservations"]["scope"] == "shared_data_directory"
        assert result["reservations"]["interprocess"] is True
        assert "password" not in str(result)
