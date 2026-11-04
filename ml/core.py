"""Infraestructura común del pipeline: configuración, corridas, artefactos y errores."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "ml" / "config.yaml"

log = logging.getLogger("ml")


# ------------------------------------------------------------------------------
# Errores con código de salida propio
# ------------------------------------------------------------------------------
class PipelineError(Exception):
    exit_code = 1
    status = "failed"


class SchemaValidationError(PipelineError):
    """Los datos no cumplen el contrato: el pipeline se detiene sin entrenar."""

    exit_code = 2
    status = "invalid_data"


class QualityGateError(PipelineError):
    """El modelo no supera el gate de calidad: no se promueve a latest."""

    exit_code = 3
    status = "rejected"


class RunLockedError(PipelineError):
    exit_code = 4
    status = "locked"


# ------------------------------------------------------------------------------
# Configuración
# ------------------------------------------------------------------------------
def _coerce(value: str) -> Any:
    try:
        return yaml.safe_load(value)
    except yaml.YAMLError:
        return value


def load_config(path: str | os.PathLike | None = None) -> dict:
    """Lee el YAML y aplica overrides ML__SECCION__CLAVE desde el entorno."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for key, raw in os.environ.items():
        if not key.startswith("ML__"):
            continue
        parts = [p.lower() for p in key[4:].split("__")]
        node = cfg
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = _coerce(raw)
    cfg["_config_path"] = str(cfg_path)
    return cfg


def resolve(path: str | os.PathLike) -> Path:
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


# ------------------------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------------------------
def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def file_fingerprint(path: Path, head_bytes: int = 16 * 1024 * 1024) -> dict:
    """Huella barata de un archivo grande: tamaño, mtime y sha256 de los primeros MB."""
    st = path.stat()
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(head_bytes))
    return {
        "path": str(path),
        "bytes": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
        "sha256_head16mb": h.hexdigest(),
    }


def git_commit() -> str | None:
    env_sha = os.environ.get("GIT_COMMIT")
    if env_sha:
        return env_sha
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def library_versions() -> dict:
    versions = {"python": platform.python_version()}
    for mod in ("numpy", "pandas", "sklearn", "joblib", "yaml"):
        try:
            versions[mod] = __import__(mod).__version__
        except Exception:
            versions[mod] = None
    return versions


# ------------------------------------------------------------------------------
# Corrida y artefactos
# ------------------------------------------------------------------------------
@dataclass
class Run:
    """Una corrida del pipeline: carpeta propia, manifest y log."""

    run_id: str
    cfg: dict
    root: Path = field(init=False)
    manifest: dict = field(init=False)

    def __post_init__(self) -> None:
        self.root = runs_dir(self.cfg) / self.run_id
        self.root.mkdir(parents=True, exist_ok=True)
        mpath = self.root / "manifest.json"
        if mpath.exists():
            self.manifest = read_json(mpath)
        else:
            cfg_snapshot = {k: v for k, v in self.cfg.items() if not k.startswith("_")}
            self.manifest = {
                "run_id": self.run_id,
                "status": "running",
                "created_at": utc_now(),
                "git_commit": git_commit(),
                "host": platform.node(),
                "versions": library_versions(),
                "config": copy.deepcopy(cfg_snapshot),
                "steps": {},
            }
            write_json(self.root / "config.yaml.json", cfg_snapshot)
            self.save()
        self._attach_log()

    # --- rutas ---------------------------------------------------------------
    def path(self, *parts: str) -> Path:
        p = self.root.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # --- manifest ------------------------------------------------------------
    def save(self) -> None:
        write_json(self.root / "manifest.json", self.manifest)

    def step_started(self, name: str) -> float:
        self.manifest["steps"][name] = {"status": "running", "started_at": utc_now()}
        self.manifest["status"] = "running"
        self.save()
        log.info("▶ paso %s", name)
        return time.monotonic()

    def step_finished(self, name: str, t0: float, outputs: dict | None = None) -> None:
        step = self.manifest["steps"][name]
        step.update(
            status="ok",
            finished_at=utc_now(),
            seconds=round(time.monotonic() - t0, 2),
            outputs=outputs or {},
        )
        self.save()
        log.info("✔ paso %s (%.1fs)", name, step["seconds"])

    def step_failed(self, name: str, t0: float, err: BaseException) -> None:
        step = self.manifest["steps"].setdefault(name, {})
        status = getattr(err, "status", "failed")
        step.update(
            status=status,
            finished_at=utc_now(),
            seconds=round(time.monotonic() - t0, 2),
            error=f"{type(err).__name__}: {err}",
        )
        self.manifest["status"] = status
        self.manifest["failed_step"] = name
        self.manifest["finished_at"] = utc_now()
        self.save()

    def require(self, *rel_paths: str) -> None:
        missing = [p for p in rel_paths if not (self.root / p).exists()]
        if missing:
            raise PipelineError(
                f"Faltan artefactos de pasos anteriores en {self.root}: {missing}. "
                "Ejecuta los pasos previos con el mismo --run-id."
            )

    def _attach_log(self) -> None:
        self._fh = logging.FileHandler(self.path("logs", "pipeline.log"), encoding="utf-8")
        self._fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(self._fh)

    def close(self) -> None:
        """Suelta el log de la corrida (si no, varias corridas en un proceso mezclan logs)."""
        log.removeHandler(self._fh)
        self._fh.close()


