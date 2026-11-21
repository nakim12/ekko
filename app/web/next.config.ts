import type { NextConfig } from "next";

// The FastAPI backend (app/api). The browser only talks to this origin; /api is proxied.
const api = process.env.EKKO_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  async rewrites() {
    return {
      // The approved landing page is served byte for byte from public/index.html.
      beforeFiles: [{ source: "/", destination: "/index.html" }],
      afterFiles: [{ source: "/api/:path*", destination: `${api}/api/:path*` }],
      fallback: [],
    };
  },
};

export default nextConfig;
