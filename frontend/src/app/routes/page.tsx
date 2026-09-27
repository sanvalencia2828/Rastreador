"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiPath } from "../lib/api";

const MapView = dynamic(() => import("../components/MapView"), { ssr: false });

type TarjetaCode = "TT" | "TS" | "TC" | "VV" | "TF" | "PT" | "VS";
type RouteStatus = "draft" | "locked" | "committed";

interface LegendItem {
  code: TarjetaCode;
  label: string;
  description: string;
}

interface CityOption {
  id: number;
  name: string;
  state?: string;
}

interface PlannerStop {
  id: string;
  seq: number;
  address: string | null;
  lat: number | null;
  lng: number | null;
  maps_url: string | null;
  visit_date: string;
  tarjeta_status: TarjetaCode;
  locked: boolean;
  distance_m: number | null;
  eta_s: number | null;
}

interface PlannerRoute {
  id: string;
  name: string;
  city_id: number;
  status: RouteStatus;
  date: string;
  vehicle_id: string | null;
  stops: PlannerStop[];
}

const FALLBACK_LEGEND: LegendItem[] = [
  { code: "TT", label: "A tarjetear", description: "Pendiente" },
  { code: "TS", label: "Sin stock", description: "Sin mercadería" },
  { code: "TC", label: "Cerrado", description: "Local cerrado" },
  { code: "VV", label: "Venta", description: "Visita con venta" },
  { code: "TF", label: "No encontrado", description: "No se encontró" },
  { code: "PT", label: "Pedido", description: "Pedido tomado" },
  { code: "VS", label: "Visitado s/venta", description: "Sin venta" },
];

const CHIP_COLOR: Record<TarjetaCode, string> = {
  TT: "#6b6b6b",
  TS: "#f59e0b",
  TC: "#ff5c5c",
  VV: "#00c9a7",
  TF: "#94a3b8",
  PT: "#60a5fa",
  VS: "#c084fc",
};

const STATUS_LABEL: Record<RouteStatus, string> = {
  draft: "Borrador",
  locked: "Bloqueada",
  committed: "Confirmada",
};

