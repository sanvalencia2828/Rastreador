#!/usr/bin/env python3
"""
scripts/descargar_maringa.py
Descarga el volcado CNPJ más reciente de la Receita Federal (las 10 partes de
Estabelecimentos) y se queda solo con los establecimientos de los municipios
pedidos (Maringá por defecto). Con --mes todo va en STREAMING: la respuesta HTTP
se descomprime al vuelo y nunca se guarda un ZIP en disco (cada parte pesa ~2,2 GB);
el resultado pesa pocas decenas de MB.

Fuente oficial (carpetas mensuales AAAA-MM):
    https://arquivos.receitafederal.gov.br/index.php/s/YggdBLfdninEJX9

Uso:
    python scripts/descargar_maringa.py --mes 2026-09
    python scripts/descargar_maringa.py --mes 2026-09 --municipios 7691,8461,7731,7687   # región de Maringá
    python scripts/descargar_maringa.py --zips "<carpeta>/Estabelecimentos*.zip"   # ZIPs ya bajados a mano

Garantías: las filas de cada parte se acumulan en memoria y solo se aceptan si la parte
llegó completa (fin del flujo deflate, CRC de cada miembro, firma del central directory y, si el
servidor lo anuncia, Content-Length); si no,
se reinicia ESA parte (3 intentos). El CSV final se escribe en .tmp y se renombra al terminar.

Salida: <RASTREADOR_DATA_DIR o .data>/maringa/<mes>_<municipios>.ESTABELE con el mismo formato crudo de la
Receita, más .data/maringa/meta/<nombre>.json con metadatos agregados (sin filas).
Va en su propia carpeta para no mezclarse con otros volcados:
    ML__DATA__INPUT_GLOB=".data/maringa/2026-09_*.ESTABELE" python -m ml run
    python scripts/analizar_zonas.py --estabelecimentos ".data/maringa/2026-09_*.ESTABELE"

Códigos de municipio de la Receita (no son IBGE), verificados por CEP en el volcado:
Maringá 7691 · Sarandi 8461 · Paiçandu 7731 · Marialva 7687 · Londrina 7667 · Cambé 7471.
"""

from __future__ import annotations

import argparse
import csv
import glob
import http.client
import json
import os
import struct
import sys
import time
import urllib.request
import zipfile
import zlib
from email.utils import parsedate_to_datetime

SHARE = "https://arquivos.receitafederal.gov.br/index.php/s/YggdBLfdninEJX9"
UF_IDX, MUNICIPIO_IDX, N_COLS = 19, 20, 30
CHUNK = 1 << 20
MAX_ATTEMPTS = 3
BACKOFFS = (5, 20)
MAX_LAST_MODIFIED_SPREAD_DAYS = 7
LOCAL, SIG_DD = b"PK\x03\x04", b"PK\x07\x08"
END_SIGS = (b"PK\x01\x02", b"PK\x05\x06", b"PK\x06\x06")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
csv.field_size_limit(1 << 16)  # una fila corrupta con comillas abiertas no debe acumular el miembro entero


class LayoutError(Exception):
    """El layout de la Receita cambió: no es reintentable."""


class ZipStreamError(ValueError):
    """Flujo ZIP truncado o corrupto: reintentable."""


class ZipFormatError(Exception):
    """Formato ZIP no soportado o corrupto de forma determinista: reintentar no sirve."""


def candidate_urls(month: str, name: str) -> list[str]:
    token = SHARE.rsplit("/", 1)[-1]
    base = SHARE.split("/index.php")[0]
    return [
        f"{base}/public.php/dav/files/{token}/{month}/{name}",  # la que sirve el ZIP (la otra responde 200 vacío)
        f"{SHARE}/download?path=/{month}&files={name}",
    ]


def _open(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "rastreador-cnpj/1.0"})
    return urllib.request.urlopen(req, timeout=120)


# ---------------------------------------------------------------- lectura ZIP en streaming
class _Buf:
    """Lector con buffer sobre algo con .read(n) (no seekable)."""

    def __init__(self, src):
        self.src, self.b, self.total = src, bytearray(), 0

    def _pull(self) -> bool:
        d = self.src.read(1 << 16)
        if not d:
            return False
        self.total += len(d)
        self.b += d
        return True

    def read_exact(self, n: int) -> bytes:
        while len(self.b) < n:
            if not self._pull():
                raise ZipStreamError("flujo truncado")
        out = bytes(self.b[:n])
        del self.b[:n]
        return out

    def read_some(self, n: int) -> bytes:
        if not self.b and not self._pull():
            raise ZipStreamError("flujo truncado")
        out = bytes(self.b[:n])
        del self.b[:n]
        return out

    def peek(self, n: int) -> bytes:
        while len(self.b) < n and self._pull():
            pass
        return bytes(self.b[:n])

    def unread(self, data: bytes) -> None:
        self.b[:0] = data

    def drain(self) -> None:
        while self._pull():
            self.b.clear()


