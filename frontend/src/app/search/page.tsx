"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import SearchBar from "../components/SearchBar";

interface SearchResult {
  cnpj: string;
  nome_fantasia: string;
  cnae_label: string;
  bairro: string;
  logradouro: string;
  municipio: string;
  lat: number;
  lon: number;
}

interface CityOption {
  id: string | number;
  name: string;
}

type Status = "idle" | "loading" | "error" | "success" | "empty";

export default function SearchPage() {
  const router = useRouter();
  const [results, setResults] = useState<SearchResult[]>([]);
  const [status, setStatus] = useState<Status>("idle");
  const [errorMessage, setErrorMessage] = useState<string | undefined>();
  const [cities, setCities] = useState<CityOption[]>([]);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let isMounted = true;
    const loadCities = async () => {
      try {
        const res = await fetch("/api/cities");
        if (!res.ok) return;
        const data = await res.json();
        if (isMounted) setCities(data);
      } catch { /* silencioso */ }
    };
    loadCities();
    return () => { isMounted = false; };
  }, []);

  const handleSearch = useCallback((query: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    debounceRef.current = setTimeout(async () => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setStatus("loading");
      setErrorMessage(undefined);

      try {
        const res = await fetch(`/api/businesses/search?q=${encodeURIComponent(query)}&limit=50`, {
          signal: controller.signal,
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || "Error en la búsqueda");
        }
        const data: SearchResult[] = await res.json();
        setResults(data);
        setStatus(data.length === 0 ? "empty" : "success");
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setStatus("error");
        setErrorMessage("No se pudo conectar al servidor.");
      }
    }, 500);
  }, []);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      abortRef.current?.abort();
    };
  }, []);

  const handleResultClick = useCallback((result: SearchResult) => {
    const city = cities.find(
      c => c.name.toLowerCase() === result.municipio.toLowerCase()
    );
    if (city) {
      router.push(`/cities/${city.id}?lat=${result.lat}&lon=${result.lon}`);
    } else {
      router.push(`/?lat=${result.lat}&lon=${result.lon}&label=${encodeURIComponent(result.nome_fantasia || result.cnpj)}`);
    }
  }, [cities, router]);

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
        <h1 className="text-lg lg:text-xl font-semibold tracking-tight" style={{ color: "var(--fg)" }}>Buscar Loja</h1>
        <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>Buscá por nombre fantasia, CNPJ o calle</p>
      </header>

      <div className="mb-5">
        <SearchBar onSearch={handleSearch} isLoading={status === "loading"} />
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
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <p className="text-sm" style={{ color: "var(--muted)" }}>Sin resultados. Probá con otro término.</p>
        </div>
      )}

      {status === "success" && (
        <div className="flex flex-col gap-2">
          <p className="text-xs mb-2" style={{ color: "var(--muted)" }}>{results.length} lojas encontradas</p>
          {results.map((r) => (
            <button
              key={r.cnpj}
              onClick={() => handleResultClick(r)}
              className="flex items-start gap-3 text-left transition-all"
              style={{
                padding: "12px 14px",
                background: "var(--card)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                cursor: "pointer",
                width: "100%",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--border)"; }}
            >
              <span className="flex-shrink-0" style={{ marginTop: "2px", color: "var(--accent)" }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" /><circle cx="12" cy="10" r="3" /></svg>
              </span>
              <div className="flex-1" style={{ minWidth: 0 }}>
                <p className="text-sm font-medium" style={{ color: "var(--fg)" }}>{r.nome_fantasia || r.cnpj}</p>
                {r.cnae_label && <p className="text-xs" style={{ color: "var(--fg-secondary)" }}>{r.cnae_label}</p>}
                <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
                  {r.logradouro}{r.bairro ? `, ${r.bairro}` : ""} · {r.municipio}
                </p>
              </div>
              <span className="flex-shrink-0" style={{ color: "var(--muted)", marginTop: "2px" }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6" /></svg>
              </span>
            </button>
          ))}
        </div>
      )}
    </main>
  );
}