import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Flask Backend Proxy (exclude NextAuth routes)
  async rewrites() {
    return [
      {
        source: '/api/auth/:path*',
        destination: '/api/auth/:path*',  // Keep auth on Next.js
      },
      {
        source: '/api/:path*',
        destination: 'http://localhost:5001/api/:path*',
      },
    ];
  },
};

export default nextConfig;