def artifacts_dir(cfg: dict) -> Path:
    p = resolve(cfg["run"]["artifacts_dir"])
    p.mkdir(parents=True, exist_ok=True)
    return p


def runs_dir(cfg: dict) -> Path:
    p = artifacts_dir(cfg) / "runs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def setup_logging(level: int = logging.INFO) -> None:
    if any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in log.handlers):
        return
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(sh)
    log.setLevel(level)


# ------------------------------------------------------------------------------
# Lock (evita que el scheduler y una corrida manual se pisen)
# ------------------------------------------------------------------------------
class RunLock:
    def __init__(self, cfg: dict, run_id: str) -> None:
        self.path = artifacts_dir(cfg) / ".pipeline.lock"
        self.stale_seconds = float(cfg["run"].get("lock_stale_hours", 6)) * 3600
        self.run_id = run_id

    def __enter__(self) -> "RunLock":
        if self.path.exists():
            age = time.time() - self.path.stat().st_mtime
            if age < self.stale_seconds:
                holder = self.path.read_text(encoding="utf-8").strip()
                raise RunLockedError(f"Hay otra corrida en curso ({holder}); lock en {self.path}")
            log.warning("Lock abandonado (%.1f h); se reemplaza", age / 3600)
            self.path.unlink()
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"{self.run_id} pid={os.getpid()} since={utc_now()}")
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


# ------------------------------------------------------------------------------
# latest + retención
# ------------------------------------------------------------------------------
def promote_latest(run: Run) -> None:
    pointer = {
        "run_id": run.run_id,
        "promoted_at": utc_now(),
        "path": str(run.root.relative_to(artifacts_dir(run.cfg))),
        "metrics": run.manifest.get("metrics", {}),
    }
    write_json(artifacts_dir(run.cfg) / "latest.json", pointer)
    log.info("latest → %s", run.run_id)


def prune_runs(cfg: dict) -> list[str]:
    """Conserva las últimas `keep_runs` corridas exitosas y las fallidas más nuevas que ellas."""
    keep = int(cfg["run"].get("keep_runs", 12))
    latest_file = artifacts_dir(cfg) / "latest.json"
    latest = read_json(latest_file)["run_id"] if latest_file.exists() else None
    runs = sorted((p for p in runs_dir(cfg).iterdir() if p.is_dir()), key=lambda p: p.name)

    def status(p: Path) -> str:
        try:
            return read_json(p / "manifest.json").get("status", "unknown")
        except Exception:
            return "unknown"

    ok_runs = [p for p in runs if status(p) == "succeeded"]
    keep_set = {p.name for p in ok_runs[-keep:]} | ({latest} if latest else set())
    oldest_kept = min(keep_set) if keep_set else ""
    removed = []
    for p in runs:
        if p.name in keep_set or status(p) == "running":
            continue
        # las fallidas/rechazadas más nuevas que la corrida exitosa más vieja se conservan para diagnóstico
        if status(p) != "succeeded" and p.name > oldest_kept:
            continue
        shutil.rmtree(p, ignore_errors=True)
        removed.append(p.name)
    if removed:
        log.info("Retención: se borraron %d corridas antiguas", len(removed))
    return removed
