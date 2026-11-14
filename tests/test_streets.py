"""Calles de Maringá: normalización, índice del volcado, cruce con OSM (JSON de Overpass congelado), sin red."""

import importlib.util
import json
from pathlib import Path

import pytest

from app.services import streets as S

FIXTURE = Path(__file__).parent / "fixtures" / "overpass_maringa_sample.json"


def _row(muni="7691", sit="02", tipo="RUA", logr="SANTOS DUMONT", numero="100", bairro="ZONA 1", cep="87013000"):
    """Fila de 30 columnas como el volcado; los campos de negocio/contacto llevan marcas para detectar fugas."""
    r = [""] * 30
    r[4], r[5] = "SECRETO FANTASIA", sit
    r[13], r[14], r[15], r[17], r[18], r[20] = tipo, logr, numero, bairro, cep, muni
    r[21], r[22], r[27] = "44", "999999999", "secreto@example.com"
    return ";".join(f'"{c}"' for c in r)


@pytest.fixture
def dump_file(tmp_path):
    rows = [
        _row(numero="100"), _row(numero="250"), _row(numero="S/N"), _row(sit="08"),            # Santos Dumont
        _row(tipo="AVENIDA", logr="BRASIL", numero="10", bairro="CENTRO"),
        _row(tipo="AVENIDA", logr="COLOMBO", numero="5"),
        _row(tipo="PRACA", logr="RAPOSO TAVARES", numero="1"),
        _row(tipo="AVENIDA", logr="GASTAO VIDIGAL DOUTOR", numero="7"),                         # título al final: no cruza
        _row(tipo="RUA", logr="SO INATIVOS", sit="08"),
        _row(muni="8461", tipo="RUA", logr="DE SARANDI"),                                      # otro municipio: se ignora
    ]
    path = tmp_path / "x.ESTABELE"
    path.write_text("\n".join(rows), encoding="latin-1")
    return str(path)


@pytest.mark.parametrize(
    "name,tipo,expected",
    [
        ("Av. Colombo", "", ("AVENIDA", "COLOMBO")),
        ("R. São João", "", ("RUA", "SAO JOAO")),
        ("Praça Raposo Tavares", "", ("PRACA", "RAPOSO TAVARES")),
        ("RAPOSO TAVARES", "PRAÇA", ("PRACA", "RAPOSO TAVARES")),
        ("  Rua   XV de  Novembro ", "", ("RUA", "XV DE NOVEMBRO")),
        ("Avenida Doutor Gastão Vidigal", "", ("AVENIDA", "DOUTOR GASTAO VIDIGAL")),  # no se expanden títulos
        ("Zona 7", "", (None, "ZONA 7")),
        ("Av. X", "RUA", ("RUA", "AV X")),  # tipo column and name prefix disagree: kept apart, never merged
    ],
)
def test_normalize_street(name, tipo, expected):
    assert S.normalize_street(name, tipo) == expected


def test_dump_index_counts_only_maringa_and_only_aggregates(dump_file):
    idx = S.build_dump_index(dump_file)
    assert "RUA|DE SARANDI" not in idx
    dumont = idx["RUA|SANTOS DUMONT"]
    assert (dumont["n_total"], dumont["n_ativos"], dumont["sem_numero"]) == (4, 3, 1)
    assert (min(dumont["numeros"]), max(dumont["numeros"])) == (100, 250)
    blob = json.dumps(idx, default=list)
    for secret in ("SECRETO", "999999999", "example.com"):
        assert secret not in blob


def test_match_rates_unmatched_and_no_invention(dump_file):
    osm_ways = S.index_osm_ways(json.loads(FIXTURE.read_text(encoding="utf-8")))
    report = S.match_streets(S.build_dump_index(dump_file), osm_ways)
    r = report["resumen"]
    # active streets: Santos Dumont, Brasil, Colombo, Raposo Tavares, Gastão Vidigal (SO INATIVOS excluded)
    assert (r["calles_con_comercios_activos"], r["cruzadas"], r["sin_cruzar"]) == (5, 3 + 1, 1)
    assert [(x["nome"], x["n_comercios_ativos"]) for x in report["sin_cruzar"]] == [("GASTAO VIDIGAL DOUTOR", 1)]
    assert report["sin_cruzar"][0]["length_m"] is None  # sin geometría inventada
    by_name = {x["nome"]: x for x in report["calles"]}
    assert by_name["BRASIL"]["length_m"] == pytest.approx(2 * 510, rel=0.02)  # dos tramos unidos
    assert by_name["BRASIL"]["n_ways"] == 2


def test_report_has_no_business_or_contact_fields(dump_file):
    report = S.match_streets(S.build_dump_index(dump_file), {})
    blob = json.dumps(report, ensure_ascii=False)
    for secret in ("SECRETO", "999999999", "example.com"):
        assert secret not in blob
    assert set(report["calles"][0]) >= {"nome", "n_comercios_ativos", "numero_min", "numero_max", "ceps"}


