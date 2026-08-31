#!/usr/bin/env python3
"""Dump and restore Digitakt II song blobs inside an Elektron Transfer .dt2prj.

The Transfer payload is LZ4-linked 32 KiB blocks, not raw song bytes. This
script decompresses the project, copies the 16 uncompressed song slots (3072
bytes each), and recompresses on restore so the device can import the file.

Dump:
  python ./dt_song_mgmt.py project.dt2prj
  → ./SONGS_<stem>/00_<name>.bin … 15_<name>.bin  (16 × 3072-byte slots)

Restore (overwrites the .dt2prj; writes a .bak first):
    python ./dt_song_mgmt.py project.dt2prj ./SONGS_<stem>
    python ./dt_song_mgmt.py project.dt2prj ./SONGS_<stem> NEW_NAME

Restore matches files by the NN_ slot prefix. Slots with no file
are cleared to an empty song (the folder is the full 16-slot setlist).

NEW_NAME - new project name (not just file/folder names but actual name in .dt2prj payload)
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import shutil
import struct
import sys
import zipfile
from pathlib import Path

MAGIC_TAIL = bytes.fromhex("bacef00c")
MAGIC_HEAD = bytes.fromhex("beefbace")
SONG_SLOTS = 16
SONG_SIZE = 3072  # uncompressed songStorage record
SONG_TABLE_LEN = SONG_SLOTS * SONG_SIZE
LZ4_BLOCK = 32768
# Transfer wrapper around the packed project body:
#   [31-byte header starting ac11d303] [body] [crc32][size][aaa1daaa]
PAYLOAD_HEAD_LEN = 31
PAYLOAD_TAIL_LEN = 12  # checksum + size + tail magic
PAYLOAD_WRAP_LEN = PAYLOAD_HEAD_LEN + PAYLOAD_TAIL_LEN  # 43
UNCOMP_SIZE_OFF = 25  # u32be uncompressed project size in the 31-byte head
# +Drive / Transfer project title: 13 bytes, NUL-terminated, '~'-padded.
PROJECT_NAME_LEN = 13
SONG_NAME_LEN = 16

PAYLOAD_HEAD_MAGIC = bytes.fromhex("ac11d303")
PAYLOAD_TAIL_MAGIC = bytes.fromhex("aaa1daaa")

NAME_CHAR = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_~ -#$")


def die(msg: str, code: int = 1) -> None:
    print(f"dt_song_mgmt: {msg}", file=sys.stderr)
    raise SystemExit(code)


def payload_name(manifest: dict) -> str:
    name = manifest.get("Payload")
    if not name:
        die("manifest.json has no Payload")
    return name


def read_project(prj: Path) -> tuple[dict, bytes, list[tuple[zipfile.ZipInfo, bytes]]]:
    if not zipfile.is_zipfile(prj):
        die(f"not a zip/.dt2prj: {prj}")
    members: list[tuple[zipfile.ZipInfo, bytes]] = []
    with zipfile.ZipFile(prj, "r") as zf:
        try:
            manifest = json.loads(zf.read("manifest.json"))
        except KeyError:
            die("manifest.json missing from archive")
        pname = payload_name(manifest)
        try:
            payload = zf.read(pname)
        except KeyError:
            die(f"payload {pname!r} missing from archive")
        for info in zf.infolist():
            members.append((info, zf.read(info.filename)))
    return manifest, payload, members


def write_project(
    prj: Path,
    members: list[tuple[zipfile.ZipInfo, bytes]],
    pname: str,
    payload: bytes,
    new_pname: str | None = None,
) -> None:
    out_name = new_pname or pname
    tmp = prj.with_suffix(prj.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w") as zf:
        for info, data in members:
            filename = info.filename
            blob = data
            if filename == "manifest.json" and new_pname:
                man = json.loads(data)
                man["Payload"] = new_pname
                blob = (json.dumps(man, indent=2) + "\n").encode("utf-8")
            elif filename == pname:
                filename = out_name
                blob = payload
            out = zipfile.ZipInfo(filename=filename, date_time=info.date_time)
            out.compress_type = info.compress_type
            out.external_attr = info.external_attr
            zf.writestr(out, blob)
    tmp.replace(prj)


def clean_project_name(name: str) -> str:
    out: list[str] = []
    for ch in name.strip():
        if ch.islower() and ch.upper() in NAME_CHAR:
            out.append(ch.upper())
        elif ch in NAME_CHAR:
            out.append(ch)
        elif ch.isspace():
            out.append("~")
    cleaned = "".join(out).strip("~") or "PROJECT"
    if len(cleaned) > PROJECT_NAME_LEN:
        print(f"note: project name truncated to {PROJECT_NAME_LEN} characters")
        cleaned = cleaned[:PROJECT_NAME_LEN]
    return cleaned


def encode_project_name_field(name: str) -> bytes:
    raw = clean_project_name(name).encode("latin-1")
    if len(raw) >= PROJECT_NAME_LEN:
        return raw[:PROJECT_NAME_LEN]
    return raw + b"\x00" + b"~" * (PROJECT_NAME_LEN - len(raw) - 1)


def read_project_name_field(raw: bytes) -> tuple[int, str]:
    i = raw.find(MAGIC_HEAD)
    if i < 0:
        die("no beefbace marker in project — cannot locate project name")
    off = i + 4 + 4
    if off + PROJECT_NAME_LEN > len(raw):
        die("project too short for project name field")
    field = raw[off : off + PROJECT_NAME_LEN]
    n = field.find(b"\x00")
    name = field if n < 0 else field[:n]
    return off, name.decode("latin-1").rstrip("~")


def patch_project_name(raw: bytes, new_name: str) -> tuple[bytes, str, str]:
    off, old = read_project_name_field(raw)
    cleaned = clean_project_name(new_name)
    field = encode_project_name_field(cleaned)
    patched = bytearray(raw)
    patched[off : off + PROJECT_NAME_LEN] = field
    return bytes(patched), cleaned, old


def _crc32_table() -> tuple[int, ...]:
    tbl: list[int] = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
        tbl.append(c)
    return tuple(tbl)


_CRC32_TABLE = _crc32_table()


def payload_crc32(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = _CRC32_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return (~crc) & 0xFFFFFFFF


# --- LZ4 (raw blocks, 32 KiB, linked on decompress) ---

_LZ4 = None
_LZ4_TRIED = False


def _lz4_lib():
    global _LZ4, _LZ4_TRIED
    if _LZ4_TRIED:
        return _LZ4
    _LZ4_TRIED = True
    path = ctypes.util.find_library("lz4")
    if not path:
        return None
    lib = ctypes.CDLL(path)
    lib.LZ4_compressBound.argtypes = [ctypes.c_int]
    lib.LZ4_compressBound.restype = ctypes.c_int
    lib.LZ4_compress_default.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_int,
    ]
    lib.LZ4_compress_default.restype = ctypes.c_int
    _LZ4 = lib
    return lib


def lz4_decompress_block(src: bytes, out: bytearray) -> None:
    """Decode one raw LZ4 block, appending into `out` (linked lookback)."""
    i = 0
    n = len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                if i >= n:
                    raise ValueError("truncated LZ4 literal length")
                extra = src[i]
                i += 1
                lit += extra
                if extra != 255:
                    break
        if i + lit > n:
            raise ValueError("truncated LZ4 literals")
        out.extend(src[i : i + lit])
        i += lit
        if i >= n:
            break
        if i + 2 > n:
            raise ValueError("truncated LZ4 match offset")
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        if offset == 0 or offset > len(out):
            raise ValueError(f"bad LZ4 offset {offset} (out {len(out)})")
        mlen = (token & 15) + 4
        if (token & 15) == 15:
            while True:
                if i >= n:
                    raise ValueError("truncated LZ4 match length")
                extra = src[i]
                i += 1
                mlen += extra
                if extra != 255:
                    break
        start = len(out) - offset
        for _ in range(mlen):
            out.append(out[start])
            start += 1


def _lz4_compress_py(src: bytes) -> bytes:
    """Independent raw LZ4 block (greedy hash matcher)."""
    n = len(src)
    if n == 0:
        return b"\x00"
    HASH_LOG = 12
    HASH_SIZE = 1 << HASH_LOG
    table = [-1] * HASH_SIZE
    out = bytearray()
    i = 0
    anchor = 0

    def hash4(p: int) -> int:
        v = int.from_bytes(src[p : p + 4], "little")
        return ((v * 2654435761) & 0xFFFFFFFF) >> (32 - HASH_LOG)

    def emit(lit_from: int, lit_to: int, match_off: int | None, match_len: int) -> None:
        literals = src[lit_from:lit_to]
        nlit = len(literals)
        token_lit = 15 if nlit >= 15 else nlit
        if match_off is None:
            out.append(token_lit << 4)
            if nlit >= 15:
                rest = nlit - 15
                while rest >= 255:
                    out.append(255)
                    rest -= 255
                out.append(rest)
            out.extend(literals)
            return
        nml = match_len - 4
        token_ml = 15 if nml >= 15 else nml
        out.append((token_lit << 4) | token_ml)
        if nlit >= 15:
            rest = nlit - 15
            while rest >= 255:
                out.append(255)
                rest -= 255
            out.append(rest)
        out.extend(literals)
        out.append(match_off & 0xFF)
        out.append((match_off >> 8) & 0xFF)
        if nml >= 15:
            rest = nml - 15
            while rest >= 255:
                out.append(255)
                rest -= 255
            out.append(rest)

    last_match = n - 12  # LZ4 last sequence: ≥5 bytes of literals, ≥12 before end for matches
    while i < last_match:
        h = hash4(i)
        ref = table[h]
        table[h] = i
        if ref < 0 or i - ref >= 65536 or src[ref : ref + 4] != src[i : i + 4]:
            i += 1
            continue
        ml = 4
        while i + ml < n - 5 and src[ref + ml] == src[i + ml]:
            ml += 1
        emit(anchor, i, i - ref, ml)
        i += ml
        anchor = i
        if i < last_match:
            table[hash4(i - 2)] = i - 2
    emit(anchor, n, None, 0)
    return bytes(out)


def lz4_compress_block(src: bytes) -> bytes:
    lib = _lz4_lib()
    if lib is not None:
        bound = lib.LZ4_compressBound(len(src))
        buf = ctypes.create_string_buffer(bound)
        n = lib.LZ4_compress_default(src, buf, len(src), bound)
        if n <= 0:
            die("lz4 compress failed")
        return buf.raw[:n]
    return _lz4_compress_py(src)


def unwrap_payload(payload: bytes) -> tuple[bytes, list[bytes]]:
    """Split Transfer payload into header + LZ4 block list."""
    if len(payload) < PAYLOAD_WRAP_LEN:
        die("payload too short for Transfer wrapper")
    if payload[:4] != PAYLOAD_HEAD_MAGIC:
        die("payload missing Transfer head magic (ac11d303)")
    if payload[-4:] != PAYLOAD_TAIL_MAGIC:
        die("payload missing Transfer tail magic (aaa1daaa)")
    i = PAYLOAD_HEAD_LEN
    blocks: list[bytes] = []
    end = len(payload) - PAYLOAD_TAIL_LEN
    while i + 4 <= end:
        n = struct.unpack_from(">I", payload, i)[0]
        i += 4
        if n == 0:
            return payload[:PAYLOAD_HEAD_LEN], blocks
        if n < 0 or i + n > end:
            die("payload chunk list is corrupt")
        blocks.append(payload[i : i + n])
        i += n
    die("payload chunk list is corrupt (no terminating 0-length chunk)")
    raise AssertionError


def decompress_blocks(blocks: list[bytes]) -> bytes:
    out = bytearray()
    try:
        for b in blocks:
            lz4_decompress_block(b, out)
    except ValueError as e:
        die(
            f"LZ4 decompress failed ({e}). Restore into an original Transfer "
            "export, not a previously broken file."
        )
    return bytes(out)


def compress_raw(raw: bytes) -> list[bytes]:
    blocks: list[bytes] = []
    for i in range(0, len(raw), LZ4_BLOCK):
        blocks.append(lz4_compress_block(raw[i : i + LZ4_BLOCK]))
    return blocks


def wrap_payload(head: bytes, blocks: list[bytes]) -> bytes:
    """Rebuild Transfer TLV framing, uncompressed-size, CRC32 around LZ4 blocks."""
    if len(head) < PAYLOAD_HEAD_LEN:
        die("Transfer head too short")
    body = b"".join(struct.pack(">I", len(c)) + c for c in blocks) + struct.pack(">I", 0)
    crc = payload_crc32(body)
    return (
        head[:PAYLOAD_HEAD_LEN]
        + body
        + struct.pack(">I", crc)
        + struct.pack(">I", len(body))
        + PAYLOAD_TAIL_MAGIC
    )


def set_uncompressed_size(head: bytes, size: int) -> bytes:
    h = bytearray(head[:PAYLOAD_HEAD_LEN])
    if len(h) < UNCOMP_SIZE_OFF + 4:
        die("Transfer head too short for uncompressed size")
    struct.pack_into(">I", h, UNCOMP_SIZE_OFF, size)
    return bytes(h)


def unpack_project(payload: bytes) -> tuple[bytes, bytes]:
    head, blocks = unwrap_payload(payload)
    raw = decompress_blocks(blocks)
    stored = struct.unpack_from(">I", head, UNCOMP_SIZE_OFF)[0]
    if stored != len(raw):
        print(f"note: header uncompressed size {stored} != decoded {len(raw)}")
    return head, raw


def pack_project(head: bytes, raw: bytes) -> bytes:
    head = set_uncompressed_size(head, len(raw))
    return wrap_payload(head, compress_raw(raw))


def song_table_off(raw: bytes) -> int:
    if len(raw) < SONG_TABLE_LEN + 4:
        die("uncompressed project too short to hold 16 songs")
    if raw[-4:] != MAGIC_TAIL:
        die("uncompressed project does not end with bacef00c")
    off = len(raw) - SONG_TABLE_LEN
    if off < 0:
        die("uncompressed project too short for song table")
    return off


def song_name(rec: bytes) -> str:
    field = rec[:SONG_NAME_LEN]
    n = field.find(b"\x00")
    raw = field if n < 0 else field[:n]
    name = raw.decode("latin-1", errors="replace").strip()
    return name or "EMPTY"


def empty_song_template(raw: bytes, start: int) -> bytes:
    """Blank 3072-byte slot copied from this project, without the file-tail magic."""
    blank = None
    for i in range(SONG_SLOTS):
        rec = bytearray(raw[start + i * SONG_SIZE : start + (i + 1) * SONG_SIZE])
        if song_name(bytes(rec)) != "EMPTY":
            continue
        if rec[-4:] == MAGIC_TAIL:
            rec[-4:] = b"\x00\x00\x00\x00"
        blank = bytes(rec)
        break
    if blank is None:
        rec = bytearray(SONG_SIZE)
        rec[2892:2894] = b"\x38\x40"  # default leftover in factory-empty slots
        blank = bytes(rec)
    return blank


def sanitize(name: str) -> str:
    out = "".join(ch if ch.isalnum() or ch in "~-._" else "_" for ch in name)
    return out.strip("._") or "song"


def slot_index_from_name(path: Path) -> int | None:
    stem = path.stem
    if len(stem) >= 2 and stem[:2].isdigit() and (len(stem) == 2 or stem[2] in "_-."):
        idx = int(stem[:2])
        if 0 <= idx < SONG_SLOTS:
            return idx
    return None


def dump_songs(prj: Path) -> Path:
    _manifest, payload, _ = read_project(prj)
    _head, raw = unpack_project(payload)
    start = song_table_off(raw)
    outdir = Path.cwd() / f"SONGS_{prj.stem}"
    outdir.mkdir(parents=True, exist_ok=True)
    for p in outdir.glob("*.bin"):
        p.unlink()
    used = 0
    for i in range(SONG_SLOTS):
        rec = raw[start + i * SONG_SIZE : start + (i + 1) * SONG_SIZE]
        name = song_name(rec)
        if name != "EMPTY":
            used += 1
        path = outdir / f"{i:02d}_{sanitize(name)}.bin"
        path.write_bytes(rec)
        print(f"dump  {path.name:40s}  {len(rec):5d} bytes  {name}")
    print(f"wrote {SONG_SLOTS} slots ({used} named) to {outdir}")
    print(f"uncompressed project {len(raw)} bytes; each slot is {SONG_SIZE} bytes")
    return outdir


def restore_songs(prj: Path, folder: Path, new_name: str | None = None) -> None:
    if not folder.is_dir():
        die(f"not a directory: {folder}")
    bins = sorted(
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() == ".bin" and not p.name.startswith("99_")
    )
    if not bins:
        die(f"no .bin files in {folder}")

    by_slot: dict[int, Path] = {}
    for p in bins:
        idx = slot_index_from_name(p)
        if idx is None:
            die(f"song file name must start with NN_ slot number (00–15): {p.name}")
        if idx in by_slot:
            die(f"duplicate slot {idx:02d}: {by_slot[idx].name} and {p.name}")
        by_slot[idx] = p

    manifest, payload, members = read_project(prj)
    pname = payload_name(manifest)
    head, raw = unpack_project(payload)
    start = song_table_off(raw)
    patched = bytearray(raw)
    old_len = len(payload)
    empty = empty_song_template(raw, start)

    for idx in range(SONG_SLOTS):
        path = by_slot.get(idx)
        off = start + idx * SONG_SIZE
        if path is None:
            patched[off : off + SONG_SIZE] = empty
            print(f"  slot {idx:02d}  ←  (empty)")
            continue
        blob = path.read_bytes()
        if len(blob) == 0:
            patched[off : off + SONG_SIZE] = empty
            print(f"  slot {idx:02d}  ←  {path.name}  (empty file)")
            continue
        if len(blob) != SONG_SIZE:
            die(
                f"{path.name} is {len(blob)} bytes, expected {SONG_SIZE}. "
                "Re-dump songs with this script (older dumps were LZ4 fragments "
                "and will not import)."
            )
        patched[off : off + SONG_SIZE] = blob
        print(f"  slot {idx:02d}  ←  {path.name}  {song_name(blob)}")

    patched[-4:] = MAGIC_TAIL
    new_raw = bytes(patched)
    out_pname: str | None = None
    if new_name is not None:
        new_raw, out_pname, old_internal = patch_project_name(new_raw, new_name)
        print(f"name   {old_internal!r} → {out_pname!r}")

    new_payload = pack_project(head, new_raw)
    crc = struct.unpack_from(">I", new_payload, len(new_payload) - 12)[0]
    size = struct.unpack_from(">I", new_payload, len(new_payload) - 8)[0]
    if len(new_payload) != old_len:
        print(f"payload length {old_len} → {len(new_payload)}")
    print(f"footer size={size}  crc32={crc:08x}  uncompressed={len(new_raw)}")

    bak = prj.with_suffix(prj.suffix + ".bak")
    shutil.copy2(prj, bak)
    write_project(prj, members, pname, new_payload, out_pname)
    print(f"backup {bak}")
    print(f"wrote  {prj}")
    missing = [i for i in range(SONG_SLOTS) if i not in by_slot]
    if missing:
        print(
            f"cleared {len(missing)} missing slot"
            f"{'s' if len(missing) != 1 else ''} to empty"
        )


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip(), file=sys.stderr)
        raise SystemExit(0 if argv and argv[0] in ("-h", "--help") else 2)
    prj = Path(argv[0]).expanduser().resolve()
    if not prj.is_file():
        die(f"not a file: {prj}")
    if len(argv) == 1:
        dump_songs(prj)
    elif len(argv) == 2:
        restore_songs(prj, Path(argv[1]).expanduser().resolve())
    elif len(argv) == 3:
        restore_songs(prj, Path(argv[1]).expanduser().resolve(), argv[2])
    else:
        die("usage: python ./dt_song_mgmt.py project.dt2prj [songs_folder [new_project_name]]")


if __name__ == "__main__":
    main(sys.argv[1:])
