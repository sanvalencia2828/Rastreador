"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  Cpu,
  Search,
  X,
  ChevronDown,
  MapPin,
  Building2,
  RefreshCw,
  AlertCircle,
  Package,
} from "lucide-react";

interface TechBusiness {
  cnpj: string;
  nome_fantasia: string;
  cnae: string;
  cnae_label: string;
  cnae_icon: string;
  bairro: string;
  logradouro: string;
  municipio: string;
  business_type: string;
}

interface TechBusinessesResponse {
  total: number;
  offset: number;
  limit: number;
  items: TechBusiness[];
}

interface TechBusinessPanelProps {
  apiBaseUrl: string;
}

const PAGE_SIZE = 30;

// Badge color map by subcategory label
const BADGE_COLOR: Record<string, string> = {
  "Software & TI":          "bg-violet-500/15 text-violet-300 border-violet-500/25",
  "Data & Servicios Web":   "bg-cyan-500/15 text-cyan-300 border-cyan-500/25",
  "Electrónica":            "bg-blue-500/15 text-blue-300 border-blue-500/25",
  "Electrodomésticos":      "bg-yellow-500/15 text-yellow-300 border-yellow-500/25",
  "Telecomunicaciones":     "bg-emerald-500/15 text-emerald-300 border-emerald-500/25",
  "Reparación TI":          "bg-orange-500/15 text-orange-300 border-orange-500/25",
  "Comercio Mayorista TI":  "bg-slate-500/15 text-slate-300 border-slate-500/25",
  "Retail de Tecnología":   "bg-pink-500/15 text-pink-300 border-pink-500/25",
  "Consultoría TI":         "bg-indigo-500/15 text-indigo-300 border-indigo-500/25",
  "Ingeniería & P&D":       "bg-teal-500/15 text-teal-300 border-teal-500/25",
  "Investigación":          "bg-purple-500/15 text-purple-300 border-purple-500/25",
  "Educación TI":           "bg-lime-500/15 text-lime-300 border-lime-500/25",
};

function SkeletonCard() {
  return (
    <div className="rounded-xl border border-white/5 bg-gradient-to-b from-slate-900 to-slate-950 p-3 flex items-center gap-3 animate-pulse">
      <div className="w-9 h-9 rounded-lg bg-white/10 flex-shrink-0" />
      <div className="flex-1 space-y-1.5">
        <div className="h-3 bg-white/10 rounded w-2/3" />
        <div className="h-2.5 bg-white/5 rounded w-1/2" />
        <div className="h-2 bg-white/5 rounded w-1/3" />
      </div>
    </div>
  );
}

