"""Paso 5 · evaluate: mide el modelo de backtest fuera de tiempo y aplica el gate de calidad."""

from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

from ml.core import QualityGateError, Run, log, read_json, write_json
from ml.steps.features import FEATURES, LABEL


def top_k_metrics(y: np.ndarray, score: np.ndarray, frac: float) -> dict:
    k = max(1, int(round(len(y) * frac)))
    idx = np.argsort(-score, kind="stable")[:k]
    hits = y[idx].sum()
    prevalence = y.mean()
    precision = hits / k
    return {
        "k": k,
        "precision": round(float(precision), 4),
        "recall": round(float(hits / max(y.sum(), 1)), 4),
        "lift": round(float(precision / prevalence), 3) if prevalence else None,
    }


def metrics(y: np.ndarray, p: np.ndarray, heuristic: np.ndarray, top_frac: float) -> dict:
    prevalence = float(y.mean())
    return {
        "rows": int(len(y)),
        "positives": int(y.sum()),
        "prevalence": round(prevalence, 4),
        "pr_auc": round(float(average_precision_score(y, p)), 4),
        "roc_auc": round(float(roc_auc_score(y, p)), 4),
        "brier": round(float(brier_score_loss(y, p)), 5),
        "log_loss": round(float(log_loss(y, np.clip(p, 1e-6, 1 - 1e-6))), 5),
        "pr_auc_lift": round(float(average_precision_score(y, p)) / prevalence, 3) if prevalence else None,
        "heuristic_pr_auc": round(float(average_precision_score(y, heuristic)), 4),
        "heuristic_roc_auc": round(float(roc_auc_score(y, heuristic)), 4),
        f"top_{int(top_frac * 100)}pct": top_k_metrics(y, p, top_frac),
    }


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> pd.DataFrame:
    df = pd.DataFrame({"y": y, "p": p})
    df["decil"] = pd.qcut(df["p"].rank(method="first"), bins, labels=list(range(1, bins + 1)))
    return (
        df.groupby("decil", observed=True)
        .agg(filas=("y", "size"), prob_media=("p", "mean"), tasa_real=("y", "mean"))
        .reset_index()
        .round(4)
    )


def gate(m: dict, cfg: dict) -> list[str]:
    ev = cfg["evaluation"]
    failures = []
    if m["roc_auc"] < float(ev["min_roc_auc"]):
        failures.append(f"ROC-AUC {m['roc_auc']} < {ev['min_roc_auc']}")
    if m["pr_auc_lift"] is None or m["pr_auc_lift"] < float(ev["min_pr_auc_lift"]):
        failures.append(f"PR-AUC/prevalencia {m['pr_auc_lift']} < {ev['min_pr_auc_lift']}")
    if ev.get("must_beat_heuristic", True) and m["pr_auc"] <= m["heuristic_pr_auc"]:
        failures.append(f"PR-AUC {m['pr_auc']} no supera la heurística por CNAE ({m['heuristic_pr_auc']})")
    return failures


