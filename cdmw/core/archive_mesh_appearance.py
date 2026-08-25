"""Read-only character appearance resolution for PAC preview and FBX export."""

from __future__ import annotations

import threading
from pathlib import PurePosixPath
from typing import Mapping, Optional, Sequence

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_relationships import build_archive_relationship_plan
from cdmw.core.common import RunCancelled, raise_if_cancelled
from cdmw.core.skeleton_resolver import resolve_skeleton_for_model
from cdmw.models import ArchiveEntry, ModelPreviewData
from cdmw.modding.mesh_parser import ParsedMesh, resolve_pac_bone_palette
from cdmw.modding.skeleton_parser import iter_pab_candidate_basenames, parse_pab
from cdmw.modding.skeleton_variation_parser import (
    apply_skeleton_variation_to_mesh,
    parse_pabc_skeleton_variation,
    parse_pamt_morph_target_set,
)


def _normalized_path(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/").casefold()


def _shared_prefix_length(left: str, right: str) -> int:
    count = 0
    for left_part, right_part in zip(PurePosixPath(_normalized_path(left)).parts, PurePosixPath(_normalized_path(right)).parts):
        if left_part != right_part:
            break
        count += 1
    return count


def _sorted_candidates(source_path: str, entries: Sequence[ArchiveEntry]) -> tuple[ArchiveEntry, ...]:
    deduped: dict[tuple[str, str, int, int], ArchiveEntry] = {}
    for entry in entries:
        key = (
            _normalized_path(entry.path),
            str(entry.pamt_path or "").casefold(),
            int(entry.paz_index or 0),
            int(entry.offset or 0),
        )
        deduped.setdefault(key, entry)
    return tuple(
        sorted(
            deduped.values(),
            key=lambda entry: (
                _shared_prefix_length(source_path, entry.path),
                -len(str(entry.path or "")),
                _normalized_path(entry.path),
            ),
            reverse=True,
        )
    )


def _related_appearance_entries(
    model_entry: ArchiveEntry,
    *,
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
    context_entries: Sequence[ArchiveEntry],
) -> tuple[ArchiveEntry, ...]:
    if context_entries:
        return _sorted_candidates(model_entry.path, context_entries)
    related: list[ArchiveEntry] = []
    relationship_plan = build_archive_relationship_plan(
        model_entry,
        (),
        path_index=path_index,
        basename_index=basename_index,
    )
    related.extend(
        edge.related_entry
        for edge in relationship_plan.edges
        if isinstance(getattr(edge, "related_entry", None), ArchiveEntry)
    )
    model_stem = PurePosixPath(str(model_entry.path or "").replace("\\", "/")).stem.casefold()
    descriptors: list[ArchiveEntry] = []
    for suffix in (".prefabdata_xml", ".prefabdata.xml"):
        descriptors.extend(tuple(basename_index.get(f"{model_stem}{suffix}", ()) or ()))
    for descriptor in _sorted_candidates(model_entry.path, descriptors):
        related.append(descriptor)
        descriptor_plan = build_archive_relationship_plan(
            descriptor,
            (),
            path_index=path_index,
            basename_index=basename_index,
        )
        related.extend(
            edge.related_entry
            for edge in descriptor_plan.edges
            if isinstance(getattr(edge, "related_entry", None), ArchiveEntry)
        )
    return _sorted_candidates(model_entry.path, related)


def _indexed_skeleton_for_variation(
    model_entry: ArchiveEntry,
    pac_data: bytes,
    pabc_data: bytes,
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
    read_payload,
) -> tuple[object, tuple[int, ...]] | None:
    """Resolve the small exact PAB candidate set without scanning every descriptor."""

    best: tuple[tuple[int, int, int], object, tuple[int, ...]] | None = None
    for priority, basename in enumerate(iter_pab_candidate_basenames(model_entry.path)):
        for entry in _sorted_candidates(model_entry.path, tuple(basename_index.get(basename.casefold(), ()) or ())):
            try:
                candidate = parse_pab(read_payload(entry), entry.path)
                variation = parse_pabc_skeleton_variation(pabc_data, skeleton=candidate)
                palette = tuple(resolve_pac_bone_palette(pac_data, candidate))
            except Exception:
                continue
            score = (variation.matched_record_count, len(palette), -priority)
            if palette and (best is None or score > best[0]):
                best = score, candidate, palette
    return (best[1], best[2]) if best is not None and best[0][0] > 0 else None


def apply_archive_mesh_appearance(
    model_entry: ArchiveEntry,
    parsed_mesh: ParsedMesh,
    pac_data: bytes,
    *,
    archive_entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]],
    archive_entries_by_basename: Mapping[str, Sequence[ArchiveEntry]],
    context_entries: Sequence[ArchiveEntry] = (),
    include_morph_targets: bool = False,
    skeleton: object | None = None,
    bone_palette: Sequence[int] | None = None,
    stop_event: Optional[threading.Event] = None,
) -> tuple[ParsedMesh, tuple[str, ...]]:
    """Return a presentation clone with its linked PABC/PAMT appearance."""

    if str(getattr(parsed_mesh, "format", "") or "").lower() != "pac":
        return parsed_mesh, ()
    raise_if_cancelled(stop_event)
    related = _related_appearance_entries(
        model_entry,
        path_index=archive_entries_by_normalized_path,
        basename_index=archive_entries_by_basename,
        context_entries=context_entries,
    )
    pabc_candidates = tuple(entry for entry in related if str(entry.extension or "").lower() == ".pabc")
    if not pabc_candidates:
        return parsed_mesh, ()
    pabc_entry = pabc_candidates[0]

    def read_payload(entry: ArchiveEntry) -> bytes:
        raise_if_cancelled(stop_event)
        payload, _decompressed, _note = read_archive_entry_data(entry, stop_event=stop_event)
        return payload

    pabc_data = read_payload(pabc_entry)
    resolved_skeleton = skeleton
    palette = tuple(int(value) for value in (bone_palette or ()))
    if resolved_skeleton is None:
        indexed = _indexed_skeleton_for_variation(
            model_entry, pac_data, pabc_data, archive_entries_by_basename, read_payload
        )
        if indexed is not None:
            resolved_skeleton, palette = indexed
        else:
            skeleton_entry, report = resolve_skeleton_for_model(
                model_entry,
                (),
                archive_entries_by_normalized_path=archive_entries_by_normalized_path,
                archive_entries_by_basename=archive_entries_by_basename,
                pac_data=pac_data,
                read_entry_data=read_payload,
            )
            if skeleton_entry is None:
                detail = report.blocking_errors[0] if report.blocking_errors else "matching PAB skeleton was not resolved"
                raise ValueError(detail)
            resolved_skeleton = parse_pab(read_payload(skeleton_entry), skeleton_entry.path)
    if not palette:
        palette = tuple(resolve_pac_bone_palette(pac_data, resolved_skeleton))
    if not palette:
        raise ValueError("PAC bone palette was not resolved against the character skeleton")

    variation = parse_pabc_skeleton_variation(pabc_data, pabc_entry.path, skeleton=resolved_skeleton)
    pamt_entry = None
    morph_target_set = None
    if include_morph_targets:
        pamt_entry = next((entry for entry in related if str(entry.extension or "").lower() == ".pamt"), None)
        if pamt_entry is not None:
            morph_target_set = parse_pamt_morph_target_set(read_payload(pamt_entry), pamt_entry.path)
    deformed = apply_skeleton_variation_to_mesh(
        parsed_mesh,
        resolved_skeleton,
        palette,
        variation,
        morph_target_set=morph_target_set,
    )
    notes = [
        f"Applied character skeleton variation {pabc_entry.path} "
        f"({variation.matched_record_count:,}/{variation.record_count:,} records matched the PAB)."
    ]
    if morph_target_set is not None and pamt_entry is not None:
        notes.append(
            f"Recovered {max(0, morph_target_set.target_count - 1):,} facial shape target(s) from {pamt_entry.path}."
        )
    return deformed, tuple(notes)


