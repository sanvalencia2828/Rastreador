"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { apiFetch } from "../lib/auth";
import { CIUDADES } from "../lib/ciudades";

interface Stop {
  nome_fantasia: string;
  bairro: string;
  logradouro: string;
  cliente_id?: string | null;
  diario?: boolean;
}

interface WeekDay {
  day: number;
  day_label: string;
  selected: number;
  stops: Stop[];
  distance_km: number;
  maps_links: string[];
}

interface Listed {
  nombre: string;
  direccion: string;
  municipio: string;
}

interface WeekResult {
  total_clientes: number;
  days: WeekDay[];
  fuera_de_maringa: Listed[];
  pendientes: Listed[];
  sin_asignar: Listed[];
  avisos?: string[];
}

export default function WeekPage() {
  const [days, setDays] = useState(5);
  const [maxStops, setMaxStops] = useState(10);
  const [cities, setCities] = useState<string[]>(["Maringá"]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WeekResult | null>(null);

  const generate = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch("/api/routes/generate-week", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ days, max_stops: maxStops, cities }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : "Erro ao gerar a semana");
        setResult(null);
      } else {
        setResult(data as WeekResult);
      }
    } catch {
      setError("Não foi possível conectar ao servidor.");
    } finally {
      setLoading(false);
    }
  }, [days, maxStops, cities]);

  const toggleCity = (name: string) =>
    setCities((cur) => (cur.includes(name) ? cur.filter((c) => c !== name) : [...cur, name]));

  const lists: Array<[string, Listed[] | undefined]> = [
    ["Fuera de las ciudades elegidas", result?.fuera_de_maringa],
    ["Pendentes de localizar", result?.pendientes],
    ["Sem atribuir (excedem o limite de paradas)", result?.sin_asignar],
  ];

  return (
    <main className="flex flex-col min-h-dvh px-4 py-4 lg:px-6 lg:py-6" style={{ maxWidth: "900px", margin: "0 auto", width: "100%" }}>
      <header className="mb-6">
        <Link href="/generate" className="inline-flex items-center gap-1 text-xs font-medium mb-3" style={{ color: "var(--muted)", textDecoration: "none" }}>
          ← Gerar Rota
        </Link>
        <h1 className="text-xl font-semibold tracking-tight" style={{ color: "var(--fg)" }}>Rotas da Semana</h1>
        <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>Tus clientes de las ciudades elegidas, agrupados por cercanía; los de visita diaria salen todos los días</p>
      </header>

      <section>
        {([["Dias", days, setDays, 1, 7], ["Paradas por dia (máx.)", maxStops, setMaxStops, 1, 30]] as const).map(([label, value, set, min, max]) => (
          <div key={label} className="mb-5">
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs" style={{ color: "var(--muted)" }}>{label}</label>
              <span className="text-xs font-bold" style={{ color: "var(--accent)" }}>{value}</span>
            </div>
            <input
              type="range" min={min} max={max} step={1} value={value}
              onChange={(e) => set(Number(e.target.value))}
              style={{ width: "100%", accentColor: "var(--accent)", height: "6px", padding: "8px 0", touchAction: "manipulation" }}
            />
          </div>
        ))}
        <fieldset className="mb-5">
          <legend className="text-xs mb-2" style={{ color: "var(--muted)" }}>Ciudades</legend>
          <div className="flex flex-wrap" style={{ gap: "8px" }}>
            {CIUDADES.map((c) => (
              <label key={c.name} className="flex items-center text-xs" style={{ gap: "6px", minHeight: "36px", padding: "4px 10px", border: "1px solid var(--border)", borderRadius: "999px", color: "var(--fg)" }}>
                <input type="checkbox" checked={cities.includes(c.name)} onChange={() => toggleCity(c.name)} style={{ accentColor: "var(--accent)" }} />
                {c.name}
              </label>
            ))}
          </div>
        </fieldset>
        <button
          onClick={generate}
          disabled={loading || cities.length === 0}
          style={{
            padding: "12px 24px", background: "var(--accent)", color: "#0f0f0f", fontWeight: 500, fontSize: "14px",
            borderRadius: "var(--radius)", width: "100%", border: "none",
            cursor: loading ? "not-allowed" : "pointer", opacity: loading || cities.length === 0 ? 0.5 : 1,
          }}
        >
          {loading ? "Gerando..." : "Gerar Semana"}
        </button>
        {error && <p className="text-xs mt-3" style={{ color: "var(--error)" }}>{error}</p>}
      </section>

      {result && (
        <>
          <hr style={{ border: "none", borderTop: "1px solid var(--border)", margin: "24px 0" }} />
          <p className="text-xs mb-4" style={{ color: "var(--muted)" }}>
            {result.total_clientes} clientes. Distâncias aproximadas em linha reta (não por rua).
          </p>

          {result.avisos?.map((a) => (
            <p key={a} className="text-xs mb-3" style={{ color: "var(--warning, var(--muted))" }}>⚠ {a}</p>
          ))}

          {result.days.length === 0 && (
            <p className="text-sm" style={{ color: "var(--fg-secondary)" }}>Ningún cliente ubicado en las ciudades elegidas.</p>
          )}

          {result.days.map((d) => (
            <section key={d.day} className="mb-6" style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: "16px", background: "var(--card)" }}>
              <h2 className="text-sm font-semibold mb-1" style={{ color: "var(--fg)" }}>
                {d.day_label} — {d.selected} paradas
              </h2>
              <p className="text-xs mb-3" style={{ color: "var(--muted)" }}>
                <span style={{ color: "var(--accent)", fontWeight: 600 }}>~{d.distance_km.toFixed(1)} km em linha reta</span>
              </p>
              <ol className="text-xs" style={{ color: "var(--fg-secondary)", paddingLeft: "20px", listStyle: "decimal" }}>
                {d.stops.map((s, i) => (
                  <li key={s.cliente_id ?? i} style={{ padding: "2px 0" }}>
                    <span style={{ color: "var(--fg)" }}>{s.nome_fantasia}</span>{s.diario && <span style={{ marginLeft: "6px", padding: "1px 6px", borderRadius: "999px", fontSize: "10px", fontWeight: 600, background: "var(--accent-dim)", color: "var(--accent)" }}>Diario</span>} — {s.logradouro}{s.bairro ? `, ${s.bairro}` : ""}
                  </li>
                ))}
              </ol>
              {d.maps_links.map((url, i) => (
                <p key={url} className="text-xs mt-2">
                  <a href={url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>
                    Abrir no Google Maps{d.maps_links.length > 1 ? ` (parte ${i + 1})` : ""}
                  </a>
                </p>
              ))}
            </section>
          ))}

          {lists.map(([title, items]) =>
            items && items.length > 0 ? (
              <div key={title} className="mt-2 mb-4">
                <h3 className="text-sm mb-2" style={{ color: "var(--fg-secondary)", fontWeight: 600 }}>{title} ({items.length})</h3>
                <ul className="text-xs" style={{ color: "var(--muted)" }}>
                  {items.map((c, i) => (
                    <li key={i}>{c.nombre} — {c.direccion}{c.municipio ? `, ${c.municipio}` : ""}</li>
                  ))}
                </ul>
              </div>
            ) : null
          )}
        </>
      )}
    </main>
  );
}
