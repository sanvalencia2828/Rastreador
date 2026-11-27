// Clientes propios (GET /api/clientes, solo con sesión) para pintarlos en los mapas de lojas.
import { authHeaders, getToken } from "./auth";
export { mismaCiudad } from "./ciudades";

export interface Cliente {
  id: string;
  nombre_negocio: string | null;
  nombre_cliente: string | null;
  direccion: string | null;
  bairro: string | null;
  municipio: string | null;
  lat: number | null;
  lon: number | null;
  geocode_status: string;
  nota: string | null;
  visita_diaria: boolean;
  atrasado: boolean;
}

/** [] sin sesión o si falla: los mapas públicos siguen funcionando sin clientes. */
export async function cargarClientes(): Promise<Cliente[]> {
  if (!getToken()) return [];
  try {
    const res = await fetch("/api/clientes?limit=500", { headers: authHeaders() });
    return res.ok ? await res.json() : [];
  } catch {
    return [];
  }
}

/** Pines para MapView: solo los que tienen coordenadas. */
export function pinesClientes(clientes: Cliente[]) {
  return clientes
    .filter((c) => c.lat !== null && c.lon !== null)
    .map((c) => ({
      lat: c.lat as number,
      lon: c.lon as number,
      nome_fantasia: c.nombre_negocio || c.nombre_cliente || "Cliente",
      distance_m: 0,
      origen: "cliente" as const,
      visita_diaria: c.visita_diaria,
      atrasado: c.atrasado,
    }));
}
