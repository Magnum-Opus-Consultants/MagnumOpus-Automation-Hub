import type { NextConfig } from "next";

// Origin of the Django backend (dev default; override with BACKEND_ORIGIN in .env.local)
const BACKEND = process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Next 16 blocks dev-only assets (/_next/*) requested from an origin it does
  // not recognise, and it treats 127.0.0.1 and the LAN IP as different origins
  // from localhost — which shows up as 403s on chunks and a failing HMR socket.
  // Dev-only setting; has no effect on a production build.
  allowedDevOrigins: ["127.0.0.1", "localhost", "100.108.209.54"],

  // The dev-tools badge defaults to the bottom-left, where it sits on top of the
  // sidebar's user block. Dev-only overlay; moving it keeps that corner readable.
  devIndicators: { position: "bottom-right" },

  async rewrites() {
    return [
      // Same-origin proxy for Django JSON endpoints — call fetch("/api/...") from
      // the React app and it hits the backend with no CORS. Trailing slashes are
      // preserved, so match whatever the Django route expects (usually a slash).
      { source: "/api/:path*", destination: `${BACKEND}/api/:path*` },
      // Published client sites and the shared stock images. nginx serves these
      // in production; without the rewrite a local preview renders the layout
      // with every photograph broken, which is the thing you need to see.
      { source: "/sites/:path*", destination: `${BACKEND}/sites/:path*` },
    ];
  },
};

export default nextConfig;
