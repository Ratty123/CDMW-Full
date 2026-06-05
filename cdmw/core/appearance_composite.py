from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import dataclasses
import html
import math
import re
import threading
import xml.etree.ElementTree as ET
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive import (
    _attach_model_texture_preview_paths,
    _extract_archive_model_sidecar_texture_references,
    build_archive_asset_family_graph,
    build_archive_model_texture_references,
    build_archive_relationship_references,
    merge_archive_reference_rows,
    read_archive_entry_data,
    try_decode_text_like_archive_data,
)
from cdmw.core.archive_modding import ArchivePatchRequest, MeshImportSupplementalFileSpec
from cdmw.core.archive_relationships import (
    _candidate_basenames_for_xml_reference,
    build_archive_relationship_plan,
)
from cdmw.core.common import raise_if_cancelled
from cdmw.core.model_preview import _build_model_preview
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference, AssetFamilyGraph, ModelPreviewData, ModelPreviewMesh
from cdmw.modding.mesh_parser import SubMesh, parse_mesh


_APPEARANCE_COMPONENT_SECTIONS = {"nude", "head", "hair", "armor", "accessory", "face", "body"}
_MODEL_EXTENSIONS = {".pac", ".pam", ".pamlod"}
_PREFAB_EXTENSIONS = {".prefab", ".pappt"}
_MATERIAL_SIDECAR_EXTENSIONS = {".pac_xml", ".pam_xml", ".pamlod_xml", ".pami"}
_CONTEXT_EXTENSIONS = {".prefabdata_xml", ".pab", ".pabc", ".pabv", ".pabgb", ".pabgh", ".hkx", ".hkt", ".sockets.xml"}
_DEFAULT_SELECTED_SECTIONS = {"nude", "head", "hair"}


@dataclass(frozen=True, slots=True)
class AppearanceCompositeComponent:
    section: str = ""
    prefab_name: str = ""
    attributes: Mapping[str, str] = field(default_factory=dict)
    preview_flag: bool = False
    scale: float = 1.0
    default_selected: bool = False
    resolved_prefab_entries: Tuple[ArchiveEntry, ...] = ()
    resolved_model_entries: Tuple[ArchiveEntry, ...] = ()
    resolved_context_entries: Tuple[ArchiveEntry, ...] = ()
    unresolved_references: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AppearanceCompositePreviewPlan:
    source_entry: ArchiveEntry
    appearance_entry: Optional[ArchiveEntry] = None
    appearance_candidates: Tuple[ArchiveEntry, ...] = ()
    components: Tuple[AppearanceCompositeComponent, ...] = ()
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AppearanceCompositeBuildResult:
    plan: AppearanceCompositePreviewPlan
    preview_model: Optional[ModelPreviewData] = None
    model_texture_references: Tuple[ArchiveModelTextureReference, ...] = ()
    asset_family_graph: Optional[AssetFamilyGraph] = None
    selected_component_indexes: Tuple[int, ...] = ()
    model_overrides: Tuple["AppearanceCompositeModelOverride", ...] = ()
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AppearanceCompositeModelOverride:
    component_index: int
    model_entries: Tuple[ArchiveEntry, ...] = ()
    label: str = "What-if model override"


@dataclass(frozen=True, slots=True)
class AppearanceSinglePacSwapPlan:
    target_app_entry: ArchiveEntry
    donor_model_entry: ArchiveEntry
    target_component_index: int = -1
    target_component: Optional[AppearanceCompositeComponent] = None
    target_model_candidates: Tuple[ArchiveEntry, ...] = ()
    target_model_entry: Optional[ArchiveEntry] = None
    target_sidecar_entry: Optional[ArchiveEntry] = None
    target_sidecar_path: str = ""
    donor_sidecar_entry: Optional[ArchiveEntry] = None
    donor_texture_entries: Tuple[ArchiveEntry, ...] = ()
    donor_texture_missing_paths: Tuple[str, ...] = ()
    target_slot: str = ""
    donor_slot: str = ""
    target_body_family: str = ""
    donor_body_family: str = ""
    slot_match: bool = False
    body_family_match: bool = False
    allow_experimental_mismatch: bool = False
    warnings: Tuple[str, ...] = ()
    blocking_reasons: Tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AppearanceSinglePacSwapPackagePlan:
    swap_plan: AppearanceSinglePacSwapPlan
    requests: Tuple[ArchivePatchRequest, ...] = ()
    extra_payloads: Tuple[MeshImportSupplementalFileSpec, ...] = ()
    warnings: Tuple[str, ...] = ()
    blocking_reasons: Tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _AppearancePrefabNode:
    section: str
    name: str
    attributes: Mapping[str, str] = field(default_factory=dict)


def _normalize_archive_path(path: object) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/").lower()


def _entry_identity(entry: ArchiveEntry) -> Tuple[str, str, int]:
    return (
        _normalize_archive_path(getattr(entry, "path", "")),
        str(getattr(entry, "pamt_path", "") or "").casefold(),
        int(getattr(entry, "offset", 0) or 0),
    )


def _dedupe_entries(entries: Sequence[ArchiveEntry]) -> Tuple[ArchiveEntry, ...]:
    result: List[ArchiveEntry] = []
    seen: set[Tuple[str, str, int]] = set()
    for entry in entries:
        if not isinstance(entry, ArchiveEntry):
            continue
        key = _entry_identity(entry)
        if key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return tuple(result)


