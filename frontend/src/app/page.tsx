"use client";

import { useState, useRef, useCallback } from "react";
import dynamic from "next/dynamic";
import SearchBar from "./components/SearchBar";
import StatusMessage from "./components/StatusMessage";
import StopCard from "./components/StopCard";
import type { Stop, Business } from "./types";

const MapView = dynamic(() => import("./components/MapView"), { ssr: false });

type Status = "empty" | "loading" | "error" | "success";

export default function Home() {
  const [status, setStatus] = useState<Status>("empty");
  const [errorMessage, setErrorMessage] = useState<string | undefined>();
  const [stops, setStops] = useState<Stop[]>([]);
  const abortRef = useRef<AbortController | null>(null);

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

  const handleRemoveStop = useCallback((id: string) => {
    setStops(prev => {
      const next = prev.filter(s => s.id !== id);
      if (next.length === 0) setStatus("empty");
      return next;
    });
  }, []);

  const allBusinesses = stops.flatMap(s => s.businesses);
  const totalBusinesses = allBusinesses.length;

  return (
    <main className="flex flex-col min-h-dvh" style={{ padding: "24px 20px", maxWidth: "1200px", margin: "0 auto", width: "100%" }}>
      <header className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight" style={{ color: "var(--fg)" }}>Rastreador de Lojas</h1>
        <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>Agregá direcciones para escanear lojas en un radio de 500m alrededor de cada punto.</p>
      </header>
      <div className="mb-5">
        <SearchBar onSearch={handleSearch} isLoading={status === "loading"} />
      </div>
      <div className="flex flex-col lg:flex-row gap-5 flex-1">
        <div className="lg:w-2/3" style={{ minHeight: "400px", height: "100%" }}>
          <MapView stops={stops.map(s => ({ id: s.id, lat: s.lat, lon: s.lon }))} businesses={allBusinesses} />
        </div>
        <aside className="lg:w-1/3 flex flex-col gap-4">
          {stops.length > 0 && (
            <div className="flex items-center gap-4 text-xs" style={{ padding: "12px 16px", background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius)" }}>
              <span><span className="font-semibold" style={{ color: "var(--accent)" }}>{stops.length}</span><span style={{ color: "var(--muted)" }}> paradas</span></span>
              <span><span className="font-semibold" style={{ color: "#f59e0b" }}>{totalBusinesses}</span><span style={{ color: "var(--muted)" }}> lojas</span></span>
            </div>
          )}
          {stops.length === 0 && <StatusMessage type={status} message={status === "error" ? errorMessage : undefined} />}
          <div className="flex flex-col gap-3" style={{ maxHeight: "calc(100dvh - 280px)", overflowY: "auto" }}>
            {stops.map((stop, i) => (
              <StopCard key={stop.id} index={i} displayName={stop.displayName} cep={stop.cep} businesses={stop.businesses} loadingBusinesses={stop.loadingBusinesses} onRemove={() => handleRemoveStop(stop.id)} />
            ))}
          </div>
          <div className="hidden lg:block flex-1" />
          <div className="text-xs" style={{ color: "var(--muted)", lineHeight: "1.5" }}>
            <p><span style={{ color: "var(--accent)", fontWeight: 500 }}>● Verde:</span> Parada de ruta</p>
            <p><span style={{ color: "#f59e0b", fontWeight: 500 }}>● Naranja:</span> Loja cercana</p>
          </div>
        </aside>
      </div>
    </main>
  );
}
