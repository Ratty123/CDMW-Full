"""D3D11 preview package workers."""

from __future__ import annotations

import copy
import dataclasses
import json
import shutil
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.models import (
    ArchiveEntry,
    ModelPreviewRenderSettings,
    PreparedModelPreviewBatch,
    PreparedModelPreviewData,
    RunCancelled,
    clamp_model_preview_render_settings,
)
from cdmw.rendering.model_preview_prepare import prepare_model_preview
from cdmw.rendering.native_preview_core import run_native_preview_core_preview_job
from cdmw.rendering.native_preview_package import write_isolated_d3d11_preview_package
from cdmw.rendering.native_preview_package_cache import (
    create_native_preview_package_staging_dir,
    lookup_native_preview_package_cache,
    store_native_preview_package_cache,
)


NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS = {".pac", ".pam", ".pamlod"}


class ArchiveD3D11PackageWorker(QObject):
    completed = Signal(int, int, object, float)
    error = Signal(int, int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        archive_preview_request_id: int,
        preview_model: object,
        prepared_preview: PreparedModelPreviewData,
        render_settings: ModelPreviewRenderSettings,
        *,
        use_textures: bool,
        high_quality_textures: bool,
        backend: str = "d3d11",
        prefer_direct_dds: bool = True,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.archive_preview_request_id = int(archive_preview_request_id)
        self.preview_model = preview_model
        self.prepared_preview = prepared_preview
        self.render_settings = clamp_model_preview_render_settings(render_settings)
        self.use_textures = bool(use_textures)
        self.high_quality_textures = bool(high_quality_textures)
        self.backend = str(backend or "d3d11").strip().lower() or "d3d11"
        self.prefer_direct_dds = bool(prefer_direct_dds)
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            started = time.perf_counter()
            package_dir = write_isolated_d3d11_preview_package(
                self.preview_model,
                self.prepared_preview,
                render_settings=self.render_settings,
                use_textures=self.use_textures,
                high_quality_textures=self.high_quality_textures,
                backend=self.backend,
                enable_material_combiner=True,
                prefer_direct_dds=self.prefer_direct_dds,
                stop_event=self.stop_event,
            )
            elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            if not self.stop_event.is_set():
                self.completed.emit(self.request_id, self.archive_preview_request_id, package_dir, elapsed_ms)
            else:
                try:
                    shutil.rmtree(package_dir, ignore_errors=True)
                except OSError:
                    pass
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, self.archive_preview_request_id, str(exc))
        finally:
            self.finished.emit()


