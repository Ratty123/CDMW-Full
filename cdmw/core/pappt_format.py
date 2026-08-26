"""The part-prefab table, `character/bin__/partprefabtable.pappt`.

This is how the game turns a part-prefab *stem* into a file. Item and appearance
data never carry prefab paths: an ItemInfo row stores `hashlittle(stem, 0xC5EDE)`,
StringInfo turns that hash back into the stem, and this table says which folder
under `character/bin__/prefab/` the stem lives in, which sockets descriptor it
uses and which character part slot(s) it fills. A stem that is not in here does
not resolve, which is why adding a weapon means adding a record here.

Layout, verified to parse the shipped file to its last byte and to rebuild it
byte for byte. The original 2026-08 layout carried no per-record prefix. Game
2.00.00 added one opaque ``01`` byte before every part record's ``extra`` string
(15,556 part records and 2,628 head records in that build):

    u8[8]   reserved, zero
    u32     part record count
    part record * count:
        str stem                e.g. cd_phm_01_sword_0109_r
        str folder              e.g. 1_pc/01_phm/weapon/01_onehandweapon
        str sockets descriptor  e.g. character/descriptors/socketbonedata/.../x.sockets.xml
        [u8  opaque tag prefix] absent in the original layout; 01 in 2.00.00
        str extra               usually empty; a shrink/variant tag such as "Empty"
        u8  flag                0 or 1
        u8  part count
        part * part count:
            str name            e.g. CD_MainWeapon_Sword_R
            u8  flag            0 or 1
    u32     head record count
    head record * count:
        str stem
        str folder

where every `str` is a u8 length that *includes* the trailing NUL, followed by
UTF-8 bytes and that NUL. An empty string is therefore `01 00`. Nothing in the
file is an absolute offset, so records can be inserted or removed freely.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Tuple

PAPPT_PREFAB_ROOT = "character/bin__/prefab"


class PapptFormatError(ValueError):
    """Raised when a buffer is not a part-prefab table."""


class PapptLayoutError(PapptFormatError):
    """Raised when a table matches neither supported record layout."""


@dataclass(frozen=True, slots=True)
class PartPrefabPart:
    """One character part slot a prefab fills, e.g. CD_MainWeapon_Sword_R."""

    name: str
    flag: int = 1


@dataclass(frozen=True, slots=True)
class PartPrefabRecord:
    stem: str
    folder: str
    sockets_path: str
    extra: str = ""
    flag: int = 1
    parts: Tuple[PartPrefabPart, ...] = ()

    @property
    def prefab_path(self) -> str:
        """The archive path the record resolves to."""

        return f"{PAPPT_PREFAB_ROOT}/{self.folder}/{self.stem}.prefab"

    def cloned(self, stem: str) -> "PartPrefabRecord":
        """The same record for a new stem: same folder, sockets, tag and parts."""

        return replace(self, stem=str(stem))


@dataclass(frozen=True, slots=True)
class HeadPrefabRecord:
    stem: str
    folder: str


@dataclass(frozen=True, slots=True)
class PartPrefabTable:
    records: Tuple[PartPrefabRecord, ...]
    head_records: Tuple[HeadPrefabRecord, ...] = ()
    #: The eight leading bytes; zero in the shipped file and kept so a rebuild cannot invent them.
    reserved: bytes = b"\x00" * 8
    #: Opaque byte before every part record's tag. Empty originally; ``01`` in game 2.00.00.
    tag_prefix: bytes = b""

    def __len__(self) -> int:
        return len(self.records)

    def index(self) -> Mapping[str, PartPrefabRecord]:
        """stem -> record. Stems are unique in the shipped table; later duplicates would win."""

        return {record.stem: record for record in self.records}

    def find(self, stem: str) -> PartPrefabRecord | None:
        wanted = str(stem or "")
        for record in self.records:
            if record.stem == wanted:
                return record
        return None


def _read_str(data: bytes, pos: int, *, where: str, what: str) -> tuple[str, int]:
    if pos >= len(data):
        raise PapptFormatError(f"{what} at 0x{pos:X} runs past the table{where}")
    length = data[pos]
    end = pos + 1 + length
    if length < 1 or end > len(data):
        raise PapptFormatError(f"{what} at 0x{pos:X} has length {length}, which does not fit the table{where}")
    raw = data[pos + 1 : end]
    if raw[-1] != 0:
        raise PapptFormatError(f"{what} at 0x{pos:X} is not NUL-terminated{where}")
    try:
        return raw[:-1].decode("utf-8"), end
    except UnicodeDecodeError as exc:
        raise PapptFormatError(f"{what} at 0x{pos:X} is not UTF-8{where}: {exc}") from exc


def _write_str(text: str, *, what: str) -> bytes:
    raw = str(text or "").encode("utf-8") + b"\x00"
    if len(raw) > 255:
        raise PapptFormatError(f"{what} {text!r} is {len(raw)} bytes with its NUL; the format allows 255")
    return bytes([len(raw)]) + raw


def _parse_pappt_layout(data: bytes, *, name: str, tag_prefix: bytes) -> PartPrefabTable:
    where = f" ({name})" if name else ""
    if len(data) < 12:
        raise PapptFormatError(f"buffer is too short to hold the header{where}")
    reserved = bytes(data[:8])
    count = struct.unpack_from("<I", data, 8)[0]
    pos = 12
    records: list[PartPrefabRecord] = []
    for index in range(count):
        stem, pos = _read_str(data, pos, where=where, what=f"record {index} stem")
        folder, pos = _read_str(data, pos, where=where, what=f"record {index} folder")
        sockets, pos = _read_str(data, pos, where=where, what=f"record {index} sockets path")
        if tag_prefix:
            end = pos + len(tag_prefix)
            if end > len(data) or data[pos:end] != tag_prefix:
                actual = data[pos:end].hex(" ") if pos < len(data) else "end of table"
                raise PapptFormatError(
                    f"record {index} tag prefix at 0x{pos:X} is {actual}, expected {tag_prefix.hex(' ')}{where}"
                )
            pos = end
        extra, pos = _read_str(data, pos, where=where, what=f"record {index} tag")
        if pos + 2 > len(data):
            raise PapptFormatError(f"record {index} flags at 0x{pos:X} run past the table{where}")
        flag, part_count = data[pos], data[pos + 1]
        pos += 2
        parts: list[PartPrefabPart] = []
        for part_index in range(part_count):
            part_name, pos = _read_str(data, pos, where=where, what=f"record {index} part {part_index}")
            if pos >= len(data):
                raise PapptFormatError(f"record {index} part {part_index} flag runs past the table{where}")
            parts.append(PartPrefabPart(name=part_name, flag=data[pos]))
            pos += 1
        records.append(
            PartPrefabRecord(stem=stem, folder=folder, sockets_path=sockets, extra=extra, flag=flag, parts=tuple(parts))
        )
    if pos + 4 > len(data):
        raise PapptFormatError(f"head record count at 0x{pos:X} runs past the table{where}")
    head_count = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    heads: list[HeadPrefabRecord] = []
    for index in range(head_count):
        stem, pos = _read_str(data, pos, where=where, what=f"head record {index} stem")
        folder, pos = _read_str(data, pos, where=where, what=f"head record {index} folder")
        heads.append(HeadPrefabRecord(stem=stem, folder=folder))
    if pos != len(data):
        raise PapptFormatError(f"the walk ends at 0x{pos:X} but the table is {len(data):,} bytes{where}")
    return PartPrefabTable(
        records=tuple(records),
        head_records=tuple(heads),
        reserved=reserved,
        tag_prefix=tag_prefix,
    )


def parse_pappt(data: bytes, *, name: str = "") -> PartPrefabTable:
    """Parse either known part-prefab layout; both sections must close exactly."""

    failures: list[PapptFormatError] = []
    for tag_prefix in (b"", b"\x01"):
        try:
            return _parse_pappt_layout(data, name=name, tag_prefix=tag_prefix)
        except PapptFormatError as exc:
            failures.append(exc)
    legacy, game_200 = failures
    where = f" ({name})" if name else ""
    raise PapptLayoutError(
        f"unsupported part-prefab table layout{where}; "
        f"original layout: {legacy}; game 2.00.00 layout: {game_200}"
    ) from legacy


def encode_pappt(table: PartPrefabTable) -> bytes:
    """Serialise a table. Re-encoding an unedited parse reproduces the source."""

    if len(table.reserved) != 8:
        raise PapptFormatError("the reserved header is eight bytes")
    if table.tag_prefix not in (b"", b"\x01"):
        raise PapptFormatError(
            f"the per-record tag prefix {table.tag_prefix.hex(' ')} is not a supported part-prefab layout"
        )
    out = bytearray(table.reserved)
    out += struct.pack("<I", len(table.records))
    for index, record in enumerate(table.records):
        out += _write_str(record.stem, what=f"record {index} stem")
        out += _write_str(record.folder, what=f"record {index} folder")
        out += _write_str(record.sockets_path, what=f"record {index} sockets path")
        out += table.tag_prefix
        out += _write_str(record.extra, what=f"record {index} tag")
        for value, what in ((record.flag, "flag"), (len(record.parts), "part count")):
            if not 0 <= int(value) <= 0xFF:
                raise PapptFormatError(f"record {index} {what} {value} does not fit a byte")
        out += bytes([int(record.flag), len(record.parts)])
        for part_index, part in enumerate(record.parts):
            out += _write_str(part.name, what=f"record {index} part {part_index}")
            if not 0 <= int(part.flag) <= 0xFF:
                raise PapptFormatError(f"record {index} part {part_index} flag {part.flag} does not fit a byte")
            out += bytes([int(part.flag)])
    out += struct.pack("<I", len(table.head_records))
    for index, head in enumerate(table.head_records):
        out += _write_str(head.stem, what=f"head record {index} stem")
        out += _write_str(head.folder, what=f"head record {index} folder")
    return bytes(out)


def rebuild_is_exact(data: bytes, *, name: str = "") -> bool:
    try:
        return encode_pappt(parse_pappt(data, name=name)) == bytes(data)
    except PapptFormatError:
        return False


def insert_part_prefabs(
    table: PartPrefabTable,
    records: Iterable[PartPrefabRecord],
    *,
    after_stem: str | None = None,
) -> PartPrefabTable:
    """Return a table with `records` inserted after `after_stem` (or appended).

    Stems must be new: a duplicate would shadow the shipped record, and the game
    keys this table by stem. Placing new records beside their template keeps the
    file grouped by folder the way the shipped one is; the game does not depend on
    the order (the spike proved that with records spliced mid-table).
    """

    incoming = tuple(records)
    known = {record.stem for record in table.records}
    seen: set[str] = set()
    for record in incoming:
        if not isinstance(record, PartPrefabRecord):
            raise TypeError("insert_part_prefabs takes PartPrefabRecord values")
        if not record.stem or "/" in record.stem or "\\" in record.stem:
            raise PapptFormatError(f"stem {record.stem!r} must be a bare file stem")
        if record.stem in known:
            raise PapptFormatError(f"stem {record.stem!r} is already in the table")
        if record.stem in seen:
            raise PapptFormatError(f"stem {record.stem!r} is given twice")
        seen.add(record.stem)
    if not incoming:
        return table
    if after_stem is None:
        return replace(table, records=table.records + incoming)
    for position, record in enumerate(table.records):
        if record.stem == after_stem:
            new_records = table.records[: position + 1] + incoming + table.records[position + 1 :]
            return replace(table, records=new_records)
    raise PapptFormatError(f"stem {after_stem!r} is not in the table, so there is nothing to insert after")


def describe_folders(table: PartPrefabTable) -> Mapping[str, int]:
    """folder -> record count, for a quick picture of what the table covers."""

    counts: dict[str, int] = {}
    for record in table.records:
        counts[record.folder] = counts.get(record.folder, 0) + 1
    return counts


__all__ = [
    "PAPPT_PREFAB_ROOT",
    "HeadPrefabRecord",
    "PapptFormatError",
    "PapptLayoutError",
    "PartPrefabPart",
    "PartPrefabRecord",
    "PartPrefabTable",
    "describe_folders",
    "encode_pappt",
    "insert_part_prefabs",
    "parse_pappt",
    "rebuild_is_exact",
]
