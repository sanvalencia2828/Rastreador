const backendUrl = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

// Rutas concretas que van ANTES de los comodines (se conserva el orden original).
const EXACT_ROUTES = [
  "/api/businesses/status",
  "/api/businesses/search",
  "/api/businesses/:cnpj/status",
];

// Prefijos que se reenvían al backend. Cada uno lleva DOS reglas: la exacta (el prefijo solo, p. ej.
// GET /api/clientes) y `${prefix}/:path*`. Sin la exacta, `:path*` con cero segmentos manda el destino
// con barra final (/api/clientes/), FastAPI responde 307 a su propio dominio y el navegador lo bloquea.
// Si el frontend llama a un prefijo nuevo, agrégalo aquí: tests/test_frontend_rewrites.py falla si falta alguno.
// /api/geocode NO va: es una ruta local de Next (src/app/api/geocode/route.ts).
const BACKEND_PREFIXES = [
  "/api/businesses",
  "/api/routes",
  "/api/visits",
  "/api/segments",
  "/api/street-coverage",
  "/api/cities",
  "/auth",
  "/api/stats",
  "/api/clientes",
  "/api/tarjetas",
];

const nextConfig = {
  turbopack: { root: "../frontend" },
  async rewrites() {
    return [
      ...EXACT_ROUTES.map((route) => ({ source: route, destination: `${backendUrl}${route}` })),
      ...BACKEND_PREFIXES.map((prefix) => ({ source: prefix, destination: `${backendUrl}${prefix}` })),
      ...BACKEND_PREFIXES.map((prefix) => ({
        source: `${prefix}/:path*`,
        destination: `${backendUrl}${prefix}/:path*`,
      })),
    ];
  },
};

export default nextConfig;