def test_long_street_flag_uses_configurable_thresholds(dump_file):
    osm_ways = S.index_osm_ways(json.loads(FIXTURE.read_text(encoding="utf-8")))
    idx = S.build_dump_index(dump_file)
    by_len = {x["nome"]: x["calle_larga"] for x in S.match_streets(idx, osm_ways, larga_m=2000)["calles"]}
    assert by_len["COLOMBO"] is True and by_len["SANTOS DUMONT"] is False  # Colombo ≈ 3 km
    by_count = {x["nome"]: x["calle_larga"] for x in S.match_streets(idx, osm_ways, larga_m=10**9, larga_comercios=2)["calles"]}
    assert by_count["SANTOS DUMONT"] is True and by_count["COLOMBO"] is False


def test_overpass_query_filters_by_ibge_area_not_by_name():
    q = S.overpass_query()
    assert '"IBGE:GEOCODIGO"="4115200"' in q and "area[" in q and "Maring" not in q


def test_fetch_rejects_other_municipalities_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(S.requests, "post", lambda *a, **k: pytest.fail("no debe haber red"))
    with pytest.raises(ValueError):
        S.fetch_osm_streets(str(tmp_path), "4113700")


def test_fetch_uses_cache_and_retries_busy_server(tmp_path, monkeypatch):
    calls = []

    class Resp:
        def __init__(self, code):
            self.status_code = code

        def raise_for_status(self):
            pass

        def json(self):
            return {"elements": [{"type": "way"}]}

    codes = iter([502, 200])
    monkeypatch.setattr(S.requests, "post", lambda *a, **k: calls.append(k) or Resp(next(codes)))
    monkeypatch.setattr(S.time, "sleep", lambda s: None)
    assert S.fetch_osm_streets(str(tmp_path)) == {"elements": [{"type": "way"}]}
    assert len(calls) == 2
    # the request carries only the IBGE-based query: nothing about customers
    assert "4115200" in calls[0]["data"]["data"]
    monkeypatch.setattr(S.requests, "post", lambda *a, **k: pytest.fail("la segunda vez sale de la caché"))
    assert S.fetch_osm_streets(str(tmp_path)) == {"elements": [{"type": "way"}]}


class _Resp:
    def __init__(self, code=200, body=None, text_error=False):
        self.status_code, self._body, self._text_error = code, body, text_error

    def raise_for_status(self):
        if self.status_code >= 400:
            raise S.requests.HTTPError(str(self.status_code))

    def json(self):
        if self._text_error:
            raise ValueError("html")
        return self._body


GOOD = {"elements": [{"type": "way"}]}


@pytest.mark.parametrize(
    "bad",
    [_Resp(200, {"elements": [], "remark": "runtime error: Query timed out"}), _Resp(200, {"elements": []}), _Resp(200, text_error=True)],
)
def test_incomplete_200_is_retried_and_never_cached(tmp_path, monkeypatch, bad):
    answers = iter([bad, _Resp(200, GOOD)])
    monkeypatch.setattr(S.requests, "post", lambda *a, **k: next(answers))
    monkeypatch.setattr(S.time, "sleep", lambda s: None)
    assert S.fetch_osm_streets(str(tmp_path)) == GOOD
    assert len(list(tmp_path.glob("*.json"))) == 1 and json.loads(next(tmp_path.glob("*.json")).read_text()) == GOOD


def test_always_incomplete_raises_and_writes_no_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(S.requests, "post", lambda *a, **k: _Resp(200, {"elements": [], "remark": "x"}))
    monkeypatch.setattr(S.time, "sleep", lambda s: None)
    with pytest.raises(S._IncompleteOverpass):
        S.fetch_osm_streets(str(tmp_path), attempts=2)
    assert not list(tmp_path.glob("*"))


def test_client_error_is_not_retried(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(S.requests, "post", lambda *a, **k: calls.append(1) or _Resp(400))
    with pytest.raises(S.requests.HTTPError):
        S.fetch_osm_streets(str(tmp_path))
    assert len(calls) == 1


def test_corrupt_or_empty_cache_is_ignored_and_attempts_zero_still_tries_once(tmp_path, monkeypatch):
    (tmp_path / "4115200_2099-01-01.json").write_text('{"elements": [', encoding="utf-8")  # truncated
    (tmp_path / "4115200_2098-01-01.json").write_text('{"elements": []}', encoding="utf-8")  # empty
    monkeypatch.setattr(S.requests, "post", lambda *a, **k: _Resp(200, GOOD))
    assert S.fetch_osm_streets(str(tmp_path), attempts=0) == GOOD


def test_script_rejects_other_municipality(capsys):
    spec = importlib.util.spec_from_file_location("cargar_calles_osm", Path(__file__).parent.parent / "scripts" / "cargar_calles_osm.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--municipio", "4113700"]) == 2
    assert "Maringá" in capsys.readouterr().err


