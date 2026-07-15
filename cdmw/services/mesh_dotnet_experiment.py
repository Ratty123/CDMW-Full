"""Connected handoff package for the Mesh Editor .NET experiment."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from uuid import uuid4
from dataclasses import dataclass, asdict, replace
from pathlib import Path, PurePosixPath

from cdmw.core.atomic_file import atomic_copy_file, atomic_write_text
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.mesh.operations import (
    mesh_edit_operations_from_dicts,
    mesh_edit_operations_to_dicts,
    validate_mesh_edit_operations,
)
from cdmw.modding.mesh_exporter import export_obj
from cdmw.modding.mesh_deformer import clone_mesh_for_editing
from cdmw.modding.mesh_edit_ops import refresh_mesh_totals
from cdmw.modding.mesh_obj_importer import import_obj
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.modding.static_mesh_scene_frame import (
    StaticMeshSceneFrame,
    StaticSceneRoleFrame,
    StaticWorldBounds,
    build_authoritative_static_scene_frame,
    static_scene_source_identity,
)
from cdmw.modding.static_mesh_types import StaticReplacementTransform
from cdmw.services.mesh_dotnet_material_state import (
    _dotnet_manifest_resource_bindings,
    _dotnet_initial_material_parameters,
    _dotnet_material_channel_components,
    _dotnet_material_normal_y_policy,
    _dotnet_material_input_channels,
    _dotnet_material_semantic_contract,
    _dotnet_resolved_texture_channels,
    _source_file_stat_key,
    mesh_dotnet_material_input_signature,
    mesh_dotnet_material_state_payload,
)
from cdmw.services.mesh_dotnet_material_package import (
    _copy_dotnet_texture_channel_resources,
    _dotnet_texture_channels,
    _write_dotnet_material_manifest,
)
from cdmw.services.mesh_dotnet_runtime_status import (
    MESH_DOTNET_HELPER_MANIFEST_NAME,
    mesh_dotnet_experiment_evaluation_path,
    mesh_dotnet_helper_provenance_blockers,
    mesh_dotnet_material_parity_warnings,
    mesh_dotnet_renderer_blockers,
    write_mesh_dotnet_experiment_evaluation,
)


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
    material_signature: str = ""
    scene_mesh_path: Path | None = None
    scene_manifest_path: Path | None = None
    editable_submesh_count: int = 0
    reference_submesh_count: int = 0
    scene_frame: StaticMeshSceneFrame | None = None
    scene_session_id: str = ""


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


def _mesh_scene_bounds(meshes: Sequence[ParsedMesh]) -> tuple[list[float], list[float]]:
    vertices = [
        vertex
        for mesh in meshes
        for submesh in tuple(getattr(mesh, "submeshes", ()) or ())
        for vertex in tuple(getattr(submesh, "vertices", ()) or ())
        if len(vertex) >= 3
    ]
    if not vertices:
        return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    return (
        [min(float(vertex[axis]) for vertex in vertices) for axis in range(3)],
        [max(float(vertex[axis]) for vertex in vertices) for axis in range(3)],
    )


def _build_dotnet_scene_mesh(mesh: ParsedMesh, reference_mesh: ParsedMesh | None) -> ParsedMesh:
    scene_mesh = clone_mesh_for_editing(mesh)
    if reference_mesh is not None:
        reference = clone_mesh_for_editing(reference_mesh)
        for index, submesh in enumerate(reference.submeshes):
            submesh.name = f"original_reference_{index}_{submesh.name or 'part'}"
        scene_mesh.submeshes.extend(reference.submeshes)
    refresh_mesh_totals(scene_mesh)
    return scene_mesh


def _shutdown_dotnet_native_export_service() -> None:
    from cdmw.modding.mesh_native_core import shutdown_native_mesh_core_service

    shutdown_native_mesh_core_service()


def _export_dotnet_obj_paths(mesh: ParsedMesh, package_dir: Path, name: str) -> tuple[Path, ...]:
    try:
        return tuple(Path(path) for path in export_obj(mesh, str(package_dir), name))
    except RuntimeError as exc:
        if str(exc) != "native OBJ export failed and Python export fallback was blocked":
            raise
        _shutdown_dotnet_native_export_service()
        return tuple(Path(path) for path in export_obj(mesh, str(package_dir), name))


def _write_dotnet_scene_manifest(
    path: Path,
    *,
    scene_frame: StaticMeshSceneFrame,
    session_id: str = "",
) -> None:
    payload = scene_frame.to_protocol_payload()
    payload["renderer_authority"] = "dotnet_vortice_resident_scene"
    payload["session_id"] = str(session_id or "")
    atomic_write_text(path, json.dumps(payload, indent=2))


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
                ("exe_root_internal_flat", exe_root / "_internal" / "native" / MESH_DOTNET_EXPERIMENT_BINARY_NAME),
                (
                    "exe_root_release",
                    exe_root / "native" / "cdmw_mesh_dotnet_editor" / "build" / "Release" / MESH_DOTNET_EXPERIMENT_BINARY_NAME,
                ),
                (
                    "exe_root_internal_release",
                    exe_root
                    / "_internal"
                    / "native"
                    / "cdmw_mesh_dotnet_editor"
                    / "build"
                    / "Release"
                    / MESH_DOTNET_EXPERIMENT_BINARY_NAME,
                ),
                (
                    "exe_root_debug",
                    exe_root / "native" / "cdmw_mesh_dotnet_editor" / "build" / "Debug" / MESH_DOTNET_EXPERIMENT_BINARY_NAME,
                ),
                (
                    "exe_root_internal_debug",
                    exe_root
                    / "_internal"
                    / "native"
                    / "cdmw_mesh_dotnet_editor"
                    / "build"
                    / "Debug"
                    / MESH_DOTNET_EXPERIMENT_BINARY_NAME,
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
    reference_mesh: ParsedMesh | None = None,
    comparison_mode: str = "side_by_side",
    interaction_mode: str = "placement",
    scene_transform: StaticReplacementTransform | None = None,
    scene_generation: int = 1,
    scene_session_id: str = "",
    selection_pivot_source: tuple[float, float, float] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> MeshDotNetExperimentPackage:
    material_signature = mesh_dotnet_material_input_signature(mesh)
    root = Path(output_root) if output_root is not None else Path(tempfile.gettempdir()) / "cdmw_mesh_dotnet_experiment"
    package_dir = root / f"package_{int(time.time() * 1000)}_{uuid4().hex[:8]}"
    package_dir.mkdir(parents=True, exist_ok=False)

    exported_paths = _export_dotnet_obj_paths(mesh, package_dir, "mesh")
    mesh_path = package_dir / "mesh.obj"
    obj_sidecar_path = package_dir / "mesh.obj.meta.json"
    if mesh_path not in exported_paths or not mesh_path.is_file():
        raise RuntimeError("Mesh .NET experiment package did not create mesh.obj.")
    if obj_sidecar_path not in exported_paths or not obj_sidecar_path.is_file():
        raise RuntimeError("Mesh .NET experiment package did not create mesh.obj.meta.json.")

    cdmeta_path = package_dir / "mesh.cdmeta.json"
    atomic_copy_file(obj_sidecar_path, cdmeta_path)
    sidecar_payload = json.loads(cdmeta_path.read_text(encoding="utf-8"))
    if not isinstance(sidecar_payload, dict):
        raise RuntimeError("Mesh .NET experiment sidecar is not a JSON object.")
    original_asset_hash = str(sidecar_payload.get("source_asset_hash", "") or "")
    original_asset_hash_path = package_dir / "original_asset_hash.txt"
    atomic_write_text(original_asset_hash_path, original_asset_hash)
    net_materials_path = package_dir / "net_materials.json"

    editable_submesh_count = len(tuple(getattr(mesh, "submeshes", ()) or ()))
    reference_submesh_count = len(tuple(getattr(reference_mesh, "submeshes", ()) or ())) if reference_mesh is not None else 0
    scene_mesh = _build_dotnet_scene_mesh(mesh, reference_mesh)
    scene_mesh_path = package_dir / "scene.obj"
    scene_sidecar_path = package_dir / "scene.obj.meta.json"
    if reference_mesh is None:
        mesh_mtl_path = package_dir / "mesh.mtl"
        scene_mtl_path = package_dir / "scene.mtl"
        mesh_obj_text = mesh_path.read_text(encoding="utf-8")
        atomic_write_text(
            scene_mesh_path,
            mesh_obj_text.replace("mtllib mesh.mtl", "mtllib scene.mtl", 1),
        )
        atomic_copy_file(mesh_mtl_path, scene_mtl_path)
        scene_sidecar_payload = dict(sidecar_payload)
        scene_sidecar_payload["export_path"] = scene_mesh_path.name
        scene_sidecar_payload["companion_filename"] = scene_mtl_path.name
        atomic_write_text(scene_sidecar_path, json.dumps(scene_sidecar_payload, indent=2))
    else:
        scene_exported_paths = _export_dotnet_obj_paths(scene_mesh, package_dir, "scene")
        if scene_mesh_path not in scene_exported_paths or not scene_mesh_path.is_file():
            raise RuntimeError("Mesh .NET experiment package did not create scene.obj.")
        if scene_sidecar_path not in scene_exported_paths or not scene_sidecar_path.is_file():
            raise RuntimeError("Mesh .NET experiment package did not create scene.obj.meta.json.")
        scene_sidecar_payload = json.loads(scene_sidecar_path.read_text(encoding="utf-8"))
    if not isinstance(scene_sidecar_payload, dict):
        raise RuntimeError("Mesh .NET experiment scene sidecar is not a JSON object.")
    try:
        _write_dotnet_material_manifest(
            net_materials_path,
            mesh=scene_mesh,
            sidecar_payload=scene_sidecar_payload,
            material_signature=material_signature,
            editable_submesh_count=editable_submesh_count,
            cancelled=cancelled,
        )
    except RunCancelled:
        shutil.rmtree(package_dir, ignore_errors=True)
        raise
    if cancelled is not None and cancelled():
        shutil.rmtree(package_dir, ignore_errors=True)
        raise RunCancelled("Mesh .NET experiment package cancelled.")
    scene_manifest_path = package_dir / "dotnet_scene.json"
    target_frame_mesh = reference_mesh if reference_mesh is not None else mesh
    try:
        scene_frame = build_authoritative_static_scene_frame(
            target_frame_mesh,
            mesh,
            scene_transform
            or StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
            source_identity=static_scene_source_identity(mesh, reference_mesh),
            scene_generation=scene_generation,
            comparison_mode=comparison_mode,
            interaction_mode=interaction_mode,
            selection_pivot_source=selection_pivot_source,
            cancelled=cancelled,
        )
    except RunCancelled:
        shutil.rmtree(package_dir, ignore_errors=True)
        raise
    if reference_mesh is None:
        empty_bounds = StaticWorldBounds((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        scene_frame = replace(
            scene_frame,
            reference=StaticSceneRoleFrame(
                role="reference",
                model_matrix=scene_frame.reference.model_matrix,
                world_bounds=empty_bounds,
                visible=False,
                submesh_indices=(),
            ),
            framing_bounds=scene_frame.editable.world_bounds,
            framing_extent=max(0.01, scene_frame.editable.world_bounds.extent),
        )
    _write_dotnet_scene_manifest(
        scene_manifest_path,
        scene_frame=scene_frame,
        session_id=scene_session_id,
    )

    output_dir = package_dir / "output"
    output_dir.mkdir()
    status_path = output_dir / "dotnet_status.json"
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
        material_signature=material_signature,
        scene_mesh_path=scene_mesh_path,
        scene_manifest_path=scene_manifest_path,
        editable_submesh_count=editable_submesh_count,
        reference_submesh_count=reference_submesh_count,
        scene_frame=scene_frame,
        scene_session_id=str(scene_session_id or ""),
    )
    _write_initial_dotnet_launch_manifest(package, net_materials_path, scene_mesh_path, scene_manifest_path)
    return package


def _write_initial_dotnet_launch_manifest(
    package: MeshDotNetExperimentPackage,
    net_materials_path: Path,
    scene_mesh_path: Path,
    scene_manifest_path: Path,
) -> None:
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    atomic_write_text(
        package.launch_manifest_path,
        json.dumps(
            {
                "format": "cdmw_mesh_dotnet_experiment_handoff_v1",
                "interchange_format": "obj_sidecar",
                "metadata_risk": True,
                "metadata_risk_reasons": [
                    "OBJ does not carry the full native PAC mesh metadata contract.",
                    "Python/C++ validation and edit operations remain authoritative before rebuild.",
                ],
                "requires_edit_operations": True,
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
                    "mesh": package.mesh_path.name,
                    "metadata": package.cdmeta_path.name,
                    "obj_sidecar": package.obj_sidecar_path.name,
                    "original_asset_hash": package.original_asset_hash_path.name,
                    "materials": net_materials_path.name,
                    "scene": scene_mesh_path.name,
                    "scene_state": scene_manifest_path.name,
                    "material_signature": package.material_signature,
                },
                "output": {
                    "directory": package.output_dir.name,
                    "edit_operations": str(package.edit_operations_path.relative_to(package.package_dir)),
                    "edit_operations_required": True,
                    "status": str(package.status_path.relative_to(package.package_dir)),
                    "evaluation": str(
                        mesh_dotnet_experiment_evaluation_path(package).relative_to(package.package_dir)
                    ),
                },
                "package": {
                    key: str(value)
                    for key, value in asdict(package).items()
                    if key != "scene_frame"
                },
            },
            indent=2,
        ),
    )


def mesh_dotnet_experiment_command(
    executable_path: Path | str,
    package: MeshDotNetExperimentPackage,
    *,
    embedded_parent_hwnd: int = 0,
    developer_renderer_fallback: bool = False,
) -> tuple[str, list[str]]:
    executable = Path(executable_path)
    if not str(executable).strip():
        raise ValueError("Mesh .NET editor experiment executable is not configured.")
    status_path = _resolve_package_output_path(package, package.status_path, label="status")
    edit_operations_path = _resolve_package_output_path(
        package, package.edit_operations_path, label="edit operations"
    )
    evaluation_path = _resolve_package_output_path(
        package, mesh_dotnet_experiment_evaluation_path(package), label="evaluation"
    )
    args = [
        "--input-package",
        str(package.package_dir),
        "--mesh",
        str(package.scene_mesh_path or package.mesh_path),
        "--metadata",
        str(package.cdmeta_path),
        "--status",
        str(status_path),
        "--output",
        str(package.output_dir),
        "--edit-operations",
        str(edit_operations_path),
        "--evaluation",
        str(evaluation_path),
    ]
    if int(embedded_parent_hwnd or 0) > 0:
        args.extend(["--embedded", "--parent-hwnd", str(int(embedded_parent_hwnd))])
    if bool(developer_renderer_fallback):
        args.append("--developer-renderer-fallback")
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
    atomic_write_text(package.launch_manifest_path, json.dumps(payload, indent=2))
    return package.launch_manifest_path


def write_mesh_dotnet_launch_diagnostics(
    package: MeshDotNetExperimentPackage,
    payload: Mapping[str, object],
) -> Path:
    path = package.package_dir / "dotnet_launch_diagnostics.json"
    diagnostics = dict(payload or {})
    diagnostics.setdefault("created_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    atomic_write_text(path, json.dumps(diagnostics, indent=2, default=str))
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
            candidates.append(_resolve_package_output_path(package, raw_value, label=key))
    edited_package = str(payload.get("edited_package", "") or "").strip()
    if edited_package:
        edited_path = _resolve_package_output_path(package, edited_package, label="edited_package")
        if edited_path.is_file():
            candidates.append(edited_path)
        elif edited_path.is_dir():
            candidates.extend(_obj_candidates_in_dir(edited_path))
    candidates.extend(_obj_candidates_in_dir(package.output_dir))

    for candidate in candidates:
        candidate = _resolve_package_output_path(package, candidate, label="edited OBJ")
        if candidate.suffix.casefold() != ".obj":
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
    operation_path = _dotnet_edit_operations_path(package, status_payload)
    if not operation_path.is_file():
        raise ValueError("Mesh .NET output is missing authoritative edit operation records.")
    operations = _load_dotnet_edit_operations(operation_path)
    if not operations:
        raise ValueError("Mesh .NET output has no authoritative edit operation records.")
    _ensure_output_sidecar(package, obj_path)
    mesh = import_obj(str(obj_path))
    issues = validate_mesh_edit_operations(operations, mesh=mesh)
    blockers = tuple(issue for issue in issues if issue.severity == "blocker")
    if blockers:
        raise ValueError(blockers[0].message)
    setattr(mesh, "_cdmw_edit_operations", mesh_edit_operations_to_dicts(operations))
    setattr(mesh, "_cdmw_dotnet_authority_contract", "dotnet_viewport_python_cpp_validation")
    return mesh


def _resolve_package_output_path(
    package: MeshDotNetExperimentPackage,
    value: Path | str,
    *,
    label: str,
) -> Path:
    raw_value = str(value or "").strip()
    if not raw_value or "\x00" in raw_value:
        raise ValueError(f"Mesh .NET {label} path is invalid.")
    normalized_value = raw_value.replace("\\", "/")
    if ".." in PurePosixPath(normalized_value).parts:
        raise ValueError(f"Mesh .NET {label} path contains traversal.")

    try:
        package_root = package.package_dir.resolve(strict=True)
        output_root = package.output_dir.resolve(strict=True)
        output_root.relative_to(package_root)
    except OSError as exc:
        raise ValueError("Mesh .NET package output directory is unavailable.") from exc
    except ValueError as exc:
        raise ValueError("Mesh .NET package output directory escapes its package root.") from exc
    if not output_root.is_dir():
        raise ValueError("Mesh .NET package output directory is unavailable.")

    raw_path = Path(normalized_value).expanduser()
    candidate = raw_path if raw_path.is_absolute() else output_root / raw_path
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(output_root)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Mesh .NET {label} path escapes the package output directory.") from exc

    input_paths = (package.mesh_path, package.scene_mesh_path)
    for input_path in input_paths:
        if input_path is None:
            continue
        try:
            input_resolved = Path(input_path).resolve(strict=False)
        except OSError:
            input_resolved = Path(input_path)
        physical_alias = False
        try:
            physical_alias = (
                resolved.is_file()
                and input_resolved.is_file()
                and os.path.samefile(resolved, input_resolved)
            )
        except OSError:
            pass
        if resolved == input_resolved or physical_alias:
            raise ValueError(f"Mesh .NET {label} path aliases an input OBJ.")
    return resolved


def _obj_candidates_in_dir(directory: Path) -> tuple[Path, ...]:
    return (
        directory / "mesh.obj",
        directory / "edited_mesh.obj",
        directory / "edited.obj",
    )


def _ensure_output_sidecar(package: MeshDotNetExperimentPackage, obj_path: Path) -> None:
    contained_obj_path = _resolve_package_output_path(package, obj_path, label="edited OBJ")
    sidecar_path = _resolve_package_output_path(
        package,
        Path(f"{contained_obj_path}.meta.json"),
        label="edited OBJ sidecar",
    )
    if sidecar_path.is_file():
        return
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_copy_file(package.obj_sidecar_path, sidecar_path)


def _dotnet_edit_operations_path(
    package: MeshDotNetExperimentPackage,
    status_payload: Mapping[str, object] | None,
) -> Path:
    raw_value = str((status_payload or {}).get("edit_operations", "") or "").strip()
    value = raw_value if raw_value else package.edit_operations_path
    return _resolve_package_output_path(package, value, label="edit_operations")


def _load_dotnet_edit_operations(path: Path) -> tuple[object, ...]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict):
        payload = payload.get("operations", ())
    if not isinstance(payload, list):
        raise ValueError("Mesh .NET edit operations must be a JSON list.")
    return mesh_edit_operations_from_dicts(payload)




__all__ = [
    "MESH_DOTNET_EXPERIMENT_BINARY_NAME",
    "MESH_DOTNET_HELPER_MANIFEST_NAME",
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
    "mesh_dotnet_helper_provenance_blockers",
    "mesh_dotnet_material_input_signature",
    "mesh_dotnet_material_state_payload",
    "mesh_dotnet_material_parity_warnings",
    "mesh_dotnet_renderer_blockers",
    "write_mesh_dotnet_experiment_evaluation",
    "write_mesh_dotnet_launch_diagnostics",
    "write_mesh_dotnet_launch_manifest",
]
