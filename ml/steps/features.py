"""Paso 3 · features: arma las cohortes con etiqueta temporal y sus variables.

Con un único volcado se puede reconstruir el pasado porque cada fila trae la fecha
de su última situación cadastral. Para una fecha de corte C y un horizonte h:

    población(C) = abiertos antes de C que seguían activos en C
                   (activos hoy con situación anterior a C, o cerrados en C o después)
    etiqueta(C)  = 1 si la situación pasó a cerrada en [C, C + h)

Se construyen tres cohortes (S = fecha del volcado):

    train    corte T1 = S − 2h   (etiquetas observadas en [T1, T0))
    test     corte T0 = S − h    (etiquetas observadas en [T0, S)) → validación fuera de tiempo
    scoring  corte S             (sin etiqueta; lo que se predice para los próximos h meses)

Todas las variables usan solo información anterior a la fecha de corte.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.core import Run, SchemaValidationError, log, write_json

ID_COLS = ["cnpj", "municipio", "cep5", "cnae_fiscal_principal", "cutoff"]
LABEL = "label"

NUMERIC_FEATURES = [
    "idade_anos",
    "n_cnae_secundarias",
    "es_matriz",
    "tem_nome_fantasia",
    "tem_email",
    "tem_telefone",
    "tem_telefone2",
    "tem_fax",
    "tem_complemento",
    "numero_sn",
    "n_ativos_cep8",
    "n_ativos_cep5",
    "n_mesmo_cnae_cep5",
    "n_mesma_divisao_cep5",
    "share_divisao_cep5",
    "aberturas_prev_cep5",
    "n_ativos_cnae_uf",
    "n_ativos_municipio",
    "taxa_fechamento_prev_cep5",
    "taxa_fechamento_prev_cnae",
    "taxa_fechamento_prev_municipio",
]
CATEGORICAL_FEATURES = ["cnae_divisao", "email_tipo", "tipo_logradouro_cat", "municipio_cat"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


# ------------------------------------------------------------------------------
# Preparación de columnas base (una vez por corrida)
# ------------------------------------------------------------------------------
def prepare_base(raw: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    fcfg = cfg["features"]
    df = pd.DataFrame(index=raw.index)
    df["cnpj"] = raw["cnpj_basico"] + raw["cnpj_ordem"] + raw["cnpj_dv"]
    df["situacao"] = raw["situacao_cadastral"]
    df["data_situacao"] = pd.to_datetime(raw["data_situacao_cadastral"], format="%Y%m%d", errors="coerce")
    df["data_inicio"] = pd.to_datetime(raw["data_inicio_atividade"], format="%Y%m%d", errors="coerce")
    df["cnae_fiscal_principal"] = raw["cnae_fiscal_principal"]
    df["cnae_divisao"] = raw["cnae_fiscal_principal"].str[:2]
    sec = raw["cnae_fiscal_secundaria"].str.strip()
    df["n_cnae_secundarias"] = np.where(sec.eq(""), 0, sec.str.count(",") + 1).astype("int32")
    df["es_matriz"] = (raw["identificador_matriz_filial"] == "1").astype("int8")
    df["tem_nome_fantasia"] = raw["nome_fantasia"].str.strip().ne("").astype("int8")
    email = raw["correio_eletronico"].str.strip().str.lower()
    df["tem_email"] = email.ne("").astype("int8")
    domain = email.str.extract(r"@([^@\s]+)$", expand=False).fillna("")
    free = set(fcfg.get("free_email_domains", []))
    accountant = set(fcfg.get("accountant_email_domains", []))
    df["email_tipo"] = np.select(
        [email.eq(""), domain.isin(accountant), domain.isin(free)],
        ["sin_email", "contador", "gratuito"],
        default="propio",
    )
    df["tem_telefone"] = raw["telefone_1"].str.strip().ne("").astype("int8")
    df["tem_telefone2"] = raw["telefone_2"].str.strip().ne("").astype("int8")
    df["tem_fax"] = raw["fax"].str.strip().ne("").astype("int8")
    df["tem_complemento"] = raw["complemento"].str.strip().ne("").astype("int8")
    numero = raw["numero"].str.strip().str.upper()
    df["numero_sn"] = numero.isin(["", "S/N", "SN", "S N", "0", "SEM NUMERO", "SN."]).astype("int8")
    tipo = raw["tipo_logradouro"].str.strip().str.upper().str.replace(r"^\d+A\s+", "", regex=True)
    df["tipo_logradouro_cat"] = tipo.replace("", "SEM_TIPO")
    df["municipio"] = raw["municipio"]
    df["municipio_cat"] = "m" + raw["municipio"]
    cep = raw["cep"].str.strip()
    df["cep8"] = cep.where(cep.str.len() == 8, "")
    df["cep5"] = df["cep8"].str[:5]
    return df


# ------------------------------------------------------------------------------
# Cohortes
# ------------------------------------------------------------------------------
def cohort_masks(
    base: pd.DataFrame, cutoff: pd.Timestamp, horizon_end: pd.Timestamp, cfg: dict, only_active: bool = False
):
    active = cfg["labels"]["active_code"]
    closed = set(cfg["labels"]["closed_codes"])
    started = base["data_inicio"] < cutoff
    is_active = base["situacao"].eq(active)
    is_closed = base["situacao"].isin(closed)
    active_at_cutoff = is_active & (base["data_situacao"].isna() | (base["data_situacao"] <= cutoff))
    closed_after = is_closed & (base["data_situacao"] >= cutoff)
    # en la cohorte de scoring (corte = fecha del volcado) solo interesan los activos hoy
    population = started & (active_at_cutoff if only_active else (active_at_cutoff | closed_after))
    label = is_closed & (base["data_situacao"] >= cutoff) & (base["data_situacao"] < horizon_end)
    return population, label


def _smoothed_rate(events: pd.Series, exposure: pd.Series, prior: float, m: float) -> pd.Series:
    return (events + m * prior) / (exposure + m)


def build_cohort(
    base: pd.DataFrame, cutoff: pd.Timestamp, horizon: pd.DateOffset, cfg: dict, only_active: bool = False
) -> pd.DataFrame:
    m = float(cfg["features"]["smoothing_m"])
    closed = set(cfg["labels"]["closed_codes"])
    population, label = cohort_masks(base, cutoff, cutoff + horizon, cfg, only_active=only_active)
    pop = base[population].copy()
    pop["cutoff"] = cutoff.date().isoformat()
    pop[LABEL] = label[population].astype("int8")
    pop["idade_anos"] = ((cutoff - pop["data_inicio"]).dt.days / 365.25).astype("float32")

    # densidad de establecimientos activos en la fecha de corte
    def count_by(keys: list[str], name: str) -> None:
        counts = pop.groupby(keys, observed=True)["cnpj"].transform("size")
        pop[name] = counts.astype("int32")

    count_by(["cep8"], "n_ativos_cep8")
    count_by(["cep5"], "n_ativos_cep5")
    count_by(["cep5", "cnae_fiscal_principal"], "n_mesmo_cnae_cep5")
    count_by(["cep5", "cnae_divisao"], "n_mesma_divisao_cep5")
    count_by(["cnae_fiscal_principal"], "n_ativos_cnae_uf")
    count_by(["municipio"], "n_ativos_municipio")
    no_cep = pop["cep8"].eq("")
    pop.loc[no_cep, ["n_ativos_cep8", "n_ativos_cep5", "n_mesmo_cnae_cep5", "n_mesma_divisao_cep5"]] = 0
    pop["share_divisao_cep5"] = (pop["n_mesma_divisao_cep5"] / pop["n_ativos_cep5"].replace(0, np.nan)).fillna(0).astype("float32")

    # dinámica del período anterior [cutoff − h, cutoff): aperturas y tasas de cierre
    prev_start = cutoff - horizon
    closed_prev = base["situacao"].isin(closed) & (base["data_situacao"] >= prev_start) & (base["data_situacao"] < cutoff)
    opened_prev = (base["data_inicio"] >= prev_start) & (base["data_inicio"] < cutoff)

    openings = base[opened_prev].groupby("cep5").size()
    pop["aberturas_prev_cep5"] = pop["cep5"].map(openings).fillna(0).astype("int32")
    pop.loc[no_cep, "aberturas_prev_cep5"] = 0

    closures = base[closed_prev]
    exposure_total = len(pop) + len(closures)
    prior = len(closures) / exposure_total if exposure_total else 0.0
    for key, name in [
        ("cep5", "taxa_fechamento_prev_cep5"),
        ("cnae_fiscal_principal", "taxa_fechamento_prev_cnae"),
        ("municipio", "taxa_fechamento_prev_municipio"),
    ]:
        ev = closures.groupby(key).size()
        alive = pop.groupby(key).size()
        events = pop[key].map(ev).fillna(0)
        exposure = pop[key].map(alive).fillna(0) + events
        pop[name] = _smoothed_rate(events, exposure, prior, m).astype("float32")

    cols = ID_COLS + [LABEL] + FEATURES
    return pop[cols].reset_index(drop=True)


# ------------------------------------------------------------------------------
# Contrato de la tabla de features (protege train ↔ predict)
# ------------------------------------------------------------------------------
def check_features(df: pd.DataFrame, name: str, cfg: dict, labelled: bool) -> list[str]:
    errors = []
    expected = ID_COLS + [LABEL] + FEATURES
    if list(df.columns) != expected:
        errors.append(f"{name}: columnas {list(df.columns)} ≠ esperadas {expected}")
        return errors
    if len(df) < int(cfg["validation"]["min_rows"]):
        errors.append(f"{name}: {len(df)} filas, menos que min_rows")
    for col in NUMERIC_FEATURES:
        if not pd.api.types.is_numeric_dtype(df[col]):
            errors.append(f"{name}.{col}: dtype {df[col].dtype} no numérico")
        elif df[col].isna().any():
            errors.append(f"{name}.{col}: {int(df[col].isna().sum())} nulos")
        elif (df[col] < 0).any():
            errors.append(f"{name}.{col}: valores negativos")
    if df["cnpj"].duplicated().any():
        errors.append(f"{name}: CNPJ duplicados")
    if labelled:
        prev = float(df[LABEL].mean()) if len(df) else 0.0
        lo, hi = cfg["validation"]["min_label_prevalence"], cfg["validation"]["max_label_prevalence"]
        if not lo <= prev <= hi:
            errors.append(f"{name}: prevalencia de la etiqueta {prev:.3f} fuera de [{lo}, {hi}]")
    return errors


def snapshot_date(base: pd.DataFrame, cfg: dict) -> pd.Timestamp:
    forced = cfg["data"].get("snapshot_date")
    if forced:
        return pd.Timestamp(str(forced))
    return base["data_situacao"].max().normalize()


def run(run: Run) -> dict:
    run.require("data/raw.pkl", "validation/raw_report.json")
    cfg = run.cfg
    raw = pd.read_pickle(run.root / "data" / "raw.pkl")
    base = prepare_base(raw, cfg)
    S = snapshot_date(base, cfg)
    h = pd.DateOffset(months=int(cfg["labels"]["horizon_months"]))
    T0 = S - h
    T1 = T0 - h
    log.info("Fecha del volcado S=%s · cortes T1=%s T0=%s", S.date(), T1.date(), T0.date())

    cohorts = {
        "train": build_cohort(base, T1, h, cfg),
        "test": build_cohort(base, T0, h, cfg),
        "scoring": build_cohort(base, S, h, cfg, only_active=True),
    }
    errors = []
    summary = {"snapshot_date": S.date().isoformat(), "cutoffs": {"train": T1.date().isoformat(), "test": T0.date().isoformat(), "scoring": S.date().isoformat()}, "cohorts": {}}
    for name, df in cohorts.items():
        labelled = name != "scoring"
        errors += check_features(df, name, cfg, labelled)
        summary["cohorts"][name] = {
            "rows": len(df),
            "prevalence": round(float(df[LABEL].mean()), 4) if labelled else None,
        }
        df.to_pickle(run.path("features", f"{name}.pkl"))
        log.info("Cohorte %-7s filas=%s prevalencia=%s", name, f"{len(df):,}", summary["cohorts"][name]["prevalence"])

    summary["errors"] = errors
    summary["features"] = {"numeric": NUMERIC_FEATURES, "categorical": CATEGORICAL_FEATURES}
    write_json(run.path("validation", "features_report.json"), summary)
    if errors:
        raise SchemaValidationError("; ".join(errors))
    run.manifest["snapshot_date"] = summary["snapshot_date"]
    return {"cohorts": summary["cohorts"], "snapshot_date": summary["snapshot_date"]}
