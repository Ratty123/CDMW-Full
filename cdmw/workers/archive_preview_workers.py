"""Archive preview worker for progressive archive asset previews."""

from __future__ import annotations

import dataclasses
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage, QImageReader

from cdmw.core.archive import (
    build_archive_asset_family_graph,
    build_archive_entry_detail_text,
    build_archive_entry_metadata_summary,
    build_archive_preview_result,
)
from cdmw.core.archive_modding import ARCHIVE_MESH_EXTENSIONS
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    ArchivePreviewResult,
    AssetFamilyGraph,
    ModelPreviewData,
    ModelPreviewMesh,
    ModelPreviewRenderSettings,
    PreparedModelPreviewData,
    RelationConfidence,
    RelationKind,
    RunCancelled,
    clamp_model_preview_render_settings,
)
from cdmw.rendering.model_preview_prepare import prepare_model_preview
from cdmw.rendering.static_model_thumbnail import render_static_model_thumbnail_image
from cdmw.workers.archive_preview_native import ArchivePreviewNativeMixin, NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS
from cdmw.rendering.native_preview_package_cache import (
    lookup_native_preview_package_cache,
)


def _merge_timing_maps(*timing_maps: Optional[Dict[str, float]]) -> Dict[str, float]:
    merged: Dict[str, float] = {}
    for timing_map in timing_maps:
        if not timing_map:
            continue
        for key, value in timing_map.items():
            try:
                merged[str(key)] = max(0.0, float(value))
            except (TypeError, ValueError):
                continue
    return merged


@dataclasses.dataclass(slots=True)
class _ArchivePreviewWorkerPayload:
    result: ArchivePreviewResult
    source: str = "worker"
    cache_key: str = ""
    cacheable: bool = True


