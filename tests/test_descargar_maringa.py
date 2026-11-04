"""Streaming ZIP de scripts/descargar_maringa.py con filas inventadas (sin datos reales)."""
from __future__ import annotations

import io
import zipfile

import pytest

from scripts import descargar_maringa as dm


def _row(i: int, muni: str, uf: str = "PR", extra: str = "") -> list[str]:
    r = [""] * 30
    r[0], r[4] = f"{i:08d}", f"LOJA {i}{extra}"
    r[19], r[20] = uf, muni
    return r


ROWS = [_row(1, "7691"), _row(2, "7667"), _row(3, "8461", extra="\nCON SALTO"), _row(4, "7691", uf="SP"), _row(5, "7731")]
WANTED = {"7691", "8461", "7731"}


def _csv_bytes(rows) -> bytes:
    return "".join(";".join(f'"{v}"' for v in r) + "\n" for r in rows).encode("latin-1")


class NonSeekable(io.RawIOBase):
    """Fuerza a zipfile a escribir con data descriptor (bit 3)."""

    def __init__(self):
        self.data = bytearray()

    def writable(self):
        return True

    def write(self, b):
        self.data += b
        return len(b)


def make_zip(payload: bytes, method=zipfile.ZIP_DEFLATED, descriptor=True) -> bytes:
    if descriptor:
        sink = NonSeekable()
        with zipfile.ZipFile(sink, "w", method) as zf:
            zf.writestr("X.ESTABELE", payload)
        return bytes(sink.data)
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", method) as zf:
        zf.writestr("X.ESTABELE", payload)
    return bio.getvalue()


class Trickle:
    """Respuesta HTTP falsa que entrega `step` bytes por lectura."""

    def __init__(self, data: bytes, step: int, length: int | None = -1):
        self.data, self.step, self.pos = data, step, 0
        self.headers = {"Content-Length": str(len(data) if length == -1 else length), "Last-Modified": "Tue, 15 Sep 2026 10:00:00 GMT"}

    def read(self, n=-1):
        n = self.step if n < 0 else min(n, self.step)
        out = self.data[self.pos : self.pos + n]
        self.pos += len(out)
        return out

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fetch(data: bytes, step: int, **kw):
    return dm.fetch_part("2026-09", "Estabelecimentos0.zip", WANTED, opener=lambda url: Trickle(data, step, **kw), sleep=lambda s: None)


EXPECTED = [r[0] for r in ROWS if r[20] in WANTED and r[19] == "PR"]


@pytest.mark.parametrize("step", [1, 7, 4096, 1 << 20])
@pytest.mark.parametrize("kind", ["deflate_descriptor", "deflate", "stored"])
def test_streams_all_layouts(kind, step):
    payload = _csv_bytes(ROWS)
    data = {"deflate_descriptor": lambda: make_zip(payload), "deflate": lambda: make_zip(payload, descriptor=False),
            "stored": lambda: make_zip(payload, zipfile.ZIP_STORED, descriptor=False)}[kind]()
    rows, meta = fetch(data, step)
    assert [r[0] for r in rows] == EXPECTED  # incluye la fila con salto de línea entre comillas
    assert meta["filas_leidas"] == len(ROWS) and meta["intentos"] == 1


def test_truncated_download_fails_after_retries():
    data = make_zip(_csv_bytes(ROWS))
    for cut in (len(data) // 2, len(data) - 10):  # a mitad del deflate y dentro del central directory
        with pytest.raises(SystemExit):
            fetch(data[:cut], 64, length=len(data))  # el servidor anunció el tamaño completo


def test_content_length_mismatch_is_rejected():
    with pytest.raises(SystemExit):
        fetch(make_zip(_csv_bytes(ROWS)), 64, length=10**9)


def test_wrong_column_count_is_a_layout_error_not_retried():
    bad = _csv_bytes([ROWS[0][:29]])
    calls = []
    with pytest.raises(dm.LayoutError):
        dm.fetch_part("2026-09", "x.zip", WANTED, opener=lambda u: calls.append(u) or Trickle(make_zip(bad), 4096), sleep=lambda s: None)
    assert len(calls) == 1


def test_retry_restarts_the_part_without_duplicate_rows():
    good = make_zip(_csv_bytes(ROWS))
    attempts = []

    def opener(url):
        attempts.append(url)
        return Trickle(good[: len(good) // 2] if len(attempts) == 1 else good, 4096, length=len(good))

    rows, meta = dm.fetch_part("2026-09", "x.zip", WANTED, opener=opener, sleep=lambda s: None)
    assert [r[0] for r in rows] == EXPECTED and meta["intentos"] == 2
    assert attempts[0] != attempts[1]  # rota la URL candidata


def test_directory_entry_is_skipped():
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("carpeta/", b"")
        zf.writestr("X.ESTABELE", _csv_bytes(ROWS))
    rows, meta = fetch(bio.getvalue(), 4096)
    assert [r[0] for r in rows] == EXPECTED and meta["intentos"] == 1


def test_unsupported_method_is_not_retried():
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_BZIP2) as zf:
        zf.writestr("X.ESTABELE", _csv_bytes(ROWS))
    calls = []
    with pytest.raises(dm.ZipFormatError):
        dm.fetch_part("2026-09", "x.zip", WANTED, opener=lambda u: calls.append(u) or Trickle(bio.getvalue(), 4096), sleep=lambda s: None)
    assert len(calls) == 1


def test_retry_after_rows_were_accumulated_leaves_no_duplicates():
    many = [_row(i, "7691") for i in range(1, 4000)]
    good = make_zip(_csv_bytes(many))
    attempts = []

    def opener(url):
        attempts.append(url)
        data = good[: int(len(good) * 0.9)] if len(attempts) == 1 else good  # falla tras haber acumulado filas
        return Trickle(data, 65536, length=len(good))

    rows, meta = dm.fetch_part("2026-09", "x.zip", WANTED, opener=opener, sleep=lambda s: None)
    assert len(rows) == len(many) and len({r[0] for r in rows}) == len(many) and meta["intentos"] == 2


def test_errors_do_not_echo_row_contents():
    secret = _row(9, "7691", extra="SEGREDO-NAO-VAZAR")[:25]
    with pytest.raises(dm.LayoutError) as err:
        fetch(make_zip(_csv_bytes([secret])), 4096)
    assert "SEGREDO" not in str(err.value)