function todayInParana(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

async function readError(res: Response): Promise<string> {
  const data = await res.json().catch(() => ({}));
  if (typeof data.detail === "string") return data.detail;
  return `Error ${res.status}`;
}

export default function RoutesPage() {
  const [cities, setCities] = useState<CityOption[]>([]);
  const [cityId, setCityId] = useState<number | "">("");
  const [date, setDate] = useState(todayInParana);
  const [legend, setLegend] = useState<LegendItem[]>(FALLBACK_LEGEND);
  const [routes, setRoutes] = useState<PlannerRoute[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mapsText, setMapsText] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const selected = routes.find((route) => route.id === selectedId) || routes[0] || null;

  const loadRoutes = useCallback(async (nextCity: number, nextDate: string) => {
    const res = await fetch(apiPath(`/api/v1/routes?city_id=${nextCity}&date=${nextDate}`));
    if (!res.ok) throw new Error(await readError(res));
    const data = (await res.json()) as PlannerRoute[];
    setRoutes(data);
    setSelectedId((current) => (current && data.some((route) => route.id === current) ? current : data[0]?.id || null));
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const fromQuery = params.get("city");
    let cancelled = false;

    (async () => {
      try {
        const [cityRes, legendRes] = await Promise.all([
          fetch(apiPath("/api/cities")),
          fetch(apiPath("/api/v1/tarjeta-statuses")),
        ]);
        if (cancelled) return;
        if (legendRes.ok) setLegend(await legendRes.json());
        if (!cityRes.ok) {
          setError(await readError(cityRes));
          return;
        }
        const data = (await cityRes.json()) as CityOption[];
        setCities(data);
        const preferred = fromQuery ? Number(fromQuery) : data[0]?.id;
        if (preferred) setCityId(preferred);
      } catch {
        if (!cancelled) setError("No se pudo conectar con la API.");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (cityId === "") return;
    let cancelled = false;
    loadRoutes(Number(cityId), date).catch((err: Error) => {
      if (!cancelled) setError(err.message);
    });
    return () => {
      cancelled = true;
    };
  }, [cityId, date, loadRoutes]);

  const mapStops = useMemo(
    () =>
      (selected?.stops || [])
        .filter((stop) => stop.lat != null && stop.lng != null)
        .map((stop) => ({ id: stop.id, lat: stop.lat as number, lon: stop.lng as number })),
    [selected]
  );

  async function importMaps() {
    if (cityId === "") return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await fetch(apiPath("/api/v1/routes/import-maps"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          city_id: Number(cityId),
          date,
          visit_date: date,
          text: mapsText,
          append: true,
        }),
      });
      if (!res.ok) throw new Error(await readError(res));
      const created = (await res.json()) as PlannerRoute;
      setMapsText("");
      setMessage(`Importadas ${created.stops.length} paradas. Fecha de visita: ${date}.`);
      setSelectedId(created.id);
      await loadRoutes(Number(cityId), date);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo importar.");
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(status: RouteStatus) {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(apiPath(`/api/v1/routes/${selected.id}`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (!res.ok) throw new Error(await readError(res));
      const updated = (await res.json()) as PlannerRoute;
      setRoutes((prev) => prev.map((route) => (route.id === updated.id ? updated : route)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cambiar el estado.");
    } finally {
      setBusy(false);
    }
  }

  async function setTarjeta(stop: PlannerStop, code: TarjetaCode) {
    if (!selected) return;
    const previous = stop.tarjeta_status;
    setRoutes((prev) =>
      prev.map((route) =>
        route.id !== selected.id
          ? route
          : {
              ...route,
              stops: route.stops.map((item) => (item.id === stop.id ? { ...item, tarjeta_status: code } : item)),
            }
      )
    );
    try {
      const res = await fetch(apiPath(`/api/v1/routes/${selected.id}/stops/${stop.id}/tarjeta`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tarjeta_status: code, visit_date: stop.visit_date }),
      });
      if (!res.ok) throw new Error(await readError(res));
      const updated = (await res.json()) as PlannerStop;
      setRoutes((prev) =>
        prev.map((route) =>
          route.id !== selected.id
            ? route
            : { ...route, stops: route.stops.map((item) => (item.id === updated.id ? updated : item)) }
        )
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar el tarjeteo.");
      setRoutes((prev) =>
        prev.map((route) =>
          route.id !== selected.id
            ? route
            : {
                ...route,
                stops: route.stops.map((item) => (item.id === stop.id ? { ...item, tarjeta_status: previous } : item)),
              }
        )
      );
    }
  }

  async function saveVisitDate(stop: PlannerStop, visitDate: string) {
    if (!selected || !visitDate) return;
    const res = await fetch(apiPath(`/api/v1/routes/${selected.id}/stops/${stop.id}`), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visit_date: visitDate }),
    });
    if (!res.ok) {
      setError(await readError(res));
      return;
    }
    const updated = (await res.json()) as PlannerStop;
    setRoutes((prev) =>
      prev.map((route) =>
        route.id !== selected.id
          ? route
          : { ...route, stops: route.stops.map((item) => (item.id === updated.id ? updated : item)) }
      )
    );
  }

  return (
    <main className="px-4 py-4 lg:px-5" style={{ maxWidth: 1200, margin: "0 auto" }}>
      <header style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 650, letterSpacing: "-0.03em" }}>Rutas del día</h1>
        <p style={{ color: "var(--muted)", fontSize: 12, marginTop: 4 }}>
          Pegá los Maps de hoy. Cada parada guarda la fecha de visita y el tarjeteo.
        </p>
      </header>

      <div className="planner">
        <section className="flex flex-col gap-3">
          <div className="planner-card" style={{ display: "grid", gridTemplateColumns: "1.4fr 0.8fr", gap: 10 }}>
            <label>
              <span className="planner-label">Ciudad</span>
              <select
                value={cityId}
                onChange={(event) => setCityId(event.target.value ? Number(event.target.value) : "")}
              >
                {cities.length === 0 && <option value="">Sin ciudades</option>}
                {cities.map((city) => (
                  <option key={city.id} value={city.id}>
                    {city.name}
                    {city.state ? ` · ${city.state}` : ""}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className="planner-label">Día del planner</span>
              <input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
            </label>
          </div>

          <div className="planner-card">
            <label className="planner-label" htmlFor="maps-paste">
              Links de Google Maps
            </label>
            <textarea
              id="maps-paste"
              value={mapsText}
              onChange={(event) => setMapsText(event.target.value)}
              placeholder={"Un link por línea.\nhttps://www.google.com/maps/place/Rua+Sergipe,+Londrina/@-23.311,-51.162,17z"}
            />
            <p style={{ color: "var(--muted)", fontSize: 11, margin: "8px 0 10px" }}>
              Los links cortos se guardan para abrirlos. Para lat/lng, pegá el link largo de compartir. No se rastrea GPS.
            </p>
            <button
              onClick={importMaps}
              disabled={busy || cityId === "" || !mapsText.trim()}
              style={{
                background: "var(--accent)",
                color: "#0f0f0f",
                borderRadius: 8,
                padding: "8px 12px",
                fontSize: 13,
                fontWeight: 700,
                opacity: busy || cityId === "" || !mapsText.trim() ? 0.5 : 1,
              }}
            >
              {busy ? "Importando..." : "Importar Maps de hoy"}
            </button>
          </div>

          <div style={{ height: 280, minHeight: 280 }}>
            <MapView stops={mapStops} businesses={[]} center={mapStops[0] ? { lat: mapStops[0].lat, lon: mapStops[0].lon } : undefined} />
          </div>
        </section>

        <aside className="flex flex-col gap-3">
          {error && (
            <p className="planner-card" style={{ color: "var(--error)", fontSize: 12 }}>
              {error}
            </p>
          )}
          {message && (
            <p className="planner-card" style={{ color: "var(--accent)", fontSize: 12 }}>
              {message}
            </p>
          )}

          <div className="planner-card">
            <p className="planner-label">Rutas de {date}</p>
            {routes.length === 0 && <p style={{ fontSize: 12, color: "var(--muted)" }}>Todavía no hay ruta para este día.</p>}
            <div className="flex flex-col gap-2">
              {routes.map((route) => (
                <button
                  key={route.id}
                  onClick={() => setSelectedId(route.id)}
                  style={{
                    textAlign: "left",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    padding: "8px 10px",
                    background: selected?.id === route.id ? "var(--bg-elevated)" : "transparent",
                  }}
                >
                  <span style={{ display: "block", fontSize: 13, fontWeight: 650 }}>{route.name}</span>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>
                    {STATUS_LABEL[route.status] || route.status} · {route.stops.length} paradas
                  </span>
                </button>
              ))}
            </div>
          </div>

          {selected && (
            <div className="planner-card flex flex-col gap-3">
              <div className="chip-row">
                {(Object.keys(STATUS_LABEL) as RouteStatus[]).map((status) => (
                  <button
                    key={status}
                    className="chip"
                    data-on={selected.status === status}
                    style={{ background: selected.status === status ? "var(--accent)" : "transparent" }}
                    onClick={() => setStatus(status)}
                    disabled={busy}
                  >
                    {STATUS_LABEL[status]}
                  </button>
                ))}
              </div>
              {selected.stops.map((stop) => (
                <article key={stop.id} style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <p style={{ fontSize: 13, fontWeight: 650 }}>
                      {stop.seq}. {stop.address || "Sin dirección"}
                    </p>
                    {stop.maps_url && (
                      <a href={stop.maps_url} target="_blank" rel="noreferrer" style={{ color: "var(--accent)", fontSize: 11 }}>
                        Maps
                      </a>
                    )}
                  </div>
                  <label style={{ display: "block", margin: "8px 0" }}>
                    <span className="planner-label">Fecha de visita</span>
                    <input
                      type="date"
                      value={stop.visit_date}
                      onChange={(event) => {
                        const visitDate = event.target.value;
                        setRoutes((prev) =>
                          prev.map((route) =>
                            route.id !== selected.id
                              ? route
                              : {
                                  ...route,
                                  stops: route.stops.map((item) =>
                                    item.id === stop.id ? { ...item, visit_date: visitDate } : item
                                  ),
                                }
                          )
                        );
                      }}
                      onBlur={(event) => saveVisitDate(stop, event.target.value)}
                    />
                  </label>
                  <div className="chip-row">
                    {legend.map((item) => (
                      <button
                        key={item.code}
                        className="chip"
                        title={item.description}
                        data-on={stop.tarjeta_status === item.code}
                        style={{
                          background: stop.tarjeta_status === item.code ? CHIP_COLOR[item.code] : "transparent",
                          color: stop.tarjeta_status === item.code ? "#0f0f0f" : "var(--fg-secondary)",
                        }}
                        onClick={() => setTarjeta(stop, item.code)}
                      >
                        {item.code} {item.label}
                      </button>
                    ))}
                  </div>
                  {(stop.distance_m != null || stop.eta_s != null) && (
                    <p style={{ fontSize: 11, color: "var(--muted)", marginTop: 6 }}>
                      {stop.distance_m != null ? `${stop.distance_m} m` : ""}
                      {stop.eta_s != null ? ` · ${Math.round(stop.eta_s / 60)} min` : ""}
                    </p>
                  )}
                </article>
              ))}
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}
