"use client";

import { useMemo, useState, useSyncExternalStore } from "react";
import { apiFetch } from "../lib/auth";
import { CIUDADES } from "../lib/ciudades";
import { alternarVisitado, guardarRuta, hoy, leerCrudo, parsear, suscribir } from "../lib/visitados";

interface Stop {
  id: string;
  nombre: string;
  ciudad: string;
  lat: number;
  lon: number;
  km_desde_anterior: number;
  llegada: string;
  diario: boolean;
  atrasado: boolean;
}

interface Listed {
  id: string;
  nombre: string;
  ciudad: string;
}

interface DiaResult {
  hora_salida: string;
  hora_fin: string;
  distance_km: number;
  stops: Stop[];
  maps_links: string[];
  sin_ubicacion: Listed[];
  fuera_por_tope: Listed[];
  extra_no_encontrados: number;
}

interface ClienteOption {
  id: string;
  nombre_negocio: string | null;
  nombre_cliente: string | null;
  municipio: string | null;
  visita_diaria: boolean;
}

const badge = (bg: string, fg: string) => ({
  padding: "2px 8px", borderRadius: "999px", fontSize: "12px", fontWeight: 600, background: bg, color: fg,
});
const card = { background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius)" };
const big = { minHeight: "48px", fontSize: "16px" }; // 16px evita el zoom de iOS al enfocar

