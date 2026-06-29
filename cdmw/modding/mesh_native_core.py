from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Optional

from cdmw.core.common import run_process_with_cancellation
from cdmw.modding.mesh_parser import ParsedMesh

NATIVE_MESH_CORE_BINARY_NAME = "cdmw-mesh-core.exe" if os.name == "nt" else "cdmw-mesh-core"
NATIVE_MESH_CORE_BACKEND_ID = "cdmw_mesh_core_0.1"

Vec3 = tuple[float, float, float]
Vec2 = tuple[float, float]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_native_mesh_core_path(*, release: bool = True) -> Path:
    config = "Release" if release else "Debug"
    return _repo_root() / "native" / "cdmw_mesh_core" / "build" / config / NATIVE_MESH_CORE_BINARY_NAME


def find_native_mesh_core_binary() -> Optional[Path]:
    env_path = os.environ.get("CDMW_MESH_CORE_BIN", "").strip()
    candidates = [Path(env_path)] if env_path else []
    frozen_root = Path(str(getattr(sys, "_MEIPASS", ""))) if getattr(sys, "_MEIPASS", "") else None
    exe_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    if frozen_root is not None:
        candidates.append(frozen_root / "native" / NATIVE_MESH_CORE_BINARY_NAME)
    if exe_root is not None:
        candidates.append(exe_root / "native" / NATIVE_MESH_CORE_BINARY_NAME)
    candidates.extend(
        [
            default_native_mesh_core_path(release=True),
            default_native_mesh_core_path(release=False),
            _repo_root() / "native" / "cdmw_mesh_core" / "bin" / NATIVE_MESH_CORE_BINARY_NAME,
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def native_mesh_core_available() -> bool:
    return find_native_mesh_core_binary() is not None


def apply_native_mesh_transform(
    mesh: ParsedMesh,
    vertices_by_submesh: Mapping[int, set[int]],
    *,
    translate: Vec3,
    scale: Vec3,
    rotate: Vec3,
    pivot: Vec3,
    snap: float = 0.0,
    timeout_seconds: float = 5.0,
) -> dict[int, set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    submeshes = []
    for submesh_index, selected in sorted(vertices_by_submesh.items()):
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        kept = sorted(index for index in selected if 0 <= index < len(submesh.vertices))
        if not kept:
            continue
        submeshes.append(
            {
                "index": submesh_index,
                "vertices": [_vec3_json(vertex) for vertex in submesh.vertices],
                "selected_vertices": kept,
            }
        )
    if not submeshes:
        return {}

    # ponytail: JSON process bridge is the first native seam; use a persistent library when command volume matters.
    report = _run_native_mesh_core_job(
        binary,
        "transform-json",
        {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "transform",
            "transform": {
                "translate": _vec3_json(translate),
                "scale": _vec3_json(scale, fallback=1.0),
                "rotate": _vec3_json(rotate),
                "pivot": _vec3_json(pivot),
                "snap": _finite_float(snap, 0.0),
            },
            "submeshes": submeshes,
        },
        timeout_seconds=timeout_seconds,
    )
    if report is None:
        return None
    return _apply_transform_report(mesh, report)


def apply_native_mesh_recalculate_normals(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    timeout_seconds: float = 5.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    submeshes = []
    for submesh_index in sorted(submesh_indices):
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        faces = _face_json(submesh.faces, len(submesh.vertices))
        if not submesh.vertices or not faces:
            continue
        submeshes.append(
            {
                "index": submesh_index,
                "vertices": [_vec3_json(vertex) for vertex in submesh.vertices],
                "faces": faces,
            }
        )
    if not submeshes:
        return set()

    report = _run_native_mesh_core_job(
        binary,
        "recalculate-normals-json",
        {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "recalculate_normals",
            "submeshes": submeshes,
        },
        timeout_seconds=timeout_seconds,
    )
    if report is None:
        return None
    return _apply_recalculate_normals_report(mesh, report)


def apply_native_mesh_uv_transform(
    mesh: ParsedMesh,
    vertices_by_submesh: Mapping[int, set[int]],
    *,
    offset: Vec2,
    scale: Vec2,
    rotate_degrees: float,
    flip_u: bool = False,
    flip_v: bool = False,
    pivot: Vec2 = (0.0, 0.0),
    timeout_seconds: float = 5.0,
) -> dict[int, set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    submeshes = []
    for submesh_index, selected in sorted(vertices_by_submesh.items()):
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        if len(submesh.uvs) != len(submesh.vertices):
            continue
        kept = sorted(index for index in selected if 0 <= index < len(submesh.uvs))
        if not kept:
            continue
        submeshes.append(
            {
                "index": submesh_index,
                "vertex_count": len(submesh.vertices),
                "uvs": [_vec2_json(uv) for uv in submesh.uvs],
                "selected_vertices": kept,
            }
        )
    if not submeshes:
        return {}

    report = _run_native_mesh_core_job(
        binary,
        "uv-transform-json",
        {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "uv_transform",
            "uv_transform": {
                "offset": _vec2_json(offset),
                "scale": _vec2_json(scale, fallback=1.0),
                "rotate": _finite_float(rotate_degrees, 0.0),
                "flip_u": bool(flip_u),
                "flip_v": bool(flip_v),
                "pivot": _vec2_json(pivot),
            },
            "submeshes": submeshes,
        },
        timeout_seconds=timeout_seconds,
    )
    if report is None:
        return None
    return _apply_uv_transform_report(mesh, report)


def _apply_transform_report(mesh: ParsedMesh, report: Mapping[str, object]) -> dict[int, set[int]] | None:
    changed: dict[int, set[int]] = {}
    submesh_reports = report.get("submeshes")
    if not isinstance(submesh_reports, list):
        return None
    for item in submesh_reports:
        if not isinstance(item, dict):
            continue
        submesh_index = _index(item.get("index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        vertices = item.get("vertices")
        changed_vertices = item.get("changed_vertices")
        if not isinstance(vertices, list) or not isinstance(changed_vertices, list):
            continue
        submesh = mesh.submeshes[submesh_index]
        if len(vertices) != len(submesh.vertices):
            return None
        parsed_vertices = [_vec3(value) for value in vertices]
        parsed_changed = {
            index
            for raw_index in changed_vertices
            for index in [_index(raw_index)]
            if index is not None and 0 <= index < len(parsed_vertices)
        }
        if parsed_changed:
            submesh.vertices = parsed_vertices
            submesh.vertex_count = len(parsed_vertices)
            changed[submesh_index] = parsed_changed
    return changed


def _apply_recalculate_normals_report(mesh: ParsedMesh, report: Mapping[str, object]) -> set[int] | None:
    affected: set[int] = set()
    submesh_reports = report.get("submeshes")
    if not isinstance(submesh_reports, list):
        return None
    for item in submesh_reports:
        if not isinstance(item, dict):
            continue
        submesh_index = _index(item.get("index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        normals = item.get("normals")
        if not isinstance(normals, list):
            continue
        submesh = mesh.submeshes[submesh_index]
        if len(normals) != len(submesh.vertices):
            return None
        before = tuple(_vec3(normal, fallback=0.0) for normal in submesh.normals or ())
        parsed_normals = [_vec3(value, fallback=0.0) for value in normals]
        submesh.normals = parsed_normals
        if not _same_vec3_tuple(before, tuple(parsed_normals)):
            affected.add(submesh_index)
    return affected


def _apply_uv_transform_report(mesh: ParsedMesh, report: Mapping[str, object]) -> dict[int, set[int]] | None:
    changed: dict[int, set[int]] = {}
    submesh_reports = report.get("submeshes")
    if not isinstance(submesh_reports, list):
        return None
    for item in submesh_reports:
        if not isinstance(item, dict):
            continue
        submesh_index = _index(item.get("index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        uvs = item.get("uvs")
        changed_vertices = item.get("changed_vertices")
        if not isinstance(uvs, list) or not isinstance(changed_vertices, list):
            continue
        submesh = mesh.submeshes[submesh_index]
        if len(uvs) != len(submesh.uvs):
            return None
        parsed_uvs = [_vec2(value) for value in uvs]
        parsed_changed = {
            index
            for raw_index in changed_vertices
            for index in [_index(raw_index)]
            if index is not None and 0 <= index < len(parsed_uvs)
        }
        if parsed_changed:
            submesh.uvs = parsed_uvs
            changed[submesh_index] = parsed_changed
    return changed


def _run_native_mesh_core_job(
    binary: Path,
    command: str,
    payload: Mapping[str, object],
    *,
    timeout_seconds: float,
) -> dict[str, object] | None:
    job_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_"))
    job_path = job_root / "job.json"
    report_path = job_root / "report.json"
    try:
        job_path.write_text(json.dumps(dict(payload), separators=(",", ":"), allow_nan=False), encoding="utf-8")
        returncode, _stdout, _stderr = run_process_with_cancellation(
            [str(binary), command, str(job_path), str(report_path)],
            timeout_seconds=max(0.5, float(timeout_seconds)),
        )
        if returncode != 0 or not report_path.is_file():
            return None
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(report, dict) or str(report.get("status") or "").lower() != "ok":
            return None
        return report
    except Exception:
        return None
    finally:
        shutil.rmtree(job_root, ignore_errors=True)


def _face_json(faces: object, vertex_count: int) -> list[list[int]]:
    result: list[list[int]] = []
    if not isinstance(faces, list):
        return result
    for face in faces:
        if not isinstance(face, (tuple, list)) or len(face) < 3:
            continue
        a = _index(face[0])
        b = _index(face[1])
        c = _index(face[2])
        if a is None or b is None or c is None:
            continue
        if 0 <= a < vertex_count and 0 <= b < vertex_count and 0 <= c < vertex_count:
            result.append([a, b, c])
    return result


def _vec3_json(value: object, fallback: float = 0.0) -> list[float]:
    parsed = _vec3(value, fallback=fallback)
    return [parsed[0], parsed[1], parsed[2]]


def _vec2_json(value: object, fallback: float = 0.0) -> list[float]:
    parsed = _vec2(value, fallback=fallback)
    return [parsed[0], parsed[1]]


def _vec3(value: object, *, fallback: float = 0.0) -> Vec3:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return (fallback, fallback, fallback)
    return (
        _finite_float(value[0], fallback),
        _finite_float(value[1], fallback),
        _finite_float(value[2], fallback),
    )


def _vec2(value: object, *, fallback: float = 0.0) -> Vec2:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return (fallback, fallback)
    return (
        _finite_float(value[0], fallback),
        _finite_float(value[1], fallback),
    )


def _finite_float(value: object, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return parsed if math.isfinite(parsed) else fallback


def _same_vec3(left: Vec3, right: Vec3) -> bool:
    return abs(left[0] - right[0]) <= 1e-8 and abs(left[1] - right[1]) <= 1e-8 and abs(left[2] - right[2]) <= 1e-8


def _same_vec3_tuple(left: tuple[Vec3, ...], right: tuple[Vec3, ...]) -> bool:
    return len(left) == len(right) and all(_same_vec3(left_item, right_item) for left_item, right_item in zip(left, right))


def _index(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        index = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return index


__all__ = [
    "NATIVE_MESH_CORE_BACKEND_ID",
    "NATIVE_MESH_CORE_BINARY_NAME",
    "apply_native_mesh_recalculate_normals",
    "apply_native_mesh_transform",
    "apply_native_mesh_uv_transform",
    "default_native_mesh_core_path",
    "find_native_mesh_core_binary",
    "native_mesh_core_available",
]
