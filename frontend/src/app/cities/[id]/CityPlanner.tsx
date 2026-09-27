"use client";

import { useState, useRef, useCallback, useMemo, useEffect } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import SearchBar from "../../components/SearchBar";
import StatusMessage from "../../components/StatusMessage";
import StopCard from "../../components/StopCard";
import type { Stop, Business, SavedRoute } from "../../types";

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

export default function CityPage({ id }: { id: string }) {
  const searchParams = useSearchParams();
  const paramLat = searchParams?.get("lat");
  const paramLon = searchParams?.get("lon");

  const [city, setCity] = useState<CityStats | null>(null);
  const [cityError, setCityError] = useState<string | undefined>();
  const [cityLoading, setCityLoading] = useState(true);

  const [status, setStatus] = useState<Status>("empty");
  const [errorMessage, setErrorMessage] = useState<string | undefined>();
  const [stops, setStops] = useState<Stop[]>([]);
  const [filter, setFilter] = useState<FilterType>("all");
  const [savedRoutes, setSavedRoutes] = useState<SavedRoute[]>([]);
  const [loadingRouteId, setLoadingRouteId] = useState<string | undefined>();
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
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

    const loadRoutes = async () => {
      try {
        const res = await fetch(`/api/cities/${id}/routes`);
        if (!res.ok) return;
        const data = await res.json();
        if (!isMounted) return;
        setSavedRoutes(data);
      } catch {
        /* silencioso */
      }
    };

    loadRoutes();

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

  const handleLoadRoute = useCallback(async (route: SavedRoute) => {
    setLoadingRouteId(route.id);
    const newStops: Stop[] = route.stops.map(s => ({
      id: crypto.randomUUID(),
      address: s.address,
      lat: s.lat,
      lon: s.lon,
      displayName: s.display_name || s.address,
      cep: s.cep,
      businesses: [],
      loadingBusinesses: true,
    }));
    setStops(newStops);
    setStatus("success");

    const allBusinesses: Business[] = [];
    await Promise.all(newStops.map(async (stop) => {
      try {
        const res = await fetch(`/api/businesses/near?lat=${stop.lat}&lon=${stop.lon}&radius=500`);
        if (!res.ok) return;
        const data = await res.json();
        const businesses: Business[] = data.items;
        allBusinesses.push(...businesses);
        setStops(prev => prev.map(s => s.id === stop.id ? { ...s, businesses, loadingBusinesses: false } : s));
      } catch {
        setStops(prev => prev.map(s => s.id === stop.id ? { ...s, loadingBusinesses: false } : s));
      }
    }));

    const allCnpjs = allBusinesses.map(b => b.cnpj).filter(Boolean);
    if (allCnpjs.length > 0) {
      try {
        const res = await fetch(`/api/businesses/status?cnpjs=${allCnpjs.join(",")}`);
        if (res.ok) {
          const statusMap = await res.json();
          setStops(prev => prev.map(stop => ({
            ...stop,
            businesses: stop.businesses.map(b => ({
              ...b,
              status: (statusMap[b.cnpj] as "visited" | "client") || b.status || "new",
            })),
          })));
        }
      } catch { /* silencioso */ }
    }

    setLoadingRouteId(undefined);
  }, []);

  const handleConfirmDelete = useCallback(async () => {
    const routeId = confirmDeleteId;
    if (!routeId) return;

    const route = savedRoutes.find(r => r.id === routeId);

    try {
      const res = await fetch(`/api/routes/${routeId}`, { method: "DELETE" });
      if (!res.ok) throw new Error("delete failed");

      setSavedRoutes(prev => prev.filter(r => r.id !== routeId));

      if (route && stops.length === route.stops.length) {
        const routeAddrs = new Set(route.stops.map(s => s.address));
        const matches = stops.every(s => routeAddrs.has(s.address));
        if (matches) {
          setStops([]);
          setStatus("empty");
        }
      }

      setConfirmDeleteId(null);
    } catch (err) {
      console.error("Error deleting route:", err);
    }
  }, [confirmDeleteId, savedRoutes, stops]);

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

  const paramLatNum = paramLat ? parseFloat(paramLat) : NaN;
  const paramLonNum = paramLon ? parseFloat(paramLon) : NaN;
  const mapCenter = !isNaN(paramLatNum) && !isNaN(paramLonNum)
    ? { lat: paramLatNum, lon: paramLonNum }
    : city ? { lat: city.lat, lon: city.lon } : undefined;

  if (cityLoading) {
    return (
      <main className="flex flex-col min-h-dvh px-4 py-4 lg:px-5 lg:py-6" style={{ maxWidth: "1200px", margin: "0 auto", width: "100%" }}>
        <p className="text-xs" style={{ color: "var(--muted)" }}>Cargando ciudad...</p>
      </main>
    );
  }

  if (cityError || !city) {
    return (
      <main className="flex flex-col min-h-dvh px-4 py-4 lg:px-5 lg:py-6" style={{ maxWidth: "1200px", margin: "0 auto", width: "100%" }}>
        <Link href="/cities" className="inline-flex items-center gap-1 text-xs font-medium mb-4" style={{ color: "var(--accent)", textDecoration: "none" }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" /></svg>
          Cidades
        </Link>
        <StatusMessage type="error" message={cityError ?? "Ciudad no encontrada."} />
      </main>
    );
  }

  return (
    <main className="flex flex-col min-h-dvh px-4 py-4 lg:px-5 lg:py-6" style={{ maxWidth: "1200px", margin: "0 auto", width: "100%" }}>
      <header className="mb-5 lg:mb-6">
        <Link href="/cities" className="inline-flex items-center gap-1 text-xs font-medium mb-3" style={{ color: "var(--accent)", textDecoration: "none" }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" /></svg>
          Cidades
        </Link>
        <h1 className="text-lg lg:text-xl font-semibold tracking-tight" style={{ color: "var(--fg)" }}>{city.name}</h1>
        <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>{city.total_businesses} lojas registradas · {city.state}</p>
      </header>
      <div className="mb-4 lg:mb-5">
        <SearchBar onSearch={handleSearch} isLoading={status === "loading"} />
      </div>
      <div className="flex flex-col lg:flex-row gap-4 lg:gap-5 flex-1">
        <div className="lg:w-2/3 h-[50dvh] lg:h-full min-h-[300px] lg:min-h-[400px]">
          <MapView stops={stops.map(s => ({ id: s.id, lat: s.lat, lon: s.lon }))} businesses={mapBusinesses} center={mapCenter} />
        </div>
        <aside className="lg:w-1/3 flex flex-col gap-4">
          {savedRoutes.length > 0 && (
            <div className="flex flex-col gap-2" style={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: "12px" }}>
              <p className="text-xs font-medium" style={{ color: "var(--muted)" }}>Rutas guardadas</p>
              {savedRoutes.map(route => (
                <div key={route.id} className="flex flex-col gap-2">
                  <div className="flex items-center justify-between gap-2" style={{ padding: "8px 10px", background: "var(--bg-elevated)", borderRadius: "6px", border: "1px solid var(--border)" }}>
                    <div className="flex flex-col" style={{ minWidth: 0, flex: 1 }}>
                      <span className="text-xs font-medium truncate" style={{ color: "var(--fg)" }}>{route.name}</span>
                      <span className="text-xs" style={{ color: "var(--muted)" }}>{route.stops.length} paradas</span>
                    </div>
                    <button
                      onClick={() => handleLoadRoute(route)}
                      disabled={loadingRouteId === route.id}
                      className="text-xs font-medium inline-flex items-center gap-1"
                      style={{
                        padding: "5px 10px",
                        borderRadius: "6px",
                        border: "1px solid var(--accent)",
                        background: "var(--accent)",
                        color: "var(--bg)",
                        cursor: loadingRouteId === route.id ? "wait" : "pointer",
                        opacity: loadingRouteId === route.id ? 0.6 : 1,
                        whiteSpace: "nowrap",
                        transition: "opacity 0.2s",
                      }}
                    >
                      {loadingRouteId === route.id ? (
                        <>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ animation: "spin 1s linear infinite" }}>
                            <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                          </svg>
                          Cargando
                        </>
                      ) : "Cargar"}
                    </button>
                    <button
                      onClick={() => setConfirmDeleteId(route.id)}
                      onMouseEnter={(e) => { e.currentTarget.style.color = "var(--error)"; e.currentTarget.style.background = "var(--error-dim)"; }}
                      onMouseLeave={(e) => { e.currentTarget.style.color = "var(--muted)"; e.currentTarget.style.background = "transparent"; }}
                      style={{ width: "28px", height: "28px", borderRadius: "6px", color: "var(--muted)", display: "inline-flex", alignItems: "center", justifyContent: "center", border: "none", cursor: "pointer", flexShrink: 0, transition: "all 0.2s" }}
                      aria-label="Eliminar ruta"
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
                    </button>
                  </div>
                  {confirmDeleteId === route.id && (
                    <div className="flex items-center gap-2" style={{ padding: "4px 10px" }}>
                      <span className="text-xs" style={{ color: "var(--fg)" }}>¿Eliminar esta ruta?</span>
                      <button
                        onClick={handleConfirmDelete}
                        className="text-xs font-medium"
                        style={{ background: "var(--error)", color: "white", padding: "4px 12px", borderRadius: "4px", border: "none", cursor: "pointer" }}
                      >
                        Sí
                      </button>
                      <button
                        onClick={() => setConfirmDeleteId(null)}
                        className="text-xs font-medium"
                        style={{ background: "var(--bg-elevated)", color: "var(--fg-secondary)", border: "1px solid var(--border)", padding: "4px 12px", borderRadius: "4px", cursor: "pointer" }}
                      >
                        No
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
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
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </main>
  );
}