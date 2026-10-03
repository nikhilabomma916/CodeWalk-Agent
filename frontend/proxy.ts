import { NextResponse, type NextRequest } from "next/server";

import { appConfig } from "@/lib/config";
import { buildContentSecurityPolicy } from "@/lib/csp";

/**
 * Sets a nonce-based Content-Security-Policy on every page. Next.js reads the nonce from the
 * request's CSP header and attaches it to its own scripts, so pages are rendered per request
 * (see the root layout). Static assets, Monaco files and the health check are excluded.
 */
export function proxy(request: NextRequest) {
  const nonce = btoa(crypto.randomUUID());
  const policy = buildContentSecurityPolicy({
    nonce,
    development: process.env.NODE_ENV === "development",
    apiBaseUrl: appConfig.apiBaseUrl,
    https:
      request.nextUrl.protocol === "https:" || request.headers.get("x-forwarded-proto") === "https",
  });

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", policy);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", policy);
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!_next/static|_next/image|monaco/|favicon.ico|healthz).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
