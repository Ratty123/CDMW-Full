from __future__ import annotations

from dataclasses import dataclass, field
import html
import re
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive import (
    _binary_sidecar_asset_reference_rows,
    _binary_sidecar_schema_declarations,
    _extract_archive_sidecar_texture_lookup_paths,
    _extract_binary_string_records,
    _find_archive_model_sidecar_entries,
    read_archive_entry_data,
    try_decode_text_like_archive_data,
)
from cdmw.core.archive_modding import ARCHIVE_MESH_EXTENSIONS
from cdmw.core.upscale_profiles import normalize_texture_reference_for_sidecar_lookup, parse_texture_sidecar_bindings
from cdmw.core.table_catalog import (
    evidence_label,
    extract_table_asset_reference_evidence,
    recognized_table_for_path,
)
from cdmw.models import ArchiveEntry


ARCHIVE_REL_INCLUDE_REQUIRED = "required"
ARCHIVE_REL_INCLUDE_RECOMMENDED = "recommended"
ARCHIVE_REL_INCLUDE_MANUAL = "manual"
ARCHIVE_REL_INCLUDE_RISKY = "risky"
ARCHIVE_REL_INCLUDE_UNRESOLVED = "unresolved"

SWAP_SCOPE_BODY_ONLY = "body_only"
SWAP_SCOPE_BODY_HEAD = "body_head"
SWAP_SCOPE_FULL_APPEARANCE_REDIRECT = "full_appearance_redirect"

