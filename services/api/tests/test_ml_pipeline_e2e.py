"""Synthetic Silver + explicitly demo-trained models: integration, not Radar/model acceptance."""

import json
import os
import time
from pathlib import Path

import httpx
import pytest
from test_analysis_pipeline_e2e import silver_fixture  # noqa: F401
from test_keycloak_e2e import keycloak_stack  # noqa: F401


def run_job(client, api, service, headers, mart, expected):
    before = mart.execute(
        "SELECT count(*) FROM gold.service_runs WHERE service=%s", (service,)
    ).fetchone()[0]
    accepted = client.post(api + f"/api/jobs/{service}/run", headers=headers)
    assert accepted.status_code == 202, accepted.text
    run_id = accepted.json()["run_id"]
    deadline = time.monotonic() + 60
    while True:
        result = client.get(api + f"/api/jobs/runs/{run_id}", headers=headers)
        assert result.status_code == 200
        row = result.json()
        if row["status"] != "running" or time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    assert row["status"] == expected, row
    assert row["finished_at"] is not None
    assert mart.execute(
        "SELECT count(*) FROM gold.service_runs WHERE service=%s", (service,)
    ).fetchone()[0] == before + 1
    return row


@pytest.mark.keycloak
def test_ml_admin_jobs_write_gold_once_and_skip_empty_silver(request, mart):
    warehouse = request.getfixturevalue("silver_fixture")
    api, login = request.getfixturevalue("keycloak_stack")
    admin = login("admin", os.environ["TEST_KEYCLOAK_ADMIN_PASSWORD"])
    viewer = login("demo", os.environ["TEST_KEYCLOAK_DEMO_PASSWORD"])
    ah = {"Authorization": "Bearer " + admin["access_token"]}
    vh = {"Authorization": "Bearer " + viewer["access_token"]}
    mart.execute("TRUNCATE gold.cluster_results, gold.forecast_continuous, gold.forecast_discrete")
    with httpx.Client(timeout=30, trust_env=False) as client:
        for service in ("clustering", "prediction"):
            assert client.post(api + f"/api/jobs/{service}/run", headers=vh).status_code == 403
            for _ in range(2):
                row = run_job(client, api, service, ah, mart, "success")
                assert row["error"] is None
        clusters = client.get(api + "/api/clusters", headers=vh)
        assert clusters.status_code == 200
        assert int(clusters.headers["X-Total-Count"]) == 84
        assert {"http_mean", "l7_max", "bot_mean", "metric"} <= clusters.json()[0]["features"].keys()
        # The fixture ends on Oct 24 VN: D+2 = Oct 26, not the actual tomorrow.
        window = {"start": "2026-10-26T00:00:00+07:00", "end": "2026-10-27T00:00:00+07:00"}
        for kind in ("continuous", "discrete"):
            response = client.get(api + f"/api/forecast/{kind}", params=window, headers=vh)
            assert response.status_code == 200, response.text
            assert response.json()["target_date"] == "2026-10-26"
            assert "/demo/" in response.json()["model_name"]
        discrete = client.get(api + "/api/forecast/discrete", params=window, headers=vh).json()
        assert 0 <= discrete["probability"] <= 1
        # Cutoff is tuned offline and saved with the fixture model, not fixed at 0.5.
        metadata = json.loads(Path("/test-models/metrics.json").read_text(encoding="utf-8"))
        cutoff = metadata["rf_classifier"]["proba_cutoff"]
        assert discrete["label"] == ("Cao" if discrete["probability"] >= cutoff else "Thấp")
        before = mart.execute("SELECT * FROM gold.forecast_continuous").fetchall()
        # Force the second write to fail: the continuous write must roll back too.
        mart.execute("ALTER TABLE gold.forecast_discrete ADD CONSTRAINT test_reject_prediction CHECK (false) NOT VALID")
        try:
            row = run_job(client, api, "prediction", ah, mart, "failed")
            assert row["error"] and "test-only" not in row["error"]
            assert mart.execute("SELECT * FROM gold.forecast_continuous").fetchall() == before
        finally:
            mart.execute("ALTER TABLE gold.forecast_discrete DROP CONSTRAINT test_reject_prediction")
        warehouse.execute("TRUNCATE silver.metrics_hourly")
        for service in ("clustering", "prediction"):
            run_job(client, api, service, ah, mart, "skipped")
        assert mart.execute("SELECT count(*) FROM gold.cluster_results").fetchone()[0] == 84
        for table in ("forecast_continuous", "forecast_discrete"):
            assert mart.execute(f"SELECT count(*) FROM gold.{table}").fetchone()[0] == 1
