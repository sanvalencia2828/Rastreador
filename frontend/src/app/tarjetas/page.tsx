"use client";

import { useCallback, useMemo, useState, useSyncExternalStore } from "react";
import { apiFetch } from "../lib/auth";
import StatusMessage from "../components/StatusMessage";

// Mismos nombres que cities.py (el backend rechaza los demás).
const CIUDADES = ["Maringá", "Marialva", "Arapongas", "Apucarana", "Mandaguari"];
const POR_DEFECTO = ["Maringá", "Marialva", "Arapongas"];
const GUARDADAS_KEY = "rastreador_tarjetas_rutas";

type Resultado = "tarjeta_entregada" | "cerrado" | "rechazo" | "interesado" | "no_encontrado";

const BOTONES: Array<[Resultado, string]> = [
  ["tarjeta_entregada", "Tarjeta entregada"],
  ["interesado", "Interesado"],
  ["cerrado", "Cerrado"],
  ["no_encontrado", "No lo encontré"],
];
const ETIQUETAS: Record<Resultado, string> = {
  tarjeta_entregada: "Tarjeta entregada",
  interesado: "Interesado",
  cerrado: "Cerrado",
  rechazo: "Rechazo",
  no_encontrado: "No encontrado",
};

interface Parada {
  orden: number;
  cnpj: string;
  nombre: string;
  direccion: string;
  bairro: string;
  ciudad: string;
  tipo: string | null;
  distancia_m: number;
  maps_url: string;
  hecha: boolean;
}

interface Ruta {
  route_id: string | null;
  nombre: string;
  ciudades: string[];
  paradas: Parada[];
  total: number;
  distancia_km: number;
  aviso: string | null;
}

interface Conteo {
  hoy: number;
  semana: number;
  total: number;
  por_resultado: Record<Resultado, number>;
}

interface Resumen {
  ciudades: Array<Conteo & { ciudad: string; geocodificados: number; sin_tarjeta: number }>;
  totales: Conteo;
}

function detalle(data: unknown, fallback: string): string {
  const d = (data as { detail?: unknown } | null)?.detail;
  return typeof d === "string" ? d : fallback;
}

