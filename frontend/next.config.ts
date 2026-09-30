import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the container image (deploy/). Vercel
  // ignores this and builds as usual.
  output: "standalone",
  // Rewrites are evaluated at BUILD time: BACKEND_ORIGIN must be set when
  // `next build` runs (Vercel env var, or the Docker build arg).
  async rewrites() {
    const backend = process.env.BACKEND_ORIGIN || "http://localhost:8000";
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
    ];
  },
};

export default nextConfig;
