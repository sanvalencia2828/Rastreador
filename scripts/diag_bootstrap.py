"""Diagnóstico A2: bootstrap pareado sobre el conjunto del gate (zonas no vistas, fuera de tiempo).
Informa; no cambia el criterio. Uso: python scripts/diag_bootstrap.py <run_dir> [B]
"""
import json, sys
from pathlib import Path
import joblib, numpy as np, pandas as pd
from sklearn.metrics import average_precision_score as ap
from ml.steps.features import FEATURES, LABEL


def gate_frame(run: Path) -> pd.DataFrame:
    """Filas del gate (fuera de tiempo, zonas no vistas) con la probabilidad del modelo de backtest."""
    model = joblib.load(run / "model" / "backtest.joblib")
    test = pd.read_pickle(run / "features" / "test.pkl")
    hold = set(json.load(open(run / "model" / "holdout_cep5.json")))
    t = test[test["cep5"].isin(hold)].reset_index(drop=True)
    t["p"] = model.predict_proba(t[FEATURES])[:, 1]
    return t


def bootstrap(t: pd.DataFrame, B: int) -> dict:
    y = t[LABEL].to_numpy(); p = t["p"].to_numpy(); h = t["taxa_fechamento_prev_cnae"].to_numpy()
    n = len(y); rng = np.random.default_rng(0)
    groups = pd.Series(np.arange(n)).groupby(t["cep5"].to_numpy()).apply(lambda s: s.to_numpy()).tolist()

    def stats(idx):
        yy = y[idx]
        if yy.sum() == 0:  # sin positivos no hay PR-AUC: se descarta el remuestreo
            return None
        m = ap(yy, p[idx]); he = ap(yy, h[idx])
        return m - he, m / yy.mean(), m, he

    def ci(a): return [round(float(v), 4) for v in np.percentile(a, [2.5, 50, 97.5])]
    def block(a): return {"delta_pr_auc_IC95": ci(a[:, 0]), "ratio_IC95": ci(a[:, 1]),
                          "P(delta<=0)": round(float((a[:, 0] <= 0).mean()), 4), "P(ratio<1.5)": round(float((a[:, 1] < 1.5).mean()), 4)}
    names = ["delta_pr_auc", "pr_auc_sobre_prevalencia", "pr_auc_modelo", "pr_auc_heuristica"]
    rows = np.array([r for r in (stats(rng.integers(0, n, n)) for _ in range(B)) if r is not None])
    cl = np.array([r for r in (stats(np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])) for _ in range(B)) if r is not None])
    return {"rows": n, "positives": int(y.sum()), "prevalence": round(float(y.mean()), 4), "B": B, "descartados": [B - len(rows), B - len(cl)], "zonas_cep5": len(groups),
            "puntual": dict(zip(names, (round(float(v), 4) for v in stats(np.arange(n))))),
            "bootstrap_filas": block(rows), "bootstrap_por_zona_(complementario)": block(cl)}


if __name__ == "__main__":
    run = Path(sys.argv[1]); B = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
    res = bootstrap(gate_frame(run), B)
    print(json.dumps(res, indent=1)); json.dump(res, open(run / "evaluation" / "diag_bootstrap.json", "w"), indent=1)
