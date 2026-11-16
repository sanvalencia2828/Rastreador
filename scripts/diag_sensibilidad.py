"""Sensibilidad de V1: ¿qué pasa si se excluyen del test las filas censuradas (códigos 03/04 posteriores al corte)?
No es una variante nueva: mismo modelo, mismas zonas; solo cambia qué filas del test se evalúan.
Uso: PYTHONPATH=. python -m scripts.diag_sensibilidad <run_dir> [B]   (necesita data/raw.pkl: keep_intermediate=true)
Las censuradas DENTRO de la ventana son cierres reales etiquetados 0: "completo" subestima y "sin censuradas"
sobrestima; leer ambos como cotas, no como estimación.
"""
import json, sys
from pathlib import Path
import pandas as pd
from ml.steps.features import LABEL, prepare_base
from scripts.diag_bootstrap import bootstrap, gate_frame  # noqa: E402

run = Path(sys.argv[1]); B = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
cfg = json.load(open(run / "config.yaml.json"))
censored_codes = set(cfg["labels"].get("censored_codes", []))
if not censored_codes:
    raise SystemExit("La corrida no tiene censored_codes: no hay nada que excluir")
base = prepare_base(pd.read_pickle(run / "data" / "raw.pkl"), cfg)
t = gate_frame(run)
h = pd.DateOffset(months=int(cfg["labels"]["horizon_months"]))
cutoff = pd.Timestamp(t["cutoff"].iat[0])


def in_window(c):  # censurados que cierran dentro de [c, c+h): los que de verdad se etiquetaron 0 pese a cerrar
    return base["situacao"].isin(censored_codes) & (base["data_situacao"] >= c) & (base["data_situacao"] < c + h)


cens = set(base.loc[in_window(cutoff), "cnpj"])
test = pd.read_pickle(run / "features" / "test.pkl")
train = pd.read_pickle(run / "features" / "train.pkl")
tr_cut = pd.Timestamp(train["cutoff"].iat[0])
cens_tr = set(base.loc[in_window(tr_cut), "cnpj"])
cens_tr_fuera = set(base.loc[base["situacao"].isin(censored_codes) & (base["data_situacao"] >= tr_cut + h), "cnpj"])
by_code = base.set_index("cnpj")["situacao"]
is_c = t["cnpj"].isin(cens)
out = {"censored_codes": sorted(censored_codes),
       "test_total": {"filas": len(test), "censuradas": int(test["cnpj"].isin(cens).sum()),
                      "censuradas_con_etiqueta_1": int(test.loc[test["cnpj"].isin(cens), LABEL].sum())},
       "train_total": {"filas": len(train), "censuradas_en_ventana": int(train["cnpj"].isin(cens_tr).sum()),
                       "censuradas_despues_de_la_ventana": int(train["cnpj"].isin(cens_tr_fuera).sum())},
       "gate_set": {"filas": len(t), "censuradas": int(is_c.sum()), "por_codigo": by_code.reindex(t.loc[is_c, "cnpj"]).value_counts().to_dict()},
       "gate_set_completo": bootstrap(t, B), "gate_set_sin_censuradas": bootstrap(t[~is_c].reset_index(drop=True), B)}
print(json.dumps(out, indent=1)); json.dump(out, open(run / "evaluation" / "diag_sensibilidad_v1.json", "w"), indent=1)
