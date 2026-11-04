"""Tests del pipeline de ML con datos sintéticos (no requieren el volcado real)."""

from __future__ import annotations

import copy
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from ml.core import load_config, read_json
from ml.pipeline import execute
from ml.steps.features import FEATURES, ID_COLS, LABEL, check_features, cohort_masks
from ml.steps.ingest import load_contract
from ml.steps.validate import check_frame

SNAPSHOT = date(2023, 8, 12)
CNAES = ["4781400", "5611201", "4712100", "9602501", "4520001", "8599604", "4744099", "5620104"]
MUNIS = ["7667", "7445", "7493", "7535", "7885"]


def _d(x: date) -> str:
    return x.strftime("%Y%m%d")


def synthetic_rows(n: int = 6000, seed: int = 7) -> list[list[str]]:
    """Filas con el layout de 30 columnas de la Receita y una señal real (edad y CNAE)."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        start = date(2010, 1, 1) + timedelta(days=rng.randint(0, (SNAPSHOT - date(2010, 1, 1)).days - 30))
        cnae = rng.choice(CNAES)
        age_years = (SNAPSHOT - start).days / 365.25
        risk = 0.06 + (0.25 if age_years < 3 else 0.0) + (0.15 if cnae in CNAES[:2] else 0.0)
        if rng.random() < risk * 2.5:
            closed_on = start + timedelta(days=rng.randint(1, max(1, (SNAPSHOT - start).days)))
            sit, data_sit, motivo = rng.choice(["08", "08", "04"]), _d(closed_on), "01"
        else:
            sit, data_sit, motivo = "02", _d(start), "00"
        cep5 = f"{86000 + rng.randint(0, 49):05d}"
        email = rng.choice(["", f"loja{i}@gmail.com", f"contato@empresa{i}.com.br"])
        rows.append(
            [
                f"{10000000 + i:08d}", "0001", f"{i % 100:02d}", "1", f"LOJA {i}", sit, data_sit, motivo,
                "", "", _d(start), cnae, rng.choice(["", "4789099,4751201"]), "RUA", "PRINCIPAL",
                str(rng.randint(1, 3000)), rng.choice(["", "SALA 1"]), "CENTRO", f"{cep5}{rng.randint(0, 999):03d}",
                "PR", rng.choice(MUNIS), "43", "33334444", "", "", "", "", email, "", "",
            ]
        )
    return rows


def write_raw(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="latin-1") as f:
        for r in rows:
            f.write(";".join(f'"{v}"' for v in r) + "\n")


@pytest.fixture
def cfg(tmp_path: Path) -> dict:
    c = load_config()
    c = copy.deepcopy(c)
    c["data"]["input_glob"] = str(tmp_path / "raw" / "*ESTABELE*")
    c["run"]["artifacts_dir"] = str(tmp_path / "artifacts")
    c["validation"]["min_rows"] = 200
    c["model"]["max_iter"] = 60
    c["features"]["smoothing_m"] = 5
    return c


def raw_file(tmp_path: Path) -> Path:
    return tmp_path / "raw" / "TEST.ESTABELE"


def latest_run(cfg: dict) -> str | None:
    p = Path(cfg["run"]["artifacts_dir"]) / "latest.json"
    return read_json(p)["run_id"] if p.exists() else None


# ------------------------------------------------------------------------------
def test_full_run_writes_artifacts_and_promotes_latest(cfg, tmp_path):
    write_raw(raw_file(tmp_path), synthetic_rows())
    assert execute(cfg, run_id="r1") == 0
    root = Path(cfg["run"]["artifacts_dir"]) / "runs" / "r1"
    for rel in [
        "manifest.json",
        "validation/raw_report.json",
        "validation/features_report.json",
        "model/production.joblib",
        "model/backtest.joblib",
        "evaluation/metrics.json",
        "evaluation/report.md",
        "predictions/business_scores.csv.gz",
        "logs/pipeline.log",
    ]:
        assert (root / rel).exists(), rel
    assert not (root / "data" / "raw.pkl").exists()  # intermedio borrado por defecto
    manifest = read_json(root / "manifest.json")
    assert manifest["status"] == "succeeded"
    assert all(s["status"] == "ok" for s in manifest["steps"].values())
    assert manifest["inputs"][0]["bytes"] > 0
    assert latest_run(cfg) == "r1"
    scores = pd.read_csv(root / "predictions" / "business_scores.csv.gz", dtype={"cnpj": str})
    assert scores["prob_cierre_12m"].between(0, 1).all()


@pytest.mark.parametrize(
    "mutation",
    ["extra_column", "missing_column", "swapped_columns", "unknown_status", "bad_dates"],
)
def test_schema_change_stops_pipeline(cfg, tmp_path, mutation):
    rows = synthetic_rows(n=1500)
    if mutation == "extra_column":
        rows = [r + ["X"] for r in rows]
    elif mutation == "missing_column":
        rows = [r[:-1] for r in rows]
    elif mutation == "swapped_columns":  # uf ↔ municipio
        rows = [r[:19] + [r[20], r[19]] + r[21:] for r in rows]
    elif mutation == "unknown_status":
        rows = [r[:5] + ["09" if i % 10 == 0 else r[5]] + r[6:] for i, r in enumerate(rows)]
    elif mutation == "bad_dates":
        rows = [r[:10] + ["2023-01-05"] + r[11:] for r in rows]
    write_raw(raw_file(tmp_path), rows)

    code = execute(cfg, run_id=f"bad_{mutation}")
    assert code == 2
    root = Path(cfg["run"]["artifacts_dir"]) / "runs" / f"bad_{mutation}"
    manifest = read_json(root / "manifest.json")
    assert manifest["status"] == "invalid_data"
    assert manifest["failed_step"] in {"ingest", "validate"}
    assert read_json(root / "validation" / "raw_report.json")["status"] == "failed"
    assert not (root / "model").exists()  # nunca llegó a entrenar
    assert latest_run(cfg) is None


def test_failed_run_keeps_previous_latest(cfg, tmp_path):
    write_raw(raw_file(tmp_path), synthetic_rows())
    assert execute(cfg, run_id="good") == 0
    write_raw(raw_file(tmp_path), [r + ["X"] for r in synthetic_rows()])
    assert execute(cfg, run_id="broken") == 2
    assert latest_run(cfg) == "good"


def test_quality_gate_rejects_without_promoting(cfg, tmp_path):
    write_raw(raw_file(tmp_path), synthetic_rows())
    cfg["evaluation"]["min_roc_auc"] = 0.999
    assert execute(cfg, run_id="weak") == 3
    root = Path(cfg["run"]["artifacts_dir"]) / "runs" / "weak"
    assert read_json(root / "manifest.json")["status"] == "rejected"
    assert (root / "evaluation" / "metrics.json").exists()  # las métricas quedan para diagnóstico
    assert latest_run(cfg) is None


def test_steps_can_run_separately_and_resume(cfg, tmp_path):
    write_raw(raw_file(tmp_path), synthetic_rows())
    assert execute(cfg, run_id="split", steps=["ingest", "validate", "features"]) == 0
    root = Path(cfg["run"]["artifacts_dir"]) / "runs" / "split"
    assert read_json(root / "manifest.json")["status"] == "partial"
    assert latest_run(cfg) is None
    assert execute(cfg, run_id="split", steps=["train", "evaluate", "predict"]) == 0
    assert read_json(root / "manifest.json")["status"] == "succeeded"
    assert latest_run(cfg) == "split"


def test_step_without_inputs_fails_cleanly(cfg, tmp_path):
    write_raw(raw_file(tmp_path), synthetic_rows(n=300))
    assert execute(cfg, run_id="orphan", steps=["train"]) == 1


def test_lock_blocks_concurrent_run(cfg, tmp_path):
    write_raw(raw_file(tmp_path), synthetic_rows(n=300))
    lock = Path(cfg["run"]["artifacts_dir"]) / ".pipeline.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("otra-corrida")
    assert execute(cfg, run_id="blocked") == 4


def test_retention_keeps_last_successful_runs(cfg, tmp_path):
    write_raw(raw_file(tmp_path), synthetic_rows(n=2500))
    cfg["run"]["keep_runs"] = 2
    for rid in ["a1", "a2", "a3"]:
        assert execute(cfg, run_id=rid) == 0
    runs = sorted(p.name for p in (Path(cfg["run"]["artifacts_dir"]) / "runs").iterdir())
    assert runs == ["a2", "a3"]


def test_contract_accepts_valid_frame(cfg):
    contract = load_contract(cfg)
    names = [c["name"] for c in contract["columns"]]
    df = pd.DataFrame(synthetic_rows(n=500), columns=names)
    report = check_frame(df, contract, min_rows=100)
    assert report["status"] == "passed", report["errors"]


def test_contract_flags_shifted_null_rate(cfg):
    contract = load_contract(cfg)
    names = [c["name"] for c in contract["columns"]]
    df = pd.DataFrame(synthetic_rows(n=500), columns=names)
    df["cep"] = ""
    report = check_frame(df, contract, min_rows=100)
    assert report["status"] == "failed"
    assert any(e.startswith("cep:") for e in report["errors"])


def test_feature_contract_detects_missing_feature(cfg):
    df = pd.DataFrame({c: [0] for c in ID_COLS + [LABEL] + FEATURES})
    assert check_features(df.drop(columns=["idade_anos"]), "x", cfg, labelled=False)


def test_scheduler_skips_when_no_new_data(cfg, tmp_path):
    write_raw(raw_file(tmp_path), synthetic_rows())
    assert execute(cfg, run_id="first") == 0
    assert execute(cfg, skip_if_unchanged=True) == 0
    runs = [p.name for p in (Path(cfg["run"]["artifacts_dir"]) / "runs").iterdir()]
    assert runs == ["first"]  # no se creó otra corrida
    write_raw(raw_file(tmp_path), synthetic_rows(seed=99))  # llega un volcado nuevo
    assert execute(cfg, skip_if_unchanged=True) == 0
    assert len(list((Path(cfg["run"]["artifacts_dir"]) / "runs").iterdir())) == 2


def _labels_cfg(cfg, closed, censored):
    c = copy.deepcopy(cfg)
    c["labels"]["closed_codes"] = closed
    c["labels"]["censored_codes"] = censored
    return c


def test_censored_codes_stay_in_population_as_negatives(cfg):
    base = pd.DataFrame(
        {
            "situacao": ["02", "08", "04", "04"],  # activo, baixada en ventana, inapta en ventana, inapta antes del corte
            "data_situacao": pd.to_datetime(["2020-01-01", "2024-06-01", "2024-07-01", "2023-06-01"]),
            "data_inicio": pd.to_datetime(["2019-01-01"] * 4),
        }
    )
    cut, end = pd.Timestamp("2024-01-01"), pd.Timestamp("2025-01-01")

    def run(closed, censored):
        pop, lab = cohort_masks(base, cut, end, _labels_cfg(cfg, closed, censored))
        return pop.tolist(), lab.tolist()

    # por defecto (sin censored_codes) el comportamiento es el de siempre: 04 cuenta como cierre
    assert run(["03", "04", "08"], []) == ([True, True, True, False], [False, True, True, False])
    # solo-08 con 04 censurado: el inapta sigue en la población con etiqueta 0
    assert run(["08"], ["03", "04"]) == ([True, True, True, False], [False, True, False, False])
    # sin censurar, el inapta desaparecería de la población (sesgo de supervivencia)
    assert run(["08"], []) == ([True, True, False, False], [False, True, False, False])


def test_censored_codes_must_not_overlap_closed_codes(cfg):
    base = pd.DataFrame({"situacao": ["02"], "data_situacao": pd.to_datetime(["2020-01-01"]), "data_inicio": pd.to_datetime(["2019-01-01"])})
    with pytest.raises(ValueError):
        cohort_masks(base, pd.Timestamp("2024-01-01"), pd.Timestamp("2025-01-01"), _labels_cfg(cfg, ["04", "08"], ["04"]))


def test_censored_after_horizon_is_in_population_with_label_zero(cfg):
    base = pd.DataFrame({"situacao": ["04"], "data_situacao": pd.to_datetime(["2026-05-01"]), "data_inicio": pd.to_datetime(["2019-01-01"])})
    pop, lab = cohort_masks(base, pd.Timestamp("2024-01-01"), pd.Timestamp("2025-01-01"), _labels_cfg(cfg, ["08"], ["03", "04"]))
    assert pop.tolist() == [True] and lab.tolist() == [False]