def _read_entry_text(entry: ArchiveEntry) -> str:
    data, _decompressed, _note = read_archive_entry_data(entry)
    return try_decode_text_like_archive_data(data) or data.decode("utf-8-sig", errors="replace")


def _xml_local_name(tag: object) -> str:
    return str(tag or "").rsplit("}", 1)[-1].strip()


def _parse_appearance_prefabs(text: str) -> Tuple[_AppearancePrefabNode, ...]:
    raw = str(text or "").strip()
    if not raw:
        return ()
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        try:
            root = ET.fromstring(f"<Root>{raw}</Root>")
        except ET.ParseError:
            return ()
    nodes: List[_AppearancePrefabNode] = []
    for section_element in root.iter():
        section = _xml_local_name(section_element.tag)
        if section.casefold() not in _APPEARANCE_COMPONENT_SECTIONS:
            continue
        section_attrs = {str(key): html.unescape(str(value or "")) for key, value in section_element.attrib.items()}
        direct_name = section_attrs.get("Name") or section_attrs.get("name") or ""
        if direct_name:
            nodes.append(_AppearancePrefabNode(section=section, name=direct_name, attributes=section_attrs))
        for child in tuple(section_element):
            attrs = {str(key): html.unescape(str(value or "")) for key, value in child.attrib.items()}
            name = attrs.get("Name") or attrs.get("name") or ""
            if name:
                nodes.append(_AppearancePrefabNode(section=section, name=name, attributes=attrs))
    return tuple(nodes)


def _path_parts(path: object) -> Tuple[str, ...]:
    return tuple(part for part in PurePosixPath(_normalize_archive_path(path)).parts if part)


def _score_local_candidate(source_path: str, candidate: ArchiveEntry) -> Tuple[int, int, int]:
    source_parts = _path_parts(source_path)
    candidate_parts = _path_parts(candidate.path)
    shared_prefix = 0
    for source_part, candidate_part in zip(source_parts, candidate_parts):
        if source_part != candidate_part:
            break
        shared_prefix += 1
    source_text = "/".join(source_parts)
    candidate_text = "/".join(candidate_parts)
    character_bonus = 1 if "/character/" in f"/{source_text}/" and "/character/" in f"/{candidate_text}/" else 0
    return shared_prefix, character_bonus, -len(candidate.path)


def _sorted_candidates(source_path: str, entries: Sequence[ArchiveEntry]) -> Tuple[ArchiveEntry, ...]:
    return tuple(sorted(_dedupe_entries(entries), key=lambda entry: _score_local_candidate(source_path, entry), reverse=True))


def _resolve_reference_candidates(
    raw_value: str,
    attr_name: str,
    *,
    source_path: str,
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
) -> Tuple[ArchiveEntry, ...]:
    candidates: List[ArchiveEntry] = []
    normalized_value = str(raw_value or "").replace("\\", "/").strip()
    if normalized_value and "/" in normalized_value:
        for basename in _candidate_basenames_for_xml_reference(normalized_value, attr_name):
            candidate_path = normalized_value
            if PurePosixPath(normalized_value).name != basename:
                parent = str(PurePosixPath(normalized_value).parent).strip(".")
                candidate_path = f"{parent}/{basename}" if parent else basename
            candidates.extend(path_index.get(_normalize_archive_path(candidate_path), ()) or ())
    for basename in _candidate_basenames_for_xml_reference(raw_value, attr_name):
        candidates.extend(basename_index.get(str(basename).lower(), ()) or ())
    return _sorted_candidates(source_path, candidates)


def _component_name_model_variants(prefab_name: str) -> Tuple[str, ...]:
    name = str(prefab_name or "").strip()
    if not name:
        return ()
    variants: List[str] = [name]
    # Character-specific appearance names often add a final owner token while the PAC keeps the shared stem.
    if "_" in name:
        stripped = re.sub(r"_[a-z][a-z0-9]*$", "", name, flags=re.IGNORECASE)
        if stripped and stripped != name:
            variants.append(stripped)
    if name.lower().endswith("_player"):
        variants.append(name[:-7])
    return tuple(dict.fromkeys(variant for variant in variants if variant))


def _entries_for_model_name_variants(
    prefab_name: str,
    *,
    source_path: str,
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
) -> Tuple[ArchiveEntry, ...]:
    candidates: List[ArchiveEntry] = []
    for variant in _component_name_model_variants(prefab_name):
        for extension in _MODEL_EXTENSIONS:
            candidates.extend(basename_index.get(f"{variant}{extension}".lower(), ()) or ())
    return _sorted_candidates(source_path, candidates)


def _entries_for_section_fallback_model(
    section: str,
    prefab_name: str,
    *,
    source_path: str,
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
) -> Tuple[ArchiveEntry, ...]:
    normalized_section = str(section or "").strip().casefold()
    name = str(prefab_name or "").strip()
    if not name:
        return ()
    candidates: List[ArchiveEntry] = []
    if normalized_section == "nude":
        # Some named actor Nude prefabdata only points at skeleton/variation metadata.
        # The renderable body mesh is the gender/body-family default nude PAC.
        match = re.match(r"^(?P<prefix>.+?_nude_)\d+_\d+(?:_[a-z][a-z0-9]*)?$", name, flags=re.IGNORECASE)
        if match:
            candidates.extend(basename_index.get(f"{match.group('prefix')}00_0001.pac".lower(), ()) or ())
    return _sorted_candidates(source_path, candidates)


