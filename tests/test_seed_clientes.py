"""scripts/seed_clientes.py: validación del CSV, guardas y upsert real (Postgres desechable opcional)."""

import importlib.util
import os
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "seed_clientes", Path(__file__).resolve().parent.parent / "scripts" / "seed_clientes.py"
)
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)

HEAD = ",".join(seed.HEADER)
SECRET = "ZZ-NOMBRE-SECRETO"
PEND = "pendiente_geocodificar"


def write(tmp_path, *lines, bom=False):
    p = tmp_path / "c.csv"
    p.write_text("\n".join([HEAD, *lines]) + "\n", encoding="utf-8-sig" if bom else "utf-8")
    return p


def test_valid_rows_and_state_mapping(tmp_path):
    p = write(
        tmp_path,
        f"1,{SECRET},Neg,Rua A,B,Maringa,87000-000,-23.4,-51.9,coords_del_enlace,",
        f"2,{SECRET},Neg,Rua B,B,Maringa,87000-000,,,{PEND},n",
        bom=True,
    )
    rows, errors = seed.parse_rows(p)
    assert errors == []
    assert (rows[0]["geocode_status"], rows[0]["geocode_source"], rows[0]["lat"]) == ("ok", "usuario", -23.4)
    assert (rows[1]["geocode_status"], rows[1]["geocode_source"], rows[1]["lat"]) == ("pendiente", None, None)


@pytest.mark.parametrize(
    "line,col",
    [
        (f"1,{SECRET},N,D,B,M,C,,,coords_del_enlace,", "lat"),  # ok sin coords
        (f"1,{SECRET},N,D,B,M,C,95,-51,coords_del_enlace,", "lat"),  # lat fuera de rango
        (f"1,{SECRET},N,D,B,M,C,-23,-181,coords_del_enlace,", "lon"),
        (f"1,{SECRET},N,D,B,M,C,-23,5,{PEND},", "lat/lon"),  # pendiente con coords
        (f"1,{SECRET},N,D,B,M,C,,,otro,", "estado"),
        (f'1,{SECRET},N,D,B,M,C,"-23,4",-51,coords_del_enlace,', "lat"),  # coma decimal rechazada
    ],
)
def test_invalid_rows_report_line_and_column_only(tmp_path, line, col):
    rows, errors = seed.parse_rows(write(tmp_path, line))
    assert rows == [] and errors and errors[0][1] == col
    assert SECRET not in repr(errors)


def test_duplicate_id_and_bad_files_never_echo_content(tmp_path):
    row = f"1,{SECRET},N,D,B,M,C,,,{PEND},"
    _, errors = seed.parse_rows(write(tmp_path, row, row))
    assert errors == [(3, "id", "duplicado")]
    bad = tmp_path / "bad.csv"
    bad.write_text(f"{SECRET},x\n", encoding="utf-8")
    with pytest.raises(seed.SeedError) as e:
        seed.parse_rows(bad)
    assert SECRET not in str(e.value)
    bad.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(seed.SeedError) as e:
        seed.parse_rows(bad)
    assert "UnicodeDecodeError" in str(e.value)


def test_production_guard_and_dry_run_never_touch_the_db(tmp_path, monkeypatch, capsys):
    p = write(tmp_path, f"1,{SECRET},N,D,B,M,C,,,{PEND},")
    monkeypatch.setenv("APP_ENV", "production")
    assert seed.main(["--csv", str(p), "--user", "u", "--apply"]) == 2
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setattr(seed, "UPSERT", None)  # una escritura reventaría
    assert seed.main(["--csv", str(p), "--user", "u"]) == 0
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err and "Dry-run" in out.out


PG = os.environ.get("TEST_SEED_PG_URL")


@pytest.mark.skipif(not PG, reason="TEST_SEED_PG_URL no definido (Postgres desechable con tabla users)")
def test_reseed_is_idempotent_and_does_not_downgrade_geocoded_rows(tmp_path):
    from sqlalchemy import create_engine, text

    from app.db.bootstrap import CLIENTES_DDL

    engine = create_engine(PG)
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS clientes"))
        c.execute(text("INSERT INTO users(username) VALUES ('seedtest') ON CONFLICT DO NOTHING"))
        c.execute(text(CLIENTES_DDL))
        uid = c.execute(text("SELECT id FROM users WHERE username='seedtest'")).scalar()
    rows, _ = seed.parse_rows(
        write(tmp_path, "1,a,n,d,b,m,c,-23.4,-51.9,coords_del_enlace,", f"2,a,n,d,b,m,c,,,{PEND},")
    )
    pend, _ = seed.parse_rows(write(tmp_path, f"1,a,n,d,b,m,c,,,{PEND},"))
    for batch in (rows, rows, pend):
        with engine.begin() as c:
            c.execute(seed.UPSERT, [{**r, "user_id": uid} for r in batch])
    with engine.begin() as c:
        got = c.execute(text("SELECT external_id, geocode_status, lat FROM clientes ORDER BY 1")).fetchall()
    assert [(g[0], g[1], float(g[2]) if g[2] else None) for g in got] == [("1", "ok", -23.4), ("2", "pendiente", None)]
