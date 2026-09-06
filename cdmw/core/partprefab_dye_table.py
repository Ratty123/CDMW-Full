"""PartPrefabDyeSlotInfo, including per-model-property overrides.

Verified against all 1,626 current rows, including ten with property overrides.
A model path hashes to the row key with the StringInfo seed. Each submesh has
three dye-slot indices, a default material binding and an explicit override list.
Bindings contain three material tags, twelve preserved grime flags and one signed
property index (-1 for the default). No submesh-name matching is inferred.
"""
from dataclasses import dataclass, replace
import struct
from cdmw.core.archive_format import hashlittle
from cdmw.core.structured_binary_editor import parse_pabgh_table


class DyeTableError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DyeMaterialBinding:
    tags: tuple[str, str, str]
    grime_flags: bytes
    property_index: int = -1


@dataclass(frozen=True, slots=True)
class DyeSubmesh:
    name: str
    slots: tuple[int, int, int]
    default: DyeMaterialBinding
    overrides: tuple[DyeMaterialBinding, ...] = ()


@dataclass(frozen=True, slots=True)
class PrefabDyeRow:
    key: int
    string_key: str
    blocked: bool
    submeshes: tuple[DyeSubmesh, ...]
    model_path: str

    def for_model(self, path: str, *, submeshes=None):
        normalized = path.replace("\\", "/")
        return replace(self, key=hashlittle(normalized.encode("utf-8"), 0xC5EDE), model_path=normalized,
                       submeshes=self.submeshes if submeshes is None else tuple(submeshes))


class _Reader:
    def __init__(self, raw):
        self.raw, self.pos = bytes(raw), 0

    def take(self, count):
        if count < 0 or self.pos + count > len(self.raw):
            raise DyeTableError("Truncated dye record")
        result = self.raw[self.pos:self.pos + count]
        self.pos += count
        return result

    def count(self):
        value = struct.unpack("<I", self.take(4))[0]
        if value > 4096:
            raise DyeTableError("Dye list exceeds the supported bound")
        return value

    def text(self):
        return self.take(self.count()).decode("utf-8")

    def binding(self):
        tags = tuple(self.text() for _ in range(3))
        flags = self.take(12)
        index = struct.unpack("<b", self.take(1))[0]
        if any(value not in (0, 1) for value in flags) or index < -1:
            raise DyeTableError("Unsupported dye material binding")
        return DyeMaterialBinding(tags, flags, index)


def parse_prefab_dye_row(raw: bytes) -> PrefabDyeRow:
    reader = _Reader(raw)
    key = struct.unpack("<I", reader.take(4))[0]
    name = reader.text()
    blocked = reader.take(1)[0]
    if blocked not in (0, 1):
        raise DyeTableError("Unsupported dye row flag")
    submeshes = []
    for _ in range(reader.count()):
        part = reader.text()
        slots = tuple(-1 if value == 255 else value for value in reader.take(3))
        if any(value > 11 for value in slots):
            raise DyeTableError("Unsupported dye slot index")
        default = reader.binding()
        if default.property_index != -1:
            raise DyeTableError("Dye default must use the default property index")
        overrides = tuple(reader.binding() for _ in range(reader.count()))
        if any(value.property_index < 0 for value in overrides) or len({value.property_index for value in overrides}) != len(overrides):
            raise DyeTableError("Duplicate dye property override")
        submeshes.append(DyeSubmesh(part, slots, default, overrides))
    path = reader.text()
    if reader.pos != len(reader.raw) or not path.endswith(".pac"):
        raise DyeTableError("Unproven dye row boundary")
    if key != hashlittle(path.encode("utf-8"), 0xC5EDE):
        raise DyeTableError("Dye row key does not match its model path")
    return PrefabDyeRow(key, name, bool(blocked), tuple(submeshes), path)


def _text(value):
    raw = value.encode("utf-8")
    if len(raw) > 4096:
        raise DyeTableError("Dye string exceeds the supported bound")
    return struct.pack("<I", len(raw)) + raw


def _binding(value):
    if len(value.tags) != 3 or len(value.grime_flags) != 12 or any(flag not in (0, 1) for flag in value.grime_flags):
        raise DyeTableError("Invalid dye material binding")
    return b"".join(_text(tag) for tag in value.tags) + value.grime_flags + struct.pack("<b", value.property_index)


def encode_prefab_dye_row(row: PrefabDyeRow) -> bytes:
    out = bytearray(struct.pack("<I", row.key) + _text(row.string_key) + bytes([row.blocked]))
    out += struct.pack("<I", len(row.submeshes))
    for part in row.submeshes:
        if len(part.slots) != 3 or any(not -1 <= value <= 11 for value in part.slots):
            raise DyeTableError("Dye slots are three indices from -1 (none) through 11")
        out += _text(part.name) + bytes(value & 255 for value in part.slots) + _binding(part.default)
        out += struct.pack("<I", len(part.overrides)) + b"".join(_binding(value) for value in part.overrides)
    out += _text(row.model_path)
    result = bytes(out)
    if parse_prefab_dye_row(result) != row:
        raise DyeTableError("Edited dye row did not round-trip")
    return result


def parse_prefab_dye_table(body: bytes, header: bytes):
    rows = []
    for directory, start, end in parse_pabgh_table(header, payload=body).row_spans(len(body)):
        row = parse_prefab_dye_row(body[start:end])
        if row.key != directory.row_id or encode_prefab_dye_row(row) != body[start:end]:
            raise DyeTableError("Dye table does not round-trip")
        rows.append(row)
    return tuple(rows)
