import type { VercelConfig } from "@vercel/config/v1";

const apiOrigin = (process.env.API_ORIGIN ?? "").trim().replace(/\/+$/, "");

const csp =
  "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'";

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
        { key: "Content-Security-Policy", value: csp },
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
