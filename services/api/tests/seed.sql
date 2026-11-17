-- Deterministic synthetic fixtures, not collected Cloudflare data.
INSERT INTO gold.timeseries_resampled VALUES
('day', '2026-11-01T00:00:00Z', 'http_traffic', 0.3, 0.1, 0.5),
('day', '2026-11-02T00:00:00Z', 'http_traffic', 0.6, 0.4, 0.8),
('week', '2026-11-01T00:00:00Z', 'http_traffic', 0.5, 0.1, 0.8),
('day', '2026-11-01T00:00:00Z', 'bot_share', 25, 20, 30);
INSERT INTO gold.histogram VALUES ('l7_attack', 0, 0.5, 2), ('l7_attack', 0.5, 1, 3);
INSERT INTO gold.trend VALUES
('week', '2026-11-01T00:00:00Z', 'http_traffic', NULL),
('week', '2026-11-08T00:00:00Z', 'http_traffic', 0.6);
INSERT INTO gold.seasonal VALUES ('hour_of_day', 0, 'http_traffic', 0.3), ('hour_of_day', 1, 'http_traffic', 0.4);
INSERT INTO gold.correlation (var_x, var_y, coef) VALUES
('http_traffic', 'bot_share', 0.7), ('netflows', 'bot_share', 'NaN');
INSERT INTO gold.cluster_results (date, cluster_id, cluster_name, features) VALUES
('2026-11-01', 0, 'Bình thường', '{"traffic_mean":0.3}'),
('2026-11-02', 1, 'Cao điểm', '{"traffic_mean":0.6}');
INSERT INTO gold.forecast_continuous (target_date, predicted_value, model_name) VALUES
('2026-11-01', 0.4, 'fixture'), ('2026-11-02', 0.5, 'fixture'),
((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Ho_Chi_Minh')::date + 1, 0.7, 'fixture-tomorrow');
INSERT INTO gold.forecast_discrete (target_date, label, probability, model_name) VALUES
((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Ho_Chi_Minh')::date + 1, 'Cao', 0.8, 'fixture-tomorrow');
INSERT INTO gold.service_runs (service, started_at, status) VALUES
('analysis', '2026-11-01T00:00:00Z', 'success'),
('analysis', '2026-11-02T00:00:00Z', 'failed'),
('analysis', NULL, 'unknown'),
('prediction', '2026-11-02T00:00:00Z', 'success');
INSERT INTO gold.data_freshness (latest_silver_ts) VALUES ('2026-11-02T00:00:00Z');
