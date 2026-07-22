"""UI-free manifest preparation for material-sidecar live previews."""

from __future__ import annotations

import copy
import dataclasses
import json
import shutil
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Optional, Sequence, Tuple

from cdmw.core.atomic_file import atomic_write_text
from cdmw.core.archive import (
    _attach_model_sidecar_texture_preview_paths,
    _parse_archive_model_sidecar_texture_bindings,
    build_archive_preview_result,
)
from cdmw.core.common import read_text_file_cancellable
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.core.material_sidecar_editor import discover_material_sidecar_preview_overrides_for_edits
from cdmw.core.upscale_profiles import normalize_texture_reference_for_sidecar_lookup
from cdmw.models import ArchiveEntry
from cdmw.models import (
    ArchivePreviewResult,
    ModelPreviewData,
    ModelPreviewRenderSettings,
)
from cdmw.rendering.native_preview_package_cache import create_native_preview_package_staging_dir
from cdmw.services.mesh_dotnet_preview_package import (
    build_or_lookup_dotnet_preview_package_from_model,
)


@dataclass(frozen=True, slots=True)
class MaterialSidecarPreviewBuildRequest:
    generation: int
    preview_model_entry: ArchiveEntry
    sidecar_entry: ArchiveEntry
    companion_entry: Optional[ArchiveEntry]
    preview_sidecar_text: str
    material_preview_edits: Mapping[str, str]
    include_texture_edits: bool
    live: bool
    material_effects_active: bool
    color_edits_active: bool
    include_skeleton_overlay: bool
    preview_settings: ModelPreviewRenderSettings
    base_cache_key: str
    reusable_package_dir: Optional[Path]
    fast_source_package_dir: Optional[Path]
    current_archive_result: Optional[ArchivePreviewResult]
    cached_base_result: Optional[ArchivePreviewResult]
    cache_root: Path
    texture_entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]]
    texture_entries_by_basename: Mapping[str, Sequence[ArchiveEntry]]
    sidecar_entries_by_texture_path: Mapping[str, Sequence[ArchiveEntry]]
    sidecar_entries_by_texture_basename: Mapping[str, Sequence[ArchiveEntry]]
    clone_preview_model: Callable[..., object]
    apply_preview_overrides: Callable[..., Sequence[str]]
    texture_resolution_warnings: Callable[..., Sequence[str]]
    label_normalizer: Callable[[object], str]
    cached_geometry_log: str
    cached_geometry_note: str
    building_model_log: str
    prepare_failed_message: str


@dataclass(frozen=True, slots=True)
class MaterialSidecarPreviewBuildResult:
    kind: str
    generation: int
    package_dir: Optional[Path]
    base_result_for_cache: Optional[ArchivePreviewResult]
    base_cache_key: str
    notes: Tuple[str, ...]
    warnings: Tuple[str, ...]
    live: bool
    material_effects_active: bool
    color_edits_active: bool
    elapsed_ms: float
    batch_count: int
    vertex_count: int


