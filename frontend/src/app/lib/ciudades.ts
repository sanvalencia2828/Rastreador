// Mismas ciudades y centros que cities.py (tests/test_ciudades_front.py los compara).
export const CIUDADES = [
  { name: "Maringá", lat: -23.4205, lon: -51.933 },
  { name: "Apucarana", lat: -23.5521, lon: -51.4614 },
  { name: "Arapongas", lat: -23.4194, lon: -51.4244 },
  { name: "Marialva", lat: -23.4855, lon: -51.7927 },
  { name: "Mandaguari", lat: -23.5478, lon: -51.6708 },
  { name: "Jandaia do Sul", lat: -23.6064, lon: -51.6447 },
] as const;

/** Ciudad con el centro más cercano; aproximación plana, suficiente para preseleccionar en el formulario. */
export function ciudadCercana(lat: number, lon: number): string {
  const k = Math.cos((lat * Math.PI) / 180);
  let best: string = CIUDADES[0].name;
  let bestD = Infinity;
  for (const c of CIUDADES) {
    const d = (c.lat - lat) ** 2 + ((c.lon - lon) * k) ** 2;
    if (d < bestD) { bestD = d; best = c.name; }
  }
  return best;
}