class ArchivePreviewWorker(ArchivePreviewNativeMixin, QObject):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        entry: Optional[ArchiveEntry],
        companion_entry: Optional[ArchiveEntry],
        texture_entries_by_normalized_path: Dict[str, List[ArchiveEntry]],
        texture_entries_by_basename: Dict[str, List[ArchiveEntry]],
        sidecar_entries_by_texture_path: Optional[Dict[str, Sequence[ArchiveEntry]]],
        sidecar_entries_by_texture_basename: Optional[Dict[str, Sequence[ArchiveEntry]]],
        loose_search_roots: Sequence[Path],
        visible_texture_mode: str = "mesh_base_first",
        support_texture_slots: Sequence[str] = ("normal", "material", "height"),
        render_settings: Optional[ModelPreviewRenderSettings] = None,
        include_loose_preview_assets: bool = False,
        sidecar_generation: int = 0,
        attach_preview_images: bool = True,
        native_preview_core_enabled: bool = False,
        native_preview_core_cache_root: Optional[Path] = None,
        native_preview_core_package_root: Optional[Path] = None,
        native_preview_package_cache_key: str = "",
        native_preview_package_cache_mode: str = "off",
        native_preview_package_cache_max_bytes: int = 0,
        native_preview_package_cache_target_bytes: int = 0,
        full_preview_cache_key: str = "",
        fast_preview_cache_key: str = "",
        preview_cache_snapshot: Optional[Mapping[str, ArchivePreviewResult]] = None,
        emit_quick_preview: bool = False,
        emit_private_payloads: bool = False,
        static_thumbnail_size: Optional[Tuple[int, int]] = None,
        static_thumbnail_text_color: str = "#8b949e",
        static_thumbnail_point_cloud: bool = False,
    ):
        super().__init__()
        self.request_id = request_id
        self.entry = entry
        self.companion_entry = companion_entry
        self.texture_entries_by_normalized_path = texture_entries_by_normalized_path
        self.texture_entries_by_basename = texture_entries_by_basename
        self.sidecar_entries_by_texture_path = sidecar_entries_by_texture_path
        self.sidecar_entries_by_texture_basename = sidecar_entries_by_texture_basename
        self.loose_search_roots = list(loose_search_roots)
        self.visible_texture_mode = str(visible_texture_mode or "").strip().lower() or "mesh_base_first"
        self.support_texture_slots = tuple(
            slot
            for slot in ("normal", "material", "height")
            if str(slot) in {
                str(value or "").strip().lower()
                for value in (support_texture_slots or ())
            }
        )
        self.render_settings = clamp_model_preview_render_settings(render_settings)
        self.include_loose_preview_assets = include_loose_preview_assets
        self.sidecar_generation = int(sidecar_generation)
        self.attach_preview_images = bool(attach_preview_images)
        self.native_preview_core_enabled = bool(native_preview_core_enabled)
        self.native_preview_core_cache_root = native_preview_core_cache_root
        self.native_preview_core_package_root = native_preview_core_package_root
        self.native_preview_package_cache_key = str(native_preview_package_cache_key or "").strip()
        self.native_preview_package_cache_mode = str(native_preview_package_cache_mode or "off").strip().lower()
        self.native_preview_package_cache_max_bytes = max(0, int(native_preview_package_cache_max_bytes or 0))
        self.native_preview_package_cache_target_bytes = max(0, int(native_preview_package_cache_target_bytes or 0))
        self.full_preview_cache_key = str(full_preview_cache_key or "").strip()
        self.fast_preview_cache_key = str(fast_preview_cache_key or "").strip()
        self.preview_cache_snapshot = dict(preview_cache_snapshot or {})
        self.emit_quick_preview = bool(emit_quick_preview)
        self.emit_private_payloads = bool(emit_private_payloads)
        self.static_thumbnail_size = (
            (max(320, int(static_thumbnail_size[0])), max(260, int(static_thumbnail_size[1])))
            if static_thumbnail_size is not None and len(static_thumbnail_size) >= 2
            else None
        )
        self.static_thumbnail_text_color = str(static_thumbnail_text_color or "#8b949e")
        self.static_thumbnail_point_cloud = bool(static_thumbnail_point_cloud)
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            timings: Dict[str, float] = {}
            if self.stop_event.is_set():
                return
            cached_full = self._cached_preview_payload(self.full_preview_cache_key, source="preview_cache")
            if cached_full is not None:
                self._emit_preview_payload(cached_full)
                return
            durable_native = self._durable_native_preview_cache_payload()
            if durable_native is not None:
                self._emit_preview_payload(durable_native)
                return
            native_attempt: Optional[NativePreviewCoreAttempt] = None
            native_supported = self._native_preview_core_supported_for_entry()
            if native_supported and self.emit_quick_preview:
                quick_payload = self._quick_archive_model_preview_payload()
                if quick_payload is not None:
                    self._emit_preview_payload(quick_payload)
            if native_supported:
                native_attempt = self._try_native_preview_core()
                if self._emit_native_preview_core_attempt(native_attempt, timings):
                    return
            cached_fast = self._cached_preview_payload(self.fast_preview_cache_key, source="preview_cache_fast")
            if cached_fast is not None:
                self._emit_preview_payload(cached_fast)
            elif self.emit_quick_preview:
                quick_payload = self._quick_archive_model_preview_payload()
                if quick_payload is not None:
                    self._emit_preview_payload(quick_payload)
            if self._should_emit_progressive_fast_preview():
                fast_started_at = time.perf_counter()
                fast_payload = self._build_archive_preview_payload(
                    quality_tier="fast",
                    render_settings=self._fast_render_settings(),
                    support_texture_slots=(),
                )
                fast_timings = dict(getattr(fast_payload, "timings", {}) or {})
                fast_timings["progressive_fast_s"] = max(0.0, float(time.perf_counter() - fast_started_at))
                fast_payload = dataclasses.replace(
                    fast_payload,
                    timings=fast_timings,
                    sidecar_generation=self.sidecar_generation,
                )
                if not self.stop_event.is_set():
                    self._emit_archive_preview_result(fast_payload)
            if native_attempt is None:
                native_attempt = self._try_native_preview_core()
                if self._emit_native_preview_core_attempt(native_attempt, timings):
                    return
            payload = self._build_archive_preview_payload(quality_tier="full", render_settings=self.render_settings)
            if native_attempt is not None:
                payload = self._attach_native_preview_core_note(payload, native_attempt)
            if self.stop_event.is_set():
                return
            if not self.stop_event.is_set():
                payload_timings = _merge_timing_maps(getattr(payload, "timings", None), timings)
                payload_timings["progressive_full_s"] = max(
                    0.0,
                    payload_timings.get("worker_build_s", 0.0)
                    + payload_timings.get("prepared_model_s", 0.0)
                    + payload_timings.get("image_attach_s", 0.0),
                )
                payload = dataclasses.replace(
                    payload,
                    timings=payload_timings,
                    sidecar_generation=self.sidecar_generation,
                )
                self._emit_archive_preview_result(payload)
        except RunCancelled:
            pass
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, str(exc))
        finally:
            self.finished.emit()

    def _should_emit_progressive_fast_preview(self) -> bool:
        if self.entry is None or self.include_loose_preview_assets:
            return False
        if self.static_thumbnail_size is not None:
            return False
        if self._native_preview_core_supported_for_entry():
            return False
        return str(getattr(self.entry, "extension", "") or "").strip().lower() in {".pac", ".pam", ".pamlod"}

    def _emit_preview_payload(self, payload: _ArchivePreviewWorkerPayload) -> None:
        if self.stop_event.is_set():
            return
        result = self._with_static_thumbnail(payload.result)
        if self.emit_private_payloads:
            self.completed.emit(self.request_id, dataclasses.replace(payload, result=result))
        else:
            self.completed.emit(self.request_id, result)

    def _emit_archive_preview_result(self, result: ArchivePreviewResult) -> None:
        if not self.stop_event.is_set():
            self.completed.emit(self.request_id, self._with_static_thumbnail(result))

    def _with_static_thumbnail(self, result: ArchivePreviewResult) -> ArchivePreviewResult:
        size = self.static_thumbnail_size
        if size is None or not isinstance(result.preview_model, ModelPreviewData):
            return result
        existing = getattr(result, "static_preview_image", None)
        if isinstance(existing, QImage) and not existing.isNull() and (existing.width(), existing.height()) == size:
            return result
        image = render_static_model_thumbnail_image(
            result.preview_model,
            width=size[0],
            height=size[1],
            text_color=self.static_thumbnail_text_color,
            draw_point_cloud_when_no_triangles=self.static_thumbnail_point_cloud,
            stop_event=self.stop_event,
        )
        return dataclasses.replace(result, static_preview_image=image)

    def _cached_preview_payload(self, cache_key: str, *, source: str) -> Optional[_ArchivePreviewWorkerPayload]:
        key = str(cache_key or "").strip()
        if not key:
            return None
        cached = self.preview_cache_snapshot.get(key)
        if not isinstance(cached, ArchivePreviewResult):
            return None
        native_package_path = str(getattr(cached, "native_preview_package_path", "") or "").strip()
        if native_package_path:
            valid_package, _missing = self._validate_native_preview_core_package_basic(Path(native_package_path))
            if not valid_package:
                return None
        result = self._attach_cached_preview_payload_images(cached)
        return _ArchivePreviewWorkerPayload(
            result=result,
            source=source,
            cache_key=key,
            cacheable=True,
        )

    def _durable_native_preview_cache_payload(self) -> Optional[_ArchivePreviewWorkerPayload]:
        if self.entry is None or self.include_loose_preview_assets:
            return None
        if not self.native_preview_core_enabled:
            return None
        if str(getattr(self.entry, "extension", "") or "").strip().lower() not in NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS:
            return None
        cache_root = self.native_preview_core_cache_root
        cache_key = str(self.native_preview_package_cache_key or "").strip()
        cache_mode = str(self.native_preview_package_cache_mode or "off").strip().lower()
        if cache_root is None or cache_mode == "off" or not cache_key:
            return None
        hit = lookup_native_preview_package_cache(
            Path(cache_root),
            cache_key,
            validate_package=self._validate_native_preview_core_package_basic,
        )
        if hit is None:
            return None
        diagnostics_source = hit.metadata.get("diagnostics") if isinstance(hit.metadata, Mapping) else {}
        diagnostics = dict(diagnostics_source) if isinstance(diagnostics_source, Mapping) else {}
        diagnostics["native_preview_package_cache"] = "hit"
        diagnostics["native_preview_package_cache_mode"] = str(hit.metadata.get("cache_mode", "") or "")
        diagnostics["package_path"] = str(hit.package_dir)
        detail_lines = [
            "Native Preview Core loaded a validated durable D3D11 preview package.",
            "D3D11 package source: native-core cache",
            f"Package: {hit.package_dir}",
            "Cached preview package hit; no archive package rebuild was needed.",
        ]
        result = ArchivePreviewResult(
            status="ok",
            title=self.entry.basename,
            metadata_summary=f"{build_archive_entry_metadata_summary(self.entry)} | cached preview package",
            detail_text="\n".join(detail_lines),
            preview_model=None,
            native_preview_package_path=str(hit.package_dir),
            native_preview_diagnostics=diagnostics,
            preferred_view="model",
            sidecar_generation=self.sidecar_generation,
        )
        return _ArchivePreviewWorkerPayload(
            result=result,
            source="native_package_cache",
            cache_key=self.full_preview_cache_key,
            cacheable=True,
        )

    def _quick_archive_model_preview_payload(self) -> Optional[_ArchivePreviewWorkerPayload]:
        entry = self.entry
        if entry is None or entry.extension not in ARCHIVE_MESH_EXTENSIONS:
            return None
        sidecar_refs: List[ArchiveModelTextureReference] = []
        normalized_path = entry.path.replace("\\", "/").strip()
        source_stem = PurePosixPath(normalized_path).stem.strip()
        candidate_basenames: List[str] = []
        if source_stem:
            if entry.extension == ".pac":
                candidate_basenames.append(f"{source_stem}.pac_xml")
            elif entry.extension == ".pam":
                candidate_basenames.append(f"{source_stem}.pami")
                candidate_basenames.append(f"{source_stem}.pam_xml")
            elif entry.extension == ".pamlod":
                candidate_basenames.append(f"{source_stem}.pami")
                candidate_basenames.append(f"{source_stem}.pamlod_xml")
        seen_paths: set[str] = set()
        for basename in candidate_basenames:
            for related_entry in self.texture_entries_by_basename.get(basename.lower(), ()):
                normalized_related = related_entry.path.replace("\\", "/")
                if normalized_related in seen_paths:
                    continue
                seen_paths.add(normalized_related)
                sidecar_refs.append(
                    ArchiveModelTextureReference(
                        reference_name=PurePosixPath(normalized_related).name,
                        semantic_label="Material Sidecar",
                        resolution_status="resolved",
                        resolved_archive_path=related_entry.path,
                        resolved_package_label=related_entry.package_label,
                        resolved_entry=related_entry,
                        usage_count=1,
                        reference_kind=RelationKind.MATERIAL_SIDECAR.value,
                        relation_group="Material Sidecars",
                        relation_reason="Same-stem material sidecar",
                        relation_confidence=RelationConfidence.DERIVED_SAME_STEM.value,
                    )
                )
        detail_parts = [
            build_archive_entry_detail_text(
                entry,
                "Quick preview is showing metadata and same-stem material sidecars while the full 3D model preview builds in the background.",
            ),
            "Full preview loading...",
        ]
        if sidecar_refs:
            detail_parts.append(f"Found {len(sidecar_refs):,} likely material sidecar(s).")
        result = ArchivePreviewResult(
            status="ok",
            title=entry.basename,
            metadata_summary=f"{build_archive_entry_metadata_summary(entry)} | Full preview loading...",
            detail_text="\n\n".join(part for part in detail_parts if part),
            quality_tier="quick",
            model_texture_references=tuple(sidecar_refs),
            asset_family_graph=build_archive_asset_family_graph(entry, tuple(sidecar_refs)),
            preferred_view="info",
            sidecar_generation=self.sidecar_generation,
        )
        return _ArchivePreviewWorkerPayload(
            result=result,
            source="quick_preview",
            cache_key="",
            cacheable=False,
        )

    @staticmethod
    def _clone_preview_model_for_worker(
        preview_model: Optional[object],
        *,
        strip_images: bool = False,
    ) -> Optional[object]:
        if not isinstance(preview_model, ModelPreviewData):
            return preview_model
        cloned_meshes: List[object] = []
        for mesh in getattr(preview_model, "meshes", []) or []:
            if isinstance(mesh, ModelPreviewMesh):
                mesh_values = {
                    field_info.name: getattr(mesh, field_info.name)
                    for field_info in dataclasses.fields(ModelPreviewMesh)
                }
                if strip_images:
                    mesh_values["preview_texture_image"] = None
                    mesh_values["preview_normal_texture_image"] = None
                    mesh_values["preview_material_texture_image"] = None
                    mesh_values["preview_height_texture_image"] = None
                cloned_meshes.append(ModelPreviewMesh(**mesh_values))
            else:
                cloned_meshes.append(mesh)
        return ModelPreviewData(
            **{
                field_info.name: (
                    cloned_meshes
                    if field_info.name == "meshes"
                    else getattr(preview_model, field_info.name)
                )
                for field_info in dataclasses.fields(ModelPreviewData)
            }
        )

    def _attach_cached_preview_payload_images(self, result: ArchivePreviewResult) -> ArchivePreviewResult:
        prepared_preview = getattr(result, "prepared_preview_model", None)
        cloned = dataclasses.replace(
            result,
            preview_model=self._clone_preview_model_for_worker(result.preview_model, strip_images=False),
        )
        return self._attach_loaded_images(
            cloned,
            include_model_textures=not isinstance(prepared_preview, PreparedModelPreviewData),
        )

    def _fast_render_settings(self) -> ModelPreviewRenderSettings:
        return clamp_model_preview_render_settings(
            dataclasses.replace(
                self.render_settings,
                high_quality_by_default=False,
                preview_texture_max_dimension=min(int(self.render_settings.preview_texture_max_dimension), 1024),
                low_quality_texture_max_dimension=min(int(self.render_settings.low_quality_texture_max_dimension), 256),
                disable_all_support_maps=True,
                disable_normal_map=True,
                disable_material_map=True,
                disable_height_map=True,
                max_anisotropy=min(int(self.render_settings.max_anisotropy), 4),
            )
        )

    def _build_archive_preview_payload(
        self,
        *,
        quality_tier: str,
        render_settings: ModelPreviewRenderSettings,
        support_texture_slots: Optional[Sequence[str]] = None,
    ) -> ArchivePreviewResult:
        timings: Dict[str, float] = {}
        worker_build_started_at = time.perf_counter()
        payload = build_archive_preview_result(
            self.entry,
            self.loose_search_roots,
            companion_entry=self.companion_entry,
            texture_entries_by_normalized_path=self.texture_entries_by_normalized_path,
            texture_entries_by_basename=self.texture_entries_by_basename,
            sidecar_entries_by_texture_path=self.sidecar_entries_by_texture_path,
            sidecar_entries_by_texture_basename=self.sidecar_entries_by_texture_basename,
            include_loose_preview_assets=self.include_loose_preview_assets,
            visible_texture_mode=self.visible_texture_mode,
            support_texture_slots=self.support_texture_slots if support_texture_slots is None else support_texture_slots,
            quality_tier=quality_tier,
            enable_hkx_visual_preview=str(getattr(self.entry, "extension", "") or "").strip().lower() not in {".hkx", ".hkt"},
            stop_event=self.stop_event,
        )
        timings["worker_build_s"] = max(0.0, float(time.perf_counter() - worker_build_started_at))
        if self.stop_event.is_set():
            return payload
        has_preview_model = getattr(payload, "preview_model", None) is not None
        image_attach_started_at = time.perf_counter()
        if self.attach_preview_images and not has_preview_model:
            payload = self._attach_loaded_images(payload)
        timings["image_attach_s"] = max(0.0, float(time.perf_counter() - image_attach_started_at))
        if self.stop_event.is_set():
            return payload
        prepared_model_started_at = time.perf_counter()
        prepared_preview_model = None
        if getattr(payload, "preview_model", None) is not None:
            prepared_model, prepared_preview_model = prepare_model_preview(
                payload.preview_model,
                render_settings=render_settings,
                stop_event=self.stop_event,
            )
            payload = dataclasses.replace(
                payload,
                preview_model=prepared_model,
                prepared_preview_model=prepared_preview_model,
            )
        timings["prepared_model_s"] = max(0.0, float(time.perf_counter() - prepared_model_started_at))
        if self.stop_event.is_set():
            return payload
        if self.attach_preview_images and has_preview_model:
            image_attach_started_at = time.perf_counter()
            payload = self._attach_loaded_images(payload, include_model_textures=False)
            timings["image_attach_s"] = timings.get("image_attach_s", 0.0) + max(
                0.0,
                float(time.perf_counter() - image_attach_started_at),
            )
        return dataclasses.replace(
            payload,
            timings=_merge_timing_maps(getattr(payload, "timings", None), timings),
            sidecar_generation=self.sidecar_generation,
        )

    def _attach_loaded_images(
        self,
        result: ArchivePreviewResult,
        *,
        include_model_textures: bool = True,
    ) -> ArchivePreviewResult:
        loaded_images: Dict[str, object] = {}

        def load_image_cached(path: str) -> object:
            if self.stop_event.is_set():
                return None
            normalized_path = str(path or "").strip()
            if not normalized_path:
                return None
            if normalized_path not in loaded_images:
                loaded_images[normalized_path] = self._load_image(normalized_path)
            return loaded_images[normalized_path]

        preview_image = load_image_cached(result.preview_image_path)
        loose_preview_image = load_image_cached(result.loose_preview_image_path)
        preview_model = result.preview_model
        meshes = getattr(preview_model, "meshes", None)
        if include_model_textures and meshes:
            for mesh in meshes:
                raise_if_cancelled(self.stop_event)
                texture_slots = (
                    ("preview_texture_path", "preview_texture_image"),
                    ("preview_normal_texture_path", "preview_normal_texture_image"),
                    ("preview_material_texture_path", "preview_material_texture_image"),
                    ("preview_height_texture_path", "preview_height_texture_image"),
                )
                for path_attr, image_attr in texture_slots:
                    raise_if_cancelled(self.stop_event)
                    preview_texture_path = str(getattr(mesh, path_attr, "") or "").strip()
                    if not preview_texture_path or getattr(mesh, image_attr, None) is not None:
                        continue
                    texture_image = load_image_cached(preview_texture_path)
                    if texture_image is not None:
                        setattr(mesh, image_attr, texture_image)
        if preview_image is None and loose_preview_image is None:
            return result
        return dataclasses.replace(
            result,
            preview_image=preview_image,
            loose_preview_image=loose_preview_image,
        )

    def _load_image(self, image_path: str) -> object:
        if self.stop_event.is_set() or not image_path:
            return None
        reader = QImageReader(image_path)
        image = reader.read()
        if self.stop_event.is_set() or image.isNull():
            return None
        return image


__all__ = ["ArchivePreviewWorker", "_ArchivePreviewWorkerPayload"]
