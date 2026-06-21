from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple
import xml.etree.ElementTree as ET

from cdmw.constants import ARCHIVE_IMAGE_EXTENSIONS
from cdmw.core.archive import (
    ArchiveEntry,
    archive_entry_role,
    ensure_archive_preview_source,
    read_archive_entry_data,
    try_decode_text_like_archive_data,
)
from cdmw.core.classification_registry import get_registered_texture_classification
from cdmw.core.common import raise_if_cancelled
from cdmw.domain.textures.output import max_mips_for_size
from cdmw.domain.textures.plan import describe_processing_path_kind
from cdmw.core.texture_pipeline.runtime_config import normalize_config, normalize_config_for_planning
from cdmw.core.texture_pipeline.discovery import collect_dds_files
from cdmw.core.texture_pipeline.inspection import parse_dds
from cdmw.core.texture_pipeline.planning import (
    _build_loose_sidecar_index,
    _collect_loose_sidecar_texts,
    build_texture_processing_plan,
)
from cdmw.core.texture_pipeline.preview import collect_compare_relative_paths, ensure_dds_preview_png
from cdmw.domain.textures.profiles import _SCALAR_HIGH_PRECISION_MASK_SUBTYPES
from cdmw.core.upscale_profiles import (
    derive_texture_group_key as derive_semantic_texture_group_key,
    infer_texture_semantics,
    is_png_intermediate_high_risk,
    normalize_texture_reference_for_sidecar_lookup,
    parse_texture_sidecar_bindings,
)
from cdmw.models import AppConfig, DdsInfo, TextureProcessingPlan

try:
    from PySide6.QtGui import QColor, QImage
except Exception:  # pragma: no cover - GUI/runtime fallback
    QImage = None  # type: ignore[assignment]
    QColor = None  # type: ignore[assignment]


