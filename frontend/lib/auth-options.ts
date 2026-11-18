import "server-only";
import type { NextAuthOptions, Profile } from "next-auth";
import { loadIdentity, refreshAccessToken, type AuthConfig } from "./auth-core";
import { sessionAuth } from "./auth-core";

export function authConfig(): AuthConfig {
  const issuer = process.env.KEYCLOAK_ISSUER?.replace(/\/$/, "");
  const clientSecret = process.env.KEYCLOAK_CLIENT_SECRET;
  if (!issuer || !clientSecret || !(process.env.AUTH_SECRET || process.env.NEXTAUTH_SECRET)) throw new Error("AuthenticationNotConfigured");
  return { issuer, internalIssuer: (process.env.KEYCLOAK_INTERNAL_ISSUER || issuer).replace(/\/$/, ""),
    clientId: process.env.KEYCLOAK_CLIENT_ID || "dashboard", clientSecret,
    apiUrl: process.env.API_INTERNAL_URL || "http://api:8000" };
}

export function getAuthOptions(): NextAuthOptions {
  const config = authConfig();
  return {
    secret: process.env.AUTH_SECRET || process.env.NEXTAUTH_SECRET,
    session: { strategy: "jwt", maxAge: 1800 },
    providers: [{
      id: "keycloak", name: "Keycloak", type: "oauth", issuer: config.issuer,
      authorization: { url: `${config.issuer}/protocol/openid-connect/auth`, params: { scope: "openid profile email" } },
      token: `${config.internalIssuer}/protocol/openid-connect/token`,
      userinfo: `${config.internalIssuer}/protocol/openid-connect/userinfo`,
      jwks_endpoint: `${config.internalIssuer}/protocol/openid-connect/certs`,
      idToken: true, checks: ["pkce", "state"], clientId: config.clientId, clientSecret: config.clientSecret,
      profile(profile: Profile) { return { id: profile.sub!, name: profile.name, email: profile.email }; },
      httpOptions: { timeout: 10000 },
    }],
    callbacks: {
      async jwt({ token, account, user }) {
        if (account?.access_token) {
          const identity = await loadIdentity(account.access_token, config, user?.id || token.sub);
          return { ...token, sub: identity.sub, username: identity.username, roles: identity.roles,
            accessToken: account.access_token, refreshToken: account.refresh_token, idToken: account.id_token,
            accessTokenExpires: (account.expires_at ?? Math.floor(Date.now() / 1000) + 300) * 1000, error: undefined };
        }
        if (token.error || !token.accessToken) return token;
        if (Date.now() < (token.accessTokenExpires ?? 0) - 30000) return token;
        return refreshAccessToken(token, config);
      },
      async session({ session, token }) {
        Object.assign(session, sessionAuth(token));
        session.user = { ...session.user, id: token.sub, name: token.username || session.user?.name };
        return session;
      },
    },
    logger: { error(code) { console.error(`[auth] ${code}`); }, warn(code) { console.warn(`[auth] ${code}`); }, debug() {} },
  };
}
