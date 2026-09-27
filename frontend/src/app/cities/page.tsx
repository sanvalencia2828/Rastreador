"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import StatusMessage from "../components/StatusMessage";

interface CityWithStats {
  id: string | number;
  name: string;
  state: string;
  lat: number;
  lon: number;
  total_businesses: number | null;
}

const skeletonCards = Array.from({ length: 6 }, (_, index) => index);

export default function CitiesPage() {
  const [citiesWithStats, setCitiesWithStats] = useState<CityWithStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | undefined>();

  useEffect(() => {
    let isMounted = true;

    const load = async () => {
      try {
        const res = await fetch("/api/cities");
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          const detail = typeof body.detail === "string" ? body.detail : `Error ${res.status}`;
          throw new Error(detail);
        }
        const data = await res.json();
        if (!isMounted) return;

        const baseCities: CityWithStats[] = (data as Array<{ id: string | number; name: string; state: string; lat: number; lon: number }>).map(c => ({
          id: c.id,
          name: c.name,
          state: c.state,
          lat: c.lat,
          lon: c.lon,
          total_businesses: null,
        }));
        setCitiesWithStats(baseCities);
        setLoading(false);

        const statsResults = await Promise.allSettled(
          baseCities.map(async (city) => {
            const statRes = await fetch(`/api/cities/${city.id}/stats`);
            if (!statRes.ok) throw new Error(`Unable to fetch stats for ${city.id}`);
            const stat = await statRes.json();
            return stat.total_businesses ?? null;
          })
        );

        if (!isMounted) return;

        setCitiesWithStats(prev =>
          prev.map((city, i) => {
            const result = statsResults[i];
            if (!result || result.status === "rejected") return city;
            return { ...city, total_businesses: result.value };
          })
        );
      } catch (err) {
        if (isMounted) {
          setError(err instanceof Error ? err.message : "No se pudieron cargar las ciudades en este momento.");
          setLoading(false);
        }
      }
    };

    load();

    return () => {
      isMounted = false;
    };
  }, []);

  return (
    <main
      className="w-full"
      style={{
        maxWidth: "1200px",
        margin: "0 auto",
        width: "100%",
      }}
    >
      <header className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight" style={{ color: "var(--fg)" }}>
          Cidades
        </h1>
        <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
          Seleccioná una ciudad para ver rutas
        </p>
      </header>

      {loading && citiesWithStats.length === 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {skeletonCards.map((item) => (
            <div
              key={item}
              className="rounded-[var(--radius)] border"
              style={{
                background: "var(--card)",
                borderColor: "var(--border)",
                padding: "20px",
                minHeight: "152px",
              }}
            >
              <div
                style={{
                  height: "14px",
                  width: "60%",
                  borderRadius: "999px",
                  background: "linear-gradient(90deg, var(--bg-elevated) 25%, var(--card) 50%, var(--bg-elevated) 75%)",
                  backgroundSize: "200% 100%",
                  animation: "shimmer 1.2s ease-in-out infinite",
                  marginBottom: "12px",
                }}
              />
              <div
                style={{
                  height: "12px",
                  width: "30%",
                  borderRadius: "999px",
                  background: "linear-gradient(90deg, var(--bg-elevated) 25%, var(--card) 50%, var(--bg-elevated) 75%)",
                  backgroundSize: "200% 100%",
                  animation: "shimmer 1.2s ease-in-out infinite",
                  marginBottom: "14px",
                }}
              />
              <div
                style={{
                  height: "12px",
                  width: "45%",
                  borderRadius: "999px",
                  background: "linear-gradient(90deg, var(--bg-elevated) 25%, var(--card) 50%, var(--bg-elevated) 75%)",
                  backgroundSize: "200% 100%",
                  animation: "shimmer 1.2s ease-in-out infinite",
                  marginBottom: "18px",
                }}
              />
              <div
                style={{
                  height: "36px",
                  width: "100%",
                  borderRadius: "8px",
                  background: "linear-gradient(90deg, var(--bg-elevated) 25%, var(--card) 50%, var(--bg-elevated) 75%)",
                  backgroundSize: "200% 100%",
                  animation: "shimmer 1.2s ease-in-out infinite",
                }}
              />
            </div>
          ))}
        </div>
      ) : null}

      {error && !loading ? <StatusMessage type="error" message={error} /> : null}

      {!error && citiesWithStats.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {citiesWithStats.map((city) => (
            <article
              key={city.id}
              className="flex flex-col gap-4 rounded-[var(--radius)] border"
              style={{
                background: "var(--card)",
                borderColor: "var(--border)",
                padding: "20px",
              }}
            >
              <div>
                <h2 className="text-base font-medium" style={{ color: "var(--fg)" }}>
                  {city.name}
                </h2>
                <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
                  {city.state}
                </p>
              </div>

              {city.total_businesses !== null && (
                <p className="text-xs" style={{ color: "var(--accent)" }}>
                  {city.total_businesses} lojas registradas
                </p>
              )}

              <Link
                href={`/cities/${city.id}`}
                className="inline-flex items-center justify-center text-sm font-medium transition-colors"
                style={{
                  background: "var(--bg-elevated)",
                  border: "1px solid var(--border)",
                  borderRadius: "8px",
                  color: "var(--fg-secondary)",
                  padding: "10px 12px",
                  textDecoration: "none",
                }}
              >
                Ver mapa
              </Link>
            </article>
          ))}
        </div>
      ) : null}

      <style jsx global>{`
        @keyframes shimmer {
          0% {
            background-position: 200% 0;
          }
          100% {
            background-position: -200% 0;
          }
        }
      `}</style>
    </main>
  );
}