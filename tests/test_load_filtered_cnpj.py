import codecs
import csv

import pytest

import load_filtered_cnpj as lf
from load_filtered_cnpj import parse_rows, row_to_dict


def make_row(sit="2", mun="7691", cnae="6201501"):
    r = [""] * 30
    r[0:6] = ["123", "1", "9", "1", " Loja X ", sit]
    r[11], r[14], r[15], r[17], r[20] = cnae, "Rua A", "10", "Centro", mun
    return r


def write_csv(tmp_path, rows):
    p = tmp_path / "f.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    return str(p)


def test_row_to_dict_maps_columns():
    d = row_to_dict(make_row())
    assert d["cnpj_completo"] == "00000123000109"
    assert d["municipio"] == "Maringá"
    assert d["business_type"] == "tech"
    assert d["nome_fantasia"] == "Loja X"
    assert d["logradouro"] == "Rua A" and d["numero"] == "10" and d["bairro"] == "Centro"


def test_non_tech_cnae_is_repairs():
    assert row_to_dict(make_row(cnae="9529699"))["business_type"] == "repairs"


@pytest.mark.parametrize("row,reason", [
    (["1", "2", "3"], "corta"),
    (make_row(mun="9999"), "municipio_desconocido"),
    (make_row(sit="3"), "inactiva"),
])
def test_rejection_reasons(tmp_path, row, reason):
    rows, rejected = parse_rows(write_csv(tmp_path, [make_row(), row]))
    assert len(rows) == 1
    assert [(line, m) for line, m, _ in rejected] == [(2, reason)]


def test_non_numeric_situacao_in_valid_municipio_is_inactive(tmp_path):
    _, rejected = parse_rows(write_csv(tmp_path, [make_row(sit="x")]))
    assert rejected[0][1] == "inactiva"


def _accent_row():
    r = make_row()
    r[4], r[14] = "Ótica Maringá", "Avenida São Paulo"
    return r


def _write_bytes(tmp_path, encoding, bom=b""):
    p = tmp_path / "enc.csv"
    p.write_bytes(bom + _csv_text(_accent_row()).encode(encoding))
    return str(p)


def _csv_text(row):
    import io
    buf = io.StringIO()
    csv.writer(buf).writerow(row)
    return buf.getvalue()


@pytest.mark.parametrize("encoding,bom", [("utf-8", b""), ("latin-1", b""), ("utf-8", codecs.BOM_UTF8)])
def test_encoding_is_detected_without_flag(tmp_path, encoding, bom):
    rows, rejected = parse_rows(_write_bytes(tmp_path, encoding, bom))
    assert rejected == []
    assert rows[0]["cnpj_basico"] == "00000123"
    assert rows[0]["nome_fantasia"] == "Ótica Maringá"
    assert rows[0]["logradouro"] == "Avenida São Paulo"


def _run(monkeypatch, path, *flags):
    def no_db(*a, **k):
        raise AssertionError("no debe conectarse a la base")

    monkeypatch.setattr(lf, "prod_url", lambda: "postgresql://fake")  # nunca leer PROD_DATABASE_URL
    monkeypatch.setattr(lf.psycopg2, "connect", no_db)
    monkeypatch.setattr("sys.argv", ["load_filtered_cnpj.py", path, *flags])
    lf.main()


def test_apply_refuses_on_format_errors(tmp_path, monkeypatch):
    path = write_csv(tmp_path, [make_row(), ["1"]])
    with pytest.raises(SystemExit) as e:
        _run(monkeypatch, path, "--apply")
    assert "se niega" in str(e.value)  # sale antes de conectarse (connect fallaría con AssertionError)


def test_inactive_rows_do_not_block_apply(tmp_path, monkeypatch):
    path = write_csv(tmp_path, [make_row(), make_row(sit="3")])
    with pytest.raises(AssertionError, match="no debe conectarse"):
        _run(monkeypatch, path, "--apply")  # llegó a conectarse => no lo bloqueó la inactiva


class _Cur:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append(sql)

    def fetchone(self):
        return None  # information_schema no devuelve la columna


def test_apply_exits_when_geocode_attempts_column_is_missing(tmp_path, monkeypatch):
    cur = _Cur()
    conn = type("C", (), {"set_session": lambda self, **k: None, "cursor": lambda self: cur})()
    path = write_csv(tmp_path, [make_row()])
    monkeypatch.setattr(lf, "prod_url", lambda: "postgresql://fake")
    monkeypatch.setattr(lf.psycopg2, "connect", lambda *a, **k: conn)
    monkeypatch.setattr("sys.argv", ["load_filtered_cnpj.py", path, "--apply"])
    with pytest.raises(SystemExit) as e:
        lf.main()
    assert "008_geocode_attempts.sql" in str(e.value)
    assert len(cur.sql) == 1  # solo la consulta a information_schema; no llegó a escribir
