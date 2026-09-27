import path from "path";
import type { NextConfig } from "next";

const isExport = process.env.NEXT_OUTPUT === "export";
const backendUrl =
  process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

const nextConfig: NextConfig = {
  turbopack: { root: path.resolve(process.cwd()) },
  ...(isExport
    ? {
        output: "export",
        trailingSlash: true,
        images: { unoptimized: true },
      }
    : {}),
};

if (!isExport) {
  nextConfig.rewrites = async () => [
    { source: "/api/geocode", destination: `${backendUrl}/api/geocode` },
    { source: "/api/v1/:path*", destination: `${backendUrl}/api/v1/:path*` },
    { source: "/api/businesses/status", destination: `${backendUrl}/api/businesses/status` },
    { source: "/api/businesses/search", destination: `${backendUrl}/api/businesses/search` },
    { source: "/api/businesses/:cnpj/status", destination: `${backendUrl}/api/businesses/:cnpj/status` },
    { source: "/api/businesses/:path*", destination: `${backendUrl}/api/businesses/:path*` },
    { source: "/api/routes/:path*", destination: `${backendUrl}/api/routes/:path*` },
    { source: "/api/visits/:path*", destination: `${backendUrl}/api/visits/:path*` },
    { source: "/api/segments/:path*", destination: `${backendUrl}/api/segments/:path*` },
    { source: "/api/street-coverage/:path*", destination: `${backendUrl}/api/street-coverage/:path*` },
    { source: "/api/cities/:path*", destination: `${backendUrl}/api/cities/:path*` },
    { source: "/api/stats/:path*", destination: `${backendUrl}/api/stats/:path*` },
    { source: "/api/heatmap", destination: `${backendUrl}/api/heatmap` },
    { source: "/api/daily-routes/:path*", destination: `${backendUrl}/api/daily-routes/:path*` },
  ];
}

export default nextConfig;