_XML_DESCRIPTOR_EXTENSIONS = {".xml", ".app_xml", ".prefabdata_xml", ".paccd", ".pac_xml", ".pami", ".pappt", ".pamhc", ".seqmt"}
_MATERIAL_SIDECAR_EXTENSIONS = {".pac_xml", ".pam_xml", ".pamlod_xml", ".pami", ".xml"}
_SKELETON_EXTENSIONS = {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh", ".papr"}
_PHYSICS_EXTENSIONS = {".hkx", ".hkt"}
_ANIMATION_EXTENSIONS = {
    ".pam",
    ".paa",
    ".paa_metabin",
    ".pacb",
    ".motionblending",
    ".pae",
    ".paem",
    ".paseq",
    ".paseqc",
    ".paschedule",
    ".paschedulepath",
    ".pastage",
    ".seqmt",
}
_UNRESOLVED_DESCRIPTOR_SUFFIXES = (".pabc", ".pabv", ".papr", ".hkx", ".hkt")
_SIDECAR_DESCRIPTOR_REFERENCE_SUFFIXES = frozenset(
    set(ARCHIVE_MESH_EXTENSIONS)
    | _MATERIAL_SIDECAR_EXTENSIONS
    | _SKELETON_EXTENSIONS
    | _PHYSICS_EXTENSIONS
    | _ANIMATION_EXTENSIONS
    | {
        ".app_xml",
        ".app.xml",
        ".meshinfo",
        ".prefab",
        ".prefabdata",
        ".prefabdata_xml",
        ".prefabdata.xml",
        ".paccd",
        ".pappt",
        ".pamhc",
        ".seqmt",
        ".xml",
    }
)
_PATH_INDEX_CACHE: Dict[Tuple[int, int, str, str], Dict[str, List[ArchiveEntry]]] = {}
_BASENAME_INDEX_CACHE: Dict[Tuple[int, int, str, str], Dict[str, List[ArchiveEntry]]] = {}
_INDEX_CACHE_LIMIT = 4


@dataclass(frozen=True, slots=True)
class ArchiveRelationEdge:
    source_path: str
    related_path: str = ""
    related_entry: Optional[ArchiveEntry] = None
    relation_kind: str = ""
    role: str = ""
    confidence: str = "heuristic"
    reason: str = ""
    include_policy: str = ARCHIVE_REL_INCLUDE_MANUAL
    risk: bool = False
    suggested_target_path: str = ""
    unresolved: bool = False
    source_table: str = ""
    source_field: str = ""


@dataclass(frozen=True, slots=True)
class ArchiveRelationshipPlan:
    source_path: str
    mode: str = "inspect"
    edges: Tuple[ArchiveRelationEdge, ...] = ()
    warnings: Tuple[str, ...] = ()
    swap_scope: str = ""
    patched_target_app_xml: bytes = b""
    patched_target_app_path: str = ""


@dataclass(frozen=True, slots=True)
class CharacterDependencyPlan:
    body_path: str
    selected_appearance_path: str = ""
    appearance_paths: Tuple[str, ...] = ()
    entries: Tuple[ArchiveEntry, ...] = ()
    edges: Tuple[ArchiveRelationEdge, ...] = ()
    warnings: Tuple[str, ...] = ()
    blocking_errors: Tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _AppPrefabReference:
    tag: str
    name: str
    attributes: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _AppDescriptor:
    prefabs: Tuple[_AppPrefabReference, ...] = ()
    descriptor_values: Tuple[Tuple[str, str], ...] = ()


def _normalized_archive_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/").lower()


def _archive_entries_cache_key(archive_entries: Sequence[ArchiveEntry]) -> Tuple[int, int, str, str]:
    count = len(archive_entries)
    first = _normalized_archive_path(archive_entries[0].path) if count else ""
    last = _normalized_archive_path(archive_entries[-1].path) if count else ""
    return (id(archive_entries), count, first, last)


def _trim_index_cache(cache: Dict[Tuple[int, int, str, str], object]) -> None:
    while len(cache) > _INDEX_CACHE_LIMIT:
        try:
            cache.pop(next(iter(cache)))
        except StopIteration:
            break


def _entry_key(entry: ArchiveEntry) -> str:
    return f"{entry.pamt_path.resolve()}::{_normalized_archive_path(entry.path)}"


def _build_path_index(archive_entries: Sequence[ArchiveEntry]) -> Dict[str, List[ArchiveEntry]]:
    cache_key = _archive_entries_cache_key(archive_entries)
    cached = _PATH_INDEX_CACHE.get(cache_key)
    if cached is not None:
        return cached
    result: Dict[str, List[ArchiveEntry]] = {}
    for entry in archive_entries:
        key = _normalized_archive_path(entry.path)
        if key:
            result.setdefault(key, []).append(entry)
    _PATH_INDEX_CACHE[cache_key] = result
    _trim_index_cache(_PATH_INDEX_CACHE)
    return result


def _build_basename_index(archive_entries: Sequence[ArchiveEntry]) -> Dict[str, List[ArchiveEntry]]:
    cache_key = _archive_entries_cache_key(archive_entries)
    cached = _BASENAME_INDEX_CACHE.get(cache_key)
    if cached is not None:
        return cached
    result: Dict[str, List[ArchiveEntry]] = {}
    for entry in archive_entries:
        basename = PurePosixPath(entry.path.replace("\\", "/")).name.lower()
        if basename:
            result.setdefault(basename, []).append(entry)
    _BASENAME_INDEX_CACHE[cache_key] = result
    _trim_index_cache(_BASENAME_INDEX_CACHE)
    return result


def _read_entry_text(entry: ArchiveEntry) -> str:
    data, _decompressed, _note = read_archive_entry_data(entry)
    return try_decode_text_like_archive_data(data) or ""


def _parse_xml(text: str) -> Optional[ET.Element]:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        try:
            return ET.fromstring(f"<Root>{raw}</Root>")
        except ET.ParseError:
            return None


def _local_name(tag: str) -> str:
    return str(tag or "").split("}", 1)[-1].strip()


def _looks_like_reference(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if "/" in text or "\\" in text or "." in PurePosixPath(text).name:
        return True
    return bool(re.search(r"_(?:\d{4,}|[a-z]{2,})", text, re.IGNORECASE))


def parse_app_xml(text: str) -> _AppDescriptor:
    root = _parse_xml(text)
    if root is None:
        return _AppDescriptor()
    prefabs: List[_AppPrefabReference] = []
    descriptors: List[Tuple[str, str]] = []
    for element in root.iter():
        tag = _local_name(element.tag)
        attrs = {str(key): html.unescape(str(value or "")) for key, value in element.attrib.items()}
        name = attrs.get("Name") or attrs.get("name") or ""
        if name:
            prefabs.append(_AppPrefabReference(tag=tag, name=name, attributes=attrs))
        for key, value in attrs.items():
            key_lower = key.lower()
            if key_lower in {"customizationfile", "meshparamfile", "decorationparamfile"} or (
                key_lower.endswith("file") and _looks_like_reference(value)
            ):
                descriptors.append((key, value))
    return _AppDescriptor(prefabs=tuple(prefabs), descriptor_values=tuple(dict.fromkeys(descriptors)))


def parse_prefabdata_xml(text: str) -> Tuple[Tuple[str, str], ...]:
    root = _parse_xml(text)
    if root is None:
        return ()
    refs: List[Tuple[str, str]] = []
    for element in root.iter():
        for key, raw_value in element.attrib.items():
            value = html.unescape(str(raw_value or "")).strip()
            if not value:
                continue
            key_lower = str(key or "").lower()
            if (
                key_lower in {"filename", "skeletonname", "skeletonvariationname", "morphtargetsetname", "ragdollname"}
                or key_lower.endswith("name")
                or key_lower.endswith("file")
                or key_lower.endswith("path")
            ):
                if _looks_like_reference(value) or key_lower in {"filename", "skeletonname", "skeletonvariationname"}:
                    refs.append((str(key), value))
    return tuple(dict.fromkeys(refs))


def _candidate_basenames_for_xml_reference(raw_value: str, attr_name: str) -> Tuple[str, ...]:
    value = html.unescape(str(raw_value or "")).replace("\\", "/").strip()
    if not value:
        return ()
    basename = PurePosixPath(value).name.strip()
    if not basename:
        return ()
    stem = PurePosixPath(basename).stem
    suffix = PurePosixPath(basename).suffix.lower()
    attr = str(attr_name or "").strip().lower()
    candidates: List[str] = [basename]
    if attr == "name":
        candidates.extend(
            (
                f"{basename}.prefab",
                f"{basename}.prefabdata_xml",
                f"{basename}.prefabdata.xml",
                f"{basename}.pac",
                f"{basename}.pac_xml",
                f"{basename}.pami",
                f"{basename}.pappt",
                f"{basename}.pamhc",
                f"{basename}.seqmt",
            )
        )
    elif attr == "customizationfile":
        if not suffix:
            candidates.extend((f"{basename}.paccd", f"{basename}.xml"))
    elif attr in {"meshparamfile", "decorationparamfile"} and not suffix:
        candidates.append(f"{basename}.xml")
    elif attr == "filename":
        if not suffix:
            candidates.extend((f"{basename}.xml", f"{basename}.pab", f"{basename}.pabc", f"{basename}.pabv", f"{basename}.papr", f"{basename}.hkx", f"{basename}.hkt", f"{basename}.pappt", f"{basename}.pamhc", f"{basename}.seqmt"))
        if suffix == ".prefabdata":
            candidates.append(f"{stem}.prefabdata_xml")
    elif not suffix:
        candidates.extend((f"{basename}.xml", f"{basename}.prefabdata_xml", f"{basename}.pab", f"{basename}.hkx", f"{basename}.hkt", f"{basename}.pappt", f"{basename}.pamhc", f"{basename}.seqmt"))
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))


def _score_xml_reference_candidate(source_path: str, entry: ArchiveEntry) -> Tuple[int, int, int]:
    source_parts = [part for part in PurePosixPath(_normalized_archive_path(source_path)).parts if part]
    entry_parts = [part for part in PurePosixPath(_normalized_archive_path(entry.path)).parts if part]
    shared_prefix = 0
    for source_part, entry_part in zip(source_parts, entry_parts):
        if source_part != entry_part:
            break
        shared_prefix += 1
    same_package_depth = 1 if source_parts[:1] and source_parts[:1] == entry_parts[:1] else 0
    return shared_prefix, same_package_depth, -len(entry.path)


