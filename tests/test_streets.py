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
