import { NextRequest, NextResponse } from "next/server";

const NOMINATIM_BASE = "https://nominatim.openstreetmap.org/search";
const USER_AGENT = "GeolocalizadorApp/1.0 (contacto@ejemplo.com)";
const TIMEOUT_MS = 8000;
const MIN_INTERVAL_MS = 1100;

let lastNominatimCall = 0;
let pendingCall: Promise<unknown[]> | null = null;

interface GeoResult {
  lat: string;
  lon: string;
  display_name: string;
  address?: Record<string, string>;
}

function extractCep(address: Record<string, string> | undefined): string | null {
  if (!address) return null;
  return address.postcode ?? address.postal_code ?? null;
}

async function callNominatim(query: string): Promise<GeoResult[]> {
  if (pendingCall) {
    return pendingCall as Promise<GeoResult[]>;
  }

  const now = Date.now();
  const wait = MIN_INTERVAL_MS - (now - lastNominatimCall);

  if (wait > 0) {
    await new Promise((r) => setTimeout(r, wait));
  }

  lastNominatimCall = Date.now();

  const url = `${NOMINATIM_BASE}?q=${query}&format=json&limit=1&addressdetails=1&countrycodes=br`;

  pendingCall = fetch(url, {
    headers: { "User-Agent": USER_AGENT },
    signal: AbortSignal.timeout(TIMEOUT_MS),
  })
    .then((res) => res.json())
    .finally(() => {
      pendingCall = null;
    });

  return pendingCall as Promise<GeoResult[]>;
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const raw = body.address;

    if (!raw || typeof raw !== "string") {
      return NextResponse.json(
        { error: "El campo 'address' es obligatorio y debe ser texto." },
        { status: 400 }
      );
    }

    const trimmed = raw.trim();
    if (trimmed.length < 5) {
      return NextResponse.json(
        { error: "La dirección debe tener al menos 5 caracteres." },
        { status: 400 }
      );
    }

    const query = encodeURIComponent(trimmed);

    let data: GeoResult[];
    try {
      data = await callNominatim(query);
    } catch (fetchError) {
      if (fetchError instanceof DOMException && fetchError.name === "TimeoutError") {
        return NextResponse.json(
          { error: "El servicio de mapas tardó demasiado. Intentá de nuevo." },
          { status: 504 }
        );
      }
      throw fetchError;
    }

    if (!Array.isArray(data) || data.length === 0) {
      return NextResponse.json(
        { error: "No se encontró la dirección. Verificá el nombre o agregá más detalles." },
        { status: 404 }
      );
    }

    const best = data[0];
    const cep = extractCep(best.address);

    return NextResponse.json({
      lat: parseFloat(best.lat),
      lon: parseFloat(best.lon),
      display_name: best.display_name,
      cep,
    });
  } catch {
    return NextResponse.json(
      { error: "Error interno del servidor. Intentá de nuevo en unos segundos." },
      { status: 500 }
    );
  }
}
