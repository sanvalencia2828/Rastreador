const backendUrl = process.env.BACKEND_URL || "http://localhost:8001";

const nextConfig = {
  turbopack: { root: "../frontend" },
  async rewrites() {
    return [
      {
        source: "/api/businesses/:path*",
        destination: `${backendUrl}/api/businesses/:path*`,
      },
      {
        source: "/api/visits/:path*",
        destination: `${backendUrl}/api/visits/:path*`,
      },
      {
        source: "/api/segments/:path*",
        destination: `${backendUrl}/api/segments/:path*`,
      },
      {
        source: "/api/street-coverage/:path*",
        destination: `${backendUrl}/api/street-coverage/:path*`,
      },
    ];
  },
};

export default nextConfig;
