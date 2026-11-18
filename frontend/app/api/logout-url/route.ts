import { getToken } from "next-auth/jwt";
import type { NextRequest } from "next/server";
import { authConfig } from "@/lib/auth-options";
import { providerLogoutUrl } from "@/lib/auth-core";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const appUrl = process.env.NEXTAUTH_URL || "http://localhost:3000";
  if (request.headers.get("origin") !== new URL(appUrl).origin) return Response.json({ error: "Invalid origin" }, { status: 403 });
  const token = await getToken({ req: request, secret: process.env.AUTH_SECRET || process.env.NEXTAUTH_SECRET });
  if (!token) return Response.json({ error: "Not authenticated" }, { status: 401 });
  return Response.json({ url: providerLogoutUrl(authConfig().issuer, appUrl, token.idToken) }, { headers: { "Cache-Control": "no-store" } });
}