export default function TechBusinessPanel({ apiBaseUrl }: TechBusinessPanelProps) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [data, setData] = useState<TechBusinessesResponse | null>(null);
  const [allItems, setAllItems] = useState<TechBusiness[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const listRef = useRef<HTMLDivElement>(null);

  // Debounce search query
  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedQuery(query);
      setOffset(0);
      setAllItems([]);
      setHasMore(true);
    }, 350);
    return () => clearTimeout(t);
  }, [query]);

  // Fetch page of tech businesses
  const fetchPage = useCallback(
    async (currentOffset: number, reset = false) => {
      if (reset) {
        setLoading(true);
      } else {
        setLoadingMore(true);
      }
      setError(null);

      try {
        const params = new URLSearchParams({
          limit: String(PAGE_SIZE),
          offset: String(currentOffset),
          ...(debouncedQuery ? { search: debouncedQuery } : {}),
        });
        const res = await fetch(`${apiBaseUrl}/api/businesses/tech?${params}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json: TechBusinessesResponse = await res.json();

        setData(json);
        setAllItems((prev) => (reset || currentOffset === 0 ? json.items : [...prev, ...json.items]));
        setHasMore(currentOffset + json.items.length < json.total);
      } catch (e: any) {
        setError("No se pudo conectar con la API.");
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [apiBaseUrl, debouncedQuery]
  );

  // Initial load / when search changes
  useEffect(() => {
    fetchPage(0, true);
  }, [fetchPage]);

  // Load more
  const loadMore = () => {
    if (loadingMore || !hasMore) return;
    const nextOffset = offset + PAGE_SIZE;
    setOffset(nextOffset);
    fetchPage(nextOffset);
  };

  const clearSearch = () => {
    setQuery("");
  };

  return (
    <div className="space-y-3 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider flex items-center gap-1.5">
          <Cpu className="w-3.5 h-3.5 text-violet-400" />
          Empresas de Tecnología
        </h2>
        {data && (
          <span className="text-[10px] bg-violet-500/10 border border-violet-500/20 text-violet-300 px-2 py-0.5 rounded-full font-bold">
            {data.total} empresas
          </span>
        )}
      </div>

      {/* Search bar */}
      <div className="relative">
        <Search className="w-3.5 h-3.5 text-muted-foreground absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          id="tech-business-search"
          type="text"
          placeholder="Buscar por nombre, CNAE, barrio..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full bg-white/5 border border-white/10 rounded-xl py-2 pl-9 pr-8 text-[11px] text-white placeholder-muted-foreground focus:outline-none focus:border-violet-500/50 focus:bg-white/10 transition-all font-medium"
        />
        {query && (
          <button
            onClick={clearSearch}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-white transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* List */}
      <div ref={listRef} className="space-y-1.5 max-h-[340px] overflow-y-auto pr-0.5 scrollbar-thin">
        {loading ? (
          Array.from({ length: 5 }).map((_, i) => <SkeletonCard key={i} />)
        ) : error ? (
          <div className="rounded-xl border border-destructive/20 bg-destructive/5 p-4 flex items-start gap-3">
            <AlertCircle className="w-4 h-4 text-destructive flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-xs font-semibold text-destructive">{error}</p>
              <button
                onClick={() => fetchPage(0, true)}
                className="mt-1.5 text-[10px] text-muted-foreground hover:text-white flex items-center gap-1 transition-colors"
              >
                <RefreshCw className="w-3 h-3" /> Reintentar
              </button>
            </div>
          </div>
        ) : allItems.length === 0 ? (
          <div className="rounded-xl border border-white/5 bg-white/[0.02] p-5 text-center">
            <Package className="w-6 h-6 text-muted-foreground/40 mx-auto mb-2" />
            <p className="text-[11px] text-muted-foreground font-medium">
              {debouncedQuery
                ? `Sin resultados para "${debouncedQuery}"`
                : "No hay empresas tech en el dataset actual."}
            </p>
          </div>
        ) : (
          <>
            {allItems.map((biz, i) => {
              const badgeClass =
                BADGE_COLOR[biz.cnae_label] ||
                "bg-violet-500/10 text-violet-300 border-violet-500/20";

              return (
                <div
                  key={`${biz.cnpj}-${i}`}
                  className="group rounded-xl border border-slate-800/80 bg-gradient-to-b from-slate-900 to-slate-950 p-3 flex items-start gap-3 hover:border-violet-500/30 hover:bg-white/5 transition-all duration-200 cursor-default animate-fade-in"
                >
                  {/* Icon badge */}
                  <div className="w-9 h-9 rounded-lg bg-violet-500/10 border border-violet-500/20 flex items-center justify-center text-base flex-shrink-0 group-hover:bg-violet-500/20 transition-all">
                    {biz.cnae_icon}
                  </div>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <p className="text-[11px] font-black text-white leading-snug truncate">
                      {biz.nome_fantasia}
                    </p>

                    {/* Subcategory badge */}
                    <span
                      className={`inline-flex items-center text-[9px] font-bold px-1.5 py-0.5 rounded-full border mt-1 leading-none ${badgeClass}`}
                    >
                      {biz.cnae_label}
                    </span>

                    {/* Location */}
                    <p className="text-[9px] text-muted-foreground flex items-center gap-1 mt-1.5 leading-none font-mono truncate">
                      <MapPin className="w-2.5 h-2.5 flex-shrink-0 text-muted-foreground/60" />
                      {biz.bairro
                        ? `${biz.bairro}, ${biz.municipio}`
                        : biz.municipio}
                    </p>

                    {/* CNAE code */}
                    {biz.cnae && (
                      <p className="text-[9px] text-muted-foreground/50 font-mono mt-0.5">
                        CNAE {biz.cnae}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}

            {/* Load more button */}
            {hasMore && (
              <button
                onClick={loadMore}
                disabled={loadingMore}
                className="w-full py-2.5 rounded-xl border border-violet-500/20 bg-violet-500/5 text-violet-300 text-[10px] font-bold uppercase tracking-wider hover:bg-violet-500/15 transition-all flex items-center justify-center gap-2 disabled:opacity-50 cursor-pointer"
              >
                {loadingMore ? (
                  <>
                    <RefreshCw className="w-3 h-3 animate-spin" />
                    Cargando...
                  </>
                ) : (
                  <>
                    <ChevronDown className="w-3.5 h-3.5" />
                    Ver más ({data ? data.total - allItems.length : ""} restantes)
                  </>
                )}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
