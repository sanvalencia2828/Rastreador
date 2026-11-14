"""Paso 4 · train: entrena el modelo de backtest y el modelo de producción.

* backtest   → cohorte `train` (corte T1) sin las zonas reservadas; se evalúa en `test`.
* production → cohorte `test` (corte T0, la más reciente con etiqueta completa);
               es el que puntúa a los comercios activos hoy en el paso `predict`.

Ambos comparten hiperparámetros, así que la métrica del backtest estima la calidad
del modelo de producción un año hacia adelante.
"""

from __future__ import annotations

import hashlib

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from ml.core import Run, log, write_json
from ml.steps.features import CATEGORICAL_FEATURES, FEATURES, LABEL, NUMERIC_FEATURES


def holdout_mask(cep5: pd.Series, fraction: float, seed: int) -> pd.Series:
    """Asignación determinista de zonas (CEP5) al hold-out espacial, estable entre corridas."""

    def bucket(z: str) -> float:
        h = hashlib.md5(f"{seed}:{z}".encode()).hexdigest()
        return int(h[:8], 16) / 0xFFFFFFFF

    buckets = {z: bucket(z) for z in cep5.unique()}
    return cep5.map(buckets) < fraction


def build_model(cfg: dict) -> Pipeline:
    m = cfg["model"]
    encoder = OrdinalEncoder(
        handle_unknown="use_encoded_value",
        unknown_value=np.nan,
        encoded_missing_value=np.nan,
        max_categories=int(m["ordinal_max_categories"]),
        min_frequency=int(m["ordinal_min_frequency"]),
    )
    pre = ColumnTransformer(
        [("cat", encoder, CATEGORICAL_FEATURES), ("num", "passthrough", NUMERIC_FEATURES)],
        verbose_feature_names_out=False,
    )
    n_cat = len(CATEGORICAL_FEATURES)
    clf = HistGradientBoostingClassifier(
        learning_rate=float(m["learning_rate"]),
        max_iter=int(m["max_iter"]),
        max_leaf_nodes=int(m["max_leaf_nodes"]),
        min_samples_leaf=int(m["min_samples_leaf"]),
        l2_regularization=float(m["l2_regularization"]),
        early_stopping=bool(m["early_stopping"]),
        validation_fraction=float(m["validation_fraction"]),
        categorical_features=list(range(n_cat)),
        random_state=int(m["random_state"]),
    )
    return Pipeline([("pre", pre), ("clf", clf)])


def fit(cfg: dict, df: pd.DataFrame) -> Pipeline:
    model = build_model(cfg)
    model.fit(df[FEATURES], df[LABEL].to_numpy())
    return model


def run(run: Run) -> dict:
    run.require("features/train.pkl", "features/test.pkl")
    cfg = run.cfg
    train = pd.read_pickle(run.root / "features" / "train.pkl")
    test = pd.read_pickle(run.root / "features" / "test.pkl")

    hold = holdout_mask(train["cep5"], float(cfg["split"]["holdout_cep5_fraction"]), int(cfg["split"]["seed"]))
    train_fit = train[~hold]
    log.info(
        "Backtest: %s filas de entrenamiento (%s reservadas en zonas hold-out)",
        f"{len(train_fit):,}",
        f"{int(hold.sum()):,}",
    )
    backtest = fit(cfg, train_fit)
    log.info("Backtest: %d iteraciones", backtest.named_steps["clf"].n_iter_)

    log.info("Producción: %s filas (corte %s)", f"{len(test):,}", test["cutoff"].iat[0])
    production = fit(cfg, test)
    log.info("Producción: %d iteraciones", production.named_steps["clf"].n_iter_)

    holdout_zones = sorted(train.loc[hold, "cep5"].unique().tolist())
    joblib.dump(backtest, run.path("model", "backtest.joblib"))
    joblib.dump(production, run.path("model", "production.joblib"))
    write_json(
        run.path("model", "model_card.json"),
        {
            "task": f"P(cierre/inactivación en {cfg['labels']['horizon_months']} meses)",
            "closed_codes": cfg["labels"]["closed_codes"],
            "algorithm": "sklearn HistGradientBoostingClassifier",
            "features": {"numeric": NUMERIC_FEATURES, "categorical": CATEGORICAL_FEATURES},
            "hyperparameters": cfg["model"],
            "backtest": {
                "cutoff": train["cutoff"].iat[0],
                "rows": len(train_fit),
                "positives": int(train_fit[LABEL].sum()),
                "n_iter": int(backtest.named_steps["clf"].n_iter_),
                "holdout_cep5_zones": len(holdout_zones),
            },
            "production": {
                "cutoff": test["cutoff"].iat[0],
                "rows": len(test),
                "positives": int(test[LABEL].sum()),
                "n_iter": int(production.named_steps["clf"].n_iter_),
            },
        },
    )
    write_json(run.path("model", "holdout_cep5.json"), holdout_zones)
    return {"backtest": "model/backtest.joblib", "production": "model/production.joblib"}
