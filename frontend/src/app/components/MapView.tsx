"use client";

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

delete (L.Icon.Default.prototype as any)._getIconUrl;

const DEFAULT_CENTER: [number, number] = [-23.37, -51.13];
const DEFAULT_ZOOM = 14;
const RADIUS_METERS = 500;

const markerIcon = L.divIcon({
  html: `<svg width="28" height="40" viewBox="0 0 28 40" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M14 0C6.268 0 0 6.268 0 14c0 10.5 14 26 14 26s14-15.5 14-26C28 6.268 21.732 0 14 0z" fill="#00c9a7"/><circle cx="14" cy="14" r="6" fill="#0f0f0f"/></svg>`,
  iconSize: [28, 40],
  iconAnchor: [14, 40],
  popupAnchor: [0, -40],
  className: "",
});

interface MapViewProps {
  lat: number | null;
  lon: number | null;
}

export default function MapView({ lat, lon }: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markerRef = useRef<L.Marker | null>(null);
  const circleRef = useRef<L.Circle | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { zoomControl: true, attributionControl: true }).setView(DEFAULT_CENTER, DEFAULT_ZOOM);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>', maxZoom: 18 }).addTo(map);
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (lat !== null && lon !== null) {
      markerRef.current?.remove();
      circleRef.current?.remove();
      markerRef.current = L.marker([lat, lon], { icon: markerIcon }).addTo(map);
      circleRef.current = L.circle([lat, lon], { radius: RADIUS_METERS, color: "#00c9a7", fillColor: "#00c9a7", fillOpacity: 0.08, weight: 2, dashArray: "8 4" }).addTo(map);
      map.flyTo([lat, lon], 16, { duration: 1.5 });
    }
  }, [lat, lon]);

  return (
    <div ref={containerRef} role="application" aria-label="Mapa interactivo con la ubicación buscada" style={{ width: "100%", height: "100%", minHeight: "400px", borderRadius: "var(--radius)", overflow: "hidden" }} />
  );
}
