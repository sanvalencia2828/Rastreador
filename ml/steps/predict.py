"""Paso 6 · predict: puntúa a los comercios activos en la fecha del volcado."""

from __future__ import annotations

import joblib
import pandas as pd

from ml.core import Run, log
from ml.steps.features import FEATURES


def run(run: Run) -> dict:
    run.require("model/production.joblib", "features/scoring.pkl")
    model = joblib.load(run.root / "model" / "production.joblib")
    scoring = pd.read_pickle(run.root / "features" / "scoring.pkl")
    prob = model.predict_proba(scoring[FEATURES])[:, 1]
    out = pd.DataFrame(
        {
            "cnpj": scoring["cnpj"],
            "municipio": scoring["municipio"],
            "cep5": scoring["cep5"],
            "cnae_fiscal_principal": scoring["cnae_fiscal_principal"],
            "snapshot_date": scoring["cutoff"],
            "prob_cierre_12m": prob.round(5),
        }
    )
    out["decil_riesgo"] = pd.qcut(out["prob_cierre_12m"].rank(method="first"), 10, labels=list(range(1, 11))).astype(int)
    out = out.sort_values("prob_cierre_12m", ascending=False)
    path = run.path("predictions", "business_scores.csv.gz")
    out.to_csv(path, index=False, compression="gzip")
    log.info("Puntuados %s comercios activos · prob. media %.3f", f"{len(out):,}", out["prob_cierre_12m"].mean())
    return {"scores": "predictions/business_scores.csv.gz", "rows": len(out)}
