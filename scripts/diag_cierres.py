"""Diagnóstico A1: cierres por mes y código de situación (sin descargar nada).
Uso: python scripts/diag_cierres.py <run_dir>
"""
import json, sys
from pathlib import Path
import pandas as pd
from ml.steps.features import prepare_base, cohort_masks
from ml.core import load_config  # noqa

run = Path(sys.argv[1])
cfg = json.load(open(run / "config.yaml.json"))
raw = pd.read_pickle(run / "data" / "raw.pkl")
base = prepare_base(raw, cfg)
S = pd.Timestamp("2026-09-13")
cuts = {"train": pd.Timestamp("2024-09-13"), "test": pd.Timestamp("2025-09-13")}
off = pd.DateOffset(months=12)
out = {}
for name, c in cuts.items():
    pop, lab = cohort_masks(base, c, c + off, cfg)
    out[name] = {"cohorte": int(pop.sum()), "cierres_etiqueta": int((pop & lab).sum()),
                 "prevalencia": round(float((pop & lab).sum() / pop.sum()), 4),
                 "por_codigo": (base.loc[pop & lab, "situacao"].value_counts().sort_index().to_dict())}
    print(name, out[name])
# cierres por mes y código, sobre toda la población "abierta antes de fin de test" (cierres vigentes en el volcado)
closed = base[base["situacao"].isin(["03", "04", "08"])].copy()
closed["mes"] = closed["data_situacao"].dt.to_period("M")
tab = closed[(closed["data_situacao"] >= "2023-09-13") & (closed["data_situacao"] < S)].pivot_table(
    index="mes", columns="situacao", values="cnpj", aggfunc="count", fill_value=0)
tab["total"] = tab.sum(axis=1)
print(tab.to_string())
tab.to_csv(run / "evaluation" / "diag_cierres_mes_codigo.csv")
json.dump(out, open(run / "evaluation" / "diag_cierres_ventanas.json", "w"), indent=1)
