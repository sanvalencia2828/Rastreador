"use client";

import { useState, useRef, useCallback } from "react";
import dynamic from "next/dynamic";
import SearchBar from "./components/SearchBar";
import StatusMessage from "./components/StatusMessage";
import ResultCard from "./components/ResultCard";

const MapView = dynamic(() => import("./components/MapView"), { ssr: false });

type Status = "empty" | "loading" | "error" | "success";

interface GeoData {
  lat: number;
  lon: number;
  display_name: string;
  cep: string | null;
}

export default function Home() {
  const [status, setStatus] = useState<Status>("empty");
  const [errorMessage, setErrorMessage] = useState<string | undefined>();
  const [geoData, setGeoData] = useState<GeoData | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const handleSearch = useCallback(async (address: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setStatus("loading");
    setErrorMessage(undefined);
    setGeoData(null);

    try {
      const res = await fetch("/api/geocode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address }),
        signal: controller.signal,
      });

      const data = await res.json();

      if (!res.ok) {
        setStatus("error");
        setErrorMessage(data.error || "Error desconocido.");
        return;
      }

      setGeoData(data);
      setStatus("success");
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
      setStatus("error");
      setErrorMessage("No se pudo conectar al servidor. Verificá tu conexión.");
    }
  }, []);

  return (
    <main
      className="flex flex-col min-h-dvh"
      style={{ padding: "24px 20px", maxWidth: "1200px", margin: "0 auto", width: "100%" }}
    >
      <header className="mb-6">
        <h1
          className="text-xl font-semibold tracking-tight"
          style={{ color: "var(--fg)" }}
        >
          Geolocalizador de Lojas
        </h1>
        <p
          className="text-xs mt-1"
          style={{ color: "var(--muted)" }}
        >
          Buscá una dirección para marcar el punto y escanear lojas en un radio de 500m.
        </p>
      </header>

      <div className="mb-5">
        <SearchBar onSearch={handleSearch} isLoading={status === "loading"} />
      </div>

      <div className="flex flex-col lg:flex-row gap-5 flex-1">
        <div
          className="lg:w-2/3"
          style={{ minHeight: "400px", height: "100%" }}
        >
          <MapView lat={geoData?.lat ?? null} lon={geoData?.lon ?? null} />
        </div>

        <aside className="lg:w-1/3 flex flex-col gap-4">
          {status !== "success" && (
            <StatusMessage
              type={status}
              message={status === "error" ? errorMessage : undefined}
            />
          )}

          {status === "success" && geoData && (
            <ResultCard
              displayName={geoData.display_name}
              lat={geoData.lat}
              lon={geoData.lon}
              cep={geoData.cep}
            />
          )}

          <div className="hidden lg:block flex-1" />

          <div
            className="text-xs"
            style={{ color: "var(--muted)", lineHeight: "1.5" }}
          >
            <p>
              <span style={{ color: "var(--fg-secondary)", fontWeight: 500 }}>Fuente:</span>{" "}
              OpenStreetMap vía Nominatim
            </p>
            <p className="mt-1">
              <span style={{ color: "var(--fg-secondary)", fontWeight: 500 }}>Radio:</span>{" "}
              500m — adecuado para densidad urbana de lojas
            </p>
          </div>
        </aside>
      </div>
    </main>
  );
}