# ---------------------------------------------------------------- distritos, casco, calzada doble, cruces opcionales
def _osm(*ways):
    return {"elements": [
        {"type": "way", "id": i, "tags": tags, "geometry": [{"lat": a, "lon": b} for a, b in pts]}
        for i, (tags, pts) in enumerate(ways)
    ]}


def _idx(*rows):
    out = {}
    for tipo, nome, n in rows:
        out[S.street_key(tipo, nome)] = {"tipo": tipo, "nome": nome, "n_total": n, "n_ativos": n, "n_distrito": 0,
                                         "bairros": {}, "ceps": set(), "numeros": [], "sem_numero": 0}
    return out


def test_district_commerces_are_counted_apart(tmp_path):
    rows = [_row(bairro="ZONA 1"), _row(bairro="DISTRITO DE FLORIANO", numero="999"),
            _row(bairro="JARDIM X IGUATEMI", cep="87000999")]
    path = tmp_path / "d.ESTABELE"
    path.write_text("\n".join(rows), encoding="latin-1")
    from collections import Counter
    dist = Counter()
    s = S.build_dump_index(str(path), distritos=dist)["RUA|SANTOS DUMONT"]
    assert (s["n_ativos"], s["n_distrito"]) == (1, 2)
    assert s["numeros"] == [100] and s["ceps"] == {"87013000"}  # nada del distrito entra en rango ni CEP
    assert dist == {"DISTRITO DE FLORIANO": 1, "JARDIM X IGUATEMI": 1}


def test_only_ways_near_the_town_center_count_and_far_streets_become_ambigua():
    near = [(-23.4205, -51.9331), (-23.4205, -51.9301)]
    far = [(-23.30, -52.10), (-23.30, -52.0995)]  # ~20 km away
    osm = _osm(({"name": "Rua Sao Joao"}, near), ({"name": "Rua Sao Joao"}, far))
    ways = S.index_osm_ways(osm)
    e = ways["RUA|SAO JOAO"]
    assert (e["n_ways"], e["n_fuera"]) == (1, 1) and e["length_m"] < 400
    # with a huge radius both count: the spread (>8 km) makes it ambigua and keeps it out of the plan
    wide = S.index_osm_ways(osm, radio_m=10**6)
    rep = S.match_streets(_idx(("RUA", "SAO JOAO", 5)), wide)
    row = rep["calles"][0]
    assert row["estado"] == "ambigua" and row["en_plan_automatico"] is False and row["spread_m"] > 8000


def test_only_ok_streets_enter_the_automatic_plan():
    osm = _osm(({"name": "Rua Curta"}, [(-23.4205, -51.9331), (-23.4205, -51.9321)]),
               ({"name": "Rua Comprida"}, [(-23.4205, -51.9331), (-23.4205, -51.9031)]))
    rep = S.match_streets(_idx(("RUA", "CURTA", 5), ("RUA", "COMPRIDA", 5), ("RUA", "NO EXISTE", 5)), S.index_osm_ways(osm))
    by = {r["nome"]: (r["estado"], r["en_plan_automatico"]) for r in rep["calles"]}
    assert by == {"CURTA": ("ok", True), "COMPRIDA": ("calle_larga", False), "NO EXISTE": ("sin_geometria", False)}


def test_dual_carriageway_is_detected_as_paired_length():
    a = [(-23.4205, -51.9331), (-23.4205, -51.9301)]
    b = [(-23.42055, -51.9301), (-23.42055, -51.9331)]  # opposite direction, ~5 m apart
    osm = _osm(({"name": "Avenida Brasil", "oneway": "yes"}, a), ({"name": "Avenida Brasil", "oneway": "yes"}, b),
               ({"name": "Avenida Sola", "oneway": "yes"}, a))
    ways = S.index_osm_ways(osm)
    assert ways["AVENIDA|BRASIL"]["pareado_m"] == pytest.approx(ways["AVENIDA|BRASIL"]["length_m"], rel=0.01)
    assert ways["AVENIDA|SOLA"]["pareado_m"] == 0


