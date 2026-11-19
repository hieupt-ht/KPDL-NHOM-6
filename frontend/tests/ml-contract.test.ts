import { test } from "node:test";
import assert from "node:assert/strict";
import { clusterMeasurement, riskSummary } from "../lib/ml-contract";

test("low-label probability remains P(High), not confidence in Low", () => {
  assert.equal(riskSummary({ label: "Thấp", probability: 0.2 }), "Thấp · P(Cao): 20%");
  assert.equal(riskSummary({ label: "Cao", probability: 0.8 }), "Cao · P(Cao): 80%");
  assert.equal(riskSummary({ label: null, probability: null }), "Chưa có · P(Cao): —");
});

test("cluster metadata and lag features do not fabricate chart measurements", () => {
  const features = { metric: "http_traffic" as const, lag_1: 1.31, http_mean: 0, bot_mean: null };
  assert.equal(clusterMeasurement(features, "metric"), null);
  assert.equal(clusterMeasurement(features, "lag_1"), 1.31);
  assert.equal(clusterMeasurement(features, "http_mean"), 0);
  assert.equal(clusterMeasurement(features, "bot_mean"), null);
  assert.equal(clusterMeasurement(features, "l7_max"), null);
  assert.equal(clusterMeasurement(null, "http_mean"), null);
});
