"use client";

interface Business {
  cnpj: string;
  nome_fantasia: string;
  cnae_label: string;
  bairro: string;
  logradouro: string;
  distance_m: number;
  lat?: number;
  lon?: number;
  status?: "new" | "visited" | "client";
}

interface StopCardProps {
  index: number;
  displayName: string;
  cep: string | null;
  businesses: Business[];
  loadingBusinesses: boolean;
  onRemove: () => void;
  onMarkVisited: (cnpj: string) => void;
  onMarkClient: (cnpj: string) => void;
}

function parseAddressParts(displayName: string) {
  const parts = displayName.split(",").map(s => s.trim());
  return { street: parts[0] ?? "", district: parts[1] ?? "", city: parts.slice(2, 4).join(", ") ?? "" };
}

export default function StopCard({ index, displayName, cep, businesses, loadingBusinesses, onRemove, onMarkVisited, onMarkClient }: StopCardProps) {
  const { street, district, city } = parseAddressParts(displayName);

  async function handleVisit(b: Business) {
    if (!b.lat || !b.lon) return;
    await fetch("/api/visits", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cnpj: b.cnpj, lat: b.lat, lon: b.lon, logradouro: b.logradouro, bairro: b.bairro }),
    });
    onMarkVisited(b.cnpj);
  }

  async function handleSetClient(b: Business) {
    if (!b.lat || !b.lon) return;
    try {
      const res = await fetch(`/api/businesses/${b.cnpj}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "client" }),
      });
      if (res.ok) onMarkClient(b.cnpj);
    } catch { /* silencioso */ }
  }

  return (
    <div className="slide-up" style={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: "16px" }}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="flex items-center justify-center text-xs font-bold" style={{ width: "24px", height: "24px", borderRadius: "50%", background: "var(--accent)", color: "#0f0f0f" }}>{index + 1}</span>
          <span className="text-xs font-medium" style={{ color: "var(--accent)" }}>Parada {index + 1}</span>
        </div>
        <button onClick={onRemove} className="flex items-center justify-center" style={{ width: "28px", height: "28px", borderRadius: "6px", color: "var(--muted)" }} aria-label="Eliminar parada">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
        </button>
      </div>
      <p className="text-sm font-medium mb-0.5" style={{ color: "var(--fg)" }}>{street}</p>
      <p className="text-xs mb-0.5" style={{ color: "var(--fg-secondary)" }}>{district}</p>
      <p className="text-xs mb-1" style={{ color: "var(--muted)" }}>{city}</p>
      {cep && <p className="text-xs mb-3" style={{ color: "var(--muted)" }}>CEP: {cep}</p>}
      <div style={{ height: "1px", background: "var(--border)", margin: "12px 0" }} />
      <p className="text-xs font-medium mb-2" style={{ color: "var(--fg-secondary)" }}>
        Lojas en 500m
        {loadingBusinesses && <span className="pulse-text" style={{ marginLeft: "6px" }}>buscando...</span>}
        {!loadingBusinesses && <span style={{ color: "var(--accent)", marginLeft: "4px" }}>({businesses.length})</span>}
      </p>
      {businesses.length > 0 ? (
        <div className="space-y-2" style={{ maxHeight: "200px", overflowY: "auto" }}>
          {businesses.map(b => {
            const isClient = b.status === "client";
            const isVisited = b.status === "visited" || isClient;
            return (
              <div key={b.cnpj} className="flex items-start gap-2 text-xs" style={{ padding: "8px", background: isClient ? "#8b5cf608" : isVisited ? "#22c55e08" : "var(--bg-elevated)", borderRadius: "6px", borderLeft: isClient ? "2px solid #8b5cf6" : isVisited ? "2px solid #22c55e" : "2px solid transparent" }}>
                <span className="flex-shrink-0 mt-0.5" style={{ width: "8px", height: "8px", borderRadius: isClient ? "2px" : "50%", background: isClient ? "#8b5cf6" : isVisited ? "#22c55e" : "#f59e0b" }} />
                <div className="flex-1">
                  <p className="font-medium" style={{ color: "var(--fg)" }}>{b.nome_fantasia || b.cnpj}</p>
                  <p style={{ color: "var(--muted)" }}>{b.cnae_label} · {b.bairro}</p>
                  <p style={{ color: isClient ? "#8b5cf6" : isVisited ? "#22c55e" : "var(--accent)", fontSize: "11px" }}>{isClient ? "✓ Cliente" : isVisited ? "✓ Visitada" : `${b.distance_m}m`}</p>
                </div>
                {!isVisited && b.lat && b.lon && (
                  <div className="flex flex-col gap-1">
                    <button onClick={() => handleVisit(b)} className="text-xs font-medium" style={{ padding: "3px 8px", borderRadius: "4px", background: "#22c55e15", color: "#22c55e", border: "1px solid #22c55e30", cursor: "pointer", whiteSpace: "nowrap" }}>
                      Visitar
                    </button>
                    <button onClick={() => handleSetClient(b)} className="text-xs font-medium" style={{ padding: "3px 8px", borderRadius: "4px", background: "#8b5cf615", color: "#8b5cf6", border: "1px solid #8b5cf630", cursor: "pointer", whiteSpace: "nowrap" }}>
                      Cliente
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : !loadingBusinesses ? (
        <p className="text-xs" style={{ color: "var(--muted)" }}>Sin lojas en este radio.</p>
      ) : null}
      <style>{`@keyframes slideUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}.slide-up{animation:slideUp 0.3s ease-out}@keyframes pulseText{0%,100%{opacity:1}50%{opacity:0.4}}.pulse-text{animation:pulseText 1.5s ease-in-out infinite}`}</style>
    </div>
  );
}