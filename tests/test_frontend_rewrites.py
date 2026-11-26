"""Cada ruta /api/... o /auth/... que llama el frontend tiene una regla de reenvío en next.config.ts.

Sin regla, Next responde su propio 404 en Vercel (pasó con /api/clientes y /api/tarjetas).
Solo lee archivos: no necesita Node, Docker ni Postgres.
"""

import re
from pathlib import Path

import pytest

FRONT = Path(__file__).resolve().parent.parent / "frontend"
CONFIG = FRONT / "next.config.ts"
LOCAL = ("/api/geocode",)  # rutas propias de Next (src/app/api/...), no se reenvían

# Cualquier cadena '...', "..." o plantilla `...` que empiece por /api/ o /auth/. Se revisan todas, no solo
# los argumentos de fetch/apiFetch, para cubrir también URLs guardadas en variables (visits/page.tsx).
LITERAL = re.compile(r"""(["'`])(/(?:api|auth)/[^"'`\s]*)""")


def static_prefix(raw: str) -> str:
    """Parte fija de la ruta: hasta el primer ${...}, ? o #, sin barra final."""
    return re.split(r"\$\{|[?#]", raw, maxsplit=1)[0].rstrip("/") or "/"


def frontend_paths() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    files = [*FRONT.glob("src/**/*.ts"), *FRONT.glob("src/**/*.tsx")]
    for f in files:
        rel = f.relative_to(FRONT).as_posix()
        if rel.startswith("src/app/api/"):  # manejadores locales de Next, no llamadas al backend
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for _, raw in LITERAL.findall(line):
                path = static_prefix(raw)
                if not any(path == p or path.startswith(p + "/") for p in LOCAL):
                    found.setdefault(path, []).append(f"{rel}:{n}")
    return found


def _array(text: str, name: str) -> list[str]:
    m = re.search(rf"const {name} = \[(.*?)\];", text, re.S)
    assert m, f"next.config.ts no define {name}"
    return re.findall(r'"([^"]+)"', m.group(1))


def config_rules(text: str | None = None) -> list[re.Pattern]:
    """Regex de cada regla: rutas exactas (con :param de un segmento) y prefijos con :path* (cero o más)."""
    text = CONFIG.read_text(encoding="utf-8") if text is None else text
    exact = [re.compile("^" + re.sub(r":\w+", "[^/]+", re.escape(r).replace("\\:", ":")) + "$")
             for r in _array(text, "EXACT_ROUTES")]
    prefixes = [re.compile("^" + re.escape(p) + "(/.*)?$") for p in _array(text, "BACKEND_PREFIXES")]
    return exact + prefixes


def uncovered(rules) -> dict[str, list[str]]:
    return {p: where for p, where in frontend_paths().items() if not any(r.match(p) for r in rules)}


def test_every_frontend_api_call_has_a_rewrite():
    missing = uncovered(config_rules())
    assert not missing, "Rutas sin regla en frontend/next.config.ts (agrega el prefijo a BACKEND_PREFIXES):\n" + "\n".join(
        f"  {p}  <- {', '.join(w)}" for p, w in sorted(missing.items()))


def test_extractor_sees_the_calls_that_broke_in_vercel():
    paths = frontend_paths()
    for p in ("/api/clientes", "/api/tarjetas/resumen", "/api/tarjetas/ruta", "/auth/login", "/api/stats/summary"):
        assert p in paths, p
    assert not any(p.startswith("/api/geocode") for p in paths)


def test_geocode_stays_local():
    assert not any(r.match("/api/geocode") for r in config_rules())


@pytest.mark.parametrize("prefix", ["/api/clientes", "/api/tarjetas"])
def test_removing_a_prefix_is_detected(prefix):
    text = CONFIG.read_text(encoding="utf-8")
    assert f'"{prefix}",' in text
    broken = config_rules(text.replace(f'  "{prefix}",\n', "", 1))
    assert any(p == prefix or p.startswith(prefix + "/") for p in uncovered(broken))
