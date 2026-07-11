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

interface MapStop { id: string; lat: number; lon: number; }
interface MapBusiness { lat: number; lon: number; nome_fantasia: string; distance_m: number; }
interface MapViewProps { stops: MapStop[]; businesses: MapBusiness[]; }

export default function MapView({ stops, businesses }: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const stopsLayerRef = useRef<L.LayerGroup>(L.layerGroup());
  const businessesLayerRef = useRef<L.LayerGroup>(L.layerGroup());

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { zoomControl: true, attributionControl: true }).setView(DEFAULT_CENTER, DEFAULT_ZOOM);
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

  useEffect(() => {
    businessesLayerRef.current.clearLayers();
    businesses.forEach(b => {
      L.marker([b.lat, b.lon], { icon: businessIcon }).bindPopup(`<b>${b.nome_fantasia}</b><br>${b.distance_m}m`).addTo(businessesLayerRef.current);
    });
  }, [businesses]);

  return (
    <div ref={containerRef} role="application" aria-label="Mapa con paradas y lojas cercanas" style={{ width: "100%", height: "100%", minHeight: "400px", borderRadius: "var(--radius)", overflow: "hidden" }} />
  );
}