// Frontend :3000 -> backend :8000. The browser only ever talks to :3000;
// Next proxies /api/* to the backend, so no CORS setup is needed.
const API = (process.env.NEXT_PUBLIC_API || "http://127.0.0.1:8000").replace(/\/$/, "");

export default {
  experimental: { proxyTimeout: 120000 },
  async rewrites() {
    return {
      beforeFiles: [
        { source: "/", destination: "/darkroom.html" },
        { source: "/api/:path*", destination: `${API}/api/:path*` },
        { source: "/media/:path*", destination: `${API}/media/:path*` },
      ],
    };
  },
};
