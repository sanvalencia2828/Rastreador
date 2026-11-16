"""Paso 1 · ingest: lee los volcados crudos de la Receita y guarda las filas de la UF."""

from __future__ import annotations

import csv
import glob
from pathlib import Path

import pandas as pd
import yaml

from ml.core import Run, SchemaValidationError, file_fingerprint, log, resolve, write_json


def load_contract(cfg: dict) -> dict:
    with open(resolve(cfg["data"]["contract"]), encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_inputs(cfg: dict) -> list[Path]:
    pattern = str(resolve(cfg["data"]["input_glob"]))
    files = sorted(Path(p) for p in glob.glob(pattern) if not p.endswith((".tmp", ".zip")))
    if not files:
        raise SchemaValidationError(f"No se encontró ningún archivo que coincida con {pattern}")
    return files


def peek_column_count(path: Path, delimiter: str, encoding: str, n_lines: int = 200) -> set[int]:
    """Cuenta columnas en las primeras líneas para fallar rápido antes de leer GBs."""
    counts: set[int] = set()
    with open(path, encoding=encoding, newline="") as f:
        reader = csv.reader(f, delimiter=delimiter, quotechar='"')
        for i, row in enumerate(reader):
            counts.add(len(row))
            if i >= n_lines:
                break
    return counts


def run(run: Run) -> dict:
    cfg = run.cfg
    contract = load_contract(cfg)
    names = [c["name"] for c in contract["columns"]]
    if len(names) != contract["n_columns"]:
        raise SchemaValidationError("El contrato es inconsistente: n_columns no coincide con columns")

    delimiter = contract["delimiter"]
    encoding = cfg["data"]["encoding"]
    uf = cfg["data"]["uf"]
    uf_idx = names.index("uf")

    inputs = find_inputs(cfg)
    fingerprints = []
    frames = []
    total_read = 0
    for path in inputs:
        counts = peek_column_count(path, delimiter, encoding)
        if counts != {contract["n_columns"]}:
            raise SchemaValidationError(
                f"{path.name}: se esperaban {contract['n_columns']} columnas y se encontraron {sorted(counts)}"
            )
        log.info("Leyendo %s (%.0f MB)…", path.name, path.stat().st_size / 1e6)
        try:
            reader = pd.read_csv(
                path,
                sep=delimiter,
                header=None,
                dtype=str,
                encoding=encoding,
                keep_default_na=False,
                na_filter=False,
                quotechar='"',
                chunksize=int(cfg["data"]["chunksize"]),
            )
            for chunk in reader:
                if chunk.shape[1] != contract["n_columns"]:
                    raise SchemaValidationError(
                        f"{path.name}: un bloque trae {chunk.shape[1]} columnas (esperadas {contract['n_columns']})"
                    )
                total_read += len(chunk)
                frames.append(chunk[chunk[uf_idx] == uf])
        except pd.errors.ParserError as e:
            raise SchemaValidationError(f"{path.name}: el CSV no se pudo parsear con el contrato: {e}") from e
        fingerprints.append(file_fingerprint(path))

    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=range(len(names)))
    raw.columns = names
    raw = raw.drop_duplicates(subset=["cnpj_basico", "cnpj_ordem", "cnpj_dv"], keep="last")

    out = run.path("data", "raw.pkl")
    raw.to_pickle(out)
    info = {
        "inputs": fingerprints,
        "rows_read": total_read,
        "rows_uf": len(raw),
        "uf": uf,
    }
    write_json(run.path("data", "ingest_summary.json"), info)
    run.manifest["inputs"] = fingerprints
    log.info("Filas leídas: %s · filas %s: %s", f"{total_read:,}", uf, f"{len(raw):,}")
    return {"raw": "data/raw.pkl", "rows_uf": len(raw)}
