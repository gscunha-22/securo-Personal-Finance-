const apiOrigin = (process.env.API_ORIGIN ?? "").trim().replace(/\/+$/, "");

if (!apiOrigin) {
  throw new Error(
    "Set API_ORIGIN to the persistent FastAPI origin (scheme + host, no trailing slash), e.g. https://api.example.com",
  );
}

const csp =
  "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'";

export const config = {
  framework: "vite",
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
  rewrites: [
    { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
    { source: "/((?!api/).*)", destination: "/index.html" },
  ],
};
