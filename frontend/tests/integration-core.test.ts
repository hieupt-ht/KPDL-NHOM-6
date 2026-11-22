import { test } from "node:test";
import assert from "node:assert/strict";
import { apiDateRange, vietnamDay } from "../lib/date-utils";
import { ApiError, createApiTransport } from "../lib/api-core";

const json = (value: unknown, status = 200, headers = {}) => Response.json(value, { status, headers });

test("Vietnam day and inclusive date ranges cross month/year boundaries", () => {
  assert.equal(vietnamDay("2026-11-17T17:00:00Z"), "2026-11-18");
  assert.deepEqual(apiDateRange({ start: "2026-12-31", end: "2026-12-31" }), { start: "2026-12-31T00:00:00+07:00", end: "2027-01-01T00:00:00+07:00" });
  assert.deepEqual(apiDateRange({ end: "2024-02-29" }), { start: undefined, end: "2024-03-01T00:00:00+07:00" });
  assert.throws(() => apiDateRange({ start: "2026-02-30" }));
});

test("transport needs no login, encoded timezone and reads every page", async () => {
  const urls: URL[] = [];
  const api = createApiTransport({ baseUrl: "http://api:8000", fetcher: async (input, init) => {
    const url = new URL(String(input)); urls.push(url);
    assert.equal(new Headers(init?.headers).get("Authorization"), null);
    return json(url.searchParams.get("offset") === "0" ? [{ mean: null }] : [{ mean: 1.31 }], 200, { "X-Total-Count": "2" });
  } });
  assert.deepEqual(await api.list("timeseries", api.range({ start: "2026-11-18" })), [{ mean: null }, { mean: 1.31 }]);
  assert.equal(urls[1].searchParams.get("offset"), "1");
  assert.equal(urls[0].searchParams.get("start"), "2026-11-18T00:00:00+07:00");
});

test("requests without tokens preserve status without secrets or retries", async () => {
  let calls = 0;
  const fetcher: typeof fetch = async () => { calls++; return json({ detail: "private" }, 504); };
  const api = createApiTransport({ baseUrl: "http://api", fetcher });
  await assert.rejects(api.request("jobs/analysis/run", {}, { method: "POST" }), (e: unknown) => e instanceof ApiError && e.status === 504 && !e.message.includes("private"));
  assert.equal(calls, 1);
});

test("pagination refuses an empty intermediate page", async () => {
  const api = createApiTransport({ baseUrl: "http://api", fetcher: async () => json([], 200, { "X-Total-Count": "1" }) });
  await assert.rejects(api.list("timeseries", {}), (e: unknown) => e instanceof ApiError && e.status === 409);
});