TEXTURE_IMAGE_EXTENSIONS = {
    ".bmp",
    ".dds",
    ".gif",
    ".hdr",
    ".jpeg",
    ".jpg",
    ".png",
    ".tga",
    ".tif",
    ".tiff",
    ".webp",
}
TEXTURE_SIDECAR_EXTENSIONS = {
    ".material",
    ".shader",
    ".xml",
    ".json",
    ".pami",
}
REFERENCE_SOURCE_EXTENSIONS = {
    ".cfg",
    ".ini",
    ".json",
    ".lua",
    ".material",
    ".pami",
    ".shader",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
TEXTURE_REFERENCE_PATTERN = re.compile(
    r"(?i)([A-Za-z0-9_./\\\\-]+\.(?:dds|png|tga|jpg|jpeg|bmp|gif|tiff?|webp|hdr))"
)
REGEX_PRESET_DEFAULT_EXTENSIONS = ".xml;.json;.cfg;.ini;.lua;.material;.shader;.pami"

_SYSTEM_AREA_RULES: Tuple[Tuple[str, str], ...] = (
    ("ui", "ui"),
    ("ui", "icon"),
    ("ui", "hud"),
    ("ui", "menu"),
    ("ui", "widget"),
    ("sound", "sound"),
    ("sound", "voice"),
    ("sound", "dialog"),
    ("gameplay", "gameplay"),
    ("gameplay", "quest"),
    ("gameplay", "skill"),
    ("gameplay", "actor"),
    ("gameplay", "npc"),
    ("gameplay", "battle"),
    ("materials", "material"),
    ("materials", "renderpass"),
    ("materials", "shader"),
    ("materials", "effect"),
    ("textures", "texture"),
    ("textures", "impostor"),
    ("textures", "decal"),
    ("textures", "atlas"),
    ("world", "object"),
    ("world", "interior"),
    ("world", "gimmick"),
    ("world", "nature"),
    ("character", "character"),
    ("character", "head"),
    ("character", "body"),
    ("animation", "anim"),
    ("animation", "motion"),
    ("animation", "hkx"),
)
_XML_ATTRIBUTE_PATTERN = re.compile(r"([A-Za-z_:][A-Za-z0-9_.:-]*)\s*=\s*\"([^\"]*)\"")
_GET_RECT_PATTERN = re.compile(r"^\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*$")


@dataclass(slots=True)
class DependencyEdge:
    left: str
    right: str
    package_count: int
    example_packages: List[str] = field(default_factory=list)


@dataclass(slots=True)
class TextureClassificationRow:
    path: str
    package_label: str
    texture_type: str
    confidence: int
    reason: str
    group_key: str


@dataclass(slots=True)
class TextureSetMember:
    path: str
    package_label: str
    member_kind: str
    extension: str


@dataclass(slots=True)
class TextureSetGroup:
    group_key: str
    display_name: str
    member_count: int
    package_labels: List[str]
    member_kinds: List[str]
    members: List[TextureSetMember] = field(default_factory=list)


@dataclass(slots=True)
class UnknownResolverSuggestion:
    choice_key: str
    texture_type: str
    semantic_subtype: str
    confidence: int
    reason: str


@dataclass(slots=True)
class UnknownResolverMember:
    path: str
    package_label: str
    current_kind: str
    reason: str
    role_hint: str = ""
    extension: str = ""
    is_unknown: bool = True
    local_texture_type: str = ""
    local_semantic_subtype: str = ""


@dataclass(slots=True)
class UnknownResolverGroup:
    group_key: str
    display_name: str
    unknown_count: int
    total_members: int
    package_labels: List[str]
    known_kinds: List[str]
    sidecar_paths: List[str]
    suggestion_label: str = ""
    members: List[UnknownResolverMember] = field(default_factory=list)
    suggestions: List[UnknownResolverSuggestion] = field(default_factory=list)
    local_approval_state: str = "None"










@dataclass(slots=True)
class RegexPreset:
    category: str
    name: str
    pattern: str
    description: str
    extensions: str = REGEX_PRESET_DEFAULT_EXTENSIONS
    path_hint: str = ""


@dataclass(slots=True)
class SearchCluster:
    mode: str
    label: str
    file_count: int
    total_matches: int
    sample_paths: List[str] = field(default_factory=list)


@dataclass(slots=True)
class MaterialTextureReferenceRow:
    source_path: str
    source_package_label: str
    related_path: str
    related_package_label: str
    relation_kind: str
    match_count: int
    snippet: str
    source_kind: str = ""
    texture_name: str = ""
    filename_token: str = ""
    get_rect_raw: str = ""
    rect_x: int = -1
    rect_y: int = -1
    rect_width: int = 0
    rect_height: int = 0
    texture_width: int = 0
    texture_height: int = 0
    constraint_kind: str = ""
    warning_text: str = ""
    evidence_level: str = ""


@dataclass(slots=True)
class SidecarDiscoveryRow:
    anchor_path: str
    related_path: str
    package_label: str
    relation_kind: str
    confidence: int
    reason: str












@dataclass(slots=True)
class ResearchNote:
    target_key: str
    source_kind: str
    tags: List[str]
    note: str
    updated_at: str


def _normalized_parts(path_value: str) -> Tuple[str, ...]:
    return tuple(part for part in PurePosixPath(path_value.replace("\\", "/")).parts if part)


def system_area_from_path(path_value: str) -> str:
    lowered = path_value.replace("\\", "/").lower()
    for area, token in _SYSTEM_AREA_RULES:
        if f"/{token}/" in lowered or lowered.startswith(f"{token}/") or token in lowered.split("/")[0]:
            return area
    parts = _normalized_parts(path_value)
    if not parts:
        return "other"
    head = parts[0].lower()
    return {
        "object": "world",
        "character": "character",
        "sound": "sound",
        "material": "materials",
        "ui": "ui",
    }.get(head, head if len(head) <= 16 else "other")


def _package_bucket_for_path(path_value: str) -> str:
    parts = _normalized_parts(path_value)
    if not parts:
        return "other"
    prefix = "/".join(parts[:2]) if len(parts) >= 2 else "/".join(parts)
    return f"{system_area_from_path(path_value)} :: {prefix}"


def build_archive_dependency_graph(entries: Sequence[ArchiveEntry], *, top_n: int = 120) -> List[DependencyEdge]:
    packages: Dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        packages[entry.package_label].add(_package_bucket_for_path(entry.path))

    pair_counts: Counter[Tuple[str, str]] = Counter()
    pair_examples: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for package_label, bucket_set in packages.items():
        if len(bucket_set) < 2:
            continue
        for left, right in combinations(sorted(bucket_set), 2):
            pair = (left, right)
            pair_counts[pair] += 1
            if len(pair_examples[pair]) < 3:
                pair_examples[pair].append(package_label)

    edges = [
        DependencyEdge(
            left=left,
            right=right,
            package_count=count,
            example_packages=pair_examples[(left, right)],
        )
        for (left, right), count in pair_counts.most_common(top_n)
    ]
    return edges


def classify_texture_path(
    path_value: str,
    *,
    role_hint: str = "",
    family_members: Sequence[str] = (),
    sidecar_texts: Sequence[str] = (),
) -> Tuple[str, int, str]:
    if role_hint == "ui":
        return "ui", 92, "archive role marked as UI"
    if role_hint == "impostor":
        return "impostor", 96, "archive role marked as impostor"
    semantic = infer_texture_semantics(path_value, family_members=family_members, sidecar_texts=sidecar_texts)
    if semantic.texture_type != "unknown":
        reason = semantic.evidence[0] if semantic.evidence else "semantic inference"
        return semantic.texture_type, semantic.confidence, reason
    if role_hint == "normal":
        return "normal", 72, "archive role marked as normal-like companion map"
    if role_hint == "material":
        return "mask", 58, "archive role marked as technical/material companion map"
    lowered = path_value.replace("\\", "/").lower()
    if "/texture/" in lowered or Path(lowered).suffix.lower() in TEXTURE_IMAGE_EXTENSIONS:
        return "unknown", 45, "image/texture path without a stronger semantic hint"
    return "unknown", 25, "no strong texture-type hint"


def _read_archive_sidecar_text(
    entry: ArchiveEntry,
    *,
    stop_event: Optional[object] = None,
) -> str:
    try:
        raw, _decompressed, _note = read_archive_entry_data(entry, stop_event=stop_event)
    except Exception:
        return ""
    return str(try_decode_text_like_archive_data(raw) or "").strip()


def _build_archive_sidecar_reference_index(
    entries: Sequence[ArchiveEntry],
    *,
    stop_event: Optional[object] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    progress_label: str = "Building archive research snapshot: indexing sidecar texture bindings...",
) -> Tuple[Dict[str, Tuple[str, ...]], Dict[str, Tuple[str, ...]]]:
    sidecar_entries = [entry for entry in entries if entry.extension in TEXTURE_SIDECAR_EXTENSIONS]
    if not sidecar_entries:
        return {}, {}

    texts_by_texture_path: Dict[str, List[str]] = defaultdict(list)
    texts_by_texture_basename: Dict[str, List[str]] = defaultdict(list)
    total_sidecars = len(sidecar_entries)
    progress_interval = max(total_sidecars // 100, 1) if total_sidecars > 0 else 1
    for index, entry in enumerate(sidecar_entries, start=1):
        raise_if_cancelled(stop_event, "Research refresh cancelled.")
        text = _read_archive_sidecar_text(entry, stop_event=stop_event)
        if text and entry.extension in {".xml", ".pami"}:
            for binding in parse_texture_sidecar_bindings(text, sidecar_path=entry.path):
                normalized_texture = normalize_texture_reference_for_sidecar_lookup(binding.texture_path)
                if not normalized_texture:
                    continue
                texts_by_texture_path[normalized_texture].append(text)
                texture_basename = PurePosixPath(normalized_texture).name
                if texture_basename:
                    texts_by_texture_basename[texture_basename].append(text)
        if on_progress is not None and (index == total_sidecars or index % progress_interval == 0):
            on_progress(index, total_sidecars, f"{progress_label} {index:,} / {total_sidecars:,}")

    normalized_path_map = {
        key: tuple(dict.fromkeys(value))
        for key, value in texts_by_texture_path.items()
    }
    normalized_basename_map = {
        key: tuple(dict.fromkeys(value))
        for key, value in texts_by_texture_basename.items()
    }
    return normalized_path_map, normalized_basename_map


def _collect_archive_texture_sidecar_texts(
    path_value: str,
    *,
    sidecar_texts_by_texture_path: Dict[str, Tuple[str, ...]],
    sidecar_texts_by_texture_basename: Dict[str, Tuple[str, ...]],
    limit: int = 6,
) -> Tuple[str, ...]:
    normalized_target = normalize_texture_reference_for_sidecar_lookup(path_value)
    if not normalized_target:
        return ()
    target_basename = PurePosixPath(normalized_target).name
    collected: List[str] = []
    seen: set[str] = set()
    for text in sidecar_texts_by_texture_path.get(normalized_target, ()):
        if text in seen:
            continue
        seen.add(text)
        collected.append(text)
        if len(collected) >= limit:
            return tuple(collected)
    for text in sidecar_texts_by_texture_basename.get(target_basename, ()):
        if text in seen:
            continue
        seen.add(text)
        collected.append(text)
        if len(collected) >= limit:
            break
    return tuple(collected)


def derive_texture_group_key(path_value: str) -> str:
    return derive_semantic_texture_group_key(path_value)


def build_archive_research_snapshot(
    entries: Sequence[ArchiveEntry],
    *,
    classification_limit: int = 3000,
    group_limit: int = 2000,
    heatmap_limit_per_scope: int = 24,
    sidecar_source_entries: Optional[Sequence[ArchiveEntry]] = None,
    stop_event: Optional[object] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, object]:
    family_members_by_group: Dict[str, List[str]] = defaultdict(list)
    grouped_entries: Dict[str, List[ArchiveEntry]] = defaultdict(list)
    entry_metadata: List[Tuple[ArchiveEntry, str, bool, bool, str, str]] = []
    total_entries = len(entries)
    progress_interval = max(total_entries // 200, 1) if total_entries > 0 else 1

    for index, entry in enumerate(entries, start=1):
        raise_if_cancelled(stop_event, "Research refresh cancelled.")
        normalized_path = entry.path.replace("\\", "/")
        lowered = normalized_path.lower()
        is_texture = entry.extension in TEXTURE_IMAGE_EXTENSIONS or "/texture/" in lowered
        is_sidecar = entry.extension in TEXTURE_SIDECAR_EXTENSIONS
        group_key = derive_texture_group_key(normalized_path)
        if is_texture:
            family_members_by_group[group_key].append(normalized_path)
        if is_texture or is_sidecar:
            grouped_entries[group_key].append(entry)
        entry_metadata.append((entry, normalized_path, is_texture, is_sidecar, lowered, group_key))
        if on_progress is not None and (index == total_entries or index % progress_interval == 0):
            on_progress(index, total_entries, f"Building archive research snapshot: indexing archive entries... {index:,} / {total_entries:,}")

    semantic_source_entries = list(sidecar_source_entries or entries)
    uses_external_sidecar_source = sidecar_source_entries is not None
    archive_sidecar_texts_by_texture_path, archive_sidecar_texts_by_texture_basename = _build_archive_sidecar_reference_index(
        semantic_source_entries,
        stop_event=stop_event,
        on_progress=on_progress,
        progress_label=(
            "Building archive research snapshot: indexing loaded archive sidecar texture bindings..."
            if uses_external_sidecar_source
            else "Building archive research snapshot: indexing sidecar texture bindings..."
        ),
    )

    classification_rows: List[TextureClassificationRow] = []
    classified_kinds_by_path: Dict[str, str] = {}
    heatmap_scopes: Dict[Tuple[str, str], Dict[str, object]] = {}
    metadata_total = len(entry_metadata)
    metadata_interval = max(metadata_total // 200, 1) if metadata_total > 0 else 1

    for index, (entry, normalized_path, is_texture, is_sidecar, lowered, group_key) in enumerate(entry_metadata, start=1):
        raise_if_cancelled(stop_event, "Research refresh cancelled.")
        if not is_texture and not is_sidecar:
            continue

        family_members = tuple(family_members_by_group.get(group_key, ()))
        role_hint = archive_entry_role(entry)
        sidecar_texts = _collect_archive_texture_sidecar_texts(
            normalized_path,
            sidecar_texts_by_texture_path=archive_sidecar_texts_by_texture_path,
            sidecar_texts_by_texture_basename=archive_sidecar_texts_by_texture_basename,
        )
        texture_type, confidence, reason = classify_texture_path(
            normalized_path,
            role_hint=role_hint,
            family_members=family_members,
            sidecar_texts=sidecar_texts,
        )
        classified_kinds_by_path[lowered] = texture_type

        if is_texture:
            classification_rows.append(
                TextureClassificationRow(
                    path=entry.path,
                    package_label=entry.package_label,
                    texture_type=texture_type,
                    confidence=confidence,
                    reason=reason,
                    group_key=group_key,
                )
            )

        parts = _normalized_parts(normalized_path)
        folder_label = "/".join(parts[:3]) if len(parts) >= 3 else ("/".join(parts) or entry.package_label)
        scope_labels = (
            ("System Area", system_area_from_path(normalized_path)),
            ("Folder", folder_label),
            ("Package", entry.package_label),
        )

        for scope_name, label in scope_labels:
            bucket = heatmap_scopes.setdefault(
                (scope_name, label),
                {
                    "texture_count": 0,
                    "set_keys": set(),
                    "normal_count": 0,
                    "ui_count": 0,
                    "material_count": 0,
                    "impostor_count": 0,
                    "sample_paths": [],
                },
            )
            if is_texture:
                bucket["texture_count"] += 1
                bucket["set_keys"].add(group_key)
                if texture_type == "normal":
                    bucket["normal_count"] += 1
                if texture_type == "ui":
                    bucket["ui_count"] += 1
                if texture_type == "impostor":
                    bucket["impostor_count"] += 1
            if is_sidecar:
                bucket["material_count"] += 1
            sample_paths = bucket["sample_paths"]
            if len(sample_paths) < 3:
                sample_paths.append(entry.path)
        if on_progress is not None and (index == metadata_total or index % metadata_interval == 0):
            on_progress(index, metadata_total, f"Building archive research snapshot: classifying textures and heatmap scopes... {index:,} / {metadata_total:,}")

    classification_rows.sort(key=lambda row: (-row.confidence, row.texture_type, row.path))

    texture_groups: List[TextureSetGroup] = []
    group_items = list(grouped_entries.items())
    group_total = len(group_items)
    group_interval = max(group_total // 100, 1) if group_total > 0 else 1
    for index, (group_key, entry_members) in enumerate(group_items, start=1):
        raise_if_cancelled(stop_event, "Research refresh cancelled.")
        if len(entry_members) < 2:
            if on_progress is not None and (index == group_total or index % group_interval == 0):
                on_progress(index, group_total, f"Building archive research snapshot: assembling texture groups... {index:,} / {group_total:,}")
            continue
        members: List[TextureSetMember] = []
        for entry in sorted(entry_members, key=lambda member: member.path):
            lowered = entry.path.replace("\\", "/").lower()
            member_kind = classified_kinds_by_path.get(lowered, "unknown")
            if entry.extension in TEXTURE_SIDECAR_EXTENSIONS and member_kind == "unknown":
                member_kind = "sidecar"
            members.append(
                TextureSetMember(
                    path=entry.path,
                    package_label=entry.package_label,
                    member_kind=member_kind,
                    extension=entry.extension,
                )
            )
        package_labels = sorted({member.package_label for member in members})
        member_kinds = sorted({member.member_kind for member in members})
        texture_groups.append(
            TextureSetGroup(
                group_key=group_key,
                display_name=PurePosixPath(group_key).name or group_key,
                member_count=len(members),
                package_labels=package_labels,
                member_kinds=member_kinds,
                members=members,
            )
        )
        if on_progress is not None and (index == group_total or index % group_interval == 0):
            on_progress(index, group_total, f"Building archive research snapshot: assembling texture groups... {index:,} / {group_total:,}")
    texture_groups.sort(key=lambda group: (-group.member_count, group.display_name))

    heatmap_rows: List[TextureUsageHeatRow] = []
    for (scope_name, label), bucket in heatmap_scopes.items():
        raise_if_cancelled(stop_event, "Research refresh cancelled.")
        set_count = len(bucket["set_keys"])
        heat_score = (
            int(bucket["texture_count"])
            + (set_count * 2)
            + (int(bucket["normal_count"]) * 2)
            + (int(bucket["ui_count"]) * 2)
            + int(bucket["material_count"])
            + (int(bucket["impostor_count"]) * 2)
        )
        heatmap_rows.append(
            TextureUsageHeatRow(
                scope=scope_name,
                label=label,
                texture_count=int(bucket["texture_count"]),
                set_count=set_count,
                normal_count=int(bucket["normal_count"]),
                ui_count=int(bucket["ui_count"]),
                material_count=int(bucket["material_count"]),
                impostor_count=int(bucket["impostor_count"]),
                heat_score=heat_score,
                sample_paths=list(bucket["sample_paths"]),
            )
        )

    grouped_heatmap_rows: Dict[str, List[TextureUsageHeatRow]] = defaultdict(list)
    for row in heatmap_rows:
        grouped_heatmap_rows[row.scope].append(row)

    flattened_heatmap_rows: List[TextureUsageHeatRow] = []
    for scope_name in ("System Area", "Folder", "Package"):
        scope_rows = sorted(
            grouped_heatmap_rows.get(scope_name, []),
            key=lambda row: (-row.heat_score, -row.texture_count, row.label.lower()),
        )
        flattened_heatmap_rows.extend(scope_rows[:heatmap_limit_per_scope])

    unknown_resolver_groups = _build_unknown_resolver_groups_from_grouped_entries(
        grouped_entries,
        classification_rows,
        include_classified=False,
        stop_event=stop_event,
        on_progress=on_progress,
        progress_label="Building archive research snapshot: preparing unresolved classification review...",
    )
    classification_review_groups = _build_unknown_resolver_groups_from_grouped_entries(
        grouped_entries,
        classification_rows,
        include_classified=True,
        stop_event=stop_event,
        on_progress=on_progress,
        progress_label="Building archive research snapshot: preparing full classification review...",
    )

    return {
        "classification_rows": classification_rows[:classification_limit],
        "texture_groups": texture_groups[:group_limit],
        "heatmap_rows": flattened_heatmap_rows,
        "unknown_resolver_groups": unknown_resolver_groups,
        "classification_review_groups": classification_review_groups,
    }


def classify_texture_entries(entries: Sequence[ArchiveEntry], *, limit: int = 3000) -> List[TextureClassificationRow]:
    snapshot = build_archive_research_snapshot(entries, classification_limit=limit, group_limit=0)
    rows = snapshot.get("classification_rows", [])
    return rows if isinstance(rows, list) else []


def _build_family_members_by_relative_path(paths: Sequence[str]) -> Dict[str, Tuple[str, ...]]:
    grouped: Dict[str, List[str]] = defaultdict(list)
    for path_value in paths:
        grouped[derive_texture_group_key(path_value)].append(path_value)

    family_members: Dict[str, Tuple[str, ...]] = {}
    for members in grouped.values():
        ordered = tuple(sorted(dict.fromkeys(members), key=str.lower))
        for member in ordered:
            family_members[member] = ordered
    return family_members


_UNKNOWN_RESOLVER_LABELS: Tuple[Tuple[str, str, str], ...] = (
    ("color_albedo", "color", "albedo"),
    ("color_variant", "color", "albedo_variant"),
    ("ui", "ui", "ui"),
    ("emissive", "emissive", "emissive"),
    ("normal", "normal", "normal"),
    ("roughness", "roughness", "roughness"),
    ("height", "height", "displacement"),
    ("mask_generic", "mask", "mask"),
    ("mask_specular", "mask", "specular"),
    ("mask_opacity", "mask", "opacity_mask"),
    ("vector", "vector", "vector"),
    ("unknown", "unknown", "unknown"),
)


def default_unknown_resolver_label_choice() -> str:
    return "color_albedo"


def unknown_resolver_label_choices() -> List[Tuple[str, str, str]]:
    return list(_UNKNOWN_RESOLVER_LABELS)


def unknown_resolver_choice_for(texture_type: str, semantic_subtype: str) -> str:
    normalized_type = str(texture_type or "").strip().lower()
    normalized_subtype = str(semantic_subtype or "").strip().lower()
    for choice_key, choice_type, choice_subtype in _UNKNOWN_RESOLVER_LABELS:
        if normalized_type == choice_type and normalized_subtype == choice_subtype:
            return choice_key
    for choice_key, choice_type, _choice_subtype in _UNKNOWN_RESOLVER_LABELS:
        if normalized_type == choice_type:
            return choice_key
    return default_unknown_resolver_label_choice()


def unknown_resolver_choice_label(choice_key: str) -> str:
    mapping = {
        "color_albedo": "Color / Albedo",
        "color_variant": "Color / Variant",
        "ui": "UI",
        "emissive": "Emissive",
        "normal": "Normal",
        "roughness": "Roughness",
        "height": "Height / Displacement",
        "mask_generic": "Mask / Generic",
        "mask_specular": "Mask / Specular",
        "mask_opacity": "Mask / Opacity",
        "vector": "Vector",
        "unknown": "Keep Unknown",
    }
    return mapping.get(choice_key, choice_key)


def _default_semantic_subtype_for_type(texture_type: str) -> str:
    return {
        "color": "albedo",
        "ui": "ui",
        "emissive": "emissive",
        "impostor": "impostor",
        "normal": "normal",
        "roughness": "roughness",
        "height": "displacement",
        "mask": "mask",
        "vector": "vector",
    }.get(str(texture_type or "").strip().lower(), "unknown")


def _build_unknown_resolver_suggestions(
    group_key: str,
    *,
    members: Sequence[UnknownResolverMember],
    sidecar_paths: Sequence[str],
    stop_event: Optional[object] = None,
) -> List[UnknownResolverSuggestion]:
    raise_if_cancelled(stop_event, "Research refresh cancelled.")
    suggestions: List[UnknownResolverSuggestion] = []
    seen: set[str] = set()
    known_counter = Counter(
        member.current_kind
        for member in members
        if member.current_kind and member.current_kind != "unknown" and member.extension == ".dds"
    )
    normalized_group = group_key.replace("\\", "/").lower()
    joined_member_paths = " ".join(member.path.lower() for member in members)

    def add_suggestion(texture_type: str, semantic_subtype: str, confidence: int, reason: str) -> None:
        choice_key = unknown_resolver_choice_for(texture_type, semantic_subtype)
        if choice_key in seen:
            return
        seen.add(choice_key)
        suggestions.append(
            UnknownResolverSuggestion(
                choice_key=choice_key,
                texture_type=texture_type,
                semantic_subtype=semantic_subtype,
                confidence=int(confidence),
                reason=reason,
            )
        )

    if known_counter:
        dominant_kind, dominant_count = known_counter.most_common(1)[0]
        add_suggestion(
            dominant_kind,
            _default_semantic_subtype_for_type(dominant_kind),
            92 if dominant_count > 1 else 82,
            f"Family already contains {dominant_count} classified {dominant_kind} companion map(s).",
        )

    if "/ui/" in normalized_group or "/hud/" in normalized_group:
        add_suggestion("ui", "ui", 80, "Group path looks UI-related.")
    if any(token in joined_member_paths for token in ("emissive", "_emi", "_emc", "_glow", "_emit")):
        add_suggestion("emissive", "emissive", 78, "Member names contain emissive/glow hints.")
    if any(token in joined_member_paths for token in ("roughness", "smoothness", "gloss", "glossiness")):
        add_suggestion("roughness", "roughness", 80, "Member names contain explicit roughness/gloss/smoothness hints.")
    if any(token in joined_member_paths for token in ("displacement", "dmap", "height", "disp")):
        add_suggestion("height", "displacement", 80, "Member names contain explicit height/displacement hints.")
    if any(token in joined_member_paths for token in ("specular", "_spec", "_sp")):
        add_suggestion("mask", "specular", 74, "Member names contain specular hints.")
    if any(token in joined_member_paths for token in ("opacity", "alpha", "_mask")):
        add_suggestion("mask", "opacity_mask", 72, "Member names contain alpha/opacity mask hints.")

    if not suggestions:
        raise_if_cancelled(stop_event, "Research refresh cancelled.")
        variant_like_count = sum(1 for member in members if re.search(r"(?<=\d)[a-z]\.dds$", member.path, re.IGNORECASE))
        if variant_like_count >= 1 or sidecar_paths:
            add_suggestion(
                "color",
                "albedo",
                66,
                "Texture family has visible variant or sidecar evidence, which often indicates a color/albedo set.",
            )
        else:
            add_suggestion(
                "color",
                "albedo",
                58,
                "Texture path has no strong technical hint; visible color/albedo is the safest first review guess.",
            )
        add_suggestion(
            "mask",
            "mask",
            34,
            "If the texture behaves like grayscale support data, review it as a generic mask instead.",
        )

    suggestions.sort(key=lambda suggestion: (-suggestion.confidence, suggestion.choice_key))
    return suggestions[:3]


def _build_unknown_resolver_member_suggestions(
    group_key: str,
    selected_member_path: str,
    *,
    members: Sequence[UnknownResolverMember],
    sidecar_paths: Sequence[str],
    stop_event: Optional[object] = None,
) -> List[UnknownResolverSuggestion]:
    raise_if_cancelled(stop_event, "Research refresh cancelled.")
    normalized_selected = selected_member_path.replace("\\", "/").lower()
    selected_member = next(
        (
            member
            for member in members
            if member.extension == ".dds" and member.path.replace("\\", "/").lower() == normalized_selected
        ),
        None,
    )
    if selected_member is None:
        return _build_unknown_resolver_suggestions(
            group_key,
            members=members,
            sidecar_paths=sidecar_paths,
            stop_event=stop_event,
        )

    suggestions: List[UnknownResolverSuggestion] = []
    seen: set[str] = set()
    sibling_known_counter = Counter(
        member.current_kind
        for member in members
        if member.extension == ".dds"
        and member.path.replace("\\", "/").lower() != normalized_selected
        and member.current_kind
        and member.current_kind != "unknown"
    )
    normalized_group = group_key.replace("\\", "/").lower()
    selected_path_lower = selected_member.path.lower()

    def add_suggestion(texture_type: str, semantic_subtype: str, confidence: int, reason: str) -> None:
        choice_key = unknown_resolver_choice_for(texture_type, semantic_subtype)
        if choice_key in seen:
            return
        seen.add(choice_key)
        suggestions.append(
            UnknownResolverSuggestion(
                choice_key=choice_key,
                texture_type=texture_type,
                semantic_subtype=semantic_subtype,
                confidence=int(confidence),
                reason=reason,
            )
        )

    if selected_member.current_kind and selected_member.current_kind not in {"unknown", "sidecar"}:
        add_suggestion(
            selected_member.current_kind,
            _default_semantic_subtype_for_type(selected_member.current_kind),
            96,
            f"Selected DDS is currently classified in Research as {selected_member.current_kind}.",
        )

    if selected_member.role_hint == "ui":
        add_suggestion("ui", "ui", 90, "Selected DDS has a UI archive role hint.")
    elif selected_member.role_hint == "normal":
        add_suggestion("normal", "normal", 90, "Selected DDS has a normal-map archive role hint.")
    elif selected_member.role_hint == "material":
        add_suggestion("mask", "mask", 72, "Selected DDS has a material/technical archive role hint.")

    if sibling_known_counter:
        dominant_kind, dominant_count = sibling_known_counter.most_common(1)[0]
        add_suggestion(
            dominant_kind,
            _default_semantic_subtype_for_type(dominant_kind),
            78 if dominant_count > 1 else 70,
            f"Family already contains {dominant_count} classified {dominant_kind} companion map(s).",
        )

    if "/ui/" in normalized_group or "/hud/" in normalized_group:
        add_suggestion("ui", "ui", 76, "Group path looks UI-related.")
    if any(token in selected_path_lower for token in ("emissive", "_emi", "_emc", "_glow", "_emit")):
        add_suggestion("emissive", "emissive", 78, "Selected DDS name contains emissive/glow hints.")
    if any(token in selected_path_lower for token in ("roughness", "smoothness", "gloss", "glossiness")):
        add_suggestion("roughness", "roughness", 80, "Selected DDS name contains roughness/gloss hints.")
    if any(token in selected_path_lower for token in ("displacement", "dmap", "height", "disp")):
        add_suggestion("height", "displacement", 80, "Selected DDS name contains height/displacement hints.")
    if any(token in selected_path_lower for token in ("specular", "_spec", "_sp")):
        add_suggestion("mask", "specular", 74, "Selected DDS name contains specular hints.")
    if any(token in selected_path_lower for token in ("opacity", "alpha", "_mask")):
        add_suggestion("mask", "opacity_mask", 72, "Selected DDS name contains alpha/opacity mask hints.")

    if not suggestions:
        raise_if_cancelled(stop_event, "Research refresh cancelled.")
        variant_like_count = sum(1 for member in members if re.search(r"(?<=\d)[a-z]\.dds$", member.path, re.IGNORECASE))
        if variant_like_count >= 1 or sidecar_paths:
            add_suggestion(
                "color",
                "albedo",
                66,
                "Texture family has visible variant or sidecar evidence, which often indicates a color/albedo set.",
            )
        else:
            add_suggestion(
                "color",
                "albedo",
                58,
                "Texture path has no strong technical hint; visible color/albedo is the safest first review guess.",
            )
        add_suggestion(
            "mask",
            "mask",
            34,
            "If the texture behaves like grayscale support data, review it as a generic mask instead.",
        )

    suggestions.sort(key=lambda suggestion: (-suggestion.confidence, suggestion.choice_key))
    return suggestions[:3]


def build_unknown_resolver_groups(
    entries: Sequence[ArchiveEntry],
    classification_rows: Sequence[TextureClassificationRow],
    *,
    include_classified: bool = False,
    stop_event: Optional[object] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    progress_label: str = "Building classification review groups...",
) -> List[UnknownResolverGroup]:
    entries_by_group: Dict[str, List[ArchiveEntry]] = defaultdict(list)
    for entry in entries:
        raise_if_cancelled(stop_event, "Research refresh cancelled.")
        normalized_path = entry.path.replace("\\", "/")
        if entry.extension in TEXTURE_IMAGE_EXTENSIONS or entry.extension in TEXTURE_SIDECAR_EXTENSIONS:
            entries_by_group[derive_texture_group_key(normalized_path)].append(entry)
    return _build_unknown_resolver_groups_from_grouped_entries(
        entries_by_group,
        classification_rows,
        include_classified=include_classified,
        stop_event=stop_event,
        on_progress=on_progress,
        progress_label=progress_label,
    )


def _build_unknown_resolver_groups_from_grouped_entries(
    entries_by_group: Dict[str, List[ArchiveEntry]],
    classification_rows: Sequence[TextureClassificationRow],
    *,
    include_classified: bool = False,
    stop_event: Optional[object] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    progress_label: str = "Building classification review groups...",
) -> List[UnknownResolverGroup]:
    rows_by_path = {row.path.replace("\\", "/"): row for row in classification_rows}

    groups: List[UnknownResolverGroup] = []
    group_items = list(entries_by_group.items())
    group_total = len(group_items)
    progress_interval = max(group_total // 100, 1) if group_total > 0 else 1
    for index, (group_key, group_entries) in enumerate(group_items, start=1):
        raise_if_cancelled(stop_event, "Research refresh cancelled.")
        texture_rows: List[TextureClassificationRow] = []
        for entry in group_entries:
            raise_if_cancelled(stop_event, "Research refresh cancelled.")
            if entry.extension not in TEXTURE_IMAGE_EXTENSIONS:
                continue
            normalized_path = entry.path.replace("\\", "/")
            row = rows_by_path.get(normalized_path)
            if row is None:
                continue
            texture_rows.append(row)
        if not texture_rows:
            continue
        unknown_rows = [row for row in texture_rows if row.texture_type == "unknown"]
        if not unknown_rows and not include_classified:
            if on_progress is not None and (index == group_total or index % progress_interval == 0):
                on_progress(index, group_total, f"{progress_label} {index:,} / {group_total:,}")
            continue

        members: List[UnknownResolverMember] = []
        sidecar_paths: List[str] = []
        total_dds_members = 0
        local_approval_count = 0
        for entry in sorted(group_entries, key=lambda member: member.path):
            raise_if_cancelled(stop_event, "Research refresh cancelled.")
            normalized_path = entry.path.replace("\\", "/")
            row = rows_by_path.get(normalized_path)
            if entry.extension in TEXTURE_SIDECAR_EXTENSIONS:
                sidecar_paths.append(normalized_path)
            if row is None and entry.extension not in TEXTURE_IMAGE_EXTENSIONS:
                continue
            current_kind = row.texture_type if row is not None else "sidecar"
            reason = row.reason if row is not None else "Sidecar/support file in the same family."
            registered = get_registered_texture_classification(normalized_path) if entry.extension == ".dds" else None
            if entry.extension == ".dds":
                total_dds_members += 1
                if registered is not None:
                    local_approval_count += 1
            members.append(
                UnknownResolverMember(
                    path=normalized_path,
                    package_label=entry.package_label,
                    current_kind=current_kind,
                    reason=reason,
                    role_hint=archive_entry_role(entry),
                    extension=entry.extension,
                    is_unknown=bool(row is not None and row.texture_type == "unknown"),
                    local_texture_type=str(getattr(registered, "texture_type", "") or ""),
                    local_semantic_subtype=str(getattr(registered, "semantic_subtype", "") or ""),
                )
            )

        package_labels = sorted({member.package_label for member in members})
        known_kinds = sorted({member.current_kind for member in members if member.current_kind not in {"unknown", "sidecar"}})
        suggestions = _build_unknown_resolver_suggestions(
            group_key,
            members=members,
            sidecar_paths=sidecar_paths,
            stop_event=stop_event,
        )
        top_suggestion = suggestions[0] if suggestions else None
        suggestion_label = (
            f"{unknown_resolver_choice_label(top_suggestion.choice_key)} ({top_suggestion.confidence}%)"
            if top_suggestion is not None
            else "Manual review"
        )
        groups.append(
            UnknownResolverGroup(
                group_key=group_key,
                display_name=PurePosixPath(group_key).name or group_key,
                unknown_count=len(unknown_rows),
                total_members=len([member for member in members if member.extension in TEXTURE_IMAGE_EXTENSIONS]),
                package_labels=package_labels,
                known_kinds=known_kinds,
                sidecar_paths=sidecar_paths,
                suggestion_label=suggestion_label,
                members=members,
                suggestions=suggestions,
                local_approval_state=(
                    "All"
                    if total_dds_members > 0 and local_approval_count >= total_dds_members
                    else "Partial"
                    if local_approval_count > 0
                    else "None"
                ),
            )
        )
        if on_progress is not None and (index == group_total or index % progress_interval == 0):
            on_progress(index, group_total, f"{progress_label} {index:,} / {group_total:,}")

    groups.sort(key=lambda group: (-group.unknown_count, group.display_name.casefold()))
    raise_if_cancelled(stop_event, "Research refresh cancelled.")
    return groups


def build_unknown_resolver_detail(
    group: UnknownResolverGroup,
    selected_member_path: str,
    *,
    entries_by_path: Dict[str, ArchiveEntry],
    texconv_path: Optional[Path] = None,
) -> str:
    normalized_selected = selected_member_path.replace("\\", "/")
    selected_entry = entries_by_path.get(normalized_selected)
    member_suggestions = _build_unknown_resolver_member_suggestions(
        group.group_key,
        normalized_selected,
        members=group.members,
        sidecar_paths=group.sidecar_paths,
    )
    detail_lines: List[str] = [
        f"Group: {group.display_name}",
        f"Group key: {group.group_key}",
        f"Unknown members: {group.unknown_count}",
        f"Texture members in family: {group.total_members}",
        f"Known family kinds: {', '.join(group.known_kinds) if group.known_kinds else 'none'}",
        f"Packages: {', '.join(group.package_labels[:4])}" + (" ..." if len(group.package_labels) > 4 else ""),
        "",
        "Suggested labels:",
    ]
    if member_suggestions:
        for suggestion in member_suggestions:
            detail_lines.append(
                f"- {unknown_resolver_choice_label(suggestion.choice_key)} ({suggestion.confidence}%): {suggestion.reason}"
            )
    else:
        detail_lines.append("- No strong automatic suggestion. Manual review is recommended.")

    if group.sidecar_paths:
        detail_lines.extend(["", "Family sidecar/reference files:"])
        for sidecar_path in group.sidecar_paths[:6]:
            detail_lines.append(f"- {sidecar_path}")
        if len(group.sidecar_paths) > 6:
            detail_lines.append(f"- ... and {len(group.sidecar_paths) - 6} more")

    detail_lines.extend(["", f"Selected member: {normalized_selected}"])
    registered = get_registered_texture_classification(normalized_selected)
    if selected_entry is not None:
        detail_lines.append(f"- Package: {selected_entry.package_label}")
        detail_lines.append(f"- Role hint: {archive_entry_role(selected_entry) or 'none'}")
        detail_lines.append(f"- Stored size: {selected_entry.orig_size:,} bytes")
        if registered is not None:
            detail_lines.append(
                f"- Saved local approval: yes ({registered.texture_type}/{registered.semantic_subtype})"
            )
        else:
            detail_lines.append("- Saved local approval: no (current classification may only be inferred from naming/family context)")
        if selected_entry.extension == ".dds":
            try:
                source_path, _note = ensure_archive_preview_source(selected_entry)
                info = parse_dds(source_path)
                detail_lines.append(
                    f"- DDS header: {info.width}x{info.height} | {info.texconv_format} | mips={info.mip_count}"
                )
            except Exception as exc:
                detail_lines.append(f"- DDS header: unavailable ({exc})")
        if texconv_path is not None and texconv_path.exists() and selected_entry.extension == ".dds":
            detail_lines.append("- Review the selected DDS in the center preview pane for visual confirmation.")
    else:
        detail_lines.append("- Entry metadata unavailable in the current archive view.")
        if registered is not None:
            detail_lines.append(
                f"- Saved local approval: yes ({registered.texture_type}/{registered.semantic_subtype})"
            )
        else:
            detail_lines.append("- Saved local approval: no")

    detail_lines.extend(
        [
            "",
            "Approval flow:",
            "- Choose the label that best matches the selected DDS file or its family.",
            "- Save Current Role Locally stores the selected DDS file's current inferred Research role as the local approval.",
            "- Apply To Current File stores an override only for the selected DDS file.",
            "- Apply To Unknown Files In Current Family bulk-applies the label only to unresolved DDS files in that family.",
            "- Apply To Unknown Files In Selected Families does the same across all selected families in the review queue.",
            "- Clear Current File removes the override only from the selected DDS file.",
            "- Clear Current Family and Clear Selected Families remove saved overrides for all DDS files in those families.",
            "- The member list is only shown for the rare families that contain multiple texture files.",
            "- The approval is stored locally and reused by Research and texture policy in future runs.",
        ]
    )
    return "\n".join(detail_lines)


def bundle_texture_sets(entries: Sequence[ArchiveEntry], *, limit: int = 2000) -> List[TextureSetGroup]:
    snapshot = build_archive_research_snapshot(entries, classification_limit=0, group_limit=limit)
    groups = snapshot.get("texture_groups", [])
    return groups if isinstance(groups, list) else []


def _decode_reference_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "utf-16-le", "cp1252"):
        try:
            return data.decode(encoding, errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        except Exception:
            continue
    return data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def _normalize_reference_token(token: str) -> str:
    normalized = token.strip().strip("'\"").replace("\\", "/").lower()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.strip("/")


def _extract_texture_reference_tokens(text: str) -> List[str]:
    tokens: List[str] = []
    seen: set[str] = set()
    for match in TEXTURE_REFERENCE_PATTERN.finditer(text):
        normalized = _normalize_reference_token(match.group(1))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        tokens.append(normalized)
    return tokens


def _tail_path_key(path_value: str, depth: int) -> str:
    parts = _normalized_parts(path_value)
    if len(parts) < depth:
        return ""
    return "/".join(parts[-depth:]).lower()


def _build_texture_reference_indexes(
    entries: Sequence[ArchiveEntry],
) -> Tuple[
    Dict[str, ArchiveEntry],
    Dict[str, List[ArchiveEntry]],
    Dict[str, List[ArchiveEntry]],
    Dict[str, List[ArchiveEntry]],
]:
    by_path: Dict[str, ArchiveEntry] = {}
    by_basename: Dict[str, List[ArchiveEntry]] = defaultdict(list)
    by_tail2: Dict[str, List[ArchiveEntry]] = defaultdict(list)
    by_tail3: Dict[str, List[ArchiveEntry]] = defaultdict(list)
    for entry in entries:
        lowered = entry.path.replace("\\", "/").lower()
        if entry.extension not in TEXTURE_IMAGE_EXTENSIONS and "/texture/" not in lowered:
            continue
        by_path[lowered] = entry
        by_basename[PurePosixPath(lowered).name].append(entry)
        tail2 = _tail_path_key(lowered, 2)
        tail3 = _tail_path_key(lowered, 3)
        if tail2:
            by_tail2[tail2].append(entry)
        if tail3:
            by_tail3[tail3].append(entry)
    return by_path, by_basename, by_tail2, by_tail3


def _resolve_texture_reference_token(
    token: str,
    *,
    by_path: Dict[str, ArchiveEntry],
    by_basename: Dict[str, List[ArchiveEntry]],
    by_tail2: Dict[str, List[ArchiveEntry]],
    by_tail3: Dict[str, List[ArchiveEntry]],
) -> Tuple[List[ArchiveEntry], str]:
    normalized = _normalize_reference_token(token)
    if not normalized:
        return [], "unresolved"
    exact = by_path.get(normalized)
    if exact is not None:
        return [exact], "exact path"
    tail3 = _tail_path_key(normalized, 3)
    if tail3 and len(by_tail3.get(tail3, ())) == 1:
        return list(by_tail3[tail3]), "tail path"
    tail2 = _tail_path_key(normalized, 2)
    if tail2 and len(by_tail2.get(tail2, ())) == 1:
        return list(by_tail2[tail2]), "tail path"
    basename = PurePosixPath(normalized).name
    basename_matches = by_basename.get(basename, [])
    if len(basename_matches) == 1:
        return list(basename_matches), "unique basename"
    return [], "unresolved"


def _build_reference_snippet(text: str, token: str, *, radius: int = 80) -> str:
    lowered_text = text.lower()
    lowered_token = token.lower()
    index = lowered_text.find(lowered_token)
    if index < 0:
        compact = re.sub(r"\s+", " ", text.strip())
        return compact[: (radius * 2)] if compact else ""
    start = max(0, index - radius)
    end = min(len(text), index + len(token) + radius)
    snippet = re.sub(r"\s+", " ", text[start:end]).strip()
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


def _extract_reference_tag_text(text: str, token: str) -> str:
    escaped_token = re.escape(token)
    tag_match = re.search(rf"<[^>]*{escaped_token}[^>]*>", text, re.IGNORECASE)
    if tag_match:
        return tag_match.group(0)
    lowered_text = text.lower()
    lowered_token = token.lower()
    index = lowered_text.find(lowered_token)
    if index < 0:
        return ""
    line_start = text.rfind("\n", 0, index)
    line_end = text.find("\n", index)
    if line_start < 0:
        line_start = 0
    else:
        line_start += 1
    if line_end < 0:
        line_end = len(text)
    return text[line_start:line_end].strip()


def _parse_get_rect(value: str) -> Tuple[int, int, int, int]:
    match = _GET_RECT_PATTERN.match(value.strip())
    if match is None:
        return -1, -1, 0, 0
    return tuple(int(match.group(index)) for index in range(1, 5))  # type: ignore[return-value]


def _build_ui_constraint_warning(
    *,
    rect_width: int,
    rect_height: int,
    texture_width: int = 0,
    texture_height: int = 0,
) -> Tuple[str, str]:
    if rect_width <= 0 or rect_height <= 0:
        return "", ""
    if texture_width > 0 and texture_height > 0:
        if rect_width < texture_width or rect_height < texture_height:
            constraint_kind = "Explicit UI rect smaller than texture"
        elif rect_width == texture_width and rect_height == texture_height:
            constraint_kind = "Explicit UI rect matches texture"
        else:
            constraint_kind = "Explicit UI rect larger than texture"
    else:
        constraint_kind = "Explicit UI rect found"
    warning_text = (
        f"Referenced by UI XML with GetRect {rect_width}x{rect_height}. "
        "Upscaling the DDS alone may not change rendered size if the UI layout still uses the same rect."
    )
    return constraint_kind, warning_text


def _extract_ui_reference_metadata(
    source_path: str,
    text: str,
    token: str,
    *,
    texture_width: int = 0,
    texture_height: int = 0,
) -> Dict[str, object]:
    source_kind = PurePosixPath(source_path.replace("\\", "/")).suffix.lower().lstrip(".")
    result: Dict[str, object] = {
        "source_kind": source_kind,
        "texture_name": "",
        "filename_token": token,
        "get_rect_raw": "",
        "rect_x": -1,
        "rect_y": -1,
        "rect_width": 0,
        "rect_height": 0,
        "constraint_kind": "",
        "warning_text": "",
        "evidence_level": "",
    }
    if source_kind != "xml":
        return result
    tag_text = _extract_reference_tag_text(text, token)
    if not tag_text:
        return result
    attributes: Dict[str, str] = {}
    try:
        element = ET.fromstring(tag_text)
        attributes = {str(key): str(value) for key, value in element.attrib.items()}
    except Exception:
        attributes = {match.group(1): match.group(2) for match in _XML_ATTRIBUTE_PATTERN.finditer(tag_text)}
    normalized_attrs = {key.lower(): value for key, value in attributes.items()}
    texture_name = normalized_attrs.get("name", "")
    filename_value = normalized_attrs.get("filename", "")
    get_rect_raw = normalized_attrs.get("getrect", "")
    rect_x, rect_y, rect_width, rect_height = _parse_get_rect(get_rect_raw)
    constraint_kind, warning_text = _build_ui_constraint_warning(
        rect_width=rect_width,
        rect_height=rect_height,
        texture_width=texture_width,
        texture_height=texture_height,
    )
    evidence_level = "explicit_xml_rect" if get_rect_raw else ("explicit_xml_filename" if filename_value else "")
    result.update(
        {
            "texture_name": texture_name,
            "filename_token": filename_value or token,
            "get_rect_raw": get_rect_raw,
            "rect_x": rect_x,
            "rect_y": rect_y,
            "rect_width": rect_width,
            "rect_height": rect_height,
            "constraint_kind": constraint_kind,
            "warning_text": warning_text,
            "evidence_level": evidence_level,
        }
    )
    return result


def _archive_entry_texture_size(entry: ArchiveEntry) -> Tuple[int, int]:
    if entry.extension.lower() != ".dds":
        return 0, 0
    try:
        source_path, _note = ensure_archive_preview_source(entry)
        info = parse_dds(source_path)
    except Exception:
        return 0, 0
    return int(info.width), int(info.height)


def resolve_material_texture_references(
    entries: Sequence[ArchiveEntry],
    target_path: str,
    *,
    limit: int = 240,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[object] = None,
) -> Tuple[List[MaterialTextureReferenceRow], Dict[str, object]]:
    normalized_target = target_path.strip().replace("\\", "/").strip("/")
    if not normalized_target:
        return [], {"mode": "none", "searched_count": 0, "candidate_count": 0, "unreadable_count": 0}

    lowered_target = normalized_target.lower()
    all_entries_by_path = {entry.path.replace("\\", "/").lower(): entry for entry in entries}
    text_entries = [
        entry
        for entry in entries
        if entry.extension in REFERENCE_SOURCE_EXTENSIONS
    ]
    by_path, by_basename, by_tail2, by_tail3 = _build_texture_reference_indexes(entries)
    target_entry = all_entries_by_path.get(lowered_target)

    if target_entry is not None and target_entry.extension in REFERENCE_SOURCE_EXTENSIONS:
        rows: List[MaterialTextureReferenceRow] = []
        unreadable_count = 0
        seen_related: set[str] = set()
        if on_progress:
            on_progress(0, 1, f"Resolving outbound texture references from {target_entry.path}")
        try:
            data, _decompressed, _note = read_archive_entry_data(target_entry)
            text = _decode_reference_text(data)
        except Exception:
            unreadable_count = 1
            return [], {
                "mode": "outbound",
                "searched_count": 0,
                "candidate_count": 1,
                "unreadable_count": unreadable_count,
            }
        for token in _extract_texture_reference_tokens(text):
            resolved_entries, resolution_kind = _resolve_texture_reference_token(
                token,
                by_path=by_path,
                by_basename=by_basename,
                by_tail2=by_tail2,
                by_tail3=by_tail3,
            )
            for related_entry in resolved_entries:
                lowered_related = related_entry.path.replace("\\", "/").lower()
                if lowered_related in seen_related:
                    continue
                seen_related.add(lowered_related)
                texture_width, texture_height = _archive_entry_texture_size(related_entry)
                ui_meta = _extract_ui_reference_metadata(
                    target_entry.path,
                    text,
                    token,
                    texture_width=texture_width,
                    texture_height=texture_height,
                )
                rows.append(
                    MaterialTextureReferenceRow(
                        source_path=target_entry.path,
                        source_package_label=target_entry.package_label,
                        related_path=related_entry.path,
                        related_package_label=related_entry.package_label,
                        relation_kind=f"references texture ({resolution_kind})",
                        match_count=max(1, text.lower().count(token.lower())),
                        snippet=_build_reference_snippet(text, token),
                        source_kind=str(ui_meta.get("source_kind", "") or ""),
                        texture_name=str(ui_meta.get("texture_name", "") or ""),
                        filename_token=str(ui_meta.get("filename_token", "") or ""),
                        get_rect_raw=str(ui_meta.get("get_rect_raw", "") or ""),
                        rect_x=int(ui_meta.get("rect_x", -1) or -1),
                        rect_y=int(ui_meta.get("rect_y", -1) or -1),
                        rect_width=int(ui_meta.get("rect_width", 0) or 0),
                        rect_height=int(ui_meta.get("rect_height", 0) or 0),
                        texture_width=texture_width,
                        texture_height=texture_height,
                        constraint_kind=str(ui_meta.get("constraint_kind", "") or ""),
                        warning_text=str(ui_meta.get("warning_text", "") or ""),
                        evidence_level=str(ui_meta.get("evidence_level", "") or ""),
                    )
                )
                if len(rows) >= limit:
                    break
            if len(rows) >= limit:
                break
        rows.sort(key=lambda row: (row.related_path.lower(), row.relation_kind))
        return rows, {
            "mode": "outbound",
            "searched_count": 1,
            "candidate_count": 1,
            "unreadable_count": unreadable_count,
        }

    rows = []
    unreadable_count = 0
    target_basename = PurePosixPath(lowered_target).name
    total = len(text_entries)
    for index, entry in enumerate(text_entries, start=1):
        raise_if_cancelled(stop_event)
        if on_progress:
            on_progress(index - 1, total, f"Searching material/sidecar references in {entry.path}")
        try:
            data, _decompressed, _note = read_archive_entry_data(entry)
            text = _decode_reference_text(data)
        except Exception:
            unreadable_count += 1
            continue
        lowered_text = text.lower()
        if lowered_target not in lowered_text and target_basename and target_basename not in lowered_text:
            continue
        match_count = 0
        match_kind = ""
        snippet = ""
        for token in _extract_texture_reference_tokens(text):
            resolved_entries, resolution_kind = _resolve_texture_reference_token(
                token,
                by_path=by_path,
                by_basename=by_basename,
                by_tail2=by_tail2,
                by_tail3=by_tail3,
            )
            resolved_paths = {resolved.path.replace("\\", "/").lower() for resolved in resolved_entries}
            if lowered_target in resolved_paths:
                match_count += 1
                match_kind = resolution_kind
                if not snippet:
                    snippet = _build_reference_snippet(text, token)
            elif target_entry is None and PurePosixPath(token).name.lower() == target_basename:
                match_count += 1
                match_kind = "basename match"
                if not snippet:
                    snippet = _build_reference_snippet(text, token)
        if match_count <= 0:
            continue
        rows.append(
            MaterialTextureReferenceRow(
                source_path=entry.path,
                source_package_label=entry.package_label,
                related_path=normalized_target,
                related_package_label=target_entry.package_label if target_entry is not None else "",
                relation_kind=f"references selected texture ({match_kind or 'text match'})",
                match_count=match_count,
                snippet=snippet,
                texture_width=_archive_entry_texture_size(target_entry)[0] if target_entry is not None else 0,
                texture_height=_archive_entry_texture_size(target_entry)[1] if target_entry is not None else 0,
                **(
                    {
                        key: value
                        for key, value in _extract_ui_reference_metadata(
                            entry.path,
                            text,
                            target_entry.path if target_entry is not None else target_basename,
                            texture_width=_archive_entry_texture_size(target_entry)[0] if target_entry is not None else 0,
                            texture_height=_archive_entry_texture_size(target_entry)[1] if target_entry is not None else 0,
                        ).items()
                    }
                ),
            )
        )
        if len(rows) >= limit:
            break

    if on_progress:
        on_progress(total, total, f"Reference resolution complete. Found {len(rows):,} match(es).")
    rows.sort(key=lambda row: (-row.match_count, row.source_path.lower()))
    return rows, {
        "mode": "inbound",
        "searched_count": total - unreadable_count,
        "candidate_count": total,
        "unreadable_count": unreadable_count,
    }


def _reference_path_keys(path_value: str) -> set[str]:
    normalized = path_value.strip().replace("\\", "/").strip("/")
    if not normalized:
        return set()
    keys = {normalized.casefold()}
    parts = [part for part in PurePosixPath(normalized).parts if part]
    if len(parts) > 1 and len(parts[0]) == 4 and parts[0].isdigit():
        stripped = "/".join(parts[1:]).strip("/")
        if stripped:
            keys.add(stripped.casefold())
    return keys


def resolve_ui_reference_constraints(
    entries: Sequence[ArchiveEntry],
    target_path: str,
    *,
    limit: int = 240,
    stop_event: Optional[object] = None,
) -> List[MaterialTextureReferenceRow]:
    rows, _stats = resolve_material_texture_references(
        entries,
        target_path,
        limit=limit,
        stop_event=stop_event,
    )
    target_keys = _reference_path_keys(target_path)
    if not target_keys:
        return []
    filtered: List[MaterialTextureReferenceRow] = []
    for row in rows:
        if not isinstance(row, MaterialTextureReferenceRow):
            continue
        if not row.get_rect_raw:
            continue
        if not (_reference_path_keys(row.related_path) & target_keys):
            continue
        filtered.append(row)
    return filtered


def summarize_ui_reference_constraints(
    entries: Sequence[ArchiveEntry],
    target_path: str,
    *,
    stop_event: Optional[object] = None,
) -> Dict[str, object]:
    rows = resolve_ui_reference_constraints(entries, target_path, stop_event=stop_event)
    if not rows:
        return {"warning_text": "", "rows": [], "constraint_count": 0}
    first = rows[0]
    warning = first.warning_text or (
        f"Referenced by UI XML with GetRect {first.rect_width}x{first.rect_height}. "
        "Upscaling the DDS alone may not change rendered size if the UI layout still uses the same rect."
    )
    return {
        "warning_text": warning,
        "rows": rows,
        "constraint_count": len(rows),
        "source_paths": [row.source_path for row in rows],
    }


def build_ui_constraint_reference_rows(
    entries: Sequence[ArchiveEntry],
    *,
    limit: int = 2000,
    stop_event: Optional[object] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> List[MaterialTextureReferenceRow]:
    by_path, by_basename, by_tail2, by_tail3 = _build_texture_reference_indexes(entries)
    rows: List[MaterialTextureReferenceRow] = []
    seen_keys: set[tuple[str, str, str]] = set()
    reference_entries = [
        entry
        for entry in entries
        if isinstance(entry, ArchiveEntry) and entry.extension.lower() in REFERENCE_SOURCE_EXTENSIONS
    ]
    total_entries = len(reference_entries)
    for index, entry in enumerate(reference_entries, start=1):
        raise_if_cancelled(stop_event, "Research refresh cancelled.")
        if callable(on_progress):
            on_progress(index - 1, total_entries, f"Scanning UI rect references: {entry.path}")
        try:
            data, _decompressed, _note = read_archive_entry_data(entry)
        except Exception:
            continue
        text = _decode_reference_text(data)
        tokens = _extract_texture_reference_tokens(text)
        if not tokens:
            continue
        for token in tokens:
            raise_if_cancelled(stop_event, "Research refresh cancelled.")
            ui_meta = _extract_ui_reference_metadata(entry.path, text, token)
            if not ui_meta.get("get_rect_raw"):
                continue
            resolved_entries, resolution_kind = _resolve_texture_reference_token(
                token,
                by_path=by_path,
                by_basename=by_basename,
                by_tail2=by_tail2,
                by_tail3=by_tail3,
            )
            for related_entry in resolved_entries:
                if related_entry.extension.lower() != ".dds":
                    continue
                texture_width, texture_height = _archive_entry_texture_size(related_entry)
                refreshed_meta = _extract_ui_reference_metadata(
                    entry.path,
                    text,
                    token,
                    texture_width=texture_width,
                    texture_height=texture_height,
                )
                if not refreshed_meta.get("get_rect_raw"):
                    continue
                seen_key = (
                    entry.path.casefold(),
                    related_entry.path.casefold(),
                    str(refreshed_meta.get("get_rect_raw", "") or ""),
                )
                if seen_key in seen_keys:
                    continue
                seen_keys.add(seen_key)
                rows.append(
                    MaterialTextureReferenceRow(
                        source_path=entry.path,
                        source_package_label=entry.package_label,
                        related_path=related_entry.path,
                        related_package_label=related_entry.package_label,
                        relation_kind=f"references texture ({resolution_kind})",
                        match_count=max(1, text.lower().count(token.lower())),
                        snippet=_build_reference_snippet(text, token),
                        source_kind=str(refreshed_meta.get("source_kind", "") or ""),
                        texture_name=str(refreshed_meta.get("texture_name", "") or ""),
                        filename_token=str(refreshed_meta.get("filename_token", "") or ""),
                        get_rect_raw=str(refreshed_meta.get("get_rect_raw", "") or ""),
                        rect_x=int(refreshed_meta.get("rect_x", -1) or -1),
                        rect_y=int(refreshed_meta.get("rect_y", -1) or -1),
                        rect_width=int(refreshed_meta.get("rect_width", 0) or 0),
                        rect_height=int(refreshed_meta.get("rect_height", 0) or 0),
                        texture_width=texture_width,
                        texture_height=texture_height,
                        constraint_kind=str(refreshed_meta.get("constraint_kind", "") or ""),
                        warning_text=str(refreshed_meta.get("warning_text", "") or ""),
                        evidence_level=str(refreshed_meta.get("evidence_level", "") or ""),
                    )
                )
                if len(rows) >= limit:
                    if callable(on_progress):
                        on_progress(total_entries, total_entries, f"UI rect scan reached the current limit ({limit:,} rows).")
                    return rows
    if callable(on_progress):
        on_progress(total_entries, total_entries, f"Scanned {total_entries:,} XML/text reference file(s) for UI rect evidence.")
    rows.sort(key=lambda row: (row.related_path.casefold(), row.source_path.casefold()))
    return rows


def discover_archive_sidecars(
    entries: Sequence[ArchiveEntry],
    target_path: str,
    *,
    limit: int = 120,
    stop_event: Optional[object] = None,
) -> List[SidecarDiscoveryRow]:
    normalized_target = target_path.strip().replace("\\", "/").strip("/")
    if not normalized_target:
        return []
    lowered_target = normalized_target.lower()
    target_parts = _normalized_parts(lowered_target)
    target_parent = "/".join(target_parts[:-1])
    target_stem = PurePosixPath(lowered_target).stem.lower()
    target_group_key = derive_texture_group_key(lowered_target).lower()

    candidates: Dict[str, SidecarDiscoveryRow] = {}
    for entry in entries:
        raise_if_cancelled(stop_event)
        lowered_path = entry.path.replace("\\", "/").lower()
        if lowered_path == lowered_target:
            continue
        if entry.extension not in TEXTURE_IMAGE_EXTENSIONS and entry.extension not in TEXTURE_SIDECAR_EXTENSIONS:
            continue
        confidence = 0
        relation_kind = ""
        reason = ""
        entry_group_key = derive_texture_group_key(entry.path).lower()
        if entry_group_key == target_group_key:
            confidence = 96
            relation_kind = "same grouped set"
            reason = "Matches the same derived texture-set key."
        else:
            entry_parent = "/".join(_normalized_parts(lowered_path)[:-1])
            entry_stem = PurePosixPath(lowered_path).stem.lower()
            if entry_parent == target_parent and entry.extension in TEXTURE_SIDECAR_EXTENSIONS:
                if target_stem in entry_stem or entry_stem in target_stem:
                    confidence = 84
                    relation_kind = "same-folder sidecar"
                    reason = "Same folder with a matching or overlapping base stem."
            if confidence == 0 and entry_parent == target_parent and entry.extension in TEXTURE_IMAGE_EXTENSIONS:
                if target_stem in entry_stem or entry_stem in target_stem:
                    confidence = 74
                    relation_kind = "same-folder texture"
                    reason = "Nearby texture in the same folder with a similar base stem."
        if confidence <= 0:
            continue
        existing = candidates.get(lowered_path)
        if existing is not None and existing.confidence >= confidence:
            continue
        candidates[lowered_path] = SidecarDiscoveryRow(
            anchor_path=normalized_target,
            related_path=entry.path,
            package_label=entry.package_label,
            relation_kind=relation_kind,
            confidence=confidence,
            reason=reason,
        )

    rows = sorted(candidates.values(), key=lambda row: (-row.confidence, row.related_path.lower()))
    return rows[:limit]




























































from cdmw.core.research_texture_analysis import (
    AtlasDetectionRow,
    MipAnalysisRow,
    NormalValidationRow,
    TextureBudgetClassSummary,
    TextureBudgetGroupSummary,
    TextureBudgetProfileSummary,
    TextureBudgetRow,
    TexturePreviewStats,
    TextureUsageHeatRow,
    analyze_mip_behavior,
    build_mip_analysis_detail,
    build_mip_analysis_family_members_by_path,
    build_normal_validation_detail,
    build_processing_plan_lookup,
    build_texture_budget_analysis,
    build_texture_usage_heatmap,
    detect_texture_atlases,
    export_texture_analysis_report,
    validate_normal_maps,
)

def get_regex_presets() -> List[RegexPreset]:
    return [
        RegexPreset("Materials", "Material names", r"(?i)material(name|id)?\s*=\s*\"([^\"]+)\"", "Find material-name assignments in XML or material-like files."),
        RegexPreset("Materials", "Texture references", r"(?i)(texture|albedo|normal|roughness|mask)[^\\n=]*=\s*\"([^\"]+)\"", "Find texture-path assignments and texture parameters."),
        RegexPreset("Actors", "Actor IDs", r"(?i)(actor|npc|pawn)[^\\n=]*id\s*=\s*\"?([A-Za-z0-9_./:-]+)\"?", "Find actor or NPC identifiers.", path_hint="character"),
        RegexPreset("Actors", "Gameplay tags", r"(?i)(gameplaytag|tag)[^\\n=]*=\s*\"([^\"]+)\"", "Find gameplay-tag style assignments."),
        RegexPreset("Paths", "File paths", r"(?i)([A-Za-z0-9_./-]+\.(dds|png|xml|material|json|lua))", "Find referenced asset paths."),
        RegexPreset("Paths", "Package-like IDs", r"(?i)\b\d{4}/[A-Za-z0-9_./-]+\b", "Find archive-style package/path references."),
        RegexPreset("Sound", "Event names", r"(?i)(Wwise|Sound(Event|Bank)|RTPC|SwitchGroup|State)", "Find sound-system references.", extensions=".xml;.json"),
        RegexPreset("UI", "UI widget refs", r"(?i)(widget|hud|icon|layout|panel|button)[A-Za-z0-9_./:-]*", "Find likely UI/layout terms.", extensions=".xml;.json;.cfg", path_hint="ui"),
        RegexPreset("Gameplay", "Quest or objective refs", r"(?i)(quest|objective|mission|scenario)[A-Za-z0-9_./:-]*", "Find quest/objective-style names."),
        RegexPreset("Scripts", "Class or function refs", r"(?i)\b(class|function|script|handler)\b", "Find script/class-like declarations.", extensions=".lua;.json;.xml"),
    ]


def cluster_text_search_results(results: Sequence[object], mode: str) -> List[SearchCluster]:
    bucket_counts: Dict[str, int] = defaultdict(int)
    bucket_matches: Dict[str, int] = defaultdict(int)
    bucket_samples: Dict[str, List[str]] = defaultdict(list)

    for result in results:
        relative_path = str(getattr(result, "relative_path", "") or "")
        if not relative_path:
            continue
        if mode == "package":
            label = str(getattr(result, "package_label", "") or "Loose file")
        elif mode == "system":
            label = system_area_from_path(relative_path)
        else:
            label = PurePosixPath(relative_path).parent.as_posix() or "(root)"
        bucket_counts[label] += 1
        bucket_matches[label] += int(getattr(result, "match_count", 0) or 0)
        samples = bucket_samples[label]
        if len(samples) < 3:
            samples.append(relative_path)

    clusters = [
        SearchCluster(
            mode=mode,
            label=label,
            file_count=file_count,
            total_matches=bucket_matches[label],
            sample_paths=bucket_samples[label],
        )
        for label, file_count in bucket_counts.items()
    ]
    clusters.sort(key=lambda cluster: (-cluster.file_count, -cluster.total_matches, cluster.label))
    return clusters


def load_research_notes(notes_path: Path) -> Dict[str, ResearchNote]:
    if not notes_path.exists():
        return {}
    try:
        payload = json.loads(notes_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    notes: Dict[str, ResearchNote] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        note_text = str(value.get("note", "")).strip()
        tags = value.get("tags", [])
        if not note_text and not tags:
            continue
        notes[key] = ResearchNote(
            target_key=key,
            source_kind=str(value.get("source_kind", "unknown")),
            tags=[str(tag).strip() for tag in tags if str(tag).strip()],
            note=note_text,
            updated_at=str(value.get("updated_at", "")),
        )
    return notes


def save_research_notes(notes_path: Path, notes: Dict[str, ResearchNote]) -> None:
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        key: {
            "source_kind": note.source_kind,
            "tags": list(note.tags),
            "note": note.note,
            "updated_at": note.updated_at,
        }
        for key, note in sorted(notes.items(), key=lambda item: item[0].lower())
    }
    notes_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def upsert_research_note(
    notes: Dict[str, ResearchNote],
    *,
    target_key: str,
    source_kind: str,
    tags_text: str,
    note_text: str,
) -> Dict[str, ResearchNote]:
    normalized_key = target_key.strip().replace("\\", "/")
    if not normalized_key:
        raise ValueError("Choose a file/path before saving a note.")
    tags = [token.strip() for token in re.split(r"[,\s;|]+", tags_text) if token.strip()]
    normalized_note = note_text.strip()
    if not tags and not normalized_note:
        notes.pop(normalized_key, None)
        return notes
    notes[normalized_key] = ResearchNote(
        target_key=normalized_key,
        source_kind=source_kind.strip() or "unknown",
        tags=tags,
        note=normalized_note,
        updated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )
    return notes


def delete_research_note(notes: Dict[str, ResearchNote], target_key: str) -> Dict[str, ResearchNote]:
    normalized_key = target_key.strip().replace("\\", "/")
    if normalized_key:
        notes.pop(normalized_key, None)
    return notes
