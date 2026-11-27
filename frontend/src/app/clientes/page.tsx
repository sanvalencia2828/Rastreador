"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import StatusMessage from "../components/StatusMessage";
import { apiFetch, friendlyError } from "../lib/auth";
import type { Cliente } from "../lib/clientes";
import { coordsDeEnlace, enParana, type Coords } from "../lib/mapsLink";

type Filtro = "todos" | "diario" | "atrasado" | "sin";
const FILTROS: { id: Filtro; label: string }[] = [
  { id: "todos", label: "Todos" },
  { id: "diario", label: "Diario" },
  { id: "atrasado", label: "Atrasado" },
  { id: "sin", label: "Sin ubicación" },
];
const cumple = (c: Cliente, f: Filtro) =>
  f === "todos" || (f === "diario" && c.visita_diaria) || (f === "atrasado" && c.atrasado) || (f === "sin" && c.lat === null);
const nombre = (c: Cliente) => c.nombre_negocio || c.nombre_cliente || "Sin nombre";

type Cambios = Partial<Pick<Cliente, "visita_diaria" | "atrasado" | "nombre_negocio" | "nota" | "lat" | "lon">>;

export default function ClientesPage() {
  const [clientes, setClientes] = useState<Cliente[] | null>(null);
  const [error, setError] = useState<string | undefined>();
  const [q, setQ] = useState("");
  const [filtro, setFiltro] = useState<Filtro>("todos");

  useEffect(() => {
    let vivo = true;
    apiFetch("/api/clientes?limit=500")
      .then(async (res) => {
        if (!res.ok) throw new Error(friendlyError(res.status) ?? "No se pudieron cargar los clientes.");
        const data: Cliente[] = await res.json();
        if (vivo) setClientes(data);
      })
      .catch((e: Error) => vivo && setError(e.message || "No se pudieron cargar los clientes."));
    return () => {
      vivo = false;
    };
  }, []);

  /** PATCH y reemplaza la fila con la respuesta; devuelve un mensaje de error o null. */
  async function guardar(id: string, cambios: Cambios): Promise<string | null> {
    try {
      const res = await apiFetch(`/api/clientes/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cambios),
      });
      if (!res.ok) return friendlyError(res.status) ?? (res.status === 422 ? "Datos no válidos." : "No se pudo guardar.");
      const fila: Cliente = await res.json();
      setClientes((prev) => prev?.map((c) => (c.id === id ? fila : c)) ?? prev);
      return null;
    } catch {
      return "Sin conexión: no se guardó.";
    }
  }

  const conteo = useMemo(() => {
    const out = { todos: 0, diario: 0, atrasado: 0, sin: 0 } as Record<Filtro, number>;
    for (const c of clientes ?? []) for (const f of FILTROS) if (cumple(c, f.id)) out[f.id]++;
    return out;
  }, [clientes]);

  const visibles = useMemo(() => {
    const t = q.trim().toLocaleLowerCase();
    return (clientes ?? []).filter(
      (c) =>
        cumple(c, filtro) &&
        (!t || [c.nombre_negocio, c.nombre_cliente, c.direccion, c.bairro, c.municipio].some((v) => v?.toLocaleLowerCase().includes(t))),
    );
  }, [clientes, q, filtro]);

  return (
    <main className="flex flex-col px-3 py-4 lg:px-5 lg:py-6" style={{ maxWidth: "820px", margin: "0 auto", width: "100%" }}>
      <header className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h1 className="text-lg lg:text-xl font-semibold tracking-tight" style={{ color: "var(--fg)" }}>Clientes</h1>
          <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>Los cambios se guardan al tocar.</p>
        </div>
        <Link href="/clientes/nuevo" className="text-xs font-medium flex-shrink-0" style={{ color: "var(--accent)", textDecoration: "none", padding: "10px 0" }}>
          + Nuevo
        </Link>
      </header>

      <input
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Buscar por nombre, dirección o ciudad"
        aria-label="Buscar clientes"
        className="w-full text-sm mb-3"
        style={{ padding: "10px 12px", minHeight: "44px", background: "var(--bg-elevated)", border: "1px solid var(--border)", borderRadius: "8px", color: "var(--fg)" }}
      />
      <div className="flex gap-2 flex-wrap mb-4" role="group" aria-label="Filtrar clientes">
        {FILTROS.map((f) => (
          <button
            key={f.id}
            onClick={() => setFiltro(f.id)}
            aria-pressed={filtro === f.id}
            className="text-xs font-medium"
            style={{
              padding: "8px 12px",
              minHeight: "36px",
              borderRadius: "999px",
              border: `1px solid ${filtro === f.id ? "var(--accent)" : "var(--border)"}`,
              background: filtro === f.id ? "var(--bg-elevated)" : "transparent",
              color: filtro === f.id ? "var(--accent)" : "var(--muted)",
            }}
          >
            {f.label} ({conteo[f.id]})
          </button>
        ))}
      </div>

      {error && <StatusMessage type="error" message={error} />}
      {!error && clientes === null && <p className="text-xs" style={{ color: "var(--muted)" }}>Cargando clientes...</p>}
      {clientes !== null && visibles.length === 0 && (
        <p className="text-sm py-6 text-center" style={{ color: "var(--muted)" }}>
          {clientes.length === 0 ? "Todavía no tenés clientes." : "Ningún cliente con ese filtro."}
        </p>
      )}

      <ul className="flex flex-col gap-3">
        {visibles.map((c) => (
          <ClienteCard key={c.id} c={c} guardar={guardar} />
        ))}
      </ul>
    </main>
  );
}

function Interruptor({ label, on, color, onTap }: { label: string; on: boolean; color: string; onTap: () => void }) {
  return (
    <button
      role="switch"
      aria-checked={on}
      onClick={onTap}
      className="inline-flex items-center gap-2 text-xs font-medium"
      style={{ minHeight: "44px", padding: "0 4px", color: on ? color : "var(--muted)" }}
    >
      <span aria-hidden style={{ width: "34px", height: "20px", borderRadius: "999px", background: on ? color : "var(--border)", position: "relative", transition: "background 0.15s" }}>
        <span style={{ position: "absolute", top: "2px", left: on ? "16px" : "2px", width: "16px", height: "16px", borderRadius: "50%", background: "#fff", transition: "left 0.15s" }} />
      </span>
      {label}
    </button>
  );
}

function ClienteCard({ c, guardar }: { c: Cliente; guardar: (id: string, cambios: Cambios) => Promise<string | null> }) {
  const [msg, setMsg] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [editando, setEditando] = useState(false);
  const [nombreEd, setNombreEd] = useState(c.nombre_negocio ?? "");
  const [notaEd, setNotaEd] = useState(c.nota ?? "");
  const [enlace, setEnlace] = useState("");
  const [gps, setGps] = useState<Coords | null>(null);

  const previa = gps ?? (enlace.trim() ? coordsDeEnlace(enlace) : null);
  const previaOk = previa !== null && enParana(previa);

  async function enviar(cambios: Cambios, despues?: () => void) {
    setOcupado(true);
    setMsg(null);
    const err = await guardar(c.id, cambios);
    setOcupado(false);
    setMsg(err);
    if (!err) despues?.();
  }

  function usarMiUbicacion() {
    setMsg(null);
    if (!navigator.geolocation) return setMsg("Este navegador no da la ubicación.");
    navigator.geolocation.getCurrentPosition(
      (p) => {
        setEnlace("");
        setGps({ lat: Number(p.coords.latitude.toFixed(6)), lon: Number(p.coords.longitude.toFixed(6)) });
      },
      () => setMsg("No se pudo obtener tu ubicación (¿permiso denegado?)."),
      { enableHighAccuracy: true, timeout: 15000 },
    );
  }

  const campo = { padding: "10px 12px", minHeight: "44px", background: "var(--bg-elevated)", border: "1px solid var(--border)", borderRadius: "8px", color: "var(--fg)" };
  const boton = { padding: "10px 14px", minHeight: "44px", borderRadius: "8px", border: "1px solid var(--border)", color: "var(--fg-secondary)", background: "var(--bg-elevated)" };

  return (
    <li style={{ background: "var(--card)", border: "1px solid var(--border)", borderLeft: `3px solid ${c.atrasado ? "#ef4444" : c.visita_diaria ? "#06b6d4" : "#3b82f6"}`, borderRadius: "var(--radius)", padding: "12px" }}>
      <div className="flex items-start justify-between gap-2">
        <div style={{ minWidth: 0 }}>
          <p className="text-sm font-medium" style={{ color: "var(--fg)", overflowWrap: "anywhere" }}>{nombre(c)}</p>
          <p className="text-xs" style={{ color: "var(--muted)", overflowWrap: "anywhere" }}>
            {[c.direccion, c.bairro, c.municipio].filter(Boolean).join(" · ") || "Sin dirección"}
          </p>
          {c.nota && !editando && <p className="text-xs mt-1" style={{ color: "var(--fg-secondary)", overflowWrap: "anywhere" }}>{c.nota}</p>}
          {c.lat === null && <p className="text-xs mt-1 font-medium" style={{ color: "#f59e0b" }}>Sin ubicación</p>}
        </div>
        <button onClick={() => setEditando((v) => !v)} className="text-xs flex-shrink-0" style={{ color: "var(--accent)", minHeight: "44px", padding: "0 6px" }} aria-expanded={editando}>
          {editando ? "Cerrar" : "Editar"}
        </button>
      </div>

      <div className="flex flex-wrap gap-x-4">
        <Interruptor label="Diario" on={c.visita_diaria} color="#06b6d4" onTap={() => !ocupado && enviar({ visita_diaria: !c.visita_diaria })} />
        <Interruptor label="Atrasado" on={c.atrasado} color="#ef4444" onTap={() => !ocupado && enviar({ atrasado: !c.atrasado })} />
      </div>

      {editando && (
        <form
          className="flex flex-col gap-2 mt-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!nombreEd.trim()) return setMsg("El nombre no puede quedar vacío.");
            enviar({ nombre_negocio: nombreEd.trim(), nota: notaEd.trim() }, () => setEditando(false));
          }}
        >
          <label className="text-xs" style={{ color: "var(--muted)" }}>
            Nombre
            <input value={nombreEd} onChange={(e) => setNombreEd(e.target.value)} maxLength={300} className="w-full text-sm mt-1" style={campo} />
          </label>
          <label className="text-xs" style={{ color: "var(--muted)" }}>
            Nota
            <textarea value={notaEd} onChange={(e) => setNotaEd(e.target.value)} maxLength={1000} rows={2} className="w-full text-sm mt-1" style={campo} />
          </label>
          <button type="submit" disabled={ocupado} className="text-xs font-medium self-start" style={{ ...boton, color: "var(--accent)" }}>
            Guardar nombre y nota
          </button>
        </form>
      )}

      {(c.lat === null || editando) && (
        <div className="flex flex-col gap-2 mt-2">
          <label className="text-xs" style={{ color: "var(--muted)" }}>
            {c.lat === null ? "Pegá un enlace de Google Maps" : "Cambiar ubicación: pegá un enlace de Google Maps"}
            <input
              value={enlace}
              onChange={(e) => {
                setGps(null);
                setEnlace(e.target.value);
              }}
              inputMode="url"
              placeholder="https://maps.google.com/?q=-23.42,-51.93"
              className="w-full text-sm mt-1"
              style={campo}
            />
          </label>
          <div className="flex flex-wrap gap-2 items-center">
            <button type="button" onClick={usarMiUbicacion} className="text-xs font-medium" style={boton}>Usar mi ubicación</button>
            {previa && (
              <button
                type="button"
                disabled={!previaOk || ocupado}
                onClick={() => enviar({ lat: previa.lat, lon: previa.lon }, () => { setEnlace(""); setGps(null); })}
                className="text-xs font-medium"
                style={{ ...boton, color: previaOk ? "var(--accent)" : "var(--muted)", opacity: previaOk ? 1 : 0.6 }}
              >
                Guardar ubicación
              </button>
            )}
          </div>
          {enlace.trim() && !previa && (
            <p className="text-xs" style={{ color: "#f59e0b" }}>
              No encuentro coordenadas. Los enlaces cortos (maps.app.goo.gl) no las traen: abrilo y copiá el enlace largo.
            </p>
          )}
          {previa && (
            <p className="text-xs" style={{ color: previaOk ? "var(--fg-secondary)" : "var(--error)" }}>
              {previa.lat.toFixed(6)}, {previa.lon.toFixed(6)}
              {previaOk ? " · " : " · fuera de Paraná: revisá el enlace · "}
              <a href={`https://www.google.com/maps?q=${previa.lat},${previa.lon}`} target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>
                ver en Maps
              </a>
            </p>
          )}
        </div>
      )}

      {msg && <p className="text-xs mt-2" role="alert" style={{ color: "var(--error)" }}>{msg}</p>}
    </li>
  );
}
