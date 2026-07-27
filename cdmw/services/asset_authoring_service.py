from __future__ import annotations

import json
import importlib.util
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from cdmw.modding.mesh_native_core import find_native_mesh_core_binary
from cdmw.services.bundled_helper_availability import bundled_helper_path
from cdmw.services.process_job_service import breakaway_creation_flags


ASSET_AUTHORING_DISCOVERY_SCHEMA = "cdmw_asset_authoring_discovery_v1"
ASSET_AUTHORING_TEXTURE_SET_SCHEMA = "cdmw_asset_authoring_texture_set_v1"
ASSET_AUTHORING_SCENE_IMPORT_SCHEMA = "cdmw_asset_authoring_scene_import_v1"
ASSET_AUTHORING_MESH_HEALTH_SCHEMA = "cdmw_asset_authoring_mesh_health_v1"
ASSET_AUTHORING_MESH_OPTIMIZATION_SCHEMA = "cdmw_asset_authoring_mesh_optimization_v1"
ASSET_AUTHORING_SOURCE_IMAGE_SCHEMA = "cdmw_asset_authoring_source_image_v1"
ASSET_AUTHORING_UV_REPORT_SCHEMA = "cdmw_asset_authoring_uv_report_v1"
ASSET_AUTHORING_TANGENT_REPORT_SCHEMA = "cdmw_asset_authoring_tangent_report_v1"
MATERIAL_MAKER_EXPORT_TEMPLATE_SETTING = "asset_authoring/material_maker_export_template"
MATERIAL_MAKER_EXPORT_TEMPLATE_ENV = "CDMW_MATERIAL_MAKER_EXPORT_TEMPLATE"

_SOURCE_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".exr", ".psd", ".bmp", ".webp"})
_OPENIMAGEIO_SOURCE_SUFFIXES = frozenset({".psd", ".tga", ".exr", ".tif", ".tiff", ".ptx", ".ptex"})
_EXISTING_IMAGE_WORKFLOW_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".dds"})
_CHANNEL_ALIASES = {
    "base_color": frozenset({"basecolor", "basecolour", "albedo", "diffuse", "base"}),
    "normal": frozenset({"normal", "normals", "nrm"}),
    "roughness": frozenset({"roughness", "rough"}),
    "metallic": frozenset({"metallic", "metalness", "metal"}),
    "ao": frozenset({"ao", "ambientocclusion", "occlusion"}),
    "height": frozenset({"height", "displacement", "disp", "bump"}),
    "mask": frozenset({"mask", "masks", "orm", "rma", "mra", "arm", "packedmask", "materialmask"}),
    "recolor": frozenset({"recolor", "recolour", "recolorvariant", "recolourvariant", "tint", "colormask", "colourmask"}),
}
_CHANNEL_SEMANTICS = {
    "base_color": ("color", "albedo", "color_default", "srgb"),
    "normal": ("normal", "normal", "normal_bc5", "linear"),
    "roughness": ("roughness", "roughness", "scalar_high_precision_bc4", "linear"),
    "metallic": ("mask", "metallic", "scalar_high_precision_bc4", "linear"),
    "ao": ("mask", "ao", "scalar_high_precision_bc4", "linear"),
    "height": ("height", "height", "scalar_high_precision_bc4", "linear"),
    "mask": ("mask", "mask", "packed_mask_preserve_layout", "linear"),
    "recolor": ("mask", "recolor_variant", "packed_mask_preserve_layout", "linear"),
}
_CDMW_MESH_CORE_BACKEND_LABELS = {
    "xatlas": "bundled in CDMW Mesh Core",
    "ufbx": "bundled in CDMW Mesh Core",
    "meshoptimizer": "bundled in CDMW Mesh Core",
}


@dataclass(frozen=True, slots=True)
class AssetAuthoringHelperSpec:
    key: str
    label: str
    role: str
    setting_key: str
    env_key: str
    executables: tuple[str, ...] = ()
    module: str = ""
    capabilities: tuple[str, ...] = ()
    bundled: bool = False
    package_safe: bool = False


_HELPERS = (
    AssetAuthoringHelperSpec(
        key="cdmw_mesh_core",
        label="CDMW Mesh Core",
        role="native mesh edit helper",
        setting_key="",
        env_key="CDMW_MESH_CORE_BIN",
        capabilities=(
            "transform-json",
            "uv-transform-json",
            "auto-uv-json",
            "recalculate-normals-json",
            "generate-tangents-json",
            "mikktspace-tangents",
            "cleanup-json",
            "edit-json",
            "optimize-json",
            "meshoptimizer-optimize",
            "meshoptimizer-simplify",
            "import-scene-json",
            "ufbx-fbx-import",
        ),
        bundled=True,
        package_safe=True,
    ),
    AssetAuthoringHelperSpec(
        key="xatlas",
        label="xatlas",
        role="optional external xatlas CLI comparator; bundled backend lives in cdmw_mesh_core",
        setting_key="asset_authoring/xatlas_path",
        env_key="CDMW_XATLAS_BIN",
        executables=("xatlas", "xatlas-cli"),
        capabilities=("auto_uv", "uv_atlas_report"),
        package_safe=False,
    ),
    AssetAuthoringHelperSpec(
        key="material_maker",
        label="Material Maker",
        role="external material graph handoff/export",
        setting_key="asset_authoring/material_maker_path",
        env_key="CDMW_MATERIAL_MAKER_BIN",
        executables=("material_maker", "Material Maker"),
        capabilities=("open_project", "export_texture_set"),
        package_safe=False,
    ),
    AssetAuthoringHelperSpec(
        key="ufbx",
        label="ufbx",
        role="future FBX/OBJ import bridge",
        setting_key="asset_authoring/ufbx_path",
        env_key="CDMW_UFBX_BIN",
        executables=("ufbx",),
        module="ufbx",
        capabilities=("import_fbx", "import_obj", "scene_report"),
        package_safe=False,
    ),
    AssetAuthoringHelperSpec(
        key="meshoptimizer",
        label="meshoptimizer",
        role="optional external simplification/optimization comparator; bundled backend lives in cdmw_mesh_core",
        setting_key="asset_authoring/meshoptimizer_path",
        env_key="CDMW_MESHOPTIMIZER_BIN",
        executables=("meshoptimizer", "gltfpack"),
        capabilities=("simplify", "optimize_vertices", "optimize_indices"),
        package_safe=False,
    ),
    AssetAuthoringHelperSpec(
        key="openimageio",
        label="OpenImageIO",
        role="bundled source image ingest/diff helper",
        setting_key="asset_authoring/oiio_path",
        env_key="CDMW_OIIO_BIN",
        executables=("oiiotool",),
        module="OpenImageIO",
        capabilities=("read_source_images", "convert_intermediate", "image_diff", "metadata"),
        bundled=True,
        package_safe=True,
    ),
)


