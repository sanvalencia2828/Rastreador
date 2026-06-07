// frontend/src/components/map-view.tsx
"use client";

import React, { useState, useEffect, useRef } from "react";
import Map, { Source, Layer, Marker, NavigationControl, FullscreenControl, MapRef } from "react-map-gl/maplibre";
import maplibregl from "maplibre-gl";
import { Cluster } from "./sidebar";
import { 
  Radio, Flame, Sparkles, MapPin, Store, UtensilsCrossed, LayoutGrid, Locate,
  Wifi, WifiOff, RefreshCw, Route, CheckSquare, Plus, Trash2, CheckCircle2, UserCheck, MessageSquare, AlertCircle
} from "lucide-react";
import { Map as MapIcon } from "lucide-react";
import { 
  cacheSegments, getCachedSegments, savePendingVisit, getPendingVisits, 
  clearPendingVisits, OfflineVisit 
} from "../utils/indexedDB";
import VisitModal from "./visit-modal";

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
  selectedType: "all" | "software" | "support" | "repairs";
}

const HUB_METADATA: Record<number, { name: string; zone: string; desc: string; densityLabel: string; typeBias: string }> = {
  1: {
    name: "Centro (Peatonal)",
    zone: "Zona Central",
    desc: "Eje peatonal central con alta densidad de talleres de servicio técnico de hardware y soporte express.",
    densityLabel: "Gran volumen de tiendas de reparación y venta de accesorios para móviles y periféricos.",
    typeBias: "Soporte TI & Reparación Express"
  },
  2: {
    name: "Gleba Palhano (Av. Ayrton Senna)",
    zone: "Zona Sur",
    desc: "Polo corporativo de startups, consultoras de desarrollo de software y servicios TI empresariales.",
    densityLabel: "Alta presencia de empresas de ingeniería de software corporativo y consultorías en la nube.",
    typeBias: "Desarrollo de Software / SaaS"
  },
  3: {
    name: "Jardim Guanabara (Av. Higienópolis)",
    zone: "Zona Centro-Sur",
    desc: "Polo mixto con consultoras de software, integradores de redes y soporte corporativo de sistemas.",
    densityLabel: "Despachos de ingeniería de sistemas, redes inalámbricas y soporte corporativo.",
    typeBias: "Consultoría TI & Redes"
  },
  4: {
    name: "Zona Norte (Av. Saul Elkind)",
    zone: "Zona Norte",
    desc: "Área comercial con alta densidad de servicios técnicos de reparación de computadores y electrodomésticos.",
    densityLabel: "Alta concentración de talleres locales de reparación de computadoras y servicio autorizado multimarca.",
    typeBias: "Asistencia de Hardware y Computadores"
  },
  5: {
    name: "Zona Leste (Av. Bandeirantes)",
    zone: "Zona Este",
    desc: "Polo comercial enfocado en asistencia técnica de equipos de comunicación, telefonía y automatización.",
    densityLabel: "Servicio técnico oficial de redes, telefonía y automatización comercial.",
    typeBias: "Reparación de Comunicaciones"
  }
};

const getApiUrl = (): string => {
  const defaultUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  if (typeof window !== "undefined") {
    const hostname = window.location.hostname;
    try {
      const url = new URL(defaultUrl);
      if (url.hostname === "localhost" || url.hostname === "127.0.0.1") {
        url.hostname = hostname;
      }
      return url.toString().replace(/\/$/, "");
    } catch (e) {
      return defaultUrl;
    }
  }
  return defaultUrl;
};