def test_default_match_is_exact_only_and_optional_methods_need_unique_candidate():
    osm = _osm(({"name": "Avenida Doutor Gastão Vidigal"}, [(-23.4205, -51.9331), (-23.4205, -51.9321)]),
               ({"name": "Rua Doutor Joao"}, [(-23.4205, -51.9331), (-23.4205, -51.9321)]),
               ({"name": "Rua Joao"}, [(-23.4205, -51.9331), (-23.4205, -51.9321)]),
               ({"name": "Avenida Prudente de Moraes"}, [(-23.4205, -51.9331), (-23.4205, -51.9321)]),
               ({"name": "Rodovia PR-317", "ref": "PR-317"}, [(-23.4205, -51.9331), (-23.4205, -51.9321)]))
    ways = S.index_osm_ways(osm)
    dump = _idx(("AVENIDA", "GASTAO VIDIGAL DOUTOR", 3), ("RUA", "JOAO DOUTOR", 3), ("AVENIDA", "PRUDENTE DE MORAIS", 3),
                ("RODOVIA", "PR 317 KM 3", 3), ("RUA", "SAO", 2))
    assert {r["match_type"] for r in S.match_streets(dump, ways)["calles"]} == {None}  # exacto: nada cruza aquí
    flex = S.flexible_aliases(dump, ways)
    assert flex["AVENIDA|GASTAO VIDIGAL DOUTOR"] == ("AVENIDA|DOUTOR GASTAO VIDIGAL", "flexible")
    assert flex["RUA|JOAO DOUTOR"] == ("RUA|DOUTOR JOAO", "flexible")  # el título se conserva: no cae en "RUA JOAO"
    tol = S.tolerance_aliases(dump, ways)
    assert tol["AVENIDA|PRUDENTE DE MORAIS"] == ("AVENIDA|PRUDENTE DE MORAES", "tolerancia")
    assert "RUA|SAO" not in tol  # palabras cortas: solo exactas
    assert S.ref_aliases(dump, ways)["RODOVIA|PR 317 KM 3"] == ("REF|PR317", "ref")
    merged = {**flex, **tol, **S.ref_aliases(dump, ways)}
    kinds = {r["nome"]: r["match_type"] for r in S.match_streets(dump, ways, merged)["calles"]}
    assert kinds["GASTAO VIDIGAL DOUTOR"] == "flexible" and kinds["PR 317 KM 3"] == "ref"


def test_optional_method_with_two_osm_candidates_is_rejected():
    pts = [(-23.4205, -51.9331), (-23.4205, -51.9321)]
    ways = S.index_osm_ways(_osm(({"name": "Rua Doutor Joao Silva"}, pts), ({"name": "Rua Joao Silva Doutor"}, pts)))
    assert S.flexible_aliases(_idx(("RUA", "SILVA DOUTOR JOAO", 2)), ways) == {}


def test_tolerance_never_flips_a_final_vowel_or_changes_two_words():
    pts = [(-23.4205, -51.9331), (-23.4205, -51.9321)]
    ways = S.index_osm_ways(_osm(({"name": "Rua Maria Silva"}, pts), ({"name": "Rua Joaquim Barbosa Lima"}, pts)))
    assert S.tolerance_aliases(_idx(("RUA", "MARIO SILVA", 2)), ways) == {}  # MARIA/MARIO: otra persona
    assert S.tolerance_aliases(_idx(("RUA", "JOAQUIN BARBOZA LIMA", 2)), ways) == {}  # dos palabras difieren
    assert "RUA|JOAQUIM BARBOSA LIMA" == S.tolerance_aliases(_idx(("RUA", "JOAQUIM BARBOZA LIMA", 2)), ways)["RUA|JOAQUIM BARBOZA LIMA"][0]


def test_oneway_minus_one_flips_direction_for_dual_carriageway_pairing():
    a = [(-23.4205, -51.9331), (-23.4205, -51.9301)]
    # drawn the same way, but one is oneway=-1 (travels the opposite way): a real dual carriageway
    osm = _osm(({"name": "Avenida Dupla", "oneway": "yes"}, a),
               ({"name": "Avenida Dupla", "oneway": "-1"}, [(-23.42055, -51.9331), (-23.42055, -51.9301)]))
    e = S.index_osm_ways(osm)["AVENIDA|DUPLA"]
    assert e["pareado_m"] == pytest.approx(e["length_m"], rel=0.01)


def test_two_dump_spellings_may_share_one_osm_street_and_rows_expose_osm_key():
    pts = [(-23.4205, -51.9331), (-23.4205, -51.9321)]
    ways = S.index_osm_ways(_osm(({"name": "Rua Doutor Joao"}, pts)))
    dump = _idx(("RUA", "DOUTOR JOAO", 4), ("RUA", "JOAO DOUTOR", 3))
    rows = S.match_streets(dump, ways, S.flexible_aliases(dump, ways))["calles"]
    assert {r["osm_key"] for r in rows} == {"RUA|DOUTOR JOAO"} and {r["match_type"] for r in rows} == {"exacto", "flexible"}


def test_report_radius_is_the_one_used():
    rep = S.match_streets({}, {}, radio_casco_m=7000)
    assert rep["resumen"]["supuestos"]["radio_casco_m"] == 7000