class ArchiveNativePreviewPrefetchWorker(QObject):
    finished = Signal()

    def __init__(
        self,
        jobs: Sequence[Tuple[ArchiveEntry, Optional[ArchiveEntry], str]],
        render_settings: ModelPreviewRenderSettings,
        cache_root: Path,
        package_root: Optional[Path],
        cache_mode: str,
        package_cache_max_bytes: int,
        package_cache_target_bytes: int,
        *,
        validate_package: Callable[[Path], Tuple[bool, Sequence[str]]],
    ) -> None:
        super().__init__()
        self.jobs = tuple(jobs)
        self.render_settings = clamp_model_preview_render_settings(render_settings)
        self.cache_root = cache_root
        self.package_root = package_root
        self.cache_mode = str(cache_mode or "off").strip().lower()
        self.package_cache_max_bytes = max(0, int(package_cache_max_bytes or 0))
        self.package_cache_target_bytes = max(0, int(package_cache_target_bytes or 0))
        self.validate_package = validate_package
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.cache_mode != "aggressive" or self.package_cache_max_bytes <= 0:
                return
            for entry, companion_entry, cache_key in self.jobs:
                if self.stop_event.is_set():
                    return
                if str(getattr(entry, "extension", "") or "").strip().lower() not in NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS:
                    continue
                key = str(cache_key or "").strip()
                if not key:
                    continue
                if lookup_native_preview_package_cache(
                    self.cache_root,
                    key,
                    validate_package=self.validate_package,
                ) is not None:
                    continue
                staging_entry_dir: Optional[Path] = None
                try:
                    staging_entry_dir = create_native_preview_package_staging_dir(self.cache_root)
                    attempt = run_native_preview_core_preview_job(
                        entry,
                        cache_root=self.cache_root,
                        render_settings=self.render_settings,
                        companion_entry=companion_entry,
                        package_root=self.package_root,
                        output_root=staging_entry_dir / "package",
                        timeout_seconds=5.0,
                        stop_event=self.stop_event,
                        dds_cache_max_bytes=512 * 1024 * 1024,
                        dds_cache_target_bytes=384 * 1024 * 1024,
                    )
                    if attempt.succeeded:
                        store_native_preview_package_cache(
                            self.cache_root,
                            key,
                            staging_entry_dir,
                            {
                                "entry_path": str(getattr(entry, "path", "") or ""),
                                "companion_path": str(getattr(companion_entry, "path", "") or ""),
                                "cache_mode": self.cache_mode,
                                "prefetch": True,
                                "diagnostics": dict(attempt.diagnostics),
                            },
                            validate_package=self.validate_package,
                            max_bytes=self.package_cache_max_bytes,
                            target_bytes=self.package_cache_target_bytes,
                        )
                    else:
                        shutil.rmtree(staging_entry_dir, ignore_errors=True)
                except RunCancelled:
                    # The native service may already be writing this staging output.
                    # Leave it for later package-cache pruning instead of racing it.
                    return
                except Exception:
                    if staging_entry_dir is not None:
                        shutil.rmtree(staging_entry_dir, ignore_errors=True)
                    continue
        finally:
            self.finished.emit()


