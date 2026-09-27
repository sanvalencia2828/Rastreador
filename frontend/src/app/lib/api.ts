/** Relative by default so Vercel can proxy. A public NEXT_PUBLIC_* URL is optional. */
export function apiPath(path: string): string {
  const raw = (
    process.env.NEXT_PUBLIC_API_URL ||
    process.env.NEXT_PUBLIC_VITE_API_URL ||
    ""
  )
    .trim()
    .replace(/\/$/, "");
  if (!raw || raw.startsWith("/")) return path;
  const local = /localhost|127\.0\.0\.1/.test(raw);
  if (process.env.NODE_ENV === "production" && local) return path;
  return `${raw}${path}`;
}