def _member_chunks(buf: _Buf, method: int, csize: int, info: dict):
    crc = 0
    if method == 0:
        left = csize
        while left:
            d = buf.read_some(min(CHUNK, left))
            left -= len(d)
            crc = zlib.crc32(d, crc)
            yield d
    else:
        dec = zlib.decompressobj(-15)
        while not dec.eof:
            out = dec.decompress(buf.read_some(CHUNK), CHUNK)
            while True:
                if out:
                    crc = zlib.crc32(out, crc)
                    yield out
                if dec.eof:
                    break
                out = dec.decompress(dec.unconsumed_tail or b"", CHUNK)
                if not out and not dec.unconsumed_tail:
                    break
        buf.unread(dec.unused_data)
    info["crc"], info["finished"] = crc, True


def iter_members(buf: _Buf):
    """Entrega (nombre, trozos); el consumidor debe agotar los trozos antes de pedir el siguiente miembro."""
    n_members = 0
    while True:
        sig = buf.read_exact(4)
        if sig in END_SIGS:
            buf.unread(sig)
            break
        if sig != LOCAL:
            raise ZipFormatError(f"firma inesperada {sig!r}")
        _ver, flags, method, _t, _d, hdr_crc, csize, _usize, n, m = struct.unpack("<HHHHHIIIHH", buf.read_exact(26))
        name = buf.read_exact(n).decode("cp437", "replace")
        buf.read_exact(m)
        if flags & 0x41:
            raise ZipFormatError("miembro cifrado")
        if method not in (0, 8):
            raise ZipFormatError(f"método de compresión {method} no soportado")
        if method == 0 and flags & 8:
            raise ZipFormatError("miembro sin comprimir con data descriptor: tamaño desconocido")
        info: dict = {}
        yield name, _member_chunks(buf, method, csize, info)
        if not info.get("finished"):
            raise ZipStreamError(f"miembro {name} no consumido por completo")
        expected = hdr_crc
        if flags & 8:
            head = buf.peek(28)
            s = 4 if head[:4] == SIG_DD else 0
            expected = struct.unpack("<I", head[s : s + 4])[0]
            for size in (12, 20):  # descriptor zip32 / zip64
                if head[s + size : s + size + 4] in END_SIGS + (LOCAL,):
                    buf.read_exact(s + size)
                    break
            else:
                raise ZipStreamError("data descriptor no reconocido")
        if expected != info["crc"]:
            raise ZipStreamError(f"CRC distinto en {name}")
        n_members += 1
    if n_members == 0:
        raise ZipStreamError("el ZIP no contiene miembros")


# ---------------------------------------------------------------- filtro de filas
def _lines(chunks):
    tail = ""
    for c in chunks:
        parts = (tail + c.decode("latin-1")).split("\n")  # no str.splitlines: parte en \x85, válido en latin-1
        tail = parts.pop()
        for p in parts:
            yield p + "\n"
    if tail:
        yield tail


def filter_chunks(chunks, municipios: set[str], rows: list) -> int:
    """Añade a `rows` las filas de los municipios pedidos (UF=PR); devuelve cuántas filas leyó."""
    read = 0
    try:
        for row in csv.reader(_lines(chunks), delimiter=";", quotechar='"'):
            read += 1
            if len(row) != N_COLS:
                raise LayoutError(f"fila con {len(row)} columnas (se esperaban {N_COLS}); "
                                  "el layout cambió, revisar ml/contracts/estabelecimentos_raw.yaml")
            if row[MUNICIPIO_IDX] in municipios and row[UF_IDX] == "PR":
                rows.append(row)
    except csv.Error as err:  # un campo gigante o comillas rotas se repetirían igual en cada intento
        raise LayoutError(f"CSV inválido ({err})") from None
    return read


