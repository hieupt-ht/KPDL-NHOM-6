import { test } from "node:test";
import assert from "node:assert/strict";
import { apiDateRange, vietnamDay } from "../lib/date-utils";
import { ApiError, createApiTransport } from "../lib/api-core";
import { loadIdentity, refreshAccessToken, sessionAuth, providerLogoutUrl } from "../lib/auth-core";

const config = { issuer: "http://public/realm", internalIssuer: "http://internal/realm", apiUrl: "http://api:8000", clientId: "dashboard", clientSecret: "private" };
const json = (value: unknown, status = 200, headers = {}) => Response.json(value, { status, headers });

test("Vietnam day and inclusive date ranges cross month/year boundaries", () => {
  assert.equal(vietnamDay("2026-11-17T17:00:00Z"), "2026-11-18");
  assert.deepEqual(apiDateRange({ start: "2026-12-31", end: "2026-12-31" }), { start: "2026-12-31T00:00:00+07:00", end: "2027-01-01T00:00:00+07:00" });
  assert.deepEqual(apiDateRange({ end: "2024-02-29" }), { start: undefined, end: "2024-03-01T00:00:00+07:00" });
  assert.throws(() => apiDateRange({ start: "2026-02-30" }));
});

test("transport sends bearer, encoded timezone and reads every page", async () => {
  const urls: URL[] = [];
  const api = createApiTransport({ baseUrl: "http://api:8000", getToken: async () => "access", fetcher: async (input, init) => {
    const url = new URL(String(input)); urls.push(url);
    assert.equal(new Headers(init?.headers).get("Authorization"), "Bearer access");
    return json(url.searchParams.get("offset") === "0" ? [{ mean: null }] : [{ mean: 1.31 }], 200, { "X-Total-Count": "2" });
  } });
  assert.deepEqual(await api.list("timeseries", api.range({ start: "2026-11-18" })), [{ mean: null }, { mean: 1.31 }]);
  assert.equal(urls[1].searchParams.get("offset"), "1");
  assert.equal(urls[0].searchParams.get("start"), "2026-11-18T00:00:00+07:00");
});

test("missing token never sends request; failures preserve status without secrets or retries", async () => {
  let calls = 0;
  const fetcher: typeof fetch = async () => { calls++; return json({ detail: "private" }, 504); };
  const missing = createApiTransport({ baseUrl: "http://api", getToken: async () => null, fetcher });
  await assert.rejects(missing.request("status"), (e: unknown) => e instanceof ApiError && e.status === 401);
  assert.equal(calls, 0);
  const api = createApiTransport({ baseUrl: "http://api", getToken: async () => "access", fetcher });
  await assert.rejects(api.request("jobs/analysis/run", {}, { method: "POST" }), (e: unknown) => e instanceof ApiError && e.status === 504 && !e.message.includes("private"));
  assert.equal(calls, 1);
});

test("pagination refuses an empty intermediate page", async () => {
  const api = createApiTransport({ baseUrl: "http://api", getToken: async () => "a", fetcher: async () => json([], 200, { "X-Total-Count": "1" }) });
  await assert.rejects(api.list("timeseries", {}), (e: unknown) => e instanceof ApiError && e.status === 409);
});

test("identity validates subject and only accepts backend dashboard roles", async () => {
  await assert.rejects(loadIdentity("a", config, "one", async () => json({ sub: "two", username: "x", roles: ["admin"] })));
  await assert.rejects(loadIdentity("a", config, undefined, async () => json({ username: "development", roles: ["admin"] })));
  assert.deepEqual((await loadIdentity("a", config, "one", async () => json({ sub: "one", username: "x", roles: ["viewer", "offline_access"] }))).roles, ["viewer"]);
});

test("refresh rotates server credentials once and reloads backend roles", async () => {
  let calls = 0;
  const fetcher: typeof fetch = async (input, init) => {
    calls++;
    if (String(input).endsWith("/token")) {
      assert.equal(new URLSearchParams(String(init?.body)).get("client_secret"), "private");
      return json({ access_token: "new-access", refresh_token: "new-refresh", expires_in: 300 });
    }
    assert.equal(new Headers(init?.headers).get("Authorization"), "Bearer new-access");
    return json({ sub: "one", username: "viewer", roles: ["viewer"] });
  };
  const token = { sub: "one", refreshToken: "rotation-test", roles: ["admin"] };
  const [a, b] = await Promise.all([refreshAccessToken(token, config, fetcher), refreshAccessToken(token, config, fetcher)]);
  assert.equal(calls, 2); assert.deepEqual(a, b); assert.deepEqual(a.roles, ["viewer"]);
  assert.equal(a.refreshToken, "new-refresh");
  assert.equal("refreshToken" in sessionAuth(a), false);
  assert.equal("idToken" in sessionAuth({ ...a, idToken: "private-id" }), false);
});

test("failed refresh removes access and admin roles", async () => {
  const result = await refreshAccessToken({ sub: "one", accessToken: "old", refreshToken: "failed-test", roles: ["admin"] }, config, async () => json({}, 400));
  assert.equal(result.accessToken, undefined); assert.deepEqual(result.roles, []);
  assert.equal(result.error, "RefreshAccessTokenError");
});

test("logout returns fixed provider and registered root redirect", () => {
  const url = new URL(providerLogoutUrl(config.issuer, "http://localhost:3000/admin", "id"));
  assert.equal(url.origin, "http://public");
  assert.equal(url.searchParams.get("post_logout_redirect_uri"), "http://localhost:3000/");
  assert.equal(url.searchParams.get("id_token_hint"), "id");
});
