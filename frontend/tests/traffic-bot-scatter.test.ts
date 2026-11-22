import { test } from "node:test";
import assert from "node:assert/strict";
import { ApiError } from "../lib/api-core";
import { trafficBotScatter } from "../lib/traffic-bot-scatter";

const http = { data: [{ ts: "2026-11-18T17:00:00Z", mean: 1.31 }] };
const bot = { data: [{ ts: "2026-11-19T00:00:00+07:00", mean: 30.34 }] };

test("missing clusters (404) cannot hide available HTTP/Bot; equivalent timestamps join", () => {
  const result = trafficBotScatter(http, bot, { error: new ApiError(404, "empty") });
  assert.equal(result.error, undefined);
  assert.equal(result.loading, false);
  assert.equal(result.empty, false);
  assert.equal(result.clusterStatus, "missing");
  assert.deepEqual(result.groups, [{ name: "Chưa phân cụm", data: [[1.31, 30.34]] }]);
});

test("optional labels loading or unavailable leave points visible in neutral group", () => {
  for (const labels of [{ isLoading: true }, { error: new ApiError(503, "offline") }]) {
    const result = trafficBotScatter(http, bot, labels);
    assert.equal(result.loading, false);
    assert.equal(result.error, undefined);
    assert.equal(result.pointCount, 1);
    assert.equal(result.groups[0].name, "Chưa phân cụm");
  }
});

test("cluster color joins Vietnam day; unfamiliar ML label never implies abnormal", () => {
  const result = trafficBotScatter(http, bot, { data: [{ date: "2026-11-19", cluster_name: "Bất thường" }] });
  assert.equal(result.groups[0].name, "Bất thường");
  const unknown = trafficBotScatter(http, bot, { data: [{ date: "2026-11-19", cluster_name: "Cao" }] });
  assert.equal(unknown.groups[0].name, "Nhãn chưa hỗ trợ");
});

test("zero is real data, missing/nonfinite or unpaired measurements never become points", () => {
  const result = trafficBotScatter({ data: [
    { ts: "2026-11-18T17:00:00Z", mean: 0 },
    { ts: "2026-11-19T17:00:00Z", mean: null },
    { ts: "2026-11-20T17:00:00Z", mean: Infinity },
    { ts: "2026-11-21T17:00:00Z", mean: 1 },
  ] }, { data: [
    { ts: "2026-11-18T17:00:00Z", mean: 0 },
    { ts: "2026-11-19T17:00:00Z", mean: 20 },
    { ts: "2026-11-20T17:00:00Z", mean: 20 },
  ] }, {});
  assert.deepEqual(result.groups[0].data, [[0, 0]]);
  assert.equal(trafficBotScatter({}, {}, {}).empty, true);
});

test("required source loading/errors still propagate", () => {
  const error = new ApiError(503, "primary unavailable");
  assert.equal(trafficBotScatter({ error }, bot, {}).error, error);
  assert.equal(trafficBotScatter(http, { isLoading: true }, {}).loading, true);
});
