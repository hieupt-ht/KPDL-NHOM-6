CREATE SCHEMA bronze;
CREATE SCHEMA silver;

CREATE TABLE bronze.raw_api_responses (
    id BIGSERIAL PRIMARY KEY,
    endpoint VARCHAR(128) NOT NULL,
    params JSONB,
    status_code INT,
    payload JSONB,
    fetched_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE silver.metrics_hourly (
    ts TIMESTAMPTZ NOT NULL,
    metric VARCHAR(32) NOT NULL,
    value DOUBLE PRECISION,
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (ts, metric)
);

CREATE TABLE silver.ingestion_runs (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    status VARCHAR(16),
    rows_upserted INT,
    error TEXT
);