def _relation_kind_for_entry(entry: ArchiveEntry) -> str:
    extension = str(entry.extension or "").lower()
    path = _normalized_archive_path(entry.path)
    if extension == ".dds":
        return "texture"
    if extension == ".app_xml":
        return "appearance"
    if extension == ".prefabdata_xml":
        return "prefab_data"
    if extension == ".prefab":
        return "prefab"
    if extension == ".pappt":
        return "prefab"
    if extension in ARCHIVE_MESH_EXTENSIONS:
        return "model"
    if extension in _SKELETON_EXTENSIONS:
        return "skeleton"
    if extension in _PHYSICS_EXTENSIONS:
        return "physics"
    if extension in _ANIMATION_EXTENSIONS or "/animation/" in path:
        return "animation"
    if extension in _MATERIAL_SIDECAR_EXTENSIONS and (
        "modelproperty/" in path or extension in {".pac_xml", ".pam_xml", ".pamlod_xml", ".pami"}
    ):
        return "material_sidecar"
    if extension in _XML_DESCRIPTOR_EXTENSIONS:
        return "descriptor"
    return "file"


def _policy_for_kind(kind: str) -> Tuple[str, bool]:
    if kind in {"skeleton", "physics", "animation"}:
        return ARCHIVE_REL_INCLUDE_MANUAL, True
    if kind in {"appearance_patch"}:
        return ARCHIVE_REL_INCLUDE_REQUIRED, False
    if kind in {"texture", "model", "material_sidecar", "prefab_data", "prefab", "descriptor"}:
        return ARCHIVE_REL_INCLUDE_RECOMMENDED, False
    return ARCHIVE_REL_INCLUDE_MANUAL, False


