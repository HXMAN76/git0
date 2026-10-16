from fastapi.testclient import TestClient

from git0.api.app import app


def test_health_and_tenant_roundtrip():
    with TestClient(app) as client:
        assert client.get("/api/health").json()["ok"] is True
        assert client.post("/api/ci_smoke/init").status_code == 200
        assert client.get("/api/ci_smoke/branches/main/checkout").json() == []
        assert client.post("/api/Bad-Tenant!/init").status_code == 400