def run(run: Run) -> dict:
    run.require("model/backtest.joblib", "features/test.pkl", "model/holdout_cep5.json")
    cfg = run.cfg
    top_frac = float(cfg["evaluation"]["top_k_fraction"])
    model = joblib.load(run.root / "model" / "backtest.joblib")
    test = pd.read_pickle(run.root / "features" / "test.pkl")
    holdout = set(read_json(run.root / "model" / "holdout_cep5.json"))

    y = test[LABEL].to_numpy()
    p = model.predict_proba(test[FEATURES])[:, 1]
    heuristic = test["taxa_fechamento_prev_cnae"].to_numpy()
    unseen = test["cep5"].isin(holdout).to_numpy()

    card = read_json(run.root / "model" / "model_card.json")
    results = {
        "train_cutoff": card["backtest"]["cutoff"],
        "test_cutoff": test["cutoff"].iat[0],
        "horizon_months": int(cfg["labels"]["horizon_months"]),
        "out_of_time": metrics(y, p, heuristic, top_frac),
        "out_of_time_unseen_zones": metrics(y[unseen], p[unseen], heuristic[unseen], top_frac),
    }
    primary = results["out_of_time_unseen_zones"]
    failures = gate(primary, cfg)
    results["gate"] = {"evaluated_on": "out_of_time_unseen_zones", "passed": not failures, "failures": failures}

    # importancia por permutación (muestra para que sea rápida)
    sample = test.sample(n=min(20000, len(test)), random_state=0)
    imp = permutation_importance(
        model, sample[FEATURES], sample[LABEL], scoring="average_precision", n_repeats=3, random_state=0, n_jobs=1
    )
    importance = (
        pd.DataFrame({"feature": FEATURES, "importance": imp.importances_mean, "std": imp.importances_std})
        .sort_values("importance", ascending=False)
        .round(5)
    )
    importance.to_csv(run.path("evaluation", "feature_importance.csv"), index=False)
    calib = calibration_table(y, p)
    calib.to_csv(run.path("evaluation", "calibration_deciles.csv"), index=False)
    write_json(run.path("evaluation", "metrics.json"), results)
    write_report(run, results, importance, calib)

    run.manifest["metrics"] = {
        "pr_auc": primary["pr_auc"],
        "roc_auc": primary["roc_auc"],
        "prevalence": primary["prevalence"],
        "heuristic_pr_auc": primary["heuristic_pr_auc"],
    }
    log.info(
        "Fuera de tiempo + zonas nuevas: PR-AUC=%.3f (heurística %.3f, prevalencia %.3f) ROC-AUC=%.3f",
        primary["pr_auc"],
        primary["heuristic_pr_auc"],
        primary["prevalence"],
        primary["roc_auc"],
    )
    if failures:
        raise QualityGateError("; ".join(failures))
    return {"metrics": "evaluation/metrics.json", "report": "evaluation/report.md"}


def write_report(run: Run, results: dict, importance: pd.DataFrame, calib: pd.DataFrame) -> None:
    def row(name: str, m: dict) -> str:
        top = next(v for k, v in m.items() if k.startswith("top_"))
        return (
            f"| {name} | {m['rows']:,} | {m['prevalence']:.3f} | **{m['pr_auc']:.3f}** | {m['heuristic_pr_auc']:.3f} "
            f"| {m['roc_auc']:.3f} | {top['precision']:.3f} | {top['lift']} |"
        )

    g = results["gate"]
    lines = [
        f"# Evaluación · corrida {run.run_id}",
        "",
        f"Modelo de backtest entrenado con corte **{results['train_cutoff']}** y evaluado sobre la cohorte "
        f"con corte **{results['test_cutoff']}** (etiquetas de los {results['horizon_months']} meses siguientes). "
        "La fila «zonas no vistas» usa solo CEP5 que el modelo nunca vio al entrenar: es la métrica del gate.",
        "",
        "| Conjunto | Filas | Prevalencia | PR-AUC | PR-AUC heurística CNAE | ROC-AUC | Precisión top 10% | Lift top 10% |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        row("Fuera de tiempo", results["out_of_time"]),
        row("Fuera de tiempo + zonas no vistas", results["out_of_time_unseen_zones"]),
        "",
        f"**Gate de calidad:** {'✅ superado' if g['passed'] else '❌ rechazado — ' + '; '.join(g['failures'])}",
        "",
        "## Variables más importantes (permutación, Δ PR-AUC)",
        "",
        "| Variable | Importancia |",
        "|---|---:|",
        *[f"| {r.feature} | {r.importance:.4f} |" for r in importance.head(12).itertuples()],
        "",
        "## Calibración por decil de riesgo",
        "",
        "| Decil | Filas | Prob. media | Tasa real |",
        "|---:|---:|---:|---:|",
        *[f"| {r.decil} | {r.filas:,} | {r.prob_media:.3f} | {r.tasa_real:.3f} |" for r in calib.itertuples()],
        "",
    ]
    run.path("evaluation", "report.md").write_text("\n".join(lines), encoding="utf-8")
