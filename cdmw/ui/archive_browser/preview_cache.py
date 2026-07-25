"""Archive preview cache keys, validation, and cache lookup helpers."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtGui import QImageReader

from cdmw.services.archive_query_service import resolve_archive_pathc_path
from cdmw.services.cache_layout import runtime_cache_layout
from cdmw.models import (
    PREVIEW_MESH_IMAGE_FIELD_NAMES,
    ArchiveEntry,
    ArchivePreviewResult,
    ModelPreviewData,
    ModelPreviewMesh,
)
from cdmw.services.preview_rendering_service import PreparedModelPreviewData
from cdmw.services.preview_rendering_service import (
    NativePreviewCoreServiceClient,
    find_native_preview_core_binary,
    render_settings_to_native_preview_core_dict,
)
from cdmw.services.preview_rendering_service import (
    DOTNET_PREVIEW_PACKAGE_CACHE_SCHEMA,
    clear_dotnet_preview_package_cache,
    dotnet_preview_package_cache_budget,
    is_durable_dotnet_preview_package_path,
)
from cdmw.services.mesh_dotnet_preview_package import validate_dotnet_preview_package
from cdmw.services.mesh_workflow_service import clear_pac_xml_profile_index_cache
from cdmw.ui.model_preview_native import ARCHIVE_MODEL_RENDERER_D3D11


def _archive_preview_dependency_digest(entries: Sequence[ArchiveEntry]) -> str:
    """Hash one authoritative prepared dependency snapshot without archive I/O."""

    rows: List[Tuple[object, ...]] = []
    for entry in entries:
        prepared_sha256 = str(getattr(entry, "prepared_sha256", "") or "").strip().lower()
        if len(prepared_sha256) != 64:
            return ""
        try:
            bytes.fromhex(prepared_sha256)
        except ValueError:
            return ""
        rows.append(
            (
                str(getattr(entry, "path", "") or "").replace("\\", "/").strip("/").casefold(),
                str(getattr(entry, "pamt_path", "") or "").replace("\\", "/").casefold(),
                str(getattr(entry, "paz_file", "") or "").replace("\\", "/").casefold(),
                int(getattr(entry, "paz_index", 0) or 0),
                int(getattr(entry, "offset", 0) or 0),
                int(getattr(entry, "comp_size", 0) or 0),
                int(getattr(entry, "orig_size", 0) or 0),
                int(getattr(entry, "flags", 0) or 0),
                prepared_sha256,
            )
        )
    encoded = json.dumps(sorted(rows), separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest() if rows else ""


class ArchivePreviewCacheMixin:
    """Archive preview cache identity, validation, and local cache helpers."""

    def _clear_archive_preview_cache(self, *, clear_native_packages: bool = False) -> None:
        self.archive_preview_cache.clear()
        self.archive_preview_cache_keys.clear()
        self.archive_preview_cache_last_miss_reason = ""
        self.archive_preview_cache_last_miss_detail = ""
        if clear_native_packages:
            clear_dotnet_preview_package_cache(self._native_preview_package_cache_root())
            clear_pac_xml_profile_index_cache(self.settings_file_path.parent)

    @staticmethod
    def _archive_preview_support_texture_slots(settings: object) -> Tuple[str, ...]:
        if bool(getattr(settings, "disable_all_support_maps", False)):
            return ()
        slots: List[str] = []
        if not bool(getattr(settings, "disable_normal_map", False)):
            slots.append("normal")
        if not bool(getattr(settings, "disable_material_map", False)):
            slots.append("material")
        if not bool(getattr(settings, "disable_height_map", False)):
            slots.append("height")
        slots.append("emissive")
        return tuple(slots)

    def _archive_preview_cache_key(
        self,
        entry: Optional[ArchiveEntry],
        loose_search_roots: Sequence[Path],
        *,
        include_loose_preview_assets: bool = False,
        sidecar_generation: Optional[int] = None,
        quality_tier: str = "full",
        dependency_entries: Sequence[ArchiveEntry] = (),
        enabled_prefab_component_paths: Optional[Sequence[str]] = None,
    ) -> str:
        if entry is None:
            return ""
        # Loose model/material dependencies are discovered while building the
        # preview.  Until that exact dependency set is available here, bypass
        # result caching so an edited overlay can never reuse stale geometry or
        # textures.
        if include_loose_preview_assets:
            return ""
        dependency_entries = tuple(dependency_entries)
        dependency_digest = _archive_preview_dependency_digest(dependency_entries)
        if dependency_entries and not dependency_digest:
            return ""
        effective_settings = getattr(self, "_archive_preview_effective_render_settings", None)
        preview_settings = (
            effective_settings(getattr(self, "archive_preview_request_id", 0))
            if callable(effective_settings)
            else self._current_model_preview_render_settings()
        )
        if enabled_prefab_component_paths is None:
            enabled_prefab_paths_getter = getattr(
                self,
                "_archive_d3d11_enabled_prefab_component_paths",
                None,
            )
            enabled_prefab_paths = (
                tuple(enabled_prefab_paths_getter(entry))
                if callable(enabled_prefab_paths_getter)
                else ()
            )
        else:
            enabled_prefab_paths = tuple(
                sorted(
                    str(path or "").replace("\\", "/").strip().casefold()
                    for path in enabled_prefab_component_paths
                    if str(path or "").strip()
                )
            )
        support_slots_key = ",".join(self._archive_preview_support_texture_slots(preview_settings))
        renderer_backend_key = str(self._archive_model_renderer_backend() or "").strip().lower()
        pamt_stamp = self._archive_file_stamp_for_cache(getattr(entry, "pamt_path", None))
        paz_stamp = self._archive_file_stamp_for_cache(getattr(entry, "paz_file", None))
        pathc_stamp = ""
        if str(getattr(entry, "extension", "") or "").strip().lower() == ".dds" and int(getattr(entry, "compression_type", 0) or 0) == 1:
            try:
                pathc_stamp = self._archive_file_stamp_for_cache(resolve_archive_pathc_path(entry))
            except Exception:
                pathc_stamp = "pathc:missing"
        key_parts = [
                entry.path.strip().lower(),
                str(entry.pamt_path).strip().lower(),
                pamt_stamp,
                str(entry.paz_file).strip().lower(),
                paz_stamp,
                pathc_stamp,
                f"quality:{'fast' if str(quality_tier or '').strip().lower() == 'fast' else 'full'}",
                str(entry.offset),
                str(entry.comp_size),
                str(entry.orig_size),
                str(entry.flags),
                str(entry.paz_index),
                f"renderer:{renderer_backend_key}",
                "texture:native-v2",
                f"sidecars:{self.archive_sidecar_generation if sidecar_generation is None else int(sidecar_generation)}",
                str(preview_settings.visible_texture_mode),
                f"texdim:{int(preview_settings.preview_texture_max_dimension)}",
                f"lodim:{int(preview_settings.low_quality_texture_max_dimension)}",
                f"support:{support_slots_key}",
                "flipv" if preview_settings.flip_texture_v else "noflipv",
                "hq" if preview_settings.high_quality_by_default else "lq",
                "tex" if preview_settings.use_textures_by_default else "flat",
                "archive",
                "prefabs:" + ",".join(enabled_prefab_paths),
            ]
        if dependency_digest:
            key_parts.append(f"dependencies:{dependency_digest}")
        return "::".join(key_parts)

    def _native_preview_package_cache_root(self) -> Path:
        return runtime_cache_layout(self.archive_cache_root).model_preview_root

    def _native_preview_core_cache_root(self) -> Path:
        return runtime_cache_layout(self.archive_cache_root).native_preview_root

    def _native_preview_package_cache_mode(self) -> str:
        return str(
            getattr(self._current_archive_performance_settings(), "native_preview_cache_mode", "balanced")
            or "balanced"
        ).strip().lower()

    def _native_preview_package_cache_budget(self) -> Tuple[int, int]:
        return dotnet_preview_package_cache_budget(self._native_preview_package_cache_mode())

    def _collect_archive_preview_loose_roots(self) -> List[Path]:
        roots: List[Path] = []
        seen: set[str] = set()
        for raw in (
            self.original_dds_edit.text().strip(),
            self.archive_extract_root_edit.text().strip(),
            self.output_root_edit.text().strip(),
        ):
            if not raw:
                continue
            try:
                path = Path(raw).expanduser().resolve()
            except OSError:
                continue
            lowered = str(path).lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            roots.append(path)
        return roots

    def _archive_entry_native_cache_signature(self, entry: Optional[ArchiveEntry]) -> Dict[str, object]:
        if entry is None:
            return {}
        return {
            "path": str(getattr(entry, "path", "") or "").replace("\\", "/").strip().lower(),
            "pamt_path": str(getattr(entry, "pamt_path", "") or "").strip().lower(),
            "pamt_stamp": self._archive_file_stamp_for_cache(getattr(entry, "pamt_path", None)),
            "paz_file": str(getattr(entry, "paz_file", "") or "").strip().lower(),
            "paz_stamp": self._archive_file_stamp_for_cache(getattr(entry, "paz_file", None)),
            "offset": int(getattr(entry, "offset", 0) or 0),
            "comp_size": int(getattr(entry, "comp_size", 0) or 0),
            "orig_size": int(getattr(entry, "orig_size", 0) or 0),
            "flags": int(getattr(entry, "flags", 0) or 0),
            "paz_index": int(getattr(entry, "paz_index", 0) or 0),
            "compression_type": int(getattr(entry, "compression_type", 0) or 0),
            "prepared_sha256": str(getattr(entry, "prepared_sha256", "") or "").strip().lower(),
        }

    def _archive_native_preview_package_cache_key(
        self,
        entry: Optional[ArchiveEntry],
        companion_entry: Optional[ArchiveEntry],
        loose_search_roots: Sequence[Path],
        *,
        include_loose_preview_assets: bool = False,
        dependency_entries: Sequence[ArchiveEntry] = (),
        enabled_prefab_component_paths: Optional[Sequence[str]] = None,
    ) -> str:
        if entry is None:
            return ""
        binary = find_native_preview_core_binary()
        binary_signature = NativePreviewCoreServiceClient.resolve_binary_signature(binary) if binary is not None else (0, 0)
        if enabled_prefab_component_paths is None:
            enabled_prefab_paths_getter = getattr(
                self,
                "_archive_d3d11_enabled_prefab_component_paths",
                None,
            )
            enabled_prefab_paths = (
                tuple(enabled_prefab_paths_getter(entry))
                if callable(enabled_prefab_paths_getter)
                else ()
            )
        else:
            enabled_prefab_paths = tuple(
                sorted(
                    str(path or "").replace("\\", "/").strip().casefold()
                    for path in enabled_prefab_component_paths
                    if str(path or "").strip()
                )
            )
        base_key = self._archive_preview_cache_key(
            entry,
            loose_search_roots,
            include_loose_preview_assets=include_loose_preview_assets,
            sidecar_generation=self.archive_sidecar_generation,
            quality_tier="full",
            dependency_entries=dependency_entries,
            enabled_prefab_component_paths=enabled_prefab_paths,
        )
        if not base_key:
            return ""
        dependency_digest = _archive_preview_dependency_digest(tuple(dependency_entries))
        payload = {
            "schema": DOTNET_PREVIEW_PACKAGE_CACHE_SCHEMA,
            "base_preview_key": base_key,
            "entry": self._archive_entry_native_cache_signature(entry),
            "companion": self._archive_entry_native_cache_signature(companion_entry),
            "dependency_digest": dependency_digest,
            "enabled_prefab_component_paths": enabled_prefab_paths,
            "render_settings": render_settings_to_native_preview_core_dict(self._current_model_preview_render_settings()),
            "support_slots": self._archive_preview_support_texture_slots(self._current_model_preview_render_settings()),
            "renderer_backend": str(self._archive_model_renderer_backend() or "").strip().lower(),
            "native_binary": {
                "path": str(binary or ""),
                "mtime_ns": int(binary_signature[0]),
                "size": int(binary_signature[1]),
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8", "replace")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _archive_file_stamp_for_cache(path_value: object) -> str:
        if path_value is None:
            return ""
        try:
            path = Path(path_value).expanduser()
            stat_result = path.stat()
            mtime_ns = int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000)))
            return f"{path.resolve()}:{int(stat_result.st_size)}:{mtime_ns}"
        except Exception:
            return f"{path_value}:missing"

    @staticmethod
    def _validate_d3d11_preview_package_paths(package_dir: Path) -> Tuple[bool, Tuple[str, ...]]:
        return validate_dotnet_preview_package(Path(package_dir))

    @staticmethod
    def _d3d11_preview_package_model_key(package_dir: Path) -> str:
        manifest_path = Path(package_dir) / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return ""
        if not isinstance(manifest, Mapping):
            return ""

        def _int_value(name: str, fallback: int) -> int:
            try:
                return int(manifest.get(name, fallback))
            except (TypeError, ValueError, OverflowError):
                return fallback

        identity = {
            "source_path": str(manifest.get("source_path", "") or "").replace("\\", "/").strip().lower(),
            "format": str(manifest.get("format", "") or "").strip().lower(),
            "mesh_count": _int_value("mesh_count", 0),
            "vertex_count": _int_value("vertex_count", 0),
            "face_count": _int_value("face_count", 0),
            "lod_index": _int_value("lod_index", -1),
            "lod_count": _int_value("lod_count", 0),
            "summary": str(manifest.get("summary", "") or "").replace("\\", "/").strip().lower(),
        }
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8", "replace")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _sanitize_d3d11_view_state_for_restore(state: object) -> Dict[str, object]:
        if not isinstance(state, Mapping):
            return {}
        source = state
        roles = state.get("roles")
        if isinstance(roles, Mapping):
            for role_name in ("replacement", "all", "reference"):
                candidate = roles.get(role_name)
                if isinstance(candidate, Mapping):
                    source = candidate
                    break

        def _float_value(name: str, fallback: float) -> float:
            try:
                return float(source.get(name, fallback))
            except (TypeError, ValueError, OverflowError):
                return fallback

        try:
            pan = tuple(float(value) for value in tuple(source.get("pan", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0))[:3])
        except (TypeError, ValueError, OverflowError):
            pan = (0.0, 0.0, 0.0)
        while len(pan) < 3:
            pan = (*pan, 0.0)
        zoom_factor = max(0.1, min(16.0, _float_value("zoom_factor", 1.0)))
        return {
            "role": "replacement",
            "reason": str(source.get("reason", "") or ""),
            "zoom_factor": zoom_factor,
            "fit_to_view": bool(source.get("fit_to_view", True)),
            "yaw": _float_value("yaw", -35.0),
            "pitch": max(-89.0, min(89.0, _float_value("pitch", 20.0))),
            "pan": (float(pan[0]), float(pan[1]), float(pan[2])),
        }

    def _clone_archive_preview_model(
        self,
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
                    for image_field in PREVIEW_MESH_IMAGE_FIELD_NAMES:
                        mesh_values[image_field] = None
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

    def _archive_preview_result_cacheable(self, result: ArchivePreviewResult) -> bool:
        dotnet_package_path = str(getattr(result, "dotnet_preview_package_path", "") or "").strip()
        if dotnet_package_path:
            if not is_durable_dotnet_preview_package_path(
                self._native_preview_package_cache_root() / "dotnet_vortice",
                dotnet_package_path,
            ):
                return False
            valid_package, _missing_paths = validate_dotnet_preview_package(Path(dotnet_package_path))
            return bool(valid_package)
        if getattr(result, "preview_model", None) is None:
            return True
        prepared_preview = getattr(result, "prepared_preview_model", None)
        if not isinstance(prepared_preview, PreparedModelPreviewData):
            return False
        total_vertex_bytes = self._archive_preview_result_prepared_bytes(result)
        total_index_count = sum(
            max(0, int(getattr(batch, "index_count", 0) or 0))
            for batch in getattr(prepared_preview, "batches", ()) or ()
        )
        return total_vertex_bytes <= 24 * 1024 * 1024 and total_index_count <= 350_000

    def _clone_archive_preview_result_for_cache(
        self,
        result: ArchivePreviewResult,
        *,
        keep_prepared_model: bool = False,
    ) -> ArchivePreviewResult:
        return dataclasses.replace(
            result,
            preview_image=None,
            loose_preview_image=None,
            preview_model=self._clone_archive_preview_model(result.preview_model, strip_images=True),
            prepared_preview_model=(
                getattr(result, "prepared_preview_model", None)
                if keep_prepared_model
                else None
            ),
        )

    def _load_preview_image_if_available(self, image_path: str) -> object:
        normalized_path = str(image_path or "").strip()
        if not normalized_path:
            return None
        reader = QImageReader(normalized_path)
        image = reader.read()
        if image.isNull():
            return None
        return image

    def _attach_archive_preview_result_images(self, result: ArchivePreviewResult) -> ArchivePreviewResult:
        preview_model = self._clone_archive_preview_model(result.preview_model, strip_images=False)
        loaded_images: Dict[str, object] = {}

        def load_image_cached(path: str) -> object:
            normalized_path = str(path or "").strip()
            if not normalized_path:
                return None
            if normalized_path not in loaded_images:
                loaded_images[normalized_path] = self._load_preview_image_if_available(normalized_path)
            return loaded_images[normalized_path]

        preview_image = result.preview_image
        if preview_image is None and result.preview_image_path:
            preview_image = load_image_cached(result.preview_image_path)
        loose_preview_image = result.loose_preview_image
        if loose_preview_image is None and result.loose_preview_image_path:
            loose_preview_image = load_image_cached(result.loose_preview_image_path)
        if not isinstance(getattr(result, "prepared_preview_model", None), PreparedModelPreviewData):
            meshes = getattr(preview_model, "meshes", None) or []
            for mesh in meshes:
                texture_slots = (
                    ("preview_texture_path", "preview_texture_image"),
                    ("preview_normal_texture_path", "preview_normal_texture_image"),
                    ("preview_material_texture_path", "preview_material_texture_image"),
                    ("preview_height_texture_path", "preview_height_texture_image"),
                )
                for path_attr, image_attr in texture_slots:
                    preview_texture_path = str(getattr(mesh, path_attr, "") or "").strip()
                    if not preview_texture_path or getattr(mesh, image_attr, None) is not None:
                        continue
                    texture_image = load_image_cached(preview_texture_path)
                    if texture_image is not None:
                        setattr(mesh, image_attr, texture_image)
        return dataclasses.replace(
            result,
            preview_image=preview_image,
            loose_preview_image=loose_preview_image,
            preview_model=preview_model,
        )

    def _archive_preview_result_prepared_bytes(self, result: ArchivePreviewResult) -> int:
        prepared_preview = getattr(result, "prepared_preview_model", None)
        if not isinstance(prepared_preview, PreparedModelPreviewData):
            return 0
        return sum(
            len(getattr(batch, "vertex_blob", b"") or b"")
            for batch in getattr(prepared_preview, "batches", ()) or ()
        )

    def _get_cached_archive_preview_result(self, cache_key: str) -> Optional[ArchivePreviewResult]:
        self.archive_preview_cache_last_miss_reason = ""
        self.archive_preview_cache_last_miss_detail = ""
        if not cache_key:
            return None
        cached = self.archive_preview_cache.get(cache_key)
        if cached is None:
            return None
        dotnet_package_path = str(getattr(cached, "dotnet_preview_package_path", "") or "").strip()
        if dotnet_package_path:
            package_dir = Path(dotnet_package_path)
            valid_package, missing_paths = validate_dotnet_preview_package(package_dir)
            if not valid_package:
                self.archive_preview_cache.pop(cache_key, None)
                detail = "; ".join(missing_paths[:4])
                self.archive_preview_cache_last_miss_reason = "dotnet_package_expired"
                self.archive_preview_cache_last_miss_detail = detail
                selected_entry = self._current_archive_entry()
                self._record_runtime_event(
                    "archive_preview_cache_dotnet_package_expired",
                    request_id=self.archive_preview_request_id,
                    selected_path=getattr(selected_entry, "path", ""),
                    cache_key=cache_key,
                    package_path=dotnet_package_path,
                    missing=list(missing_paths[:12]),
                )
                return None
        self.archive_preview_cache.move_to_end(cache_key)
        return self._attach_archive_preview_result_images(cached)

    def _store_cached_archive_preview_result(self, cache_key: str, result: ArchivePreviewResult) -> None:
        if not cache_key:
            return
        if not self._archive_preview_result_cacheable(result):
            return
        keep_prepared_model = (
            getattr(result, "preview_model", None) is not None
            and isinstance(getattr(result, "prepared_preview_model", None), PreparedModelPreviewData)
        )
        self.archive_preview_cache[cache_key] = self._clone_archive_preview_result_for_cache(
            result,
            keep_prepared_model=keep_prepared_model,
        )
        self.archive_preview_cache.move_to_end(cache_key)
        self._trim_archive_preview_cache()

    def _strip_archive_preview_heavy_payloads_for_mesh_editor(self, entry: Optional[ArchiveEntry]) -> None:
        stripped_entries = 0
        reclaimed_prepared_bytes = 0
        for cache_key, cached_result in list(self.archive_preview_cache.items()):
            if not isinstance(cached_result, ArchivePreviewResult):
                continue
            reclaimed_prepared_bytes += self._archive_preview_result_prepared_bytes(cached_result)
            self.archive_preview_cache[cache_key] = self._clone_archive_preview_result_for_cache(
                cached_result,
                keep_prepared_model=False,
            )
            stripped_entries += 1
        current_result = getattr(self, "current_archive_preview_result", None)
        current_prepared_bytes = (
            self._archive_preview_result_prepared_bytes(current_result)
            if isinstance(current_result, ArchivePreviewResult)
            else 0
        )
        if isinstance(current_result, ArchivePreviewResult):
            self.current_archive_preview_result = self._clone_archive_preview_result_for_cache(
                current_result,
                keep_prepared_model=False,
            )
        current_entry = self._current_archive_entry()
        same_current_entry = bool(
            entry is not None
            and current_entry is not None
            and self._same_archive_entry(current_entry, entry)
        )
        if same_current_entry and self._archive_model_renderer_backend() == ARCHIVE_MODEL_RENDERER_D3D11:
            try:
                self._shutdown_archive_isolated_renderer_host()
            except Exception as exc:
                self._record_runtime_event(
                    "mesh_editor_archive_preview_pause_failed",
                    path=str(getattr(entry, "path", "") or ""),
                    message=str(exc),
                )
        self._record_runtime_event(
            "mesh_editor_archive_preview_payloads_stripped",
            path=str(getattr(entry, "path", "") or ""),
            same_current_entry=same_current_entry,
            stripped_cache_entries=stripped_entries,
            reclaimed_prepared_bytes=reclaimed_prepared_bytes + current_prepared_bytes,
        )

    def _trim_archive_preview_cache(self) -> None:
        while len(self.archive_preview_cache) > self.archive_preview_cache_limit:
            self.archive_preview_cache.popitem(last=False)
        prepared_byte_budget = 160 * 1024 * 1024
        total_prepared_bytes = sum(
            self._archive_preview_result_prepared_bytes(cached_result)
            for cached_result in self.archive_preview_cache.values()
        )
        if total_prepared_bytes <= prepared_byte_budget:
            return
        for existing_key in list(self.archive_preview_cache.keys()):
            if total_prepared_bytes <= prepared_byte_budget:
                break
            cached_result = self.archive_preview_cache.get(existing_key)
            prepared_bytes = self._archive_preview_result_prepared_bytes(cached_result) if cached_result is not None else 0
            if prepared_bytes <= 0:
                continue
            self.archive_preview_cache.pop(existing_key, None)
            total_prepared_bytes -= prepared_bytes

__all__ = ["ArchivePreviewCacheMixin"]