@dataclass(slots=True)
class AssetAuthoringService:
    settings: object | None = None

    def discovery_report(
        self,
        configured_paths: Mapping[str, object] | None = None,
        *,
        include_versions: bool = False,
        version_timeout_s: float = 2.0,
    ) -> dict[str, object]:
        paths = configured_paths if isinstance(configured_paths, Mapping) else {}
        helpers = {
            spec.key: _helper_report(
                spec,
                self.settings,
                paths,
                include_version=include_versions,
                version_timeout_s=version_timeout_s,
            )
            for spec in _HELPERS
        }
        return {
            "schema": ASSET_AUTHORING_DISCOVERY_SCHEMA,
            "status": "ok",
            "policy": "Optional authoring helpers are unavailable unless detected; CDMW remains DDS/package authority.",
            "helpers": helpers,
            "fixtures": asset_authoring_fixture_manifest(),
        }

    def material_maker_project_command(
        self,
        project_path: Path | str,
        configured_paths: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        helper = _helper_report(_helper_spec("material_maker"), self.settings, _configured_mapping(configured_paths))
        if helper["status"] != "available":
            return {
                "status": helper["status"],
                "helper": helper,
                "argv": [],
                "can_launch": False,
                "message": "Material Maker executable is not configured or detected.",
            }
        project = Path(project_path).expanduser()
        return {
            "status": "ready",
            "helper": helper,
            "project_path": str(project),
            "argv": [str(helper["path"]), str(project)],
            "can_launch": True,
        }

    def open_material_maker_project(
        self,
        project_path: Path | str,
        configured_paths: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        command = self.material_maker_project_command(project_path, configured_paths)
        if not command.get("can_launch"):
            return command
        # An external editor the user works in directly, so it breaks out of
        # the kill-on-close job rather than dying with the workbench.
        process = subprocess.Popen(
            tuple(str(part) for part in command["argv"]),
            cwd=str(Path(project_path).expanduser().parent),
            creationflags=breakaway_creation_flags(),
        )
        return {**command, "status": "launched", "pid": process.pid}

    def material_maker_export_command(
        self,
        project_path: Path | str,
        output_dir: Path | str,
        configured_paths: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        paths = _configured_mapping(configured_paths)
        helper = _helper_report(_helper_spec("material_maker"), self.settings, paths)
        if helper["status"] != "available":
            return {
                "status": helper["status"],
                "helper": helper,
                "argv": [],
                "can_run": False,
                "message": "Material Maker executable is not configured or detected.",
            }
        template = _configured_text(
            "material_maker_export_template",
            MATERIAL_MAKER_EXPORT_TEMPLATE_SETTING,
            MATERIAL_MAKER_EXPORT_TEMPLATE_ENV,
            self.settings,
            paths,
        )
        if not template:
            return {
                "status": "cli_export_unconfigured",
                "helper": helper,
                "argv": [],
                "can_run": False,
                "message": f"Configure {MATERIAL_MAKER_EXPORT_TEMPLATE_SETTING} before running Material Maker export.",
            }
        project = Path(project_path).expanduser()
        output = Path(output_dir).expanduser()
        replacements = {"exe": str(helper["path"]), "project": str(project), "output": str(output)}
        return {
            "status": "ready",
            "helper": helper,
            "project_path": str(project),
            "output_dir": str(output),
            "argv": _argv_from_template(template, replacements),
            "can_run": True,
        }

    def run_material_maker_export(
        self,
        project_path: Path | str,
        output_dir: Path | str,
        configured_paths: Mapping[str, object] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, object]:
        command = self.material_maker_export_command(project_path, output_dir, configured_paths)
        if not command.get("can_run"):
            return command
        Path(output_dir).expanduser().mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            tuple(str(part) for part in command["argv"]),
            cwd=str(Path(output_dir).expanduser()),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return {
            **command,
            "status": "ok" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    def ingest_exported_texture_set(
        self,
        export_dir: Path | str,
        *,
        material_name: str = "",
        channel_overrides: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        root = Path(export_dir).expanduser()
        if not root.is_dir():
            return {
                "schema": ASSET_AUTHORING_TEXTURE_SET_SCHEMA,
                "status": "missing_export_dir",
                "export_dir": str(root),
                "material_name": str(material_name or root.name),
                "channels": {},
                "unmapped": [],
                "warnings": [f"Export folder does not exist: {root}"],
                "dds_authority": "cdmw_directxtex",
            }

        overrides = _normalized_channel_overrides(channel_overrides)
        channels: dict[str, dict[str, object]] = {}
        unmapped: list[str] = []
        warnings: list[str] = []
        for path in sorted(root.iterdir(), key=lambda candidate: candidate.name.lower()):
            if not path.is_file() or path.suffix.lower() not in _SOURCE_IMAGE_SUFFIXES:
                continue
            channel = _texture_channel_for_path(path, overrides)
            if not channel:
                unmapped.append(str(path))
                continue
            if channel in channels:
                warnings.append(f"Duplicate {channel} map skipped: {path.name}")
                continue
            texture_type, semantic_subtype, profile_hint, colorspace = _CHANNEL_SEMANTICS[channel]
            channels[channel] = {
                "channel": channel,
                "path": str(path),
                "source_role": "review_intermediate",
                "texture_type": texture_type,
                "semantic_subtype": semantic_subtype,
                "profile_hint": profile_hint,
                "colorspace": colorspace,
                "dds_authority": "cdmw_directxtex",
            }

        status = "ok" if channels else "empty"
        return {
            "schema": ASSET_AUTHORING_TEXTURE_SET_SCHEMA,
            "status": status,
            "export_dir": str(root),
            "material_name": str(material_name or root.name),
            "channels": channels,
            "unmapped": unmapped,
            "warnings": warnings,
            "dds_authority": "cdmw_directxtex",
            "policy": "Source maps are review intermediates; DDS output remains owned by CDMW/DirectXTex.",
        }

    def scene_import_report(
        self,
        source_path: Path | str,
        configured_paths: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        source = Path(source_path).expanduser()
        suffix = source.suffix.lower()
        if suffix == ".fbx":
            helper = _helper_report(_helper_spec("cdmw_mesh_core"), self.settings, _configured_mapping(configured_paths))
            try:
                from cdmw.modding.mesh_native_core import native_scene_import_report

                native_report = native_scene_import_report(source)
            except Exception as exc:
                native_report = None
                native_error = str(exc)
            else:
                native_error = ""
            if isinstance(native_report, Mapping) and str(native_report.get("status") or "").lower() == "ok":
                return {
                    "schema": ASSET_AUTHORING_SCENE_IMPORT_SCHEMA,
                    "status": "ok",
                    "source_path": str(source),
                    "source_format": "fbx",
                    "backend": "ufbx",
                    "helper": helper,
                    "native_import": native_report,
                    "crimson_compatibility": "unmapped",
                    "mesh": dict(native_report.get("mesh") or {}),
                    "materials": _ufbx_material_hints(native_report),
                    "texture_hints": _ufbx_texture_hints(native_report),
                    "skeleton_hints": dict(native_report.get("skeleton_hints") or {}),
                    "unsupported": list(tuple(native_report.get("unsupported") or ())),
                    "diagnostics": list(tuple(native_report.get("diagnostics") or ())),
                    "policy": "FBX imports are source data until mapped to a known Crimson target asset.",
                }
            return {
                "schema": ASSET_AUTHORING_SCENE_IMPORT_SCHEMA,
                "status": "unsupported",
                "source_path": str(source),
                "source_format": "fbx",
                "backend": "ufbx_unavailable",
                "helper": helper,
                "crimson_compatibility": "unmapped",
                "mesh": {},
                "materials": [],
                "texture_hints": [],
                "skeleton_hints": {
                    "has_skinning": False,
                    "rig_status": "fbx_import_backend_unavailable",
                    "animation_status": "fbx_import_backend_unavailable",
                },
                "unsupported": ["fbx_mesh_import_unavailable", "fbx_skeleton_import_unavailable", "fbx_animation_import_unavailable"],
                "diagnostics": [native_error or "FBX import needs the bundled cdmw_mesh_core ufbx bridge to be built and available."],
            }
        try:
            from cdmw.modding.scene_importer import import_scene_mesh_with_report

            result = import_scene_mesh_with_report(source, include_external_audit=True)
        except Exception as exc:
            return {
                "schema": ASSET_AUTHORING_SCENE_IMPORT_SCHEMA,
                "status": "failed",
                "source_path": str(source),
                "source_format": suffix.lstrip(".") or "unknown",
                "backend": "cdmw_scene_importer",
                "crimson_compatibility": "unmapped",
                "error": str(exc),
                "mesh": {},
                "materials": [],
                "texture_hints": [],
                "skeleton_hints": {},
                "unsupported": [],
                "diagnostics": [str(exc)],
            }

        mesh = result.mesh
        return {
            "schema": ASSET_AUTHORING_SCENE_IMPORT_SCHEMA,
            "status": "ok",
            "source_path": str(source),
            "source_format": str(getattr(mesh, "format", "") or suffix.lstrip(".") or "unknown"),
            "backend": "cdmw_scene_importer",
            "crimson_compatibility": "unmapped",
            "mesh": _scene_mesh_summary(mesh),
            "materials": _scene_material_hints(result),
            "texture_hints": _scene_texture_hints(result),
            "skeleton_hints": _scene_skeleton_hints(result),
            "unsupported": _scene_unsupported_hints(result),
            "diagnostics": list(tuple(getattr(result, "diagnostics", ()) or ())),
            "policy": "Scene imports are source data until mapped to a known Crimson target asset.",
        }

    def mesh_health_report(
        self,
        mesh: object,
        *,
        original_mesh: object | None = None,
        duplicate_epsilon: float = 1e-6,
    ) -> dict[str, object]:
        parts = [
            _mesh_health_part(index, submesh, duplicate_epsilon)
            for index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ()))
        ]
        totals = _mesh_health_totals(parts)
        topology = _mesh_topology_delta(original_mesh, mesh) if original_mesh is not None else {"available": False}
        warnings = _mesh_health_warnings(totals, topology)
        return {
            "schema": ASSET_AUTHORING_MESH_HEALTH_SCHEMA,
            "status": "issues_found" if warnings else "ok",
            "mutates": False,
            "parts": parts,
            "totals": totals,
            "topology": topology,
            "warnings": warnings,
            "policy": "Mesh health reports are preflight-only; cleanup must be applied through undoable mesh edit operations.",
        }

    def mesh_optimization_report(
        self,
        mesh: object,
        *,
        original_mesh: object | None = None,
        simplify_ratio: float = 1.0,
        target_error: float = 0.01,
    ) -> dict[str, object]:
        ratio = _bounded_float(simplify_ratio, 1.0, 0.0, 1.0)
        error = _bounded_float(target_error, 0.01, 0.0, 1.0)
        native = _native_mesh_optimization_report(mesh, ratio, error)
        topology = _mesh_topology_delta(original_mesh, mesh) if original_mesh is not None else {"available": False}
        warnings = _mesh_optimization_warnings(native, topology, ratio)
        native_ok = native.get("status") == "ok"
        return {
            "schema": ASSET_AUTHORING_MESH_OPTIMIZATION_SCHEMA,
            "status": "issues_found" if native_ok and warnings else ("ok" if native_ok else "unavailable"),
            "mutates": False,
            "simplification": {
                "opt_in": ratio < 1.0,
                "target_ratio": ratio,
                "target_error": error,
            },
            "native_optimization": native,
            "topology": topology,
            "warnings": warnings,
            "policy": "Mesh optimization reports are preflight-only; simplification is opt-in and package output stays conservative for unsafe topology changes.",
        }

    def uv_authoring_report(
        self,
        mesh: object,
        *,
        original_mesh: object | None = None,
        selection: object | None = None,
        atlas_size: tuple[int, int] = (0, 0),
        include_native_unwrap: bool = False,
    ) -> dict[str, object]:
        from cdmw.domain.mesh import summarize_mesh_uvs

        summary = summarize_mesh_uvs(mesh, selection)  # type: ignore[arg-type]
        islands = [_uv_island_report(island) for island in tuple(summary.islands or ())]
        missing_parts = _uv_missing_parts(mesh)
        topology = _mesh_topology_delta(original_mesh, mesh) if original_mesh is not None else {"available": False}
        warnings = _uv_authoring_warnings(islands, missing_parts, topology)
        native_unwrap = _native_auto_uv_report(mesh, atlas_size) if include_native_unwrap else None
        return {
            "schema": ASSET_AUTHORING_UV_REPORT_SCHEMA,
            "status": "issues_found" if warnings else "ok",
            "mutates": False,
            "island_count": int(summary.island_count),
            "selected_island_count": int(summary.selected_island_count),
            "atlas_size": (int(atlas_size[0]), int(atlas_size[1])),
            "uv_bounds": _uv_bounds(islands),
            "islands": islands,
            "missing_uv_parts": missing_parts,
            "topology": topology,
            "native_unwrap": native_unwrap,
            "warnings": warnings,
            "policy": "UV authoring reports describe current editable data; xatlas unwrap reports topology deltas before any edit applies output.",
        }

    def tangent_authoring_report(
        self,
        mesh: object,
        *,
        original_mesh: object | None = None,
    ) -> dict[str, object]:
        submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
        parts = [_tangent_authoring_part(index, submesh) for index, submesh in enumerate(submeshes)]
        totals = _tangent_authoring_totals(parts)
        topology = (
            _mesh_topology_delta(original_mesh, mesh)
            if original_mesh is not None
            else {"available": False}
        )
        warnings = _tangent_authoring_warnings(totals, topology)
        return {
            "schema": ASSET_AUTHORING_TANGENT_REPORT_SCHEMA,
            "status": "issues_found" if warnings else "ok",
            "mutates": False,
            "parts": parts,
            "totals": totals,
            "topology": topology,
            "warnings": warnings,
            "policy": "Tangents are generated through undoable mesh edit commands; reports never mutate archives directly.",
        }

    def openimageio_source_report(
        self,
        source_path: Path | str,
        configured_paths: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        source = Path(source_path).expanduser()
        helper = _helper_report(_helper_spec("openimageio"), self.settings, _configured_mapping(configured_paths))
        suffix = source.suffix.lower()
        helper_ready = helper["status"] == "available" and bool(str(helper.get("path", "") or "").strip())
        existing_workflow = suffix in _EXISTING_IMAGE_WORKFLOW_SUFFIXES
        return {
            "schema": ASSET_AUTHORING_SOURCE_IMAGE_SCHEMA,
            "status": "ready" if helper_ready and source.is_file() else ("missing_source" if not source.is_file() else "helper_unavailable"),
            "source_path": str(source),
            "source_format": suffix.lstrip(".") or "unknown",
            "helper": helper,
            "openimageio_source_candidate": suffix in _OPENIMAGEIO_SOURCE_SUFFIXES,
            "existing_workflow_unaffected": existing_workflow,
            "can_read_metadata": bool(helper_ready and source.is_file()),
            "can_convert": bool(helper_ready and source.is_file()),
            "can_diff": bool(helper_ready),
            "metadata_argv": _openimageio_info_argv(helper, source) if helper_ready and source.is_file() else [],
            "policy": "OpenImageIO is optional source tooling; final DDS output remains owned by CDMW/DirectXTex.",
        }

    def openimageio_metadata_command(
        self,
        source_path: Path | str,
        configured_paths: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        helper = _helper_report(_helper_spec("openimageio"), self.settings, _configured_mapping(configured_paths))
        source = Path(source_path).expanduser()
        if helper["status"] != "available" or not str(helper.get("path", "") or "").strip():
            return {
                "status": "helper_unavailable",
                "helper": helper,
                "source_path": str(source),
                "argv": [],
                "can_run": False,
                "message": "OpenImageIO oiiotool is not configured or detected.",
            }
        if not source.is_file():
            return {
                "status": "missing_source",
                "helper": helper,
                "source_path": str(source),
                "argv": [],
                "can_run": False,
                "message": f"Source image does not exist: {source}",
            }
        return {
            "status": "ready",
            "helper": helper,
            "source_path": str(source),
            "argv": _openimageio_info_argv(helper, source),
            "can_run": True,
        }

    def run_openimageio_metadata(
        self,
        source_path: Path | str,
        configured_paths: Mapping[str, object] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, object]:
        command = self.openimageio_metadata_command(source_path, configured_paths)
        if not command.get("can_run"):
            return command
        completed = subprocess.run(
            tuple(str(part) for part in command["argv"]),
            cwd=str(Path(source_path).expanduser().parent),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return {
            **command,
            "status": "ok" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "metadata": _openimageio_metadata_from_output(completed.stdout, completed.stderr),
        }

    def openimageio_convert_command(
        self,
        source_path: Path | str,
        output_path: Path | str,
        configured_paths: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        helper = _helper_report(_helper_spec("openimageio"), self.settings, _configured_mapping(configured_paths))
        source = Path(source_path).expanduser()
        output = Path(output_path).expanduser()
        if helper["status"] != "available" or not str(helper.get("path", "") or "").strip():
            return {
                "status": "helper_unavailable",
                "helper": helper,
                "argv": [],
                "can_run": False,
                "message": "OpenImageIO oiiotool is not configured or detected.",
            }
        if not source.is_file():
            return {
                "status": "missing_source",
                "helper": helper,
                "source_path": str(source),
                "output_path": str(output),
                "argv": [],
                "can_run": False,
                "message": f"Source image does not exist: {source}",
            }
        return {
            "status": "ready",
            "helper": helper,
            "source_path": str(source),
            "output_path": str(output),
            "argv": [str(helper["path"]), str(source), "-o", str(output)],
            "can_run": True,
        }

    def run_openimageio_convert(
        self,
        source_path: Path | str,
        output_path: Path | str,
        configured_paths: Mapping[str, object] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, object]:
        command = self.openimageio_convert_command(source_path, output_path, configured_paths)
        if not command.get("can_run"):
            return command
        Path(output_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            tuple(str(part) for part in command["argv"]),
            cwd=str(Path(output_path).expanduser().parent),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return {
            **command,
            "status": "ok" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    def openimageio_diff_command(
        self,
        left_path: Path | str,
        right_path: Path | str,
        configured_paths: Mapping[str, object] | None = None,
        *,
        fail_threshold: float | None = None,
        fail_percent: float | None = None,
        hard_fail_threshold: float | None = None,
        difference_output_path: Path | str | None = None,
        difference_scale: float = 1.0,
    ) -> dict[str, object]:
        helper = _helper_report(_helper_spec("openimageio"), self.settings, _configured_mapping(configured_paths))
        left = Path(left_path).expanduser()
        right = Path(right_path).expanduser()
        difference_output = Path(difference_output_path).expanduser() if difference_output_path is not None else None
        missing = [str(path) for path in (left, right) if not path.is_file()]
        if helper["status"] != "available" or not str(helper.get("path", "") or "").strip():
            return {
                "status": "helper_unavailable",
                "helper": helper,
                "argv": [],
                "can_run": False,
                "message": "OpenImageIO oiiotool is not configured or detected.",
            }
        if missing:
            return {
                "status": "missing_source",
                "helper": helper,
                "left_path": str(left),
                "right_path": str(right),
                "missing": missing,
                "argv": [],
                "can_run": False,
            }
        thresholds = _openimageio_diff_thresholds(
            fail_threshold=fail_threshold,
            fail_percent=fail_percent,
            hard_fail_threshold=hard_fail_threshold,
        )
        argv = [str(helper["path"]), str(left), str(right)]
        if thresholds["fail_threshold"] is not None:
            argv.extend(("--fail", _openimageio_number(thresholds["fail_threshold"])))
        if thresholds["fail_percent"] is not None:
            argv.extend(("--failpercent", _openimageio_number(thresholds["fail_percent"])))
        if thresholds["hard_fail_threshold"] is not None:
            argv.extend(("--hardfail", _openimageio_number(thresholds["hard_fail_threshold"])))
        argv.append("--diff")
        if difference_output is not None:
            argv.append("--absdiff")
            if difference_scale != 1.0:
                argv.extend(("--mulc", _openimageio_number(difference_scale)))
            argv.extend(("--ch", "R,G,B"))
            argv.extend(("-o", str(difference_output)))
        return {
            "status": "ready",
            "helper": helper,
            "left_path": str(left),
            "right_path": str(right),
            "difference_output_path": str(difference_output) if difference_output is not None else "",
            "difference_scale": float(difference_scale),
            "thresholds": thresholds,
            "argv": argv,
            "can_run": True,
        }

    def run_openimageio_diff(
        self,
        left_path: Path | str,
        right_path: Path | str,
        configured_paths: Mapping[str, object] | None = None,
        timeout_s: float | None = None,
        *,
        fail_threshold: float | None = None,
        fail_percent: float | None = None,
        hard_fail_threshold: float | None = None,
        difference_output_path: Path | str | None = None,
        difference_scale: float = 1.0,
    ) -> dict[str, object]:
        command = self.openimageio_diff_command(
            left_path,
            right_path,
            configured_paths,
            fail_threshold=fail_threshold,
            fail_percent=fail_percent,
            hard_fail_threshold=hard_fail_threshold,
            difference_output_path=difference_output_path,
            difference_scale=difference_scale,
        )
        if not command.get("can_run"):
            return command
        output_text = str(command.get("difference_output_path", "") or "").strip()
        if output_text:
            Path(output_text).parent.mkdir(parents=True, exist_ok=True)
        try:
            completed = subprocess.run(
                tuple(str(part) for part in command["argv"]),
                cwd=str(Path(left_path).expanduser().parent),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                **command,
                "status": "failed",
                "returncode": None,
                "stdout": "",
                "stderr": str(exc),
                "metrics": {},
                "difference_output_written": False,
            }
        metrics = _openimageio_diff_metrics(completed.stdout, completed.stderr)
        metric_result = str(metrics.get("result", "") or "")
        if completed.returncode == 0:
            status = "ok"
        elif metric_result == "warning":
            status = "ok"
        elif metric_result == "failure":
            status = "different"
        else:
            status = "failed"
        return {
            **command,
            "status": status,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "metrics": metrics,
            "difference_output_written": bool(output_text and Path(output_text).is_file()),
        }


def asset_authoring_fixture_manifest(root: Path | None = None) -> dict[str, object]:
    base = Path(root) if root is not None else Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "asset_authoring"
    return {
        "mesh": str(base / "triangle.obj"),
        "texture": str(base / "checker.ppm"),
        "expected": {
            "mesh_vertices": 3,
            "mesh_faces": 1,
            "texture_size": (2, 2),
        },
    }


def asset_authoring_discovery_report(
    *,
    settings: object | None = None,
    configured_paths: Mapping[str, object] | None = None,
    include_versions: bool = False,
) -> dict[str, object]:
    return AssetAuthoringService(settings=settings).discovery_report(
        configured_paths,
        include_versions=include_versions,
    )


def _helper_report(
    spec: AssetAuthoringHelperSpec,
    settings: object | None,
    configured_paths: Mapping[str, object],
    *,
    include_version: bool = False,
    version_timeout_s: float = 2.0,
) -> dict[str, object]:
    configured_path = _configured_path(spec, settings, configured_paths)
    bundled_mesh_core_path = find_native_mesh_core_binary() if spec.key in _CDMW_MESH_CORE_BACKEND_LABELS else None
    if spec.key == "cdmw_mesh_core":
        path = configured_path or find_native_mesh_core_binary()
        status = "available" if path is not None and Path(path).is_file() else "unavailable"
        source = "configured" if configured_path else "bundled_lookup"
    elif bundled_mesh_core_path is not None and Path(bundled_mesh_core_path).is_file():
        path = bundled_mesh_core_path
        status = "available"
        source = "cdmw_mesh_core"
    else:
        path, source = _external_path(spec, configured_path)
        module_available = bool(spec.module and importlib.util.find_spec(spec.module) is not None)
        if path is not None:
            status = "available"
        elif configured_path:
            status = "configured_missing"
        elif module_available:
            status = "available"
            source = "python_module"
        else:
            status = "unavailable"
    report = {
        "key": spec.key,
        "label": spec.label,
        "status": status,
        "source": source,
        "path": str(path or configured_path or ""),
        "role": spec.role,
        "capabilities": list(spec.capabilities),
        "bundled": bool(spec.bundled),
        "package_safe": bool(spec.package_safe and status == "available"),
        "version": "",
        "version_status": "not_checked",
        "version_argv": _helper_version_argv(path) if status == "available" and path is not None else [],
    }
    if source == "cdmw_mesh_core":
        report.update(
            {
                "provided_by": "cdmw_mesh_core",
                "version": _CDMW_MESH_CORE_BACKEND_LABELS[spec.key],
                "version_status": "bundled",
                "version_argv": [],
                "package_safe": True,
            }
        )
    elif include_version:
        report.update(_helper_version_report(spec, report, timeout_s=version_timeout_s))
    return report


def _helper_spec(key: str) -> AssetAuthoringHelperSpec:
    for spec in _HELPERS:
        if spec.key == key:
            return spec
    raise KeyError(key)


def _configured_mapping(configured_paths: Mapping[str, object] | None) -> Mapping[str, object]:
    return configured_paths if isinstance(configured_paths, Mapping) else {}


def _configured_path(
    spec: AssetAuthoringHelperSpec,
    settings: object | None,
    configured_paths: Mapping[str, object],
) -> Path | None:
    raw = configured_paths.get(spec.key, configured_paths.get(spec.setting_key, ""))
    if not raw and spec.env_key:
        raw = os.environ.get(spec.env_key, "")
    if not raw and spec.setting_key and settings is not None:
        value = getattr(settings, "value", None)
        if callable(value):
            raw = value(spec.setting_key, "")
    text = str(raw or "").strip()
    return Path(text).expanduser() if text else None


def _configured_text(
    short_key: str,
    setting_key: str,
    env_key: str,
    settings: object | None,
    configured_paths: Mapping[str, object],
) -> object:
    raw = configured_paths.get(short_key, configured_paths.get(setting_key, ""))
    if not raw and env_key:
        raw = os.environ.get(env_key, "")
    if not raw and setting_key and settings is not None:
        value = getattr(settings, "value", None)
        if callable(value):
            raw = value(setting_key, "")
    return raw or ""


def _external_path(spec: AssetAuthoringHelperSpec, configured_path: Path | None) -> tuple[Path | None, str]:
    if configured_path is not None:
        return (configured_path if configured_path.is_file() else None), "configured"
    bundled_path = bundled_helper_path(spec.key)
    if bundled_path is not None:
        return bundled_path, "bundled_lookup"
    for name in spec.executables:
        found = shutil.which(name)
        if found:
            return Path(found), "path"
    module_executable = _module_executable_path(spec)
    if module_executable is not None:
        return module_executable, "python_module_script"
    return None, "not_detected"


def _module_executable_path(spec: AssetAuthoringHelperSpec) -> Path | None:
    if not spec.module:
        return None
    try:
        module_spec = importlib.util.find_spec(spec.module)
    except (ImportError, ModuleNotFoundError, ValueError):
        return None
    if module_spec is None:
        return None
    roots = [Path(sys.executable).resolve().parent]
    origin = str(getattr(module_spec, "origin", "") or "").strip()
    if origin:
        module_root = Path(origin).resolve().parent
        roots.extend((module_root / "bin", module_root.parent / "bin"))
    locations = tuple(getattr(module_spec, "submodule_search_locations", ()) or ())
    roots.extend(Path(location).resolve() / "bin" for location in locations if str(location or "").strip())
    for root in dict.fromkeys(roots):
        for name in spec.executables:
            for filename in (name, f"{name}.exe"):
                candidate = root / filename
                if candidate.is_file():
                    return candidate
    return None


def _helper_version_argv(path: Path | None) -> list[str]:
    if path is None:
        return []
    return [str(path), "--version"]


def _helper_version_report(
    spec: AssetAuthoringHelperSpec,
    helper: Mapping[str, object],
    *,
    timeout_s: float,
) -> dict[str, object]:
    argv = tuple(str(part) for part in tuple(helper.get("version_argv", ()) or ()))
    if not argv:
        return {"version_status": "unavailable", "version": "", "version_argv": []}
    try:
        completed = subprocess.run(
            argv,
            cwd=str(Path(argv[0]).expanduser().parent),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except Exception as exc:
        return {"version_status": "failed", "version": "", "version_error": str(exc), "version_argv": list(argv)}
    return {
        "version_status": "ok" if completed.returncode == 0 else "failed",
        "version": _helper_version_from_output(spec, completed.stdout, completed.stderr),
        "version_returncode": completed.returncode,
        "version_argv": list(argv),
    }


def _helper_version_from_output(spec: AssetAuthoringHelperSpec, stdout: str, stderr: str = "") -> str:
    text = "\n".join(part for part in (str(stdout or ""), str(stderr or "")) if part)
    for line in text.splitlines():
        value = line.strip()
        if value:
            return value
    return spec.label if spec.module and not spec.executables else ""


def _argv_from_template(template: object, replacements: Mapping[str, str]) -> list[str]:
    if isinstance(template, Sequence) and not isinstance(template, (str, bytes, bytearray)):
        return [str(part).format(**replacements) for part in template if str(part).strip()]
    text = str(template or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parts = shlex.split(text, posix=os.name != "nt")
    else:
        if isinstance(parsed, list):
            parts = [str(part) for part in parsed]
        else:
            parts = shlex.split(text, posix=os.name != "nt")
    return [part.format(**replacements) for part in parts if str(part).strip()]


def _normalized_channel_overrides(channel_overrides: Mapping[str, object] | None) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for raw_key, raw_channel in (channel_overrides or {}).items():
        channel = _normalize_channel(str(raw_channel or ""))
        if channel:
            overrides[_filename_key(raw_key)] = channel
    return overrides


def _texture_channel_for_path(path: Path, overrides: Mapping[str, str]) -> str:
    for key in (path.name, path.stem):
        override = overrides.get(_filename_key(key))
        if override:
            return override
    stem = _split_texture_name(path.stem)
    compact = "".join(stem)
    token_set = set(stem)
    for channel in ("recolor", "base_color", "normal", "roughness", "metallic", "ao", "height", "mask"):
        aliases = _CHANNEL_ALIASES[channel]
        if compact in aliases or aliases.intersection(token_set) or any(alias in compact for alias in aliases if len(alias) > 3):
            return channel
    return ""


def _normalize_channel(channel: str) -> str:
    compact = "".join(_split_texture_name(channel))
    for key, aliases in _CHANNEL_ALIASES.items():
        if compact == key.replace("_", "") or compact in aliases:
            return key
    return ""


def _filename_key(value: object) -> str:
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1].lower()


def _split_texture_name(name: str) -> tuple[str, ...]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(name or ""))
    return tuple(token for token in re.split(r"[^a-z0-9]+", spaced.lower()) if token)


def _scene_mesh_summary(mesh: object) -> dict[str, object]:
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    return {
        "format": str(getattr(mesh, "format", "") or ""),
        "submesh_count": len(submeshes),
        "vertex_count": sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in submeshes),
        "face_count": sum(len(getattr(submesh, "faces", ()) or ()) for submesh in submeshes),
        "has_uvs": any(bool(getattr(submesh, "uvs", ()) or ()) for submesh in submeshes),
        "has_normals": any(bool(getattr(submesh, "normals", ()) or ()) for submesh in submeshes),
        "has_tangents": any(bool(getattr(submesh, "tangents", ()) or ()) for submesh in submeshes),
        "has_skinning": bool(getattr(mesh, "has_bones", False))
        or any(bool(getattr(submesh, "bone_indices", ()) or getattr(submesh, "bone_weights", ())) for submesh in submeshes),
        "bounds_min": tuple(float(value) for value in tuple(getattr(mesh, "bbox_min", ()) or ())),
        "bounds_max": tuple(float(value) for value in tuple(getattr(mesh, "bbox_max", ()) or ())),
        "parts": [_scene_submesh_summary(index, submesh) for index, submesh in enumerate(submeshes)],
    }


def _scene_submesh_summary(index: int, submesh: object) -> dict[str, object]:
    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    faces = tuple(getattr(submesh, "faces", ()) or ())
    return {
        "index": index,
        "name": str(getattr(submesh, "name", "") or f"part_{index}"),
        "material": str(getattr(submesh, "material", "") or ""),
        "texture": str(getattr(submesh, "texture", "") or ""),
        "vertex_count": len(vertices),
        "face_count": len(faces),
        "has_uvs": len(tuple(getattr(submesh, "uvs", ()) or ())) == len(vertices) if vertices else False,
        "has_normals": len(tuple(getattr(submesh, "normals", ()) or ())) == len(vertices) if vertices else False,
        "has_tangents": len(tuple(getattr(submesh, "tangents", ()) or ())) == len(vertices) if vertices else False,
        "has_skinning": bool(getattr(submesh, "bone_indices", ()) or getattr(submesh, "bone_weights", ())),
    }


def _ufbx_material_hints(native_report: Mapping[str, object]) -> list[dict[str, object]]:
    materials = native_report.get("materials")
    names = tuple(materials.get("names", ()) if isinstance(materials, Mapping) else ())
    return [{"name": str(name), "source": "ufbx"} for name in names]


def _ufbx_texture_hints(native_report: Mapping[str, object]) -> list[dict[str, object]]:
    textures = native_report.get("texture_hints")
    files = tuple(textures.get("files", ()) if isinstance(textures, Mapping) else ())
    return [{"kind": "referenced", "path": str(path), "source": "ufbx"} for path in files]


def _scene_material_hints(scene_result: object) -> list[dict[str, object]]:
    mesh = getattr(scene_result, "mesh", None)
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    audit = getattr(scene_result, "external_audit", None)
    inventory = tuple(getattr(audit, "material_inventory", ()) or ())
    by_name = {str(getattr(item, "material_name", "") or ""): item for item in inventory}
    materials: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, submesh in enumerate(submeshes):
        name = str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or f"material_{index}")
        if name in seen:
            continue
        seen.add(name)
        item = by_name.get(name)
        materials.append(
            {
                "name": name,
                "submesh_indices": [
                    submesh_index
                    for submesh_index, candidate in enumerate(submeshes)
                    if str(getattr(candidate, "material", "") or getattr(candidate, "name", "") or "") == name
                ],
                "texture_slots": _scene_inventory_texture_slots(item) if item is not None else [],
                "warnings": list(tuple(getattr(item, "warnings", ()) or ())) if item is not None else [],
            }
        )
    return materials


def _scene_inventory_texture_slots(inventory: object) -> list[dict[str, object]]:
    return [
        {
            "slot": str(getattr(slot, "slot_kind", "") or ""),
            "path": str(getattr(slot, "texture_path", "") or ""),
            "semantic_type": str(getattr(slot, "semantic_type", "") or ""),
            "semantic_subtype": str(getattr(slot, "semantic_subtype", "") or ""),
            "color_space": str(getattr(slot, "color_space", "") or ""),
        }
        for slot in tuple(getattr(inventory, "texture_slots", ()) or ())
    ]


def _scene_texture_hints(scene_result: object) -> list[dict[str, object]]:
    paths = []
    for kind, attr in (
        ("discovered", "discovered_texture_files"),
        ("embedded", "extracted_embedded_files"),
        ("supplemental", "discovered_supplemental_files"),
    ):
        for path in tuple(getattr(scene_result, attr, ()) or ()):
            paths.append({"kind": kind, "path": str(path)})
    return paths


def _scene_skeleton_hints(scene_result: object) -> dict[str, object]:
    mesh = getattr(scene_result, "mesh", None)
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    skinned_parts = [
        index
        for index, submesh in enumerate(submeshes)
        if bool(getattr(submesh, "bone_indices", ()) or getattr(submesh, "bone_weights", ()))
    ]
    supplemental = tuple(getattr(scene_result, "discovered_supplemental_files", ()) or ())
    skeleton_files = [str(path) for path in supplemental if Path(path).suffix.lower() in {".pab", ".pabc", ".papr"}]
    has_skinning = bool(getattr(mesh, "has_bones", False) or skinned_parts)
    return {
        "has_skinning": has_skinning,
        "skinned_submesh_indices": skinned_parts,
        "skeleton_files": skeleton_files,
        "rig_status": "skinning_detected_target_mapping_required" if has_skinning else "none",
        "animation_status": "not_imported",
    }


def _scene_unsupported_hints(scene_result: object) -> list[str]:
    hints: list[str] = []
    skeleton = _scene_skeleton_hints(scene_result)
    if skeleton["has_skinning"]:
        hints.append("skeleton_binding_requires_target_mapping")
    return hints


def _openimageio_info_argv(helper: Mapping[str, object], source: Path) -> list[str]:
    return [str(helper["path"]), "--info", "-v", "--stats", str(source)]


def _openimageio_metadata_from_output(stdout: str, stderr: str = "") -> dict[str, object]:
    text = "\n".join(part for part in (str(stdout or ""), str(stderr or "")) if part)
    dimensions = re.search(r"(?P<width>\d+)\s*x\s*(?P<height>\d+)", text, re.IGNORECASE)
    channels = re.search(r"(?P<count>\d+)\s+channels?\b", text, re.IGNORECASE)
    bit_depth = _openimageio_bit_depth(text)
    color_space = _openimageio_metadata_value(text, (r"oiio:ColorSpace", r"Color\s*space", r"colorspace"))
    channel_names_match = re.search(r"channel\s+list\s*:\s*(?P<names>[^\r\n]+)", text, re.IGNORECASE)
    channel_names = [
        name.strip()
        for name in (channel_names_match.group("names").split(",") if channel_names_match else ())
        if name.strip()
    ]
    channel_stats = _openimageio_channel_stats(text, channel_names)
    alpha_stats = channel_stats.get("A", channel_stats.get("a", {}))
    alpha_maximum = float(alpha_stats.get("maximum", 0.0) or 0.0) if alpha_stats else 0.0
    alpha_minimum = float(alpha_stats.get("minimum", alpha_maximum) or 0.0) if alpha_stats else 0.0
    alpha_average = float(alpha_stats.get("average", alpha_maximum) or 0.0) if alpha_stats else 0.0
    return {
        "width": int(dimensions.group("width")) if dimensions else 0,
        "height": int(dimensions.group("height")) if dimensions else 0,
        "channel_count": int(channels.group("count")) if channels else 0,
        "bit_depth": bit_depth,
        "color_space": color_space,
        "channel_names": channel_names,
        "channel_stats": channel_stats,
        "has_alpha_channel": bool(alpha_stats),
        "alpha_varies": bool(alpha_stats and alpha_maximum > alpha_minimum),
        "alpha_has_transparency": bool(alpha_stats and alpha_average < alpha_maximum),
        "raw_line_count": len([line for line in text.splitlines() if line.strip()]),
    }


def _openimageio_channel_stats(text: str, channel_names: Sequence[str]) -> dict[str, dict[str, float]]:
    rows: dict[str, list[float]] = {}
    labels = {
        "Min": "minimum",
        "Max": "maximum",
        "Avg": "average",
        "StdDev": "stddev",
    }
    for source_label, target_label in labels.items():
        match = re.search(
            rf"Stats\s+{source_label}\s*:\s*(?P<values>[^\r\n(]+)",
            text,
            re.IGNORECASE,
        )
        if match is None:
            continue
        values = [
            float(value)
            for value in re.findall(r"[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)", match.group("values"), re.IGNORECASE)
        ]
        rows[target_label] = values
    count = max((len(values) for values in rows.values()), default=0)
    names = list(channel_names[:count])
    names.extend(f"channel_{index}" for index in range(len(names), count))
    return {
        name: {
            label: values[index]
            for label, values in rows.items()
            if index < len(values)
        }
        for index, name in enumerate(names)
    }


def _openimageio_diff_thresholds(
    *,
    fail_threshold: float | None,
    fail_percent: float | None,
    hard_fail_threshold: float | None,
) -> dict[str, float | None]:
    values = {
        "fail_threshold": fail_threshold,
        "fail_percent": fail_percent,
        "hard_fail_threshold": hard_fail_threshold,
    }
    normalized: dict[str, float | None] = {}
    for name, value in values.items():
        if value is None:
            normalized[name] = None
            continue
        number = float(value)
        if not math.isfinite(number) or number < 0.0:
            raise ValueError(f"OpenImageIO {name} must be a finite non-negative number.")
        if name == "fail_percent" and number > 100.0:
            raise ValueError("OpenImageIO fail_percent must be between 0 and 100.")
        normalized[name] = number
    return normalized


def _openimageio_number(value: object) -> str:
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError("OpenImageIO numeric arguments must be finite non-negative numbers.")
    return format(number, ".12g")


def _openimageio_diff_metrics(stdout: str, stderr: str = "") -> dict[str, object]:
    text = "\n".join(part for part in (str(stdout or ""), str(stderr or "")) if part)

    def metric(label: str) -> float | str | None:
        match = re.search(
            rf"{label}\s*=\s*(?P<value>[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?|inf(?:inity)?))",
            text,
            re.IGNORECASE,
        )
        if match is None:
            return None
        raw = match.group("value")
        value = float(raw)
        return value if math.isfinite(value) else raw.casefold()

    threshold_rows = []
    for match in re.finditer(
        r"(?P<count>\d+)\s+pixels?\s*\((?P<percent>[\d.]+)%\)\s+over\s+(?P<threshold>\S+)",
        text,
        re.IGNORECASE,
    ):
        threshold_rows.append(
            {
                "pixel_count": int(match.group("count")),
                "percent": float(match.group("percent")),
                "threshold": match.group("threshold"),
            }
        )
    result_rows = re.findall(r"^\s*(PASS|WARNING|FAILURE)\s*$", text, re.IGNORECASE | re.MULTILINE)
    max_location = re.search(r"Max\s+error\s*=.*?@\s*\((?P<location>[^)]+)\)", text, re.IGNORECASE)
    return {
        "mean_error": metric(r"Mean\s+error"),
        "rms_error": metric(r"RMS\s+error"),
        "peak_snr_db": metric(r"Peak\s+SNR"),
        "max_error": metric(r"Max\s+error"),
        "max_error_location": max_location.group("location").strip() if max_location else "",
        "threshold_rows": threshold_rows,
        "result": result_rows[-1].casefold() if result_rows else "unknown",
    }


def _openimageio_metadata_value(text: str, labels: Sequence[str]) -> str:
    for label in labels:
        match = re.search(label + r"\s*[:=]\s*\"?(?P<value>[^\"\r\n]+)", text, re.IGNORECASE)
        if match:
            return match.group("value").strip()
    return ""


def _openimageio_bit_depth(text: str) -> int:
    explicit = re.search(r"Bits?\s+per\s+(?:channel|sample)\s*[:=]\s*(?P<bits>\d+)", text, re.IGNORECASE)
    if explicit:
        return int(explicit.group("bits"))
    for marker, bits in (("uint8", 8), ("uint16", 16), ("half", 16), ("float", 32), ("double", 64)):
        if re.search(rf"\b{marker}\b", text, re.IGNORECASE):
            return bits
    return 0


def _uv_island_report(island: object) -> dict[str, object]:
    return {
        "index": int(getattr(island, "index", 0) or 0),
        "submesh_index": int(getattr(island, "submesh_index", 0) or 0),
        "part_name": str(getattr(island, "part_name", "") or ""),
        "material": str(getattr(island, "material", "") or ""),
        "texture": str(getattr(island, "texture", "") or ""),
        "vertex_count": int(getattr(island, "vertex_count", 0) or 0),
        "face_count": int(getattr(island, "face_count", 0) or 0),
        "uv_min": tuple(float(value) for value in tuple(getattr(island, "uv_min", (0.0, 0.0)) or (0.0, 0.0))[:2]),
        "uv_max": tuple(float(value) for value in tuple(getattr(island, "uv_max", (0.0, 0.0)) or (0.0, 0.0))[:2]),
        "selected": bool(getattr(island, "selected", False)),
        "selected_vertex_count": int(getattr(island, "selected_vertex_count", 0) or 0),
        "selected_face_count": int(getattr(island, "selected_face_count", 0) or 0),
    }


def _uv_missing_parts(mesh: object) -> list[dict[str, object]]:
    missing: list[dict[str, object]] = []
    for index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
        vertices = tuple(getattr(submesh, "vertices", ()) or ())
        uvs = tuple(getattr(submesh, "uvs", ()) or ())
        faces = tuple(getattr(submesh, "faces", ()) or ())
        if vertices and (len(uvs) != len(vertices) or not faces):
            missing.append(
                {
                    "index": index,
                    "name": str(getattr(submesh, "name", "") or f"part_{index}"),
                    "vertex_count": len(vertices),
                    "uv_count": len(uvs),
                    "face_count": len(faces),
                }
            )
    return missing


def _uv_bounds(islands: Sequence[Mapping[str, object]]) -> dict[str, object]:
    if not islands:
        return {"available": False, "uv_min": (0.0, 0.0), "uv_max": (0.0, 0.0)}
    mins = [tuple(island.get("uv_min", (0.0, 0.0)) or (0.0, 0.0)) for island in islands]
    maxes = [tuple(island.get("uv_max", (0.0, 0.0)) or (0.0, 0.0)) for island in islands]
    return {
        "available": True,
        "uv_min": (min(float(value[0]) for value in mins), min(float(value[1]) for value in mins)),
        "uv_max": (max(float(value[0]) for value in maxes), max(float(value[1]) for value in maxes)),
    }


def _native_auto_uv_report(mesh: object, atlas_size: tuple[int, int]) -> dict[str, object]:
    try:
        from cdmw.modding.mesh_native_core import native_mesh_auto_uv_report

        submesh_indices = set(range(len(tuple(getattr(mesh, "submeshes", ()) or ()))))
        resolution = max(0, int(atlas_size[0] or 0), int(atlas_size[1] or 0))
        report = native_mesh_auto_uv_report(mesh, submesh_indices, resolution=resolution)
    except Exception as exc:
        return {"status": "error", "unwrap_backend": "xatlas", "message": str(exc)}
    if isinstance(report, dict):
        return report
    return {
        "status": "unavailable",
        "unwrap_backend": "xatlas",
        "message": "cdmw_mesh_core auto-uv-json is unavailable.",
    }


def _native_mesh_optimization_report(mesh: object, simplify_ratio: float, target_error: float) -> dict[str, object]:
    try:
        from cdmw.modding.mesh_native_core import native_mesh_optimization_report

        submesh_indices = set(range(len(tuple(getattr(mesh, "submeshes", ()) or ()))))
        report = native_mesh_optimization_report(
            mesh,  # type: ignore[arg-type]
            submesh_indices,
            simplify_ratio=simplify_ratio,
            target_error=target_error,
        )
    except Exception as exc:
        return {"status": "error", "optimization_backend": "meshoptimizer", "message": str(exc)}
    if isinstance(report, dict):
        return report
    return {
        "status": "unavailable",
        "optimization_backend": "meshoptimizer",
        "message": "cdmw_mesh_core optimize-json is unavailable.",
    }


def _mesh_optimization_warnings(
    native: Mapping[str, object],
    topology: Mapping[str, object],
    simplify_ratio: float,
) -> list[str]:
    warnings: list[str] = []
    if native.get("status") not in {"ok", "OK"}:
        warnings.append("Native meshoptimizer report is unavailable.")
    if simplify_ratio < 1.0 and not bool(native.get("topology_changed", False)):
        warnings.append("Simplification requested but native output did not reduce triangle/index topology.")
    if bool(native.get("topology_changed", False)):
        warnings.append("Native simplification changes index topology; review before package output.")
    if bool(topology.get("topology_changed", False)):
        warnings.append("Current mesh topology differs from original; optimize output should be reviewed.")
    return warnings


def _uv_authoring_warnings(
    islands: Sequence[Mapping[str, object]],
    missing_parts: Sequence[Mapping[str, object]],
    topology: Mapping[str, object],
) -> list[str]:
    warnings: list[str] = []
    if missing_parts:
        warnings.append(f"{len(missing_parts)} part(s) have missing/incomplete UV data or no faces.")
    if not islands:
        warnings.append("No UV islands were found.")
    if bool(topology.get("topology_changed", False)):
        warnings.append("Topology changed from original mesh; UV remap safety needs review.")
    return warnings


def _tangent_authoring_part(index: int, submesh: object) -> dict[str, object]:
    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    faces = tuple(getattr(submesh, "faces", ()) or ())
    uvs = tuple(getattr(submesh, "uvs", ()) or ())
    normals = tuple(getattr(submesh, "normals", ()) or ())
    tangents = tuple(getattr(submesh, "tangents", ()) or ())
    return {
        "index": index,
        "name": str(getattr(submesh, "name", "") or f"part_{index}"),
        "vertex_count": len(vertices),
        "face_count": len(faces),
        "uv_count": len(uvs),
        "normal_count": len(normals),
        "tangent_count": len(tangents),
        "uv_coverage": _channel_coverage(len(uvs), len(vertices)),
        "normal_coverage": _channel_coverage(len(normals), len(vertices)),
        "tangent_coverage": _channel_coverage(len(tangents), len(vertices)),
        "can_generate": bool(vertices and faces and len(uvs) == len(vertices)),
        "face_corner_tangent_count": len(faces) * 3,
    }


def _channel_coverage(count: int, vertex_count: int) -> str:
    if vertex_count <= 0:
        return "empty"
    if count == 0:
        return "missing"
    if count == vertex_count:
        return "complete"
    return "partial"


def _tangent_authoring_totals(parts: Sequence[Mapping[str, object]]) -> dict[str, int]:
    return {
        "part_count": len(parts),
        "complete_tangent_parts": sum(1 for part in parts if part.get("tangent_coverage") == "complete"),
        "missing_tangent_parts": sum(
            1 for part in parts if part.get("vertex_count") and part.get("tangent_coverage") == "missing"
        ),
        "partial_tangent_parts": sum(1 for part in parts if part.get("tangent_coverage") == "partial"),
        "generatable_parts": sum(1 for part in parts if bool(part.get("can_generate"))),
        "missing_uv_parts": sum(
            1 for part in parts if part.get("vertex_count") and part.get("uv_coverage") != "complete"
        ),
        "missing_normal_parts": sum(
            1 for part in parts if part.get("vertex_count") and part.get("normal_coverage") != "complete"
        ),
    }


def _tangent_authoring_warnings(totals: Mapping[str, int], topology: Mapping[str, object]) -> list[str]:
    warnings: list[str] = []
    missing = int(totals.get("missing_tangent_parts", 0) or 0)
    partial = int(totals.get("partial_tangent_parts", 0) or 0)
    missing_uv = int(totals.get("missing_uv_parts", 0) or 0)
    missing_normals = int(totals.get("missing_normal_parts", 0) or 0)
    if missing or partial:
        warnings.append(f"{missing + partial} part(s) have missing or partial tangent data.")
    if missing_uv:
        warnings.append(f"{missing_uv} part(s) need complete UVs before tangent generation.")
    if missing_normals:
        warnings.append(f"{missing_normals} part(s) have missing or partial normals.")
    if bool(topology.get("topology_changed", False)):
        warnings.append("Topology changed from original mesh; regenerated tangents should be reviewed.")
    return warnings


def _mesh_health_part(index: int, submesh: object, duplicate_epsilon: float) -> dict[str, object]:
    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    faces = tuple(getattr(submesh, "faces", ()) or ())
    finite_vertices = {vertex_index for vertex_index, vertex in enumerate(vertices) if _vertex3(vertex) is not None}
    invalid_vertices = len(vertices) - len(finite_vertices)
    duplicate_vertex_groups, duplicate_vertices = _duplicate_vertex_counts(vertices, duplicate_epsilon)

    used_vertices: set[int] = set()
    invalid_faces = 0
    invalid_indices = 0
    invalid_index_faces = 0
    degenerate_faces = 0
    duplicate_faces = 0
    seen_faces: set[tuple[int, int, int]] = set()
    connected_faces: list[tuple[int, int, int]] = []
    for face in faces:
        indices = _face_indices(face)
        if indices is None:
            invalid_faces += 1
            continue
        bad_indices = sum(1 for value in indices if value < 0 or value >= len(vertices))
        if bad_indices:
            invalid_indices += bad_indices
            invalid_index_faces += 1
            continue
        if len(set(indices)) < 3:
            degenerate_faces += 1
            continue
        connected_faces.append(indices)
        used_vertices.update(indices)
        face_key = tuple(sorted(indices))
        if face_key in seen_faces:
            duplicate_faces += 1
        seen_faces.add(face_key)

    loose_vertices = max(0, len(vertices) - len(used_vertices))
    return {
        "index": index,
        "name": str(getattr(submesh, "name", "") or f"part_{index}"),
        "vertex_count": len(vertices),
        "face_count": len(faces),
        "valid_faces": len(connected_faces),
        "invalid_vertices": invalid_vertices,
        "invalid_faces": invalid_faces,
        "invalid_indices": invalid_indices,
        "invalid_index_faces": invalid_index_faces,
        "degenerate_faces": degenerate_faces,
        "duplicate_vertex_groups": duplicate_vertex_groups,
        "duplicate_vertices": duplicate_vertices,
        "duplicate_faces": duplicate_faces,
        "loose_vertices": loose_vertices,
        **_mesh_connectivity_counts(connected_faces),
    }


def _mesh_connectivity_counts(faces: Sequence[tuple[int, int, int]]) -> dict[str, int]:
    edge_slots: dict[tuple[int, int], list[int]] = {}
    edge_directions: dict[tuple[int, int], list[bool]] = {}
    vertex_slots: dict[int, list[int]] = {}
    for slot, corners in enumerate(faces):
        for position in range(3):
            start = corners[position]
            end = corners[(position + 1) % 3]
            key = (start, end) if start < end else (end, start)
            edge_slots.setdefault(key, []).append(slot)
            edge_directions.setdefault(key, []).append(start < end)
            vertex_slots.setdefault(start, []).append(slot)

    boundary_edges = 0
    non_manifold_edges = 0
    inconsistent_winding_edges = 0
    for directions in edge_directions.values():
        if len(directions) == 1:
            boundary_edges += 1
        elif len(directions) > 2:
            non_manifold_edges += 1
        elif directions[0] == directions[1]:
            inconsistent_winding_edges += 1

    fans: dict[tuple[int, int], tuple[int, int]] = {}
    for (left_vertex, right_vertex), slots in edge_slots.items():
        for other in slots[1:]:
            _union_face_fans(fans, (left_vertex, slots[0]), (left_vertex, other))
            _union_face_fans(fans, (right_vertex, slots[0]), (right_vertex, other))

    bowtie_vertices = 0
    for vertex, slots in vertex_slots.items():
        if len(slots) < 2:
            continue
        if len({_find_face_fan(fans, (vertex, slot)) for slot in slots}) > 1:
            bowtie_vertices += 1

    return {
        "boundary_edges": boundary_edges,
        "non_manifold_edges": non_manifold_edges,
        "inconsistent_winding_edges": inconsistent_winding_edges,
        "bowtie_vertices": bowtie_vertices,
    }


def _find_face_fan(fans: dict[tuple[int, int], tuple[int, int]], node: tuple[int, int]) -> tuple[int, int]:
    root = node
    while fans.get(root, root) != root:
        root = fans[root]
    while fans.get(node, node) != node:
        fans[node], node = root, fans[node]
    return root


def _union_face_fans(
    fans: dict[tuple[int, int], tuple[int, int]],
    left: tuple[int, int],
    right: tuple[int, int],
) -> None:
    left_root = _find_face_fan(fans, left)
    right_root = _find_face_fan(fans, right)
    if left_root != right_root:
        fans[left_root] = right_root


def _mesh_health_totals(parts: Sequence[Mapping[str, object]]) -> dict[str, int]:
    keys = (
        "vertex_count",
        "face_count",
        "valid_faces",
        "invalid_vertices",
        "invalid_faces",
        "invalid_indices",
        "invalid_index_faces",
        "degenerate_faces",
        "duplicate_vertex_groups",
        "duplicate_vertices",
        "duplicate_faces",
        "loose_vertices",
        "boundary_edges",
        "non_manifold_edges",
        "inconsistent_winding_edges",
        "bowtie_vertices",
    )
    return {key: sum(int(part.get(key, 0) or 0) for part in parts) for key in keys}


def _mesh_health_warnings(totals: Mapping[str, int], topology: Mapping[str, object]) -> list[str]:
    warnings: list[str] = []
    for key, label in (
        ("invalid_vertices", "non-finite or malformed vertices"),
        ("invalid_faces", "malformed faces"),
        ("invalid_indices", "out-of-range face indices"),
        ("degenerate_faces", "degenerate faces"),
        ("duplicate_vertices", "duplicate vertices"),
        ("duplicate_faces", "duplicate faces"),
        ("loose_vertices", "loose vertices"),
        ("non_manifold_edges", "non-manifold edges shared by more than two faces"),
        ("inconsistent_winding_edges", "edges whose neighbouring faces disagree on winding"),
        ("bowtie_vertices", "bowtie vertices joining otherwise disconnected face fans"),
    ):
        count = int(totals.get(key, 0) or 0)
        if count:
            warnings.append(f"{count} {label} detected.")
    if bool(topology.get("topology_changed", False)):
        warnings.append("Topology changed from original mesh; package output should stay conservative until reviewed.")
    return warnings


def _duplicate_vertex_counts(vertices: Sequence[object], epsilon: float) -> tuple[int, int]:
    groups: dict[tuple[float, float, float] | tuple[int, int, int], int] = {}
    for vertex in vertices:
        parsed = _vertex3(vertex)
        if parsed is None:
            continue
        key = _vertex_key(parsed, epsilon)
        groups[key] = groups.get(key, 0) + 1
    duplicate_groups = sum(1 for count in groups.values() if count > 1)
    duplicate_vertices = sum(count - 1 for count in groups.values() if count > 1)
    return duplicate_groups, duplicate_vertices


def _vertex_key(vertex: tuple[float, float, float], epsilon: float) -> tuple[float, float, float] | tuple[int, int, int]:
    if epsilon <= 0:
        return vertex
    return (round(vertex[0] / epsilon), round(vertex[1] / epsilon), round(vertex[2] / epsilon))


def _bounded_float(value: object, fallback: float, lower: float, upper: float) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        parsed = fallback
    if not math.isfinite(parsed):
        parsed = fallback
    return min(upper, max(lower, parsed))


def _vertex3(vertex: object) -> tuple[float, float, float] | None:
    try:
        values = tuple(vertex)  # type: ignore[arg-type]
    except TypeError:
        return None
    if len(values) != 3:
        return None
    try:
        parsed = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in parsed):
        return None
    return (parsed[0], parsed[1], parsed[2])


def _face_indices(face: object) -> tuple[int, int, int] | None:
    try:
        values = tuple(face)  # type: ignore[arg-type]
    except TypeError:
        return None
    if len(values) != 3:
        return None
    indices: list[int] = []
    for value in values:
        if isinstance(value, bool):
            return None
        try:
            index = value.__index__()  # type: ignore[attr-defined]
        except (AttributeError, TypeError):
            return None
        indices.append(int(index))
    return (indices[0], indices[1], indices[2])


def _mesh_topology_delta(original_mesh: object, mesh: object) -> dict[str, object]:
    before = _mesh_topology_summary(original_mesh)
    after = _mesh_topology_summary(mesh)
    changed_fields = [
        key
        for key in ("submesh_count", "vertex_count", "face_count", "index_count")
        if before[key] != after[key]
    ]
    return {
        "available": True,
        "topology_changed": bool(changed_fields),
        "changed_fields": changed_fields,
        "before": before,
        "after": after,
    }


def _mesh_topology_summary(mesh: object) -> dict[str, int]:
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    face_count = sum(len(tuple(getattr(submesh, "faces", ()) or ())) for submesh in submeshes)
    return {
        "submesh_count": len(submeshes),
        "vertex_count": sum(len(tuple(getattr(submesh, "vertices", ()) or ())) for submesh in submeshes),
        "face_count": face_count,
        "index_count": face_count * 3,
    }


__all__ = [
    "ASSET_AUTHORING_DISCOVERY_SCHEMA",
    "ASSET_AUTHORING_MESH_HEALTH_SCHEMA",
    "ASSET_AUTHORING_MESH_OPTIMIZATION_SCHEMA",
    "ASSET_AUTHORING_SCENE_IMPORT_SCHEMA",
    "ASSET_AUTHORING_SOURCE_IMAGE_SCHEMA",
    "ASSET_AUTHORING_TANGENT_REPORT_SCHEMA",
    "ASSET_AUTHORING_TEXTURE_SET_SCHEMA",
    "ASSET_AUTHORING_UV_REPORT_SCHEMA",
    "AssetAuthoringService",
    "asset_authoring_discovery_report",
    "asset_authoring_fixture_manifest",
]
