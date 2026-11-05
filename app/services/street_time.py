"""Tiempo por calle: estimación (SUPUESTOS marcados) y, cuando hay datos, medias reales de visitas."""

import os
from typing import Any, Dict, List, Optional, Tuple

# SUPUESTOS por defecto: configurables por variable de entorno y por petición.
WALK_SPEED_KMH = float(os.getenv("RASTREADOR_WALK_SPEED_KMH", "4"))
MIN_PER_LOCAL = float(os.getenv("RASTREADOR_MIN_PER_LOCAL", "2"))
N_MIN_REAL = int(os.getenv("RASTREADOR_STREET_TIME_MIN_N", "3"))  # registros reales para pasar de estimado a real
MIN_COMERCIOS_VISIBLES = 3  # por debajo no se muestra el conteo exacto ("<3")
PAREADO_MAX_PCT = 20  # >= esto: calzada doble contada dos veces, longitud poco fiable hasta corregirla


def supuestos(speed_kmh: float, min_per_local: float) -> Dict[str, Any]:
    default = speed_kmh == WALK_SPEED_KMH and min_per_local == MIN_PER_LOCAL
    return {"velocidad_kmh": speed_kmh, "min_por_local": min_per_local,
            "origen": "default" if default else "usuario", "estimado": True}


def estimate_minutes(length_m: float, n_comercios: int, speed_kmh: float, min_per_local: float) -> float:
    """Tiempo de calle = longitud / velocidad a pie + minutos por local."""
    return length_m / (speed_kmh * 1000 / 60) + min_per_local * n_comercios


def no_estimate_reason(estado: str, n_comercios: int, pareado_pct: Optional[int]) -> Optional[str]:
    """Por qué NO se da un tiempo estimado (None = se puede estimar)."""
    if estado == "calle_larga":
        return "calle larga: estimación poco fiable"
    if estado != "ok":
        return f"estado {estado}: fuera del plan automático"
    if n_comercios < MIN_COMERCIOS_VISIBLES:
        return "menos de 3 comercios"
    if (pareado_pct or 0) >= PAREADO_MAX_PCT:
        return "longitud poco fiable (calzada doble contada dos veces), pendiente de corrección"
    return None


def merge_catalog_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fusiona filas de catálogo que comparten la misma calle OSM (varias grafías del volcado)."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(r["osm_key"], []).append(r)
    out = []
    for osm_key, g in groups.items():
        main = max(g, key=lambda r: r["n_comercios_activos"])
        nums_min = [r["numero_min"] for r in g if r["numero_min"] is not None]
        nums_max = [r["numero_max"] for r in g if r["numero_max"] is not None]
        estados = {r["estado"] for r in g}
        out.append({
            **main,
            "osm_key": osm_key,
            "street_keys": sorted(r["street_key"] for r in g),
            "n_comercios_activos": sum(r["n_comercios_activos"] for r in g),
            "numero_min": min(nums_min) if nums_min else None,
            "numero_max": max(nums_max) if nums_max else None,
            "ceps": sorted({c for r in g for c in (r["ceps"] or [])}),
            "estado": "ambigua" if "ambigua" in estados else "calle_larga" if "calle_larga" in estados else main["estado"],
            "dist_m": min(r["dist_m"] for r in g),
        })
    return out


def street_view(
    merged: Dict[str, Any], speed_kmh: float, min_per_local: float,
    real: Optional[Dict[str, Tuple[int, float]]] = None,
) -> Dict[str, Any]:
    """Una calle lista para la respuesta: sin nombres de negocios, sin contacto; conteo "<3" si hay pocos."""
    n = merged["n_comercios_activos"]
    few = n < MIN_COMERCIOS_VISIBLES
    reason = no_estimate_reason(merged["estado"], n, merged.get("pareado_pct"))
    est = None if reason or merged.get("length_m") is None else round(
        estimate_minutes(merged["length_m"], n, speed_kmh, min_per_local), 1)
    n_real, med = max((real or {}).get(k, (0, 0.0)) for k in merged["street_keys"])
    view = {
        "calle": f"{merged['tipo'] or ''} {merged['nombre']}".strip(),
        "comercios_activos": "<3" if few else n,
        "numero_min": None if few else merged["numero_min"],
        "numero_max": None if few else merged["numero_max"],
        "ceps": merged["ceps"],
        "distancia_m": int(round(merged["dist_m"] / 10.0)) * 10,
        "length_m": merged.get("length_m"),
        "estado": merged["estado"],
        "en_plan_automatico": merged["estado"] == "ok" and not few and reason is None,
        "tiempo_estimado_min": est,
        "tiempo_real_min": round(med / 60.0, 1) if n_real else None,
        "n_real": n_real,
    }
    view["tiempo_usado"] = "real" if n_real >= N_MIN_REAL else ("estimado" if est is not None else None)
    view["tiempo_min"] = view["tiempo_real_min"] if view["tiempo_usado"] == "real" else est
    if reason and view["tiempo_usado"] != "real":
        view["tiempo_motivo"] = reason
    return view
