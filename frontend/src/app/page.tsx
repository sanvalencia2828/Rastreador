"use client";

import React, { useState, useRef, useMemo } from "react";
import useSWR from "swr";
import { MapRef } from "react-map-gl/maplibre";
import Sidebar, { Cluster } from "@/components/sidebar";
import MapView from "@/components/map-view";
import { AlertCircle, Terminal, HelpCircle } from "lucide-react";

// API base URL from environment variable (set in .env or Docker)
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

// Generic JSON fetcher utility for SWR
const fetcher = async (url: string) => {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch: ${res.statusText}`);
  }
  return res.json();
};

export default function DashboardPage() {
  // Shared interactive states
  const [activeClusterId, setActiveClusterId] = useState<number | null>(null);
  const [hoveredClusterId, setHoveredClusterId] = useState<number | null>(null);
  
  // Layer toggle states
  const [showHeatmap, setShowHeatmap] = useState(true);
  const [showClusters, setShowClusters] = useState(true);

  // Sector filter state ("all" | "retail" | "gastronomy")
  const [selectedType, setSelectedType] = useState<"all" | "retail" | "gastronomy">("all");

  // Reference for smooth fly-to camera controls on MapLibre canvas
  const mapRef = useRef<MapRef | null>(null);

  // Fetch Heatmap GeoJSON points from the local API
  const {
    data: heatmapData,
    error: heatmapError,
    isLoading: heatmapLoading,
  } = useSWR(`${API_BASE_URL}/api/heatmap`, fetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: true,
    errorRetryInterval: 5000, // Retry every 5 seconds if local API is not up yet
  });

  // Fetch Clusters JSON ranking list from the local API
  const {
    data: clustersData,
    error: clustersError,
    isLoading: clustersLoading,
  } = useSWR<Cluster[]>(`${API_BASE_URL}/api/clusters/emergentes`, fetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: true,
    errorRetryInterval: 5000,
  });

  // Camera animation handler
  const handleFlyTo = (lng: number, lat: number, zoom = 14.5) => {
    if (mapRef.current) {
      mapRef.current.flyTo({
        center: [lng, lat],
        zoom,
        duration: 2000,
        essential: true,
      });
    }
  };

  // Helper to find nearest hub coordinates for client-side local filtering
  const HUBS = useMemo(() => [
    { id: 1, coords: [-51.1610, -23.3110] },
    { id: 2, coords: [-51.1890, -23.3310] },
    { id: 3, coords: [-51.1670, -23.3220] },
    { id: 4, coords: [-51.1480, -23.2720] },
    { id: 5, coords: [-51.1550, -23.3180] }
  ], []);

  const getNearestHub = (lng: number, lat: number) => {
    let minDistance = Infinity;
    let nearestHubId = 1;
    for (const hub of HUBS) {
      const dx = lng - hub.coords[0];
      const dy = lat - hub.coords[1];
      const dist = dx * dx + dy * dy;
      if (dist < minDistance) {
        minDistance = dist;
        nearestHubId = hub.id;
      }
    }
    return nearestHubId;
  };

  // 1. Local filtering of Heatmap Data based on selectedType
  const filteredHeatmapData = useMemo(() => {
    if (!heatmapData) return null;
    if (selectedType === "all") return heatmapData;
    return {
      ...heatmapData,
      features: heatmapData.features.filter(
        (f: any) => f.properties?.business_type === selectedType
      ),
    };
  }, [heatmapData, selectedType]);

  // 2. Recalculate cluster totals dynamically based on selected sector!
  const filteredClusters = useMemo(() => {
    if (!clustersData) return [];
    if (selectedType === "all") return clustersData;

    // Initialize counts for hubs
    const counts: Record<number, number> = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };

    if (heatmapData && heatmapData.features) {
      const sectorFeatures = heatmapData.features.filter(
        (f: any) => f.properties?.business_type === selectedType
      );
      for (const f of sectorFeatures) {
        if (f.geometry && f.geometry.coordinates) {
          const [lng, lat] = f.geometry.coordinates;
          const hubId = getNearestHub(lng, lat);
          counts[hubId] = (counts[hubId] || 0) + 1;
        }
      }
    }

    return clustersData
      .map((c) => ({
        ...c,
        total_lojas: counts[c.cluster_id] || 0,
      }))
      .sort((a, b) => b.total_lojas - a.total_lojas);
  }, [clustersData, heatmapData, selectedType]);

  const hasErrors = heatmapError || clustersError;
  const isLoading = heatmapLoading || clustersLoading;

  return (
    <main className="w-screen h-screen flex bg-zinc-950 overflow-hidden text-white relative font-sans">
      {/* 1. Left Sidebar - Dynamic Rankings & Metrics */}
      <Sidebar
        clusters={filteredClusters}
        isLoading={isLoading}
        error={hasErrors}
        activeClusterId={activeClusterId}
        setActiveClusterId={setActiveClusterId}
        hoveredClusterId={hoveredClusterId}
        setHoveredClusterId={setHoveredClusterId}
        onFlyTo={handleFlyTo}
        showHeatmap={showHeatmap}
        setShowHeatmap={setShowHeatmap}
        showClusters={showClusters}
        setShowClusters={setShowClusters}
        selectedType={selectedType}
        setSelectedType={setSelectedType}
      />

      {/* 2. Right Pane - Interactive MapLibre GL Canvas */}
      <MapView
        heatmapData={filteredHeatmapData}
        clusters={filteredClusters}
        activeClusterId={activeClusterId}
        setActiveClusterId={setActiveClusterId}
        hoveredClusterId={hoveredClusterId}
        setHoveredClusterId={setHoveredClusterId}
        mapRef={mapRef}
        showHeatmap={showHeatmap}
        showClusters={showClusters}
        selectedType={selectedType}
      />

      {/* 3. Helpful Offline Overlay Banner in case the Local API has not started */}
      {hasErrors && (
        <div className="absolute top-4 right-4 z-50 max-w-sm glass-panel p-4 rounded-2xl border-destructive/30 shadow-2xl flex gap-3 animate-fade-in">
          <div className="w-8 h-8 rounded-lg bg-destructive/10 border border-destructive/20 flex-shrink-0 flex items-center justify-center text-destructive">
            <AlertCircle className="w-5 h-5" />
          </div>
          <div className="space-y-1">
            <h4 className="text-xs font-black text-white leading-tight">
              API Fuera de Línea
            </h4>
            <p className="text-[10px] text-muted-foreground leading-normal">
              No pudimos conectar con <code className="text-primary font-mono font-bold">{API_BASE_URL}</code>. El panel reintentará automáticamente cada 5 segundos.
            </p>
            <div className="pt-2 flex flex-col gap-1">
              <span className="text-[9px] text-zinc-400 font-bold uppercase flex items-center gap-1">
                <Terminal className="w-3 h-3 text-primary" /> Comando para levantar API:
              </span>
              <pre className="text-[9px] bg-black/40 border border-white/5 p-1.5 rounded font-mono text-zinc-300 overflow-x-auto">
                uvicorn main:app --reload
              </pre>
            </div>
            <div className="pt-1.5 text-[9px] text-muted-foreground flex items-center gap-1 font-semibold">
              <HelpCircle className="w-3 h-3" />
              Tip: Verifica CORS en tu backend de Python.
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
