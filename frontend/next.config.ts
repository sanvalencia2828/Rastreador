import path from "path";
import type { NextConfig } from "next";

const isExport = process.env.NEXT_OUTPUT === "export";
const backendUrl = (
  process.env.BACKEND_URL ||
  process.env.VITE_API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  ""
).replace(/\/$/, "");
const backendIsPublic = /^https?:\/\//.test(backendUrl) && !/localhost|127\.0\.0\.1/.test(backendUrl);
const onVercel = process.env.VERCEL === "1";

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

// On Vercel, never rewrite to localhost: that becomes DNS_HOSTNAME_RESOLVED_PRIVATE.
// A public BACKEND_URL/VITE_API_URL can be baked at build time. Otherwise the
// runtime proxy in src/app/api/[...path]/route.ts reads the env per request.
if (!isExport && backendIsPublic) {
  nextConfig.rewrites = async () => [
    { source: "/api/:path*", destination: `${backendUrl}/api/:path*` },
    { source: "/auth/:path*", destination: `${backendUrl}/auth/:path*` },
  ];
} else if (!isExport && !onVercel) {
  const localBackend = backendUrl || "http://localhost:8001";
  nextConfig.rewrites = async () => [
    { source: "/api/:path*", destination: `${localBackend}/api/:path*` },
    { source: "/auth/:path*", destination: `${localBackend}/auth/:path*` },
  ];
}

export default nextConfig;
