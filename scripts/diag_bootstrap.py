"""Diagnóstico A2: bootstrap pareado sobre el conjunto del gate (zonas no vistas, fuera de tiempo).
Informa; no cambia el criterio. Uso: python scripts/diag_bootstrap.py <run_dir> [B]
"""
import json, sys
from pathlib import Path
import joblib, numpy as np, pandas as pd
from sklearn.metrics import average_precision_score as ap
from ml.steps.features import FEATURES, LABEL

run = Path(sys.argv[1]); B = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
model = joblib.load(run / "model" / "backtest.joblib")
test = pd.read_pickle(run / "features" / "test.pkl")
hold = set(json.load(open(run / "model" / "holdout_cep5.json")))
t = test[test["cep5"].isin(hold)].reset_index(drop=True)
y = t[LABEL].to_numpy(); p = model.predict_proba(t[FEATURES])[:, 1]; h = t["taxa_fechamento_prev_cnae"].to_numpy()
n = len(y); rng = np.random.default_rng(0)
cep = t["cep5"].to_numpy(); groups = pd.Series(np.arange(n)).groupby(cep).apply(lambda s: s.to_numpy()).tolist()

def stats(idx):
    yy = y[idx]; prev = yy.mean(); m = ap(yy, p[idx]); he = ap(yy, h[idx])
    return m - he, m / prev, m, he

def ci(a): return [round(float(v), 4) for v in np.percentile(a, [2.5, 50, 97.5])]
res = {"rows": n, "positives": int(y.sum()), "B": B, "zonas_cep5": len(groups),
       "puntual": dict(zip(["delta_pr_auc", "pr_auc_sobre_prevalencia", "pr_auc_modelo", "pr_auc_heuristica"], map(lambda v: round(float(v), 4), stats(np.arange(n)))))}
rows = np.array([stats(rng.integers(0, n, n)) for _ in range(B)])
res["bootstrap_filas"] = {"delta_pr_auc_IC95": ci(rows[:, 0]), "ratio_IC95": ci(rows[:, 1]),
                          "P(delta<=0)": round(float((rows[:, 0] <= 0).mean()), 4), "P(ratio<1.5)": round(float((rows[:, 1] < 1.5).mean()), 4)}
cl = np.array([stats(np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])) for _ in range(B)])
res["bootstrap_por_zona_(complementario)"] = {"delta_pr_auc_IC95": ci(cl[:, 0]), "ratio_IC95": ci(cl[:, 1]),
                          "P(delta<=0)": round(float((cl[:, 0] <= 0).mean()), 4), "P(ratio<1.5)": round(float((cl[:, 1] < 1.5).mean()), 4)}
print(json.dumps(res, indent=1)); json.dump(res, open(run / "evaluation" / "diag_bootstrap.json", "w"), indent=1)
