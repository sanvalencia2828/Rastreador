"use client";

import React, { useState, useMemo } from "react";
import { 
  Radar, 
  TrendingUp, 
  MapPin, 
  Layers, 
  Eye, 
  EyeOff, 
  Search, 
  Store, 
  Sparkles, 
  HelpCircle,
  UtensilsCrossed,
  LayoutGrid
} from "lucide-react";

export interface ClusterPoint {
  type: "Point";
  coordinates: [number, number]; // [lng, lat]
}

export interface Cluster {
  cluster_id: number;
  total_lojas: number;
  center_geom: ClusterPoint;
}

interface SidebarProps {
  clusters: Cluster[] | undefined;
  isLoading: boolean;
  error: any;
  activeClusterId: number | null;
  setActiveClusterId: (id: number | null) => void;
  hoveredClusterId: number | null;
  setHoveredClusterId: (id: number | null) => void;
  onFlyTo: (lng: number, lat: number, zoom?: number) => void;
  showHeatmap: boolean;
  setShowHeatmap: (show: boolean) => void;
  showClusters: boolean;
  setShowClusters: (show: boolean) => void;
  selectedType: "all" | "retail" | "gastronomy";
  setSelectedType: (type: "all" | "retail" | "gastronomy") => void;
}

export default function Sidebar({
  clusters = [],
  isLoading,
  error,
  activeClusterId,
  setActiveClusterId,
  hoveredClusterId,
  setHoveredClusterId,
  onFlyTo,
  showHeatmap,
  setShowHeatmap,
  showClusters,
  setShowClusters,
  selectedType,
  setSelectedType,
}: SidebarProps) {
  const [searchTerm, setSearchTerm] = useState("");

  // Statistics calculations based on currently filtered/passed clusters
  const stats = useMemo(() => {
    if (!clusters || clusters.length === 0) {
      return { totalLojas: 0, topClusterId: "N/A", avgLojas: 0 };
    }
    const total = clusters.reduce((acc, c) => acc + c.total_lojas, 0);
    const sorted = [...clusters].sort((a, b) => b.total_lojas - a.total_lojas);
    const topId = sorted[0]?.cluster_id ?? "N/A";
    const avg = Math.round(total / clusters.length);
    return {
      totalLojas: total,
      topClusterId: `#${topId}`,
      avgLojas: avg,
    };
  }, [clusters]);

  // Filtered clusters based on search query
  const filteredClusters = useMemo(() => {
    if (!clusters) return [];
    return clusters.filter(
      (c) =>
        c.cluster_id.toString().includes(searchTerm) ||
        `polo ${c.cluster_id}`.toLowerCase().includes(searchTerm.toLowerCase())
    );
  }, [clusters, searchTerm]);

  // Format decimal numbers for coordinates
  const formatCoord = (val: number) => val.toFixed(4);

  return (
    <aside className="w-[350px] min-w-[350px] h-screen glass-panel flex flex-col z-10 shadow-2xl relative select-none">
      {/* Visual Scanning Effect */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden opacity-10">
        <div className="w-full h-1/2 scan-line" />
      </div>

      {/* Header Panel */}
      <div className="p-6 border-b border-border flex items-center justify-between relative">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-primary/20 flex items-center justify-center border border-primary/30 relative overflow-hidden">
            <Radar className="w-5 h-5 text-primary radar-glow" />
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tight text-white leading-none">
              Londrina
            </h1>
            <span className="text-[11px] font-semibold text-primary uppercase tracking-widest">
              Radar Comercial
            </span>
          </div>
        </div>
        <div className="flex items-center">
          <span className="flex h-2 w-2 relative">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
          <span className="text-[10px] text-muted-foreground ml-2 font-medium">LIVE</span>
        </div>
      </div>

      {/* Main Container - Scrollable Panel */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
        {/* Layer Controls Dashboard */}
        <div className="space-y-2">
          <h2 className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider flex items-center gap-1.5">
            <Layers className="w-3 h-3 text-primary/70" /> Capas de Visualización
          </h2>
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() => setShowHeatmap(!showHeatmap)}
              className={`p-3 rounded-xl border flex flex-col items-center justify-center gap-1.5 transition-all text-xs font-semibold cursor-pointer ${
                showHeatmap
                  ? "bg-primary/10 border-primary/45 text-white shadow-[0_0_12px_-3px_rgba(255,90,54,0.3)]"
                  : "bg-white/5 border-white/5 text-muted-foreground hover:bg-white/10"
              }`}
            >
              {showHeatmap ? (
                <Eye className="w-4 h-4 text-primary" />
              ) : (
                <EyeOff className="w-4 h-4" />
              )}
              <span>Mapa Térmico</span>
            </button>
            <button
              onClick={() => setShowClusters(!showClusters)}
              className={`p-3 rounded-xl border flex flex-col items-center justify-center gap-1.5 transition-all text-xs font-semibold cursor-pointer ${
                showClusters
                  ? "bg-primary/10 border-primary/45 text-white shadow-[0_0_12px_-3px_rgba(255,90,54,0.3)]"
                  : "bg-white/5 border-white/5 text-muted-foreground hover:bg-white/10"
              }`}
            >
              {showClusters ? (
                <Eye className="w-4 h-4 text-primary" />
              ) : (
                <EyeOff className="w-4 h-4" />
              )}
              <span>Polos Clúster</span>
            </button>
          </div>
        </div>

        {/* Sectores Interactivos (Glassmorphism Tab Selector) */}
        <div className="space-y-2">
          <h2 className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider flex items-center gap-1.5">
            <Store className="w-3.5 h-3.5 text-primary/70" /> Filtrar por Sector
          </h2>
          <div className="grid grid-cols-3 gap-1 p-1 bg-zinc-950/60 border border-slate-800/80 rounded-xl relative">
            <button
              onClick={() => setSelectedType("all")}
              className={`py-2 px-1 rounded-lg text-[9px] font-black tracking-wide uppercase transition-all duration-300 cursor-pointer flex flex-col items-center justify-center gap-1 ${
                selectedType === "all"
                  ? "bg-primary text-white shadow-[0_0_12px_rgba(255,90,54,0.35)]"
                  : "text-muted-foreground hover:text-white hover:bg-white/5"
              }`}
            >
              <LayoutGrid className="w-3.5 h-3.5" />
              <span>Todos</span>
            </button>
            <button
              onClick={() => setSelectedType("retail")}
              className={`py-2 px-1 rounded-lg text-[9px] font-black tracking-wide uppercase transition-all duration-300 cursor-pointer flex flex-col items-center justify-center gap-1 ${
                selectedType === "retail"
                  ? "bg-primary text-white shadow-[0_0_12px_rgba(255,90,54,0.35)]"
                  : "text-muted-foreground hover:text-white hover:bg-white/5"
              }`}
            >
              <Store className="w-3.5 h-3.5" />
              <span>Retail</span>
            </button>
            <button
              onClick={() => setSelectedType("gastronomy")}
              className={`py-2 px-1 rounded-lg text-[9px] font-black tracking-wide uppercase transition-all duration-300 cursor-pointer flex flex-col items-center justify-center gap-1 ${
                selectedType === "gastronomy"
                  ? "bg-primary text-white shadow-[0_0_12px_rgba(255,90,54,0.35)]"
                  : "text-muted-foreground hover:text-white hover:bg-white/5"
              }`}
            >
              <UtensilsCrossed className="w-3.5 h-3.5" />
              <span>Gastronomía</span>
            </button>
          </div>
        </div>

        {/* Analytic Card: "Top Polos Emergentes" */}
        <div className="glass-card rounded-2xl p-4 relative overflow-hidden group border border-slate-800/80 bg-gradient-to-b from-slate-900 to-slate-950 transition-all duration-300 hover:scale-[1.02] animate-fade-in shadow-xl">
          {/* Accent Glow border */}
          <div className="absolute top-0 right-0 w-24 h-24 bg-primary/10 rounded-full filter blur-xl group-hover:bg-primary/20 transition-all duration-500" />
          <div className="flex items-start justify-between">
            <div className="space-y-1">
              <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest flex items-center gap-1">
                <Sparkles className="w-3 h-3 text-amber-500 animate-pulse" /> Top Polo Emergente
              </span>
              <p className="text-2xl font-black text-white tracking-tight">{stats.topClusterId}</p>
            </div>
            <div className="p-2 bg-amber-500/10 rounded-lg border border-amber-500/20 text-amber-400">
              <TrendingUp className="w-4 h-4" />
            </div>
          </div>
          
          <div className="grid grid-cols-2 gap-4 mt-4 pt-3 border-t border-white/5">
            <div>
              <span className="text-[10px] text-muted-foreground block font-medium">Lojas Totales</span>
              <span className="text-sm font-bold text-white flex items-center gap-1">
                <Store className="w-3.5 h-3.5 text-primary" />
                {isLoading ? "..." : stats.totalLojas}
              </span>
            </div>
            <div>
              <span className="text-[10px] text-muted-foreground block font-medium">Promedio/Polo</span>
              <span className="text-sm font-bold text-white">
                {isLoading ? "..." : `${stats.avgLojas} lojas`}
              </span>
            </div>
          </div>
        </div>

        {/* Interactive Search Field */}
        <div className="relative">
          <Search className="w-4 h-4 text-muted-foreground absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Filtrar por ID de Polo..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded-xl py-2.5 pl-10 pr-4 text-xs text-white placeholder-muted-foreground focus:outline-none focus:border-primary/50 focus:bg-white/10 transition-all font-semibold"
          />
        </div>

        {/* Ranking List Section */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">
              Ranking de Polos Emergentes
            </h2>
            <span className="text-[10px] bg-white/5 border border-white/10 text-muted-foreground px-2 py-0.5 rounded-full font-bold">
              {filteredClusters.length} Polos
            </span>
          </div>

          <div className="space-y-2">
            {isLoading ? (
              // Beautiful Skeleton Loaders
              Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  className="glass-card rounded-xl p-3 border-white/5 border flex items-center gap-3 animate-pulse"
                >
                  <div className="w-8 h-8 rounded-lg bg-white/10 flex-shrink-0" />
                  <div className="flex-1 space-y-1.5">
                    <div className="h-3 bg-white/10 rounded w-1/3" />
                    <div className="h-2.5 bg-white/5 rounded w-2/3" />
                  </div>
                </div>
              ))
            ) : error ? (
              <div className="text-center py-6 border border-destructive/20 bg-destructive/5 rounded-2xl p-4">
                <p className="text-xs font-semibold text-destructive">Error al conectar con la API</p>
                <p className="text-[10px] text-muted-foreground mt-1">Verifica si el backend API está corriendo correctamente.</p>
              </div>
            ) : filteredClusters.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground text-xs font-medium border border-white/5 bg-white/2 rounded-xl p-4">
                No se encontraron polos con tiendas activas para este sector.
              </div>
            ) : (
              filteredClusters.map((cluster, index) => {
                const isTop3 = index < 3;
                const isActive = activeClusterId === cluster.cluster_id;
                const isHovered = hoveredClusterId === cluster.cluster_id;
                const [lng, lat] = cluster.center_geom.coordinates;

                return (
                  <div
                    key={cluster.cluster_id}
                    onClick={() => {
                      setActiveClusterId(cluster.cluster_id);
                      onFlyTo(lng, lat, 14.5);
                    }}
                    onMouseEnter={() => setHoveredClusterId(cluster.cluster_id)}
                    onMouseLeave={() => setHoveredClusterId(null)}
                    className={`glass-card rounded-xl p-3 border cursor-pointer flex items-center justify-between gap-3 transition-all duration-300 hover:scale-[1.02] animate-fade-in border-slate-800/80 bg-gradient-to-b from-slate-900 to-slate-950 ${
                      isActive
                        ? "glass-card-active border-primary/50"
                        : isHovered
                        ? "border-primary/30 bg-white/5"
                        : ""
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      {/* Position Badge */}
                      <div
                        className={`w-8 h-8 rounded-lg flex items-center justify-center font-black text-xs transition-all duration-300 ${
                          index === 0
                            ? "bg-amber-500/20 text-amber-400 border border-amber-500/30 shadow-[0_0_10px_rgba(245,166,35,0.15)]"
                            : index === 1
                            ? "bg-slate-300/20 text-slate-200 border border-slate-300/30"
                            : index === 2
                            ? "bg-orange-500/20 text-orange-400 border border-orange-500/30"
                            : "bg-white/5 text-muted-foreground border border-white/5"
                        }`}
                      >
                        {index + 1}
                      </div>

                      {/* Polo Metadata */}
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-black text-white leading-none">
                            Polo #{cluster.cluster_id}
                          </span>
                          {isTop3 && (
                            <span className="text-[8px] bg-primary/10 text-primary font-bold px-1.5 py-0.5 rounded-full uppercase leading-none">
                              Premium
                            </span>
                          )}
                        </div>
                        <span className="text-[10px] text-muted-foreground flex items-center gap-1 mt-1 leading-none font-semibold font-mono">
                          <MapPin className="w-2.5 h-2.5 text-muted-foreground/80" />
                          {formatCoord(lng)}, {formatCoord(lat)}
                        </span>
                      </div>
                    </div>

                    {/* Store Counter */}
                    <div className="text-right">
                      <span className="text-xs font-black text-white block">
                        {cluster.total_lojas}
                      </span>
                      <span className="text-[8px] text-muted-foreground font-bold uppercase block leading-none mt-0.5">
                        Lojas
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* Footer Info Panel */}
      <div className="p-4 border-t border-border bg-black/20 flex items-center justify-between text-[10px] text-muted-foreground font-semibold">
        <span className="flex items-center gap-1">
          <HelpCircle className="w-3.5 h-3.5 text-muted-foreground/60" /> Londrina PR | GIS
        </span>
        <span className="text-white/40">v1.0 (Open-Source)</span>
      </div>
    </aside>
  );
}