def _entries_from_relationships(
    source_entry: ArchiveEntry,
    *,
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
) -> Tuple[ArchiveEntry, ...]:
    try:
        plan = build_archive_relationship_plan(
            source_entry,
            (),
            path_index=path_index,
            basename_index=basename_index,
        )
    except Exception:
        return ()
    return tuple(
        edge.related_entry
        for edge in tuple(getattr(plan, "edges", ()) or ())
        if isinstance(getattr(edge, "related_entry", None), ArchiveEntry)
    )


def _direct_sidecar_model_entries(
    sidecar_entry: ArchiveEntry,
    *,
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
) -> Tuple[ArchiveEntry, ...]:
    stem = PurePosixPath(str(sidecar_entry.path or "").replace("\\", "/")).stem
    candidates: List[ArchiveEntry] = []
    for extension in _MODEL_EXTENSIONS:
        candidates.extend(basename_index.get(f"{stem}{extension}".lower(), ()) or ())
    return _sorted_candidates(sidecar_entry.path, candidates)


def _is_context_entry(entry: ArchiveEntry) -> bool:
    extension = str(entry.extension or "").lower()
    path = _normalize_archive_path(entry.path)
    return extension in _CONTEXT_EXTENSIONS or extension in _MATERIAL_SIDECAR_EXTENSIONS or path.endswith(".sockets.xml")


def _default_component_selected(section: str, prefab_name: str, preview_flag: bool) -> bool:
    normalized_section = section.strip().casefold()
    normalized_name = prefab_name.strip().casefold()
    if normalized_section in _DEFAULT_SELECTED_SECTIONS:
        return True
    if normalized_section == "armor":
        return bool(preview_flag or "_inner" in normalized_name or "underwear" in normalized_name or "_uw_" in normalized_name)
    return False


def _component_scale(section: str, attributes: Mapping[str, str]) -> float:
    candidate_keys = ("CharacterScale", "HeadScale", "Scale")
    if section.strip().casefold() == "nude":
        candidate_keys = ("CharacterScale", "Scale")
    elif section.strip().casefold() == "head":
        candidate_keys = ("HeadScale", "Scale")
    for key in candidate_keys:
        value = str(attributes.get(key, "") or "").strip()
        if not value:
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(parsed) and parsed > 0.0:
            return parsed
    return 1.0


def _resolve_component(
    appearance_entry: ArchiveEntry,
    *,
    section: str,
    prefab_name: str,
    attributes: Mapping[str, str],
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
) -> AppearanceCompositeComponent:
    preview_flag = str(attributes.get("Preview", "") or "").strip().casefold() == "true"
    direct_entries = list(
        _resolve_reference_candidates(
            prefab_name,
            "Name",
            source_path=appearance_entry.path,
            path_index=path_index,
            basename_index=basename_index,
        )
    )
    relationship_entries: List[ArchiveEntry] = []
    for entry in direct_entries:
        if str(entry.extension or "").lower() in _PREFAB_EXTENSIONS or str(entry.extension or "").lower() == ".prefabdata_xml":
            relationship_entries.extend(
                _entries_from_relationships(
                    entry,
                    path_index=path_index,
                    basename_index=basename_index,
                )
            )
    model_entries: List[ArchiveEntry] = [
        entry for entry in tuple(direct_entries) + tuple(relationship_entries) if str(entry.extension or "").lower() in _MODEL_EXTENSIONS
    ]
    for entry in tuple(direct_entries) + tuple(relationship_entries):
        if str(entry.extension or "").lower() in _MATERIAL_SIDECAR_EXTENSIONS:
            model_entries.extend(_direct_sidecar_model_entries(entry, basename_index=basename_index))
    if not model_entries:
        model_entries.extend(
            _entries_for_model_name_variants(
                prefab_name,
                source_path=appearance_entry.path,
                basename_index=basename_index,
            )
        )
    if not model_entries:
        model_entries.extend(
            _entries_for_section_fallback_model(
                section,
                prefab_name,
                source_path=appearance_entry.path,
                basename_index=basename_index,
            )
        )
    context_entries = [
        entry
        for entry in tuple(direct_entries) + tuple(relationship_entries)
        if str(entry.extension or "").lower() not in _MODEL_EXTENSIONS and _is_context_entry(entry)
    ]
    prefab_entries = [entry for entry in direct_entries if str(entry.extension or "").lower() in _PREFAB_EXTENSIONS]
    warnings: List[str] = []
    lowered_name = prefab_name.casefold()
    if "parthide" in lowered_name:
        warnings.append("Part-hide helper is context-only; exact body clipping is not simulated.")
    if not model_entries:
        warnings.append("No renderable model PAC/PAM/PAMLOD was resolved for this appearance component.")
    return AppearanceCompositeComponent(
        section=section,
        prefab_name=prefab_name,
        attributes=dict(attributes),
        preview_flag=preview_flag,
        scale=_component_scale(section, attributes),
        default_selected=_default_component_selected(section, prefab_name, preview_flag),
        resolved_prefab_entries=_dedupe_entries(prefab_entries),
        resolved_model_entries=_dedupe_entries(model_entries),
        resolved_context_entries=_dedupe_entries(context_entries),
        unresolved_references=() if direct_entries or model_entries else (prefab_name,),
        warnings=tuple(warnings),
    )


