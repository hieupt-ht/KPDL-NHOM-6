CREATE SCHEMA gold;

CREATE TABLE gold.timeseries_resampled (
    granularity VARCHAR(8) NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    metric VARCHAR(32) NOT NULL,
    mean DOUBLE PRECISION,
    min DOUBLE PRECISION,
    max DOUBLE PRECISION,
    PRIMARY KEY (granularity, ts, metric)
);
CREATE TABLE gold.histogram (
    metric VARCHAR(32) NOT NULL,
    bin_start DOUBLE PRECISION NOT NULL,
    bin_end DOUBLE PRECISION NOT NULL,
    count BIGINT NOT NULL,
    PRIMARY KEY (metric, bin_start, bin_end)
);
CREATE TABLE gold.trend (
    granularity VARCHAR(8) NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    metric VARCHAR(32) NOT NULL,
    trend_value DOUBLE PRECISION,
    PRIMARY KEY (granularity, ts, metric)
);
CREATE TABLE gold.seasonal (
    period_type VARCHAR(16) NOT NULL,
    bucket INT NOT NULL,
    metric VARCHAR(32) NOT NULL,
    value DOUBLE PRECISION,
    PRIMARY KEY (period_type, bucket, metric)
);
CREATE TABLE gold.correlation (
    var_x VARCHAR(32) NOT NULL,
    var_y VARCHAR(32) NOT NULL,
    coef DOUBLE PRECISION,
    computed_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (var_x, var_y)
);
CREATE TABLE gold.data_freshness (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    latest_silver_ts TIMESTAMPTZ,
    computed_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE gold.cluster_results (
    date DATE PRIMARY KEY,
    cluster_id INT NOT NULL,
    cluster_name VARCHAR(32) NOT NULL,
    features JSONB,
    computed_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE gold.forecast_continuous (
    target_date DATE PRIMARY KEY,
    predicted_value DOUBLE PRECISION,
    model_name VARCHAR(128),
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE gold.forecast_discrete (
    target_date DATE PRIMARY KEY,
    label VARCHAR(16),
    probability DOUBLE PRECISION,
    model_name VARCHAR(128),
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE gold.service_runs (
    id BIGSERIAL PRIMARY KEY,
    service VARCHAR(32) NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    status VARCHAR(16),
    error TEXT
);
