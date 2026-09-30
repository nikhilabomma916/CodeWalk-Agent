import path from "node:path";

import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// The repository root .env is shared by frontend and backend; frontend-local
// .env files (loaded by Next itself) still take precedence.
loadEnvConfig(path.resolve(__dirname, ".."));

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};

export default nextConfig;