class AlignmentD3D11PackageWorker(QObject):
    completed = Signal(int, object, float, float)
    progress_changed = Signal(int, int, int, str)
    error = Signal(int, str)
    finished = Signal()
    _prepared_geometry_cache_lock = threading.Lock()
    _prepared_geometry_cache: "OrderedDict[str, tuple[object, PreparedModelPreviewData]]" = OrderedDict()
    _prepared_geometry_cache_limit = 8

    def __init__(
        self,
        request_id: int,
        preview_model: object,
        render_settings: ModelPreviewRenderSettings,
        *,
        use_textures: bool,
        high_quality_textures: bool,
        enable_material_combiner: bool = True,
        original_reference_material_parity: bool = True,
        display_mode: str = "side_by_side",
        editor_workspace: str = "mesh_alignment",
        package_quality: str = "archive_parity",
        geometry_signature: str = "",
        reuse_prepared_geometry: bool = False,
        geometry_cache_dir: Optional[Path] = None,
        texture_cache_dir: Optional[Path] = None,
        original_reference_native_package_dir: Optional[Path] = None,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.preview_model = preview_model
        self.render_settings = clamp_model_preview_render_settings(render_settings)
        self.use_textures = bool(use_textures)
        self.high_quality_textures = bool(high_quality_textures)
        self.enable_material_combiner = bool(enable_material_combiner)
        self.original_reference_material_parity = bool(original_reference_material_parity)
        self.display_mode = str(display_mode or "side_by_side").strip().lower()
        self.editor_workspace = str(editor_workspace or "mesh_alignment").strip()
        self.package_quality = str(package_quality or "archive_parity").strip().lower()
        self.geometry_signature = str(geometry_signature or "").strip()
        self.reuse_prepared_geometry = bool(reuse_prepared_geometry)
        self.geometry_cache_dir = Path(geometry_cache_dir).expanduser() if geometry_cache_dir else None
        self.texture_cache_dir = Path(texture_cache_dir).expanduser() if texture_cache_dir else None
        self.original_reference_native_package_dir = (
            Path(original_reference_native_package_dir).expanduser()
            if original_reference_native_package_dir
            else None
        )
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @classmethod
    def _prepared_geometry_cache_get(cls, key: str) -> Optional[tuple[object, PreparedModelPreviewData]]:
        key = str(key or "").strip()
        if not key:
            return None
        with cls._prepared_geometry_cache_lock:
            cached = cls._prepared_geometry_cache.get(key)
            if cached is None:
                return None
            cls._prepared_geometry_cache.move_to_end(key)
            return cached

    @classmethod
    def _prepared_geometry_cache_put(cls, key: str, prepared_model: object, prepared_preview: object) -> None:
        key = str(key or "").strip()
        if not key or not isinstance(prepared_preview, PreparedModelPreviewData):
            return
        with cls._prepared_geometry_cache_lock:
            cls._prepared_geometry_cache[key] = (prepared_model, prepared_preview)
            cls._prepared_geometry_cache.move_to_end(key)
            while len(cls._prepared_geometry_cache) > max(1, int(cls._prepared_geometry_cache_limit)):
                cls._prepared_geometry_cache.popitem(last=False)

    @staticmethod
    def _preview_role_key(value: object) -> str:
        return str(value or "").strip().lower()

    @classmethod
    def _mesh_by_source_identity(cls, model: object) -> Dict[tuple[str, int], object]:
        by_source: Dict[tuple[str, int], object] = {}
        for mesh in tuple(getattr(model, "meshes", ()) or ()):
            try:
                source_index = int(getattr(mesh, "source_submesh_index", -1) or -1)
            except (TypeError, ValueError, OverflowError):
                source_index = -1
            role_key = cls._preview_role_key(getattr(mesh, "preview_role", ""))
            if source_index >= 0 and (role_key, source_index) not in by_source:
                by_source[(role_key, source_index)] = mesh
        return by_source

    @staticmethod
    def _preview_roles_compatible(batch_role: str, mesh_role: str) -> bool:
        batch_role = AlignmentD3D11PackageWorker._preview_role_key(batch_role)
        mesh_role = AlignmentD3D11PackageWorker._preview_role_key(mesh_role)
        return batch_role == mesh_role or (not batch_role and not mesh_role)

    @staticmethod
    def _prepared_preview_with_current_materials(
        prepared_preview: PreparedModelPreviewData,
        model: object,
    ) -> PreparedModelPreviewData:
        meshes = tuple(getattr(model, "meshes", ()) or ())
        by_source = AlignmentD3D11PackageWorker._mesh_by_source_identity(model)
        updated_batches: list[PreparedModelPreviewBatch] = []
        for index, batch in enumerate(tuple(getattr(prepared_preview, "batches", ()) or ())):
            if not isinstance(batch, PreparedModelPreviewBatch):
                continue
            batch_role = str(getattr(batch, "editor_role", "") or "")
            source_submesh_index = int(getattr(batch, "source_submesh_index", -1) or -1)
            mesh = by_source.get((
                AlignmentD3D11PackageWorker._preview_role_key(batch_role),
                source_submesh_index,
            ))
            if mesh is None and 0 <= index < len(meshes):
                candidate = meshes[index]
                if AlignmentD3D11PackageWorker._preview_roles_compatible(
                    batch_role,
                    getattr(candidate, "preview_role", ""),
                ):
                    mesh = candidate
            if mesh is None:
                updated_batches.append(batch)
                continue
            editor_role = str(getattr(mesh, "preview_role", getattr(batch, "editor_role", "")) or "").strip()
            editor_role_key = editor_role.lower()
            editor_editable = source_submesh_index >= 0 or (
                "replacement" in editor_role_key
                and "reference" not in editor_role_key
                and "original" not in editor_role_key
            )
            if editor_role_key.startswith("hkx_"):
                editor_editable = False
            updated_batches.append(
                dataclasses.replace(
                    batch,
                    material_name=str(getattr(mesh, "material_name", getattr(batch, "material_name", "")) or "").strip(),
                    texture_name=str(getattr(mesh, "texture_name", getattr(batch, "texture_name", "")) or "").strip(),
                    preview_texture_path=str(getattr(mesh, "preview_texture_path", getattr(batch, "preview_texture_path", "")) or ""),
                    preview_texture_dds_path=str(getattr(mesh, "preview_texture_dds_path", getattr(batch, "preview_texture_dds_path", "")) or ""),
                    preview_normal_texture_path=str(getattr(mesh, "preview_normal_texture_path", getattr(batch, "preview_normal_texture_path", "")) or ""),
                    preview_normal_texture_dds_path=str(getattr(mesh, "preview_normal_texture_dds_path", getattr(batch, "preview_normal_texture_dds_path", "")) or ""),
                    preview_material_texture_path=str(getattr(mesh, "preview_material_texture_path", getattr(batch, "preview_material_texture_path", "")) or ""),
                    preview_material_texture_dds_path=str(getattr(mesh, "preview_material_texture_dds_path", getattr(batch, "preview_material_texture_dds_path", "")) or ""),
                    preview_height_texture_path=str(getattr(mesh, "preview_height_texture_path", getattr(batch, "preview_height_texture_path", "")) or ""),
                    preview_height_texture_dds_path=str(getattr(mesh, "preview_height_texture_dds_path", getattr(batch, "preview_height_texture_dds_path", "")) or ""),
                    preview_texture_flip_vertical=getattr(mesh, "preview_texture_flip_vertical", getattr(batch, "preview_texture_flip_vertical", None)),
                    preview_texture_brightness=float(getattr(mesh, "preview_texture_brightness", getattr(batch, "preview_texture_brightness", 1.0)) or 1.0),
                    preview_texture_tint=tuple(getattr(mesh, "preview_texture_tint", getattr(batch, "preview_texture_tint", ())) or ()),
                    preview_texture_uv_scale=tuple(getattr(mesh, "preview_texture_uv_scale", getattr(batch, "preview_texture_uv_scale", ())) or ()),
                    preview_vertex_color_mean=tuple(getattr(mesh, "preview_vertex_color_mean", getattr(batch, "preview_vertex_color_mean", ())) or ()),
                    preview_vertex_alpha_mean=getattr(mesh, "preview_vertex_alpha_mean", getattr(batch, "preview_vertex_alpha_mean", None)),
                    preview_vertex_alpha_min=getattr(mesh, "preview_vertex_alpha_min", getattr(batch, "preview_vertex_alpha_min", None)),
                    preview_vertex_color_count=int(getattr(mesh, "preview_vertex_color_count", getattr(batch, "preview_vertex_color_count", 0)) or 0),
                    preview_normal_texture_strength=float(getattr(mesh, "preview_normal_texture_strength", getattr(batch, "preview_normal_texture_strength", 0.0)) or 0.0),
                    preview_material_texture_type=str(getattr(mesh, "preview_material_texture_type", getattr(batch, "preview_material_texture_type", "")) or ""),
                    preview_material_texture_subtype=str(getattr(mesh, "preview_material_texture_subtype", getattr(batch, "preview_material_texture_subtype", "")) or ""),
                    preview_material_texture_packed_channels=tuple(getattr(mesh, "preview_material_texture_packed_channels", getattr(batch, "preview_material_texture_packed_channels", ())) or ()),
                    preview_material_texture_inputs=tuple(getattr(mesh, "preview_material_texture_inputs", getattr(batch, "preview_material_texture_inputs", ())) or ()),
                    preview_native_material_overrides=dict(getattr(mesh, "preview_native_material_overrides", getattr(batch, "preview_native_material_overrides", {})) or {}),
                    preview_alpha_mode=str(getattr(mesh, "preview_alpha_mode", getattr(batch, "preview_alpha_mode", "")) or "").strip(),
                    preview_double_sided=bool(getattr(mesh, "preview_double_sided", getattr(batch, "preview_double_sided", False))),
                    editor_role=editor_role,
                    editor_part_name=str(
                        getattr(mesh, "material_name", "")
                        or getattr(mesh, "texture_name", "")
                        or getattr(batch, "editor_part_name", "")
                        or source_submesh_index
                    ).strip(),
                    editor_editable=editor_editable,
                )
            )
        return dataclasses.replace(prepared_preview, batches=tuple(updated_batches))

    @staticmethod
    def _existing_package_file_path(package_dir: Path, raw_value: object) -> str:
        text = str(raw_value or "").strip()
        if not text:
            return ""
        try:
            path = Path(text)
            if path.is_absolute():
                return str(path) if path.is_file() else ""
            candidate = package_dir / text
            return str(candidate) if candidate.is_file() else ""
        except (OSError, ValueError):
            return ""

    @classmethod
    def _retarget_native_reference_batch_paths(cls, batch: Dict[str, object], package_dir: Path) -> None:
        for key in (
            "vertex_file",
            "cloth_particle_file",
            "cloth_pin_file",
            "cloth_constraint_file",
        ):
            resolved = cls._existing_package_file_path(package_dir, batch.get(key))
            if resolved:
                batch[key] = resolved
        editor_identity = batch.get("editor_identity")
        if isinstance(editor_identity, dict):
            resolved = cls._existing_package_file_path(package_dir, editor_identity.get("identity_file"))
            if resolved:
                editor_identity["identity_file"] = resolved
        textures = batch.get("textures")
        if isinstance(textures, Mapping):
            updated_textures: Dict[str, str] = {}
            for slot, value in textures.items():
                resolved = cls._existing_package_file_path(package_dir, value)
                if resolved:
                    updated_textures[str(slot)] = resolved
            batch["textures"] = updated_textures

        def retarget_descriptor(value: object) -> object:
            if isinstance(value, Mapping):
                updated = copy.deepcopy(dict(value))
                for path_key in ("source_path", "path", "file", "file_path"):
                    if path_key not in updated:
                        continue
                    resolved = cls._existing_package_file_path(package_dir, updated.get(path_key))
                    if resolved:
                        updated[path_key] = resolved
                    elif path_key == "source_path":
                        updated.pop(path_key, None)
                return updated
            return copy.deepcopy(value)

        dds_textures = batch.get("dds_textures")
        if isinstance(dds_textures, Mapping):
            updated_dds: Dict[str, object] = {}
            for slot, value in dds_textures.items():
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                    updated_dds[str(slot)] = [retarget_descriptor(item) for item in value]
                else:
                    updated_dds[str(slot)] = retarget_descriptor(value)
            batch["dds_textures"] = updated_dds

        def retarget_layer(value: object) -> object:
            if not isinstance(value, Mapping):
                return copy.deepcopy(value)
            updated = copy.deepcopy(dict(value))
            for path_key in (
                "diffuse_source",
                "mask_source",
                "material_source",
                "normal_source",
                "height_source",
            ):
                resolved = cls._existing_package_file_path(package_dir, updated.get(path_key))
                if resolved:
                    updated[path_key] = resolved
            return updated

        material_layers = batch.get("material_layers")
        if isinstance(material_layers, Sequence) and not isinstance(material_layers, (str, bytes, bytearray)):
            batch["material_layers"] = [retarget_layer(item) for item in material_layers]
        primary_material_layer = batch.get("primary_material_layer")
        if isinstance(primary_material_layer, Mapping):
            batch["primary_material_layer"] = retarget_layer(primary_material_layer)

    @classmethod
    def _replace_original_reference_with_native_package(
        cls,
        package_dir: Path,
        native_package_dir: Path,
        *,
        mirror_replacement_batches: bool = False,
    ) -> bool:
        try:
            package_dir = Path(package_dir)
            native_package_dir = Path(native_package_dir)
            manifest_path = package_dir / "manifest.json"
            native_manifest_path = native_package_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            native_manifest = json.loads(native_manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        if not isinstance(manifest, dict) or not isinstance(native_manifest, Mapping):
            return False
        target_batches = manifest.get("batches")
        native_batches = native_manifest.get("batches")
        if not isinstance(target_batches, list):
            return False
        if not isinstance(native_batches, Sequence) or isinstance(native_batches, (str, bytes, bytearray)):
            return False
        def set_editor_identity(
            batch: Dict[str, object],
            *,
            role: str,
            editable: bool,
            part_name: str,
            fallback_source_index: Optional[int] = None,
        ) -> None:
            editor_identity = batch.get("editor_identity")
            if not isinstance(editor_identity, dict):
                editor_identity = {}
                batch["editor_identity"] = editor_identity
            if fallback_source_index is not None:
                try:
                    source_index = int(editor_identity.get("source_submesh_index", -1) or -1)
                except (TypeError, ValueError, OverflowError):
                    source_index = -1
                if source_index < 0:
                    editor_identity["source_submesh_index"] = int(fallback_source_index)
            editor_identity["role"] = role
            editor_identity["editable"] = bool(editable)
            if part_name:
                editor_identity["part_name"] = part_name
            batch["editor_role"] = role
            batch["role"] = role
            batch["editor_editable"] = bool(editable)
            batch["editable"] = bool(editable)
            batch["editor_part_name"] = part_name

        def native_batches_for_role(
            *,
            role: str,
            editable: bool,
            fallback_name_prefix: str,
            fallback_source_indices: bool = False,
        ) -> List[Dict[str, object]]:
            role_batches: List[Dict[str, object]] = []
            for raw_batch in native_batches:
                if not isinstance(raw_batch, Mapping):
                    continue
                batch = copy.deepcopy(dict(raw_batch))
                cls._retarget_native_reference_batch_paths(batch, native_package_dir)
                if not str(batch.get("vertex_file", "") or "").strip():
                    continue
                part_name = str(
                    batch.get("material_name", "")
                    or batch.get("texture_name", "")
                    or f"{fallback_name_prefix}_{len(role_batches)}"
                ).strip()
                set_editor_identity(
                    batch,
                    role=role,
                    editable=editable,
                    part_name=part_name,
                    fallback_source_index=(len(role_batches) if fallback_source_indices else None),
                )
                role_batches.append(batch)
            return role_batches

        reference_batches = native_batches_for_role(
            role="original_reference",
            editable=False,
            fallback_name_prefix="original",
        )
        if not reference_batches:
            return False
        replacement_batches: List[Dict[str, object]] = []
        if mirror_replacement_batches:
            replacement_batches = native_batches_for_role(
                role="replacement_preview",
                editable=True,
                fallback_name_prefix="replacement",
                fallback_source_indices=True,
            )
        else:
            for raw_batch in target_batches:
                if not isinstance(raw_batch, Mapping):
                    continue
                role = str(raw_batch.get("editor_role", raw_batch.get("role", "")) or "").strip().lower()
                if role == "original_reference":
                    continue
                replacement_batches.append(copy.deepcopy(dict(raw_batch)))
        if not replacement_batches:
            return False
        merged_batches = reference_batches + replacement_batches
        vertex_count = 0
        face_count = 0
        for index, batch in enumerate(merged_batches):
            batch["index"] = index
            try:
                vertex_count += int(batch.get("vertex_count", 0) or 0)
            except (TypeError, ValueError):
                pass
            try:
                face_count += int(batch.get("face_count", 0) or 0)
            except (TypeError, ValueError):
                try:
                    face_count += int(batch.get("index_count", 0) or 0) // 3
                except (TypeError, ValueError):
                    pass
        manifest["batches"] = merged_batches
        manifest["batch_count"] = len(merged_batches)
        manifest["mesh_count"] = len(merged_batches)
        manifest["vertex_count"] = vertex_count
        manifest["face_count"] = face_count
        manifest["original_reference_package_source"] = "native_preview_core"
        manifest["original_reference_native_package_path"] = str(native_package_dir)
        notes = manifest.get("notes")
        if not isinstance(notes, list):
            notes = []
        notes.append("original_reference uses exact Native Preview Core package batches")
        manifest["notes"] = notes
        try:
            manifest_path.write_text(json.dumps(manifest, separators=(",", ":"), default=str), encoding="utf-8")
        except Exception:
            return False
        return True

    @Slot()
    def run(self) -> None:
        def _emit_progress(current: int, total: int, message: str) -> None:
            if self.stop_event.is_set():
                return
            self.progress_changed.emit(
                self.request_id,
                max(0, int(current)),
                max(1, int(total)),
                str(message or "Preparing D3D11 preview package..."),
            )

        def _emit_package_progress(current: int, total: int, message: str) -> None:
            total = max(1, int(total))
            current = max(0, min(total, int(current)))
            percent = 40 + int(round((float(current) / float(total)) * 40.0))
            _emit_progress(percent, 100, message or "Writing D3D11 preview package...")

        try:
            if self.stop_event.is_set():
                return
            prepared_model: object
            prepared_preview: object
            cached_prepared = (
                self._prepared_geometry_cache_get(self.geometry_signature)
                if self.reuse_prepared_geometry
                else None
            )
            if cached_prepared is not None:
                prepared_model, cached_preview = cached_prepared
                prepared_preview = self._prepared_preview_with_current_materials(cached_preview, self.preview_model)
                prepare_ms = 0.0
                _emit_progress(35, 100, "Preparing preview - reused geometry buffers.")
            else:
                _emit_progress(0, 100, "Preparing preview - cloning model.")
                prepare_started = time.perf_counter()
                prepared_model, prepared_preview = prepare_model_preview(
                    self.preview_model,
                    render_settings=self.render_settings,
                    stop_event=self.stop_event,
                    enable_material_combiner=bool(self.enable_material_combiner and self.use_textures),
                )
                prepare_ms = max(0.0, (time.perf_counter() - prepare_started) * 1000.0)
                if isinstance(prepared_preview, PreparedModelPreviewData):
                    self._prepared_geometry_cache_put(self.geometry_signature, prepared_model, prepared_preview)
            if self.stop_event.is_set():
                return
            _emit_progress(40, 100, "Preparing preview - model buffers ready.")
            package_started = time.perf_counter()
            package_dir = write_isolated_d3d11_preview_package(
                prepared_model,
                prepared_preview,
                render_settings=self.render_settings,
                use_textures=self.use_textures,
                high_quality_textures=self.high_quality_textures,
                backend="d3d11",
                enable_material_combiner=bool(self.enable_material_combiner and self.use_textures),
                prefer_direct_dds=True,
                original_reference_material_parity=self.original_reference_material_parity,
                display_mode=self.display_mode,
                editor_workspace=self.editor_workspace,
                geometry_cache_dir=self.geometry_cache_dir,
                texture_cache_dir=self.texture_cache_dir,
                geometry_cache_key=self.geometry_signature,
                stop_event=self.stop_event,
                on_progress=_emit_package_progress,
            )
            if self.original_reference_native_package_dir is not None:
                self._replace_original_reference_with_native_package(
                    package_dir,
                    self.original_reference_native_package_dir,
                    mirror_replacement_batches=self.editor_workspace == "modify_original_alignment",
                )
            package_ms = max(0.0, (time.perf_counter() - package_started) * 1000.0)
            if not self.stop_event.is_set():
                _emit_progress(80, 100, "Preparing preview - package ready.")
                self.completed.emit(self.request_id, package_dir, prepare_ms, package_ms)
            else:
                try:
                    shutil.rmtree(package_dir, ignore_errors=True)
                except OSError:
                    pass
        except RunCancelled:
            pass
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, str(exc))
        finally:
            self.finished.emit()


__all__ = [
    "AlignmentD3D11PackageWorker",
    "ArchiveD3D11PackageWorker",
    "ArchiveNativePreviewPrefetchWorker",
    "NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS",
]
