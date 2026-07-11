"""Cancellable worker preflight for static-replacement prompt construction."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from cdmw.services.archive_workflow_service import _collect_same_stem_related_target_basenames
from cdmw.services.archive_query_service import (
    extract_archive_model_sidecar_texture_references as _extract_archive_model_sidecar_texture_references,
    build_archive_relationship_references,
)
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.services.preview_workflow_service import (
    attach_scene_preview_textures,
    parsed_mesh_to_preview_model,
)
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.mesh_workflow_service import read_archive_entry_baseline_data
from cdmw.services.preview_workflow_service import scene_import_normalizes_texture_v
from cdmw.models import ArchiveEntry, ModelPreviewData, RunCancelled
from cdmw.services.mesh_workflow_service import ReplacementAssetProfile, analyze_replacement_asset
from cdmw.services.mesh_workflow_service import ReplacementTextureSet, group_replacement_texture_sets
from cdmw.services.mesh_workflow_service import ParsedMesh, parse_mesh
from cdmw.services.mesh_workflow_service import (
    SCENE_TEXTURE_SOURCE_EXTENSIONS,
    SceneImportResult,
    discover_scene_texture_files,
    import_scene_mesh_with_report,
)
from cdmw.services.mesh_workflow_service import StaticSubmeshMapping, suggest_static_submesh_mappings
from cdmw.services.diagnostics_service import is_expected_cancellation_message
from cdmw.ui.archive_browser.static_replacement_dialog_prompt_setup_helpers import (
    apply_static_replacement_work_area_fit,
    static_replacement_prompt_mesh_bounds,
)
from cdmw.ui.archive_browser.static_replacement_geometry_math import (
    Bounds3,
    WorkAreaPlacementFit,
    external_import_work_area_fit_from_bounds,
)
from cdmw.ui.archive_browser.static_replacement_sparse_history import (
    clone_mesh_for_static_replacement_native_first,
)
from cdmw.ui.archive_browser.static_replacement_texture_sources import (
    archive_texture_lookup_indexes_for_alignment,
    register_texture_source_files,
)


ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class StaticReplacementPromptPreflightRequest:
    request_id: int
    entry: ArchiveEntry
    obj_path: Path
    supplemental_files: tuple[Path, ...]
    scene_import_result: SceneImportResult | None
    original_mesh: ParsedMesh | None
    archive_entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]]
    archive_entries_by_basename: Mapping[str, Sequence[ArchiveEntry]]
    archive_entries_by_extension: Mapping[str, Sequence[ArchiveEntry]]


@dataclass(frozen=True, slots=True)
class StaticReplacementPromptPreflightResult:
    request_id: int
    scene_import_result: SceneImportResult
    original_mesh: ParsedMesh
    replacement_mesh_base: ParsedMesh
    replacement_mesh: ParsedMesh
    original_preview_model: ModelPreviewData
    replacement_preview_model: ModelPreviewData
    asset_profile: ReplacementAssetProfile
    suggested_mappings: tuple[StaticSubmeshMapping, ...]
    texture_files: tuple[Path, ...]
    auto_texture_sources: tuple[Path, ...]
    texture_sets: Mapping[str, ReplacementTextureSet]
    texture_entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]]
    texture_entries_by_basename: Mapping[str, Sequence[ArchiveEntry]]
    sidecar_bindings: tuple[object, ...]
    sidecar_text_values: tuple[str, ...]
    sidecar_texts_by_normalized_path: Mapping[str, tuple[str, ...]]
    sidecar_texts_by_basename: Mapping[str, tuple[str, ...]]
    modify_original_clone_mode: bool
    scene_flip_v: bool
    placement_fit: WorkAreaPlacementFit | None
    source_bounds: Bounds3 | None
    reference_bounds: Bounds3 | None
    texture_lookup_source: str
    texture_lookup_dds_count: int
    texture_lookup_sidecar_count: int
    texture_lookup_reference_count: int
    sidecar_lookup_error: str = ""
    routing_error: str = ""
    routing_elapsed_ms: int = 0


@dataclass(frozen=True, slots=True)
class _PreparedMeshes:
    scene_result: SceneImportResult
    replacement_base: ParsedMesh
    replacement_mesh: ParsedMesh
    source_bounds: Bounds3 | None
    reference_bounds: Bounds3 | None
    placement_fit: WorkAreaPlacementFit | None
    original_preview: ModelPreviewData
    replacement_preview: ModelPreviewData
    had_scene_result: bool
    scene_flip_v: bool


def _modify_original_clone_mode(obj_path: Path, entry: ArchiveEntry) -> bool:
    if obj_path.suffix.lower() != ".obj":
        return False
    metadata_path = Path(f"{obj_path}.meta.json")
    if not metadata_path.is_file():
        return False
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    payload_format = str(payload.get("format", "") or "").strip()
    source_path = str(payload.get("source_path", "") or "").replace("\\", "/").strip().strip("/")
    entry_path = str(entry.path or "").replace("\\", "/").strip().strip("/")
    return bool(
        payload_format in {"", "obj_meta_v1", "mesh_roundtrip_manifest_v2"}
        and source_path
        and entry_path
        and source_path.casefold() == entry_path.casefold()
    )


def _texture_lookup_indexes(
    request: StaticReplacementPromptPreflightRequest,
    stop_event: threading.Event,
) -> tuple[
    Mapping[str, Sequence[ArchiveEntry]],
    Mapping[str, Sequence[ArchiveEntry]],
    str,
    int,
    int,
    int,
]:
    if request.archive_entries_by_normalized_path and request.archive_entries_by_basename:
        return (
            request.archive_entries_by_normalized_path,
            request.archive_entries_by_basename,
            "global_indexes",
            len(tuple(request.archive_entries_by_extension.get(".dds", ()) or ())),
            0,
            0,
        )
    raise_if_cancelled(stop_event, "Static replacement preflight stopped by user.")
    references = build_archive_relationship_references(
        request.entry,
        archive_entries_by_normalized_path=request.archive_entries_by_normalized_path,
        archive_entries_by_basename=request.archive_entries_by_basename,
    )
    related_basenames = _collect_same_stem_related_target_basenames(request.entry)
    indexes = archive_texture_lookup_indexes_for_alignment(
        target_entry=request.entry,
        graph_references=references,
        related_target_basenames=tuple(related_basenames),
        extension_index=request.archive_entries_by_extension,
    )
    raise_if_cancelled(stop_event, "Static replacement preflight stopped by user.")
    return (
        indexes.path_index,
        indexes.basename_index,
        "local_dds_extension",
        indexes.dds_count,
        indexes.sidecar_count,
        indexes.graph_reference_count,
    )


def _sidecar_context(
    request: StaticReplacementPromptPreflightRequest,
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
    stop_event: threading.Event,
) -> tuple[
    tuple[object, ...],
    tuple[str, ...],
    Mapping[str, tuple[str, ...]],
    Mapping[str, tuple[str, ...]],
    str,
]:
    try:
        bindings, _paths, by_path, by_basename = _extract_archive_model_sidecar_texture_references(
            request.entry,
            archive_entries_by_basename=basename_index,
            stop_event=stop_event,
        )
        texts: list[str] = []
        seen: set[str] = set()
        for values in by_path.values():
            for value in values:
                raise_if_cancelled(stop_event, "Static replacement preflight stopped by user.")
                text = str(value or "")
                if text.strip() and text not in seen:
                    seen.add(text)
                    texts.append(text)
        return tuple(bindings), tuple(texts), by_path, by_basename, ""
    except RunCancelled:
        raise
    except Exception as exc:
        return (), (), {}, {}, str(exc)


def _prepare_meshes(
    request: StaticReplacementPromptPreflightRequest,
    original_mesh: ParsedMesh,
    modify_original_clone_mode: bool,
    report: ProgressCallback,
    stop: threading.Event,
) -> _PreparedMeshes:
    report(3, 8, "Preparing replacement mesh copies...")
    had_scene_result = request.scene_import_result is not None
    scene_result = request.scene_import_result or import_scene_mesh_with_report(request.obj_path, stop_event=stop)
    replacement_base = clone_mesh_for_static_replacement_native_first(
        scene_result.mesh,
        "prompt_setup.replacement_base_clone",
        "Python replacement setup base clone fallback blocked while native mesh core is available",
        allow_python_setup_fallback=True,
    )
    raise_if_cancelled(stop, "Static replacement preflight stopped by user.")
    if not isinstance(replacement_base, ParsedMesh):
        raise RuntimeError("Native replacement setup base clone failed.")
    replacement_mesh = clone_mesh_for_static_replacement_native_first(
        replacement_base,
        "prompt_setup.replacement_working_clone",
        "Python replacement setup working clone fallback blocked while native mesh core is available",
        allow_python_setup_fallback=True,
    )
    raise_if_cancelled(stop, "Static replacement preflight stopped by user.")
    if not isinstance(replacement_mesh, ParsedMesh):
        raise RuntimeError("Native replacement setup working clone failed.")

    report(4, 8, "Computing work-area bounds...")
    source_bounds = static_replacement_prompt_mesh_bounds(replacement_base, stop_event=stop)
    reference_bounds = static_replacement_prompt_mesh_bounds(original_mesh, stop_event=stop)
    placement_fit = (
        external_import_work_area_fit_from_bounds(source_bounds, reference_bounds, up_axis=1, ground_plane=0.0)
        if had_scene_result and not modify_original_clone_mode and source_bounds is not None
        else None
    )
    if placement_fit is not None:
        apply_static_replacement_work_area_fit(replacement_base, placement_fit, stop_event=stop)
        apply_static_replacement_work_area_fit(replacement_mesh, placement_fit, stop_event=stop)
    raise_if_cancelled(stop, "Static replacement preflight stopped by user.")

    report(5, 8, "Building preview models...")
    original_preview = parsed_mesh_to_preview_model(original_mesh)
    replacement_preview = parsed_mesh_to_preview_model(replacement_mesh)
    if had_scene_result:
        try:
            attach_scene_preview_textures(replacement_preview, scene_result, request.obj_path)
        except Exception:
            pass
    source_format = str(replacement_base.format or "").strip().lower()
    scene_flip_v = bool(
        had_scene_result
        and scene_import_normalizes_texture_v(source_format, replacement_base.path or request.obj_path)
    )
    raise_if_cancelled(stop, "Static replacement preflight stopped by user.")
    return _PreparedMeshes(
        scene_result,
        replacement_base,
        replacement_mesh,
        source_bounds,
        reference_bounds,
        placement_fit,
        original_preview,
        replacement_preview,
        had_scene_result,
        scene_flip_v,
    )


def prepare_static_replacement_prompt_preflight(
    request: StaticReplacementPromptPreflightRequest,
    *,
    progress: ProgressCallback | None = None,
    stop_event: threading.Event | None = None,
) -> StaticReplacementPromptPreflightResult:
    stop = stop_event or threading.Event()
    report = progress or (lambda _current, _total, _detail: None)
    raise_if_cancelled(stop, "Static replacement preflight stopped by user.")
    report(0, 8, "Resolving mesh and texture indexes...")
    modify_original_clone_mode = _modify_original_clone_mode(request.obj_path, request.entry)
    path_index, basename_index, lookup_source, dds_count, sidecar_count, reference_count = (
        _texture_lookup_indexes(request, stop)
    )

    report(1, 8, "Reading original mesh and material sidecars...")
    original_mesh = request.original_mesh
    if original_mesh is None:
        baseline = read_archive_entry_baseline_data(
            request.entry,
            read_entry_data=lambda entry: read_archive_entry_data(entry, stop_event=stop),
        )
        raise_if_cancelled(stop, "Static replacement preflight stopped by user.")
        original_mesh = parse_mesh(baseline.data, request.entry.path)
    bindings, sidecar_texts, sidecar_by_path, sidecar_by_basename, sidecar_error = _sidecar_context(
        request,
        basename_index,
        stop,
    )

    report(2, 8, "Analyzing replacement compatibility...")
    asset_profile = analyze_replacement_asset(
        request.entry,
        archive_entries_by_basename=basename_index,
        parsed_mesh=original_mesh,
        sidecar_texture_bindings=bindings,
        sidecar_texts=sidecar_texts,
    )
    raise_if_cancelled(stop, "Static replacement preflight stopped by user.")

    prepared = _prepare_meshes(request, original_mesh, modify_original_clone_mode, report, stop)
    scene_result = prepared.scene_result
    replacement_base = prepared.replacement_base
    replacement_mesh = prepared.replacement_mesh
    source_bounds = prepared.source_bounds
    reference_bounds = prepared.reference_bounds
    placement_fit = prepared.placement_fit
    original_preview = prepared.original_preview
    replacement_preview = prepared.replacement_preview
    had_scene_result = prepared.had_scene_result
    scene_flip_v = prepared.scene_flip_v

    report(6, 8, "Suggesting draw-section routing...")
    routing_started = time.perf_counter()
    routing_error = ""
    try:
        suggested_mappings = suggest_static_submesh_mappings(original_mesh, replacement_mesh)
    except Exception as exc:
        suggested_mappings = []
        routing_error = str(exc)
    routing_elapsed_ms = int((time.perf_counter() - routing_started) * 1000)
    if modify_original_clone_mode and len(original_mesh.submeshes) == len(replacement_mesh.submeshes):
        suggested_mappings = [
            StaticSubmeshMapping(
                target_submesh_index=index,
                target_submesh_name=(
                    original_mesh.submeshes[index].material
                    or original_mesh.submeshes[index].name
                    or f"target {index}"
                ),
                source_submesh_indices=[index],
                target_material_slot_index=index,
                merge_sources=False,
                confidence_score=1.0,
                confidence_label="exact-original-clone",
            )
            for index in range(len(original_mesh.submeshes))
        ]
    raise_if_cancelled(stop, "Static replacement preflight stopped by user.")

    report(7, 8, "Discovering replacement texture sources...")
    auto_texture_sources: list[Path] = []
    if had_scene_result:
        auto_texture_sources.extend(
            path
            for path in (
                tuple(scene_result.discovered_texture_files or ())
                + tuple(scene_result.extracted_embedded_files or ())
                + tuple(getattr(scene_result, "discovered_supplemental_files", ()) or ())
            )
            if isinstance(path, Path)
        )
    try:
        auto_texture_sources.extend(discover_scene_texture_files(request.obj_path, replacement_mesh))
    except Exception:
        pass
    texture_files: list[Path] = []
    seen_texture_files: set[str] = set()
    register_texture_source_files(
        request.supplemental_files + tuple(auto_texture_sources),
        texture_files_for_mapping=texture_files,
        seen_texture_file_keys=seen_texture_files,
        allowed_extensions=SCENE_TEXTURE_SOURCE_EXTENSIONS,
    )
    raise_if_cancelled(stop, "Static replacement preflight stopped by user.")
    texture_sets = group_replacement_texture_sets(texture_files, obj_mesh=replacement_mesh)
    report(8, 8, "Static replacement setup ready.")
    return StaticReplacementPromptPreflightResult(
        request_id=request.request_id,
        scene_import_result=scene_result,
        original_mesh=original_mesh,
        replacement_mesh_base=replacement_base,
        replacement_mesh=replacement_mesh,
        original_preview_model=original_preview,
        replacement_preview_model=replacement_preview,
        asset_profile=asset_profile,
        suggested_mappings=tuple(suggested_mappings),
        texture_files=tuple(texture_files),
        auto_texture_sources=tuple(auto_texture_sources),
        texture_sets=texture_sets,
        texture_entries_by_normalized_path=path_index,
        texture_entries_by_basename=basename_index,
        sidecar_bindings=bindings,
        sidecar_text_values=sidecar_texts,
        sidecar_texts_by_normalized_path=sidecar_by_path,
        sidecar_texts_by_basename=sidecar_by_basename,
        modify_original_clone_mode=modify_original_clone_mode,
        scene_flip_v=scene_flip_v,
        placement_fit=placement_fit,
        source_bounds=source_bounds,
        reference_bounds=reference_bounds,
        texture_lookup_source=lookup_source,
        texture_lookup_dds_count=dds_count,
        texture_lookup_sidecar_count=sidecar_count,
        texture_lookup_reference_count=reference_count,
        sidecar_lookup_error=sidecar_error,
        routing_error=routing_error,
        routing_elapsed_ms=routing_elapsed_ms,
    )


def dispatch_static_replacement_prompt_preflight(
    owner: object,
    entry: ArchiveEntry,
    obj_path: Path,
    *,
    supplemental_files: Sequence[Path],
    scene_import_result: SceneImportResult | None,
    original_mesh: ParsedMesh | None,
    on_complete: Callable[[StaticReplacementPromptPreflightResult], None],
) -> int:
    request_id = int(getattr(owner, "_static_replacement_prompt_preflight_request_id", 0) or 0) + 1
    setattr(owner, "_static_replacement_prompt_preflight_request_id", request_id)
    request = StaticReplacementPromptPreflightRequest(
        request_id=request_id,
        entry=entry,
        obj_path=Path(obj_path),
        supplemental_files=tuple(Path(path) for path in supplemental_files),
        scene_import_result=scene_import_result,
        original_mesh=original_mesh,
        archive_entries_by_normalized_path=getattr(owner, "archive_entries_by_normalized_path", {}) or {},
        archive_entries_by_basename=getattr(owner, "archive_entries_by_basename", {}) or {},
        archive_entries_by_extension=getattr(owner, "archive_entries_by_extension", {}) or {},
    )

    def task(
        _log: Callable[[str], None],
        progress: ProgressCallback,
        stop_event: threading.Event,
    ) -> StaticReplacementPromptPreflightResult:
        return prepare_static_replacement_prompt_preflight(request, progress=progress, stop_event=stop_event)

    def ready(payload: object) -> None:
        if (
            not isinstance(payload, StaticReplacementPromptPreflightResult)
            or payload.request_id != int(getattr(owner, "_static_replacement_prompt_preflight_request_id", 0) or 0)
            or bool(getattr(owner, "_shutting_down", False))
        ):
            return
        on_complete(payload)

    def failed(message: str) -> None:
        if (
            request_id != int(getattr(owner, "_static_replacement_prompt_preflight_request_id", 0) or 0)
            or bool(getattr(owner, "_shutting_down", False))
            or is_expected_cancellation_message(message)
            or "cancel" in str(message).casefold()
        ):
            return
        getattr(owner, "set_status_message")(
            f"Mesh Replacement Builder setup failed: {message}",
            error=True,
        )

    getattr(owner, "_run_utility_task_when_idle")(
        status_message="Preparing Mesh Replacement Builder...",
        task=task,
        on_complete=ready,
        on_error=failed,
        show_archive_progress=True,
        task_accepts_progress=True,
        task_accepts_cancel=True,
    )
    return request_id


__all__ = [
    "StaticReplacementPromptPreflightRequest",
    "StaticReplacementPromptPreflightResult",
    "dispatch_static_replacement_prompt_preflight",
    "prepare_static_replacement_prompt_preflight",
]