export default function ClientesDelDia() {
  const [inicio, setInicio] = useState("Apucarana");
  const [pos, setPos] = useState<{ lat: number; lon: number } | null>(null);
  const [hora, setHora] = useState("09:30");
  const [maxParadas, setMaxParadas] = useState(12);
  const [clientes, setClientes] = useState<ClienteOption[] | null>(null);
  const [extra, setExtra] = useState<Set<string>>(new Set());
  const [filtro, setFiltro] = useState("");
  // ruta y visitados del día viven en localStorage (lib/visitados): sobreviven a recargar la página
  const fecha = hoy();
  const raw = useSyncExternalStore(suscribir, () => leerCrudo(fecha), () => "");
  const dia = useMemo(() => parsear(raw), [raw]);
  const ruta = dia.ruta as DiaResult | null;
  const result = ruta && Array.isArray(ruta.stops) ? ruta : null;
  const visitados = new Set(dia.visitados);
  const hechas = result ? result.stops.filter((s) => visitados.has(s.id)).length : 0;
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const usarUbicacion = () => {
    if (!navigator.geolocation) return setError("Este navegador no da la ubicación");
    navigator.geolocation.getCurrentPosition(
      (p) => { setPos({ lat: p.coords.latitude, lon: p.coords.longitude }); setError(null); },
      () => setError("No se pudo obtener la ubicación"),
      { enableHighAccuracy: true, timeout: 10000 },
    );
  };

  const abrirExtras = async () => {
    if (clientes) return setClientes(null); // segundo toque: cerrar
    const res = await apiFetch("/api/clientes?limit=500");
    if (!res.ok) return setError("No se pudieron cargar los clientes");
    setClientes(await res.json());
  };

  const toggle = (id: string) => setExtra((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const generar = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch("/api/routes/clientes-dia", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...(pos ? { start_lat: pos.lat, start_lon: pos.lon } : { start_city: inicio }),
          hora_salida: hora,
          max_paradas: maxParadas,
          extra_ids: [...extra],
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : "Error al generar la ruta");
        return;
      }
      guardarRuta(fecha, data);
    } catch {
      setError("Error de conexión");
    } finally {
      setLoading(false);
    }
  };

  const nombre = (c: ClienteOption) => c.nombre_negocio || c.nombre_cliente || "";
  const visibles = (clientes ?? [])
    .filter((c) => !c.visita_diaria) // los diarios ya entran siempre
    .filter((c) => `${nombre(c)} ${c.municipio ?? ""}`.toLowerCase().includes(filtro.toLowerCase()));

  return (
    <section aria-labelledby="clientes-dia-title" className="mb-8 flex flex-col gap-3">
      <h2 id="clientes-dia-title" className="text-lg font-semibold" style={{ color: "var(--fg)" }}>Clientes del día</h2>
      <p className="text-sm" style={{ color: "var(--muted)" }}>
        Siempre entran los de visita diaria y los atrasados. Distancias en línea recta.
      </p>

      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1 text-sm col-span-2" style={{ color: "var(--muted)" }}>
          Salgo de
          <select
            value={pos ? "" : inicio}
            onChange={(e) => { setInicio(e.target.value); setPos(null); }}
            className="px-3" style={{ ...big, ...card, color: "var(--fg)" }}
          >
            {pos && <option value="">Mi ubicación</option>}
            {CIUDADES.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
          </select>
        </label>
        <button type="button" onClick={usarUbicacion} className="col-span-2 font-medium"
          style={{ ...big, ...card, color: "var(--accent)" }}>
          {pos ? "Ubicación tomada ✓" : "Usar mi ubicación"}
        </button>
        <label className="flex flex-col gap-1 text-sm" style={{ color: "var(--muted)" }}>
          Hora de salida
          <input type="time" value={hora} onChange={(e) => setHora(e.target.value)} required
            className="px-3" style={{ ...big, ...card, color: "var(--fg)" }} />
        </label>
        <label className="flex flex-col gap-1 text-sm" style={{ color: "var(--muted)" }}>
          Máx. paradas
          <input type="number" inputMode="numeric" min={1} max={50} value={maxParadas}
            onChange={(e) => setMaxParadas(Math.max(1, Math.min(50, Number(e.target.value) || 1)))}
            className="px-3" style={{ ...big, ...card, color: "var(--fg)" }} />
        </label>
      </div>

      <button type="button" onClick={abrirExtras} aria-expanded={!!clientes} className="font-medium text-left px-4"
        style={{ ...big, ...card, color: "var(--fg)" }}>
        {clientes ? "Ocultar" : "Agregar otros clientes"}{extra.size > 0 && ` (${extra.size})`}
      </button>
      {clientes && (
        <div className="flex flex-col gap-2 p-3" style={card}>
          <input type="search" placeholder="Buscar por nombre o ciudad" value={filtro} onChange={(e) => setFiltro(e.target.value)}
            aria-label="Buscar cliente" className="px-3" style={{ ...big, ...card, color: "var(--fg)" }} />
          <ul className="flex flex-col" style={{ maxHeight: "50vh", overflowY: "auto" }}>
            {visibles.map((c) => (
              <li key={c.id}>
                <label className="flex items-center gap-3 px-1" style={{ minHeight: "48px", color: "var(--fg)" }}>
                  <input type="checkbox" checked={extra.has(c.id)} onChange={() => toggle(c.id)} style={{ width: "22px", height: "22px" }} />
                  <span className="flex-1">{nombre(c)}</span>
                  <span className="text-sm" style={{ color: "var(--muted)" }}>{c.municipio}</span>
                </label>
              </li>
            ))}
            {visibles.length === 0 && <li className="text-sm py-2" style={{ color: "var(--muted)" }}>Sin resultados</li>}
          </ul>
        </div>
      )}

      <button type="button" onClick={generar} disabled={loading} className="font-semibold"
        style={{ ...big, borderRadius: "var(--radius)", background: "var(--accent)", color: "#0f0f0f", opacity: loading ? 0.6 : 1 }}>
        {loading ? "Generando..." : "Generar ruta de clientes"}
      </button>
      {error && <p role="alert" className="text-sm" style={{ color: "var(--error)" }}>{error}</p>}

      {result && (
        <div className="flex flex-col gap-3" aria-live="polite">
          {result.stops.length > 0 && (
            <div className="sticky top-0 z-10 flex flex-col gap-1 py-2" style={{ background: "var(--bg)" }}>
              <div className="flex justify-between text-sm font-medium" style={{ color: "var(--fg)" }}>
                <span id="progreso-label">Visitados</span>
                <span>{hechas}/{result.stops.length}</span>
              </div>
              <div role="progressbar" aria-labelledby="progreso-label" aria-valuemin={0} aria-valuemax={result.stops.length}
                aria-valuenow={hechas} style={{ height: "10px", borderRadius: "999px", background: "var(--border)", overflow: "hidden" }}>
                <div style={{ width: `${(hechas / result.stops.length) * 100}%`, height: "100%", background: "var(--accent)", transition: "width .2s" }} />
              </div>
            </div>
          )}
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            {result.stops.length} paradas · {result.distance_km} km · salida {result.hora_salida} · fin aprox. {result.hora_fin}
          </p>
          {result.maps_links.map((url, i) => (
            <a key={url} href={url} target="_blank" rel="noopener noreferrer" className="flex items-center justify-center font-semibold"
              style={{ ...big, ...card, color: "var(--accent)", textDecoration: "none" }}>
              Abrir ruta en Google Maps{result.maps_links.length > 1 ? ` (${i + 1}/${result.maps_links.length})` : ""}
            </a>
          ))}
          <ol className="flex flex-col gap-3">
            {result.stops.map((s, i) => (
              <li key={s.id} className="flex gap-3 p-4" style={{ ...card, opacity: visitados.has(s.id) ? 0.5 : 1 }}>
                <span aria-hidden className="flex items-center justify-center font-bold shrink-0"
                  style={{ width: "40px", height: "40px", borderRadius: "999px", background: "var(--accent)", color: "#0f0f0f", fontSize: "18px" }}>
                  {i + 1}
                </span>
                <div className="flex flex-col gap-1 flex-1 min-w-0">
                  <span className="font-semibold" style={{ color: "var(--fg)", fontSize: "17px", overflowWrap: "anywhere" }}>
                    <span className="sr-only">Parada {i + 1}: </span>{s.nombre}
                  </span>
                  <span className="text-sm" style={{ color: "var(--muted)" }}>{s.ciudad}</span>
                  <div className="flex flex-wrap gap-2 items-center text-sm" style={{ color: "var(--fg-secondary, var(--fg))" }}>
                    <span>{s.llegada}</span>
                    <span>· {s.km_desde_anterior} km</span>
                    {s.diario && <span style={badge("var(--accent-dim)", "var(--accent)")}>diario</span>}
                    {s.atrasado && <span style={badge("color-mix(in srgb, var(--error) 15%, transparent)", "var(--error)")}>atrasado</span>}
                  </div>
                  <label className="flex items-center gap-3 mt-1 font-medium" style={{ minHeight: "48px", color: "var(--fg)" }}>
                    <input type="checkbox" checked={visitados.has(s.id)} onChange={() => alternarVisitado(fecha, s.id)}
                      style={{ width: "24px", height: "24px", accentColor: "var(--accent)" }} />
                    visitado
                  </label>
                  <a href={`https://www.google.com/maps/dir/?api=1&destination=${s.lat},${s.lon}`} target="_blank" rel="noopener noreferrer"
                    className="flex items-center justify-center font-medium mt-1"
                    style={{ ...big, ...card, color: "var(--accent)", textDecoration: "none" }}>
                    Navegar
                  </a>
                </div>
              </li>
            ))}
          </ol>
          {result.fuera_por_tope.length > 0 && (
            <ListaAparte titulo={`No caben con el tope (${result.fuera_por_tope.length})`} items={result.fuera_por_tope} />
          )}
          {result.sin_ubicacion.length > 0 && (
            <ListaAparte titulo={`Sin ubicación (${result.sin_ubicacion.length})`} items={result.sin_ubicacion} />
          )}
        </div>
      )}
    </section>
  );
}

function ListaAparte({ titulo, items }: { titulo: string; items: Listed[] }) {
  return (
    <div className="p-4" style={card}>
      <p className="text-sm font-medium mb-2" style={{ color: "var(--fg)" }}>{titulo}</p>
      <ul className="text-sm flex flex-col gap-1" style={{ color: "var(--muted)" }}>
        {items.map((x) => <li key={x.id}>{x.nombre} — {x.ciudad}</li>)}
      </ul>
    </div>
  );
}
