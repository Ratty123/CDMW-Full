"""File-level existing-bone palette extension; runtime rollout remains gated.

Only decoded 3/9 metadata is accepted. This does not create skeleton bones or
modify archives. A captured contract, rather than a relaxed equality check,
authorizes the exact appended identities in a later complete output.
"""

from dataclasses import asdict, dataclass
import hashlib
import struct

from .mesh_parser import _parse_par_sections, _find_pac_descriptors, _validated_pac_descriptor_prefix
from .pabv_parser import decode_pac_embedded_volumes
from .pac_cloth import pac_cloth_lods
from .pac_cloth_guide_builder import _validate_metadata_tail


@dataclass(frozen=True, slots=True)
class PacPaletteExtension:
    target_sha256: str
    skeleton_sha256: str
    original_hashes: tuple[int, ...]
    appended_names: tuple[str, ...]
    appended_hashes: tuple[int, ...]

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("Malformed palette extension contract.")
        if any(not isinstance(value[key], (tuple, list)) for key in ("original_hashes", "appended_names", "appended_hashes")):
            raise ValueError("Malformed palette extension identity arrays.")
        result = cls(value["target_sha256"], value["skeleton_sha256"],
                     tuple(value["original_hashes"]), tuple(value["appended_names"]), tuple(value["appended_hashes"]))
        for digest in (result.target_sha256, result.skeleton_sha256):
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Malformed palette extension source fingerprint.")
        hashes = result.original_hashes + result.appended_hashes
        if (not result.original_hashes or not result.appended_names or len(hashes) > 1024
                or len(result.appended_names) != len(result.appended_hashes)
                or len(set(hashes)) != len(hashes)
                or any(type(v) is not int or not 0 <= v <= 0xffffffff for v in hashes)
                or any(not isinstance(v, str) or not v for v in result.appended_names)
                or len(set(result.appended_names)) != len(result.appended_names)):
            raise ValueError("Malformed palette extension identities.")
        return result


def _rig_signature(skeleton):
    if (skeleton is None or skeleton.parser_mode != "fixed" or skeleton.parse_warning or not skeleton.bones
            or skeleton.bone_count != len(skeleton.bones)
            or any(bone.index != index for index, bone in enumerate(skeleton.bones))):
        raise ValueError("Palette extension requires the complete matching fixed-layout PAB.")
    return hashlib.sha256(repr(tuple((b.name, b.name_hash, b.parent_index, b.bind_matrix,
                                     b.inv_bind_matrix, b.position, b.rotation, b.scale)
                                    for b in skeleton.bones)).encode()).hexdigest()


