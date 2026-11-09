import type { NextConfig } from "next";

// The FastAPI backend. The browser only ever talks to this Next.js server:
// /api/* is forwarded to FastAPI, so the session cookie FastAPI sets is a
// same-origin cookie (no CORS, and httponly/samesite keep working).
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  experimental: {
    // Copilot answers and rule drafting call an LLM; the 30 s default would cut them off.
    proxyTimeout: 180_000,
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/:path*` }];
  },
};

export default nextConfig;