def find_appearance_composite_candidates(
    entry: ArchiveEntry,
    archive_entries: Sequence[ArchiveEntry],
) -> Tuple[ArchiveEntry, ...]:
    extension = str(entry.extension or "").lower()
    if extension == ".app_xml":
        return (entry,)
    if extension not in _MODEL_EXTENSIONS:
        return ()
    source_stem = PurePosixPath(str(entry.path or "").replace("\\", "/")).stem.strip().casefold()
    if not source_stem:
        return ()
    source_tokens = tuple(token for token in re.split(r"[^a-z0-9]+", source_stem) if len(token) > 1)
    candidates: List[Tuple[int, int, ArchiveEntry]] = []
    for order, candidate in enumerate(archive_entries):
        if str(candidate.extension or "").lower() != ".app_xml":
            continue
        score = 0
        candidate_path = _normalize_archive_path(candidate.path)
        if source_stem in candidate_path:
            score += 80
        for token in source_tokens:
            if token in candidate_path:
                score += 6
        try:
            text = _read_entry_text(candidate).casefold()
        except Exception:
            text = ""
        if source_stem in text:
            score += 120
        for token in source_tokens:
            if token in text:
                score += 4
        if score > 0:
            candidates.append((score, order, candidate))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return tuple(candidate for _score, _order, candidate in candidates[:16])


