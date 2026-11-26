// "Clientes del día" en este navegador: la ruta generada y los ids visitados, una entrada por fecha.
// Sin dependencias (lo prueba tests/visitados.test.mjs con node --test). Todo acceso va con try/catch:
// modo privado o almacenamiento lleno solo hace que no se recuerde.

export const PREFIJO = "rastreador:clientes-dia:";

export interface Dia {
  ruta: unknown;
  visitados: string[];
}

const VACIO: Dia = { ruta: null, visitados: [] };
const oyentes = new Set<() => void>();
const memoria = new Map<string, string>(); // respaldo si localStorage falla: dura hasta recargar

/** Fecha local del dispositivo, YYYY-MM-DD. */
export function hoy(d: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function suscribir(cb: () => void): () => void {
  oyentes.add(cb);
  return () => {
    oyentes.delete(cb);
  };
}

/** Texto guardado para la fecha ("" si no hay): snapshot estable para useSyncExternalStore. */
export function leerCrudo(fecha: string): string {
  const enMemoria = memoria.get(fecha); // lo último escrito en esta carga, aunque setItem haya fallado
  if (enMemoria !== undefined) return enMemoria;
  try {
    return localStorage.getItem(PREFIJO + fecha) ?? "";
  } catch {
    return "";
  }
}

export function parsear(raw: string): Dia {
  try {
    const v = JSON.parse(raw);
    const visitados = Array.isArray(v?.visitados) ? v.visitados.filter((x: unknown) => typeof x === "string") : [];
    return { ruta: v?.ruta ?? null, visitados };
  } catch {
    return VACIO;
  }
}

function escribir(fecha: string, dia: Dia) {
  const raw = JSON.stringify(dia);
  memoria.clear();
  memoria.set(fecha, raw);
  try {
    // los días anteriores se borran: no acumular datos de clientes en el dispositivo
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i);
      if (k?.startsWith(PREFIJO) && k !== PREFIJO + fecha) localStorage.removeItem(k);
    }
    localStorage.setItem(PREFIJO + fecha, raw);
  } catch {
    /* sin almacenamiento: no se recuerda al recargar */
  }
  oyentes.forEach((cb) => cb());
}

/** Guarda la ruta del día; conserva los visitados (regenerar no desmarca a nadie). */
export function guardarRuta(fecha: string, ruta: unknown) {
  escribir(fecha, { ...parsear(leerCrudo(fecha)), ruta });
}

export function alternarVisitado(fecha: string, id: string) {
  const dia = parsear(leerCrudo(fecha));
  const visitados = dia.visitados.includes(id) ? dia.visitados.filter((x) => x !== id) : [...dia.visitados, id];
  escribir(fecha, { ...dia, visitados });
}
