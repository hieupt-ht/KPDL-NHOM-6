import { createHash } from "node:crypto";
import type { JWT } from "next-auth/jwt";

export type AuthConfig = { issuer: string; internalIssuer: string; apiUrl: string; clientId: string; clientSecret: string };
type Identity = { sub: string; username: string; roles: string[] };

export async function loadIdentity(accessToken: string, config: AuthConfig, expectedSub?: string, fetcher: typeof fetch = fetch): Promise<Identity> {
  const response = await fetcher(`${config.apiUrl.replace(/\/$/, "")}/api/me`, {
    headers: { Authorization: `Bearer ${accessToken}` }, cache: "no-store", signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) throw new Error("IdentityValidationFailed");
  const identity = await response.json();
  if (!identity.sub || typeof identity.sub !== "string" || typeof identity.username !== "string" ||
      (expectedSub && identity.sub !== expectedSub) || !Array.isArray(identity.roles) ||
      !identity.roles.every((role: unknown) => typeof role === "string")) throw new Error("IdentityValidationFailed");
  const roles = identity.roles.filter((role: string) => role === "viewer" || role === "admin");
  if (!roles.length) throw new Error("IdentityValidationFailed");
  return { sub: identity.sub, username: identity.username, roles };
}

const refreshes = new Map<string, { expires: number; result: Promise<JWT> }>();

export async function refreshAccessToken(token: JWT, config: AuthConfig, fetcher: typeof fetch = fetch): Promise<JWT> {
  if (!token.refreshToken) return { ...token, accessToken: undefined, roles: [], error: "RefreshAccessTokenError" };
  const key = createHash("sha256").update(`${config.issuer}:${token.refreshToken}`).digest("hex");
  const now = Date.now();
  for (const [entryKey, entry] of refreshes) if (entry.expires <= now) refreshes.delete(entryKey);
  const pending = refreshes.get(key);
  if (pending) return pending.result;
  const result = (async (): Promise<JWT> => {
    try {
      const response = await fetcher(`${config.internalIssuer}/protocol/openid-connect/token`, {
        method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, cache: "no-store",
        body: new URLSearchParams({ grant_type: "refresh_token", refresh_token: token.refreshToken!, client_id: config.clientId, client_secret: config.clientSecret }),
        signal: AbortSignal.timeout(10000),
      });
      if (!response.ok) throw new Error("RefreshFailed");
      const next = await response.json();
      if (typeof next.access_token !== "string" || !Number.isFinite(next.expires_in) || next.expires_in <= 0) throw new Error("RefreshFailed");
      const identity = await loadIdentity(next.access_token, config, token.sub, fetcher);
      return { ...token, sub: identity.sub, username: identity.username, roles: identity.roles,
        accessToken: next.access_token, refreshToken: next.refresh_token ?? token.refreshToken,
        idToken: next.id_token ?? token.idToken, accessTokenExpires: Date.now() + next.expires_in * 1000, error: undefined };
    } catch {
      // Never return stale access tokens after refresh/role validation fails.
      return { ...token, accessToken: undefined, roles: [], error: "RefreshAccessTokenError" };
    }
  })();
  if (refreshes.size >= 1000) refreshes.delete(refreshes.keys().next().value!);
  // Deduplicate concurrent session requests, including a brief rotation race.
  refreshes.set(key, { expires: now + 10000, result });
  return result;
}

export function sessionAuth(token: JWT) {
  return { accessToken: token.error ? undefined : token.accessToken,
    roles: token.error ? [] : token.roles ?? [], error: token.error };
}

export function providerLogoutUrl(issuer: string, appUrl: string, idToken?: string): string {
  if (!idToken) return new URL("/", appUrl).toString();
  const url = new URL(`${issuer}/protocol/openid-connect/logout`);
  url.searchParams.set("id_token_hint", idToken);
  url.searchParams.set("post_logout_redirect_uri", new URL("/", appUrl).toString());
  return url.toString();
}