def apply_archive_mesh_appearance_for_preview(
    model_entry: ArchiveEntry,
    parsed_mesh: ParsedMesh,
    pac_data: bytes,
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
    context_entries: Sequence[ArchiveEntry],
    stop_event: Optional[threading.Event],
) -> tuple[ParsedMesh, tuple[str, ...]]:
    """Preview-safe wrapper that reports a fallback instead of hiding the mesh."""

    try:
        return apply_archive_mesh_appearance(
            model_entry,
            parsed_mesh,
            pac_data,
            archive_entries_by_normalized_path=path_index,
            archive_entries_by_basename=basename_index,
            context_entries=context_entries,
            stop_event=stop_event,
        )
    except RunCancelled:
        raise
    except Exception as exc:
        return parsed_mesh, (f"Character appearance deformation was not applied for {model_entry.path}: {exc}",)


def apply_archive_mesh_appearance_to_preview_model(
    entry: ArchiveEntry,
    data: bytes,
    model_preview: ModelPreviewData,
    parsed_mesh: ParsedMesh,
    *,
    path_index: Optional[Mapping[str, Sequence[ArchiveEntry]]],
    basename_index: Optional[Mapping[str, Sequence[ArchiveEntry]]],
    stop_event: Optional[threading.Event],
) -> tuple[ModelPreviewData, ParsedMesh, tuple[str, ...]]:
    """Apply appearance when archive indexes are available, preserving fallback."""

    if path_index is None or basename_index is None:
        return model_preview, parsed_mesh, ()
    appearance_mesh, notes = apply_archive_mesh_appearance_for_preview(
        entry,
        parsed_mesh,
        data,
        path_index,
        basename_index,
        (),
        stop_event,
    )
    if appearance_mesh is parsed_mesh:
        return model_preview, parsed_mesh, notes
    from cdmw.core.archive_mesh_import_scene_preview import parsed_mesh_to_preview_model

    return parsed_mesh_to_preview_model(appearance_mesh), appearance_mesh, notes


__all__ = [
    "apply_archive_mesh_appearance",
    "apply_archive_mesh_appearance_for_preview",
    "apply_archive_mesh_appearance_to_preview_model",
]
