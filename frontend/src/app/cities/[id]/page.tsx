"use client";

import { useState, useRef, useCallback, useMemo, useEffect, use } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import SearchBar from "../../components/SearchBar";
import StatusMessage from "../../components/StatusMessage";
import StopCard from "../../components/StopCard";
import type { Stop, Business } from "../../types";

const MapView = dynamic(() => import("../../components/MapView"), { ssr: false });

type Status = "empty" | "loading" | "error" | "success";
type FilterType = "all" | "new" | "visited" | "client";

interface CityStats {
  id: number | string;
  name: string;
  state: string;
  lat: number;
  lon: number;
  total_businesses: number;
}

export default function CityPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  const [city, setCity] = useState<CityStats | null>(null);
  const [cityError, setCityError] = useState<string | undefined>();
  const [cityLoading, setCityLoading] = useState(true);

  const [status, setStatus] = useState<Status>("empty");
  const [errorMessage, setErrorMessage] = useState<string | undefined>();
  const [stops, setStops] = useState<Stop[]>([]);
  const [filter, setFilter] = useState<FilterType>("all");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let isMounted = true;

    const loadCity = async () => {
      try {
        const res = await fetch(`/api/cities/${id}/stats`);
        if (!res.ok) throw new Error("fail");
        const data: CityStats = await res.json();
        if (!isMounted) return;
        setCity(data);
      } catch {
        if (isMounted) setCityError("No se pudo cargar la ciudad.");
      } finally {
        if (isMounted) setCityLoading(false);
      }
    };

    loadCity();

    return () => {
      isMounted = false;
    };
  }, [id]);

  const fetchBusinesses = useCallback(async (stopId: string, lat: number, lon: number) => {
    setStops(prev => prev.map(s => s.id === stopId ? { ...s, loadingBusinesses: true } : s));
    try {
      const res = await fetch(`/api/businesses/near?lat=${lat}&lon=${lon}&radius=500`);
      if (!res.ok) throw new Error("fail");
      const data = await res.json();
      setStops(prev => prev.map(s => s.id === stopId ? { ...s, businesses: data.items, loadingBusinesses: false } : s));
    } catch {
      setStops(prev => prev.map(s => s.id === stopId ? { ...s, loadingBusinesses: false } : s));
    }
  }, []);

  const handleSearch = useCallback(async (address: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus("loading");
    setErrorMessage(undefined);
    try {
      const res = await fetch("/api/geocode", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ address }), signal: controller.signal });
      const data = await res.json();
      if (!res.ok) { setStatus("error"); setErrorMessage(data.error || "Error desconocido."); return; }
      const newStop: Stop = { id: crypto.randomUUID(), address, lat: data.lat, lon: data.lon, displayName: data.display_name, cep: data.cep, businesses: [], loadingBusinesses: true };
      setStops(prev => [...prev, newStop]);
      setStatus("success");
      fetchBusinesses(newStop.id, data.lat, data.lon);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setStatus("error");
      setErrorMessage("No se pudo conectar al servidor.");
    }
  }, [fetchBusinesses]);

  const handleRemoveStop = useCallback((stopId: string) => {
    setStops(prev => {
      const next = prev.filter(s => s.id !== stopId);
      if (next.length === 0) setStatus("empty");
      return next;
    });
  }, []);

  const handleMarkVisited = useCallback((cnpj: string) => {
    setStops(prev => prev.map(stop => ({
      ...stop,
      businesses: stop.businesses.map(b => b.cnpj === cnpj ? { ...b, status: "visited" as const } : b),
    })));
  }, []);

  const handleMarkClient = useCallback((cnpj: string) => {
    setStops(prev => prev.map(stop => ({
      ...stop,
      businesses: stop.businesses.map(b => b.cnpj === cnpj ? { ...b, status: "client" as const } : b),
    })));
  }, []);

  const allBusinesses = useMemo(() => stops.flatMap(s => s.businesses), [stops]);

  const filteredBusinesses = useMemo(() => {
    if (filter === "all") return allBusinesses;
    return allBusinesses.filter(b => b.status === filter);
  }, [allBusinesses, filter]);

  const counts = useMemo(() => ({
    all: allBusinesses.length,
    new: allBusinesses.filter(b => !b.status || b.status === "new").length,
    visited: allBusinesses.filter(b => b.status === "visited").length,
    client: allBusinesses.filter(b => b.status === "client").length,
  }), [allBusinesses]);

  const mapBusinesses = useMemo(() => filteredBusinesses.map(b => ({ lat: b.lat, lon: b.lon, nome_fantasia: b.nome_fantasia, distance_m: b.distance_m, status: b.status })), [filteredBusinesses]);

  const mapCenter = city ? { lat: city.lat, lon: city.lon } : undefined;

  if (cityLoading) {
    return (
      <main className="flex flex-col min-h-dvh" style={{ padding: "24px 20px", maxWidth: "1200px", margin: "0 auto", width: "100%" }}>
        <p className="text-xs" style={{ color: "var(--muted)" }}>Cargando ciudad...</p>
      </main>
    );
  }

  if (cityError || !city) {
    return (
      <main className="flex flex-col min-h-dvh" style={{ padding: "24px 20px", maxWidth: "1200px", margin: "0 auto", width: "100%" }}>
        <Link href="/cities" className="inline-flex items-center gap-1 text-xs font-medium mb-4" style={{ color: "var(--accent)", textDecoration: "none" }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" /></svg>
          Cidades
        </Link>
        <StatusMessage type="error" message={cityError ?? "Ciudad no encontrada."} />
      </main>
    );
  }

  return (
    <main className="flex flex-col min-h-dvh" style={{ padding: "24px 20px", maxWidth: "1200px", margin: "0 auto", width: "100%" }}>
      <header className="mb-6">
        <Link href="/cities" className="inline-flex items-center gap-1 text-xs font-medium mb-3" style={{ color: "var(--accent)", textDecoration: "none" }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" /></svg>
          Cidades
        </Link>
        <h1 className="text-xl font-semibold tracking-tight" style={{ color: "var(--fg)" }}>{city.name}</h1>
        <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>{city.total_businesses} lojas registradas · {city.state}</p>
      </header>
      <div className="mb-5">
        <SearchBar onSearch={handleSearch} isLoading={status === "loading"} />
      </div>
      <div className="flex flex-col lg:flex-row gap-5 flex-1">
        <div className="lg:w-2/3" style={{ minHeight: "400px", height: "100%" }}>
          <MapView stops={stops.map(s => ({ id: s.id, lat: s.lat, lon: s.lon }))} businesses={mapBusinesses} center={mapCenter} />
        </div>
        <aside className="lg:w-1/3 flex flex-col gap-4">
          {stops.length > 0 && (
            <>
              <div className="flex items-center gap-4 text-xs" style={{ padding: "12px 16px", background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius)" }}>
                <span><span className="font-semibold" style={{ color: "var(--accent)" }}>{stops.length}</span><span style={{ color: "var(--muted)" }}> paradas</span></span>
                <span><span className="font-semibold" style={{ color: "#f59e0b" }}>{counts.all}</span><span style={{ color: "var(--muted)" }}> lojas</span></span>
                <span><span className="font-semibold" style={{ color: "#22c55e" }}>{counts.visited}</span><span style={{ color: "var(--muted)" }}> visitadas</span></span>
              </div>
              <div className="flex gap-2 flex-wrap">
                {(["all", "new", "visited", "client"] as FilterType[]).map(f => (
                  <button key={f} onClick={() => setFilter(f)} className="text-xs font-medium" style={{ padding: "5px 10px", borderRadius: "6px", border: "1px solid", borderColor: filter === f ? (f === "new" ? "#f59e0b" : f === "visited" ? "#22c55e" : f === "client" ? "#8b5cf6" : "var(--fg-secondary)") : "var(--border)", background: filter === f ? (f === "new" ? "#f59e0b15" : f === "visited" ? "#22c55e15" : f === "client" ? "#8b5cf615" : "transparent") : "transparent", color: filter === f ? (f === "new" ? "#f59e0b" : f === "visited" ? "#22c55e" : f === "client" ? "#8b5cf6" : "var(--fg-secondary)") : "var(--muted)", cursor: "pointer", transition: "all 0.2s" }}>
                    {f === "all" ? "Todas" : f === "new" ? "Nuevas" : f === "visited" ? "Visitadas" : "Clientes"} ({counts[f]})
                  </button>
                ))}
              </div>
            </>
          )}
          {stops.length === 0 && <StatusMessage type={status} message={status === "error" ? errorMessage : undefined} />}
          <div className="flex flex-col gap-3" style={{ maxHeight: "calc(100dvh - 340px)", overflowY: "auto" }}>
            {stops.map((stop, i) => (
              <StopCard key={stop.id} index={i} displayName={stop.displayName} cep={stop.cep} businesses={stop.businesses} loadingBusinesses={stop.loadingBusinesses} onRemove={() => handleRemoveStop(stop.id)} onMarkVisited={handleMarkVisited} onMarkClient={handleMarkClient} />
            ))}
          </div>
          <div className="hidden lg:block flex-1" />
          <div className="text-xs" style={{ color: "var(--muted)", lineHeight: "1.5" }}>
            <p><span style={{ color: "var(--accent)", fontWeight: 500 }}>●</span> Parada</p>
            <p><span style={{ color: "#f59e0b", fontWeight: 500 }}>●</span> Nueva</p>
            <p><span style={{ color: "#22c55e", fontWeight: 500 }}>●</span> Visitada</p>
            <p><span style={{ color: "#8b5cf6", fontWeight: 500 }}>■</span> Cliente</p>
          </div>
        </aside>
      </div>
    </main>
  );
}