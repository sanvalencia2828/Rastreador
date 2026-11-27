"""Cada ruta /api/... o /auth/... que llama el frontend tiene una regla de reenvío en next.config.ts.

Sin regla, Next responde su propio 404 en Vercel (pasó con /api/clientes y /api/tarjetas). Además, cada prefijo
necesita una regla exacta: con solo `${prefix}/:path*`, GET /api/clientes llegaba como /api/clientes/, FastAPI
respondía 307 a su propio dominio y el navegador lo bloqueaba ("Failed to fetch").
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


# --- reglas que genera rewrites(): regla exacta por prefijo, antes de su `:path*` ---------------------------

SPREAD = re.compile(
    r"\.\.\.(\w+)\.map\(\((\w+)\) => \(\{\s*source: (`[^`]*`|\w+),\s*destination: (`[^`]*`|\w+),?\s*\}\)\)", re.S)
EXACT_LINE = "      ...BACKEND_PREFIXES.map((prefix) => ({ source: prefix, destination: `${backendUrl}${prefix}` })),\n"


def _config() -> str:
    return CONFIG.read_text(encoding="utf-8").replace("\r\n", "\n")


def rewrite_rules(text: str) -> list[tuple[str, str]]:
    """(source, destination) en el orden de rewrites(), expandiendo cada `...ARRAY.map((x) => ({...}))`."""
    body = re.search(r"async rewrites\(\) \{\s*return \[(.*?)\];", text, re.S)
    assert body, "next.config.ts: no encuentro rewrites() { return [...] }"
    rules = []
    for array, var, src, dst in SPREAD.findall(body.group(1)):
        def expand(t, v):
            return v if t == var else t.strip("`").replace("${" + var + "}", v).replace("${backendUrl}", "<B>")
        rules += [(expand(src, v), expand(dst, v)) for v in _array(text, array)]
    return rules


def missing_exact(rules, text: str) -> list[str]:
    """Prefijos sin la regla exacta `prefix -> <B>prefix` antes de su `prefix/:path*`."""
    bad = []
    for prefix in _array(text, "BACKEND_PREFIXES"):
        wild = [i for i, (s, _) in enumerate(rules) if s == f"{prefix}/:path*"]
        exact = [i for i, r in enumerate(rules) if r == (prefix, f"<B>{prefix}")]
        if not wild or not exact or exact[0] > wild[0]:
            bad.append(prefix)
    return bad


def test_every_prefix_has_an_exact_rule_before_path_star():
    text = _config()
    rules = rewrite_rules(text)
    assert len(rules) == len(_array(text, "EXACT_ROUTES")) + 2 * len(_array(text, "BACKEND_PREFIXES"))
    assert missing_exact(rules, text) == []
    assert ("/api/clientes", "<B>/api/clientes") in rules and ("/api/cities", "<B>/api/cities") in rules
    assert not any(s.startswith("/api/geocode") for s, _ in rules)


def test_missing_exact_rules_are_detected():
    text = _config()
    assert EXACT_LINE in text
    assert set(missing_exact(rewrite_rules(text.replace(EXACT_LINE, "", 1)), text)) == set(_array(text, "BACKEND_PREFIXES"))
    one_missing = [r for r in rewrite_rules(text) if r != ("/api/clientes", "<B>/api/clientes")]
    assert missing_exact(one_missing, text) == ["/api/clientes"]


def test_exact_rule_after_path_star_is_detected():
    text = _config()
    rules = rewrite_rules(text)
    moved = [r for r in rules if r != ("/api/cities", "<B>/api/cities")] + [("/api/cities", "<B>/api/cities")]
    assert missing_exact(moved, text) == ["/api/cities"]
