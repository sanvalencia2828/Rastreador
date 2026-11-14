"use client";

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

delete (L.Icon.Default.prototype as any)._getIconUrl;

interface CityMapData {
  id: number;
  name: string;
  lat: number | null;
  lon: number | null;
  total: number;
  visited: number;
}

interface MapaCoberturaProps {
  cities: CityMapData[];
}

export default function MapaCobertura({ cities }: MapaCoberturaProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const validCities = cities.filter(c => c.lat !== null && c.lon !== null);
    if (validCities.length === 0) return;

    const map = L.map(containerRef.current, { zoomControl: true, attributionControl: true }).setView(
      [-23.35, -51.45], 8
    );

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 18,
    }).addTo(map);

    validCities.forEach(c => {
      const radius = Math.max(1500, Math.min(c.total * 50, 15000));
      const pct = c.total > 0 ? (c.visited / c.total) * 100 : 0;
      const color = pct > 60 ? "#22c55e" : pct > 30 ? "#f59e0b" : "#ff5c5c";

      L.circle([c.lat!, c.lon!], {
        radius,
        color,
        fillColor: color,
        fillOpacity: 0.12,
        weight: 1.5,
      }).addTo(map);

      L.marker([c.lat!, c.lon!], {
        icon: L.divIcon({
          html: `<div style="background:var(--card, #1a1a1a);color:var(--fg, #e8e8e8);padding:2px 6px;border-radius:4px;font-size:11px;font-weight:600;white-space:nowrap;border:1px solid var(--border, #2a2a2a);">${c.name}</div>`,
          iconSize: [0, 0],
          className: "",
        }),
      }).addTo(map);
    });

    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, [cities]);

  return (
    <div
      ref={containerRef}
      role="application"
      aria-label="Mapa de cobertura por ciudad"
      style={{ width: "100%", height: "350px", borderRadius: "var(--radius)", overflow: "hidden", marginTop: "24px" }}
    />
  );
}