def build_appearance_composite_preview_plan(
    entry: ArchiveEntry,
    archive_entries: Sequence[ArchiveEntry],
    *,
    appearance_entry: Optional[ArchiveEntry] = None,
    path_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    basename_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> AppearanceCompositePreviewPlan:
    path_index = path_index or {}
    basename_index = basename_index or {}
    candidates = find_appearance_composite_candidates(entry, archive_entries)
    selected_appearance = appearance_entry
    if selected_appearance is None:
        selected_appearance = entry if str(entry.extension or "").lower() == ".app_xml" else (candidates[0] if candidates else None)
    warnings: List[str] = []
    components: List[AppearanceCompositeComponent] = []
    if selected_appearance is not None and str(selected_appearance.extension or "").lower() == ".app_xml":
        try:
            prefab_nodes = _parse_appearance_prefabs(_read_entry_text(selected_appearance))
        except Exception as exc:
            prefab_nodes = ()
            warnings.append(f"Could not parse appearance XML: {exc}")
        for prefab in prefab_nodes:
            section = str(prefab.section or "").strip()
            name = str(prefab.name or "").strip()
            if not name or section.casefold() not in _APPEARANCE_COMPONENT_SECTIONS:
                continue
            components.append(
                _resolve_component(
                    selected_appearance,
                    section=section,
                    prefab_name=name,
                    attributes=dict(prefab.attributes or {}),
                    path_index=path_index,
                    basename_index=basename_index,
                )
            )
    else:
        component = _resolve_standalone_component(
            entry,
            path_index=path_index,
            basename_index=basename_index,
        )
        components.append(component)
        warnings.append("No related appearance XML was selected; preview uses the selected file's own model evidence only.")
    if not components:
        warnings.append("No appearance components were recovered.")
    return AppearanceCompositePreviewPlan(
        source_entry=entry,
        appearance_entry=selected_appearance,
        appearance_candidates=candidates,
        components=tuple(components),
        warnings=tuple(warnings),
    )


def _resolve_standalone_component(
    entry: ArchiveEntry,
    *,
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
) -> AppearanceCompositeComponent:
    extension = str(entry.extension or "").lower()
    relationship_entries = _entries_from_relationships(entry, path_index=path_index, basename_index=basename_index)
    model_entries: List[ArchiveEntry] = []
    if extension in _MODEL_EXTENSIONS:
        model_entries.append(entry)
    model_entries.extend(related for related in relationship_entries if str(related.extension or "").lower() in _MODEL_EXTENSIONS)
    if extension in _MATERIAL_SIDECAR_EXTENSIONS:
        model_entries.extend(_direct_sidecar_model_entries(entry, basename_index=basename_index))
    context_entries = [related for related in relationship_entries if _is_context_entry(related)]
    prefab_entries = (entry,) if extension in _PREFAB_EXTENSIONS else ()
    warnings = () if model_entries else ("No renderable model PAC/PAM/PAMLOD was resolved for the selected file.",)
    return AppearanceCompositeComponent(
        section="Context/Unsupported",
        prefab_name=PurePosixPath(str(entry.path or "").replace("\\", "/")).stem,
        attributes={},
        default_selected=bool(model_entries),
        resolved_prefab_entries=prefab_entries,
        resolved_model_entries=_dedupe_entries(model_entries),
        resolved_context_entries=_dedupe_entries(context_entries),
        warnings=warnings,
    )


def _preview_meshes_from_submeshes(submeshes: Sequence[SubMesh]) -> List[ModelPreviewMesh]:
    preview_meshes: List[ModelPreviewMesh] = []
    for submesh_index, submesh in enumerate(submeshes):
        if not submesh.vertices or not submesh.faces:
            continue
        indices: List[int] = []
        for face in submesh.faces:
            indices.extend(int(index) for index in face[:3])
        preview_meshes.append(
            ModelPreviewMesh(
                material_name=str(submesh.material or submesh.name or ""),
                texture_name=str(submesh.texture or ""),
                positions=[tuple(vertex) for vertex in submesh.vertices],
                texture_coordinates=[tuple(uv) for uv in submesh.uvs[: len(submesh.vertices)]],
                normals=[tuple(normal) for normal in submesh.normals[: len(submesh.vertices)]],
                indices=indices,
                source_submesh_index=submesh_index,
                source_vertex_indices=list(range(len(submesh.vertices))),
                source_face_indices=list(range(len(submesh.faces))),
            )
        )
    return preview_meshes


def _scale_preview_mesh(mesh: ModelPreviewMesh, scale: float) -> ModelPreviewMesh:
    values = {field_info.name: getattr(mesh, field_info.name) for field_info in dataclasses.fields(ModelPreviewMesh)}
    safe_scale = scale if math.isfinite(float(scale or 0.0)) and float(scale or 0.0) > 0.0 else 1.0
    values["positions"] = [
        (float(position[0]) * safe_scale, float(position[1]) * safe_scale, float(position[2]) * safe_scale)
        for position in tuple(getattr(mesh, "positions", ()) or ())
    ]
    return ModelPreviewMesh(**values)


def _component_model_entries(component: AppearanceCompositeComponent) -> Tuple[ArchiveEntry, ...]:
    return tuple(entry for entry in component.resolved_model_entries if str(entry.extension or "").lower() in _MODEL_EXTENSIONS)


def appearance_model_body_family(path: str) -> str:
    parts = _path_parts(path)
    for index, part in enumerate(parts[:-1]):
        if part == "1_pc" and index + 1 < len(parts):
            family = parts[index + 1]
            match = re.match(r"^0*(\d+)_([a-z0-9]+)$", family)
            if match:
                return f"{int(match.group(1))}_{match.group(2)}"
            return family
    return ""


def appearance_model_slot(path: str) -> str:
    parts = _path_parts(path)
    for marker in ("armor", "weapon"):
        if marker in parts:
            index = parts.index(marker)
            if index + 1 < len(parts):
                return f"{marker}/{parts[index + 1]}" if marker == "weapon" else parts[index + 1]
            return marker
    for marker in ("nude", "body", "head", "hair", "beard", "face"):
        if marker in parts:
            return marker
    return ""


def appearance_model_sidecar_path(model_path: str) -> str:
    normalized = _normalize_archive_path(model_path)
    extension = PurePosixPath(normalized).suffix.lower()
    sidecar_suffix = {
        ".pac": ".pac_xml",
        ".pam": ".pam_xml",
        ".pamlod": ".pamlod_xml",
    }.get(extension, f"{extension}_xml" if extension else ".xml")
    sidecar_path = str(PurePosixPath(normalized).with_suffix(sidecar_suffix))
    return sidecar_path.replace("/model/", "/modelproperty/", 1)


def _resolve_entries_for_path_or_basename(
    path: str,
    *,
    source_path: str,
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
) -> Tuple[ArchiveEntry, ...]:
    normalized = _normalize_archive_path(path)
    candidates: List[ArchiveEntry] = []
    if normalized:
        candidates.extend(path_index.get(normalized, ()) or ())
        basename = PurePosixPath(normalized).name.lower()
        if basename:
            candidates.extend(basename_index.get(basename, ()) or ())
    return _sorted_candidates(source_path, candidates)


def _resolve_model_sidecar_entry(
    model_entry: ArchiveEntry,
    *,
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
) -> Optional[ArchiveEntry]:
    preferred_path = appearance_model_sidecar_path(model_entry.path)
    candidates = _resolve_entries_for_path_or_basename(
        preferred_path,
        source_path=model_entry.path,
        path_index=path_index,
        basename_index=basename_index,
    )
    if not candidates:
        return None
    preferred_normalized = _normalize_archive_path(preferred_path)
    for candidate in candidates:
        if _normalize_archive_path(candidate.path) == preferred_normalized:
            return candidate
    return candidates[0]


def _extract_dds_reference_paths(text: str) -> Tuple[str, ...]:
    refs: List[str] = []
    for match in re.finditer(r"[A-Za-z0-9_./\\:-]+\.dds", str(text or ""), flags=re.IGNORECASE):
        value = html.unescape(match.group(0)).replace("\\", "/").strip().strip("\"'<>")
        if value:
            refs.append(value)
    return tuple(dict.fromkeys(refs))


def _resolve_sidecar_texture_entries(
    sidecar_entry: Optional[ArchiveEntry],
    *,
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
) -> Tuple[Tuple[ArchiveEntry, ...], Tuple[str, ...]]:
    if sidecar_entry is None:
        return (), ()
    try:
        text = _read_entry_text(sidecar_entry)
    except Exception:
        return (), ()
    entries: List[ArchiveEntry] = []
    missing: List[str] = []
    for raw_path in _extract_dds_reference_paths(text):
        resolved = _resolve_entries_for_path_or_basename(
            raw_path,
            source_path=sidecar_entry.path,
            path_index=path_index,
            basename_index=basename_index,
        )
        if resolved:
            entries.append(resolved[0])
        else:
            missing.append(raw_path)
    return _dedupe_entries(entries), tuple(dict.fromkeys(missing))


def _model_entry_in_candidates(entry: ArchiveEntry, candidates: Sequence[ArchiveEntry]) -> bool:
    entry_key = _entry_identity(entry)
    return any(_entry_identity(candidate) == entry_key for candidate in candidates)


def build_appearance_single_pac_swap_plan(
    target_app_entry: ArchiveEntry,
    donor_model_entry: ArchiveEntry,
    archive_entries: Sequence[ArchiveEntry],
    *,
    target_component_index: int,
    target_model_entry: Optional[ArchiveEntry] = None,
    allow_experimental_mismatch: bool = False,
    path_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    basename_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> AppearanceSinglePacSwapPlan:
    path_index = path_index or {}
    basename_index = basename_index or {}
    warnings: List[str] = []
    blocking_reasons: List[str] = []
    if str(getattr(target_app_entry, "extension", "") or "").lower() != ".app_xml":
        blocking_reasons.append("Target body appearance context must be an .app_xml file.")
    donor_extension = str(getattr(donor_model_entry, "extension", "") or "").lower()
    if donor_extension not in _MODEL_EXTENSIONS:
        blocking_reasons.append("Donor model must be a .pac, .pam, or .pamlod entry.")

    plan = build_appearance_composite_preview_plan(
        target_app_entry,
        archive_entries,
        appearance_entry=target_app_entry,
        path_index=path_index,
        basename_index=basename_index,
    )
    component: Optional[AppearanceCompositeComponent] = None
    try:
        component = plan.components[int(target_component_index)]
    except Exception:
        blocking_reasons.append("Choose one target appearance component from the target app XML.")
        target_component_index = -1
    target_candidates = _component_model_entries(component) if component is not None else ()
    selected_target_model = target_model_entry
    if not target_candidates:
        blocking_reasons.append("The selected target component did not resolve a model path.")
    elif selected_target_model is None:
        if len(target_candidates) == 1:
            selected_target_model = target_candidates[0]
        else:
            blocking_reasons.append("The selected target component resolves multiple model paths; choose exactly one target model.")
    elif not _model_entry_in_candidates(selected_target_model, target_candidates):
        blocking_reasons.append("The selected target model is not one of the chosen component's resolved model paths.")

    target_sidecar_entry = (
        _resolve_model_sidecar_entry(selected_target_model, path_index=path_index, basename_index=basename_index)
        if isinstance(selected_target_model, ArchiveEntry)
        else None
    )
    target_sidecar_path = (
        str(getattr(target_sidecar_entry, "path", "") or "")
        if target_sidecar_entry is not None
        else (appearance_model_sidecar_path(selected_target_model.path) if isinstance(selected_target_model, ArchiveEntry) else "")
    )
    donor_sidecar_entry = _resolve_model_sidecar_entry(donor_model_entry, path_index=path_index, basename_index=basename_index)
    donor_texture_entries, donor_texture_missing_paths = _resolve_sidecar_texture_entries(
        donor_sidecar_entry,
        path_index=path_index,
        basename_index=basename_index,
    )
    if donor_sidecar_entry is None:
        warnings.append("Donor material sidecar was not resolved; the package will only replace the model bytes.")
    elif target_sidecar_entry is None:
        warnings.append("Target material sidecar was not found; donor sidecar bytes will be written to the derived target sidecar path.")
    if donor_texture_missing_paths:
        warnings.append(f"{len(donor_texture_missing_paths):,} donor sidecar DDS reference(s) were not found in the archive index.")

    target_slot = appearance_model_slot(selected_target_model.path) if isinstance(selected_target_model, ArchiveEntry) else ""
    donor_slot = appearance_model_slot(donor_model_entry.path)
    target_family = appearance_model_body_family(selected_target_model.path) if isinstance(selected_target_model, ArchiveEntry) else ""
    donor_family = appearance_model_body_family(donor_model_entry.path)
    slot_match = bool(target_slot and donor_slot and target_slot == donor_slot)
    family_match = bool(target_family and donor_family and target_family == donor_family)
    if target_slot and donor_slot and not slot_match:
        message = f"Armor slot mismatch: target {target_slot or 'unknown'} vs donor {donor_slot or 'unknown'}."
        if allow_experimental_mismatch:
            warnings.append(f"{message} Experimental mismatch output is enabled.")
        else:
            blocking_reasons.append(f"{message} Enable experimental mismatch output to build a package.")
    elif not target_slot or not donor_slot:
        message = "Could not prove target/donor slot compatibility from archive paths."
        if allow_experimental_mismatch:
            warnings.append(f"{message} Experimental mismatch output is enabled.")
        else:
            blocking_reasons.append(f"{message} Enable experimental mismatch output to build a package.")
    if target_family and donor_family and not family_match:
        message = f"Body family mismatch: target {target_family} vs donor {donor_family}."
        if allow_experimental_mismatch:
            warnings.append(f"{message} Experimental mismatch output is enabled.")
        else:
            blocking_reasons.append(f"{message} Enable experimental mismatch output to build a package.")
    elif not target_family or not donor_family:
        warnings.append("Could not prove target/donor body-family compatibility from archive paths.")

    return AppearanceSinglePacSwapPlan(
        target_app_entry=target_app_entry,
        donor_model_entry=donor_model_entry,
        target_component_index=int(target_component_index),
        target_component=component,
        target_model_candidates=target_candidates,
        target_model_entry=selected_target_model,
        target_sidecar_entry=target_sidecar_entry,
        target_sidecar_path=target_sidecar_path,
        donor_sidecar_entry=donor_sidecar_entry,
        donor_texture_entries=donor_texture_entries,
        donor_texture_missing_paths=donor_texture_missing_paths,
        target_slot=target_slot,
        donor_slot=donor_slot,
        target_body_family=target_family,
        donor_body_family=donor_family,
        slot_match=slot_match,
        body_family_match=family_match,
        allow_experimental_mismatch=bool(allow_experimental_mismatch),
        warnings=tuple(dict.fromkeys(warnings)),
        blocking_reasons=tuple(dict.fromkeys(blocking_reasons)),
    )


def build_appearance_single_pac_swap_package_plan(
    swap_plan: AppearanceSinglePacSwapPlan,
) -> AppearanceSinglePacSwapPackagePlan:
    warnings = list(swap_plan.warnings)
    blocking = list(swap_plan.blocking_reasons)
    target_model = swap_plan.target_model_entry
    donor_model = swap_plan.donor_model_entry
    if not isinstance(target_model, ArchiveEntry):
        blocking.append("No single target model path was selected.")
    if str(getattr(donor_model, "extension", "") or "").lower() not in _MODEL_EXTENSIONS:
        blocking.append("Donor model must be a .pac, .pam, or .pamlod entry.")
    if blocking:
        return AppearanceSinglePacSwapPackagePlan(
            swap_plan=swap_plan,
            warnings=tuple(dict.fromkeys(warnings)),
            blocking_reasons=tuple(dict.fromkeys(blocking)),
        )

    requests: List[ArchivePatchRequest] = []
    extra_payloads: List[MeshImportSupplementalFileSpec] = []
    donor_model_data, _decompressed, _note = read_archive_entry_data(donor_model)
    requests.append(ArchivePatchRequest(entry=target_model, payload_data=donor_model_data))

    donor_sidecar = swap_plan.donor_sidecar_entry
    if donor_sidecar is not None and swap_plan.target_sidecar_path:
        donor_sidecar_data, _decompressed, _note = read_archive_entry_data(donor_sidecar)
        extra_payloads.append(
            MeshImportSupplementalFileSpec(
                source_path=donor_sidecar.paz_file,
                target_path=swap_plan.target_sidecar_path,
                kind="appearance_swap_material_sidecar",
                target_entry=swap_plan.target_sidecar_entry,
                payload_data=donor_sidecar_data,
                note="Donor material sidecar copied to the target component sidecar virtual path.",
            )
        )

    for texture_entry in tuple(swap_plan.donor_texture_entries or ()):
        texture_data, _decompressed, _note = read_archive_entry_data(texture_entry)
        extra_payloads.append(
            MeshImportSupplementalFileSpec(
                source_path=texture_entry.paz_file,
                target_path=texture_entry.path,
                kind="appearance_swap_donor_texture",
                target_entry=texture_entry,
                payload_data=texture_data,
                note="Donor sidecar-referenced texture copied at its original donor texture virtual path.",
            )
        )

    return AppearanceSinglePacSwapPackagePlan(
        swap_plan=swap_plan,
        requests=tuple(requests),
        extra_payloads=tuple(extra_payloads),
        warnings=tuple(dict.fromkeys(warnings)),
        blocking_reasons=tuple(dict.fromkeys(blocking)),
    )


def _model_label(component: AppearanceCompositeComponent, model_entry: ArchiveEntry) -> str:
    section = str(component.section or "Component").strip()
    prefab = str(component.prefab_name or "").strip()
    model_name = PurePosixPath(str(model_entry.path or "").replace("\\", "/")).name
    return " / ".join(part for part in (section, prefab, model_name) if part)


def _build_component_model_preview(
    model_entry: ArchiveEntry,
    component: AppearanceCompositeComponent,
    *,
    texconv_path: Optional[Path],
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
    role_prefix: str = "",
    stop_event: Optional[threading.Event],
) -> Tuple[List[ModelPreviewMesh], Tuple[ArchiveModelTextureReference, ...], Tuple[str, ...]]:
    raise_if_cancelled(stop_event)
    data, _decompressed, _note = read_archive_entry_data(model_entry, stop_event=stop_event)
    parsed_mesh = parse_mesh(data, model_entry.path)
    source_submeshes = parsed_mesh.lod_levels[0] if parsed_mesh.format == "pamlod" and parsed_mesh.lod_levels else parsed_mesh.submeshes
    meshes = _preview_meshes_from_submeshes(source_submeshes)
    temp_model = ModelPreviewData(
        path=model_entry.path,
        format=parsed_mesh.format,
        mesh_count=len(meshes),
        vertex_count=sum(len(mesh.positions) for mesh in meshes),
        face_count=sum(len(mesh.indices) // 3 for mesh in meshes),
        meshes=meshes,
    )
    sidecar_texture_references: Tuple[object, ...] = ()
    sidecar_texts_by_normalized_path: Dict[str, Tuple[str, ...]] = {}
    sidecar_texts_by_basename: Dict[str, Tuple[str, ...]] = {}
    info_lines: List[str] = []
    try:
        (
            sidecar_texture_references,
            _sidecar_reference_paths,
            sidecar_texts_by_normalized_path,
            sidecar_texts_by_basename,
        ) = _extract_archive_model_sidecar_texture_references(
            model_entry,
            archive_entries_by_basename=basename_index,
            stop_event=stop_event,
        )
    except Exception as exc:
        info_lines.append(f"Material sidecar scan failed for {model_entry.path}: {exc}")
    references = tuple(
        build_archive_model_texture_references(
            model_entry,
            temp_model,
            parsed_mesh=parsed_mesh,
            sidecar_texture_references=sidecar_texture_references,
            texture_entries_by_normalized_path=path_index,
            texture_entries_by_basename=basename_index,
            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
            sidecar_texts_by_basename=sidecar_texts_by_basename,
        )
    )
    relationship_refs = build_archive_relationship_references(
        model_entry,
        archive_entries_by_normalized_path=path_index,
        archive_entries_by_basename=basename_index,
    )
    references = merge_archive_reference_rows(references, relationship_refs)
    try:
        texture_notes = _attach_model_texture_preview_paths(
            texconv_path,
            model_entry,
            temp_model,
            texture_entries_by_normalized_path=path_index,
            texture_entries_by_basename=basename_index,
            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
            sidecar_texts_by_basename=sidecar_texts_by_basename,
            stop_event=stop_event,
        )
        info_lines.extend(texture_notes)
    except Exception as exc:
        info_lines.append(f"Texture preview binding failed for {model_entry.path}: {exc}")
    scaled_meshes: List[ModelPreviewMesh] = []
    for mesh in temp_model.meshes:
        scaled = _scale_preview_mesh(mesh, component.scale)
        role = _model_label(component, model_entry)
        scaled.preview_role = f"{role_prefix} / {role}" if role_prefix else role
        scaled_meshes.append(scaled)
    return scaled_meshes, references, tuple(info_lines)


def build_appearance_composite_model(
    plan: AppearanceCompositePreviewPlan,
    *,
    selected_component_indexes: Optional[Sequence[int]] = None,
    model_overrides: Optional[Sequence[AppearanceCompositeModelOverride]] = None,
    texconv_path: Optional[Path] = None,
    path_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    basename_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    stop_event: Optional[threading.Event] = None,
) -> AppearanceCompositeBuildResult:
    path_index = path_index or {}
    basename_index = basename_index or {}
    if selected_component_indexes is None:
        selected = tuple(index for index, component in enumerate(plan.components) if component.default_selected)
    else:
        selected = tuple(
            sorted(
                {
                    int(index)
                    for index in selected_component_indexes
                    if 0 <= int(index) < len(plan.components)
                }
            )
        )
    warnings: List[str] = list(plan.warnings)
    references: List[ArchiveModelTextureReference] = []
    meshes: List[ModelPreviewMesh] = []
    override_by_component_index: Dict[int, AppearanceCompositeModelOverride] = {}
    for override in tuple(model_overrides or ()):
        if not isinstance(override, AppearanceCompositeModelOverride):
            continue
        component_index = int(override.component_index)
        if 0 <= component_index < len(plan.components) and override.model_entries:
            override_by_component_index[component_index] = dataclasses.replace(
                override,
                model_entries=_dedupe_entries(tuple(override.model_entries or ())),
            )
    for component_index in selected:
        raise_if_cancelled(stop_event)
        component = plan.components[component_index]
        override = override_by_component_index.get(component_index)
        if override is not None:
            model_entries = tuple(entry for entry in override.model_entries if str(entry.extension or "").lower() in _MODEL_EXTENSIONS)
            original_models = ", ".join(str(getattr(entry, "path", "") or "") for entry in _component_model_entries(component)[:4])
            override_models = ", ".join(str(getattr(entry, "path", "") or "") for entry in model_entries[:4])
            warnings.append(
                f"{override.label}: {component.section} / {component.prefab_name} uses {override_models or 'no renderable override model'}"
                f" instead of {original_models or 'the unresolved app XML model'}."
            )
        else:
            model_entries = _component_model_entries(component)
        if not model_entries:
            warnings.extend(component.warnings)
            continue
        for model_entry in model_entries:
            try:
                component_meshes, component_refs, component_warnings = _build_component_model_preview(
                    model_entry,
                    component,
                    texconv_path=texconv_path,
                    path_index=path_index,
                    basename_index=basename_index,
                    role_prefix=str(getattr(override, "label", "") or "") if override is not None else "",
                    stop_event=stop_event,
                )
            except Exception as exc:
                warnings.append(f"Could not build {model_entry.path}: {exc}")
                continue
            meshes.extend(component_meshes)
            references.extend(component_refs)
            warnings.extend(component_warnings)
    if not meshes:
        return AppearanceCompositeBuildResult(
            plan=plan,
            selected_component_indexes=selected,
            model_overrides=tuple(override_by_component_index.values()),
            model_texture_references=tuple(references),
            warnings=tuple(dict.fromkeys(warnings + ["No selected appearance component produced renderable model geometry."])),
        )
    source_path = (
        str(getattr(plan.appearance_entry, "path", "") or "")
        or str(getattr(plan.source_entry, "path", "") or "")
        or "appearance-composite"
    )
    preview_model = _build_model_preview(
        source_path,
        "appearance-composite",
        meshes,
        "component mesh",
        stop_event=stop_event,
    )
    preview_model.summary = (
        f"Composite appearance preview\n"
        f"{source_path}\n"
        f"{len(selected):,} selected component(s), {preview_model.mesh_count:,} mesh(es)\n"
        f"{preview_model.vertex_count:,} vertices\n{preview_model.face_count:,} faces"
    )
    appearance_refs = build_archive_relationship_references(
        plan.appearance_entry or plan.source_entry,
        archive_entries_by_normalized_path=path_index,
        archive_entries_by_basename=basename_index,
    )
    merged_refs = merge_archive_reference_rows(references, appearance_refs)
    graph = build_archive_asset_family_graph(plan.appearance_entry or plan.source_entry, merged_refs)
    return AppearanceCompositeBuildResult(
        plan=plan,
        preview_model=preview_model,
        model_texture_references=merged_refs,
        asset_family_graph=graph,
        selected_component_indexes=selected,
        model_overrides=tuple(override_by_component_index.values()),
        warnings=tuple(dict.fromkeys(warnings)),
    )
