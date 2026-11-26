#!/usr/bin/env python3
"""
scripts/analizar_zonas.py
Analiza zonas visitadas (puntos compartidos desde Google Maps) con el volcado CNPJ
de la Receita Federal y, si existe, con los scores del modelo de riesgo de cierre.

Mientras los comercios no tengan coordenadas reales, una zona se define por su
barrio y su calle (obtenidos por geocodificación inversa del punto), no por radio.

Uso:
    python scripts/analizar_zonas.py                       # usa .data/zonas_visitadas.csv
    python scripts/analizar_zonas.py --zonas otra.csv --out output/zonas

Formato de .data/zonas_visitadas.csv (orden 1 = la más reciente):
    orden,lat,lon,municipio_tom,bairro,logradouro,cep_osm
    1,-23.39127,-51.9619721,7691,PARQUE DAS LARANJEIRAS,ORLANDIA,87080630

municipio_tom es el código de municipio de la Receita (Maringá 7691, Londrina 7667).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import unicodedata
from math import asin, cos, radians, sin, sqrt

import pandas as pd

COLUMNS = [
    "cnpj_basico", "cnpj_ordem", "cnpj_dv", "matriz", "nome_fantasia", "situacao",
    "data_situacao", "motivo", "cidade_exterior", "pais", "data_inicio", "cnae",
    "cnae_secundaria", "tipo_logradouro", "logradouro", "numero", "complemento", "bairro",
    "cep", "uf", "municipio", "ddd_1", "telefone_1", "ddd_2", "telefone_2", "ddd_fax",
    "fax", "email", "situacao_especial", "data_situacao_especial",
]
CLOSED = {"03", "04", "08"}
DIVISIONS = {
    "47": "Comercio minorista", "56": "Alimentación", "96": "Servicios personales",
    "45": "Vehículos", "86": "Salud", "43": "Obras/instalaciones", "41": "Construcción",
    "82": "Servicios administrativos", "73": "Publicidad", "85": "Educación", "62": "TI",
    "68": "Inmobiliario", "70": "Consultoría", "49": "Transporte", "93": "Deporte/ocio",
    "95": "Reparación", "46": "Mayorista", "10": "Industria alimentaria", "69": "Contable/jurídico",
}


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().upper()
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    text = re.sub(r"\b(JD|JARD)\b", "JARDIM", text)
    text = re.sub(r"\b(PQ|PQE|PRQ)\b", "PARQUE", text)
    text = re.sub(r"\b(VL)\b", "VILA", text)
    text = text.replace("LARANGEIRAS", "LARANJEIRAS")
    return " ".join(text.split())


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(radians, [*a, *b])
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * asin(sqrt(h))


def load_establishments(pattern: str, municipios: set[str]) -> pd.DataFrame:
    frames = []
    for path in sorted(glob.glob(pattern)):
        for chunk in pd.read_csv(path, sep=";", header=None, names=COLUMNS, dtype=str, encoding="latin-1",
                                 keep_default_na=False, chunksize=500_000):
            frames.append(chunk[chunk["municipio"].isin(municipios)])
    if not frames:
        raise SystemExit(f"No hay volcados que coincidan con {pattern}")
    df = pd.concat(frames, ignore_index=True)
    df["cnpj"] = df["cnpj_basico"] + df["cnpj_ordem"] + df["cnpj_dv"]
    df["inicio"] = pd.to_datetime(df["data_inicio"], format="%Y%m%d", errors="coerce")
    df["fecha_sit"] = pd.to_datetime(df["data_situacao"], format="%Y%m%d", errors="coerce")
    df["bairro_n"] = df["bairro"].map(norm)
    df["calle_n"] = df["logradouro"].map(norm)
    return df


def zone_stats(sub: pd.DataFrame, snapshot: pd.Timestamp) -> dict:
    t0 = snapshot - pd.DateOffset(months=12)
    active = sub[sub["situacao"] == "02"]
    alive_t0 = sub[(sub["inicio"] < t0) & (
        ((sub["situacao"] == "02") & ((sub["fecha_sit"] <= t0) | sub["fecha_sit"].isna()))
        | (sub["situacao"].isin(CLOSED) & (sub["fecha_sit"] >= t0)))]
    closures = sub[sub["situacao"].isin(CLOSED) & (sub["fecha_sit"] >= t0) & (sub["fecha_sit"] < snapshot)]
    openings = sub[(sub["inicio"] >= t0) & (sub["inicio"] < snapshot)]
    age = (snapshot - active["inicio"]).dt.days / 365.25
    rubros = active["cnae"].str[:2].map(lambda d: DIVISIONS.get(d, f"Otros ({d})")).value_counts(normalize=True)
    out = {
        "activos": len(active),
        "aperturas_12m": len(openings),
        "cierres_12m": len(closures),
        "tasa_cierre_12m": round(len(closures) / len(alive_t0), 3) if len(alive_t0) else None,
        "edad_mediana_anos": round(float(age.median()), 1) if len(active) else None,
        "rubros": rubros.head(4).round(3).to_dict(),
    }
    if "prob_cierre_12m" in sub and len(active):
        out["riesgo_medio"] = round(float(active["prob_cierre_12m"].mean()), 3)
        out["pct_riesgo_alto"] = round(float((active["decil_riesgo"] >= 9).mean()), 3)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--zonas", default=".data/zonas_visitadas.csv")
    p.add_argument("--estabelecimentos", default=".data/*ESTABELE*")
    p.add_argument("--scores", default="artifacts/latest.json", help="latest.json del pipeline ml/ (opcional)")
    p.add_argument("--out", default="output/zonas")
    args = p.parse_args()

    zonas = pd.read_csv(args.zonas, dtype={"municipio_tom": str, "cep_osm": str}).sort_values("orden")
    df = load_establishments(args.estabelecimentos, set(zonas["municipio_tom"]))
    snapshot = df["fecha_sit"].max().normalize()

    if os.path.exists(args.scores):
        run = json.load(open(args.scores, encoding="utf-8"))["path"]
        scores_path = os.path.join(os.path.dirname(args.scores), run, "predictions", "business_scores.csv.gz")
        scores = pd.read_csv(scores_path, dtype={"cnpj": str}, usecols=["cnpj", "prob_cierre_12m", "decil_riesgo"])
        df = df.merge(scores, on="cnpj", how="left")

    rows = []
    for mun, city in df.groupby("municipio"):
        rows.append({"zona": f"Ciudad (municipio {mun})", **zone_stats(city, snapshot)})
    previous = None
    for z in zonas.itertuples():
        city = df[df["municipio"] == z.municipio_tom]
        bairro, calle = norm(z.bairro), norm(z.logradouro)
        dist = round(haversine_km(previous, (z.lat, z.lon)), 2) if previous else None
        rows.append({"zona": f"Z{z.orden} barrio {bairro}", "km_desde_anterior": dist,
                     **zone_stats(city[city["bairro_n"].str.contains(bairro, regex=False)], snapshot)})
        rows.append({"zona": f"Z{z.orden} calle {calle}",
                     **zone_stats(city[city["calle_n"].str.contains(calle, regex=False)], snapshot)})
        previous = (z.lat, z.lon)

    os.makedirs(args.out, exist_ok=True)
    result = pd.DataFrame(rows)
    result.to_csv(os.path.join(args.out, "zonas.csv"), index=False)
    print(f"Volcado del {snapshot.date()} · {len(df):,} registros en los municipios de las zonas\n")
    print(result.drop(columns=["rubros"]).to_string(index=False))


if __name__ == "__main__":
    main()
