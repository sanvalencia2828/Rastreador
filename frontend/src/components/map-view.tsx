"use client";

import React, { useState } from "react";
import Map, { Source, Layer, Marker, NavigationControl, FullscreenControl, MapRef } from "react-map-gl/maplibre";
import maplibregl from "maplibre-gl";
import { Cluster } from "./sidebar";
import { Radio, Flame, Sparkles, MapPin, Store, UtensilsCrossed, LayoutGrid, Locate } from "lucide-react";

// Register maplibre-gl globally so react-map-gl uses it
import "maplibre-gl/dist/maplibre-gl.css";

interface MapViewProps {
  heatmapData: any;
  clusters: Cluster[] | undefined;
  activeClusterId: number | null;
  setActiveClusterId: (id: number | null) => void;
  hoveredClusterId: number | null;
  setHoveredClusterId: (id: number | null) => void;
  mapRef: React.RefObject<MapRef | null>;
  showHeatmap: boolean;
  showClusters: boolean;
  selectedType: "all" | "retail" | "gastronomy";
}

// Detailed geographical meta-data about the 5 Londrina hotspots
const HUB_METADATA: Record<number, { name: string; zone: string; desc: string; densityLabel: string; typeBias: string }> = {
  1: {
    name: "Centro (Calçadão)",
    zone: "Zona Central",
    desc: "Principal eje histórico peatonal de Londrina, con un mix de tiendas masivas y comercio tradicional.",
    densityLabel: "Alta concentración de retail masivo, calzado y tiendas departamentales de gran volumen.",
    typeBias: "Comercio Minorista / Tiendas de Ropa"
  },
  2: {
    name: "Gleba Palhano (Av. Ayrton Senna)",
    zone: "Zona Sur",
    desc: "Polo de vanguardia arquitectónica con residenciales premium y oficinas ejecutivas.",
    densityLabel: "Concentración premium de cafeterías de especialidad, restaurantes gourmet y boutiques de diseño.",
    typeBias: "Gastronomía Premium & Boutiques"
  },
  3: {
    name: "Jardim Guanabara (Av. Higienópolis)",
    zone: "Zona Centro-Sur",
    desc: "Arteria comercial de gran dinamismo corporativo y polo de esparcimiento gastronómico.",
    densityLabel: "Alta concentración de restaurantes gourmet, pubs ejecutivos y servicios financieros de alto nivel.",
    typeBias: "Gastronomía Ejecutiva y Servicios"
  },
  4: {
    name: "Zona Norte (Av. Saul Elkind)",
    zone: "Zona Norte",
    desc: "El corazón comercial de la Zona Norte, caracterizado por su comercio local y conveniencia.",
    densityLabel: "Volumen comercial masivo concentrado en supermercados, tiendas de calzado popular y conveniencia.",
    typeBias: "Retail Popular y Tiendas de Conveniencia"
  },
  5: {
    name: "Zona Leste (Av. Bandeirantes)",
    zone: "Zona Este",
    desc: "Corredor estratégico interconectado con centros médicos y de salud de gran trayectoria.",
    densityLabel: "Densidad intermedia compuesta por farmacias especializadas, clínicas y ofertas gastronómicas al paso.",
    typeBias: "Salud, Estética y Alimentación de Paso"
  }
};