def palette_layout(data):
    """Locate the counted list by sequential decoding, never a hash-byte search."""
    model = decode_pac_embedded_volumes(data)
    if model.metadata_flags & ~0x0200bf84:
        raise ValueError("Palette extension requires a proven metadata flag combination.")
    if model.model_bones:
        raise ValueError("Palette extension does not support embedded model bones.")
    sections = _parse_par_sections(data)
    metadata = sections[0]
    start, end = metadata["offset"], metadata["offset"] + metadata["size"]
    lods = data[start + 4]
    if (not 2 <= lods <= 4 or [s["index"] for s in sections] != list(range(lods + 1))
            or sections[-1]["offset"] + sections[-1]["size"] != len(data)):
        raise ValueError("Palette extension requires complete decoded two-to-four LOD sections.")
    for section in sections:
        stored, = struct.unpack_from("<I", data, 16 + section["index"] * 8)
        if stored not in (0, section["size"]):
            raise ValueError("Palette extension requires decompressed sections.")
    _validate_metadata_tail(data, model.file_end, end, model.metadata_flags)
    hashes = model.bone_palette
    if not 1 <= len(hashes) <= 1024 or len(set(hashes)) != len(hashes):
        raise ValueError("Palette extension requires an unambiguous counted palette.")
    # The decoder's volume cursor follows one or two complete six-float bounds.
    insertion = model.file_offset - 24 - (24 if model.metadata_flags & 4 else 0)
    count_at = insertion - 4 * len(hashes) - 2
    if (not start <= count_at < insertion <= end
            or struct.unpack_from("<H", data, count_at)[0] != len(hashes)
            or data[count_at + 2:insertion] != struct.pack(f"<{len(hashes)}I", *hashes)):
        raise ValueError("Palette extension cannot prove the sequential palette boundary.")
    descriptors = _validated_pac_descriptor_prefix(
        _find_pac_descriptors(data, start, metadata["size"], lods), sections, lod_count=lods)
    count, = struct.unpack_from("<H", data, start + 5 + 8 * lods)
    if not descriptors or len(descriptors) != count:
        raise ValueError("Palette extension requires every original descriptor.")
    levels = pac_cloth_lods(data)
    for lod, level in enumerate(levels):
        section = sections[lods - lod]
        vertex, = struct.unpack_from("<I", data, start + 5 + 4 * lod)
        index, = struct.unpack_from("<I", data, start + 5 + 4 * lods + 4 * lod)
        if vertex != section["offset"] or index != vertex + sum(len(p.vertices) * 40 for p in level.submeshes):
            raise ValueError("Palette extension cannot prove every LOD stream pointer.")
        for part in level.submeshes:
            if part.source_vertex_stride != 40:
                raise ValueError("Palette extension requires proven 40-byte skin records.")
            if any(slot >= len(hashes) for row in part.bone_indices for slot in row):
                raise ValueError("PAC influences exceed the counted palette.")
    return sections, count_at, insertion, hashes


def _resolve(skeleton, hashes, names=()):
    by_name, by_hash = {}, {}
    for bone in skeleton.bones:
        by_name.setdefault(bone.name, []).append(bone)
        by_hash.setdefault(bone.name_hash, []).append(bone)
    if any(len(by_hash.get(value, ())) != 1 for value in hashes):
        raise ValueError("Every palette hash must resolve uniquely against the same PAB.")
    result = []
    for name in names:
        matches = by_name.get(name, ())
        if len(matches) != 1 or len(by_hash[matches[0].name_hash]) != 1:
            raise ValueError(f"Palette bone {name} has no unique existing PAB identity.")
        result.append(matches[0].name_hash)
    return tuple(result)


def extend_pac_palette(data, skeleton, names):
    """Return an owned derived payload and its exact, revalidatable contract."""
    signature = _rig_signature(skeleton)
    sections, count_at, insertion, hashes = palette_layout(data)
    names = tuple(names)
    appended = _resolve(skeleton, hashes, names)
    contract = PacPaletteExtension.from_dict(PacPaletteExtension(
        hashlib.sha256(data).hexdigest(), signature, hashes, names, appended).to_dict())
    result = bytearray(data[:insertion] + struct.pack(f"<{len(appended)}I", *appended) + data[insertion:])
    delta = 4 * len(appended)
    struct.pack_into("<H", result, count_at, len(hashes) + len(appended))
    struct.pack_into("<2I", result, 16, 0, sections[0]["size"] + delta)
    start = sections[0]["offset"]
    for i in range(2 * data[start + 4]):
        at = start + 5 + 4 * i
        struct.pack_into("<I", result, at, struct.unpack_from("<I", data, at)[0] + delta)
    result = bytes(result)
    validate_palette_extension(data, result, skeleton, contract)
    return result, contract


def validate_palette_extension(original, payload, skeleton, contract):
    if not isinstance(contract, PacPaletteExtension):
        raise ValueError("An explicit palette extension contract is required.")
    contract = PacPaletteExtension.from_dict(contract.to_dict())
    if (hashlib.sha256(original).hexdigest() != contract.target_sha256
            or _rig_signature(skeleton) != contract.skeleton_sha256):
        raise ValueError("Palette extension source or PAB changed; prepare again.")
    before = palette_layout(original)[3]
    after = palette_layout(payload)[3]
    if (before != contract.original_hashes or after != before + contract.appended_hashes
            or _resolve(skeleton, before, contract.appended_names) != contract.appended_hashes):
        raise ValueError("Output palette differs from the exact approved existing-bone extension.")
