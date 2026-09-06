import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // Air-gapped: no remote images, no external fonts, no CDN scripts.
  images: { remotePatterns: [] },
};

export default nextConfig;
