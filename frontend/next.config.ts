const backendUrl = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

const nextConfig = {
  turbopack: { root: "../frontend" },
  async rewrites() {
    return [
      {
        source: "/api/businesses/status",
        destination: `${backendUrl}/api/businesses/status`,
      },
      {
        source: "/api/businesses/:cnpj/status",
        destination: `${backendUrl}/api/businesses/:cnpj/status`,
      },
      {
        source: "/api/businesses/:path*",
        destination: `${backendUrl}/api/businesses/:path*`,
      },
      {
        source: "/api/routes/:path*",
        destination: `${backendUrl}/api/routes/:path*`,
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
      {
        source: "/api/cities/:path*",
        destination: `${backendUrl}/api/cities/:path*`,
      },
    ];
  },
};

export default nextConfig;
