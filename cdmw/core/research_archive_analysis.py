"""Archive-backed Research snapshot and texture grouping."""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from cdmw.core.archive_binary_preview import try_decode_text_like_archive_data
from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import archive_entry_role
from cdmw.core.common import raise_if_cancelled
from cdmw.core.upscale_profiles import (
    derive_texture_group_key as derive_semantic_texture_group_key,
    infer_texture_semantics,
    normalize_texture_reference_for_sidecar_lookup,
    parse_texture_sidecar_bindings,
)
from cdmw.domain.research.classification import _normalized_parts, _package_bucket_for_path, system_area_from_path
from cdmw.domain.research.contracts import (
    DependencyEdge,
    RESEARCH_TEXTURE_IMAGE_EXTENSIONS,
    RESEARCH_TEXTURE_SIDECAR_EXTENSIONS,
    TextureClassificationRow,
    TextureSetGroup,
    TextureSetMember,
    TextureUsageHeatRow,
)
from cdmw.models import ArchiveEntry

TEXTURE_IMAGE_EXTENSIONS = set(RESEARCH_TEXTURE_IMAGE_EXTENSIONS)
TEXTURE_SIDECAR_EXTENSIONS = set(RESEARCH_TEXTURE_SIDECAR_EXTENSIONS)


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


def _index_archive_research_entries(
    entries: Sequence[ArchiveEntry],
    *,
    stop_event: Optional[object] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> Tuple[
    Dict[str, List[str]],
    Dict[str, List[ArchiveEntry]],
    List[Tuple[ArchiveEntry, str, bool, bool, str, str]],
]:
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
    return family_members_by_group, grouped_entries, entry_metadata


def _classify_archive_research_entries(
    entry_metadata: Sequence[Tuple[ArchiveEntry, str, bool, bool, str, str]],
    family_members_by_group: Dict[str, List[str]],
    *,
    sidecar_texts_by_texture_path: Dict[str, Tuple[str, ...]],
    sidecar_texts_by_texture_basename: Dict[str, Tuple[str, ...]],
    stop_event: Optional[object] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> Tuple[List[TextureClassificationRow], Dict[str, str], Dict[Tuple[str, str], Dict[str, object]]]:
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
            sidecar_texts_by_texture_path=sidecar_texts_by_texture_path,
            sidecar_texts_by_texture_basename=sidecar_texts_by_texture_basename,
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
    return classification_rows, classified_kinds_by_path, heatmap_scopes


def _build_archive_texture_groups(
    grouped_entries: Dict[str, List[ArchiveEntry]],
    classified_kinds_by_path: Dict[str, str],
    *,
    stop_event: Optional[object] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> List[TextureSetGroup]:
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
    return texture_groups


def _build_archive_heatmap_rows(
    heatmap_scopes: Dict[Tuple[str, str], Dict[str, object]],
    *,
    limit_per_scope: int,
    stop_event: Optional[object] = None,
) -> List[TextureUsageHeatRow]:
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
        flattened_heatmap_rows.extend(scope_rows[:limit_per_scope])
    return flattened_heatmap_rows


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
    from cdmw.core.research_classification import _build_unknown_resolver_groups_from_grouped_entries

    family_members_by_group, grouped_entries, entry_metadata = _index_archive_research_entries(
        entries,
        stop_event=stop_event,
        on_progress=on_progress,
    )
    semantic_source_entries = list(sidecar_source_entries or entries)
    sidecar_path_index, sidecar_basename_index = _build_archive_sidecar_reference_index(
        semantic_source_entries,
        stop_event=stop_event,
        on_progress=on_progress,
        progress_label=(
            "Building archive research snapshot: indexing loaded archive sidecar texture bindings..."
            if sidecar_source_entries is not None
            else "Building archive research snapshot: indexing sidecar texture bindings..."
        ),
    )
    classification_rows, classified_kinds_by_path, heatmap_scopes = _classify_archive_research_entries(
        entry_metadata,
        family_members_by_group,
        sidecar_texts_by_texture_path=sidecar_path_index,
        sidecar_texts_by_texture_basename=sidecar_basename_index,
        stop_event=stop_event,
        on_progress=on_progress,
    )
    texture_groups = _build_archive_texture_groups(
        grouped_entries,
        classified_kinds_by_path,
        stop_event=stop_event,
        on_progress=on_progress,
    )
    flattened_heatmap_rows = _build_archive_heatmap_rows(
        heatmap_scopes,
        limit_per_scope=heatmap_limit_per_scope,
        stop_event=stop_event,
    )

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


__all__ = [
    "TEXTURE_IMAGE_EXTENSIONS",
    "TEXTURE_SIDECAR_EXTENSIONS",
    "build_archive_dependency_graph",
    "build_archive_research_snapshot",
    "classify_texture_entries",
    "classify_texture_path",
    "derive_texture_group_key",
]