def _entry_key(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().casefold()


def material_preview_package_matches_entry(
    package_dir: object,
    model_entry: ArchiveEntry,
    *,
    stop_event: Optional[threading.Event] = None,
) -> bool:
    try:
        manifest = json.loads(
            read_text_file_cancellable(
                Path(package_dir) / "net_materials.json",
                stop_event=stop_event,
                max_bytes=64 * 1024 * 1024,
            )
        )
    except Exception:
        raise_if_cancelled(stop_event, "Material preview package validation cancelled.")
        return False
    return isinstance(manifest, Mapping) and _entry_key(manifest.get("source_mesh", "")) == _entry_key(
        model_entry.path
    )


def _source_package_path(source_package_dir: Path, raw_value: object) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return ""
    try:
        path = Path(text)
        return str(source_package_dir / path) if not path.is_absolute() else str(path)
    except (OSError, ValueError):
        return text


def fast_material_preview_package_from_manifest(
    source_package_dir: Path,
    *,
    cache_root: Path,
    label_normalizer: Callable[[object], str],
    preview_sidecar_text: str,
    edited_values: Mapping[str, str],
    color_edits_active: bool,
    include_skeleton_overlay: bool = True,
    stop_event: Optional[threading.Event] = None,
) -> Optional[Tuple[Path, int, int, Tuple[str, ...]]]:
    try:
        source_manifest = json.loads(
            read_text_file_cancellable(
                source_package_dir / "manifest.json",
                stop_event=stop_event,
                max_bytes=64 * 1024 * 1024,
            )
        )
    except Exception:
        raise_if_cancelled(stop_event, "Material live preview cancelled.")
        return None
    if not isinstance(source_manifest, Mapping):
        return None
    overrides = discover_material_sidecar_preview_overrides_for_edits(preview_sidecar_text, edited_values)
    if not overrides and include_skeleton_overlay:
        return None
    manifest = copy.deepcopy(dict(source_manifest))
    batches = manifest.get("batches")
    if not isinstance(batches, list):
        return None
    package_dir = create_native_preview_package_staging_dir(cache_root)

    def check_cancelled() -> None:
        if stop_event is not None and stop_event.is_set():
            shutil.rmtree(package_dir, ignore_errors=True)
            raise_if_cancelled(stop_event, "Material live preview cancelled.")

    manifest["created_at"] = time.time()
    manifest["use_textures"] = not color_edits_active
    if color_edits_active:
        manifest["high_quality_textures"] = False
    if manifest.get("cloth_collider_file"):
        manifest["cloth_collider_file"] = _source_package_path(
            source_package_dir,
            manifest.get("cloth_collider_file"),
        )
    if not include_skeleton_overlay:
        skeleton_overlay = dict(manifest.get("skeleton_overlay", {})) if isinstance(
            manifest.get("skeleton_overlay"), Mapping
        ) else {}
        skeleton_overlay.update(
            enabled=False,
            status="disabled",
            bone_count=0,
            pose_enabled=False,
            selected_bone_index=-1,
            posed_bone_count=0,
            pose_rotations=[],
            bones=[],
            diagnostics=["disabled in the material sidecar editor"],
        )
        manifest["skeleton_overlay"] = skeleton_overlay

    def labels(batch: Mapping[str, object]) -> set[str]:
        result = {
            label_normalizer(batch.get("material_name", "")),
            label_normalizer(batch.get("texture_name", "")),
        }
        result.discard("")
        return result

    def apply_override(batch: dict[str, object], override: object) -> bool:
        changed = False
        tint = tuple(getattr(override, "tint_color", ()) or ())
        if len(tint) >= 3:
            color = [max(0.0, min(1.0, float(tint[index]))) for index in range(3)]
            batch.update(
                base_color=color,
                texture_tint=color,
                base_tint_strength=0.0 if color_edits_active else 0.85,
            )
            changed = True
        brightness = max(0.1, min(3.0, float(getattr(override, "brightness", 1.0) or 1.0)))
        if abs(brightness - 1.0) > 1e-6:
            batch["texture_brightness"] = brightness
            changed = True
        uv_scale = max(0.05, min(64.0, float(getattr(override, "uv_scale", 1.0) or 1.0)))
        if abs(uv_scale - 1.0) > 1e-6:
            batch["texture_uv_scale"] = [uv_scale, uv_scale]
            changed = True
        return changed

    matched_count = 0
    for raw_batch in batches:
        check_cancelled()
        if not isinstance(raw_batch, dict):
            continue
        raw_batch["vertex_file"] = _source_package_path(source_package_dir, raw_batch.get("vertex_file"))
        identity = raw_batch.get("editor_identity")
        if isinstance(identity, dict) and identity.get("identity_file"):
            identity["identity_file"] = _source_package_path(source_package_dir, identity.get("identity_file"))
        for key in ("cloth_particle_file", "cloth_pin_file", "cloth_constraint_file"):
            if raw_batch.get(key):
                raw_batch[key] = _source_package_path(source_package_dir, raw_batch.get(key))
        if color_edits_active:
            for key, empty in (
                ("textures", {}),
                ("dds_textures", {}),
                ("selected_texture_slots", {}),
                ("material_inputs", []),
                ("material_layers", []),
                ("material_contract", {}),
                ("material_channel_contract", {}),
            ):
                raw_batch[key] = empty
            raw_batch["primary_material_layer"] = {"active": False}
        elif isinstance(raw_batch.get("textures"), Mapping):
            raw_batch["textures"] = {
                str(slot): _source_package_path(source_package_dir, value)
                for slot, value in dict(raw_batch["textures"]).items()
                if str(value or "").strip()
            }
        batch_labels = labels(raw_batch)
        for override in overrides:
            override_label = label_normalizer(getattr(override, "group_label", ""))
            if override_label and override_label in batch_labels and apply_override(raw_batch, override):
                matched_count += 1
                break
    if matched_count <= 0 and len(overrides) == 1:
        for raw_batch in batches:
            check_cancelled()
            if isinstance(raw_batch, dict) and apply_override(raw_batch, overrides[0]):
                matched_count += 1
    if matched_count <= 0 and include_skeleton_overlay:
        shutil.rmtree(package_dir, ignore_errors=True)
        return None
    vertex_count = sum(int(batch.get("vertex_count", 0) or 0) for batch in batches if isinstance(batch, Mapping))
    check_cancelled()
    try:
        atomic_write_text(
            package_dir / "manifest.json",
            json.dumps(manifest, separators=(",", ":"), default=str),
        )
    except Exception:
        shutil.rmtree(package_dir, ignore_errors=True)
        raise
    check_cancelled()
    notes = []
    if matched_count:
        notes.append(f"manifest-only material update: {matched_count:,} batch(es)")
    if not include_skeleton_overlay:
        notes.append("skeleton overlay omitted for material editing")
    notes.extend(
        tuple(
            dict.fromkeys(
                str(getattr(override, "reason", "") or "").strip()
                for override in overrides
                if str(getattr(override, "reason", "") or "").strip()
            )
        )[:3]
    )
    return package_dir, sum(isinstance(batch, Mapping) for batch in batches), vertex_count, tuple(notes)


def _reuse_or_fast_material_preview(
    request: MaterialSidecarPreviewBuildRequest,
    *,
    started: float,
    stop_event: Optional[threading.Event],
) -> Optional[MaterialSidecarPreviewBuildResult]:
    raise_if_cancelled(stop_event, "Material live preview cancelled.")
    reusable = request.reusable_package_dir
    if request.include_skeleton_overlay and reusable is not None and material_preview_package_matches_entry(
        reusable,
        request.preview_model_entry,
        stop_event=stop_event,
    ):
        cached_result = request.current_archive_result
        base_result = None
        if isinstance(cached_result, ArchivePreviewResult):
            base_result = dataclasses.replace(
                cached_result,
                preview_model=request.clone_preview_model(cached_result.preview_model, strip_images=True),
            )
        return MaterialSidecarPreviewBuildResult(
            "reused",
            request.generation,
            reusable,
            base_result,
            request.base_cache_key,
            (),
            (),
            request.live,
            request.material_effects_active,
            request.color_edits_active,
            0.0,
            0,
            0,
        )
    return None


def _build_full_material_preview(
    request: MaterialSidecarPreviewBuildRequest,
    *,
    log: Callable[[str], None],
    started: float,
    stop_event: Optional[threading.Event],
) -> MaterialSidecarPreviewBuildResult:
    notes: list[str] = []
    base_result: Optional[ArchivePreviewResult] = None
    cached = request.cached_base_result
    if isinstance(cached, ArchivePreviewResult) and isinstance(cached.preview_model, ModelPreviewData):
        log(request.cached_geometry_log)
        result = cached
        preview_model = request.clone_preview_model(cached.preview_model, strip_images=True)
        notes.append(request.cached_geometry_note)
    else:
        log(request.building_model_log)
        result = build_archive_preview_result(
            request.preview_model_entry,
            companion_entry=request.companion_entry,
            texture_entries_by_normalized_path=request.texture_entries_by_normalized_path,
            texture_entries_by_basename=request.texture_entries_by_basename,
            sidecar_entries_by_texture_path=request.sidecar_entries_by_texture_path,
            sidecar_entries_by_texture_basename=request.sidecar_entries_by_texture_basename,
            include_loose_preview_assets=False,
            visible_texture_mode=request.preview_settings.visible_texture_mode,
            enable_hkx_visual_preview=request.include_skeleton_overlay,
            stop_event=stop_event,
        )
        preview_model = request.clone_preview_model(result.preview_model, strip_images=True)
    raise_if_cancelled(stop_event, "Material live preview cancelled.")
    if isinstance(preview_model, ModelPreviewData) and not request.include_skeleton_overlay:
        preview_model = dataclasses.replace(preview_model, physics_overlay=None)
    if isinstance(preview_model, ModelPreviewData):
        bindings = _parse_archive_model_sidecar_texture_bindings(
            request.preview_sidecar_text,
            sidecar_path=request.sidecar_entry.path,
        )
        if bindings:
            sidecar_texts_by_path: dict[str, Tuple[str, ...]] = {}
            sidecar_texts_by_basename: dict[str, Tuple[str, ...]] = {}
            for binding in bindings:
                raise_if_cancelled(stop_event, "Material live preview cancelled.")
                normalized = normalize_texture_reference_for_sidecar_lookup(binding.texture_path)
                if normalized:
                    sidecar_texts_by_path[normalized] = (request.preview_sidecar_text,)
                    basename = PurePosixPath(normalized).name.lower()
                    if basename:
                        sidecar_texts_by_basename[basename] = (request.preview_sidecar_text,)
            notes.extend(
                _attach_model_sidecar_texture_preview_paths(
                    request.preview_model_entry,
                    preview_model,
                    parsed_mesh=None,
                    sidecar_texture_bindings=bindings,
                    visible_texture_mode=request.preview_settings.visible_texture_mode,
                    texture_entries_by_normalized_path=request.texture_entries_by_normalized_path,
                    texture_entries_by_basename=request.texture_entries_by_basename,
                    sidecar_texts_by_normalized_path=sidecar_texts_by_path,
                    sidecar_texts_by_basename=sidecar_texts_by_basename,
                    stop_event=stop_event,
                )
            )
        base_result = dataclasses.replace(
            result,
            preview_model=request.clone_preview_model(preview_model, strip_images=True),
        )
        notes.extend(
            request.apply_preview_overrides(
                preview_model,
                request.preview_sidecar_text,
                edited_values=request.material_preview_edits,
                stop_event=stop_event,
            )
        )
    warnings = (
        tuple(request.texture_resolution_warnings(request.preview_sidecar_text, stop_event=stop_event))
        if request.include_texture_edits
        else ()
    )
    if not isinstance(preview_model, ModelPreviewData):
        return MaterialSidecarPreviewBuildResult(
            "built", request.generation, None, base_result, request.base_cache_key,
            tuple(notes), warnings, request.live, request.material_effects_active,
            request.color_edits_active, 0.0, 0, 0,
        )
    package = build_or_lookup_dotnet_preview_package_from_model(
        preview_model,
        cache_root=request.cache_root,
        archive_identity=(
            f"material-sidecar:{request.preview_model_entry.path}:"
            f"{request.generation}:{hash(request.preview_sidecar_text)}"
        ),
        sidecar_generation=request.generation,
        cache_mode="off",
        cancelled=(stop_event.is_set if stop_event is not None else None),
        metadata={
            "entry_path": request.preview_model_entry.path,
            "surface": "material_sidecar",
        },
    )
    package_dir = package.package_dir
    raise_if_cancelled(stop_event, "Material live preview cancelled.")
    return MaterialSidecarPreviewBuildResult(
        "built",
        request.generation,
        package_dir,
        base_result,
        request.base_cache_key,
        tuple(notes),
        warnings,
        request.live,
        request.material_effects_active,
        request.color_edits_active,
        max(0.0, (time.perf_counter() - started) * 1000.0),
        len(tuple(getattr(preview_model, "meshes", ()) or ())),
        int(getattr(preview_model, "vertex_count", 0) or 0),
    )


def build_material_sidecar_preview(
    request: MaterialSidecarPreviewBuildRequest,
    log: Callable[[str], None],
    stop_event: Optional[threading.Event] = None,
) -> MaterialSidecarPreviewBuildResult:
    """Build, reuse, or patch one preview package with cooperative cancellation."""

    started = time.perf_counter()
    fast_result = _reuse_or_fast_material_preview(request, started=started, stop_event=stop_event)
    if fast_result is not None:
        return fast_result
    raise_if_cancelled(stop_event, "Material live preview cancelled.")
    return _build_full_material_preview(request, log=log, started=started, stop_event=stop_event)


__all__ = [
    "MaterialSidecarPreviewBuildRequest",
    "MaterialSidecarPreviewBuildResult",
    "build_material_sidecar_preview",
    "fast_material_preview_package_from_manifest",
    "material_preview_package_matches_entry",
]
