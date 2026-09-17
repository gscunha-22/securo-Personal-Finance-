import type { VercelConfig } from "@vercel/config/v1";

function normalizeApiOrigin(raw: string): string {
  // Operators often paste the Render health URL (.../api). The rewrite
  // already prefixes /api/:path*, so a trailing /api would become /api/api/.
  return raw
    .trim()
    .replace(/\/+$/, "")
    .replace(/\/api$/i, "")
    .replace(/\/+$/, "");
}

const apiOrigin = normalizeApiOrigin(process.env.API_ORIGIN ?? "");

// Header `value` must be a string literal. Vercel schema-validates vercel.ts
// before evaluating identifiers (`value: csp` → missing required property
// `value` on the production deploy of cursor/land-architecture-ci-0b4a).
// Automatic Git deploys stay off. Production is an explicit promote after
// API_ORIGIN points at persistent FastAPI. Rewrites still describe the SPA
// + same-origin /api shape for a later manual or dashboard deploy.
export const config: VercelConfig = {
  framework: "vite",
  git: {
    deploymentEnabled: false,
  },
  headers: [
    {
      source: "/(.*)",
      headers: [
        {
          key: "Content-Security-Policy",
          value:
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'",
        },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "same-origin" },
        { key: "X-Frame-Options", value: "DENY" },
      ],
    },
    {
      source: "/index.html",
      headers: [
        { key: "Cache-Control", value: "no-store, no-cache, must-revalidate" },
      ],
    },
  ],
  rewrites: apiOrigin
    ? [
        { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
        { source: "/((?!api/).*)", destination: "/index.html" },
      ]
    : [{ source: "/((?!api/).*)", destination: "/index.html" }],
};
