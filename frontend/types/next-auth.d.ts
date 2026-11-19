import type { DefaultSession } from "next-auth";

declare module "next-auth" {
  interface Session {
    accessToken?: string;
    roles: string[];
    error?: "RefreshAccessTokenError";
    user: DefaultSession["user"] & { id?: string };
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    accessToken?: string;
    refreshToken?: string;
    idToken?: string;
    accessTokenExpires?: number;
    roles?: string[];
    username?: string;
    error?: "RefreshAccessTokenError";
  }
}