// Ids de las últimas rutas guardadas (localStorage, solo para "Retomar" en este navegador).
const oyentes = new Set<() => void>();
function suscribir(cb: () => void) {
  oyentes.add(cb);
  return () => {
    oyentes.delete(cb);
  };
}
function leerCrudo(): string {
  try {
    return localStorage.getItem(GUARDADAS_KEY) ?? "[]";
  } catch {
    return "[]";
  }
}
function parsear(raw: string): string[] {
  try {
    const v = JSON.parse(raw);
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}
function escribirGuardadas(ids: string[]) {
  try {
    localStorage.setItem(GUARDADAS_KEY, JSON.stringify(ids));
  } catch {
    /* sin almacenamiento: solo no se podrá retomar */
  }
  oyentes.forEach((cb) => cb());
}

function metros(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${m} m`;
}

const tarjeta = {
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  padding: "16px",
  background: "var(--card)",
} as const;

const botonPrincipal = (deshabilitado: boolean) => ({
  padding: "14px 24px",
  background: "var(--accent)",
  color: "#0f0f0f",
  fontWeight: 600,
  fontSize: "15px",
  borderRadius: "var(--radius)",
  width: "100%",
  minHeight: "48px",
  cursor: deshabilitado ? "not-allowed" : "pointer",
  opacity: deshabilitado ? 0.5 : 1,
});

const botonSecundario = {
  padding: "12px 16px",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  color: "var(--fg)",
  fontSize: "14px",
  minHeight: "48px",
  textAlign: "center" as const,
  textDecoration: "none",
  display: "block",
};

export default function TarjetasPage() {
  const [vista, setVista] = useState<"ruta" | "resumen">("ruta");
  const [elegidas, setElegidas] = useState<string[]>(POR_DEFECTO);
  const [maxParadas, setMaxParadas] = useState(30);
  const [juntar, setJuntar] = useState(false);
  const [gps, setGps] = useState<{ lat: number; lon: number } | null>(null);
  const [gpsEstado, setGpsEstado] = useState<string | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rutas, setRutas] = useState<Ruta[]>([]);
  const [activa, setActiva] = useState(0);
  const [actual, setActual] = useState<string | null>(null);
  const [notas, setNotas] = useState<Record<string, string>>({});
  const [marcadas, setMarcadas] = useState<Record<string, Resultado>>({});
  const [enviando, setEnviando] = useState<string | null>(null);
  const [fallo, setFallo] = useState<{ cnpj: string; resultado: Resultado } | null>(null);
  const [resumen, setResumen] = useState<Resumen | null>(null);

  const crudo = useSyncExternalStore(suscribir, leerCrudo, () => "[]");
  const guardadas = useMemo(() => parsear(crudo), [crudo]);

  const ruta = rutas[activa];
  const hechas = ruta ? ruta.paradas.filter((p) => p.hecha).length : 0;

  const siguiente = (lista: Parada[], desde?: string) => {
    const i = desde ? lista.findIndex((p) => p.cnpj === desde) : -1;
    const despues = lista.slice(i + 1).find((p) => !p.hecha) ?? lista.find((p) => !p.hecha);
    return despues ? despues.cnpj : null;
  };

  const mostrar = (nuevas: Ruta[]) => {
    setRutas(nuevas);
    setActiva(0);
    setActual(nuevas[0] ? siguiente(nuevas[0].paradas) : null);
    setFallo(null);
  };

  const pedirUbicacion = () => {
    if (!navigator.geolocation) {
      setGpsEstado("Este navegador no da la ubicación. Se usará el centro de la ciudad.");
      return;
    }
    setGpsEstado("Buscando tu ubicación...");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setGps({ lat: pos.coords.latitude, lon: pos.coords.longitude });
        setGpsEstado("Ubicación lista: la ruta empieza donde estás.");
      },
      () => setGpsEstado("No se pudo leer tu ubicación (¿permiso denegado?). Se usará el centro de la ciudad."),
      { enableHighAccuracy: true, timeout: 15000 },
    );
  };

  const generar = async () => {
    setCargando(true);
    setError(null);
    try {
      const res = await apiFetch("/api/tarjetas/ruta", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cities: elegidas, max_paradas: maxParadas, juntar, ...(gps ?? {}) }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        setError(detalle(data, "No se pudo armar la ruta."));
        return;
      }
      const nuevas = (data as { rutas: Ruta[] }).rutas;
      mostrar(nuevas);
      const ids = nuevas.map((r) => r.route_id).filter((x): x is string => !!x);
      if (ids.length) escribirGuardadas(ids);
    } catch {
      setError("Sin conexión con el servidor. Revisa tu señal e inténtalo de nuevo.");
    } finally {
      setCargando(false);
    }
  };

  const retomar = async () => {
    setCargando(true);
    setError(null);
    try {
      const resp = await Promise.all(guardadas.map((id) => apiFetch(`/api/tarjetas/ruta/${id}`)));
      const ok = await Promise.all(resp.filter((r) => r.ok).map((r) => r.json() as Promise<Ruta>));
      if (!ok.length) {
        setError("La ruta guardada ya no existe. Arma una nueva.");
        escribirGuardadas([]);
        return;
      }
      mostrar(ok);
    } catch {
      setError("Sin conexión con el servidor. Revisa tu señal e inténtalo de nuevo.");
    } finally {
      setCargando(false);
    }
  };

  const marcar = async (p: Parada, resultado: Resultado) => {
    if (!ruta) return;
    setEnviando(p.cnpj);
    setFallo(null);
    try {
      const res = await apiFetch("/api/tarjetas/entregas", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cnpj: p.cnpj,
          resultado,
          nota: notas[p.cnpj]?.trim() || null,
          route_id: ruta.route_id,
          ...(gps ?? {}),
        }),
      });
      if (!res.ok) throw new Error(String(res.status));
      const lista = ruta.paradas.map((x) => (x.cnpj === p.cnpj ? { ...x, hecha: true } : x));
      setRutas((rs) => rs.map((r, i) => (i === activa ? { ...r, paradas: lista } : r)));
      setMarcadas((m) => ({ ...m, [p.cnpj]: resultado }));
      setNotas((n) => ({ ...n, [p.cnpj]: "" }));
      const sig = siguiente(lista, p.cnpj);
      setActual(sig);
      if (sig) setTimeout(() => document.getElementById(`parada-${sig}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    } catch {
      setFallo({ cnpj: p.cnpj, resultado }); // la nota queda escrita
    } finally {
      setEnviando(null);
    }
  };

  const cargarResumen = useCallback(async () => {
    setError(null);
    setResumen(null);
    try {
      const qs = elegidas.map((c) => `cities=${encodeURIComponent(c)}`).join("&");
      const res = await apiFetch(`/api/tarjetas/resumen${qs ? `?${qs}` : ""}`);
      const data = await res.json().catch(() => null);
      if (!res.ok) setError(detalle(data, "No se pudo cargar el resumen."));
      else setResumen(data as Resumen);
    } catch {
      setError("Sin conexión con el servidor. Revisa tu señal e inténtalo de nuevo.");
    }
  }, [elegidas]);

  return (
    <main className="flex flex-col min-h-dvh px-4 py-4 lg:px-6 lg:py-6" style={{ maxWidth: "640px", margin: "0 auto", width: "100%" }}>
      <header className="mb-4">
        <h1 className="text-xl font-semibold tracking-tight" style={{ color: "var(--fg)" }}>Ruta de tarjetas</h1>
        <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
          Negocios activos que todavía no tienen tu tarjeta, en un recorrido corto.
        </p>
        <div className="flex mt-3" style={{ gap: "8px" }}>
          {(["ruta", "resumen"] as const).map((v) => (
            <button
              key={v}
              onClick={() => {
                setVista(v);
                if (v === "resumen") void cargarResumen();
              }}
              aria-pressed={vista === v}
              style={{ ...botonSecundario, flex: 1, borderColor: vista === v ? "var(--accent)" : "var(--border)", color: vista === v ? "var(--accent)" : "var(--fg)" }}
            >
              {v === "ruta" ? "Ruta" : "Resumen"}
            </button>
          ))}
        </div>
      </header>

      <section className="mb-4" style={tarjeta}>
        <fieldset>
          <legend className="text-xs mb-2" style={{ color: "var(--muted)" }}>Ciudades</legend>
          <div className="flex flex-wrap" style={{ gap: "8px" }}>
            {CIUDADES.map((c) => (
              <label key={c} className="flex items-center text-sm" style={{ gap: "8px", padding: "8px 12px", border: "1px solid var(--border)", borderRadius: "var(--radius)", minHeight: "44px" }}>
                <input
                  type="checkbox"
                  checked={elegidas.includes(c)}
                  onChange={(e) => setElegidas((s) => (e.target.checked ? [...s, c] : s.filter((x) => x !== c)))}
                  style={{ width: "20px", height: "20px", accentColor: "var(--accent)" }}
                />
                {c}
              </label>
            ))}
          </div>
        </fieldset>

        {vista === "ruta" && (
          <>
            <div className="mt-4 mb-2 flex items-center justify-between">
              <label htmlFor="max-paradas" className="text-xs" style={{ color: "var(--muted)" }}>Paradas por ruta</label>
              <span className="text-sm font-bold" style={{ color: "var(--accent)" }}>{maxParadas}</span>
            </div>
            <input
              id="max-paradas" type="range" min={1} max={80} step={1} value={maxParadas}
              onChange={(e) => setMaxParadas(Number(e.target.value))}
              style={{ width: "100%", accentColor: "var(--accent)", padding: "8px 0", touchAction: "manipulation" }}
            />
            <label className="flex items-center text-sm mt-3" style={{ gap: "8px", color: "var(--fg-secondary)" }}>
              <input type="checkbox" checked={juntar} onChange={(e) => setJuntar(e.target.checked)} style={{ width: "20px", height: "20px", accentColor: "var(--accent)" }} />
              Juntar las ciudades en una sola ruta (solo si están a menos de 25 km)
            </label>
            <button onClick={pedirUbicacion} className="mt-4" style={{ ...botonSecundario, width: "100%" }}>
              📍 Usar mi ubicación
            </button>
            {gpsEstado && <p className="text-xs mt-2" style={{ color: "var(--muted)" }}>{gpsEstado}</p>}
            <button onClick={generar} disabled={cargando || elegidas.length === 0} className="mt-4" style={botonPrincipal(cargando || elegidas.length === 0)}>
              {cargando ? "Armando la ruta..." : "Armar ruta"}
            </button>
            {guardadas.length > 0 && rutas.length === 0 && (
              <button onClick={retomar} disabled={cargando} className="mt-3" style={{ ...botonSecundario, width: "100%" }}>
                Retomar la última ruta
              </button>
            )}
          </>
        )}
        {vista === "resumen" && (
          <button onClick={cargarResumen} className="mt-4" style={{ ...botonSecundario, width: "100%" }}>Actualizar</button>
        )}
        {error && <p role="alert" className="text-sm mt-3" style={{ color: "var(--error)" }}>{error}</p>}
      </section>

      {vista === "ruta" && rutas.length > 1 && (
        <div className="flex mb-4 overflow-x-auto" style={{ gap: "8px" }}>
          {rutas.map((r, i) => (
            <button
              key={r.nombre + i}
              onClick={() => { setActiva(i); setActual(siguiente(r.paradas)); setFallo(null); }}
              aria-pressed={i === activa}
              style={{ ...botonSecundario, flexShrink: 0, borderColor: i === activa ? "var(--accent)" : "var(--border)", color: i === activa ? "var(--accent)" : "var(--fg)" }}
            >
              {r.ciudades.join(" + ")} ({r.total})
            </button>
          ))}
        </div>
      )}

      {vista === "ruta" && ruta && (
        <section>
          {ruta.aviso && (
            <p className="text-sm mb-3" style={{ ...tarjeta, color: "var(--fg-secondary)" }}>{ruta.aviso}</p>
          )}
          {ruta.paradas.length > 0 && (
            <>
              <div className="mb-3" style={{ position: "sticky", top: "48px", background: "var(--bg)", padding: "8px 0", zIndex: 10 }}>
                <p className="text-base font-semibold" style={{ color: "var(--fg)" }} aria-live="polite">
                  {hechas} de {ruta.total} {hechas === ruta.total && "· ¡Ruta terminada!"}
                </p>
                <div style={{ height: "6px", background: "var(--border)", borderRadius: "3px", marginTop: "6px" }}>
                  <div style={{ width: `${(hechas / ruta.total) * 100}%`, height: "100%", background: "var(--accent)", borderRadius: "3px" }} />
                </div>
                <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>~{ruta.distancia_km.toFixed(1)} km en línea recta</p>
              </div>

              <ol className="flex flex-col" style={{ gap: "8px" }}>
                {ruta.paradas.map((p) => {
                  const abierta = p.cnpj === actual;
                  const marcada = marcadas[p.cnpj];
                  return (
                    <li key={p.cnpj} id={`parada-${p.cnpj}`} style={{ ...tarjeta, scrollMarginTop: "120px", borderColor: abierta ? "var(--accent)" : "var(--border)", opacity: p.hecha && !abierta ? 0.6 : 1 }}>
                      <button onClick={() => { setActual(p.cnpj); setFallo(null); }} style={{ width: "100%", textAlign: "left" }} aria-expanded={abierta}>
                        <span className="text-xs" style={{ color: "var(--muted)" }}>
                          {p.orden}. {p.hecha ? `✓ ${marcada ? ETIQUETAS[marcada] : "Marcada"}` : `a ${metros(p.distancia_m)}`}
                        </span>
                        <span className="block text-base font-semibold" style={{ color: "var(--fg)" }}>{p.nombre}</span>
                        <span className="block text-sm" style={{ color: "var(--fg-secondary)" }}>
                          {p.direccion}{p.bairro ? ` · ${p.bairro}` : ""}{p.ciudad ? ` · ${p.ciudad}` : ""}
                        </span>
                      </button>
                      {abierta && (
                        <div className="mt-3 flex flex-col" style={{ gap: "8px" }}>
                          <a href={p.maps_url} target="_blank" rel="noopener noreferrer" style={{ ...botonSecundario, color: "var(--accent)" }}>
                            Abrir en Maps
                          </a>
                          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
                            {BOTONES.map(([r, label]) => (
                              <button
                                key={r}
                                onClick={() => marcar(p, r)}
                                disabled={enviando !== null}
                                style={{
                                  ...botonSecundario,
                                  minHeight: "64px",
                                  fontWeight: 600,
                                  background: r === "tarjeta_entregada" ? "var(--accent)" : "var(--bg-elevated)",
                                  color: r === "tarjeta_entregada" ? "#0f0f0f" : "var(--fg)",
                                  opacity: enviando ? 0.5 : 1,
                                }}
                              >
                                {enviando === p.cnpj ? "Guardando..." : label}
                              </button>
                            ))}
                          </div>
                          <label className="text-xs" style={{ color: "var(--muted)" }} htmlFor={`nota-${p.cnpj}`}>Nota (opcional)</label>
                          <textarea
                            id={`nota-${p.cnpj}`}
                            value={notas[p.cnpj] ?? ""}
                            maxLength={500}
                            rows={2}
                            onChange={(e) => setNotas((n) => ({ ...n, [p.cnpj]: e.target.value }))}
                            style={{ width: "100%", padding: "10px", fontSize: "16px", background: "var(--bg-elevated)", color: "var(--fg)", border: "1px solid var(--border)", borderRadius: "var(--radius)" }}
                          />
                          {fallo?.cnpj === p.cnpj && (
                            <div role="alert" className="text-sm" style={{ color: "var(--error)", background: "var(--error-dim)", padding: "10px", borderRadius: "var(--radius)" }}>
                              No se pudo guardar «{ETIQUETAS[fallo.resultado]}»: parece que no hay conexión. Tu nota sigue aquí.
                              <button onClick={() => marcar(p, fallo.resultado)} disabled={enviando !== null} style={{ ...botonSecundario, width: "100%", marginTop: "8px", color: "var(--fg)" }}>
                                Reintentar
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ol>
            </>
          )}
        </section>
      )}

      {vista === "resumen" && !resumen && !error && <StatusMessage type="loading" />}
      {vista === "resumen" && resumen && (
        <section className="flex flex-col" style={{ gap: "8px" }}>
          <div style={tarjeta}>
            <h2 className="text-sm font-semibold mb-2" style={{ color: "var(--fg)" }}>Tarjetas entregadas</h2>
            <Cifras c={resumen.totales} />
          </div>
          {resumen.ciudades.map((c) => (
            <div key={c.ciudad} style={tarjeta}>
              <h2 className="text-sm font-semibold mb-2" style={{ color: "var(--fg)" }}>{c.ciudad}</h2>
              {c.geocodificados === 0 ? (
                <p className="text-sm" style={{ color: "var(--fg-secondary)" }}>
                  Todavía no hay negocios geocodificados en {c.ciudad}: faltan por cargar y geocodificar.
                </p>
              ) : (
                <>
                  <Cifras c={c} />
                  <p className="text-xs mt-2" style={{ color: "var(--muted)" }}>
                    Quedan {c.sin_tarjeta} de {c.geocodificados} negocios sin tarjeta.
                  </p>
                  <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
                    {(Object.keys(ETIQUETAS) as Resultado[]).map((r) => `${ETIQUETAS[r]}: ${c.por_resultado[r] ?? 0}`).join(" · ")}
                  </p>
                </>
              )}
            </div>
          ))}
        </section>
      )}
    </main>
  );
}

function Cifras({ c }: { c: Conteo }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "8px", textAlign: "center" }}>
      {([["Hoy", c.hoy], ["Esta semana", c.semana], ["Total", c.total]] as const).map(([label, n]) => (
        <div key={label}>
          <p className="text-xl font-bold" style={{ color: "var(--accent)" }}>{n}</p>
          <p className="text-xs" style={{ color: "var(--muted)" }}>{label}</p>
        </div>
      ))}
    </div>
  );
}