def fetch_part(month: str, name: str, municipios: set[str], opener=_open, sleep=time.sleep) -> tuple[list, dict]:
    """Una parte (Estabelecimentos<i>.zip) en streaming; reinicia la parte entera si algo falla."""
    urls = candidate_urls(month, name)
    last: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        rows: list = []  # estado del intento: se descarta entero si falla
        try:
            with opener(urls[attempt % len(urls)]) as resp:
                length = int(resp.headers.get("Content-Length") or 0)
                modified = resp.headers.get("Last-Modified")
                buf = _Buf(resp)
                read, members = 0, {}
                for member, chunks in iter_members(buf):
                    if member.endswith("/"):
                        for _ in chunks:  # hay que agotar el miembro aunque no tenga datos
                            pass
                        continue
                    members[member] = filter_chunks(chunks, municipios, rows)
                    read += members[member]
                buf.drain()
                if length and buf.total != length:
                    raise ZipStreamError(f"descarga incompleta: {buf.total} de {length} bytes")
            return rows, {"archivo": name, "bytes": buf.total, "last_modified": modified, "filas_leidas": read,
                          "filas_guardadas": len(rows), "miembros": members, "intentos": attempt + 1}
        except (OSError, zlib.error, ValueError, http.client.HTTPException) as err:
            last = err
            print(f"  {name}: intento {attempt + 1}/{MAX_ATTEMPTS} falló ({type(err).__name__}: {err})", file=sys.stderr)
            if attempt < MAX_ATTEMPTS - 1:
                sleep(BACKOFFS[min(attempt, len(BACKOFFS) - 1)])
    raise SystemExit(f"No se pudo descargar {name} de {month}: {last}\n"
                     f"Descárgalo a mano desde {SHARE} y usa --zips.")


def filter_local_zip(path: str, municipios: set[str]) -> tuple[list, dict]:
    rows: list = []
    read = 0
    with zipfile.ZipFile(path) as zf:
        for member in zf.namelist():
            with zf.open(member) as raw:
                read += filter_chunks(iter(lambda: raw.read(CHUNK), b""), municipios, rows)
    return rows, {"archivo": os.path.basename(path), "filas_leidas": read, "filas_guardadas": len(rows)}


def check_same_dump(parts: list[dict]) -> None:
    try:
        dates = [parsedate_to_datetime(p["last_modified"]) for p in parts if p.get("last_modified")]
    except (TypeError, ValueError):
        print("Aviso: Last-Modified ilegible; no se pudo comprobar que las partes son del mismo volcado", file=sys.stderr)
        return
    if dates and (max(dates) - min(dates)).days > MAX_LAST_MODIFIED_SPREAD_DAYS:
        raise SystemExit("Las partes tienen Last-Modified muy distintos: podrían ser de volcados diferentes")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mes", help="carpeta AAAA-MM de la Receita (la más reciente publicada)")
    p.add_argument("--municipios", default="7691", help="códigos Receita separados por coma (7691 = Maringá)")
    p.add_argument("--zips", help="glob de ZIPs ya descargados (omite la descarga)")
    args = p.parse_args()
    municipios = {m.strip() for m in args.municipios.split(",") if m.strip()}

    if args.zips:
        sources, label = sorted(glob.glob(args.zips)), "manual"
        if not sources:
            raise SystemExit("No se encontraron ZIPs")
    elif args.mes:
        sources, label = [f"Estabelecimentos{i}.zip" for i in range(10)], args.mes
    else:
        p.error("indica --mes AAAA-MM o --zips")

    out_dir = os.path.join(os.environ.get("RASTREADOR_DATA_DIR") or os.path.join(REPO_ROOT, ".data"), "maringa")
    os.makedirs(os.path.join(out_dir, "meta"), exist_ok=True)
    stem = f"{label}_{'-'.join(sorted(municipios))}"
    out_path = os.path.join(out_dir, f"{stem}.ESTABELE")
    all_rows: list = []
    parts: list[dict] = []
    for src in sources:
        try:
            rows, meta = filter_local_zip(src, municipios) if args.zips else fetch_part(args.mes, src, municipios)
        except LayoutError as err:
            raise SystemExit(f"{os.path.basename(src)}: {err}") from None
        all_rows += rows
        parts.append(meta)
        print(f"  {meta['archivo']}: {meta['filas_leidas']:,} filas · {meta['filas_guardadas']:,} de {sorted(municipios)}")
    if args.mes:
        check_same_dump(parts)

    if not all_rows:  # no pisar un .ESTABELE bueno con uno vacío
        raise SystemExit("0 filas: ¿código de municipio correcto? (Receita, no IBGE). No se escribió nada.")
    tmp = out_path + ".tmp"
    try:
        with open(tmp, "w", encoding="latin-1", newline="") as out:
            csv.writer(out, delimiter=";", quotechar='"', quoting=csv.QUOTE_ALL, lineterminator="\n").writerows(all_rows)
        os.replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    meta_path = os.path.join(out_dir, "meta", f"{stem}.json")
    try:
        with open(meta_path + ".tmp", "w", encoding="utf-8") as f:  # solo metadatos agregados, nunca filas
            json.dump({"mes": label, "municipios": sorted(municipios), "filas_guardadas": len(all_rows), "partes": parts}, f, indent=1)
        os.replace(meta_path + ".tmp", meta_path)
    finally:
        if os.path.exists(meta_path + ".tmp"):
            os.remove(meta_path + ".tmp")
    print(f"\nListo: {len(all_rows):,} establecimientos de {sum(x['filas_leidas'] for x in parts):,} -> {out_path}")


if __name__ == "__main__":
    main()
