from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Mapping, Sequence

from cdmw.core.structured_binary_editor import StructuredStringField, parse_length_prefixed_string_fields


MATERIAL_SIDECAR_EXTENSIONS = frozenset({".pac_xml", ".pam_xml", ".pamlod_xml", ".pami"})
ANIMATION_METADATA_EXTENSIONS = frozenset({".paa_metabin"})


@dataclass(frozen=True, slots=True)
class CrimsonTextureParameter:
    material_name: str
    parameter_name: str
    texture_path: str
    source_attribute: str


@dataclass(frozen=True, slots=True)
class CrimsonMaterialInstance:
    material_name: str
    shader_name: str = ""
    primitive_name: str = ""
    texture_parameters: tuple[CrimsonTextureParameter, ...] = ()
    scalar_parameters: Mapping[str, str] = None  # type: ignore[assignment]
    color_parameters: Mapping[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.scalar_parameters is None:
            object.__setattr__(self, "scalar_parameters", {})
        if self.color_parameters is None:
            object.__setattr__(self, "color_parameters", {})


@dataclass(frozen=True, slots=True)
class CrimsonBinaryReference:
    field: StructuredStringField
    text: str
    extension: str
    role: str


@dataclass(frozen=True, slots=True)
class CrimsonPrefabHeader:
    magic: int
    version: int
    prefix_byte_length: int
    first_string_offset: int


@dataclass(frozen=True, slots=True)
class CrimsonPrefabMemberDeclaration:
    member_index: int
    name_field_index: int
    type_field_index: int
    name_offset: int
    type_offset: int
    descriptor_offset: int
    descriptor_byte_length: int
    descriptor_words_le_u16: tuple[int, ...]
    descriptor_kind: str
    is_array: bool
    is_reference: bool
    is_transform: bool
    array_stride_hint: int
    array_count_hint: int
    name: str
    type_name: str


@dataclass(frozen=True, slots=True)
class CrimsonPrefabByteSpan:
    index: int
    start: int
    end: int
    kind: str
    field_index: int = -1


@dataclass(frozen=True, slots=True)
class CrimsonPrefabOffsetCandidate:
    offset: int
    value: int
    target_kind: str
    target_field_index: int


@dataclass(frozen=True, slots=True)
class CrimsonPrefabLayout:
    byte_length: int
    spans: tuple[CrimsonPrefabByteSpan, ...]
    string_span_count: int
    preserved_span_count: int
    parsed_string_byte_count: int
    preserved_byte_count: int
    accounted_byte_count: int
    fully_accounted: bool


@dataclass(frozen=True, slots=True)
class CrimsonPrefabDecode:
    references: tuple[CrimsonBinaryReference, ...]
    declared_fields: tuple[str, ...]
    member_declarations: tuple[CrimsonPrefabMemberDeclaration, ...]
    offset_candidates: tuple[CrimsonPrefabOffsetCandidate, ...]
    material_parameter_markers: tuple[str, ...]
    patchable_reference_count: int
    write_policy: str
    header: CrimsonPrefabHeader
    layout: CrimsonPrefabLayout


@dataclass(frozen=True, slots=True)
class CrimsonMeshInfoDecode:
    references: tuple[CrimsonBinaryReference, ...]
    declared_fields: tuple[str, ...]
    write_policy: str
    material_policy: str


@dataclass(frozen=True, slots=True)
class CrimsonPaaMetabinDecode:
    declared_type: str
    references: tuple[CrimsonBinaryReference, ...]
    write_policy: str
    material_policy: str


@dataclass(frozen=True, slots=True)
class PrefabResourcePathPatchResult:
    data: bytes
    patched_count: int
    proof_lines: tuple[str, ...]


def _asset_extension(value: str) -> str:
    return PurePosixPath(str(value or "").replace("\\", "/")).suffix.lower()


def _reference_role(value: str) -> str:
    ext = _asset_extension(value)
    lowered = str(value or "").replace("\\", "/").lower()
    if ext in {".pac", ".pam", ".pamlod"}:
        return "model"
    if ext in MATERIAL_SIDECAR_EXTENSIONS or "modelproperty/" in lowered:
        return "material_sidecar"
    if ext == ".dds":
        return "texture"
    if ext in {".hkx", ".hkt", ".pab", ".sockets.xml", ".xml", ".prefabdata_xml"}:
        return "companion_metadata"
    if ext in ANIMATION_METADATA_EXTENSIONS or ext in {".paa", ".pae", ".paem"}:
        return "animation"
    return "path" if "/" in lowered else "text"


def _binary_references(data: bytes) -> tuple[CrimsonBinaryReference, ...]:
    references: list[CrimsonBinaryReference] = []
    for field in parse_length_prefixed_string_fields(data, max_length=4096):
        text = str(field.text or "").strip()
        ext = _asset_extension(text)
        if not ext and "/" not in text and "\\" not in text:
            continue
        references.append(CrimsonBinaryReference(field=field, text=text, extension=ext, role=_reference_role(text)))
    return tuple(references)


def _declared_binary_field_names(data: bytes) -> tuple[str, ...]:
    names: list[str] = []
    for field in parse_length_prefixed_string_fields(data, max_length=128):
        text = str(field.text or "").strip()
        if not text.startswith("_"):
            continue
        if "/" in text or "\\" in text or "." in text:
            continue
        if text not in names:
            names.append(text)
    return tuple(names)


def _prefab_header(data: bytes) -> CrimsonPrefabHeader:
    payload = bytes(data or b"")
    magic = struct.unpack_from("<H", payload, 0)[0] if len(payload) >= 2 else 0
    version = struct.unpack_from("<H", payload, 2)[0] if len(payload) >= 4 else 0
    fields = parse_length_prefixed_string_fields(payload, max_length=4096)
    first_string_offset = int(fields[0].offset) if fields else -1
    prefix_byte_length = first_string_offset if first_string_offset >= 0 else len(payload)
    return CrimsonPrefabHeader(
        magic=magic,
        version=version,
        prefix_byte_length=prefix_byte_length,
        first_string_offset=first_string_offset,
    )


def _looks_like_member_name(value: str) -> bool:
    text = str(value or "").strip()
    return bool(text.startswith("_") and "/" not in text and "\\" not in text and "." not in text)


def _looks_like_member_type(value: str) -> bool:
    text = str(value or "").strip()
    if not text or text.startswith("_"):
        return False
    return "/" not in text and "\\" not in text


def _prefab_descriptor_words(data: bytes, offset: int, byte_length: int) -> tuple[int, ...]:
    if byte_length < 2 or offset < 0 or offset >= len(data):
        return ()
    word_count = min(byte_length // 2, 4)
    end = offset + word_count * 2
    if end > len(data):
        return ()
    return tuple(int(value) for value in struct.unpack_from(f"<{word_count}H", data, offset))


def _prefab_descriptor_kind(name: str, type_name: str, words: Sequence[int]) -> tuple[str, bool, bool, bool]:
    normalized_name = str(name or "").strip().lower()
    normalized_type = str(type_name or "").strip().lower()
    is_array = normalized_type.startswith("vector<") or normalized_type.endswith("[]")
    if normalized_name.endswith("list") and len(words) >= 3 and (int(words[2]) & 0x1000):
        is_array = True
    is_reference = normalized_type in {"reflectobject", "reflectobjectptr"} or "referencepath" in normalized_type
    is_transform = normalized_type in {"transform", "tiledtransform"} or normalized_type.endswith("transform")
    if is_transform:
        return "transform", is_array, is_reference, True
    if is_array:
        return "array", True, is_reference, False
    if is_reference:
        return "reference", False, True, False
    if normalized_type == "bool":
        return "bool", False, False, False
    if normalized_type in {"uint64", "uint32", "uint16", "uint8", "int64", "int32", "int16", "int8", "float", "double"}:
        return "scalar", False, False, False
    if normalized_type in {"indexedstringa", "staticstringa"} or normalized_type.startswith("resource"):
        return "string", False, is_reference, False
    if words:
        return "descriptor", False, False, False
    return "unknown", False, False, False


def _prefab_member_declarations(data: bytes) -> tuple[CrimsonPrefabMemberDeclaration, ...]:
    fields = parse_length_prefixed_string_fields(data, max_length=256)
    declarations: list[CrimsonPrefabMemberDeclaration] = []
    for index, field in enumerate(fields[:-1]):
        type_field = fields[index + 1]
        if not _looks_like_member_name(field.text) or not _looks_like_member_type(type_field.text):
            continue
        descriptor_offset = type_field.offset + 4 + type_field.length
        next_offset = fields[index + 2].offset if index + 2 < len(fields) else descriptor_offset
        descriptor_byte_length = max(0, next_offset - descriptor_offset)
        descriptor_words = _prefab_descriptor_words(data, descriptor_offset, descriptor_byte_length)
        descriptor_kind, is_array, is_reference, is_transform = _prefab_descriptor_kind(
            field.text,
            type_field.text,
            descriptor_words,
        )
        array_stride_hint = int(descriptor_words[1]) if is_array and len(descriptor_words) > 1 else 0
        array_count_hint = int(descriptor_words[3]) if is_array and len(descriptor_words) > 3 else 0
        declarations.append(
            CrimsonPrefabMemberDeclaration(
                member_index=len(declarations),
                name_field_index=field.index,
                type_field_index=type_field.index,
                name_offset=field.offset,
                type_offset=type_field.offset,
                descriptor_offset=descriptor_offset,
                descriptor_byte_length=descriptor_byte_length,
                descriptor_words_le_u16=descriptor_words,
                descriptor_kind=descriptor_kind,
                is_array=is_array,
                is_reference=is_reference,
                is_transform=is_transform,
                array_stride_hint=array_stride_hint,
                array_count_hint=array_count_hint,
                name=field.text,
                type_name=type_field.text,
            )
        )
    return tuple(declarations)


def _prefab_layout(data: bytes) -> CrimsonPrefabLayout:
    payload = bytes(data or b"")
    spans: list[CrimsonPrefabByteSpan] = []
    cursor = 0
    string_span_count = 0
    preserved_span_count = 0
    parsed_string_byte_count = 0
    preserved_byte_count = 0
    fields = sorted(parse_length_prefixed_string_fields(payload, max_length=4096), key=lambda field: (field.offset, field.length))
    for field in fields:
        start = int(field.offset)
        end = start + 4 + int(field.length)
        if start < cursor:
            continue
        if start > cursor:
            preserved_byte_count += start - cursor
            preserved_span_count += 1
            spans.append(
                CrimsonPrefabByteSpan(
                    index=len(spans),
                    start=cursor,
                    end=start,
                    kind="preserved",
                )
            )
        parsed_string_byte_count += end - start
        string_span_count += 1
        spans.append(
            CrimsonPrefabByteSpan(
                index=len(spans),
                start=start,
                end=end,
                kind="string_field",
                field_index=field.index,
            )
        )
        cursor = end
    if cursor < len(payload):
        preserved_byte_count += len(payload) - cursor
        preserved_span_count += 1
        spans.append(
            CrimsonPrefabByteSpan(
                index=len(spans),
                start=cursor,
                end=len(payload),
                kind="preserved",
            )
        )
    accounted = parsed_string_byte_count + preserved_byte_count
    return CrimsonPrefabLayout(
        byte_length=len(payload),
        spans=tuple(spans),
        string_span_count=string_span_count,
        preserved_span_count=preserved_span_count,
        parsed_string_byte_count=parsed_string_byte_count,
        preserved_byte_count=preserved_byte_count,
        accounted_byte_count=accounted,
        fully_accounted=accounted == len(payload),
    )


def _prefab_offset_candidates(data: bytes, layout: CrimsonPrefabLayout | None = None) -> tuple[CrimsonPrefabOffsetCandidate, ...]:
    payload = bytes(data or b"")
    prefab_layout = layout if isinstance(layout, CrimsonPrefabLayout) else _prefab_layout(payload)
    target_offsets: dict[int, tuple[str, int]] = {}
    for field in parse_length_prefixed_string_fields(payload, max_length=4096):
        target_offsets[int(field.offset)] = ("string_length_prefix", field.index)
        target_offsets[int(field.offset) + 4] = ("string_value", field.index)
        target_offsets[int(field.offset) + 4 + int(field.length)] = ("string_end", field.index)
    candidates: list[CrimsonPrefabOffsetCandidate] = []
    seen: set[tuple[int, int]] = set()
    for span in prefab_layout.spans:
        if span.kind != "preserved":
            continue
        for offset in range(span.start, max(span.start, span.end - 3)):
            value = struct.unpack_from("<I", payload, offset)[0]
            target = target_offsets.get(value)
            if target is None:
                continue
            key = (offset, value)
            if key in seen:
                continue
            seen.add(key)
            target_kind, field_index = target
            candidates.append(
                CrimsonPrefabOffsetCandidate(
                    offset=offset,
                    value=value,
                    target_kind=target_kind,
                    target_field_index=field_index,
                )
            )
    return tuple(candidates)


def decode_prefab(data: bytes) -> CrimsonPrefabDecode:
    declared = _declared_binary_field_names(data)
    material_markers = tuple(
        name
        for name in declared
        if any(token in name.lower() for token in ("material", "texture", "shader", "prefabmaterial"))
    )
    references = _binary_references(data)
    patchable_count = sum(
        1
        for reference in references
        if reference.role in {"model", "material_sidecar", "texture", "companion_metadata"}
    )
    layout = _prefab_layout(data)
    return CrimsonPrefabDecode(
        references=references,
        declared_fields=declared,
        member_declarations=_prefab_member_declarations(data),
        offset_candidates=_prefab_offset_candidates(data, layout),
        material_parameter_markers=material_markers,
        patchable_reference_count=patchable_count,
        write_policy="same-length ResourceReferencePath string patches only; no binary structure resizing",
        header=_prefab_header(data),
        layout=layout,
    )


def rebuild_prefab_no_edit(data: bytes) -> bytes:
    payload = bytes(data or b"")
    layout = decode_prefab(payload).layout
    if not layout.fully_accounted:
        raise ValueError("Prefab layout is not fully byte-accounted.")
    rebuilt = bytearray()
    cursor = 0
    for span in layout.spans:
        if span.start != cursor:
            raise ValueError("Prefab layout has a gap or overlap.")
        if span.start < 0 or span.end < span.start or span.end > len(payload):
            raise ValueError("Prefab layout span points outside the payload.")
        if span.kind not in {"preserved", "string_field"}:
            raise ValueError(f"Unsupported prefab layout span kind: {span.kind}.")
        rebuilt.extend(payload[span.start : span.end])
        cursor = span.end
    if cursor != len(payload) or len(rebuilt) != layout.byte_length:
        raise ValueError("Prefab layout rebuild did not account for the full payload.")
    return bytes(rebuilt)


def rebuild_prefab_same_length_strings(data: bytes, replacements_by_field_index: Mapping[int, str]) -> bytes:
    payload = bytes(data or b"")
    decoded = decode_prefab(payload)
    layout = decoded.layout
    if not layout.fully_accounted:
        raise ValueError("Prefab layout is not fully byte-accounted.")
    fields = {field.index: field for field in parse_length_prefixed_string_fields(payload, max_length=4096)}
    replacements = {
        int(field_index): str(value or "")
        for field_index, value in dict(replacements_by_field_index or {}).items()
    }
    rebuilt = bytearray()
    cursor = 0
    for span in layout.spans:
        if span.start != cursor:
            raise ValueError("Prefab layout has a gap or overlap.")
        if span.start < 0 or span.end < span.start or span.end > len(payload):
            raise ValueError("Prefab layout span points outside the payload.")
        if span.kind == "preserved":
            rebuilt.extend(payload[span.start : span.end])
            cursor = span.end
            continue
        if span.kind != "string_field":
            raise ValueError(f"Unsupported prefab layout span kind: {span.kind}.")
        field = fields.get(span.field_index)
        if not isinstance(field, StructuredStringField):
            raise ValueError("Prefab layout string span does not resolve to a parsed string field.")
        if field.offset != span.start or field.offset + 4 + field.length != span.end:
            raise ValueError("Prefab layout string span does not match parsed string field bounds.")
        replacement = replacements.get(field.index)
        if replacement is None:
            rebuilt.extend(payload[span.start : span.end])
            cursor = span.end
            continue
        encoded = replacement.encode("utf-8")
        if len(encoded) != field.length:
            raise ValueError(
                f"Prefab string field {field.index} replacement must be exactly {field.length} byte(s); "
                f"{replacement!r} is {len(encoded)} byte(s)."
            )
        current_length = struct.unpack_from("<I", payload, field.offset)[0]
        if current_length != field.length:
            raise ValueError("Prefab string length prefix changed before rebuilding.")
        rebuilt.extend(payload[span.start : span.start + 4])
        rebuilt.extend(encoded)
        cursor = span.end
    if cursor != len(payload) or len(rebuilt) != layout.byte_length:
        raise ValueError("Prefab layout rebuild did not account for the full payload.")
    return bytes(rebuilt)


def rebuild_prefab_resized_strings(data: bytes, replacements_by_field_index: Mapping[int, str]) -> bytes:
    payload = bytes(data or b"")
    decoded = decode_prefab(payload)
    layout = decoded.layout
    if not layout.fully_accounted:
        raise ValueError("Prefab layout is not fully byte-accounted.")
    fields = {field.index: field for field in parse_length_prefixed_string_fields(payload, max_length=4096)}
    replacements = {
        int(field_index): str(value or "")
        for field_index, value in dict(replacements_by_field_index or {}).items()
    }
    encoded_replacements: dict[int, bytes] = {}
    field_deltas: list[tuple[int, int]] = []
    for field_index, replacement in replacements.items():
        field = fields.get(field_index)
        if not isinstance(field, StructuredStringField):
            continue
        current_length = struct.unpack_from("<I", payload, field.offset)[0]
        if current_length != field.length:
            raise ValueError("Prefab string length prefix changed before rebuilding.")
        encoded = replacement.encode("utf-8")
        encoded_replacements[field_index] = encoded
        delta = len(encoded) - int(field.length)
        if delta:
            field_deltas.append((field.offset + 4 + field.length, delta))
    field_deltas.sort()

    def shifted(position: int) -> int:
        return int(position) + sum(delta for end, delta in field_deltas if end <= int(position))

    candidates_by_offset = {candidate.offset: candidate for candidate in decoded.offset_candidates}
    rebuilt = bytearray()
    cursor = 0
    for span in layout.spans:
        if span.start != cursor:
            raise ValueError("Prefab layout has a gap or overlap.")
        if span.start < 0 or span.end < span.start or span.end > len(payload):
            raise ValueError("Prefab layout span points outside the payload.")
        if span.kind == "preserved":
            segment = bytearray(payload[span.start : span.end])
            patched_candidates: list[tuple[int, int]] = []
            for offset, candidate in candidates_by_offset.items():
                if offset < span.start or offset + 4 > span.end:
                    continue
                local_offset = offset - span.start
                value = shifted(candidate.value)
                struct.pack_into("<I", segment, local_offset, value)
                patched_candidates.append((local_offset, value))
            for local_offset, value in patched_candidates:
                if struct.unpack_from("<I", segment, local_offset)[0] != value:
                    raise ValueError("Prefab offset candidates overlap; length-changing rebuild is ambiguous.")
            rebuilt.extend(segment)
            cursor = span.end
            continue
        if span.kind != "string_field":
            raise ValueError(f"Unsupported prefab layout span kind: {span.kind}.")
        field = fields.get(span.field_index)
        if not isinstance(field, StructuredStringField):
            raise ValueError("Prefab layout string span does not resolve to a parsed string field.")
        if field.offset != span.start or field.offset + 4 + field.length != span.end:
            raise ValueError("Prefab layout string span does not match parsed string field bounds.")
        encoded = encoded_replacements.get(field.index)
        if encoded is None:
            rebuilt.extend(payload[span.start : span.end])
        else:
            rebuilt.extend(len(encoded).to_bytes(4, "little"))
            rebuilt.extend(encoded)
        cursor = span.end
    if cursor != len(payload):
        raise ValueError("Prefab layout rebuild did not account for the full payload.")
    return bytes(rebuilt)


def decode_meshinfo(data: bytes) -> CrimsonMeshInfoDecode:
    return CrimsonMeshInfoDecode(
        references=_binary_references(data),
        declared_fields=_declared_binary_field_names(data),
        write_policy="read-only for mesh replacement until count/offset tables are proven",
        material_policy="not a visible texture/material authority; preserve for physics/bounds/socket context",
    )


def _paa_declared_type(data: bytes) -> str:
    payload = bytes(data or b"")
    match = re.search(rb"AnimationMetaData[A-Za-z0-9_]*", payload[:512])
    if match:
        return match.group(0).decode("ascii", errors="ignore")
    return ""


def decode_paa_metabin(data: bytes) -> CrimsonPaaMetabinDecode:
    return CrimsonPaaMetabinDecode(
        declared_type=_paa_declared_type(data),
        references=_binary_references(data),
        write_policy="read-only animation metadata",
        material_policy="excluded from texture/material replacement; no material or DDS references are expected",
    )


def parse_pami_material_instances(text: str) -> tuple[CrimsonMaterialInstance, ...]:
    source = str(text or "")
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return ()
    instances: list[CrimsonMaterialInstance] = []
    for material in root.iter():
        if material.tag.split("}")[-1] != "Material":
            continue
        material_name = str(material.attrib.get("Name") or material.attrib.get("MaterialName") or material.attrib.get("PrimitiveName") or "").strip()
        primitive_name = str(material.attrib.get("PrimitiveName") or "").strip()
        shader_name = ""
        common = material.find(".//Common")
        if common is not None:
            shader_name = str(common.attrib.get("MaterialName") or "").strip()
        texture_parameters: list[CrimsonTextureParameter] = []
        scalar_parameters: dict[str, str] = {}
        color_parameters: dict[str, str] = {}
        for element in material.iter():
            tag = element.tag.split("}")[-1]
            name = str(element.attrib.get("Name") or element.attrib.get("_name") or element.attrib.get("StringItemID") or "").strip()
            if not name:
                continue
            if tag == "MaterialParameterTexture":
                texture_path = str(
                    element.attrib.get("Value")
                    or element.attrib.get("_value")
                    or element.attrib.get("value")
                    or element.attrib.get("_path")
                    or element.attrib.get("path")
                    or ""
                ).strip()
                source_attribute = "Value" if "Value" in element.attrib else "_path" if "_path" in element.attrib else ""
                if not texture_path:
                    child = next((child for child in element if child.tag.split("}")[-1] == "ResourceReferencePath_ITexture"), None)
                    if child is not None:
                        for attr in ("_path", "path", "Path", "_value", "Value", "value"):
                            if child.attrib.get(attr):
                                texture_path = str(child.attrib.get(attr) or "").strip()
                                source_attribute = attr
                                break
                if texture_path:
                    texture_parameters.append(
                        CrimsonTextureParameter(
                            material_name=material_name,
                            parameter_name=name,
                            texture_path=texture_path.lstrip("/"),
                            source_attribute=source_attribute or "Value",
                        )
                    )
            elif tag == "MaterialParameterFloat":
                scalar_parameters[name] = str(element.attrib.get("Value") or element.attrib.get("_value") or "").strip()
            elif tag == "MaterialParameterColor":
                color_parameters[name] = str(element.attrib.get("Value") or element.attrib.get("_value") or "").strip()
        instances.append(
            CrimsonMaterialInstance(
                material_name=material_name,
                shader_name=shader_name,
                primitive_name=primitive_name,
                texture_parameters=tuple(texture_parameters),
                scalar_parameters=scalar_parameters,
                color_parameters=color_parameters,
            )
        )
    return tuple(instances)


def build_prefab_resource_path_patch(
    data: bytes,
    replacements: Mapping[str, str],
    *,
    roles: Sequence[str] = ("model", "material_sidecar", "texture"),
) -> PrefabResourcePathPatchResult:
    payload = bytes(data or b"")
    normalized_replacements = {
        str(old or "").replace("\\", "/").strip(): str(new or "").replace("\\", "/").strip()
        for old, new in dict(replacements or {}).items()
        if str(old or "").strip() and str(new or "").strip()
    }
    allowed_roles = {str(role or "").strip().lower() for role in tuple(roles or ()) if str(role or "").strip()}
    proof: list[str] = [
        "Prefab resource path patch uses recovered length-prefixed UTF-8 strings and the prefab layout encoder.",
        "Only exact-length replacements are allowed, so binary offsets and following fields do not move.",
    ]
    patched_count = 0
    replacements_by_field_index: dict[int, str] = {}
    for reference in decode_prefab(payload).references:
        if allowed_roles and reference.role not in allowed_roles:
            continue
        old_text = reference.text.replace("\\", "/").strip()
        new_text = normalized_replacements.get(old_text)
        if not new_text:
            new_text = normalized_replacements.get(old_text.lstrip("/"))
        if not new_text:
            continue
        try:
            encoded = new_text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError(f"Prefab replacement must be UTF-8 encodable: {new_text!r}") from exc
        if len(encoded) != int(reference.field.length):
            raise ValueError(
                f"Prefab replacement for {old_text!r} must be exactly {reference.field.length} byte(s); "
                f"{new_text!r} is {len(encoded)} byte(s)."
            )
        current_length = struct.unpack_from("<I", payload, int(reference.field.offset))[0]
        if current_length != int(reference.field.length):
            raise ValueError("Prefab string length prefix changed before patching.")
        replacements_by_field_index[reference.field.index] = new_text
        patched_count += 1
        proof.append(f"{reference.role}: {old_text} -> {new_text}")
    patched = rebuild_prefab_same_length_strings(payload, replacements_by_field_index) if replacements_by_field_index else payload
    return PrefabResourcePathPatchResult(data=patched, patched_count=patched_count, proof_lines=tuple(proof))


def complete_swap_file_policy(extension: str) -> str:
    normalized = str(extension or "").strip().lower()
    if normalized in {".pac", ".pam", ".pamlod"}:
        return "replace geometry payload and keep material sidecar bindings synchronized"
    if normalized in MATERIAL_SIDECAR_EXTENSIONS:
        return "authoritative visible color/material binding; patch base/normal and neutralize inherited tint/layer state"
    if normalized == ".prefab":
        return "relationship/placement metadata; patch only proven same-length resource/socket strings or copy reviewed source prefab bytes"
    if normalized == ".meshinfo":
        return "physics/bounds/socket context; preserve unless an explicit same-family source-owned swap is selected"
    if normalized in ANIMATION_METADATA_EXTENSIONS:
        return "animation metadata; excluded from texture/color replacement"
    return "context only"


__all__ = [
    "ANIMATION_METADATA_EXTENSIONS",
    "MATERIAL_SIDECAR_EXTENSIONS",
    "CrimsonBinaryReference",
    "CrimsonMaterialInstance",
    "CrimsonMeshInfoDecode",
    "CrimsonPaaMetabinDecode",
    "CrimsonPrefabByteSpan",
    "CrimsonPrefabHeader",
    "CrimsonPrefabLayout",
    "CrimsonPrefabMemberDeclaration",
    "CrimsonPrefabOffsetCandidate",
    "CrimsonPrefabDecode",
    "CrimsonTextureParameter",
    "PrefabResourcePathPatchResult",
    "build_prefab_resource_path_patch",
    "complete_swap_file_policy",
    "decode_meshinfo",
    "decode_paa_metabin",
    "decode_prefab",
    "parse_pami_material_instances",
    "rebuild_prefab_no_edit",
    "rebuild_prefab_resized_strings",
    "rebuild_prefab_same_length_strings",
]
