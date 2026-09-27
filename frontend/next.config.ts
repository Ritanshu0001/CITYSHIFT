import type { NextConfig } from "next";
import { loadEnvConfig } from "@next/env";
import { resolve } from "node:path";

// Next initially checks frontend/. Reload from the shared repository root before
// reading settings; forceReload bypasses that initial cached environment lookup.
loadEnvConfig(resolve(__dirname, ".."), process.env.NODE_ENV === "development", undefined, true);

const backendOrigin = process.env.CITYSHIFT_BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  env: {
    // Browser Maps/Places/Street View key, inlined into the client bundle (public by design; restrict it by
    // HTTP referrer in Google Cloud). The old NEXT_PUBLIC_GOOGLE_MAPS_KEY name still works.
    GOOGLE_MAPS_KEY: process.env.GOOGLE_MAPS_KEY || process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY || "",
  },
  async rewrites() {
    return [
      {
        source: "/api/backend/:path*",
        destination: `${backendOrigin}/:path*`,
      },
    ];
  },
};

export default nextConfig;
