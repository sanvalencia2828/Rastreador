"use client";

import { useState, useEffect } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import StatusMessage from "../components/StatusMessage";

const MapaCobertura = dynamic(() => import("./MapaCobertura"), { ssr: false });

interface StatsSummary {
  total_businesses: number;
  visited: number;
  clients: number;
  cities: CityStat[];
}

interface CityStat {
  id: number;
  name: string;
  state: string;
  lat: number | null;
  lon: number | null;
  total: number;
  visited: number;
}

type Status = "loading" | "error" | "success";

export default function DashboardPage() {
  const [stats, setStats] = useState<StatsSummary | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [errorMessage, setErrorMessage] = useState<string | undefined>();

  useEffect(() => {
    let isMounted = true;

    const load = async () => {
      try {
        const res = await fetch("/api/stats/summary");
        if (!res.ok) throw new Error("fail");
        const data: StatsSummary = await res.json();
        if (!isMounted) return;
        setStats(data);
        setStatus("success");
      } catch {
        if (isMounted) {
          setStatus("error");
          setErrorMessage("No se pudieron cargar las estadísticas.");
        }
      }
    };

    load();

    return () => {
      isMounted = false;
    };
  }, []);

  const cards = stats
    ? [
        {
          label: "Total lojas",
          value: stats.total_businesses,
          color: "var(--accent)",
          icon: (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
              <polyline points="9 22 9 12 15 12 15 22" />
            </svg>
          ),
        },
        {
          label: "Visitadas",
          value: stats.visited,
          color: "#22c55e",
          icon: (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
              <circle cx="12" cy="10" r="3" />
            </svg>
          ),
        },
        {
          label: "Clientes",
          value: stats.clients,
          color: "#8b5cf6",
          icon: (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
              <circle cx="8.5" cy="7" r="4" />
              <line x1="20" y1="8" x2="20" y2="14" />
              <line x1="23" y1="11" x2="17" y2="11" />
            </svg>
          ),
        },
      ]
    : [];

  return (
    <main className="flex flex-col min-h-dvh px-4 py-4 lg:px-6 lg:py-6" style={{ maxWidth: "900px", margin: "0 auto", width: "100%" }}>
      <header className="mb-6">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-xs font-medium mb-3 transition-colors"
          style={{ color: "var(--muted)", textDecoration: "none" }}
          onMouseEnter={(e) => { e.currentTarget.style.color = "var(--accent)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = "var(--muted)"; }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" /></svg>
          Inicio
        </Link>
        <h1 className="text-lg lg:text-xl font-semibold tracking-tight" style={{ color: "var(--fg)" }}>Dashboard</h1>
        <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>Cobertura de visitas por ciudad</p>
      </header>

      {status === "loading" && <StatusMessage type="loading" />}
      {status === "error" && <StatusMessage type="error" message={errorMessage} />}

      {status === "success" && stats && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
            {cards.map((card) => (
              <div
                key={card.label}
                className="flex flex-col gap-3"
                style={{
                  padding: "20px",
                  background: "var(--card)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius)",
                }}
              >
                <div className="flex items-center justify-between">
                  <span style={{ color: card.color }}>{card.icon}</span>
                  <span className="text-2xl font-bold" style={{ color: "var(--fg)" }}>{card.value}</span>
                </div>
                <p className="text-xs" style={{ color: "var(--muted)" }}>{card.label}</p>
              </div>
            ))}
          </div>

          <div className="flex flex-col gap-3">
            <p className="text-xs font-medium" style={{ color: "var(--fg-secondary)" }}>Cobertura por ciudad</p>
            {stats.cities.map((city) => {
              const pct = city.total > 0 ? Math.round((city.visited / city.total) * 100) : 0;
              return (
                <div
                  key={city.id}
                  style={{
                    padding: "14px 16px",
                    background: "var(--card)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius)",
                  }}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium" style={{ color: "var(--fg)" }}>{city.name}</span>
                    <span className="text-xs" style={{ color: "var(--muted)" }}>
                      <span style={{ color: "var(--accent)", fontWeight: 600 }}>{city.visited}</span>
                      {" de "}
                      <span style={{ color: "var(--fg-secondary)", fontWeight: 600 }}>{city.total}</span>
                      {" lojas"}
                      <span style={{ marginLeft: "6px", color: "var(--fg-secondary)" }}>({pct}%)</span>
                    </span>
                  </div>
                  <div style={{ height: "6px", background: "var(--border)", borderRadius: "3px", overflow: "hidden" }}>
                    <div
                      style={{
                        height: "100%",
                        width: `${pct}%`,
                        background: "var(--accent)",
                        borderRadius: "3px",
                        transition: "width 0.4s ease",
                      }}
                    />
                  </div>
                </div>
              );
            })}
            {stats.cities.length === 0 && (
              <p className="text-xs" style={{ color: "var(--muted)" }}>Sin datos de ciudades.</p>
            )}
          </div>

          {stats.cities.length > 0 && (
            <div className="mt-6">
              <p className="text-xs font-medium mb-1" style={{ color: "var(--fg-secondary)" }}>Mapa de cobertura</p>
              <MapaCobertura cities={stats.cities} />
              <div className="flex items-center gap-4 flex-wrap" style={{ padding: "10px 14px", background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius)", marginTop: "12px" }}>
                <span className="text-xs" style={{ color: "var(--muted)" }}>Cobertura:</span>
                <span className="flex items-center gap-1.5 text-xs" style={{ color: "var(--fg-secondary)" }}>
                  <span style={{ width: "10px", height: "10px", borderRadius: "50%", background: "#ff5c5c", display: "inline-block" }} />
                  &lt;30%
                </span>
                <span className="flex items-center gap-1.5 text-xs" style={{ color: "var(--fg-secondary)" }}>
                  <span style={{ width: "10px", height: "10px", borderRadius: "50%", background: "#f59e0b", display: "inline-block" }} />
                  30-60%
                </span>
                <span className="flex items-center gap-1.5 text-xs" style={{ color: "var(--fg-secondary)" }}>
                  <span style={{ width: "10px", height: "10px", borderRadius: "50%", background: "#22c55e", display: "inline-block" }} />
                  &gt;60%
                </span>
              </div>
            </div>
          )}
        </>
      )}
    </main>
  );
}