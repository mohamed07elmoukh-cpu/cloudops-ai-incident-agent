import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  outputFileTracingRoot: process.cwd(),
  turbopack: { root: process.cwd() },
  allowedDevOrigins: ["localhost", "127.0.0.1"],
};

export default nextConfig;
