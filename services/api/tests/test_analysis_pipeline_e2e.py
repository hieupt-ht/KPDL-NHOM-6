"""Run the actual Analysis service, then read its Gold output through open API."""

import os
import time

import httpx
import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict


@pytest.fixture
def silver_fixture(mart):
    dsn = os.environ.get("TEST_WAREHOUSE_ADMIN_DSN")
    if not dsn:
        pytest.skip("Requires an explicitly configured disposable Warehouse")
    if not conninfo_to_dict(dsn).get("dbname", "").startswith("test_"):
        pytest.fail("Synthetic Silver must only be written to a test_* database")
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as warehouse:
        warehouse.execute("TRUNCATE silver.metrics_hourly")
        # Synthetic values, not fetched Radar data. source='radar' exercises the
        # production reader filter only inside this explicitly named test DB.
        warehouse.execute("""
            INSERT INTO silver.metrics_hourly (ts, metric, value, source)
            SELECT ts, metric,
                CASE metric
                    WHEN 'http_traffic' THEN 1.1 + 0.001 * extract(doy from ts) + 0.1 * sin(extract(epoch from ts)/86400)
                    WHEN 'l7_attack' THEN 0.2 + 0.03 * cos(extract(epoch from ts)/36000)
                    WHEN 'bot_share' THEN 35 + 5 * sin(extract(epoch from ts)/86400)
                    WHEN 'human_share' THEN 65 - 5 * sin(extract(epoch from ts)/86400)
                    ELSE 1.2 + 0.1 * cos(extract(epoch from ts)/86400)
                END, 'radar'
            FROM generate_series('2026-08-01T17:00:00Z'::timestamptz,
                                 '2026-10-24T16:00:00Z'::timestamptz, interval '1 hour') ts
            CROSS JOIN unnest(ARRAY['http_traffic','l7_attack','bot_share','human_share','netflows']) metric
        """)
        warehouse.execute("""
            INSERT INTO silver.metrics_hourly (ts, metric, value, source) VALUES
            ('2026-10-25T00:00:00Z', 'http_traffic', 'NaN', 'radar'),
            ('2026-10-25T01:00:00Z', 'netflows', 'Infinity', 'radar'),
            ('2026-10-25T02:00:00Z', 'l7_attack', '-Infinity', 'radar'),
            ('2026-10-25T03:00:00Z', 'bot_share', NULL, 'radar'),
            ('2026-10-26T00:00:00Z', 'http_traffic', 999, 'demo')
        """)
        mart.execute(
            "TRUNCATE gold.timeseries_resampled, gold.histogram, gold.trend, gold.seasonal, gold.correlation, gold.data_freshness, gold.service_runs"
        )
        yield warehouse
        warehouse.execute("TRUNCATE silver.metrics_hourly")


@pytest.mark.stack
def test_analysis_job_writes_gold_and_api_reads_actual_results(
    silver_fixture, mart
):
    api = os.environ["TEST_API_URL"]
    with httpx.Client(timeout=30, trust_env=False) as client:
        assert (
            client.get(
                api + "/api/timeseries",
                params={"metric": "http_traffic", "granularity": "day"},
            ).status_code
            == 404
        )
        accepted = client.post(api + "/api/jobs/analysis/run")
        assert accepted.status_code == 202
        run_id = accepted.json()["run_id"]
        deadline = time.monotonic() + 60
        while True:
            result = client.get(api + f"/api/jobs/runs/{run_id}")
            assert result.status_code == 200
            row = result.json()
            if row["status"] != "running" or time.monotonic() >= deadline:
                break
            time.sleep(0.2)
        assert row["status"] == "success", row
        assert row["finished_at"] is not None and row["error"] is None
        assert (
            mart.execute(
                "SELECT count(*) FROM gold.service_runs WHERE service='analysis'"
            ).fetchone()[0]
            == 1
        )
        params = {"metric": "http_traffic", "granularity": "day", "limit": 3}
        page = client.get(
            api + "/api/timeseries", params=params
        )
        assert page.status_code == 200
        assert len(page.json()) == 3
        assert int(page.headers["X-Total-Count"]) == 84
        assert page.json()[0]["ts"].startswith("2026-08-01T17:00:00")
        assert page.json()[0]["mean"] > 1
        next_page = client.get(
            api + "/api/timeseries",
            params={**params, "offset": 3},
        )
        assert next_page.status_code == 200
        assert next_page.json()[0]["ts"] > page.json()[-1]["ts"]
        for endpoint, query in [
            ("histogram", {"metric": "http_traffic"}),
            ("trend", {"metric": "http_traffic", "granularity": "week"}),
            ("seasonal", {"metric": "http_traffic", "period_type": "hour_of_day"}),
            ("correlation", {}),
        ]:
            response = client.get(
                api + "/api/" + endpoint, params=query
            )
            assert response.status_code == 200, (endpoint, response.text)
            assert response.json()
        histogram = client.get(
            api + "/api/histogram",
            params={"metric": "http_traffic"},
        ).json()
        assert sum(bin["count"] for bin in histogram) == 84 * 24
        for metric in ("human_share", "netflows"):
            assert (
                client.get(
                    api + "/api/histogram",
                    params={"metric": metric},
                ).status_code
                == 404
            )
        assert (
            client.get(
                api + "/api/histogram",
                params={"metric": "http_traffic", "start": "2026-08-02T00:00:00+07:00"},
            ).status_code
            == 422
        )
        status = client.get(api + "/api/status").json()
        assert status["data_freshness"]["latest_silver_ts"].startswith(
            "2026-10-24T16:00:00"
        )
        assert status["service_runs"][0]["id"] == run_id
