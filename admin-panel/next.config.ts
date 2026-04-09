import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // basePath removed to serve from the root of the custom port
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
