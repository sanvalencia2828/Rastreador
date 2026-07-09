import { dirname } from "path";
import { fileURLToPath } from "url";

const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
const rootDir = dirname(fileURLToPath(import.meta.url));

const nextConfig = {
  turbopack: {
    root: rootDir,
  },
  async rewrites() {
    return [
      {
        source: "/api/businesses/:path*",
        destination: `${backendUrl}/api/businesses/:path*`,
      },
    ];
  },
};

export default nextConfig;
