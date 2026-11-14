"""Paso 2 · validate: comprueba el contrato de esquema y detiene el pipeline si no se cumple."""

from __future__ import annotations

import pandas as pd

from ml.core import Run, SchemaValidationError, log, write_json
from ml.steps.ingest import load_contract


def check_frame(df: pd.DataFrame, contract: dict, min_rows: int) -> dict:
    """Devuelve un reporte {status, errors, warnings, columns}. No lanza excepciones."""
    errors: list[str] = []
    warnings: list[str] = []
    columns: dict[str, dict] = {}

    expected = [c["name"] for c in contract["columns"]]
    actual = list(df.columns)
    if actual != expected:
        missing = [c for c in expected if c not in actual]
        extra = [c for c in actual if c not in expected]
        errors.append(f"columnas distintas al contrato · faltan={missing} · sobran={extra}")
        return {"status": "failed", "errors": errors, "warnings": warnings, "columns": columns, "rows": len(df)}

    n = len(df)
    if n < min_rows:
        errors.append(f"solo {n} filas (mínimo {min_rows}); ¿volcado incompleto o filtro UF equivocado?")

    default_tol = float(contract.get("default_max_invalid_fraction", 0.001))
    for spec in contract["columns"]:
        name = spec["name"]
        s = df[name].astype(str).str.strip()
        empty = s.eq("")
        null_frac = float(empty.mean()) if n else 0.0
        col = {"null_fraction": round(null_frac, 5)}

        if not spec.get("nullable", True) and empty.any():
            # tolerancia mínima para filas rotas sueltas
            if null_frac > default_tol:
                errors.append(f"{name}: {null_frac:.2%} vacíos en una columna obligatoria")
            else:
                warnings.append(f"{name}: {int(empty.sum())} vacíos en columna obligatoria (tolerado)")
        max_null = spec.get("max_null_fraction")
        if max_null is not None and null_frac > float(max_null):
            errors.append(f"{name}: {null_frac:.2%} vacíos supera el máximo {float(max_null):.2%}")

        values = s[~empty]
        invalid = pd.Series(False, index=values.index)
        if "pattern" in spec:
            invalid |= ~values.str.fullmatch(spec["pattern"])
        if "allowed" in spec:
            invalid |= ~values.isin([str(v) for v in spec["allowed"]])
        if len(values):
            inv_frac = float(invalid.mean())
            col["invalid_fraction"] = round(inv_frac, 6)
            if inv_frac > 0:
                col["invalid_examples"] = values[invalid].value_counts().head(5).to_dict()
            tol = float(spec.get("max_invalid_fraction", default_tol))
            if inv_frac > tol:
                errors.append(
                    f"{name}: {inv_frac:.2%} de valores no cumplen el contrato (tolerancia {tol:.2%}); "
                    f"ejemplos {list(col.get('invalid_examples', {}))[:3]}"
                )
            elif inv_frac > 0:
                warnings.append(f"{name}: {int(invalid.sum())} valores fuera de contrato (tolerado)")
        columns[name] = col

    return {
        "status": "failed" if errors else "passed",
        "rows": n,
        "contract_version": contract.get("version"),
        "errors": errors,
        "warnings": warnings,
        "columns": columns,
    }


def run(run: Run) -> dict:
    run.require("data/raw.pkl")
    contract = load_contract(run.cfg)
    raw = pd.read_pickle(run.root / "data" / "raw.pkl")
    report = check_frame(raw, contract, int(run.cfg["validation"]["min_rows"]))
    write_json(run.path("validation", "raw_report.json"), report)
    for w in report["warnings"]:
        log.warning("validación: %s", w)
    if report["status"] != "passed":
        for e in report["errors"]:
            log.error("validación: %s", e)
        raise SchemaValidationError(
            f"{len(report['errors'])} violaciones del contrato de esquema; ver validation/raw_report.json"
        )
    log.info("Contrato v%s OK sobre %s filas", report["contract_version"], f"{report['rows']:,}")
    return {"report": "validation/raw_report.json", "warnings": len(report["warnings"])}
