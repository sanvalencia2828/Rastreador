"""Sensibilidad de V1: ¿qué pasa si se excluyen del test las filas censuradas (códigos 03/04 posteriores al corte)?
No es una variante nueva: mismo modelo, mismas zonas; solo cambia qué filas del test se evalúan.
Uso: python scripts/diag_sensibilidad.py <run_dir> [B]   (necesita data/raw.pkl: keep_intermediate=true)
"""
import json, sys
from pathlib import Path
import pandas as pd
from ml.steps.features import prepare_base
from scripts.diag_bootstrap import bootstrap, gate_frame  # noqa: E402

run = Path(sys.argv[1]); B = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
cfg = json.load(open(run / "config.yaml.json"))
censored_codes = set(cfg["labels"].get("censored_codes", []))
if not censored_codes:
    raise SystemExit("La corrida no tiene censored_codes: no hay nada que excluir")
base = prepare_base(pd.read_pickle(run / "data" / "raw.pkl"), cfg)
t = gate_frame(run)
cutoff = pd.Timestamp(t["cutoff"].iat[0])
cens = set(base.loc[base["situacao"].isin(censored_codes) & (base["data_situacao"] >= cutoff), "cnpj"])
test = pd.read_pickle(run / "features" / "test.pkl")
train = pd.read_pickle(run / "features" / "train.pkl")
tr_cut = pd.Timestamp(train["cutoff"].iat[0])
cens_tr = set(base.loc[base["situacao"].isin(censored_codes) & (base["data_situacao"] >= tr_cut), "cnpj"])
by_code = base.set_index("cnpj")["situacao"]
is_c = t["cnpj"].isin(cens)
out = {"censored_codes": sorted(censored_codes),
       "test_total": {"filas": len(test), "censuradas": int(test["cnpj"].isin(cens).sum()),
                      "censuradas_con_etiqueta_1": int(test.loc[test["cnpj"].isin(cens), "label"].sum())},
       "train_total": {"filas": len(train), "censuradas": int(train["cnpj"].isin(cens_tr).sum())},
       "gate_set": {"filas": len(t), "censuradas": int(is_c.sum()), "por_codigo": by_code.reindex(t.loc[is_c, "cnpj"]).value_counts().to_dict()},
       "gate_set_completo": bootstrap(t, B), "gate_set_sin_censuradas": bootstrap(t[~is_c].reset_index(drop=True), B)}
print(json.dumps(out, indent=1)); json.dump(out, open(run / "evaluation" / "diag_sensibilidad_v1.json", "w"), indent=1)
