/** Same-origin API paths. A baked localhost URL is ignored in production builds. */
export function apiPath(path: string): string {
  const raw = (process.env.NEXT_PUBLIC_API_URL || "").trim().replace(/\/$/, "");
  if (!raw || raw.startsWith("/")) return path;
  const local = /localhost|127\.0\.0\.1/.test(raw);
  if (process.env.NODE_ENV === "production" && local) return path;
  return `${raw}${path}`;
}
