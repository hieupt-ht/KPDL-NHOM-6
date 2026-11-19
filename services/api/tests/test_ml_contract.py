"""Regression contracts for the Gold payload written by the ML feature branch."""

from datetime import UTC, datetime

import pytest
import repository
from psycopg.types.json import Jsonb
from pydantic import ValidationError
from schemas import ClusterResult


def cluster(features):
    return ClusterResult(
        date="2026-11-18",
        cluster_id=0,
        cluster_name="Bình thường",
        features=features,
        computed_at=None,
    )


def test_ml_features_preserve_metric_and_missing_measurements():
    result = cluster(
        {
            "metric": "http_traffic",
            "lag_1": 1.31,
            "rolling_mean_7": None,
            "lag_2": float("nan"),
        }
    )
    assert result.model_dump(mode="json")["features"] == {
        "metric": "http_traffic",
        "lag_1": 1.31,
        "rolling_mean_7": None,
        "lag_2": None,
    }
    assert cluster(None).features is None
    assert cluster({"http_mean": 0.4}).features == {"http_mean": 0.4}


@pytest.mark.parametrize(
    "features", [{"metric": "unknown"}, {"metric": 1}, {"http_mean": "http_traffic"}]
)
def test_feature_metadata_does_not_allow_arbitrary_strings(features):
    with pytest.raises(ValidationError):
        cluster(features)


@pytest.mark.integration
def test_cluster_api_reads_ml_json_without_response_validation_error(client, mart):
    features = {"metric": "http_traffic", "lag_1": 1.31, "rolling_mean_7": None}
    mart.execute(
        "UPDATE gold.cluster_results SET features=%s WHERE date='2026-11-01'",
        (Jsonb(features),),
    )
    response = client.get("/api/clusters")
    assert response.status_code == 200
    assert response.json()[0]["features"] == features


@pytest.mark.integration
def test_low_label_still_returns_probability_of_high(client, mart):
    mart.execute(
        "UPDATE gold.forecast_discrete SET label='Thấp', probability=0.2, model_name='rf_classifier/silver/2026-11-19T00:00:00Z'"
    )
    response = client.get("/api/forecast/discrete")
    assert response.status_code == 200
    assert response.json()["label"] == "Thấp"
    assert response.json()["probability"] == 0.2
    assert response.json()["model_name"] == "rf_classifier/silver/2026-11-19T00:00:00Z"


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["continuous", "discrete"])
def test_forecast_calendar_uses_vietnam_tomorrow_not_latest_ml_date(
    client, mart, monkeypatch, kind
):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            # UTC Nov 18 evening is already Nov 19 in Vietnam.
            return datetime(2026, 11, 18, 18, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(repository, "datetime", Clock)
    mart.execute("DELETE FROM gold.forecast_continuous")
    mart.execute("DELETE FROM gold.forecast_discrete")
    mart.execute(
        "INSERT INTO gold.forecast_continuous (target_date, predicted_value) VALUES ('2026-11-19', 1.31)"
    )
    mart.execute(
        "INSERT INTO gold.forecast_discrete (target_date, label, probability) VALUES ('2026-11-19', 'Thấp', 0.2)"
    )
    # A result for today must not be relabelled as tomorrow by API fallback.
    assert client.get(f"/api/forecast/{kind}").status_code == 404
    mart.execute("UPDATE gold.forecast_continuous SET target_date='2026-11-20'")
    mart.execute("UPDATE gold.forecast_discrete SET target_date='2026-11-20'")
    response = client.get(f"/api/forecast/{kind}")
    assert response.status_code == 200
    assert response.json()["target_date"] == "2026-11-20"
