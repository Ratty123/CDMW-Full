"""Connected handoff package for the Mesh Editor .NET experiment."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from uuid import uuid4
from dataclasses import dataclass, asdict
from pathlib import Path

from cdmw.domain.mesh.operations import (
    mesh_edit_operations_from_dicts,
    mesh_edit_operations_to_dicts,
    validate_mesh_edit_operations,
)
from cdmw.modding.mesh_exporter import export_obj
from cdmw.modding.mesh_obj_importer import import_obj
from cdmw.modding.mesh_parser import ParsedMesh


MESH_DOTNET_EXPERIMENT_BINARY_NAME = "cdmw-mesh-dotnet-editor.exe" if os.name == "nt" else "cdmw-mesh-dotnet-editor"


@dataclass(frozen=True, slots=True)
class MeshDotNetExperimentPackage:
    package_dir: Path
    mesh_path: Path
    obj_sidecar_path: Path
    cdmeta_path: Path
    original_asset_hash_path: Path
    status_path: Path
    output_dir: Path
    edit_operations_path: Path
    launch_manifest_path: Path


@dataclass(frozen=True, slots=True)
class MeshDotNetExecutableResolution:
    configured_path: str
    env_path: str
    frozen_root: str
    exe_root: str
    resolved_path: str
    exists: bool
    is_file: bool
    source: str

    def as_event_payload(self) -> dict[str, object]:
        return asdict(self)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _safe_int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _texture_reference_with_suffix(texture: str, suffix: str) -> str:
    normalized = str(texture or "").replace("\\", "/").strip()
    if not normalized:
        return ""
    return normalized if Path(normalized).suffix else f"{normalized}{suffix}"


def _texture_reference_variant(texture: str, suffix: str) -> str:
    normalized = str(texture or "").replace("\\", "/").strip()
    if not normalized:
        return ""
    base = Path(normalized).stem if Path(normalized).suffix else normalized
    extension = Path(normalized).suffix or ".dds"
    return f"{base}{suffix}{extension}"


def _dotnet_texture_channels(texture: str) -> dict[str, object]:
    base = _texture_reference_with_suffix(texture, ".dds")
    return {
        "base": base,
        "albedo": base,
        "diffuse": base,
        "normal": _texture_reference_variant(texture, "_n"),
        "specular": _texture_reference_variant(texture, "_s"),
        "roughness": _texture_reference_variant(texture, "_r"),
        "metallic": _texture_reference_variant(texture, "_m"),
        "emissive": _texture_reference_variant(texture, "_e"),
        "height": _texture_reference_variant(texture, "_h"),
        "material": _texture_reference_variant(texture, "_mat"),
    }


def _dotnet_material_input_channels(source: object | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if source is None:
        return result
    for item in tuple(getattr(source, "preview_material_texture_inputs", ()) or ()): 
        semantic = str(getattr(item, "semantic_type", "") or getattr(item, "slot_kind", "") or "").strip().lower()
        path = str(getattr(item, "source_path", "") or getattr(item, "preview_texture_path", "") or "").strip()
        if semantic and path and semantic not in result:
            result[semantic] = path
    return result


def _dotnet_resolved_texture_channels(source: object | None) -> dict[str, str]:
    if source is None:
        return {}
    result = _dotnet_material_input_channels(source)
    pairs = {
        "base": ("preview_texture_path", "preview_texture_dds_path", "preview_base_texture_default_path"),
        "albedo": ("preview_texture_path", "preview_texture_dds_path", "preview_base_texture_default_path"),
        "diffuse": ("preview_texture_path", "preview_texture_dds_path", "preview_base_texture_default_path"),
        "normal": ("preview_normal_texture_path", "preview_normal_texture_dds_path", "preview_normal_texture_default_path"),
        "material": ("preview_material_texture_path", "preview_material_texture_dds_path", "preview_material_texture_default_path"),
        "specular": ("preview_material_texture_path", "preview_material_texture_dds_path", "preview_material_texture_default_path"),
        "roughness": ("preview_material_texture_path", "preview_material_texture_dds_path", "preview_material_texture_default_path"),
        "metallic": ("preview_material_texture_path", "preview_material_texture_dds_path", "preview_material_texture_default_path"),
        "height": ("preview_height_texture_path", "preview_height_texture_dds_path", "preview_height_texture_default_path"),
    }
    for channel, attrs in pairs.items():
        for attr in attrs:
            value = str(getattr(source, attr, "") or "").strip()
            if value:
                result[channel] = value
                break
    return result


def _copy_dotnet_texture_channel_resources(channels: Mapping[str, str], package_dir: Path) -> dict[str, str]:
    textures_dir = package_dir / "textures"
    result: dict[str, str] = {}
    for channel, value in channels.items():
        source = Path(str(value or "")).expanduser()
        if not source.is_file():
            continue
        digest = hashlib.sha1(str(source.resolve()).encode("utf-8", errors="ignore")).hexdigest()[:10]
        target = textures_dir / f"{channel}_{digest}_{source.name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            shutil.copyfile(source, target)
        result[channel] = target.relative_to(package_dir).as_posix()
    return result


def _dotnet_material_slot_payload(slot: object, fallback_index: int) -> dict[str, object]:
    slot_map = slot if isinstance(slot, Mapping) else {}
    index = _safe_int(slot_map.get("index"), fallback_index)
    name = str(slot_map.get("name", "") or "").strip()
    texture = str(slot_map.get("texture", "") or "").strip()
    channels = _dotnet_texture_channels(texture)
    return {"index": index, "name": name, "texture": texture, "channels": channels}


def _dotnet_submesh_material_payload(
    submesh: object,
    fallback_index: int,
    *,
    source_submesh: object | None = None,
    package_dir: Path,
) -> dict[str, object]:
    submesh_map = submesh if isinstance(submesh, Mapping) else {}
    texture = str(submesh_map.get("texture", "") or "").strip()
    resolved_channels = _dotnet_resolved_texture_channels(source_submesh)
    packaged_channels = _copy_dotnet_texture_channel_resources(resolved_channels, package_dir)
    return {
        "submesh_index": _safe_int(submesh_map.get("submesh_index"), fallback_index),
        "name": str(submesh_map.get("name", "") or "").strip(),
        "material_slot_index": _safe_int(submesh_map.get("material_slot_index"), fallback_index),
        "material": str(submesh_map.get("material", "") or "").strip(),
        "texture": texture,
        "channels": _dotnet_texture_channels(texture),
        "resolved_channels": resolved_channels,
        "packaged_channels": packaged_channels,
        "resolved_texture_count": len([value for value in resolved_channels.values() if value]),
        "packaged_texture_count": len(packaged_channels),
    }


def _write_dotnet_material_manifest(path: Path, *, mesh: ParsedMesh, sidecar_payload: Mapping[str, object]) -> None:
    raw_slots = sidecar_payload.get("material_slots", [])
    slots = list(raw_slots) if isinstance(raw_slots, list) else []
    if not slots:
        slots = [
            {"index": index, "name": str(submesh.material or submesh.name or ""), "texture": str(submesh.texture or "")}
            for index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ()))
        ]
    source_submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    raw_lods = sidecar_payload.get("lods", [])
    lods = list(raw_lods) if isinstance(raw_lods, list) else []
    first_lod = lods[0] if lods and isinstance(lods[0], Mapping) else {}
    raw_submeshes = first_lod.get("submeshes", []) if isinstance(first_lod, Mapping) else []
    submeshes = list(raw_submeshes) if isinstance(raw_submeshes, list) else []
    if not submeshes:
        submeshes = [
            {
                "submesh_index": index,
                "name": str(submesh.name or ""),
                "material_slot_index": index,
                "material": str(submesh.material or ""),
                "texture": str(submesh.texture or ""),
            }
            for index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ()))
        ]
    payload = {
        "format": "cdmw_mesh_dotnet_materials_v1",
        "renderer_authority": "dotnet_mesh_editor",
        "source": "mesh.cdmeta.json",
        "texture_channels": ["base", "normal", "specular", "roughness", "metallic", "emissive", "height", "material"],
        "material_slots": [_dotnet_material_slot_payload(slot, index) for index, slot in enumerate(slots)],
        "submeshes": [
            _dotnet_submesh_material_payload(
                submesh,
                index,
                source_submesh=source_submeshes[index] if index < len(source_submeshes) else None,
                package_dir=path.parent,
            )
            for index, submesh in enumerate(submeshes)
        ],
        "fallbacks": {"base": "neutral_checker", "normal": "flat_normal", "emissive": "black"},
        "source_mesh": str(getattr(mesh, "path", "") or ""),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def default_mesh_dotnet_experiment_editor_path(*, release: bool = True) -> Path:
    config = "Release" if release else "Debug"
    return _repo_root() / "native" / "cdmw_mesh_dotnet_editor" / "build" / config / MESH_DOTNET_EXPERIMENT_BINARY_NAME


def _mesh_dotnet_candidate_paths(
    *,
    configured_path: Path | None = None,
    env_path: str = "",
    frozen_root: Path | None = None,
    exe_root: Path | None = None,
) -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    if configured_path is not None:
        candidates.append(("configured_path", configured_path.expanduser()))
    if env_path:
        candidates.append(("env_path", Path(env_path).expanduser()))
    if frozen_root is not None:
        candidates.extend(
            [
                ("frozen_root_flat", frozen_root / "native" / MESH_DOTNET_EXPERIMENT_BINARY_NAME),
                (
                    "frozen_root_release",
                    frozen_root / "native" / "cdmw_mesh_dotnet_editor" / "build" / "Release" / MESH_DOTNET_EXPERIMENT_BINARY_NAME,
                ),
                (
                    "frozen_root_debug",
                    frozen_root / "native" / "cdmw_mesh_dotnet_editor" / "build" / "Debug" / MESH_DOTNET_EXPERIMENT_BINARY_NAME,
                ),
            ]
        )
    if exe_root is not None:
        candidates.extend(
            [
                ("exe_root_flat", exe_root / "native" / MESH_DOTNET_EXPERIMENT_BINARY_NAME),
                (
                    "exe_root_release",
                    exe_root / "native" / "cdmw_mesh_dotnet_editor" / "build" / "Release" / MESH_DOTNET_EXPERIMENT_BINARY_NAME,
                ),
                (
                    "exe_root_debug",
                    exe_root / "native" / "cdmw_mesh_dotnet_editor" / "build" / "Debug" / MESH_DOTNET_EXPERIMENT_BINARY_NAME,
                ),
            ]
        )
    candidates.extend(
        [
            (
                "source_release",
                _repo_root()
                / "tools"
                / "dotnet_mesh_editor_experiment"
                / "bin"
                / "Release"
                / "net8.0-windows"
                / MESH_DOTNET_EXPERIMENT_BINARY_NAME,
            ),
            (
                "source_debug",
                _repo_root()
                / "tools"
                / "dotnet_mesh_editor_experiment"
                / "bin"
                / "Debug"
                / "net8.0-windows"
                / MESH_DOTNET_EXPERIMENT_BINARY_NAME,
            ),
            ("native_release", default_mesh_dotnet_experiment_editor_path(release=True)),
            ("native_debug", default_mesh_dotnet_experiment_editor_path(release=False)),
        ]
    )
    return candidates


def resolve_mesh_dotnet_experiment_editor(
    configured_path: Path | str | None = None,
) -> MeshDotNetExecutableResolution:
    raw_configured = str(configured_path or "").strip()
    configured = Path(raw_configured).expanduser() if raw_configured else None
    env_path = os.environ.get("CDMW_MESH_DOTNET_EXPERIMENT_EXE", "").strip()
    frozen_root = Path(str(getattr(sys, "_MEIPASS", ""))) if getattr(sys, "_MEIPASS", "") else None
    exe_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    first_existing: tuple[str, Path] | None = None
    for source, candidate in _mesh_dotnet_candidate_paths(
        configured_path=configured,
        env_path=env_path,
        frozen_root=frozen_root,
        exe_root=exe_root,
    ):
        if candidate.exists() and first_existing is None:
            first_existing = (source, candidate)
        if candidate.is_file():
            return MeshDotNetExecutableResolution(
                configured_path=raw_configured,
                env_path=env_path,
                frozen_root=str(frozen_root or ""),
                exe_root=str(exe_root or ""),
                resolved_path=str(candidate),
                exists=True,
                is_file=True,
                source=source,
            )
    if first_existing is not None:
        source, candidate = first_existing
        return MeshDotNetExecutableResolution(
            configured_path=raw_configured,
            env_path=env_path,
            frozen_root=str(frozen_root or ""),
            exe_root=str(exe_root or ""),
            resolved_path=str(candidate),
            exists=True,
            is_file=False,
            source=source,
        )
    missing = configured or (Path(env_path).expanduser() if env_path else None)
    return MeshDotNetExecutableResolution(
        configured_path=raw_configured,
        env_path=env_path,
        frozen_root=str(frozen_root or ""),
        exe_root=str(exe_root or ""),
        resolved_path=str(missing or ""),
        exists=False,
        is_file=False,
        source="missing",
    )


def find_mesh_dotnet_experiment_editor() -> Path | None:
    resolution = resolve_mesh_dotnet_experiment_editor()
    return Path(resolution.resolved_path) if resolution.is_file and resolution.resolved_path else None


def build_mesh_dotnet_experiment_package(
    mesh: ParsedMesh,
    *,
    output_root: Path | str | None = None,
) -> MeshDotNetExperimentPackage:
    root = Path(output_root) if output_root is not None else Path(tempfile.gettempdir()) / "cdmw_mesh_dotnet_experiment"
    package_dir = root / f"package_{int(time.time() * 1000)}_{uuid4().hex[:8]}"
    package_dir.mkdir(parents=True, exist_ok=False)

    exported_paths = tuple(Path(path) for path in export_obj(mesh, str(package_dir), "mesh"))
    mesh_path = package_dir / "mesh.obj"
    obj_sidecar_path = package_dir / "mesh.obj.meta.json"
    if mesh_path not in exported_paths or not mesh_path.is_file():
        raise RuntimeError("Mesh .NET experiment package did not create mesh.obj.")
    if obj_sidecar_path not in exported_paths or not obj_sidecar_path.is_file():
        raise RuntimeError("Mesh .NET experiment package did not create mesh.obj.meta.json.")

    cdmeta_path = package_dir / "mesh.cdmeta.json"
    shutil.copyfile(obj_sidecar_path, cdmeta_path)
    sidecar_payload = json.loads(cdmeta_path.read_text(encoding="utf-8"))
    if not isinstance(sidecar_payload, dict):
        raise RuntimeError("Mesh .NET experiment sidecar is not a JSON object.")
    original_asset_hash = str(sidecar_payload.get("source_asset_hash", "") or "")
    original_asset_hash_path = package_dir / "original_asset_hash.txt"
    original_asset_hash_path.write_text(original_asset_hash, encoding="utf-8")
    net_materials_path = package_dir / "net_materials.json"
    _write_dotnet_material_manifest(net_materials_path, mesh=mesh, sidecar_payload=sidecar_payload)

    output_dir = package_dir / "output"
    output_dir.mkdir()
    status_path = package_dir / "dotnet_status.json"
    edit_operations_path = output_dir / "edit_operations.json"
    launch_manifest_path = package_dir / "dotnet_launch.json"

    package = MeshDotNetExperimentPackage(
        package_dir=package_dir,
        mesh_path=mesh_path,
        obj_sidecar_path=obj_sidecar_path,
        cdmeta_path=cdmeta_path,
        original_asset_hash_path=original_asset_hash_path,
        status_path=status_path,
        output_dir=output_dir,
        edit_operations_path=edit_operations_path,
        launch_manifest_path=launch_manifest_path,
    )
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    launch_manifest_path.write_text(
        json.dumps(
            {
                "format": "cdmw_mesh_dotnet_experiment_handoff_v1",
                "authority": "python_cpp_mesh_editor_v2",
                "parser_authority": "cdmw_python_cpp",
                "rebuild_authority": "cdmw_python_cpp",
                "executable": "",
                "arguments": [],
                "embedded": False,
                "parent_hwnd": 0,
                "created_at": created_at,
                "launch": {
                    "executable": "",
                    "arguments": [],
                    "embedded": False,
                    "parent_hwnd": 0,
                    "created_at": created_at,
                },
                "input": {
                    "mesh": mesh_path.name,
                    "metadata": cdmeta_path.name,
                    "obj_sidecar": obj_sidecar_path.name,
                    "original_asset_hash": original_asset_hash_path.name,
                    "materials": net_materials_path.name,
                },
                "output": {
                    "directory": output_dir.name,
                    "edit_operations": str(edit_operations_path.relative_to(package_dir)),
                    "status": status_path.name,
                    "evaluation": "dotnet_evaluation.md",
                },
                "package": {key: str(value) for key, value in asdict(package).items()},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return package


def mesh_dotnet_experiment_command(
    executable_path: Path | str,
    package: MeshDotNetExperimentPackage,
    *,
    embedded_parent_hwnd: int = 0,
) -> tuple[str, list[str]]:
    executable = Path(executable_path)
    if not str(executable).strip():
        raise ValueError("Mesh .NET editor experiment executable is not configured.")
    args = [
        "--input-package",
        str(package.package_dir),
        "--mesh",
        str(package.mesh_path),
        "--metadata",
        str(package.cdmeta_path),
        "--status",
        str(package.status_path),
        "--output",
        str(package.output_dir),
        "--edit-operations",
        str(package.edit_operations_path),
        "--evaluation",
        str(mesh_dotnet_experiment_evaluation_path(package)),
    ]
    if int(embedded_parent_hwnd or 0) > 0:
        args.extend(["--embedded", "--parent-hwnd", str(int(embedded_parent_hwnd))])
    return (
        str(executable),
        args,
    )


def write_mesh_dotnet_launch_manifest(
    package: MeshDotNetExperimentPackage,
    *,
    executable: Path | str,
    arguments: Sequence[object],
    embedded: bool,
    parent_hwnd: int,
) -> Path:
    payload: dict[str, object] = {}
    if package.launch_manifest_path.is_file():
        try:
            loaded = json.loads(package.launch_manifest_path.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                payload = loaded
        except (OSError, ValueError):
            payload = {}
    created_at = str(payload.get("created_at", "") or "").strip()
    if not created_at:
        created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    launch = {
        "executable": str(executable),
        "arguments": [str(argument) for argument in tuple(arguments or ())],
        "embedded": bool(embedded),
        "parent_hwnd": int(parent_hwnd or 0),
        "created_at": created_at,
    }
    payload.update(launch)
    payload["launch"] = launch
    package.launch_manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return package.launch_manifest_path


def write_mesh_dotnet_launch_diagnostics(
    package: MeshDotNetExperimentPackage,
    payload: Mapping[str, object],
) -> Path:
    path = package.package_dir / "dotnet_launch_diagnostics.json"
    diagnostics = dict(payload or {})
    diagnostics.setdefault("created_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    path.write_text(json.dumps(diagnostics, indent=2, default=str), encoding="utf-8")
    return path


def mesh_dotnet_experiment_evaluation_path(package: MeshDotNetExperimentPackage) -> Path:
    return package.package_dir / "dotnet_evaluation.md"


def write_mesh_dotnet_experiment_evaluation(
    package: MeshDotNetExperimentPackage,
    status_payload: Mapping[str, object] | None = None,
    *,
    validation_report: object | None = None,
) -> Path:
    path = mesh_dotnet_experiment_evaluation_path(package)
    payload = status_payload or {}
    event = str(payload.get("event", "") or "closed").strip().lower()
    dotnet_metrics = _metrics_mapping(payload, "metrics", "dotnet_metrics")
    native_metrics = _metrics_mapping(payload, "native_baseline", "baseline", "python_cpp_baseline")
    validation_ok = _validation_ok(validation_report)
    blocker_count = _sequence_len(getattr(validation_report, "blockers", None))
    warning_count = _sequence_len(getattr(validation_report, "warnings", None))
    recommendation = _dotnet_recommendation(event, dotnet_metrics, native_metrics, validation_ok)
    path.write_text(
        "\n".join(
            [
                "# Mesh .NET Editor Evaluation",
                "",
                f"Package: `{package.package_dir}`",
                f"Status event: `{event or 'closed'}`",
                f"Output validation: `{_validation_label(validation_ok)}`",
                f"Validation blockers: {blocker_count if blocker_count is not None else 'not run'}",
                f"Validation warnings: {warning_count if warning_count is not None else 'not run'}",
                "",
                "| Area | Python/C++ Editor | .NET Experiment |",
                "|---|---:|---:|",
                f"| FPS | {_metric_text(native_metrics, 'fps', 'average_fps', 'avg_fps')} | {_metric_text(dotnet_metrics, 'fps', 'average_fps', 'avg_fps')} |",
                f"| Frame time ms | {_metric_text(native_metrics, 'frame_time_ms', 'average_frame_time_ms', 'avg_frame_time_ms')} | {_metric_text(dotnet_metrics, 'frame_time_ms', 'average_frame_time_ms', 'avg_frame_time_ms')} |",
                f"| UI responsiveness ms | {_metric_text(native_metrics, 'responsiveness_ms', 'input_latency_ms')} | {_metric_text(dotnet_metrics, 'responsiveness_ms', 'input_latency_ms')} |",
                f"| Crash behavior | {_metric_text(native_metrics, 'crash_behavior', 'crash_rate')} | {_dotnet_crash_text(event, dotnet_metrics)} |",
                f"| Memory MB | {_metric_text(native_metrics, 'memory_mb', 'working_set_mb')} | {_metric_text(dotnet_metrics, 'memory_mb', 'working_set_mb')} |",
                f"| Packaging complexity | {_metric_text(native_metrics, 'packaging_complexity', default='bundled Python/C++ path')} | {_metric_text(dotnet_metrics, 'packaging_complexity', default='bundled external process; parser/rebuilder stay Python/C++')} |",
                f"| Maintenance complexity | {_metric_text(native_metrics, 'maintenance_complexity', default='current authority')} | {_metric_text(dotnet_metrics, 'maintenance_complexity', default='UI-only bridge; parser/rebuilder remain Python/C++')} |",
                "",
                f"Keep/drop Recommendation: **{recommendation}**",
                "",
                "Notes:",
                "- Python/C++ remains the parser, validator, rebuilder, and package authority.",
                "- Missing metrics mean the .NET prototype has not produced enough evidence for a migration decision.",
                "- A validation failure means the edited output is not rebuildable, regardless of viewport performance.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def mesh_dotnet_experiment_output_obj_path(
    package: MeshDotNetExperimentPackage,
    status_payload: Mapping[str, object] | None = None,
) -> Path | None:
    """Return the edited OBJ produced by the external .NET experiment, if any."""
    payload = status_payload or {}
    candidates: list[Path] = []
    for key in ("edited_mesh", "edited_obj", "output_mesh"):
        raw_value = str(payload.get(key, "") or "").strip()
        if raw_value:
            candidates.append(_resolve_package_path(package, raw_value))
    edited_package = str(payload.get("edited_package", "") or "").strip()
    if edited_package:
        edited_path = _resolve_package_path(package, edited_package)
        if edited_path.is_file():
            candidates.append(edited_path)
        elif edited_path.is_dir():
            candidates.extend(_obj_candidates_in_dir(edited_path))
    candidates.extend(_obj_candidates_in_dir(package.output_dir))

    for candidate in candidates:
        if candidate.suffix.casefold() != ".obj":
            continue
        if _same_path(candidate, package.mesh_path):
            continue
        if candidate.is_file():
            return candidate
    return None


def import_mesh_dotnet_experiment_output(
    package: MeshDotNetExperimentPackage,
    status_payload: Mapping[str, object] | None = None,
) -> ParsedMesh | None:
    """Import the edited .NET output through the existing OBJ sidecar contract."""
    obj_path = mesh_dotnet_experiment_output_obj_path(package, status_payload)
    if obj_path is None:
        return None
    _ensure_output_sidecar(package, obj_path)
    mesh = import_obj(str(obj_path))
    operation_path = _dotnet_edit_operations_path(package, status_payload)
    if not operation_path.is_file():
        raise ValueError("Mesh .NET output is missing authoritative edit operation records.")
    operations = _load_dotnet_edit_operations(operation_path)
    if not operations:
        raise ValueError("Mesh .NET output has no authoritative edit operation records.")
    issues = validate_mesh_edit_operations(operations, mesh=mesh)
    blockers = tuple(issue for issue in issues if issue.severity == "blocker")
    if blockers:
        raise ValueError(blockers[0].message)
    setattr(mesh, "_cdmw_edit_operations", mesh_edit_operations_to_dicts(operations))
    setattr(mesh, "_cdmw_dotnet_authority_contract", "dotnet_viewport_python_cpp_validation")
    return mesh


def _resolve_package_path(package: MeshDotNetExperimentPackage, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else package.package_dir / path


def _obj_candidates_in_dir(directory: Path) -> tuple[Path, ...]:
    return (
        directory / "mesh.obj",
        directory / "edited_mesh.obj",
        directory / "edited.obj",
    )


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


def _ensure_output_sidecar(package: MeshDotNetExperimentPackage, obj_path: Path) -> None:
    sidecar_path = Path(f"{obj_path}.meta.json")
    if sidecar_path.is_file():
        return
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(package.obj_sidecar_path, sidecar_path)


def _dotnet_edit_operations_path(
    package: MeshDotNetExperimentPackage,
    status_payload: Mapping[str, object] | None,
) -> Path:
    raw_value = str((status_payload or {}).get("edit_operations", "") or "").strip()
    return _resolve_package_path(package, raw_value) if raw_value else package.edit_operations_path


def _load_dotnet_edit_operations(path: Path) -> tuple[object, ...]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict):
        payload = payload.get("operations", ())
    if not isinstance(payload, list):
        raise ValueError("Mesh .NET edit operations must be a JSON list.")
    return mesh_edit_operations_from_dicts(payload)


def _metrics_mapping(payload: Mapping[str, object], *keys: str) -> Mapping[str, object]:
    for key in keys:
        raw_value = payload.get(key)
        if isinstance(raw_value, Mapping):
            return raw_value
    return {}


def _metric_text(metrics: Mapping[str, object], *keys: str, default: str = "not reported") -> str:
    for key in keys:
        value = metrics.get(key)
        if value is None or value == "":
            continue
        return str(value)
    return default


def _metric_float(metrics: Mapping[str, object], *keys: str) -> float | None:
    for key in keys:
        value = metrics.get(key)
        if isinstance(value, bool):
            continue
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            continue
        return number
    return None


def _validation_ok(validation_report: object | None) -> bool | None:
    if validation_report is None:
        return None
    return bool(getattr(validation_report, "ok", False))


def _validation_label(value: bool | None) -> str:
    if value is True:
        return "passed"
    if value is False:
        return "blocked"
    return "not run"


def _sequence_len(value: object) -> int | None:
    if value is None:
        return None
    try:
        return len(tuple(value))  # type: ignore[arg-type]
    except TypeError:
        return None


def _dotnet_crash_text(event: str, dotnet_metrics: Mapping[str, object]) -> str:
    if event in {"error", "crash", "crashed"}:
        return "failed"
    return _metric_text(dotnet_metrics, "crash_behavior", "crash_rate", default="no crash reported")


def _dotnet_recommendation(
    event: str,
    dotnet_metrics: Mapping[str, object],
    native_metrics: Mapping[str, object],
    validation_ok: bool | None,
) -> str:
    if event in {"error", "crash", "crashed"}:
        return "drop .NET output for this run; the external editor reported failure"
    if validation_ok is False:
        return "drop .NET output for this run; validation blocked rebuild"
    dotnet_fps = _metric_float(dotnet_metrics, "average_fps", "avg_fps", "fps")
    native_fps = _metric_float(native_metrics, "average_fps", "avg_fps", "fps")
    if dotnet_fps is None:
        return "keep as experiment only; .NET FPS/frame metrics were not reported"
    if native_fps is None:
        return "keep as experiment only; no Python/C++ baseline was reported"
    if validation_ok is True and dotnet_fps >= native_fps * 1.1:
        return "keep .NET experiment for more testing; reported FPS beats baseline and validation passed"
    return "keep Python/C++ editor as default; .NET has not beaten the baseline enough"


__all__ = [
    "MESH_DOTNET_EXPERIMENT_BINARY_NAME",
    "MeshDotNetExecutableResolution",
    "MeshDotNetExperimentPackage",
    "build_mesh_dotnet_experiment_package",
    "default_mesh_dotnet_experiment_editor_path",
    "find_mesh_dotnet_experiment_editor",
    "resolve_mesh_dotnet_experiment_editor",
    "import_mesh_dotnet_experiment_output",
    "mesh_dotnet_experiment_command",
    "mesh_dotnet_experiment_evaluation_path",
    "mesh_dotnet_experiment_output_obj_path",
    "write_mesh_dotnet_experiment_evaluation",
    "write_mesh_dotnet_launch_diagnostics",
    "write_mesh_dotnet_launch_manifest",
]
