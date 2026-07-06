const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";

const nextConfig = {
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
