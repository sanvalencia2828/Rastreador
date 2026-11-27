"use client";

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

delete (L.Icon.Default.prototype as any)._getIconUrl;

const DEFAULT_CENTER: [number, number] = [-23.37, -51.13];
const DEFAULT_ZOOM = 14;
const RADIUS_METERS = 500;

const stopIcon = L.divIcon({
  html: `<svg width="28" height="40" viewBox="0 0 28 40" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M14 0C6.268 0 0 6.268 0 14c0 10.5 14 26 14 26s14-15.5 14-26C28 6.268 21.732 0 14 0z" fill="#00c9a7"/><circle cx="14" cy="14" r="6" fill="#0f0f0f"/></svg>`,
  iconSize: [28, 40],
  iconAnchor: [14, 40],
  popupAnchor: [0, -40],
  className: "",
});

const businessIcon = L.divIcon({
  html: `<svg width="12" height="12" viewBox="0 0 12 12" xmlns="http://www.w3.org/2000/svg"><circle cx="6" cy="6" r="5" fill="#f59e0b" stroke="#0f0f0f" stroke-width="1.5"/></svg>`,
  iconSize: [12, 12],
  iconAnchor: [6, 6],
  className: "",
});

const visitedIcon = L.divIcon({
  html: `<svg width="12" height="12" viewBox="0 0 12 12" xmlns="http://www.w3.org/2000/svg"><circle cx="6" cy="6" r="5" fill="#22c55e" stroke="#0f0f0f" stroke-width="1.5"/></svg>`,
  iconSize: [12, 12],
  iconAnchor: [6, 6],
  className: "",
});

const clientIcon = L.divIcon({
  html: `<svg width="14" height="14" viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg"><rect x="1" y="1" width="12" height="12" rx="2" fill="#8b5cf6" stroke="#0f0f0f" stroke-width="1.5"/></svg>`,
  iconSize: [14, 14],
  iconAnchor: [7, 7],
  className: "",
});

// Clientes propios: rombo azul; atrasado rojo y diario cian, más grandes.
function clienteIcon(color: string, size: number) {
  const h = size / 2;
  return L.divIcon({
    html: `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" xmlns="http://www.w3.org/2000/svg"><path d="M${h} 1 L${size - 1} ${h} L${h} ${size - 1} L1 ${h} Z" fill="${color}" stroke="#0f0f0f" stroke-width="1.5"/></svg>`,
    iconSize: [size, size],
    iconAnchor: [h, h],
    className: "",
  });
}
const clienteNormalIcon = clienteIcon("#3b82f6", 16);
const clienteDiarioIcon = clienteIcon("#06b6d4", 20);
const clienteAtrasadoIcon = clienteIcon("#ef4444", 20);

const escapar = (t: string) => t.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

interface MapStop { id: string; lat: number; lon: number; }
interface MapBusiness {
  lat: number; lon: number; nome_fantasia: string; distance_m: number; status?: string;
  origen?: "cliente" | "negocio"; visita_diaria?: boolean; atrasado?: boolean;
}
interface MapViewProps { stops: MapStop[]; businesses: MapBusiness[]; center?: { lat: number; lon: number }; }

function getIcon(b: MapBusiness) {
  if (b.origen === "cliente") return b.atrasado ? clienteAtrasadoIcon : b.visita_diaria ? clienteDiarioIcon : clienteNormalIcon;
  const status = b.status;
  if (status === "client") return clientIcon;
  if (status === "visited") return visitedIcon;
  return businessIcon;
}

export default function MapView({ stops, businesses, center }: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const stopsLayerRef = useRef<L.LayerGroup>(L.layerGroup());
  const businessesLayerRef = useRef<L.LayerGroup>(L.layerGroup());

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const initialCenter: [number, number] = center ? [center.lat, center.lon] : DEFAULT_CENTER;
    const map = L.map(containerRef.current, { zoomControl: true, attributionControl: true }).setView(initialCenter, DEFAULT_ZOOM);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>', maxZoom: 18 }).addTo(map);
    stopsLayerRef.current.addTo(map);
    businessesLayerRef.current.addTo(map);
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  useEffect(() => {
    stopsLayerRef.current.clearLayers();
    const map = mapRef.current;
    if (!map) return;
    stops.forEach((stop, i) => {
      L.marker([stop.lat, stop.lon], { icon: stopIcon }).bindPopup(`<b>Parada ${i + 1}</b>`).addTo(stopsLayerRef.current);
      L.circle([stop.lat, stop.lon], { radius: RADIUS_METERS, color: "#00c9a7", fillColor: "#00c9a7", fillOpacity: 0.06, weight: 1.5, dashArray: "6 4" }).addTo(stopsLayerRef.current);
    });
    if (stops.length > 0) {
      const bounds = L.latLngBounds(stops.map(s => [s.lat, s.lon] as [number, number]));
      map.fitBounds(bounds, { padding: [50, 50], maxZoom: 16 });
    }
  }, [stops]);

  const encuadradoRef = useRef(false);
  const sinParadas = stops.length === 0;
  const hayCentro = center !== undefined; // booleano: center llega como objeto nuevo en cada render

  useEffect(() => {
    businessesLayerRef.current.clearLayers();
    const map = mapRef.current;
    const propios = businesses.filter(b => b.origen === "cliente");
    // la primera vez que llegan clientes y no hay paradas ni centro pedido, encuadrarlos (si no, quedan fuera de vista)
    if (map && sinParadas && !hayCentro && propios.length > 0 && !encuadradoRef.current) {
      encuadradoRef.current = true;
      map.fitBounds(L.latLngBounds(propios.map(b => [b.lat, b.lon] as [number, number])), { padding: [40, 40], maxZoom: 15 });
    }
    businesses.forEach(b => {
      const detalle = b.origen === "cliente"
        ? ["Cliente", b.atrasado && "atrasado", b.visita_diaria && "diario"].filter(Boolean).join(" · ")
        : `${b.distance_m}m`;
      L.marker([b.lat, b.lon], { icon: getIcon(b), zIndexOffset: b.origen === "cliente" ? 1000 : 0 })
        .bindPopup(`<b>${escapar(b.nome_fantasia || "")}</b><br>${detalle}`)
        .addTo(businessesLayerRef.current);
    });
  }, [businesses, sinParadas, hayCentro]);

  return (
    <div ref={containerRef} role="application" aria-label="Mapa con paradas y lojas" style={{ width: "100%", height: "100%", minHeight: "400px", borderRadius: "var(--radius)", overflow: "hidden" }} />
  );
}