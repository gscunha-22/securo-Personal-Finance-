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

const csp =
  "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'";

// Used when the Vercel Root Directory is the repo root (not frontend/).
export const config: VercelConfig = {
  framework: "vite",
  installCommand: "npm ci --prefix frontend",
  buildCommand: "npm run build --prefix frontend",
  outputDirectory: "frontend/dist",
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