export default function MapView({
  heatmapData,
  clusters = [],
  activeClusterId,
  setActiveClusterId,
  hoveredClusterId,
  setHoveredClusterId,
  mapRef,
  showHeatmap,
  showClusters,
  selectedType,
}: MapViewProps) {
  const [viewState, setViewState] = useState({
    longitude: -51.1628,
    latitude: -23.3102,
    zoom: 12.0,
    pitch: 30, // Slight pitch for modern 2.5D visual depth
    bearing: 0,
  });

  // Geolocation states
  const [userLocation, setUserLocation] = useState<[number, number] | null>(null);
  const [isLocating, setIsLocating] = useState(false);
  const [locationError, setLocationError] = useState<string | null>(null);

  // Heatmap configuration layers style
  const heatmapLayer: any = {
    id: "heatmap-layer",
    type: "heatmap",
    paint: {
      "heatmap-weight": 1.0,
      "heatmap-intensity": [
        "interpolate",
        ["linear"],
        ["zoom"],
        0, 1.0,
        9, 1.5,
        15, 3.5
      ],
      "heatmap-color": [
        "interpolate",
        ["linear"],
        ["heatmap-density"],
        0, "rgba(0,0,50,0)",
        0.15, "rgba(0, 128, 255, 0.25)",
        0.35, "rgba(0, 242, 254, 0.6)",
        0.6, "rgba(0, 255, 128, 0.8)",
        0.8, "rgba(245, 166, 35, 0.9)",
        0.95, "rgba(255, 90, 54, 1)",
        1.0, "rgba(255, 235, 59, 1)"
      ],
      "heatmap-radius": [
        "interpolate",
        ["linear"],
        ["zoom"],
        0, 3,
        9, 9,
        15, 28
      ],
      "heatmap-opacity": 0.85
    }
  };

  // Find active cluster details for the overlay HUD
  const activeClusterDetails = clusters.find(c => c.cluster_id === activeClusterId);
  const activeMeta = activeClusterDetails ? HUB_METADATA[activeClusterDetails.cluster_id] : null;

  // Custom calculation for density label based on selected sector
  const getSectorDensityLabel = (lojasCount: number) => {
    if (lojasCount === 0) {
      return "Sin comercios activos detectados para este sector en esta zona.";
    }

    if (selectedType === "all") {
      return activeMeta?.densityLabel || `Zona comercial consolidada con ${lojasCount} establecimientos activos.`;
    } else if (selectedType === "retail") {
      return `Alta densidad de locales comerciales y tiendas de vestuario (${lojasCount} locales de venta al público en funcionamiento).`;
    } else {
      return `Alta concentración de establecimientos de gastronomía, bares y locales de comida (${lojasCount} puntos culinarios activos).`;
    }
  };

  // Geolocation function
  const locateUser = () => {
    if (!navigator.geolocation) {
      setLocationError("Geolocalización no soportada por este navegador");
      setTimeout(() => setLocationError(null), 3000);
      return;
    }

    setIsLocating(true);
    setLocationError(null);

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude } = position.coords;
        setUserLocation([longitude, latitude]);
        setIsLocating(false);

        // Fly to user location
        if (mapRef.current) {
          mapRef.current.flyTo({
            center: [longitude, latitude],
            zoom: 15,
            duration: 2000,
          });
        }
      },
      (error) => {
        setIsLocating(false);
        let errorMessage = "";
        switch (error.code) {
          case error.PERMISSION_DENIED:
            errorMessage = "Permiso de ubicación denegado";
            break;
          case error.POSITION_UNAVAILABLE:
            errorMessage = "Información de ubicación no disponible";
            break;
          case error.TIMEOUT:
            errorMessage = "Tiempo de espera agotado para obtener ubicación";
            break;
          default:
            errorMessage = "Error desconocido al obtener ubicación";
            break;
        }
        setLocationError(errorMessage);
        setTimeout(() => setLocationError(null), 3000);
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 300000, // 5 minutes
      }
    );
  };

  return (
    <div className="flex-1 h-screen w-full relative animate-fade-in">
      <Map
        ref={mapRef}
        {...viewState}
        onMove={(evt: any) => setViewState(evt.viewState)}
        mapLib={maplibregl}
        mapStyle="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
        style={{ width: "100%", height: "100%" }}
        maxZoom={18}
        minZoom={9}
      >
        {/* Map Control Primitives */}
        <div className="absolute right-4 top-4 z-20 flex flex-col gap-2">
          <NavigationControl position="top-right" showCompass={true} />
          <FullscreenControl position="top-right" />
        </div>

        {/* User Location Marker */}
        {userLocation && (
          <Marker
            longitude={userLocation[0]}
            latitude={userLocation[1]}
            anchor="center"
          >
            <div className="relative">
              {/* Pulsing blue circle */}
              <div className="absolute inset-0 rounded-full bg-blue-500/30 animate-ping" style={{ width: '20px', height: '20px', margin: '-10px' }}></div>
              <div className="absolute inset-0 rounded-full bg-blue-500/50" style={{ width: '16px', height: '16px', margin: '-8px' }}></div>
              {/* Center dot */}
              <div className="w-3 h-3 rounded-full bg-blue-500 border-2 border-white shadow-lg"></div>
            </div>
          </Marker>
        )}

        {/* 1. Heatmap Source and Layer */}
        {showHeatmap && heatmapData && (
          <Source type="geojson" data={heatmapData}>
            <Layer {...heatmapLayer} />
          </Source>
        )}

        {/* 2. Interactive Markers for Clusters */}
        {showClusters && clusters.map((cluster) => {
          const [lng, lat] = cluster.center_geom.coordinates;
          const isActive = activeClusterId === cluster.cluster_id;
          const isHovered = hoveredClusterId === cluster.cluster_id;

          // Skip rendering if no stores in this cluster for the current sector filter
          if (cluster.total_lojas === 0) return null;

          return (
            <Marker
              key={cluster.cluster_id}
              longitude={lng}
              latitude={lat}
              anchor="center"
              onClick={(e: any) => {
                e.originalEvent.stopPropagation();
                setActiveClusterId(cluster.cluster_id);
                if (mapRef.current) {
                  mapRef.current.flyTo({
                    center: [lng, lat],
                    zoom: 14.5,
                    duration: 1500,
                  });
                }
              }}
            >
              <div
                onMouseEnter={() => setHoveredClusterId(cluster.cluster_id)}
                onMouseLeave={() => setHoveredClusterId(null)}
                className={`relative flex items-center justify-center cursor-pointer transition-all duration-300 ${
                  isActive ? "scale-125 z-40" : isHovered ? "scale-110 z-30" : "scale-100 z-20"
                }`}
              >
                {/* Ring Outer Radar Glow */}
                <div
                  className={`absolute inset-0 rounded-full transition-all duration-500 ${
                    isActive
                      ? "w-12 h-12 -m-2.5 bg-primary/25 border-2 border-primary/50 animate-ping"
                      : isHovered
                      ? "w-10 h-10 -m-1.5 bg-primary/15 border border-primary/30"
                      : "w-8 h-8 bg-transparent"
                  }`}
                />

                {/* Blinking wave pulse */}
                <span className="absolute flex h-7 w-7">
                  <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-65 ${
                    isActive ? "bg-amber-400" : "bg-primary"
                  }`}></span>
                </span>

                {/* Cluster Circle Center */}
                <div
                  className={`w-8 h-8 rounded-full border-2 flex items-center justify-center font-black text-[10px] shadow-lg transition-all ${
                    isActive
                      ? "bg-amber-500 border-white text-black font-extrabold shadow-[0_0_15px_rgba(245,166,35,0.6)]"
                      : isHovered
                      ? "bg-primary border-white text-white shadow-[0_0_12px_rgba(255,90,54,0.5)]"
                      : "bg-zinc-900 border-primary text-primary hover:bg-primary hover:text-white"
                  }`}
                >
                  {cluster.total_lojas}
                </div>

                {/* Floating Micro-Badge for top clusters when active */}
                {isActive && (
                  <div className="absolute -top-6 bg-amber-500 border border-white text-[7px] text-black font-extrabold px-1 py-0.5 rounded shadow-md uppercase tracking-wider whitespace-nowrap">
                    Polo #{cluster.cluster_id}
                  </div>
                )}
              </div>
            </Marker>
          );
        })}
      </Map>

      {/* FLOATING OVERLAYS (HUD) */}
      
      {/* Heatmap Legend */}
      {showHeatmap && (
        <div className="absolute left-6 bottom-8 z-10 glass-panel px-4 py-3 rounded-2xl flex flex-col gap-1.5 shadow-2xl pointer-events-none select-none max-w-[200px]">
          <span className="text-[9px] uppercase font-bold text-muted-foreground tracking-wider flex items-center gap-1">
            <Flame className="w-3.5 h-3.5 text-primary animate-pulse" /> Densidad de Lojas
          </span>
          <div className="w-full h-2.5 rounded-full bg-gradient-to-r from-blue-500 via-teal-400 via-green-400 via-amber-400 to-red-500 border border-white/5" />
          <div className="flex items-center justify-between text-[8px] text-muted-foreground font-bold uppercase mt-0.5">
            <span>Bajo</span>
            <span>Avenidas Hot</span>
          </div>
        </div>
      )}

      {/* Active Cluster detail card HUD overlay (Bottom Right Floating Drawer) */}
      {activeClusterDetails && activeMeta && (
        <div className="absolute right-6 bottom-8 z-10 glass-panel p-5 rounded-2xl flex flex-col gap-3 shadow-2xl border border-slate-800/80 bg-gradient-to-b from-slate-900/95 to-slate-950/98 max-w-[320px] animate-fade-in">
          {/* Header */}
          <div className="flex items-start justify-between gap-6">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center shadow-[0_0_12px_rgba(245,166,35,0.1)]">
                <Radio className="w-4.5 h-4.5 text-amber-500 animate-pulse" />
              </div>
              <div>
                <h3 className="text-xs font-black text-white leading-none flex items-center gap-1.5">
                  Polo #{activeClusterDetails.cluster_id}
                </h3>
                <span className="text-[9px] font-bold text-amber-500 uppercase tracking-widest mt-0.5 block leading-none">
                  {activeMeta.zone}
                </span>
              </div>
            </div>
            <button
              onClick={() => setActiveClusterId(null)}
              className="text-[9px] font-bold text-muted-foreground hover:text-white transition-all bg-white/5 hover:bg-white/10 px-2 py-1 rounded-lg border border-white/5 cursor-pointer"
            >
              Cerrar
            </button>
          </div>

          <div className="h-px bg-white/5" />

          {/* Description */}
          <div className="space-y-1">
            <h4 className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider leading-none">
              Identidad de Zona
            </h4>
            <p className="text-[11px] text-zinc-300 font-semibold leading-relaxed">
              {activeMeta.name} — <span className="text-zinc-400 font-medium">{activeMeta.desc}</span>
            </p>
          </div>

          {/* Local Sector Density Calculations */}
          <div className="space-y-1 bg-black/40 border border-white/5 p-3 rounded-xl">
            <span className="text-[9px] uppercase font-extrabold text-primary tracking-widest flex items-center gap-1">
              {selectedType === "all" ? (
                <LayoutGrid className="w-3 h-3" />
              ) : selectedType === "retail" ? (
                <Store className="w-3 h-3" />
              ) : (
                <UtensilsCrossed className="w-3 h-3" />
              )}
              Estimación de Densidad ({selectedType === "all" ? "Total" : selectedType === "retail" ? "Retail" : "Gastronomía"})
            </span>
            <p className="text-[10px] text-zinc-300 font-medium leading-normal mt-1">
              {getSectorDensityLabel(activeClusterDetails.total_lojas)}
            </p>
          </div>

          {/* Coordinates and Numeric KPIs */}
          <div className="grid grid-cols-2 gap-3 text-[10px] mt-1">
            <div>
              <span className="text-muted-foreground font-medium text-[9px] block uppercase tracking-wider">Total Lojas</span>
              <span className="text-white font-extrabold text-xs mt-0.5 block">
                {activeClusterDetails.total_lojas} tiendas
              </span>
            </div>
            <div>
              <span className="text-muted-foreground font-medium text-[9px] block uppercase tracking-wider">Centroide GIS</span>
              <span className="text-[10px] text-zinc-300 font-mono font-bold mt-1 flex items-center gap-0.5 leading-none">
                <MapPin className="w-3 h-3 text-muted-foreground/60" />
                {activeClusterDetails.center_geom.coordinates[0].toFixed(4)}, {activeClusterDetails.center_geom.coordinates[1].toFixed(4)}
              </span>
            </div>
          </div>

          <div className="h-px bg-white/5" />

          {/* Action Button to zoom directly to this active cluster center */}
          <button
            onClick={() => {
              const [lng, lat] = activeClusterDetails.center_geom.coordinates;
              if (mapRef.current) {
                mapRef.current.flyTo({
                  center: [lng, lat],
                  zoom: 16.0,
                  duration: 1800,
                  essential: true
                });
              }
            }}
            className="w-full mt-1 py-2.5 px-4 rounded-xl bg-primary hover:bg-primary/95 text-white font-extrabold text-xs shadow-lg shadow-primary/20 hover:shadow-primary/30 transition-all hover:scale-[1.02] flex items-center justify-center gap-1.5 cursor-pointer"
          >
            <Sparkles className="w-3.5 h-3.5 text-white animate-pulse" />
            Hacer zoom a este polo
          </button>
        </div>
      )}

      {/* Geolocation Button */}
      <button
        onClick={locateUser}
        disabled={isLocating}
        className="absolute left-4 top-4 z-20 w-12 h-12 rounded-full bg-white/10 backdrop-blur-sm border border-white/20 flex items-center justify-center text-white hover:bg-white/20 transition-all duration-300 shadow-lg hover:shadow-xl disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {isLocating ? (
          <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
        ) : (
          <Locate className="w-5 h-5" />
        )}
      </button>

      {/* Location Error Message */}
      {locationError && (
        <div className="absolute left-1/2 top-4 z-20 transform -translate-x-1/2 bg-red-500/90 backdrop-blur-sm text-white text-xs font-bold px-4 py-2 rounded-lg shadow-lg animate-fade-in">
          {locationError}
        </div>
      )}
    </div>
  );
}
