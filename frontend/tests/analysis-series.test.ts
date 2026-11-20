import { test } from "node:test";
import assert from "node:assert/strict";
import { alignTrendSeries } from "../lib/analysis-series";

test("trimmed trend keeps its actual bucket instead of shifting to the first mean", () => {
  const result = alignTrendSeries([
    { ts: "2026-11-02T00:00:00+07:00", mean: 1.31 },
    { ts: "2026-11-09T00:00:00+07:00", mean: 0 },
    { ts: "2026-11-16T00:00:00+07:00", mean: null },
  ], [{ ts: "2026-11-08T17:00:00Z", trend_value: 0.7 }]);
  assert.deepEqual(result.means, [1.31, 0, null]);
  assert.deepEqual(result.trends, [null, 0.7, null]);
  assert.equal(result.timestamps[1], "2026-11-08T17:00:00.000Z");
});

test("union includes out-of-order buckets from either response without filling missing data with zero", () => {
  const result = alignTrendSeries([{ ts: "2026-11-16T00:00:00Z", mean: 1 }], [
    { ts: "2026-11-23T00:00:00Z", trend_value: null },
    { ts: "2026-11-09T00:00:00Z", trend_value: 0.8 },
  ]);
  assert.deepEqual(result.means, [null, 1, null]);
  assert.deepEqual(result.trends, [0.8, null, null]);
  assert.deepEqual(alignTrendSeries(), { timestamps: [], means: [], trends: [] });
});
