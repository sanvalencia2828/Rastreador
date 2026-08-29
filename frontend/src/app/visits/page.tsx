"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import Link from "next/link";

interface Visit {
  id: string | number;
  cnpj: string;
  lat: number;
  lon: number;
  logradouro: string | null;
  bairro: string | null;
  notes: string | null;
  route_id: string | null;
  visited_at: string;
  street_name: string | null;
}

interface CityOption {
  id: string | number;
  name: string;
  lat: number;
  lon: number;
}

type Status = "loading" | "error" | "success" | "empty";

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    const dd = String(d.getDate()).padStart(2, "0");
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const yyyy = d.getFullYear();
    return `${dd}/${mm}/${yyyy}`;
  } catch {
    return iso;
  }
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  } catch {
    return "";
  }
}

export default function VisitsPage() {
  const [visits, setVisits] = useState<Visit[]>([]);
  const [cities, setCities] = useState<CityOption[]>([]);
  const [selectedCityId, setSelectedCityId] = useState<string>("all");
  const [status, setStatus] = useState<Status>("loading");
  const [errorMessage, setErrorMessage] = useState<string | undefined>();

  useEffect(() => {
    let isMounted = true;
    const loadCities = async () => {
      try {
        const res = await fetch("/api/cities");
        if (!res.ok) return;
        const data = await res.json();
        if (!isMounted) return;
        setCities(data);
      } catch { /* silencioso */ }
    };
    loadCities();
    return () => { isMounted = false; };
  }, []);

  const loadVisits = useCallback(async (cityId: string) => {
    setStatus("loading");
    setErrorMessage(undefined);
    try {
      let url = "/api/visits";
      if (cityId !== "all") {
        const city = cities.find(c => String(c.id) === cityId);
        if (city) {
          const delta = 0.15;
          const bbox = `${city.lon - delta},${city.lat - delta},${city.lon + delta},${city.lat + delta}`;
          url = `/api/visits?bbox=${bbox}`;
        }
      }
      const res = await fetch(url);
      if (!res.ok) throw new Error("fail");
      const data = await res.json();
      setVisits(data);
      setStatus(data.length === 0 ? "empty" : "success");
    } catch {
      setStatus("error");
      setErrorMessage("No se pudieron cargar las visitas.");
    }
  }, [cities]);

  useEffect(() => {
    if (selectedCityId !== "all" && cities.length === 0) return;
    loadVisits(selectedCityId);
  }, [selectedCityId, cities.length, loadVisits]);

  const grouped = useMemo(() => {
    const sorted = [...visits].sort((a, b) => b.visited_at.localeCompare(a.visited_at));
    const groups: Record<string, Visit[]> = {};
    for (const v of sorted) {
      const day = formatDate(v.visited_at);
      if (!groups[day]) groups[day] = [];
      groups[day].push(v);
    }
    return Object.entries(groups);
  }, [visits]);

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
        <h1 className="text-lg lg:text-xl font-semibold tracking-tight" style={{ color: "var(--fg)" }}>Histórico de Visitas</h1>
        <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>Visitas registradas ordenadas por fecha</p>
      </header>

      <div className="mb-5">
        <select
          value={selectedCityId}
          onChange={(e) => setSelectedCityId(e.target.value)}
          className="text-xs font-medium"
          style={{
            padding: "8px 12px",
            background: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            color: "var(--fg)",
            cursor: "pointer",
            outline: "none",
            width: "100%",
            maxWidth: "280px",
          }}
        >
          <option value="all">Todas las ciudades</option>
          {cities.map(c => (
            <option key={c.id} value={String(c.id)}>{c.name}</option>
          ))}
        </select>
      </div>

      {status === "error" && (
        <p className="text-sm" style={{ color: "var(--error)" }}>{errorMessage}</p>
      )}

      {status === "empty" && (
        <div
          className="flex flex-col items-center gap-3 py-10 px-4 text-center"
          style={{ background: "var(--bg-elevated)", border: "1px dashed var(--border)", borderRadius: "var(--radius)" }}
        >
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ color: "var(--muted)" }}>
            <rect x="3" y="4" width="18" height="18" rx="2" />
            <line x1="16" y1="2" x2="16" y2="6" />
            <line x1="8" y1="2" x2="8" y2="6" />
            <line x1="3" y1="10" x2="21" y2="10" />
          </svg>
          <p className="text-sm" style={{ color: "var(--muted)" }}>Sin visitas registradas.</p>
        </div>
      )}

      {status === "loading" && (
        <p className="text-xs" style={{ color: "var(--muted)" }}>Cargando visitas...</p>
      )}

      {status === "success" && (
        <div className="flex flex-col gap-5">
          {grouped.map(([day, dayVisits]) => (
            <div key={day}>
              <div className="flex items-center gap-3 mb-2">
                <span className="text-xs font-semibold" style={{ color: "var(--accent)" }}>{day}</span>
                <span className="text-xs" style={{ color: "var(--muted)" }}>{dayVisits.length} visita{dayVisits.length !== 1 ? "s" : ""}</span>
                <div style={{ flex: 1, height: "1px", background: "var(--border)" }} />
              </div>
              <div className="flex flex-col gap-2">
                {dayVisits.map(v => (
                  <div
                    key={v.id}
                    className="flex items-start gap-3"
                    style={{
                      padding: "12px 14px",
                      background: "var(--card)",
                      border: "1px solid var(--border)",
                      borderRadius: "var(--radius)",
                    }}
                  >
                    <span className="flex-shrink-0" style={{ marginTop: "2px", color: "var(--accent)" }}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" /><circle cx="12" cy="10" r="3" /></svg>
                    </span>
                    <div className="flex-1" style={{ minWidth: 0 }}>
                      <p className="text-sm font-medium" style={{ color: "var(--fg)" }}>{v.logradouro || v.cnpj}</p>
                      {v.bairro && <p className="text-xs" style={{ color: "var(--fg-secondary)" }}>{v.bairro}</p>}
                      <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
                        <span style={{ color: "var(--accent)" }}>{formatTime(v.visited_at)}</span>
                        {" · "}
                        <span style={{ fontFamily: "monospace", fontSize: "11px" }}>{v.cnpj}</span>
                      </p>
                      {v.notes && <p className="text-xs mt-1" style={{ color: "var(--fg-secondary)" }}>{v.notes}</p>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}