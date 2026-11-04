"""Orquestador y CLI del pipeline de ML.

    python -m ml run                         # corrida completa con id nuevo
    python -m ml run --steps ingest,validate # solo algunos pasos
    python -m ml run --run-id 20261012T200000Z --from train   # retoma una corrida
    python -m ml run --if-new-data           # lo que usa el scheduler: solo si hay volcado nuevo
    python -m ml status                      # últimas corridas y latest

Códigos de salida: 0 ok · 1 error · 2 datos inválidos (esquema) · 3 gate de calidad · 4 otra corrida en curso
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback

from ml.core import (
    PipelineError,
    Run,
    RunLock,
    SchemaValidationError,
    artifacts_dir,
    file_fingerprint,
    load_config,
    log,
    new_run_id,
    promote_latest,
    prune_runs,
    read_json,
    runs_dir,
    setup_logging,
    utc_now,
    write_json,
)
from ml.steps import evaluate, features, ingest, predict, train, validate

STEPS = {
    "ingest": ingest.run,
    "validate": validate.run,
    "features": features.run,
    "train": train.run,
    "evaluate": evaluate.run,
    "predict": predict.run,
}
ORDER = list(STEPS)


def select_steps(steps: str | None, start: str | None, end: str | None) -> list[str]:
    if steps:
        chosen = [s.strip() for s in steps.split(",") if s.strip()]
        unknown = [s for s in chosen if s not in STEPS]
        if unknown:
            raise SystemExit(f"Pasos desconocidos: {unknown}. Válidos: {ORDER}")
        return [s for s in ORDER if s in chosen]
    i = ORDER.index(start) if start else 0
    j = ORDER.index(end) + 1 if end else len(ORDER)
    return ORDER[i:j]


def inputs_unchanged(cfg: dict) -> bool:
    """True si los volcados de entrada son los mismos que usó la última corrida promovida."""
    latest_file = artifacts_dir(cfg) / "latest.json"
    if not latest_file.exists():
        return False
    try:
        manifest = read_json(runs_dir(cfg) / read_json(latest_file)["run_id"] / "manifest.json")
        previous = {(i["bytes"], i["sha256_head16mb"]) for i in manifest.get("inputs", [])}
        current = {(f["bytes"], f["sha256_head16mb"]) for f in map(file_fingerprint, ingest.find_inputs(cfg))}
    except Exception:
        return False
    return bool(previous) and previous == current


def execute(
    cfg: dict, run_id: str | None = None, steps: list[str] | None = None, skip_if_unchanged: bool = False
) -> int:
    steps = steps or ORDER
    if skip_if_unchanged and run_id is None and steps == ORDER and inputs_unchanged(cfg):
        log.info("Sin volcados nuevos desde la última corrida promovida; no se entrena (ejecuta sin --if-new-data para forzar)")
        return 0
    run_id = run_id or new_run_id()
    try:
        with RunLock(cfg, run_id):
            run = Run(run_id, cfg)
            try:
                return _execute_steps(cfg, run, steps)
            finally:
                run.close()
    except PipelineError as err:
        log.error("Corrida %s detenida (%s): %s", run_id, err.status, err)
        return err.exit_code
    except Exception:
        log.error("Corrida %s falló:\n%s", run_id, traceback.format_exc())
        return 1


def _execute_steps(cfg: dict, run: Run, steps: list[str]) -> int:
    log.info("Corrida %s · pasos %s · artefactos en %s", run.run_id, steps, run.root)
    for name in steps:
        t0 = run.step_started(name)
        try:
            outputs = STEPS[name](run)
        except Exception as err:
            run.step_failed(name, t0, err)
            report = run.root / "validation" / "raw_report.json"
            if isinstance(err, SchemaValidationError) and not report.exists():
                write_json(run.path("validation", "raw_report.json"), {"status": "failed", "errors": [str(err)]})
            raise
        run.step_finished(name, t0, outputs)

    complete = all(run.manifest["steps"].get(s, {}).get("status") == "ok" for s in ORDER)
    run.manifest["finished_at"] = utc_now()
    run.manifest["status"] = "succeeded" if complete else "partial"
    run.save()
    if complete:
        promote_latest(run)
        if not cfg["run"].get("keep_intermediate", False):
            (run.root / "data" / "raw.pkl").unlink(missing_ok=True)
        prune_runs(cfg)
    log.info("Corrida %s terminada: %s", run.run_id, run.manifest["status"])
    return 0


def status(cfg: dict, n: int = 10) -> int:
    latest_file = artifacts_dir(cfg) / "latest.json"
    if latest_file.exists():
        latest = read_json(latest_file)
        print(f"latest: {latest['run_id']}  métricas={latest.get('metrics')}")
    else:
        print("latest: (ninguna corrida promovida todavía)")
    runs = sorted((p for p in runs_dir(cfg).iterdir() if p.is_dir()), reverse=True)[:n]
    for p in runs:
        try:
            m = read_json(p / "manifest.json")
        except Exception:
            continue
        extra = m.get("failed_step") or ""
        print(f"{p.name}  {m.get('status', '?'):<13} {extra:<10} {m.get('metrics', '')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ml", description="Pipeline de riesgo de cierre de comercios")
    parser.add_argument("--config", default=None, help="ruta al YAML (por defecto ml/config.yaml)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="ejecuta el pipeline")
    r.add_argument("--run-id", default=None, help="id de una corrida existente para retomarla")
    r.add_argument("--steps", default=None, help=f"lista separada por comas de {ORDER}")
    r.add_argument("--from", dest="start", choices=ORDER, default=None)
    r.add_argument("--to", dest="end", choices=ORDER, default=None)
    r.add_argument(
        "--if-new-data",
        action="store_true",
        help="no hace nada si los volcados son los mismos de la última corrida promovida (para el scheduler)",
    )
    s = sub.add_parser("status", help="muestra las últimas corridas")
    s.add_argument("-n", type=int, default=10)
    args = parser.parse_args(argv)

    setup_logging()
    cfg = load_config(args.config)
    if args.cmd == "status":
        return status(cfg, args.n)
    t0 = time.monotonic()
    code = execute(cfg, args.run_id, select_steps(args.steps, args.start, args.end), args.if_new_data)
    log.info("Duración total %.1fs · código de salida %d", time.monotonic() - t0, code)
    return code


if __name__ == "__main__":
    sys.exit(main())