const NEXT_PUBLIC_API_URL = getApiUrl();

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
  const MAP_STYLES = {
    dark: {
      name: "Modo Oscuro",
      url: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
    },
    light: {
      name: "Modo Claro",
      url: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    },
    voyager: {
      name: "Navegación",
      url: "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
    }
  };

  const [mapStyleKey, setMapStyleKey] = useState<"dark" | "light" | "voyager">("dark");
  const [showStyleMenu, setShowStyleMenu] = useState(false);

  const [viewState, setViewState] = useState({
    longitude: -51.1628,
    latitude: -23.3102,
    zoom: 13.5,
    pitch: 20,
    bearing: 0,
  });

  // Connection & Offline States
  const [isOnline, setIsOnline] = useState(true);
  const [pendingCount, setPendingCount] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  // Authentication & Session
  const [token, setToken] = useState<string | null>(null);
  const [username, setUsername] = useState<string>("");
  const [userId, setUserId] = useState<string>("");

  // Segments and Visits States
  const [segmentsData, setSegmentsData] = useState<any>(null);
  const [selectedSegment, setSelectedSegment] = useState<any>(null);
  const [isVisitModalOpen, setIsVisitModalOpen] = useState(false);
  const [conflicts, setConflicts] = useState<any[]>([]);
  const [showConflictsAlert, setShowConflictsAlert] = useState(false);

  // Custom Routes Building
  const [isRouteMode, setIsRouteMode] = useState(false);
  const [selectedSegmentIds, setSelectedSegmentIds] = useState<Set<number>>(new Set());
  const [routeName, setRouteName] = useState("");
  const [isSavingRoute, setIsSavingRoute] = useState(false);

  // Active visits list drawer
  const [isVisitsDrawerOpen, setIsVisitsDrawerOpen] = useState(false);
  const [myVisits, setMyVisits] = useState<any[]>([]);

  // Geolocation states
  const [userLocation, setUserLocation] = useState<[number, number] | null>(null);
  const [isLocating, setIsLocating] = useState(false);
  const [locationError, setLocationError] = useState<string | null>(null);

  // ------------------------------------------------------------------------------
  // AUTHENTICATION UTILS
  // ------------------------------------------------------------------------------
  const autoRegisterAnonymously = async () => {
    if (typeof window === "undefined") return;
    
    const savedToken = localStorage.getItem("auth_token");
    const savedUsername = localStorage.getItem("auth_username");
    
    if (savedToken && savedUsername) {
      setToken(savedToken);
      setUsername(savedUsername);
      return;
    }

    const anonUser = `mobile_${Math.floor(1000 + Math.random() * 9000)}`;
    const anonPass = "londrina_secure_123";

    try {
      const res = await fetch(`${NEXT_PUBLIC_API_URL}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: anonUser, password: anonPass })
      });
      if (res.ok) {
        const data = await res.json();
        localStorage.setItem("auth_token", data.token);
        localStorage.setItem("auth_username", data.username);
        localStorage.setItem("auth_user_id", data.user_id);
        setToken(data.token);
        setUsername(data.username);
        setUserId(data.user_id);
      }
    } catch (err) {
      console.warn("Auto-register failed (development mode offline fallback):", err);
      // Dummy credentials for offline preview
      setToken("dummy_dev_token");
      setUsername("offline_visitor");
    }
  };

  // ------------------------------------------------------------------------------
  // SEGMENTS LOADER
  // ------------------------------------------------------------------------------
  const fetchSegments = async (bboxStr: string) => {
    const currentToken = token || localStorage.getItem("auth_token");
    const headers: any = {};
    if (currentToken) {
      headers["Authorization"] = `Bearer ${currentToken}`;
    }

    if (!navigator.onLine) {
      const cached = await getCachedSegments(bboxStr);
      if (cached) {
        // Apply selection highlights
        const markedFeatures = cached.features.map((f: any) => ({
          ...f,
          properties: {
            ...f.properties,
            selected: selectedSegmentIds.has(f.properties.id)
          }
        }));
        setSegmentsData({ ...cached, features: markedFeatures });
      }
      return;
    }

    try {
      const res = await fetch(`${NEXT_PUBLIC_API_URL}/api/segments?bbox=${bboxStr}`, {
        headers
      });
      if (res.ok) {
        const geojson = await res.json();
        
        // Cache to IndexedDB for offline access
        await cacheSegments(bboxStr, geojson);

        // Highlight selected segments in real-time
        const markedFeatures = geojson.features.map((f: any) => ({
          ...f,
          properties: {
            ...f.properties,
            selected: selectedSegmentIds.has(f.properties.id)
          }
        }));
        setSegmentsData({ ...geojson, features: markedFeatures });
      }
    } catch (err) {
      console.warn("Could not fetch segments, trying cache:", err);
      const cached = await getCachedSegments(bboxStr);
      if (cached) {
        setSegmentsData(cached);
      }
    }
  };

  const reloadVisibleSegments = () => {
    const map = mapRef.current;
    if (!map) return;
    const bounds = map.getBounds();
    const bboxStr = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;
    fetchSegments(bboxStr);
  };

  // ------------------------------------------------------------------------------
  // OFFLINE VISITS QUEUE SYNC
  // ------------------------------------------------------------------------------
  const syncPendingVisits = async () => {
    if (!navigator.onLine || syncing) return;
    
    const pending = await getPendingVisits();
    if (pending.length === 0) {
      setPendingCount(0);
      return;
    }

    const currentToken = token || localStorage.getItem("auth_token");
    if (!currentToken) return;

    setSyncing(true);
    setSyncMessage("Sincronizando visitas pendientes...");

    try {
      const res = await fetch(`${NEXT_PUBLIC_API_URL}/api/sync/visits`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${currentToken}`
        },
        body: JSON.stringify(pending)
      });

      if (res.ok) {
        const data = await res.json();
        await clearPendingVisits();
        setPendingCount(0);
        setSyncMessage(`Sincronizados ${data.synced} registros.`);

        if (data.conflicts && data.conflicts.length > 0) {
          setConflicts(data.conflicts);
          setShowConflictsAlert(true);
        }

        setTimeout(() => setSyncMessage(null), 3000);
        reloadVisibleSegments();
      } else {
        setSyncMessage("Fallo al sincronizar. Reintentando luego.");
        setTimeout(() => setSyncMessage(null), 3000);
      }
    } catch (err) {
      setSyncMessage("Error de conexión al sincronizar.");
      setTimeout(() => setSyncMessage(null), 3000);
    } finally {
      setSyncing(false);
    }
  };

  // Check offline queue size
  const checkPendingQueue = async () => {
    const pending = await getPendingVisits();
    setPendingCount(pending.length);
  };

  // Fetch my visits
  const fetchMyVisits = async () => {
    const currentToken = token || localStorage.getItem("auth_token");
    if (!currentToken || !navigator.onLine) return;
    
    try {
      const res = await fetch(`${NEXT_PUBLIC_API_URL}/api/visits`, {
        headers: { "Authorization": `Bearer ${currentToken}` }
      });
      if (res.ok) {
        const data = await res.json();
        setMyVisits(data);
      }
    } catch (err) {
      console.warn("Could not fetch visits:", err);
    }
  };

  // Save visit handler
  const handleSaveVisit = async (notes: string, visited: boolean) => {
    if (!selectedSegment) return;

    const currentToken = token || localStorage.getItem("auth_token");
    const visitPayload: OfflineVisit = {
      segment_id: selectedSegment.id,
      visited,
      visited_at: new Date().toISOString(),
      notes,
      source: "mobile"
    };

    if (!navigator.onLine) {
      // Guardar localmente
      await savePendingVisit(visitPayload);
      await checkPendingQueue();
      
      // Update local layer in-memory instantly
      if (segmentsData) {
        const updatedFeatures = segmentsData.features.map((f: any) => {
          if (f.properties.id === selectedSegment.id) {
            return {
              ...f,
              properties: {
                ...f.properties,
                visited_by_user: visited,
                notes
              }
            };
          }
          return f;
        });
        setSegmentsData({ ...segmentsData, features: updatedFeatures });
      }
      return;
    }

    try {
      const res = await fetch(`${NEXT_PUBLIC_API_URL}/api/visits`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${currentToken}`
        },
        body: JSON.stringify(visitPayload)
      });

      if (res.ok) {
        reloadVisibleSegments();
        fetchMyVisits();
      }
    } catch (err) {
      console.warn("API saving failed, writing to offline queue:", err);
      await savePendingVisit(visitPayload);
      await checkPendingQueue();
    }
  };

  // ------------------------------------------------------------------------------
  // ROUTE CREATOR
  // ------------------------------------------------------------------------------
  const handleCreateRoute = async () => {
    if (selectedSegmentIds.size === 0) return;
    if (!routeName.trim()) {
      alert("Por favor introduce un nombre para la ruta");
      return;
    }

    const currentToken = token || localStorage.getItem("auth_token");
    if (!currentToken) return;

    setIsSavingRoute(true);
    try {
      const res = await fetch(`${NEXT_PUBLIC_API_URL}/api/routes`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${currentToken}`
        },
        body: JSON.stringify({
          name: routeName,
          segment_ids: Array.from(selectedSegmentIds)
        })
      });

      if (res.ok) {
        const data = await res.json();
        alert(`¡Ruta "${data.name}" guardada con éxito en PostGIS!`);
        setSelectedSegmentIds(new Set());
        setRouteName("");
        setIsRouteMode(false);
        reloadVisibleSegments();
      } else {
        alert("Fallo al crear la ruta. Asegúrate de que las calles estén conectadas.");
      }
    } catch (err) {
      alert("Error de conexión al crear la ruta.");
    } finally {
      setIsSavingRoute(false);
    }
  };

  // ------------------------------------------------------------------------------
  // INITIALIZATION AND CONTEXT EVENTS
  // ------------------------------------------------------------------------------
  useEffect(() => {
    autoRegisterAnonymously();

    // Set online/offline listeners
    const handleOnline = () => {
      setIsOnline(true);
      syncPendingVisits();
    };
    const handleOffline = () => {
      setIsOnline(false);
    };

    setIsOnline(navigator.onLine);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    // Check offline database queue
    checkPendingQueue();

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  // When token or selection highlights change
  useEffect(() => {
    if (token) {
      reloadVisibleSegments();
      fetchMyVisits();
    }
  }, [token, selectedSegmentIds]);

  // Handle map click
  const handleMapClick = (event: any) => {
    const features = event.features || [];
    const segmentFeature = features.find((f: any) => f.layer.id === "street-segments-touch-layer");
    
    if (segmentFeature) {
      const props = segmentFeature.properties;
      const segmentId = props.id;
      
      if (isRouteMode) {
        setSelectedSegmentIds(prev => {
          const next = new Set(prev);
          if (next.has(segmentId)) {
            next.delete(segmentId);
          } else {
            next.add(segmentId);
          }
          return next;
        });
      } else {
        setSelectedSegment({
          id: segmentId,
          name: props.name,
          length_m: props.length_m,
          visited_by_user: props.visited_by_user === "true" || props.visited_by_user === true,
          notes: props.notes
        });
        setIsVisitModalOpen(true);
      }
    }
  };

  // Map moves ended
  const handleMoveEnd = (evt: any) => {
    setViewState(evt.viewState);
    reloadVisibleSegments();
  };

  // Find active cluster details for the overlay HUD
  const activeClusterDetails = clusters.find(c => c.cluster_id === activeClusterId);
  const activeMeta = activeClusterDetails ? HUB_METADATA[activeClusterDetails.cluster_id] : null;

  // Custom calculation for density label based on selected sector
  const getSectorDensityLabel = (lojasCount: number) => {
    if (lojasCount === 0) return "Sin comercios activos detectados en esta zona.";
    if (selectedType === "all") return activeMeta?.densityLabel || `Zona comercial consolidada con ${lojasCount} locales.`;
    const typeLabel = selectedType === "software" 
      ? "Desarrollo de Software" 
      : selectedType === "support" 
        ? "Soporte TI" 
        : selectedType === "repairs" 
          ? "Hardware" 
          : "Servicios Tecnológicos";
    const nounLabel = selectedType === "software" 
      ? "empresas de desarrollo de software activas" 
      : selectedType === "support" 
        ? "empresas de soporte TI activas" 
        : selectedType === "repairs" 
          ? "talleres de reparación de hardware activos"
          : "locales tecnológicos activos";
    return `${typeLabel} en funcionamiento: ${lojasCount} ${nounLabel}.`;
  };

  // Geolocation function
  const locateUser = () => {
    if (!navigator.geolocation) {
      setLocationError("Geolocalización no soportada por tu dispositivo");
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
            duration: 1500,
          });
        }
      },
      (error) => {
        setIsLocating(false);
        setLocationError("Ubicación denegada o señal GPS inestable.");
        setTimeout(() => setLocationError(null), 3000);
      },
      {
        enableHighAccuracy: true,
        timeout: 8000,
        maximumAge: 120000,
      }
    );
  };

  return (
    <div className="flex-1 h-screen w-full relative overflow-hidden bg-zinc-950 flex flex-col">
      {/* MAP VIEW WRAPPER */}
      <div className="flex-1 w-full relative">
        <Map
          ref={mapRef}
          {...viewState}
          onMove={(evt: any) => setViewState(evt.viewState)}
          onMoveEnd={handleMoveEnd}
          onClick={handleMapClick}
          mapLib={maplibregl}
          mapStyle={MAP_STYLES[mapStyleKey].url}
          style={{ width: "100%", height: "100%" }}
          maxZoom={18}
          minZoom={9}
          interactiveLayerIds={["street-segments-touch-layer"]}
        >
          {/* Controls */}
          <div className="absolute right-4 top-4 z-20 flex flex-col gap-2">
            <NavigationControl position="top-right" showCompass={true} />
            <FullscreenControl position="top-right" />
          </div>

          {/* User Location */}
          {userLocation && (
            <Marker longitude={userLocation[0]} latitude={userLocation[1]} anchor="center">
              <div className="relative">
                <div className="absolute inset-0 rounded-full bg-blue-500/30 animate-ping" style={{ width: '24px', height: '24px', margin: '-12px' }} />
                <div className="w-4 h-4 rounded-full bg-blue-500 border-2 border-white shadow-lg" />
              </div>
            </Marker>
          )}

          {/* 1. Heatmap */}
          {showHeatmap && heatmapData && (
            <Source type="geojson" data={heatmapData}>
              <Layer
                id="heatmap-layer"
                type="heatmap"
                paint={{
                  "heatmap-weight": 1.0,
                  "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 0, 1.0, 9, 1.5, 15, 3.5],
                  "heatmap-color": [
                    "interpolate",
                    ["linear"],
                    ["heatmap-density"],
                    0, "rgba(0,0,50,0)",
                    0.15, "rgba(45, 0, 90, 0.25)",
                    0.35, "rgba(138, 43, 226, 0.55)",
                    0.6, "rgba(0, 0, 255, 0.75)",
                    0.8, "rgba(0, 191, 255, 0.85)",
                    0.95, "rgba(0, 242, 254, 0.95)",
                    1.0, "rgba(255, 255, 255, 1)"
                  ],
                  "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 0, 3, 9, 9, 15, 28],
                  "heatmap-opacity": 0.85
                }}
              />
            </Source>
          )}

          {/* 2. Street Segments Layer */}
          {segmentsData && (
            <Source type="geojson" data={segmentsData}>
              <Layer
                id="street-segments-layer"
                type="line"
                paint={{
                  "line-width": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    11, 1.5,
                    14, 3.5,
                    17, 8
                  ],
                  "line-color": [
                    "case",
                    ["boolean", ["get", "selected"], false],
                    "#f59e0b", // Orange selected for route building
                    ["boolean", ["get", "visited_by_user"], false],
                    "#10b981", // Bright green if visited
                    "#4b5563"  // Grey otherwise
                  ],
                  "line-opacity": 0.9
                }}
              />
              {/* Invisible, wider layer for mobile touch targeting */}
              <Layer
                id="street-segments-touch-layer"
                type="line"
                paint={{
                  "line-width": 18,
                  "line-color": "transparent"
                }}
              />
            </Source>
          )}

          {/* 3. Cluster Markers */}
          {showClusters && clusters.map((cluster) => {
            const [lng, lat] = cluster.center_geom.coordinates;
            const isActive = activeClusterId === cluster.cluster_id;
            const isHovered = hoveredClusterId === cluster.cluster_id;

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
                      duration: 1200,
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
                  <div className={`absolute inset-0 rounded-full transition-all duration-500 ${
                    isActive ? "w-12 h-12 -m-2.5 bg-primary/25 border-2 border-primary/50 animate-ping" : "w-8 h-8 bg-transparent"
                  }`} />
                  <span className="absolute flex h-7 w-7">
                    <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-65 ${
                      isActive ? "bg-amber-400" : "bg-primary"
                    }`}></span>
                  </span>
                  <div className={`w-8 h-8 rounded-full border-2 flex items-center justify-center font-black text-[10px] shadow-lg transition-all ${
                    isActive ? "bg-amber-500 border-white text-black" : "bg-zinc-900 border-primary text-primary"
                  }`}>
                    {cluster.total_lojas}
                  </div>
                </div>
              </Marker>
            );
          })}
        </Map>

        {/* FLOATING STATUS HUD */}
        <div className="absolute top-4 left-4 z-20 flex flex-col gap-2">
          {/* Geolocation trigger */}
          <button
            onClick={locateUser}
            disabled={isLocating}
            className="w-12 h-12 rounded-full bg-zinc-950/90 border border-zinc-800 flex items-center justify-center text-white hover:bg-zinc-900 transition-all shadow-xl pointer-events-auto"
          >
            {isLocating ? <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" /> : <Locate className="w-5 h-5" />}
          </button>

          {/* Map style toggle */}
          <div className="relative">
            <button
              onClick={() => setShowStyleMenu(!showStyleMenu)}
              className="w-12 h-12 rounded-full bg-zinc-950/90 border border-zinc-800 flex items-center justify-center text-white hover:bg-zinc-900 transition-all shadow-xl pointer-events-auto cursor-pointer"
              title="Cambiar estilo del mapa"
            >
              <MapIcon className="w-5 h-5 text-primary" />
            </button>
            {showStyleMenu && (
              <div className="absolute left-14 top-0 bg-zinc-950/95 border border-zinc-800 rounded-xl p-2 shadow-2xl flex flex-col gap-1 z-30 min-w-[120px] animate-fade-in pointer-events-auto">
                <button
                  onClick={() => { setMapStyleKey("dark"); setShowStyleMenu(false); }}
                  className={`px-3 py-1.5 rounded-lg text-left text-xs font-bold transition-all cursor-pointer ${mapStyleKey === "dark" ? "bg-primary text-white" : "text-zinc-400 hover:text-white hover:bg-white/5"}`}
                >
                  🌌 Oscuro
                </button>
                <button
                  onClick={() => { setMapStyleKey("light"); setShowStyleMenu(false); }}
                  className={`px-3 py-1.5 rounded-lg text-left text-xs font-bold transition-all cursor-pointer ${mapStyleKey === "light" ? "bg-primary text-white" : "text-zinc-400 hover:text-white hover:bg-white/5"}`}
                >
                  ☀️ Claro
                </button>
                <button
                  onClick={() => { setMapStyleKey("voyager"); setShowStyleMenu(false); }}
                  className={`px-3 py-1.5 rounded-lg text-left text-xs font-bold transition-all cursor-pointer ${mapStyleKey === "voyager" ? "bg-primary text-white" : "text-zinc-400 hover:text-white hover:bg-white/5"}`}
                >
                  🗺️ Voyager
                </button>
              </div>
            )}
          </div>

          {/* Connection Status Badge */}
          <div className="glass-panel px-3 py-2 rounded-2xl flex items-center gap-2 shadow-2xl text-[10px] font-bold text-white max-w-fit">
            {isOnline ? (
              <>
                <Wifi className="w-4 h-4 text-emerald-400" />
                <span className="text-zinc-200">Online | {username}</span>
              </>
            ) : (
              <>
                <WifiOff className="w-4 h-4 text-amber-500" />
                <span className="text-amber-500">Offline (Local Cache)</span>
              </>
            )}
          </div>

          {/* Sync Messages */}
          {syncMessage && (
            <div className="glass-panel px-3 py-2 rounded-2xl flex items-center gap-2 shadow-2xl text-[10px] font-bold text-white animate-fade-in bg-zinc-900 border border-zinc-800">
              <RefreshCw className="w-3.5 h-3.5 text-primary animate-spin" />
              <span>{syncMessage}</span>
            </div>
          )}

          {/* Pending Sync Queue Alert */}
          {pendingCount > 0 && (
            <button
              onClick={syncPendingVisits}
              disabled={syncing || !isOnline}
              className="glass-panel px-3 py-2 rounded-2xl flex items-center gap-2 shadow-2xl text-[10px] font-extrabold bg-amber-500 text-black hover:bg-amber-400 transition-all text-left max-w-fit cursor-pointer disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${syncing ? "animate-spin" : ""}`} />
              <span>Sincronizar {pendingCount} visitas pendientes</span>
            </button>
          )}
        </div>

        {/* Route Building Overlay HUD */}
        {isRouteMode && (
          <div className="absolute top-4 left-1/2 transform -translate-x-1/2 z-20 w-11/12 max-w-sm glass-panel p-4 rounded-2xl shadow-2xl border border-amber-500/20 bg-zinc-950/98 animate-slide-down">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Route className="w-4 h-4 text-amber-500" />
                <h4 className="text-xs font-black text-white">Construcción de Ruta</h4>
              </div>
              <button 
                onClick={() => {
                  setSelectedSegmentIds(new Set());
                  setIsRouteMode(false);
                }} 
                className="text-[9px] font-extrabold text-zinc-400 hover:text-white"
              >
                Cancelar
              </button>
            </div>
            <p className="text-[10px] text-zinc-400 mt-1 leading-tight">
              Toca las calles en el mapa para agregarlas a la ruta ({selectedSegmentIds.size} seleccionadas).
            </p>
            {selectedSegmentIds.size > 0 && (
              <div className="flex flex-col gap-2 mt-3 animate-fade-in">
                <input
                  type="text"
                  placeholder="Nombre de la ruta (Ej: Ruta Norte 1)"
                  value={routeName}
                  onChange={(e) => setRouteName(e.target.value)}
                  className="w-full bg-zinc-900 border border-zinc-800 rounded-xl px-3 py-2 text-xs text-white placeholder-zinc-500 focus:outline-none"
                />
                <button
                  onClick={handleCreateRoute}
                  disabled={isSavingRoute}
                  className="w-full py-2 bg-amber-500 hover:bg-amber-400 text-black font-extrabold text-xs rounded-xl shadow-lg transition-all"
                >
                  {isSavingRoute ? "Guardando en PostGIS..." : "Guardar Ruta"}
                </button>
              </div>
            )}
          </div>
        )}

        {/* Active Cluster HUD Card */}
        {activeClusterDetails && activeMeta && !isRouteMode && (
          <div className="absolute right-6 bottom-24 z-10 glass-panel p-5 rounded-2xl flex flex-col gap-3 shadow-2xl border border-slate-800/80 bg-zinc-950/98 max-w-[300px] animate-fade-in">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-xs font-black text-white leading-none">Polo #{activeClusterDetails.cluster_id}</h3>
                <span className="text-[9px] font-bold text-amber-500 uppercase tracking-widest mt-0.5 block">{activeMeta.zone}</span>
              </div>
              <button onClick={() => setActiveClusterId(null)} className="text-[8px] font-extrabold text-zinc-500 hover:text-white">Cerrar</button>
            </div>
            <p className="text-[10px] text-zinc-300 font-semibold leading-tight">{activeMeta.name}</p>
            <div className="space-y-1 bg-black/40 p-2.5 rounded-xl border border-white/5 text-[9px] text-zinc-400">
              {getSectorDensityLabel(activeClusterDetails.total_lojas)}
            </div>
          </div>
        )}
      </div>

      {/* MOBILE BOTTOM NAVIGATION BAR */}
      <div className="w-full bg-zinc-950 border-t border-zinc-900 px-4 py-3 pb-6 flex items-center justify-around gap-2 z-25">
        <button
          onClick={() => {
            setIsRouteMode(false);
            setIsVisitsDrawerOpen(false);
          }}
          className={`flex-1 flex flex-col items-center gap-1 py-1 px-2 rounded-xl transition-all cursor-pointer ${
            !isRouteMode && !isVisitsDrawerOpen ? "text-primary bg-primary/10" : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          <LayoutGrid className="w-5 h-5" />
          <span className="text-[9px] font-bold">Mapa</span>
        </button>

        <button
          onClick={() => {
            setIsRouteMode(true);
            setIsVisitsDrawerOpen(false);
          }}
          className={`flex-1 flex flex-col items-center gap-1 py-1 px-2 rounded-xl transition-all cursor-pointer ${
            isRouteMode ? "text-amber-500 bg-amber-500/10" : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          <Route className="w-5 h-5" />
          <span className="text-[9px] font-bold">Crear Ruta</span>
        </button>

        <button
          onClick={() => {
            fetchMyVisits();
            setIsVisitsDrawerOpen(true);
            setIsRouteMode(false);
          }}
          className={`flex-1 flex flex-col items-center gap-1 py-1 px-2 rounded-xl transition-all cursor-pointer ${
            isVisitsDrawerOpen ? "text-emerald-400 bg-emerald-500/10" : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          <CheckSquare className="w-5 h-5" />
          <span className="text-[9px] font-bold">Mis Visitas</span>
        </button>
      </div>

      {/* DRAWER FOR MY VISITS */}
      {isVisitsDrawerOpen && (
        <div className="fixed inset-x-0 bottom-0 z-40 bg-zinc-950 border-t border-zinc-900 rounded-t-3xl shadow-2xl p-6 flex flex-col gap-4 animate-slide-up max-h-[60%] overflow-y-auto">
          <div className="flex items-center justify-between border-b border-zinc-900 pb-3">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-5 h-5 text-emerald-400" />
              <h3 className="text-sm font-extrabold text-white">Calles Visitadas por Mí</h3>
            </div>
            <button 
              onClick={() => setIsVisitsDrawerOpen(false)}
              className="text-xs font-bold text-zinc-500 hover:text-white"
            >
              Cerrar
            </button>
          </div>

          <div className="flex flex-col gap-2.5">
            {myVisits.length === 0 ? (
              <div className="text-center py-6 text-xs text-zinc-500">
                Aún no has marcado calles como visitadas de forma online.
              </div>
            ) : (
              myVisits.map((visit) => (
                <div key={visit.id} className="p-3 bg-zinc-900 border border-zinc-800 rounded-2xl flex items-start justify-between gap-3">
                  <div>
                    <h4 className="text-xs font-extrabold text-white">{visit.street_name}</h4>
                    <span className="text-[9px] text-zinc-500 block mt-0.5">
                      Fecha: {new Date(visit.visited_at).toLocaleDateString()} | Disp: {visit.source}
                    </span>
                    {visit.notes && (
                      <p className="text-[10px] text-zinc-400 mt-1.5 flex items-start gap-1">
                        <MessageSquare className="w-3.5 h-3.5 text-zinc-500 shrink-0 mt-0.5" />
                        <span>{visit.notes}</span>
                      </p>
                    )}
                  </div>
                  <div className="bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded text-[8px] font-black text-emerald-400 uppercase">
                    Visitada
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* MODALS */}
      <VisitModal
        isOpen={isVisitModalOpen}
        onClose={() => {
          setIsVisitModalOpen(false);
          setSelectedSegment(null);
        }}
        segmentData={selectedSegment}
        onSave={handleSaveVisit}
        isOffline={!isOnline}
      />

      {/* CONFLICTS DIALOG */}
      {showConflictsAlert && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
          <div className="w-full max-w-md bg-zinc-950 border border-zinc-800 rounded-3xl p-6 shadow-2xl flex flex-col gap-4">
            <div className="flex items-center gap-2.5 border-b border-zinc-900 pb-3">
              <AlertCircle className="w-5 h-5 text-amber-500" />
              <h3 className="text-sm font-extrabold text-white">Resolución de Conflictos</h3>
            </div>
            <p className="text-[11px] text-zinc-400 leading-normal">
              Algunos registros se guardaron offline pero el servidor tiene marcas de fecha posteriores. 
              El servidor mantuvo su estado según la política de "última escritura gana":
            </p>
            <div className="flex flex-col gap-2 max-h-[150px] overflow-y-auto pr-1">
              {conflicts.map((c, i) => (
                <div key={i} className="p-2.5 bg-zinc-900 rounded-xl border border-zinc-800 text-[10px]">
                  <span className="font-extrabold text-white block">Segmento #{c.segment_id}</span>
                  <span className="text-zinc-500 block mt-0.5">Local: {c.client_visited ? "Visitado" : "No Visitado"} ({new Date(c.client_visited_at).toLocaleDateString()})</span>
                  <span className="text-amber-500 block">Servidor: {c.server_visited ? "Visitado" : "No Visitado"} ({new Date(c.server_visited_at).toLocaleDateString()})</span>
                </div>
              ))}
            </div>
            <button
              onClick={() => {
                setShowConflictsAlert(false);
                setConflicts([]);
              }}
              className="w-full py-2.5 bg-zinc-900 hover:bg-zinc-800 text-white font-extrabold text-xs rounded-xl border border-zinc-800 transition-all cursor-pointer"
            >
              Entendido
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
