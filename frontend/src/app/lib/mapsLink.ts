// Coordenadas pegadas desde Google Maps: ?q=lat,lon · @lat,lon · !3dLAT!4dLON · "lat, lon" suelto.
// Sin dependencias (lo prueba tests/mapsLink.test.mjs con node --test).

export interface Coords {
  lat: number;
  lon: number;
}

// Igual que el PATCH del backend (app/schemas/cliente.py): Paraná aproximado.
export const PR_LAT = [-24.5, -22.5] as const;
export const PR_LON = [-53.5, -50.5] as const;

const NUM = String.raw`(-?\d{1,3}(?:\.\d+)?)`;
const PATRONES = [
  new RegExp(String.raw`!3d${NUM}!4d${NUM}`), // el punto exacto del lugar: gana sobre @ (que es el centro de la vista)
  new RegExp(String.raw`[?&](?:q|query|ll|destination)=${NUM},\s*${NUM}`, "i"),
  new RegExp(String.raw`@${NUM},${NUM}`),
  new RegExp(String.raw`^\s*${NUM}\s*,\s*${NUM}\s*$`),
];

/** Primer par lat,lon reconocible en el texto, o null. No valida la región (ver enParana). */
export function coordsDeEnlace(texto: string): Coords | null {
  let t = texto.trim();
  try {
    t = decodeURIComponent(t);
  } catch {
    /* texto con % sueltos: se usa tal cual */
  }
  for (const re of PATRONES) {
    const m = t.match(re);
    if (m) {
      const lat = Number(m[1]);
      const lon = Number(m[2]);
      if (Number.isFinite(lat) && Number.isFinite(lon)) return { lat, lon };
    }
  }
  return null;
}

export function enParana({ lat, lon }: Coords): boolean {
  return lat >= PR_LAT[0] && lat <= PR_LAT[1] && lon >= PR_LON[0] && lon <= PR_LON[1];
}