def _resolve_basenames(
    raw_value: str,
    attr_name: str,
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
    *,
    source_path: str = "",
    path_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[ArchiveEntry, ...]:
    result: List[ArchiveEntry] = []
    seen: set[str] = set()

    def add_entries(candidates: Sequence[ArchiveEntry]) -> None:
        ordered_candidates = list(candidates)
        if source_path:
            ordered_candidates.sort(key=lambda entry: _score_xml_reference_candidate(source_path, entry), reverse=True)
            if len(ordered_candidates) > 1:
                best_prefix = _score_xml_reference_candidate(source_path, ordered_candidates[0])[0]
                if best_prefix > 0:
                    ordered_candidates = [
                        entry
                        for entry in ordered_candidates
                        if _score_xml_reference_candidate(source_path, entry)[0] == best_prefix
                    ]
        for entry in ordered_candidates:
            key = _entry_key(entry)
            if key and key not in seen:
                result.append(entry)
                seen.add(key)

    value = html.unescape(str(raw_value or "")).replace("\\", "/").strip()
    if value and "/" in value and path_index is not None:
        path_candidates: List[ArchiveEntry] = []
        for basename in _candidate_basenames_for_xml_reference(raw_value, attr_name):
            candidate_path = value
            if PurePosixPath(value).name != basename:
                parent = str(PurePosixPath(value).parent).strip(".")
                candidate_path = f"{parent}/{basename}" if parent else basename
            path_candidates.extend(tuple(path_index.get(_normalized_archive_path(candidate_path), ()) or ()))
        add_entries(path_candidates)

    for basename in _candidate_basenames_for_xml_reference(raw_value, attr_name):
        add_entries(tuple(basename_index.get(str(basename).lower(), ()) or ()))
    return tuple(result)


def _edge_for_entry(
    source_path: str,
    entry: ArchiveEntry,
    *,
    role: str,
    confidence: str,
    reason: str,
    suggested_target_path: str = "",
    source_table: str = "",
    source_field: str = "",
) -> ArchiveRelationEdge:
    kind = _relation_kind_for_entry(entry)
    policy, risk = _policy_for_kind(kind)
    return ArchiveRelationEdge(
        source_path=source_path,
        related_path=entry.path.replace("\\", "/"),
        related_entry=entry,
        relation_kind=kind,
        role=role,
        confidence=confidence,
        reason=reason,
        include_policy=policy,
        risk=risk,
        suggested_target_path=suggested_target_path,
        source_table=source_table,
        source_field=source_field,
    )


def _unresolved_edge(source_path: str, raw_value: str, attr_name: str, *, role: str, reason: str) -> ArchiveRelationEdge:
    return ArchiveRelationEdge(
        source_path=source_path,
        related_path=str(raw_value or "").replace("\\", "/").strip(),
        relation_kind="unresolved",
        role=role,
        confidence="unresolved",
        reason=reason,
        include_policy=ARCHIVE_REL_INCLUDE_UNRESOLVED,
        risk=True,
        unresolved=True,
    )


def _dedupe_edges(edges: Iterable[ArchiveRelationEdge]) -> Tuple[ArchiveRelationEdge, ...]:
    result: List[ArchiveRelationEdge] = []
    seen: set[Tuple[str, str, str, str]] = set()
    for edge in edges:
        entry_key = _entry_key(edge.related_entry) if edge.related_entry is not None else ""
        key = (entry_key, _normalized_archive_path(edge.related_path), edge.relation_kind, edge.role)
        if key in seen:
            continue
        seen.add(key)
        result.append(edge)
    return tuple(result)


def _resolve_table_catalog_edges(
    table_entry: ArchiveEntry,
    *,
    source_path: str,
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
) -> Tuple[ArchiveRelationEdge, ...]:
    table_spec = recognized_table_for_path(table_entry.path)
    if table_spec is None:
        return ()
    try:
        data, _decompressed, _note = read_archive_entry_data(table_entry)
    except Exception:
        return ()
    if not data:
        return ()
    string_records = _extract_binary_string_records(data, sample_limit=262_144, max_strings=512)
    evidence_records = extract_table_asset_reference_evidence(
        table_spec.source_table,
        (record.text for record in string_records),
    )
    if not evidence_records:
        return ()
    edges: List[ArchiveRelationEdge] = []
    for evidence in evidence_records:
        resolved_entries = _resolve_basenames(
            evidence.target,
            evidence.source_field,
            basename_index,
            source_path=source_path,
            path_index=path_index,
        )
        for related in resolved_entries[:16]:
            edges.append(
                _edge_for_entry(
                    source_path,
                    related,
                    role=evidence.role,
                    confidence=evidence.confidence,
                    reason=f"Referenced by {evidence_label(evidence)} in decoded table/string data",
                    source_table=evidence.source_table,
                    source_field=evidence.source_field,
                )
            )
    return _dedupe_edges(edges)


def _resolve_sidecar_texture_edges(
    sidecar_entry: ArchiveEntry,
    *,
    source_path: str,
    archive_entries: Sequence[ArchiveEntry] = (),
    path_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    basename_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[ArchiveRelationEdge, ...]:
    if path_index is None:
        path_index = _build_path_index(archive_entries)
    if basename_index is None:
        basename_index = _build_basename_index(archive_entries)
    try:
        text = _read_entry_text(sidecar_entry)
    except Exception:
        return ()
    edges: List[ArchiveRelationEdge] = []
    structured_bindings = tuple(parse_texture_sidecar_bindings(text, sidecar_path=sidecar_entry.path))
    structured_paths: List[Tuple[str, str]] = []
    seen_structured: set[Tuple[str, str]] = set()
    for binding in structured_bindings:
        raw_texture_path = str(getattr(binding, "texture_path", "") or "").strip()
        if not raw_texture_path:
            continue
        parameter_name = str(getattr(binding, "parameter_name", "") or "").strip()
        key = (normalize_texture_reference_for_sidecar_lookup(raw_texture_path), parameter_name.lower())
        if key in seen_structured:
            continue
        seen_structured.add(key)
        structured_paths.append((raw_texture_path, parameter_name))
    if not structured_paths:
        structured_paths = [(raw_texture_path, "") for raw_texture_path in _extract_archive_sidecar_texture_lookup_paths(text)]

    for raw_texture_path, parameter_name in structured_paths:
        normalized = normalize_texture_reference_for_sidecar_lookup(raw_texture_path)
        exact_candidates = tuple(path_index.get(normalized, ()) or ())
        if exact_candidates:
            for candidate in exact_candidates:
                if str(candidate.extension or "").lower() == ".dds":
                    edges.append(
                        _edge_for_entry(
                            source_path,
                            candidate,
                            role=parameter_name or "texture",
                            confidence="exact_path",
                            reason=f"Texture path referenced by {sidecar_entry.basename}",
                        )
                    )
            continue
        basename = PurePosixPath(str(raw_texture_path or "").replace("\\", "/")).name.lower()
        for candidate in tuple(basename_index.get(basename, ()) or ()):
            if str(candidate.extension or "").lower() == ".dds":
                edges.append(
                    ArchiveRelationEdge(
                        source_path=source_path,
                        related_path=candidate.path.replace("\\", "/"),
                        related_entry=candidate,
                        relation_kind="texture",
                        role=parameter_name or "texture",
                        confidence="basename_fallback",
                        reason=f"Texture basename referenced by {sidecar_entry.basename}",
                        include_policy=ARCHIVE_REL_INCLUDE_MANUAL,
                    )
                )
    return _dedupe_edges(edges)


def _sidecar_descriptor_attr_name(element: ET.Element, attr_name: str, raw_value: str) -> str:
    key = str(attr_name or "").strip()
    if key.lower() not in {"value", "path", "filename", "file", "name"}:
        return key
    raw_text = str(raw_value or "").strip()
    for context_key in ("_name", "name", "Name", "parameter", "Parameter"):
        context = str(element.attrib.get(context_key, "") or "").strip()
        if context and context != raw_text:
            return f"{context}.{key}" if key else context
    return key


def _sidecar_descriptor_reference_value(raw_value: str) -> bool:
    value = html.unescape(str(raw_value or "")).replace("\\", "/").strip()
    if not value:
        return False
    basename = PurePosixPath(value).name.strip()
    if not basename:
        return False
    suffix = PurePosixPath(basename).suffix.lower()
    if suffix == ".dds":
        return False
    if suffix in _SIDECAR_DESCRIPTOR_REFERENCE_SUFFIXES:
        return True
    return bool(suffix and ("/" in value or "\\" in str(raw_value or "")))


def _sidecar_descriptor_role(attr_name: str, raw_value: str) -> str:
    key = str(attr_name or "").casefold()
    value = str(raw_value or "").replace("\\", "/").casefold()
    suffix = PurePosixPath(value).suffix.lower()
    combined = f"{key} {value}"
    if suffix in _PHYSICS_EXTENSIONS or any(token in combined for token in ("physics", "ragdoll", "collision")):
        return "sidecar_physics_context"
    if suffix in _SKELETON_EXTENSIONS or any(token in key for token in ("skeleton", "rig")):
        return "sidecar_skeleton_context"
    if "socket" in combined:
        return "sidecar_socket_descriptor"
    if suffix in ARCHIVE_MESH_EXTENSIONS or "mesh" in key:
        return "sidecar_model_resource"
    if suffix in _ANIMATION_EXTENSIONS or any(token in key for token in ("animation", "motion")):
        return "sidecar_animation_context"
    if "prefab" in combined or suffix in {".prefab", ".prefabdata", ".prefabdata_xml"}:
        return "sidecar_prefab_descriptor"
    return "sidecar_descriptor"


def _resolve_sidecar_descriptor_edges(
    sidecar_entry: ArchiveEntry,
    *,
    source_path: str,
    archive_entries: Sequence[ArchiveEntry] = (),
    path_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    basename_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[ArchiveRelationEdge, ...]:
    if path_index is None:
        path_index = _build_path_index(archive_entries)
    if basename_index is None:
        basename_index = _build_basename_index(archive_entries)
    try:
        text = _read_entry_text(sidecar_entry)
    except Exception:
        return ()
    root = _parse_xml(text)
    if root is None:
        return ()
    edges: List[ArchiveRelationEdge] = []
    for element in root.iter():
        for key, raw_value in element.attrib.items():
            value = html.unescape(str(raw_value or "")).strip()
            if not _sidecar_descriptor_reference_value(value):
                continue
            attr_name = _sidecar_descriptor_attr_name(element, key, value)
            role = _sidecar_descriptor_role(attr_name, value)
            resolved = _resolve_basenames(
                value,
                attr_name,
                basename_index,
                source_path=sidecar_entry.path,
                path_index=path_index,
            )
            if resolved:
                for entry in resolved:
                    edges.append(
                        _edge_for_entry(
                            source_path,
                            entry,
                            role=role,
                            confidence="sidecar_descriptor_reference",
                            reason=f"Descriptor path referenced by {sidecar_entry.basename} attribute {attr_name}",
                        )
                    )
            elif PurePosixPath(value.replace("\\", "/")).suffix.lower() in _UNRESOLVED_DESCRIPTOR_SUFFIXES:
                edges.append(
                    _unresolved_edge(
                        source_path,
                        value,
                        attr_name,
                        role=role,
                        reason=f"{sidecar_entry.basename} references a descriptor not present in the loaded archive set",
                    )
                )
    return _dedupe_edges(edges)


def _sidecar_submesh_names(sidecar_text: str) -> Tuple[str, ...]:
    names: List[str] = []
    for match in re.finditer(r'_subMeshName"\s*value="([^"]+)"', sidecar_text or "", re.IGNORECASE):
        value = html.unescape(match.group(1)).strip().lower()
        if value and value not in names:
            names.append(value)
    return tuple(names)


def _read_sidecar_submesh_names(entry: ArchiveEntry) -> Tuple[str, ...]:
    try:
        return _sidecar_submesh_names(_read_entry_text(entry))
    except Exception:
        return ()


def resolve_material_texture_graph(
    model_or_sidecar_entry: ArchiveEntry,
    archive_entries: Sequence[ArchiveEntry] = (),
    *,
    path_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    basename_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> ArchiveRelationshipPlan:
    if basename_index is None:
        basename_index = _build_basename_index(archive_entries)
    if path_index is None:
        path_index = _build_path_index(archive_entries)
    source_path = model_or_sidecar_entry.path.replace("\\", "/")
    edges: List[ArchiveRelationEdge] = []
    sidecar_entries: Tuple[ArchiveEntry, ...]
    if _relation_kind_for_entry(model_or_sidecar_entry) == "material_sidecar":
        sidecar_entries = (model_or_sidecar_entry,)
    else:
        sidecar_entries = _find_archive_model_sidecar_entries(model_or_sidecar_entry, basename_index)

    for sidecar_entry in sidecar_entries:
        edges.append(
            _edge_for_entry(
                source_path,
                sidecar_entry,
                role="material_sidecar",
                confidence="sidecar_match",
                reason="Material sidecar matched by model basename/path",
            )
        )
        edges.extend(
            _resolve_sidecar_texture_edges(
                sidecar_entry,
                source_path=source_path,
                archive_entries=archive_entries,
                path_index=path_index,
                basename_index=basename_index,
            )
        )
        edges.extend(
            _resolve_sidecar_descriptor_edges(
                sidecar_entry,
                source_path=source_path,
                archive_entries=archive_entries,
                path_index=path_index,
                basename_index=basename_index,
            )
        )
    return ArchiveRelationshipPlan(source_path=source_path, mode="material_texture_graph", edges=_dedupe_edges(edges))


def _expand_prefabdata_graph(
    source_path: str,
    prefab_entry: ArchiveEntry,
    archive_entries: Sequence[ArchiveEntry] = (),
    *,
    basename_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    path_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[ArchiveRelationEdge, ...]:
    if basename_index is None:
        basename_index = _build_basename_index(archive_entries)
    if path_index is None:
        path_index = _build_path_index(archive_entries)
    try:
        text = _read_entry_text(prefab_entry)
    except Exception:
        return ()
    edges: List[ArchiveRelationEdge] = []
    for attr_name, raw_value in parse_prefabdata_xml(text):
        resolved = _resolve_basenames(
            raw_value,
            attr_name,
            basename_index,
            source_path=prefab_entry.path,
            path_index=path_index,
        )
        if resolved:
            for entry in resolved:
                edges.append(
                    _edge_for_entry(
                        source_path,
                        entry,
                        role=str(attr_name).lower(),
                        confidence="xml_reference",
                        reason=f"Referenced by {prefab_entry.basename} attribute {attr_name}",
                    )
                )
        elif PurePosixPath(str(raw_value or "").replace("\\", "/")).suffix.lower() in _UNRESOLVED_DESCRIPTOR_SUFFIXES:
            edges.append(
                _unresolved_edge(
                    source_path,
                    raw_value,
                    attr_name,
                    role=str(attr_name).lower(),
                    reason=f"{prefab_entry.basename} references a descriptor not present in the loaded archive set",
                )
            )
    return _dedupe_edges(edges)


def _prefab_declared_name_set(data: bytes) -> set[str]:
    try:
        schema = _binary_sidecar_schema_declarations(data, ".prefab")
    except Exception:
        return set()
    rows = schema.get("declared_member_rows") if isinstance(schema, Mapping) else ()
    return {
        str(row.get("name") or "").strip().lstrip("_").lower()
        for row in tuple(rows or ())
        if isinstance(row, Mapping)
    }


def _prefab_role_for_reference(raw_reference: str, entry: Optional[ArchiveEntry], declared_names: set[str]) -> str:
    reference_path = str(getattr(entry, "path", "") or raw_reference).replace("\\", "/").lower()
    basename = PurePosixPath(reference_path).name
    extension = str(getattr(entry, "extension", "") or PurePosixPath(reference_path).suffix).lower()
    if "socket" in basename or basename.endswith(".sockets.xml"):
        return "prefab_socket_descriptor"
    if extension in {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh"} or "skeleton" in basename:
        return "prefab_skeleton_context"
    if extension in _PHYSICS_EXTENSIONS or "physics" in reference_path or "ragdoll" in reference_path:
        return "prefab_physics_context"
    if extension in ARCHIVE_MESH_EXTENSIONS:
        if any(name in declared_names for name in ("skinnedmeshfile", "skinnedmeshfilename", "skeletonfilename")):
            return "prefab_skinned_model_resource"
        return "prefab_model_resource"
    if extension in _MATERIAL_SIDECAR_EXTENSIONS or extension == ".pamhc" or "modelproperty" in reference_path:
        return "prefab_material_context"
    if extension == ".dds":
        return "prefab_texture_hint"
    if extension in _XML_DESCRIPTOR_EXTENSIONS:
        return "prefab_descriptor"
    return "prefab_reference"


def _expand_binary_prefab_graph(
    source_path: str,
    prefab_entry: ArchiveEntry,
    archive_entries: Sequence[ArchiveEntry] = (),
    *,
    basename_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    path_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[ArchiveRelationEdge, ...]:
    if basename_index is None:
        basename_index = _build_basename_index(archive_entries)
    if path_index is None:
        path_index = _build_path_index(archive_entries)
    try:
        data, _decompressed, _note = read_archive_entry_data(prefab_entry)
    except Exception:
        return ()

    declared_names = _prefab_declared_name_set(data)
    try:
        string_records = _extract_binary_string_records(data, sample_limit=262_144, max_strings=512)
        reference_rows = _binary_sidecar_asset_reference_rows(string_records, max_references=128)
    except Exception:
        reference_rows = ()

    edges: List[ArchiveRelationEdge] = []
    for row in tuple(reference_rows or ()):
        if not isinstance(row, Mapping):
            continue
        raw_reference = str(row.get("path") or "").replace("\\", "/").strip()
        if not raw_reference:
            continue
        resolved_entries = _resolve_basenames(
            raw_reference,
            "PrefabBinaryReference",
            basename_index,
            source_path=prefab_entry.path,
            path_index=path_index,
        )
        if not resolved_entries:
            suffix = PurePosixPath(raw_reference).suffix.lower()
            if suffix in _UNRESOLVED_DESCRIPTOR_SUFFIXES:
                edges.append(
                    _unresolved_edge(
                        source_path,
                        raw_reference,
                        "PrefabBinaryReference",
                        role="prefab_unresolved_reference",
                        reason=f"{prefab_entry.basename} contains an unresolved binary prefab reference",
                    )
                )
            continue
        for related in resolved_entries[:8]:
            role = _prefab_role_for_reference(raw_reference, related, declared_names)
            edges.append(
                _edge_for_entry(
                    source_path,
                    related,
                    role=role,
                    confidence="prefab_binary_reference",
                    reason=f"Referenced by binary prefab metadata in {prefab_entry.basename}",
                )
            )

    return _dedupe_edges(edges)


def build_archive_relationship_plan(
    entry: ArchiveEntry,
    archive_entries: Sequence[ArchiveEntry] = (),
    mode: str = "inspect",
    *,
    path_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    basename_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> ArchiveRelationshipPlan:
    source_path = entry.path.replace("\\", "/")
    relation_kind = _relation_kind_for_entry(entry)
    edges: List[ArchiveRelationEdge] = []
    warnings: List[str] = []
    if basename_index is None:
        basename_index = _build_basename_index(archive_entries)
    if path_index is None:
        path_index = _build_path_index(archive_entries)

    edges.extend(
        _resolve_table_catalog_edges(
            entry,
            source_path=source_path,
            path_index=path_index,
            basename_index=basename_index,
        )
    )

    if relation_kind in {"model", "material_sidecar"}:
        material_plan = resolve_material_texture_graph(
            entry,
            archive_entries,
            path_index=path_index,
            basename_index=basename_index,
        )
        edges.extend(material_plan.edges)

    if relation_kind == "appearance":
        try:
            descriptor = parse_app_xml(_read_entry_text(entry))
        except Exception:
            descriptor = _AppDescriptor()
        for attr_name, raw_value in descriptor.descriptor_values:
            resolved = _resolve_basenames(
                raw_value,
                attr_name,
                basename_index,
                source_path=entry.path,
                path_index=path_index,
            )
            if not resolved:
                edges.append(
                    _unresolved_edge(
                        source_path,
                        raw_value,
                        attr_name,
                        role=str(attr_name).lower(),
                        reason=f"Appearance descriptor references {raw_value}",
                    )
                )
            for related in resolved:
                edges.append(
                    _edge_for_entry(
                        source_path,
                        related,
                        role=str(attr_name).lower(),
                        confidence="app_xml_reference",
                        reason=f"Referenced by appearance attribute {attr_name}",
                    )
                )
        for prefab in descriptor.prefabs:
            resolved = _resolve_basenames(
                prefab.name,
                "Name",
                basename_index,
                source_path=entry.path,
                path_index=path_index,
            )
            if not resolved:
                edges.append(
                    _unresolved_edge(
                        source_path,
                        prefab.name,
                        "Name",
                        role=prefab.tag.lower(),
                        reason=f"Appearance prefab {prefab.tag} was not resolved",
                    )
                )
                continue
            for related in resolved:
                role = prefab.tag.lower()
                edges.append(
                    _edge_for_entry(
                        source_path,
                        related,
                        role=role,
                        confidence="app_xml_prefab",
                        reason=f"Appearance {prefab.tag} prefab reference",
                    )
                )
                if _relation_kind_for_entry(related) == "prefab_data":
                    edges.extend(
                        _expand_prefabdata_graph(
                            source_path,
                            related,
                            archive_entries,
                            basename_index=basename_index,
                            path_index=path_index,
                        )
                    )
                if _relation_kind_for_entry(related) in {"model", "material_sidecar"}:
                    edges.extend(
                        resolve_material_texture_graph(
                            related,
                            archive_entries,
                            path_index=path_index,
                            basename_index=basename_index,
                        ).edges
                    )

    if relation_kind == "prefab_data":
        edges.extend(
            _expand_prefabdata_graph(
                source_path,
                entry,
                archive_entries,
                basename_index=basename_index,
                path_index=path_index,
            )
        )

    if relation_kind == "prefab":
        edges.extend(
            _expand_binary_prefab_graph(
                source_path,
                entry,
                archive_entries,
                basename_index=basename_index,
                path_index=path_index,
            )
        )

    # Follow direct models/sidecars discovered from XML once so app graphs include textures.
    expanded: List[ArchiveRelationEdge] = []
    for edge in edges:
        expanded.append(edge)
        if edge.related_entry is None:
            continue
        if _relation_kind_for_entry(edge.related_entry) in {"model", "material_sidecar"}:
            expanded.extend(
                resolve_material_texture_graph(
                    edge.related_entry,
                    archive_entries,
                    path_index=path_index,
                    basename_index=basename_index,
                ).edges
            )
    return ArchiveRelationshipPlan(source_path=source_path, mode=mode, edges=_dedupe_edges(expanded), warnings=tuple(warnings))


def _find_related_app_entries(entry: ArchiveEntry, archive_entries: Sequence[ArchiveEntry]) -> Tuple[ArchiveEntry, ...]:
    if str(entry.extension or "").lower() == ".app_xml":
        return (entry,)
    source_stem = PurePosixPath(entry.path.replace("\\", "/")).stem.lower()
    if not source_stem:
        return ()
    tokens = tuple(token for token in re.split(r"[^a-z0-9]+", source_stem) if token and len(token) > 1)
    app_candidates = tuple(candidate for candidate in archive_entries if str(candidate.extension or "").lower() == ".app_xml")
    scored: List[Tuple[int, ArchiveEntry]] = []
    for candidate in archive_entries:
        if str(candidate.extension or "").lower() != ".app_xml":
            continue
        candidate_path = candidate.path.replace("\\", "/").lower()
        score = 0
        if source_stem in candidate_path:
            score += 80
        for token in tokens:
            if token in candidate_path:
                score += 8
        if score > 0:
            scored.append((score, candidate))
    # Reading thousands of app_xml payloads on the GUI thread is expensive.
    # Path matches are enough for named characters like Damian/Macduff; only
    # fall back to payload scanning when no plausible path match exists.
    if scored:
        scored.sort(key=lambda item: (item[0], -len(item[1].path)), reverse=True)
        return tuple(candidate for _score, candidate in scored[:8])
    for candidate in app_candidates:
        candidate_path = candidate.path.replace("\\", "/").lower()
        score = 0
        try:
            text = _read_entry_text(candidate).lower()
        except Exception:
            text = ""
        if source_stem in text:
            score += 120
        for token in tokens:
            if token in text:
                score += 4
        for token in tokens:
            if token in candidate_path:
                score += 2
        if score > 0:
            scored.append((score, candidate))
    scored.sort(key=lambda item: (item[0], -len(item[1].path)), reverse=True)
    result: List[ArchiveEntry] = []
    seen: set[str] = set()
    for _score, candidate in scored[:8]:
        key = _entry_key(candidate)
        if key not in seen:
            result.append(candidate)
            seen.add(key)
    return tuple(result)


def _find_primary_sidecar(entry: ArchiveEntry, archive_entries: Sequence[ArchiveEntry]) -> Optional[ArchiveEntry]:
    basename_index = _build_basename_index(archive_entries)
    sidecars = _find_archive_model_sidecar_entries(entry, dict(basename_index))
    return sidecars[0] if sidecars else None


def _patch_target_app_with_source(
    target_app: ArchiveEntry,
    source_app: ArchiveEntry,
    *,
    swap_scope: str,
) -> Tuple[bytes, str]:
    try:
        target_text = _read_entry_text(target_app)
        source_text = _read_entry_text(source_app)
    except Exception:
        return b"", ""
    target_root = _parse_xml(target_text)
    source_root = _parse_xml(source_text)
    if target_root is None or source_root is None:
        return b"", ""
    tags_to_patch = {"Nude"}
    if swap_scope == SWAP_SCOPE_BODY_HEAD:
        tags_to_patch.add("Head")
    elif swap_scope == SWAP_SCOPE_FULL_APPEARANCE_REDIRECT:
        tags_to_patch.update({"Head", "Hair", "Armor", "Accessory", "Face", "Body"})

    source_by_tag: Dict[str, ET.Element] = {}
    for element in source_root.iter():
        local = _local_name(element.tag)
        if local in tags_to_patch and ("Name" in element.attrib or "name" in element.attrib):
            source_by_tag.setdefault(local, element)

    changed = False
    for element in target_root.iter():
        local = _local_name(element.tag)
        source_element = source_by_tag.get(local)
        if source_element is None:
            continue
        for attr_name, source_value in source_element.attrib.items():
            if attr_name.lower() in {"name", "characterscale", "scale", "preview"} or "scale" in attr_name.lower():
                target_key = attr_name if attr_name in element.attrib else next(
                    (key for key in element.attrib if key.lower() == attr_name.lower()),
                    attr_name,
                )
                if element.attrib.get(target_key) != source_value:
                    element.attrib[target_key] = source_value
                    changed = True
    if not changed:
        return b"", ""
    return ET.tostring(target_root, encoding="utf-8", xml_declaration=True), target_app.path.replace("\\", "/")


def build_character_swap_plan(
    target_entry: ArchiveEntry,
    source_entry: ArchiveEntry,
    archive_entries: Sequence[ArchiveEntry],
    swap_scope: str = SWAP_SCOPE_BODY_HEAD,
) -> ArchiveRelationshipPlan:
    if swap_scope not in {SWAP_SCOPE_BODY_ONLY, SWAP_SCOPE_BODY_HEAD, SWAP_SCOPE_FULL_APPEARANCE_REDIRECT}:
        swap_scope = SWAP_SCOPE_BODY_HEAD
    source_path = source_entry.path.replace("\\", "/")
    target_apps = _find_related_app_entries(target_entry, archive_entries)
    source_apps = _find_related_app_entries(source_entry, archive_entries)
    edges: List[ArchiveRelationEdge] = []
    warnings: List[str] = []
    patched_payload = b""
    patched_target_path = ""

    if target_apps and source_apps:
        patched_payload, patched_target_path = _patch_target_app_with_source(
            target_apps[0],
            source_apps[0],
            swap_scope=swap_scope,
        )
        if patched_payload:
            edges.append(
                ArchiveRelationEdge(
                    source_path=source_path,
                    related_path=patched_target_path,
                    related_entry=target_apps[0],
                    relation_kind="appearance_patch",
                    role=swap_scope,
                    confidence="app_xml_patch",
                    reason="Patch target appearance body/head prefab names while preserving other target appearance sections",
                    include_policy=ARCHIVE_REL_INCLUDE_REQUIRED,
                    suggested_target_path=patched_target_path,
                )
            )
        else:
            warnings.append("No target appearance XML patch was produced for the selected source/target pair.")
        source_app_plan = build_archive_relationship_plan(source_apps[0], archive_entries, mode="character_swap_source_graph")
        edges.extend(source_app_plan.edges)
        warnings.extend(source_app_plan.warnings)
    else:
        warnings.append("Character appearance XML could not be resolved for the selected source/target pair.")

    source_sidecar = _find_primary_sidecar(source_entry, archive_entries)
    target_sidecar = _find_primary_sidecar(target_entry, archive_entries)
    if source_sidecar is not None and target_sidecar is not None:
        source_names = set(_read_sidecar_submesh_names(source_sidecar))
        target_names = set(_read_sidecar_submesh_names(target_sidecar))
        if source_names and target_names and source_names != target_names:
            warnings.append(
                "Source and target material sidecar submesh wrappers differ; generated/retargeted sidecar patching is preferred over copying source sidecar bytes."
            )
            edges.append(
                ArchiveRelationEdge(
                    source_path=source_path,
                    related_path=source_sidecar.path.replace("\\", "/"),
                    related_entry=source_sidecar,
                    relation_kind="material_sidecar",
                    role="topology_reference",
                    confidence="topology_diff",
                    reason="Source material wrapper topology differs from target; use as patch input, not direct source-sidecar copy.",
                    include_policy=ARCHIVE_REL_INCLUDE_MANUAL,
                    risk=True,
                )
            )
    material_plan = resolve_material_texture_graph(source_entry, archive_entries)
    edges.extend(material_plan.edges)
    return ArchiveRelationshipPlan(
        source_path=source_path,
        mode="character_swap",
        edges=_dedupe_edges(edges),
        warnings=tuple(dict.fromkeys(warnings)),
        swap_scope=swap_scope,
        patched_target_app_xml=patched_payload,
        patched_target_app_path=patched_target_path,
    )


def _edge_resolves_entry(edge: ArchiveRelationEdge, target: ArchiveEntry) -> bool:
    target_path = _normalized_archive_path(target.path)
    edge_path = _normalized_archive_path(edge.related_path)
    if edge_path == target_path:
        return True
    if edge.related_entry is not None and _normalized_archive_path(edge.related_entry.path) == target_path:
        return True
    return False


def _relationship_plan_references_body(
    plan: ArchiveRelationshipPlan,
    body_entry: ArchiveEntry,
) -> bool:
    body_path = _normalized_archive_path(body_entry.path)
    body_name = PurePosixPath(body_path).name
    body_stem = PurePosixPath(body_path).stem
    for edge in plan.edges:
        related_path = _normalized_archive_path(edge.related_path)
        if related_path == body_path:
            return True
        related_name = PurePosixPath(related_path).name
        if related_name == body_name:
            return True
        if PurePosixPath(related_path).stem == body_stem and str(edge.relation_kind or "") in {"model", "prefab_data", "prefab"}:
            return True
    return False


def _strict_animation_token_match(body_entry: ArchiveEntry, candidate: ArchiveEntry) -> bool:
    body_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", PurePosixPath(_normalized_archive_path(body_entry.path)).stem)
        if len(token) > 2
    }
    if not body_tokens:
        return False
    candidate_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", PurePosixPath(_normalized_archive_path(candidate.path)).stem)
        if len(token) > 2
    }
    return bool(body_tokens and body_tokens.issubset(candidate_tokens))


def build_character_dependency_plan(
    body_entry: ArchiveEntry,
    archive_entries: Sequence[ArchiveEntry],
    *,
    selected_appearance_path: str = "",
) -> CharacterDependencyPlan:
    body_path = body_entry.path.replace("\\", "/")
    app_entries = tuple(entry for entry in archive_entries if str(entry.extension or "").lower() == ".app_xml")
    matched_apps: List[ArchiveEntry] = []
    plans_by_app: Dict[str, ArchiveRelationshipPlan] = {}
    warnings: List[str] = []
    for app_entry in app_entries:
        try:
            plan = build_archive_relationship_plan(app_entry, archive_entries, mode="character_dependency_scan")
        except Exception as exc:
            warnings.append(f"Skipped {app_entry.path}: {exc}")
            continue
        plans_by_app[_normalized_archive_path(app_entry.path)] = plan
        if _relationship_plan_references_body(plan, body_entry):
            matched_apps.append(app_entry)

    if not matched_apps:
        return CharacterDependencyPlan(
            body_path=body_path,
            warnings=tuple(dict.fromkeys(warnings)),
            blocking_errors=(f"No matching appearance descriptor was found for body/model {body_path}.",),
        )

    selected_key = _normalized_archive_path(selected_appearance_path)
    selected_app = next(
        (entry for entry in matched_apps if _normalized_archive_path(entry.path) == selected_key),
        matched_apps[0],
    )
    selected_plan = plans_by_app.get(_normalized_archive_path(selected_app.path))
    if selected_plan is None:
        selected_plan = build_archive_relationship_plan(selected_app, archive_entries, mode="character_dependency")

    edges: List[ArchiveRelationEdge] = [
        ArchiveRelationEdge(
            source_path=body_path,
            related_path=selected_app.path.replace("\\", "/"),
            related_entry=selected_app,
            relation_kind="appearance",
            role="selected_appearance",
            confidence="strict_graph_match",
            reason="Appearance descriptor relationship graph references the selected body/model.",
            include_policy=ARCHIVE_REL_INCLUDE_REQUIRED,
        )
    ]
    edges.extend(selected_plan.edges)
    edges.extend(resolve_material_texture_graph(body_entry, archive_entries).edges)

    for candidate in archive_entries:
        if str(candidate.extension or "").lower() not in _ANIMATION_EXTENSIONS:
            continue
        if _strict_animation_token_match(body_entry, candidate):
            edges.append(
                ArchiveRelationEdge(
                    source_path=body_path,
                    related_path=candidate.path.replace("\\", "/"),
                    related_entry=candidate,
                    relation_kind="animation",
                    role="strict_token_animation",
                    confidence="token_match",
                    reason="Animation/motion entry matched all significant body/model stem tokens.",
                    include_policy=ARCHIVE_REL_INCLUDE_RECOMMENDED,
                )
            )

    entries: List[ArchiveEntry] = [body_entry, selected_app]
    seen_entries: set[str] = {_entry_key(body_entry), _entry_key(selected_app)}
    for edge in _dedupe_edges(edges):
        if edge.related_entry is None:
            continue
        key = _entry_key(edge.related_entry)
        if key in seen_entries:
            continue
        seen_entries.add(key)
        entries.append(edge.related_entry)

    return CharacterDependencyPlan(
        body_path=body_path,
        selected_appearance_path=selected_app.path.replace("\\", "/"),
        appearance_paths=tuple(entry.path.replace("\\", "/") for entry in matched_apps),
        entries=tuple(entries),
        edges=_dedupe_edges(edges),
        warnings=tuple(dict.fromkeys([*warnings, *selected_plan.warnings])),
        blocking_errors=(
            ("Multiple matching appearance descriptors were found; user selection is required for exact export.",)
            if len(matched_apps) > 1 and not selected_appearance_path
            else ()
        ),
    )
