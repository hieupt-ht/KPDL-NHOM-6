"""Public Jobs API retains internal service-token checks and exact run tracking."""

import os
import time

import httpx
import pytest


@pytest.mark.stack
def test_open_jobs_and_internal_boundary():
    api = os.environ["TEST_API_URL"]
    with httpx.Client(timeout=15, trust_env=False) as client:
        assert client.get(api + "/api/status").status_code == 200
        assert client.get(api + "/api/me").status_code == 404
        for service in ("analysis", "clustering", "prediction"):
            accepted = client.post(api + f"/api/jobs/{service}/run")
            assert accepted.status_code == 202, accepted.text
            run_id = accepted.json()["run_id"]
            deadline = time.monotonic() + 60
            while True:
                response = client.get(api + f"/api/jobs/runs/{run_id}")
                assert response.status_code == 200
                row = response.json()
                if row["status"] != "running" or time.monotonic() >= deadline:
                    break
                time.sleep(0.1)
            assert row["status"] in {"success", "failed", "partial", "skipped"}
            assert row["finished_at"] is not None
            internal = os.environ[f"TEST_{service.upper()}_URL"]
            assert client.post(internal + "/run").status_code == 401
            assert client.post(internal + "/run", headers={"X-Job-Token": "wrong"}).status_code == 401
