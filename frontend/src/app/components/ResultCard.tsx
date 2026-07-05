"use client";

import { useState, type MouseEvent } from "react";

interface ResultCardProps {
  displayName: string;
  lat: number;
  lon: number;
  cep: string | null;
}

function formatCoords(lat: number, lon: number): string {
  return `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
}

function parseAddressParts(displayName: string): { street: string; district: string; city: string } {
  const parts = displayName.split(",").map((s) => s.trim());
  return { street: parts[0] ?? "", district: parts[1] ?? "", city: parts.slice(2, 4).join(", ") ?? "" };
}

export default function ResultCard({ displayName, lat, lon, cep }: ResultCardProps) {
  const [copied, setCopied] = useState(false);
  const { street, district, city } = parseAddressParts(displayName);
  const coordsText = formatCoords(lat, lon);

  async function handleCopy(e: MouseEvent<HTMLButtonElement>) {
    e.preventDefault();
    try {
      await navigator.clipboard.writeText(coordsText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = coordsText;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  return (
    <div className="slide-up" style={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: "20px" }}>
      <div className="flex items-center gap-2 mb-4" style={{ color: "var(--accent)", fontSize: "12px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
        Ubicación encontrada
      </div>
      <div className="space-y-1.5 mb-4">
        <p className="text-sm font-medium" style={{ color: "var(--fg)" }}>{street}</p>
        <p className="text-xs" style={{ color: "var(--fg-secondary)" }}>{district}</p>
        <p className="text-xs" style={{ color: "var(--muted)" }}>{city}</p>
        {cep && <p className="text-xs" style={{ color: "var(--muted)" }}>CEP: {cep}</p>}
      </div>
      <div style={{ height: "1px", background: "var(--border)", margin: "16px 0" }} />
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs mb-0.5" style={{ color: "var(--muted)", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.05em" }}>Coordenadas</p>
          <p className="font-mono text-sm" style={{ color: "var(--fg)", letterSpacing: "0.02em" }}>{coordsText}</p>
        </div>
        <button onClick={handleCopy} className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors" style={{ background: copied ? "var(--accent)" : "var(--bg-elevated)", color: copied ? "#0f0f0f" : "var(--fg-secondary)", border: "1px solid var(--border)", borderRadius: "calc(var(--radius) - 2px)", whiteSpace: "nowrap" }} aria-label={copied ? "Coordenadas copiadas" : "Copiar coordenadas"}>
          {copied ? (<><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>Copiado</>) : (<><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>Copiar</>)}
        </button>
      </div>
      <p className="mt-3 text-xs" style={{ color: "var(--muted)" }}>Radio de búsqueda: <span style={{ color: "var(--accent)" }}>500m</span> alrededor del punto</p>
      <style>{`@keyframes slideUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}.slide-up{animation:slideUp 0.3s ease-out}`}</style>
    </div>
  );
}
