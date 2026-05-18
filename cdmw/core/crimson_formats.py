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
class CrimsonPrefabDecode:
    references: tuple[CrimsonBinaryReference, ...]
    declared_fields: tuple[str, ...]
    material_parameter_markers: tuple[str, ...]
    patchable_reference_count: int
    write_policy: str


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


def decode_prefab(data: bytes) -> CrimsonPrefabDecode:
    declared = _declared_binary_field_names(data)
    material_markers = tuple(
        name
        for name in declared
        if any(token in name.lower() for token in ("material", "texture", "shader", "prefabmaterial"))
    )
    references = _binary_references(data)
    patchable_count = sum(1 for reference in references if reference.role in {"model", "material_sidecar", "texture"})
    return CrimsonPrefabDecode(
        references=references,
        declared_fields=declared,
        material_parameter_markers=material_markers,
        patchable_reference_count=patchable_count,
        write_policy="same-length ResourceReferencePath string patches only; no binary structure resizing",
    )


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
    payload = bytearray(data or b"")
    normalized_replacements = {
        str(old or "").replace("\\", "/").strip(): str(new or "").replace("\\", "/").strip()
        for old, new in dict(replacements or {}).items()
        if str(old or "").strip() and str(new or "").strip()
    }
    allowed_roles = {str(role or "").strip().lower() for role in tuple(roles or ()) if str(role or "").strip()}
    proof: list[str] = [
        "Prefab resource path patch uses recovered length-prefixed UTF-8 strings.",
        "Only exact-length replacements are allowed, so binary offsets and following fields do not move.",
    ]
    patched_count = 0
    for reference in decode_prefab(data).references:
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
        start = int(reference.field.offset) + 4
        end = start + int(reference.field.length)
        current_length = struct.unpack_from("<I", payload, int(reference.field.offset))[0]
        if current_length != int(reference.field.length):
            raise ValueError("Prefab string length prefix changed before patching.")
        payload[start:end] = encoded
        patched_count += 1
        proof.append(f"{reference.role}: {old_text} -> {new_text}")
    return PrefabResourcePathPatchResult(data=bytes(payload), patched_count=patched_count, proof_lines=tuple(proof))


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
    "CrimsonPrefabDecode",
    "CrimsonTextureParameter",
    "PrefabResourcePathPatchResult",
    "build_prefab_resource_path_patch",
    "complete_swap_file_policy",
    "decode_meshinfo",
    "decode_paa_metabin",
    "decode_prefab",
    "parse_pami_material_instances",
]
