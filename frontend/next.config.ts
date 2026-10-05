import path from "node:path";

import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// The repository root .env is shared by frontend and backend; frontend-local
// .env files (loaded by Next itself) still take precedence.
loadEnvConfig(path.resolve(__dirname, ".."));

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Self-contained server (.next/standalone/server.js) for the production container image, which
  // sets NEXT_OUTPUT=standalone; host builds keep the regular output that "next start" serves.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  // The full-screen layout has controls in every corner (the account menu sits where the dev
  // indicator would). Compile and runtime errors are still shown in development.
  devIndicators: false,
  // On Vercel the API is the "backend" service of the same deployment, routed at /api
  // (vercel.json), so the browser calls it on the page's own origin unless configured otherwise.
  env:
    process.env.VERCEL === "1" && !process.env.NEXT_PUBLIC_API_BASE_URL?.trim()
      ? { NEXT_PUBLIC_API_BASE_URL: "/api/v1" }
      : {},
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), payment=()",
          },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
