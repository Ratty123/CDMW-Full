from __future__ import annotations

import atexit
from array import array
import dataclasses
import json
import math
import os
import struct
import subprocess
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence
from uuid import uuid4

from cdmw.core.common import ProcessTimeoutExpired, hidden_subprocess_kwargs, raise_if_cancelled, run_process_with_cancellation
from cdmw.modding.mesh_deformer import MeshFaceDeleteResult, MeshPartSplitResult, _EXTRA_SUBMESH_ATTRS, recompute_submesh_normals
from cdmw.modding.mesh_native_core_blend_helpers import (
    _apply_vertex_aligned_topology_result,
    _blend_bone_assignment,
    _clear_vertex_aligned_topology_result,
    _copy_blend_bone_lists,
    _copy_blend_scalar_list,
    _copy_blend_tuple_list,
    _copy_with_blend_default,
    _edge_list,
    _int_list,
    _mirror_pairs_json,
    _tuple_value,
    _vertex_blends,
    _vertex_weights_json,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.mesh_native_core_constants import (
    Face,
    NATIVE_MESH_CORE_BACKEND_ID,
    NATIVE_MESH_CORE_BINARY_NAME,
    NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR,
    Vec2,
    Vec3,
    _NATIVE_MATERIAL_REPORT_ATTRS,
    _NATIVE_MESH_EDITOR_NORMAL_OPERATIONS,
    _NATIVE_MESH_SESSION_TOKEN_ATTR,
    _NATIVE_PREVIEW_MATERIAL_OVERRIDE_KEYS,
    _TRANSIENT_NATIVE_SUBMESH_ATTRS,
)
from cdmw.modding import mesh_native_core_diagnostics as _native_mesh_core_diagnostics
from cdmw.modding import mesh_native_core_temp_paths as _native_mesh_core_temp_paths
from cdmw.modding.mesh_native_core_payload_helpers import (
    _copy_vertex_aligned_list,
    _face_count_json,
    _face_json,
    _face_json_with_source_indices,
    _finite_float,
    _finite_float_sequence,
    _finite_vec2_list_or_none,
    _finite_vec3_list_or_none,
    _index,
    _iter_valid_submesh_indices,
    _native_uv_transform_payload,
    _remap_vertex_aligned_list,
    _same_vec3,
    _same_vec3_tuple,
    _sorted_unique_valid_submesh_indices,
    _source_part_adjustment_payload,
    _source_part_adjustment_pivot_vertices,
    _valid_face_triplet,
    _vec2,
    _vec2_json,
    _vec3,
    _vec3_json,
)
from cdmw.models import RunCancelled

_native_mesh_core_session_cache_lock = threading.RLock()
_native_mesh_core_session_cache: dict[tuple[str, int], tuple[tuple[object, ...], str]] = {}
def _new_native_sparse_vertex_snapshot_id(role: str) -> str:
    return f"py-sparse-vertices-{role}-{uuid4().hex}"


def _clear_native_mesh_core_session_cache() -> None:
    with _native_mesh_core_session_cache_lock:
        _native_mesh_core_session_cache.clear()


def clear_native_mesh_core_fallback_counts() -> None:
    _native_mesh_core_diagnostics.clear_native_mesh_core_fallback_counts()


def native_mesh_core_fallback_counts() -> dict[str, int]:
    return _native_mesh_core_diagnostics.native_mesh_core_fallback_counts()


def native_mesh_core_fallback_events() -> tuple[dict[str, object], ...]:
    return _native_mesh_core_diagnostics.native_mesh_core_fallback_events()


def record_native_mesh_core_fallback(operation: object, reason: object = "", **details: object) -> None:
    _native_mesh_core_diagnostics.record_native_mesh_core_fallback(operation, reason, **details)


def _native_preview_delta_output_path(suffix: str = ".bin") -> str:
    return _native_mesh_core_temp_paths.native_preview_delta_output_path(suffix)


def _native_preview_delta_output_dir() -> str:
    return _native_mesh_core_temp_paths.native_preview_delta_output_dir()


def _cleanup_native_preview_delta_paths() -> None:
    _native_mesh_core_temp_paths.cleanup_native_preview_delta_paths()


def _native_mesh_core_count_hint(mesh: object, attr: str) -> int:
    try:
        value = int(getattr(mesh, attr, 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return value if value >= 0 else 0


def _native_mesh_core_service_enabled(*, stop_event: threading.Event | None = None) -> bool:
    return not os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE_SERVICE", "").strip()


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


class NativeMeshCoreServiceClient:
    """Persistent JSON-line client for cdmw-mesh-core.exe helper jobs."""

    def __init__(self, binary: Path) -> None:
        self.binary = Path(binary)
        self.binary_signature = self.resolve_binary_signature(self.binary)
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._jobs_completed = 0

    @staticmethod
    def resolve_binary_signature(binary: Path) -> tuple[int, int]:
        try:
            stat_result = Path(binary).stat()
        except OSError:
            return (0, 0)
        return (int(getattr(stat_result, "st_mtime_ns", 0) or 0), int(getattr(stat_result, "st_size", 0) or 0))

    def shutdown(self) -> None:
        with self._lock:
            _clear_native_mesh_core_session_cache()
            process = self._process
            self._process = None
            self._jobs_completed = 0
            if process is None:
                return
            try:
                if process.poll() is None and process.stdin is not None:
                    process.stdin.write('{"command":"shutdown"}\n')
                    process.stdin.flush()
            except OSError:
                pass
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except OSError:
                    pass

    def _kill_locked(self) -> None:
        _clear_native_mesh_core_session_cache()
        process = self._process
        self._process = None
        self._jobs_completed = 0
        if process is None:
            return
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass

    def _read_stdout_line_locked(self, timeout_seconds: float, *, stop_event: threading.Event | None = None) -> str:
        process = self._process
        if process is None or process.stdout is None:
            raise RuntimeError("native mesh-core service is not running")
        result: dict[str, object] = {}

        def read_line() -> None:
            try:
                result["line"] = process.stdout.readline()
            except Exception as exc:  # pragma: no cover - pipe teardown defense
                result["error"] = exc

        thread = threading.Thread(target=read_line, name="cdmw-mesh-core-readline", daemon=True)
        thread.start()
        deadline = time.monotonic() + max(0.1, float(timeout_seconds))
        while thread.is_alive():
            try:
                raise_if_cancelled(stop_event, "Native mesh-core job cancelled.")
            except RunCancelled:
                self._kill_locked()
                raise
            if time.monotonic() >= deadline:
                self._kill_locked()
                raise ProcessTimeoutExpired([str(self.binary), "--service"], float(timeout_seconds))
            thread.join(0.02)
        error = result.get("error")
        if isinstance(error, BaseException):
            raise RuntimeError(f"native mesh-core service read failed: {error}") from error
        line = str(result.get("line") or "").strip()
        if not line:
            self._kill_locked()
            raise RuntimeError("native mesh-core service closed its stdout")
        return line

    def _start_locked(self, *, stop_event: threading.Event | None = None) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            return
        _clear_native_mesh_core_session_cache()
        self._jobs_completed = 0
        self._process = subprocess.Popen(
            [str(self.binary), "--service"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_kwargs(),
        )
        ready_line = self._read_stdout_line_locked(5.0, stop_event=stop_event)
        try:
            ready = json.loads(ready_line)
        except json.JSONDecodeError as exc:
            self._kill_locked()
            raise RuntimeError(f"native mesh-core service sent invalid ready line: {ready_line}") from exc
        if str(ready.get("event") or "").strip().lower() != "ready":
            self._kill_locked()
            raise RuntimeError(f"native mesh-core service did not become ready: {ready_line}")

    def run_job(
        self,
        command: str,
        job_path: Path,
        report_path: Path,
        *,
        timeout_seconds: float,
        stop_event: threading.Event | None = None,
    ) -> None:
        with self._lock:
            self._start_locked(stop_event=stop_event)
            process = self._process
            if process is None or process.stdin is None:
                raise RuntimeError("native mesh-core service stdin is unavailable")
            request = json.dumps(
                {"command": command, "job_path": str(job_path), "report_path": str(report_path)},
                separators=(",", ":"),
            )
            try:
                process.stdin.write(request + "\n")
                process.stdin.flush()
            except OSError as exc:
                self._kill_locked()
                raise RuntimeError(f"native mesh-core service write failed: {exc}") from exc
            response_line = self._read_stdout_line_locked(timeout_seconds, stop_event=stop_event)
            try:
                response = json.loads(response_line)
            except json.JSONDecodeError as exc:
                self._kill_locked()
                raise RuntimeError(f"native mesh-core service sent invalid response: {response_line}") from exc
            response_status = str(response.get("status") or response.get("event") or "").strip().lower()
            if response_status == "error" and not report_path.is_file():
                raise RuntimeError(str(response.get("message") or "native mesh-core service returned an error"))
            self._jobs_completed += 1

    def run_inline_job(
        self,
        command: str,
        payload: Mapping[str, object],
        *,
        timeout_seconds: float,
        stop_event: threading.Event | None = None,
    ) -> dict[str, object]:
        with self._lock:
            self._start_locked(stop_event=stop_event)
            process = self._process
            if process is None or process.stdin is None:
                raise RuntimeError("native mesh-core service stdin is unavailable")
            request = json.dumps(
                {"command": command, "payload": dict(payload)},
                separators=(",", ":"),
                allow_nan=False,
            )
            try:
                process.stdin.write(request + "\n")
                process.stdin.flush()
            except OSError as exc:
                self._kill_locked()
                raise RuntimeError(f"native mesh-core service write failed: {exc}") from exc
            response_line = self._read_stdout_line_locked(timeout_seconds, stop_event=stop_event)
            try:
                response = json.loads(response_line)
            except json.JSONDecodeError as exc:
                self._kill_locked()
                raise RuntimeError(f"native mesh-core service sent invalid response: {response_line}") from exc
            if not isinstance(response, dict):
                self._kill_locked()
                raise RuntimeError("native mesh-core service sent non-object response")
            response_status = str(response.get("status") or response.get("event") or "").strip().lower()
            if response_status == "error" and not isinstance(response.get("inline_report"), Mapping):
                raise RuntimeError(str(response.get("message") or "native mesh-core service returned an error"))
            self._jobs_completed += 1
            return response


_native_mesh_core_service_lock = threading.RLock()
_native_mesh_core_service: NativeMeshCoreServiceClient | None = None


def _get_native_mesh_core_service(binary: Path) -> NativeMeshCoreServiceClient:
    global _native_mesh_core_service
    with _native_mesh_core_service_lock:
        resolved_binary = Path(binary)
        binary_signature = NativeMeshCoreServiceClient.resolve_binary_signature(resolved_binary)
        if (
            _native_mesh_core_service is None
            or _native_mesh_core_service.binary != resolved_binary
            or _native_mesh_core_service.binary_signature != binary_signature
        ):
            if _native_mesh_core_service is not None:
                _native_mesh_core_service.shutdown()
            _native_mesh_core_service = NativeMeshCoreServiceClient(resolved_binary)
        return _native_mesh_core_service


def _native_mesh_core_service_running(binary: Path) -> bool:
    with _native_mesh_core_service_lock:
        service = _native_mesh_core_service
        if service is None or service.binary != Path(binary):
            return False
        process = service._process
        return process is not None and process.poll() is None


def _native_mesh_core_service_known_for_binary(binary: Path) -> bool:
    with _native_mesh_core_service_lock:
        service = _native_mesh_core_service
        return service is not None and service.binary == Path(binary)


def shutdown_native_mesh_core_service() -> None:
    global _native_mesh_core_service
    with _native_mesh_core_service_lock:
        if _native_mesh_core_service is not None:
            _native_mesh_core_service.shutdown()
            _native_mesh_core_service = None


def write_native_preview_identity_blob(
    output_path: Path | str,
    *,
    source_submesh_index: int,
    vertex_count: int,
    source_vertex_indices: Sequence[int] = (),
    source_face_indices: Sequence[int] = (),
    source_vertex_indices_binary: Mapping[str, object] | None = None,
    source_face_indices_binary: Mapping[str, object] | None = None,
    source_vertex_start: int | None = None,
    source_vertex_count: int = 0,
    source_face_start: int | None = None,
    source_face_count: int = 0,
    role: str = "",
    part_name: str = "",
    editable: bool = True,
    append: bool = True,
    timeout_seconds: float = 5.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    path = Path(output_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    payload: dict[str, object] = {
        "version": 1,
        "backend": NATIVE_MESH_CORE_BACKEND_ID,
        "operation": "preview_identity",
        "output_path": str(path),
        "append": bool(append),
        "source_submesh_index": int(source_submesh_index),
        "vertex_count": max(0, int(vertex_count)),
        "role": str(role or ""),
        "part_name": str(part_name or ""),
        "editable": bool(editable),
    }
    sidecar_root: Path | None = None
    try:
        source_vertex_descriptor = _native_i32_descriptor(source_vertex_indices_binary)
        if source_vertex_descriptor is not None:
            payload["source_vertex_indices_binary"] = source_vertex_descriptor
        elif source_vertex_start is not None and int(source_vertex_start) >= 0 and int(source_vertex_count) > 0:
            payload["source_vertex_start"] = int(source_vertex_start)
            payload["source_vertex_count"] = int(source_vertex_count)
        else:
            sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_preview_identity_"))
            payload["source_vertex_indices_binary"] = _write_int_binary_payload(
                sidecar_root / "source_vertices.bin",
                source_vertex_indices if source_vertex_indices is not None else (),
            )
        source_face_descriptor = _native_i32_descriptor(source_face_indices_binary)
        if source_face_descriptor is not None:
            payload["source_face_indices_binary"] = source_face_descriptor
        elif source_face_start is not None and int(source_face_start) >= 0 and int(source_face_count) > 0:
            payload["source_face_start"] = int(source_face_start)
            payload["source_face_count"] = int(source_face_count)
        else:
            if sidecar_root is None:
                sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_preview_identity_"))
            payload["source_face_indices_binary"] = _write_int_binary_payload(
                sidecar_root / "source_faces.bin",
                source_face_indices if source_face_indices is not None else (),
            )
        return _run_native_mesh_core_job(
            binary,
            "preview-identity-json",
            payload,
            timeout_seconds=timeout_seconds,
        )
    finally:
        if sidecar_root is not None:
            shutil.rmtree(sidecar_root, ignore_errors=True)


def _native_i32_descriptor(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    path = str(value.get("path") or "").strip()
    if not path:
        return None
    try:
        count = int(value.get("count", 0) or 0)
        components = int(value.get("components", 1) or 1)
    except (TypeError, ValueError, OverflowError):
        return None
    if count < 0 or components != 1:
        return None
    if str(value.get("type") or "i32").strip().lower() != "i32":
        return None
    descriptor: dict[str, object] = {
        "path": path,
        "count": count,
        "components": 1,
        "type": "i32",
    }
    if bool(value.get("delete_after")):
        descriptor["delete_after"] = True
    return descriptor


def _native_i32_range_descriptor(value: object, *, max_count: int | None = None) -> tuple[int, int] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        raw_start = value.get("start", value.get("selected_vertex_start", value.get("source_vertex_start", -1)))
        raw_count = value.get("count", value.get("selected_vertex_count", value.get("source_vertex_count", 0)))
        start = int(raw_start if raw_start is not None else -1)
        count = int(raw_count if raw_count is not None else 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if start < 0 or count <= 0:
        return None
    if max_count is not None and start + count > max(0, int(max_count)):
        return None
    return start, count


def write_native_preview_geometry_blob(
    output_path: Path | str,
    *,
    meshes: Sequence[Mapping[str, object]],
    identity_output_path: Path | str | None = None,
    append: bool = False,
    timeout_seconds: float = 20.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    path = Path(output_path)
    identity_path = Path(identity_output_path) if identity_output_path is not None else None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if identity_path is not None:
            identity_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_preview_geometry_"))
    try:
        native_meshes: list[dict[str, object]] = []
        for mesh_index, mesh in enumerate(meshes if meshes is not None else ()):
            item = dict(mesh)
            prefix = sidecar_root / f"preview_geometry_{mesh_index}"
            if "positions" in item:
                item["positions_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_positions.bin"), item.pop("positions"))
            if "normals" in item:
                item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), item.pop("normals"))
            if "texture_coordinates" in item:
                item["texture_coordinates_binary"] = _write_vec2_binary_payload(
                    prefix.with_name(prefix.name + "_uvs.bin"),
                    item.pop("texture_coordinates"),
                )
            if "indices" in item:
                indices = item.pop("indices")
                item["indices_binary"] = _write_int_binary_payload(prefix.with_name(prefix.name + "_indices.bin"), indices if indices is not None else ())
            if "faces" in item:
                faces = item.pop("faces")
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces if faces is not None else ())
            if "source_vertex_indices" in item:
                source_vertices = item.pop("source_vertex_indices")
                _put_source_vertex_indices_payload(item, prefix, source_vertices if source_vertices is not None else ())
            if "source_face_indices" in item:
                source_faces = item.pop("source_face_indices")
                _put_source_face_indices_payload(item, prefix, source_faces if source_faces is not None else ())
            native_meshes.append(item)
        return _run_native_mesh_core_job(
            binary,
            "preview-geometry-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "preview_geometry",
                "output_path": str(path),
                "identity_output_path": str(identity_path) if identity_path is not None else "",
                "append": bool(append),
                "meshes": native_meshes,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def _native_obj_submesh_payloads(
    mesh: ParsedMesh,
    binary: Path,
    sidecar_root: Path,
    *,
    timeout_seconds: float,
) -> tuple[tuple[object, ...], list[dict[str, object]]]:
    raw_submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    submeshes: list[dict[str, object]] = []
    for submesh_index, submesh in enumerate(raw_submeshes):
        prefix = sidecar_root / f"obj_export_{submesh_index}"
        item: dict[str, object] = {
            "index": submesh_index,
            "name": str(getattr(submesh, "name", "") or ""),
            "material": str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or f"part_{submesh_index}"),
            "texture": str(getattr(submesh, "texture", "") or ""),
        }
        session_id = _ensure_native_mesh_session_submesh(
            binary,
            mesh,
            submesh_index,
            timeout_seconds=timeout_seconds,
        )
        if session_id:
            item["session_id"] = session_id
        else:
            vertices = tuple(getattr(submesh, "vertices", ()) or ())
            faces = _face_json(getattr(submesh, "faces", ()) or (), len(vertices))
            item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices)
            item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
            uvs = tuple(getattr(submesh, "uvs", ()) or ())
            if uvs:
                item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), uvs)
            normals = tuple(getattr(submesh, "normals", ()) or ())
            if normals:
                item["normals_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_normals.bin"),
                    normals,
                    fallback=0.0,
                )
            source_vertex_map = getattr(submesh, "source_vertex_map", ()) or ()
            if len(source_vertex_map) == len(vertices):
                _put_source_vertex_map_payload(item, prefix, source_vertex_map)
        submeshes.append(item)
    return raw_submeshes, submeshes


def export_native_obj(
    mesh: ParsedMesh,
    obj_path: str | Path,
    *,
    base_name: str,
    mtl_filename: str,
    scale: float = 1.0,
    manifest_path: str | Path = "",
    extra_payload: Mapping[str, object] | None = None,
    timeout_seconds: float = 20.0,
) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return False
    binary = find_native_mesh_core_binary()
    if binary is None:
        return False
    path = Path(obj_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_obj_export_"))
    try:
        raw_submeshes, submeshes = _native_obj_submesh_payloads(
            mesh,
            binary,
            sidecar_root,
            timeout_seconds=timeout_seconds,
        )
        job: dict[str, object] = {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "obj_export",
            "output_path": str(path),
            "base_name": str(base_name or path.stem),
            "source_path": str(getattr(mesh, "path", "") or ""),
            "source_format": str(getattr(mesh, "format", "") or ""),
            "mtl_filename": str(mtl_filename or ""),
            "scale": _finite_float(scale, 1.0),
            "total_vertices": sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in raw_submeshes),
            "total_faces": sum(len(getattr(submesh, "faces", ()) or ()) for submesh in raw_submeshes),
            "submeshes": submeshes,
        }
        if manifest_path:
            job["manifest_output_path"] = str(manifest_path)
        if extra_payload:
            job["extra_payload"] = dict(extra_payload)
        report = _run_native_mesh_core_job(
            binary,
            "obj-export-json",
            job,
            timeout_seconds=timeout_seconds,
        )
        if not isinstance(report, Mapping) or str(report.get("operation") or "") != "obj_export":
            return False
        if _index(report.get("submesh_count")) != len(submeshes):
            return False
        if manifest_path and not Path(manifest_path).is_file():
            return False
        return path.is_file()
    except (OSError, OverflowError, RuntimeError, ValueError):
        return False
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def write_native_obj_roundtrip_manifest(
    mesh: ParsedMesh,
    export_path: str | Path,
    *,
    companion_path: str | Path = "",
    extra_payload: Mapping[str, object] | None = None,
    timeout_seconds: float = 20.0,
) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return False
    binary = find_native_mesh_core_binary()
    if binary is None:
        return False
    manifest_path = Path(f"{export_path}.meta.json")
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_obj_manifest_"))
    try:
        _raw_submeshes, submeshes = _native_obj_submesh_payloads(
            mesh,
            binary,
            sidecar_root,
            timeout_seconds=timeout_seconds,
        )
        job: dict[str, object] = {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "obj_manifest",
            "manifest_output_path": str(manifest_path),
            "export_path": str(export_path),
            "companion_path": str(companion_path or ""),
            "source_path": str(getattr(mesh, "path", "") or ""),
            "source_format": str(getattr(mesh, "format", "") or ""),
            "submeshes": submeshes,
        }
        if extra_payload:
            job["extra_payload"] = dict(extra_payload)
        report = _run_native_mesh_core_job(
            binary,
            "obj-manifest-json",
            job,
            timeout_seconds=timeout_seconds,
        )
        if not isinstance(report, Mapping) or str(report.get("operation") or "") != "obj_manifest":
            return False
        if _index(report.get("submesh_count")) != len(submeshes):
            return False
        return manifest_path.is_file()
    except (OSError, OverflowError, RuntimeError, ValueError):
        return False
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def build_native_fbx_geometry_arrays(
    mesh: ParsedMesh,
    output_dir: str | Path,
    *,
    scale: float = 1.0,
    require_vertex_aligned_uvs: bool = False,
    timeout_seconds: float = 20.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    output_root = Path(output_dir)
    try:
        output_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_fbx_geometry_"))
    try:
        submeshes: list[dict[str, object]] = []
        raw_submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
        for submesh_index, submesh in enumerate(raw_submeshes):
            output_prefix = output_root / f"fbx_geometry_{submesh_index}"
            input_prefix = sidecar_root / f"fbx_geometry_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "vertices_output_path": str(output_prefix.with_name(output_prefix.name + "_vertices.bin")),
                "indices_output_path": str(output_prefix.with_name(output_prefix.name + "_indices.bin")),
                "normals_output_path": str(output_prefix.with_name(output_prefix.name + "_normals.bin")),
                "uvs_output_path": str(output_prefix.with_name(output_prefix.name + "_uvs.bin")),
            }
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                vertices = tuple(getattr(submesh, "vertices", ()) or ())
                faces = _face_json(getattr(submesh, "faces", ()) or (), len(vertices))
                item["vertices_binary"] = _write_vec3_binary_payload(
                    input_prefix.with_name(input_prefix.name + "_vertices.bin"),
                    vertices,
                )
                item["faces_binary"] = _write_face_binary_payload(
                    input_prefix.with_name(input_prefix.name + "_faces.bin"),
                    faces,
                )
                normals = tuple(getattr(submesh, "normals", ()) or ())
                if normals:
                    item["normals_binary"] = _write_vec3_binary_payload(
                        input_prefix.with_name(input_prefix.name + "_normals.bin"),
                        normals,
                        fallback=0.0,
                    )
                uvs = tuple(getattr(submesh, "uvs", ()) or ())
                if uvs:
                    item["uvs_binary"] = _write_vec2_binary_payload(input_prefix.with_name(input_prefix.name + "_uvs.bin"), uvs)
            submeshes.append(item)
        report = _run_native_mesh_core_job(
            binary,
            "fbx-geometry-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "fbx_geometry",
                "scale": _finite_float(scale, 1.0),
                "require_vertex_aligned_uvs": bool(require_vertex_aligned_uvs),
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        if not isinstance(report, Mapping) or str(report.get("operation") or "") != "fbx_geometry":
            return None
        raw_results = report.get("submeshes")
        if not isinstance(raw_results, list) or len(raw_results) != len(submeshes):
            return None
        for raw_item in raw_results:
            if not isinstance(raw_item, Mapping):
                return None
            for key in ("vertices_binary", "indices_binary", "normals_binary", "uvs_binary"):
                descriptor = raw_item.get(key)
                if not isinstance(descriptor, Mapping):
                    return None
                raw_path = str(descriptor.get("path") or "").strip()
                if not raw_path or not Path(raw_path).is_file():
                    return None
        return dict(report)
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def export_native_fbx(
    mesh: ParsedMesh,
    fbx_path: str | Path,
    *,
    base_name: str,
    scale: float = 1.0,
    skeleton: object = None,
    timeout_seconds: float = 20.0,
) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return False
    binary = find_native_mesh_core_binary()
    if binary is None:
        return False
    path = Path(fbx_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_fbx_export_"))
    try:
        submeshes: list[dict[str, object]] = []
        raw_submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
        for submesh_index, submesh in enumerate(raw_submeshes):
            prefix = sidecar_root / f"fbx_export_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "name": str(getattr(submesh, "name", "") or f"part_{submesh_index}"),
                "material": str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or f"part_{submesh_index}"),
            }
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                vertices = tuple(getattr(submesh, "vertices", ()) or ())
                faces = _face_json(getattr(submesh, "faces", ()) or (), len(vertices))
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                normals = tuple(getattr(submesh, "normals", ()) or ())
                if normals:
                    item["normals_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_normals.bin"),
                        normals,
                        fallback=0.0,
                    )
                uvs = tuple(getattr(submesh, "uvs", ()) or ())
                if uvs:
                    item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), uvs)
            submeshes.append(item)
        report = _run_native_mesh_core_job(
            binary,
            "fbx-export-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "fbx_export",
                "output_path": str(path),
                "base_name": str(base_name or path.stem),
                "scale": _finite_float(scale, 1.0),
                "submeshes": submeshes,
                "bones": _native_fbx_bone_payloads(skeleton),
            },
            timeout_seconds=timeout_seconds,
        )
        if not isinstance(report, Mapping) or str(report.get("operation") or "") != "fbx_export":
            return False
        if _index(report.get("submesh_count")) != len(submeshes):
            return False
        return path.is_file()
    except (OSError, OverflowError, RuntimeError, ValueError):
        return False
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def _native_fbx_bone_payloads(skeleton: object) -> list[dict[str, object]]:
    raw_bones = tuple(getattr(skeleton, "bones", ()) or ())
    result: list[dict[str, object]] = []
    for fallback_index, bone in enumerate(raw_bones):
        index = _index(getattr(bone, "index", fallback_index))
        if index is None:
            index = fallback_index
        parent_index = _index(getattr(bone, "parent_index", -1))
        if parent_index is None:
            parent_index = -1
        result.append(
            {
                "index": index,
                "name": str(getattr(bone, "name", "") or f"Bone_{index}"),
                "parent_index": parent_index,
                "position": list(_vec3(getattr(bone, "position", (0.0, 0.0, 0.0)), fallback=0.0)),
            }
        )
    return result


def build_native_preview_model_in_original_frame(
    parsed_mesh: object,
    *,
    normalization_center: Sequence[object],
    normalization_scale: object,
    source_indices: Sequence[int] | None = None,
    timeout_seconds: float = 20.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_preview_model_"))
    try:
        submeshes = []
        raw_source_indices = source_indices or ()
        for submesh_position, submesh in enumerate(getattr(parsed_mesh, "submeshes", ()) or ()):
            raw_vertices = getattr(submesh, "vertices", ()) or ()
            raw_faces = getattr(submesh, "faces", ()) or ()
            if not raw_vertices or not raw_faces:
                continue
            try:
                source_submesh_index = int(raw_source_indices[submesh_position]) if submesh_position < len(raw_source_indices) else int(submesh_position)
            except (TypeError, ValueError, OverflowError):
                return None
            prefix = sidecar_root / f"preview_model_{submesh_position}"
            item: dict[str, object] = {
                "index": int(submesh_position),
                "source_submesh_index": source_submesh_index,
                "positions_output_path": _native_preview_delta_output_path("_preview_model_positions.bin"),
                "texture_coordinates_output_path": _native_preview_delta_output_path("_preview_model_uvs.bin"),
                "normals_output_path": _native_preview_delta_output_path("_preview_model_normals.bin"),
                "indices_output_path": _native_preview_delta_output_path("_preview_model_indices.bin"),
                "source_vertex_indices_output_path": _native_preview_delta_output_path("_preview_model_source_vertices.bin"),
                "source_face_indices_output_path": _native_preview_delta_output_path("_preview_model_source_faces.bin"),
            }
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                parsed_mesh,
                submesh_position,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                vertices = _finite_vec3_list_or_none(raw_vertices)
                if vertices is None:
                    return None
                faces, _source_face_indices = _face_json_with_source_indices(raw_faces, len(vertices))
                if len(faces) != len(raw_faces):
                    return None
                uvs = _finite_vec2_list_or_none(getattr(submesh, "uvs", ()) or ())
                normals = _finite_vec3_list_or_none(getattr(submesh, "normals", ()) or ())
                if uvs is None or normals is None:
                    return None
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), uvs[: len(vertices)])
                item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), normals[: len(vertices)])
            submeshes.append(item)
        if not submeshes:
            return {"status": "ok", "backend": NATIVE_MESH_CORE_BACKEND_ID, "operation": "preview_model", "mesh_count": 0, "vertex_count": 0, "face_count": 0, "meshes": []}
        report = _run_native_mesh_core_job(
            binary,
            "preview-model-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "preview_model",
                "normalization_center": _vec3_json(normalization_center),
                "normalization_scale": _finite_float(normalization_scale, 1.0),
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        return _hydrate_native_preview_model_report(report)
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def _hydrate_native_preview_model_report(report: object) -> dict[str, object] | None:
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "preview_model":
        return None
    raw_meshes = report.get("meshes")
    if not isinstance(raw_meshes, list):
        return None
    hydrated_report = dict(report)
    hydrated_meshes: list[dict[str, object]] = []
    for raw_mesh in raw_meshes:
        if not isinstance(raw_mesh, Mapping):
            return None
        mesh = dict(raw_mesh)
        vertex_count = _index(mesh.get("vertex_count"))
        face_count = _index(mesh.get("face_count"))
        positions_binary = mesh.get("positions_binary")
        source_face_indices_binary = mesh.get("source_face_indices_binary")
        if vertex_count is None and isinstance(positions_binary, Mapping):
            vertex_count = _index(positions_binary.get("count"))
        if face_count is None and isinstance(source_face_indices_binary, Mapping):
            face_count = _index(source_face_indices_binary.get("count"))
        if vertex_count is None and isinstance(mesh.get("positions"), list):
            vertex_count = len(mesh["positions"])  # type: ignore[arg-type]
        if face_count is None and isinstance(mesh.get("indices"), list):
            face_count = len(mesh["indices"]) // 3  # type: ignore[arg-type]
        if vertex_count is None or vertex_count < 0 or face_count is None or face_count < 0:
            return None

        positions_binary = _native_binary_descriptor(mesh.get("positions_binary"), expected_count=vertex_count, components=3, kind="f64")
        if positions_binary is not None:
            mesh["positions_binary"] = positions_binary
            mesh.pop("positions", None)
        elif "positions_binary" in mesh:
            return None
        elif not isinstance(mesh.get("positions"), list):
            return None

        uvs_binary = mesh.get("texture_coordinates_binary")
        uv_count = _index(uvs_binary.get("count")) if isinstance(uvs_binary, Mapping) else vertex_count
        if uv_count is None or uv_count < 0 or uv_count > vertex_count:
            return None
        texture_coordinates_binary = _native_binary_descriptor(uvs_binary, expected_count=uv_count, components=2, kind="f64")
        if texture_coordinates_binary is not None:
            mesh["texture_coordinates_binary"] = texture_coordinates_binary
            mesh.pop("texture_coordinates", None)
        elif "texture_coordinates_binary" in mesh:
            return None

        normals_binary = mesh.get("normals_binary")
        normal_count = _index(normals_binary.get("count")) if isinstance(normals_binary, Mapping) else vertex_count
        if normal_count is None or normal_count < 0 or normal_count > vertex_count:
            return None
        normals_binary_descriptor = _native_binary_descriptor(normals_binary, expected_count=normal_count, components=3, kind="f64")
        if normals_binary_descriptor is not None:
            mesh["normals_binary"] = normals_binary_descriptor
            mesh.pop("normals", None)
        elif "normals_binary" in mesh:
            return None

        indices_binary = _native_binary_descriptor(mesh.get("indices_binary"), expected_count=face_count * 3, components=1, kind="i32")
        if indices_binary is not None:
            mesh["indices_binary"] = indices_binary
            mesh.pop("indices", None)
        elif "indices_binary" in mesh:
            return None
        elif not isinstance(mesh.get("indices"), list):
            return None

        source_vertex_indices_binary = _native_binary_descriptor(
            mesh.get("source_vertex_indices_binary"),
            expected_count=vertex_count,
            components=1,
            kind="i32",
        )
        if source_vertex_indices_binary is not None:
            mesh["source_vertex_indices_binary"] = source_vertex_indices_binary
            mesh.pop("source_vertex_indices", None)
        elif "source_vertex_indices_binary" in mesh:
            return None

        source_face_indices_binary = _native_binary_descriptor(
            mesh.get("source_face_indices_binary"),
            expected_count=face_count,
            components=1,
            kind="i32",
        )
        if source_face_indices_binary is not None:
            mesh["source_face_indices_binary"] = source_face_indices_binary
            mesh.pop("source_face_indices", None)
        elif "source_face_indices_binary" in mesh:
            return None

        hydrated_meshes.append(mesh)
    hydrated_report["meshes"] = hydrated_meshes
    return hydrated_report


def _selection_domain_submesh_items(
    mesh: ParsedMesh,
    *,
    vertices_by_submesh: Mapping[int, set[int]],
    edges_by_submesh: Mapping[int, set[tuple[int, int]]],
    faces_by_submesh: Mapping[int, set[int]],
    source_indices: Sequence[int],
    binary: Path,
    sidecar_root: Path,
    stop_event: threading.Event | None = None,
    timeout_seconds: float,
) -> list[dict[str, object]] | None:
    requested_sources = {
        parsed
        for raw in source_indices or ()
        for parsed in (_index(raw),)
        if parsed is not None and 0 <= parsed < len(mesh.submeshes)
    }
    target_indices = set(requested_sources)
    for mapping in (vertices_by_submesh, edges_by_submesh, faces_by_submesh):
        for raw_index in mapping:
            parsed = _index(raw_index)
            if parsed is not None:
                target_indices.add(parsed)
    submeshes: list[dict[str, object]] = []
    for raw_submesh_index in sorted(target_indices):
        submesh_index = _index(raw_submesh_index)
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        vertex_count = len(submesh.vertices or ())
        if vertex_count <= 0:
            continue
        selected_vertices = sorted(
            parsed
            for raw in vertices_by_submesh.get(submesh_index, set()) or ()
            for parsed in (_index(raw),)
            if parsed is not None and 0 <= parsed < vertex_count
        )
        selected_edges = sorted(
            (min(left, right), max(left, right))
            for raw_edge in edges_by_submesh.get(submesh_index, set()) or ()
            if isinstance(raw_edge, (tuple, list)) and len(raw_edge) >= 2
            for left in (_index(raw_edge[0]),)
            for right in (_index(raw_edge[1]),)
            if left is not None and right is not None and 0 <= left < vertex_count and 0 <= right < vertex_count and left != right
        )
        selected_faces = sorted(
            parsed
            for raw in faces_by_submesh.get(submesh_index, set()) or ()
            for parsed in (_index(raw),)
            if parsed is not None and parsed >= 0
        )
        selected_all_vertices = submesh_index in requested_sources
        if not (selected_vertices or selected_edges or selected_faces or selected_all_vertices):
            continue
        session_id = _ensure_native_mesh_session_submesh(
            binary,
            mesh,
            submesh_index,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not session_id:
            return None
        prefix = sidecar_root / f"selection_domain_{submesh_index}"
        item: dict[str, object] = {"index": submesh_index, "session_id": session_id}
        if selected_vertices:
            _put_i32_range_or_binary_payload(
                item,
                values=selected_vertices,
                start_key="selected_vertex_start",
                count_key="selected_vertex_count",
                binary_key="selected_vertices_binary",
                binary_path=prefix.with_name(prefix.name + "_selected_vertices.bin"),
                max_count=vertex_count,
            )
        if selected_edges:
            item["selected_edges_binary"] = _write_edge_binary_payload(prefix.with_name(prefix.name + "_selected_edges.bin"), selected_edges)
        if selected_faces:
            _put_i32_range_or_binary_payload(
                item,
                values=selected_faces,
                start_key="selected_face_start",
                count_key="selected_face_count",
                binary_key="selected_faces_binary",
                binary_path=prefix.with_name(prefix.name + "_selected_faces.bin"),
            )
        if selected_all_vertices:
            item["selected_all_vertices"] = True
        submeshes.append(item)
    return submeshes


def apply_native_mesh_transform(
    mesh: ParsedMesh,
    vertices_by_submesh: Mapping[int, set[int]],
    *,
    translate: Vec3,
    scale: Vec3,
    rotate: Vec3,
    pivot: Vec3 | None,
    snap: float = 0.0,
    mirror_x: bool = False,
    mirror_pairs_by_submesh: Mapping[int, Mapping[int, int]] | None = None,
    history_delta: bool = False,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root: Path | None = None
    try:
        sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_transform_"))
        submeshes = []
        for submesh_index, selected in sorted(vertices_by_submesh.items()):
            if not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            kept = sorted(index for index in selected if 0 <= index < len(submesh.vertices))
            if not kept:
                continue
            item: dict[str, object] = {"index": submesh_index}
            prefix = sidecar_root / f"transform_{submesh_index}"
            item["changed_vertices_output_path"] = _native_preview_delta_output_path("_changed_vertices.bin")
            item["changed_positions_output_path"] = _native_preview_delta_output_path("_positions.bin")
            if history_delta:
                item["before_positions_output_path"] = _native_preview_delta_output_path("_before_positions.bin")
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
                item["sparse_output"] = True
                _put_i32_range_or_binary_payload(
                    item,
                    values=kept,
                    start_key="selected_vertex_start",
                    count_key="selected_vertex_count",
                    binary_key="selected_vertices_binary",
                    binary_path=prefix.with_name(prefix.name + "_indices.bin"),
                    max_count=len(submesh.vertices),
                )
                mirror_pairs = _mirror_pairs_json(mirror_pairs_by_submesh, submesh_index) if mirror_x else []
                if mirror_pairs:
                    item["mirror_pairs"] = mirror_pairs
            elif mirror_x:
                _put_selected_vertices_payload(item, prefix, kept, max_count=len(submesh.vertices))
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
                mirror_pairs = _mirror_pairs_json(mirror_pairs_by_submesh, submesh_index)
                if mirror_pairs:
                    item["mirror_pairs"] = mirror_pairs
            else:
                item["vertex_count"] = len(submesh.vertices)
                compact_range = _contiguous_i32_range(kept, max_count=len(submesh.vertices))
                if compact_range is not None:
                    item["selected_vertex_start"] = compact_range[0]
                    item["selected_vertex_count"] = compact_range[1]
                    item["vertex_index_start"] = compact_range[0]
                    item["vertex_index_count"] = compact_range[1]
                else:
                    selected_descriptor = _write_int_binary_payload(prefix.with_name(prefix.name + "_indices.bin"), kept)
                    item["selected_vertices_binary"] = selected_descriptor
                    item["vertex_indices_binary"] = selected_descriptor
                item["vertex_positions_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_positions.bin"),
                    (submesh.vertices[index] for index in kept),
                )
            submeshes.append(item)
        if not submeshes:
            return {}

        payload: dict[str, object] = {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "transform",
            "transform": {
                "translate": _vec3_json(translate),
                "scale": _vec3_json(scale, fallback=1.0),
                "rotate": _vec3_json(rotate),
                "pivot": _vec3_json(pivot or (0.0, 0.0, 0.0)),
                "pivot_from_selection": pivot is None,
                "snap": _finite_float(snap, 0.0),
                "mirror_x": bool(mirror_x),
            },
            "submeshes": submeshes,
        }
        if history_delta:
            payload["sparse_snapshot_id"] = _new_native_sparse_vertex_snapshot_id("transform")
        report = _run_native_mesh_core_job(
            binary,
            "transform-json",
            payload,
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
        if report is None:
            return None
        changed = _apply_transform_report(mesh, report)
        if changed:
            _mark_native_mesh_session_submeshes_current(mesh, changed.keys())
        return changed
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        if sidecar_root is not None:
            shutil.rmtree(sidecar_root, ignore_errors=True)


def apply_native_mesh_transform_selection(
    mesh: ParsedMesh,
    *,
    vertices_by_submesh: Mapping[int, set[int]],
    edges_by_submesh: Mapping[int, set[tuple[int, int]]],
    faces_by_submesh: Mapping[int, set[int]],
    source_indices: Sequence[int],
    translate: Vec3,
    scale: Vec3,
    rotate: Vec3,
    pivot: Vec3 | None,
    snap: float = 0.0,
    mirror_x: bool = False,
    mirror_pairs_by_submesh: Mapping[int, Mapping[int, int]] | None = None,
    history_delta: bool = False,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_transform_selection_"))
    try:
        submeshes = _selection_domain_submesh_items(
            mesh,
            vertices_by_submesh=vertices_by_submesh,
            edges_by_submesh=edges_by_submesh,
            faces_by_submesh=faces_by_submesh,
            source_indices=source_indices,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if submeshes is None:
            return None
        if not submeshes:
            return {}
        for item in submeshes:
            item["sparse_output"] = True
            submesh_index = _index(item.get("index"))
            if submesh_index is not None:
                item["changed_vertices_output_path"] = _native_preview_delta_output_path("_changed_vertices.bin")
                item["changed_positions_output_path"] = _native_preview_delta_output_path("_positions.bin")
                if history_delta:
                    item["before_positions_output_path"] = _native_preview_delta_output_path("_before_positions.bin")
            mirror_pairs = _mirror_pairs_json(mirror_pairs_by_submesh, int(item["index"])) if mirror_x else []
            if mirror_pairs:
                item["mirror_pairs"] = mirror_pairs
        payload: dict[str, object] = {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "transform",
            "transform": {
                "translate": _vec3_json(translate),
                "scale": _vec3_json(scale, fallback=1.0),
                "rotate": _vec3_json(rotate),
                "pivot": _vec3_json(pivot or (0.0, 0.0, 0.0)),
                "pivot_from_selection": pivot is None,
                "snap": _finite_float(snap, 0.0),
                "mirror_x": bool(mirror_x),
            },
            "submeshes": submeshes,
        }
        if history_delta:
            payload["sparse_snapshot_id"] = _new_native_sparse_vertex_snapshot_id("transform-selection")
        report = _run_native_mesh_core_job(
            binary,
            "transform-json",
            payload,
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
        if report is None:
            return None
        changed = _apply_transform_report(mesh, report)
        if changed:
            _mark_native_mesh_session_submeshes_current(mesh, changed.keys())
        return changed
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def apply_native_mesh_transform_binary_selection(
    mesh: ParsedMesh,
    *,
    selected_vertices_binary_by_submesh: Mapping[object, object],
    translate: Vec3,
    scale: Vec3,
    rotate: Vec3,
    pivot: Vec3 | None,
    snap: float = 0.0,
    mirror_x: bool = False,
    mirror_pairs_by_submesh: Mapping[int, Mapping[int, int]] | None = None,
    history_delta: bool = False,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    if not selected_vertices_binary_by_submesh:
        return None
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    try:
        submeshes: list[dict[str, object]] = []
        for raw_submesh_index, raw_descriptor in sorted(selected_vertices_binary_by_submesh.items(), key=lambda item: str(item[0])):
            submesh_index = _index(raw_submesh_index)
            if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
                continue
            selected_descriptor = _native_existing_binary_descriptor(
                raw_descriptor,
                components=1,
                kinds={"i32"},
            )
            vertex_count = len(getattr(mesh.submeshes[submesh_index], "vertices", ()) or ())
            selected_range = _native_i32_range_descriptor(raw_descriptor, max_count=vertex_count)
            if selected_descriptor is None and selected_range is None:
                continue
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            if not session_id:
                return None
            item: dict[str, object] = {
                "index": submesh_index,
                "session_id": session_id,
                "sparse_output": True,
                "changed_vertices_output_path": _native_preview_delta_output_path("_changed_vertices.bin"),
                "changed_positions_output_path": _native_preview_delta_output_path("_positions.bin"),
            }
            if selected_descriptor is not None:
                item["selected_vertices_binary"] = selected_descriptor
            elif selected_range is not None:
                item["selected_vertex_start"] = selected_range[0]
                item["selected_vertex_count"] = selected_range[1]
            if history_delta:
                item["before_positions_output_path"] = _native_preview_delta_output_path("_before_positions.bin")
            mirror_pairs = _mirror_pairs_json(mirror_pairs_by_submesh, submesh_index) if mirror_x else []
            if mirror_pairs:
                item["mirror_pairs"] = mirror_pairs
            submeshes.append(item)
        if not submeshes:
            return {}
        payload: dict[str, object] = {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "transform",
            "transform": {
                "translate": _vec3_json(translate),
                "scale": _vec3_json(scale, fallback=1.0),
                "rotate": _vec3_json(rotate),
                "pivot": _vec3_json(pivot or (0.0, 0.0, 0.0)),
                "pivot_from_selection": pivot is None,
                "snap": _finite_float(snap, 0.0),
                "mirror_x": bool(mirror_x),
            },
            "submeshes": submeshes,
        }
        if history_delta:
            payload["sparse_snapshot_id"] = _new_native_sparse_vertex_snapshot_id("transform-binary")
        report = _run_native_mesh_core_job(
            binary,
            "transform-json",
            payload,
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
        if report is None:
            return None
        changed = _apply_transform_report(mesh, report)
        if changed:
            _mark_native_mesh_session_submeshes_current(mesh, changed.keys())
        return changed
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None


def apply_native_mesh_sparse_vertex_restore(
    mesh: ParsedMesh,
    before_positions_by_submesh: Mapping[object, object],
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
    history_delta: bool = False,
) -> dict[int, Sequence[int] | set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    if not isinstance(before_positions_by_submesh, Mapping) or not before_positions_by_submesh:
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_sparse_restore_"))
    try:
        submeshes: list[dict[str, object]] = []
        for raw_submesh_index, raw_positions_by_vertex in sorted(
            before_positions_by_submesh.items(),
            key=lambda item: str(item[0]),
        ):
            submesh_index = _index(raw_submesh_index)
            if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
                continue
            if not isinstance(raw_positions_by_vertex, Mapping):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            if vertex_count <= 0:
                continue
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            if not session_id:
                return None
            raw_groups = raw_positions_by_vertex.get("groups") if isinstance(raw_positions_by_vertex, Mapping) else None
            restore_groups = tuple(raw_groups) if isinstance(raw_groups, (tuple, list)) and raw_groups else (raw_positions_by_vertex,)
            for raw_group in restore_groups:
                if not isinstance(raw_group, Mapping):
                    continue
                restore_items: list[tuple[int, Vec3]] = []
                raw_descriptor = dict(raw_group)
                raw_sparse_snapshot_id = str(
                    raw_descriptor.get("native_sparse_snapshot_id")
                    or raw_descriptor.get("sparse_snapshot_id")
                    or ""
                ).strip()
                raw_positions_binary = raw_descriptor.get("before_positions_binary")
                descriptor_indices = _vertex_indices_from_history_descriptor(raw_descriptor, vertex_count)
                descriptor_positions_binary = None
                if isinstance(raw_positions_binary, Mapping) and descriptor_indices is not None:
                    descriptor_positions_binary = _native_binary_descriptor(
                        raw_positions_binary,
                        expected_count=len(descriptor_indices),
                        components=3,
                        kind="f64",
                    )
                    if descriptor_positions_binary is None and not raw_sparse_snapshot_id:
                        return None
                if descriptor_indices is None:
                    for raw_vertex_index, raw_position in raw_descriptor.items():
                        vertex_index = _index(raw_vertex_index)
                        if vertex_index is None or vertex_index < 0 or vertex_index >= vertex_count:
                            continue
                        try:
                            position = (
                                float(raw_position[0]),  # type: ignore[index]
                                float(raw_position[1]),  # type: ignore[index]
                                float(raw_position[2]),  # type: ignore[index]
                            )
                        except (TypeError, ValueError, OverflowError, IndexError):
                            continue
                        if not all(math.isfinite(component) for component in position):
                            continue
                        restore_items.append((vertex_index, position))
                    if not restore_items:
                        continue
                    restore_items.sort(key=lambda item: item[0])
                prefix = sidecar_root / f"restore_{submesh_index}_{len(submeshes)}"
                item = {
                    "index": submesh_index,
                    "session_id": session_id,
                    "vertex_count": vertex_count,
                    "changed_vertices_output_path": _native_preview_delta_output_path("_changed_vertices.bin"),
                    "changed_positions_output_path": _native_preview_delta_output_path("_positions.bin"),
                }
                _put_vertex_indices_payload(
                    item,
                    prefix,
                    descriptor_indices if descriptor_indices is not None else [item[0] for item in restore_items],
                    max_count=vertex_count,
                )
                if raw_sparse_snapshot_id:
                    item["native_sparse_snapshot_id"] = raw_sparse_snapshot_id
                if descriptor_positions_binary is not None:
                    item["vertex_positions_binary"] = descriptor_positions_binary
                elif raw_sparse_snapshot_id:
                    pass
                else:
                    item["vertex_positions_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_positions.bin"),
                        [item[1] for item in restore_items],
                    )
                if history_delta:
                    item["before_positions_output_path"] = _native_preview_delta_output_path("_before_positions.bin")
                submeshes.append(item)
        if not submeshes:
            return {}
        payload: dict[str, object] = {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "restore_vertices",
            "submeshes": submeshes,
        }
        if history_delta:
            payload["sparse_snapshot_id"] = _new_native_sparse_vertex_snapshot_id("restore")
        report = _run_native_mesh_core_job(
            binary,
            "restore-vertices-json",
            payload,
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
        if report is None:
            return None
        changed = _apply_transform_report(mesh, report)
        if changed is None:
            return None
        if changed:
            _mark_native_mesh_session_submeshes_current(mesh, changed.keys())
        return changed
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def snapshot_native_mesh_sparse_vertex_positions(
    mesh: ParsedMesh,
    vertex_indices_by_submesh: Mapping[object, object],
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> dict[int, dict[str, object]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    if not isinstance(vertex_indices_by_submesh, Mapping) or not vertex_indices_by_submesh:
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_sparse_snapshot_"))
    try:
        submeshes: list[dict[str, object]] = []
        vertex_counts: dict[int, int] = {}
        snapshot_id = _new_native_sparse_vertex_snapshot_id("snapshot")
        for raw_submesh_index, raw_positions_by_vertex in sorted(
            vertex_indices_by_submesh.items(),
            key=lambda item: str(item[0]),
        ):
            submesh_index = _index(raw_submesh_index)
            if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
                continue
            if not isinstance(raw_positions_by_vertex, Mapping):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            if vertex_count <= 0:
                continue
            indices: list[int] = []
            seen_indices: set[int] = set()
            raw_groups = raw_positions_by_vertex.get("groups")
            if isinstance(raw_groups, (tuple, list)) and raw_groups:
                raw_index_groups = (
                    _vertex_indices_from_history_descriptor(group, vertex_count)
                    for group in raw_groups
                    if isinstance(group, Mapping)
                )
            else:
                raw_index_groups = (raw_positions_by_vertex.keys(),)
            for raw_group_indices in raw_index_groups:
                if raw_group_indices is None:
                    continue
                for raw_vertex_index in raw_group_indices:
                    vertex_index = _index(raw_vertex_index)
                    if vertex_index is None or vertex_index < 0 or vertex_index >= vertex_count or vertex_index in seen_indices:
                        continue
                    indices.append(vertex_index)
                    seen_indices.add(vertex_index)
            if not indices:
                continue
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            if not session_id:
                return None
            prefix = sidecar_root / f"snapshot_{submesh_index}_{len(submeshes)}"
            item: dict[str, object] = {
                "index": submesh_index,
                "session_id": session_id,
                "vertex_count": vertex_count,
                "changed_vertices_output_path": _native_preview_delta_output_path("_snapshot_vertices.bin"),
                "before_positions_output_path": _native_preview_delta_output_path("_snapshot_positions.bin"),
            }
            _put_vertex_indices_payload(item, prefix, indices, max_count=vertex_count)
            submeshes.append(item)
            vertex_counts[submesh_index] = vertex_count
        if not submeshes:
            return {}
        report = _run_native_mesh_core_job(
            binary,
            "snapshot-vertices-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "snapshot_vertices",
                "sparse_snapshot_id": snapshot_id,
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
        if report is None:
            return None
        result: dict[int, dict[str, object]] = {}
        for item in tuple(report.get("submeshes") or ()) if isinstance(report, Mapping) else ():
            if not isinstance(item, Mapping):
                continue
            submesh_index = _index(item.get("index"))
            if submesh_index is None or submesh_index not in vertex_counts:
                continue
            changed_vertices = _changed_vertices_from_report_item(item, vertex_counts[submesh_index])
            if changed_vertices is None:
                return None
            delta = _native_history_vertex_delta(item, submesh_index, changed_vertices)
            if delta is None:
                return None
            result[submesh_index] = {
                "groups": [
                    {
                        **_native_history_delta_vertex_payload(delta),
                        "native_sparse_snapshot_id": delta.get("native_sparse_snapshot_id", snapshot_id),
                        "before_positions_binary": delta["before_positions_binary"],
                    }
                ]
            }
        return result
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def snapshot_native_mesh_submeshes(
    mesh: ParsedMesh,
    submesh_indices: Sequence[int] | None = None,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    if getattr(mesh, "lod_levels", None):
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    requested = tuple(_iter_valid_submesh_indices(mesh, submesh_indices, all_when_none=True))
    if len(requested) != len(set(requested)):
        return None
    snapshot_items: dict[int, dict[str, object]] = {}
    job_submeshes: list[dict[str, object]] = []
    snapshot_id = f"py-submesh-snapshot-{uuid4().hex}"
    try:
        for submesh_index in requested:
            submesh = mesh.submeshes[submesh_index]
            metadata = _submesh_snapshot_metadata(submesh)
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            face_count = _face_count_json(getattr(submesh, "faces", ()) or (), vertex_count)
            if vertex_count <= 0:
                snapshot_items[submesh_index] = {
                    "index": submesh_index,
                    "metadata": metadata,
                    "vertex_count": 0,
                    "face_count": 0,
                }
                continue
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            if not session_id:
                session_id = _ensure_native_mesh_session_submesh(
                    binary,
                    mesh,
                    submesh_index,
                    stop_event=stop_event,
                    timeout_seconds=timeout_seconds,
                )
            if not session_id:
                return None
            job_submeshes.append(
                {
                    "index": submesh_index,
                    "session_id": session_id,
                    "vertices_output_path": _native_preview_delta_output_path("_snapshot_vertices.bin"),
                    "faces_output_path": _native_preview_delta_output_path("_snapshot_faces.bin"),
                    "source_face_indices_output_path": _native_preview_delta_output_path("_snapshot_source_faces.bin"),
                    "normals_output_path": _native_preview_delta_output_path("_snapshot_normals.bin"),
                    "uvs_output_path": _native_preview_delta_output_path("_snapshot_uvs.bin"),
                    "tangents_output_path": _native_preview_delta_output_path("_snapshot_tangents.bin"),
                    "tangent_signs_output_path": _native_preview_delta_output_path("_snapshot_tangent_signs.bin"),
                    "bone_counts_output_path": _native_preview_delta_output_path("_snapshot_bone_counts.bin"),
                    "bone_indices_output_path": _native_preview_delta_output_path("_snapshot_bone_indices.bin"),
                    "bone_weights_output_path": _native_preview_delta_output_path("_snapshot_bone_weights.bin"),
                    "source_vertex_map_output_path": _native_preview_delta_output_path("_snapshot_source_vertex_map.bin"),
                    "source_vertex_offsets_output_path": _native_preview_delta_output_path("_snapshot_source_vertex_offsets.bin"),
                    "_metadata": metadata,
                    "_vertex_count": vertex_count,
                    "_face_count": face_count,
                }
            )
        if job_submeshes:
            report = _run_native_mesh_core_service_job(
                binary,
                "snapshot-submeshes-json",
                {
                    "version": 1,
                    "backend": NATIVE_MESH_CORE_BACKEND_ID,
                    "operation": "snapshot_submeshes",
                    "snapshot_id": snapshot_id,
                    "submeshes": [
                        {key: value for key, value in item.items() if not str(key).startswith("_")}
                        for item in job_submeshes
                    ],
                },
                **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
            )
            if report is None:
                return None
            metadata_by_index = {
                int(item["index"]): (dict(item["_metadata"]), int(item["_vertex_count"]), int(item["_face_count"]))
                for item in job_submeshes
            }
            for raw_item in tuple(report.get("submeshes") or ()) if isinstance(report, Mapping) else ():
                if not isinstance(raw_item, Mapping):
                    continue
                submesh_index = _index(raw_item.get("index"))
                if submesh_index is None or submesh_index not in metadata_by_index:
                    continue
                metadata, expected_vertices, expected_faces = metadata_by_index[submesh_index]
                snapshot_item = _native_submesh_snapshot_item(
                    raw_item,
                    metadata=metadata,
                    expected_vertices=expected_vertices,
                    expected_faces=expected_faces,
                )
                if snapshot_item is None:
                    return None
                snapshot_items[submesh_index] = snapshot_item
        if set(snapshot_items) != set(requested):
            return None
        return {
            "kind": "native_submesh_snapshot",
            "mesh": _mesh_snapshot_metadata(mesh),
            "handle": _native_submesh_snapshot_handle(report if job_submeshes else None, snapshot_id),
            "submeshes": [snapshot_items[index] for index in sorted(snapshot_items)],
        }
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None


def restore_native_mesh_submesh_snapshot(
    mesh: ParsedMesh,
    snapshot: Mapping[str, object],
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> bool:
    if not isinstance(snapshot, Mapping) or snapshot.get("kind") != "native_submesh_snapshot":
        return False
    restored_native_sessions = _restore_native_submesh_snapshot_handle_sessions(
        snapshot,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )
    exported_snapshot = _export_native_submesh_snapshot_handle(
        snapshot,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )
    if exported_snapshot is not None:
        snapshot = exported_snapshot
    raw_submeshes = snapshot.get("submeshes")
    if not isinstance(raw_submeshes, list):
        return False
    new_submeshes: list[SubMesh] = []
    session_items_by_id: dict[str, list[dict[str, object]]] = {}
    for raw_item in raw_submeshes:
        if not isinstance(raw_item, Mapping):
            return False
        submesh = _submesh_from_native_snapshot_item(raw_item)
        if submesh is None:
            return False
        new_submeshes.append(submesh)
        session_id = str(raw_item.get("session_id") or "").strip()
        if session_id and submesh.vertices:
            session_item = _mesh_session_item_from_native_snapshot(raw_item)
            if session_item is not None:
                session_items_by_id.setdefault(session_id, []).append(session_item)
    mesh_meta = snapshot.get("mesh") if isinstance(snapshot.get("mesh"), Mapping) else {}
    mesh.path = str(mesh_meta.get("path") or getattr(mesh, "path", "") or "")
    mesh.format = str(mesh_meta.get("format") or getattr(mesh, "format", "") or "")
    mesh.bbox_min = _vec3(mesh_meta.get("bbox_min"), fallback=0.0)
    mesh.bbox_max = _vec3(mesh_meta.get("bbox_max"), fallback=0.0)
    mesh.submeshes = new_submeshes
    mesh.lod_levels = []
    mesh.total_vertices = sum(len(submesh.vertices or ()) for submesh in new_submeshes)
    mesh.total_faces = sum(len(submesh.faces or ()) for submesh in new_submeshes)
    mesh.has_uvs = any(len(submesh.uvs or ()) == len(submesh.vertices or ()) and submesh.vertices for submesh in new_submeshes)
    mesh.has_bones = any(bool(submesh.bone_indices) or bool(submesh.bone_weights) for submesh in new_submeshes)

    restored_indices = range(len(new_submeshes))
    stored_native = False
    binary = find_native_mesh_core_binary()
    if restored_native_sessions:
        stored_native = True
    elif binary is not None and session_items_by_id:
        stored_native = True
        for session_id, session_items in session_items_by_id.items():
            report = _run_native_mesh_core_service_job(
                binary,
                "mesh-session-json",
                {
                    "version": 1,
                    "backend": NATIVE_MESH_CORE_BACKEND_ID,
                    "operation": "store",
                    "session_id": session_id,
                    "submeshes": session_items,
                },
                **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
            )
            if report is None:
                stored_native = False
                break
    if stored_native:
        with _native_mesh_core_session_cache_lock:
            for session_id, session_items in session_items_by_id.items():
                for session_item in session_items:
                    submesh_index = _index(session_item.get("index"))
                    if submesh_index is not None and 0 <= submesh_index < len(mesh.submeshes):
                        _native_mesh_core_session_cache[_native_mesh_session_cache_key(mesh, submesh_index)] = (
                            _native_mesh_session_signature(mesh.submeshes[submesh_index]),
                            session_id,
                        )
    else:
        _invalidate_native_mesh_session_submeshes(mesh, restored_indices)
    return True


def restore_native_mesh_submeshes_from_mesh(
    target_mesh: ParsedMesh,
    source_mesh: ParsedMesh,
    submesh_indices: Iterable[int],
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return False
    if getattr(target_mesh, "lod_levels", None) or getattr(source_mesh, "lod_levels", None):
        return False
    target_submeshes = list(getattr(target_mesh, "submeshes", ()) or ())
    source_submeshes = getattr(source_mesh, "submeshes", ()) or ()
    requested: list[int] = []
    seen: set[int] = set()
    try:
        raw_indices = iter(submesh_indices)
    except TypeError:
        return False
    for raw_index in raw_indices:
        index = _index(raw_index)
        if index is None or index in seen:
            continue
        if 0 <= index < len(target_submeshes) and 0 <= index < len(source_submeshes):
            requested.append(index)
            seen.add(index)
    if not requested:
        return False

    snapshot = snapshot_native_mesh_submeshes(
        source_mesh,
        requested,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(snapshot, Mapping):
        return False
    try:
        raw_snapshot_items = snapshot.get("submeshes")
        if not isinstance(raw_snapshot_items, list):
            return False
        target_items: list[dict[str, object]] = []
        target_sessions: dict[int, str] = {}
        for raw_item in raw_snapshot_items:
            if not isinstance(raw_item, Mapping):
                return False
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is None or submesh_index not in seen:
                return False
            item = dict(raw_item)
            session_id = _native_mesh_session_id(target_mesh, submesh_index)
            item["session_id"] = session_id
            target_items.append(item)
            vertex_count = _index(item.get("vertex_count"))
            if vertex_count is not None and vertex_count > 0:
                target_sessions[submesh_index] = session_id
        if {int(item["index"]) for item in target_items} != seen:
            return False

        target_snapshot = {
            **dict(snapshot),
            "mesh": _mesh_snapshot_metadata(target_mesh),
            "submeshes": target_items,
        }
        restored_native_sessions = _restore_native_submesh_snapshot_handle_sessions(
            target_snapshot,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        exported_snapshot = _export_native_submesh_snapshot_handle(
            target_snapshot,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        restore_items = (
            exported_snapshot.get("submeshes")
            if isinstance(exported_snapshot, Mapping) and isinstance(exported_snapshot.get("submeshes"), list)
            else target_items
        )
        if not isinstance(restore_items, list):
            return False
        restored_indices: set[int] = set()
        for raw_item in restore_items:
            if not isinstance(raw_item, Mapping):
                return False
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is None or submesh_index not in seen:
                return False
            submesh = _submesh_from_native_snapshot_item(raw_item)
            if submesh is None:
                return False
            target_submeshes[submesh_index] = submesh
            restored_indices.add(submesh_index)
        if restored_indices != seen:
            return False

        target_mesh.submeshes = target_submeshes
        target_mesh.total_vertices = sum(len(submesh.vertices or ()) for submesh in target_submeshes)
        target_mesh.total_faces = sum(len(submesh.faces or ()) for submesh in target_submeshes)
        target_mesh.has_uvs = any(
            len(submesh.uvs or ()) == len(submesh.vertices or ()) and bool(submesh.vertices)
            for submesh in target_submeshes
        )
        target_mesh.has_bones = any(
            bool(getattr(submesh, "bone_indices", None)) or bool(getattr(submesh, "bone_weights", None))
            for submesh in target_submeshes
        )

        stored_native = restored_native_sessions
        if not stored_native and target_sessions:
            binary = find_native_mesh_core_binary()
            stored_native = binary is not None
            if binary is not None:
                for raw_item in restore_items:
                    if not isinstance(raw_item, Mapping):
                        stored_native = False
                        break
                    submesh_index = _index(raw_item.get("index"))
                    if submesh_index is None or submesh_index not in target_sessions:
                        continue
                    session_item = _mesh_session_item_from_native_snapshot(raw_item)
                    if session_item is None:
                        stored_native = False
                        break
                    report = _run_native_mesh_core_service_job(
                        binary,
                        "mesh-session-json",
                        {
                            "version": 1,
                            "backend": NATIVE_MESH_CORE_BACKEND_ID,
                            "operation": "store",
                            "session_id": target_sessions[submesh_index],
                            "submeshes": [session_item],
                        },
                        **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
                    )
                    if report is None:
                        stored_native = False
                        break
        if stored_native:
            with _native_mesh_core_session_cache_lock:
                for submesh_index, session_id in target_sessions.items():
                    _native_mesh_core_session_cache[_native_mesh_session_cache_key(target_mesh, submesh_index)] = (
                        _native_mesh_session_signature(target_mesh.submeshes[submesh_index]),
                        session_id,
                    )
        else:
            _invalidate_native_mesh_session_submeshes(target_mesh, restored_indices)
        return True
    finally:
        dispose_native_mesh_submesh_snapshot(
            snapshot,
            stop_event=stop_event,
            timeout_seconds=min(float(timeout_seconds or 5.0), 2.0),
        )


def _restore_native_submesh_snapshot_handle_sessions(
    snapshot: Mapping[str, object],
    *,
    stop_event: threading.Event | None,
    timeout_seconds: float,
) -> bool:
    handle = snapshot.get("handle")
    if not isinstance(handle, Mapping):
        return False
    snapshot_id = str(handle.get("id") or "").strip()
    if not snapshot_id:
        return False
    raw_submeshes = snapshot.get("submeshes")
    if not isinstance(raw_submeshes, list):
        return False
    requested: list[dict[str, object]] = []
    for raw_item in raw_submeshes:
        if not isinstance(raw_item, Mapping):
            return False
        submesh_index = _index(raw_item.get("index"))
        vertex_count = _index(raw_item.get("vertex_count"))
        session_id = str(raw_item.get("session_id") or "").strip()
        if submesh_index is None or vertex_count is None:
            return False
        if vertex_count <= 0:
            continue
        if not session_id:
            return False
        requested.append({"index": submesh_index, "session_id": session_id})
    if not requested:
        return False
    binary = find_native_mesh_core_binary()
    if binary is None:
        return False
    try:
        report = _run_native_mesh_core_service_job(
            binary,
            "snapshot-submeshes-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "restore_snapshot",
                "snapshot_id": snapshot_id,
                "submeshes": requested,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return False
    if not isinstance(report, Mapping) or str(report.get("status") or "").strip().lower() != "ok":
        return False
    return _index(report.get("restored_submesh_count")) == len(requested)


def _native_submesh_snapshot_handle(report: object, snapshot_id: str) -> dict[str, object] | None:
    if not isinstance(report, Mapping):
        return None
    raw_handle = report.get("snapshot_handle")
    if not isinstance(raw_handle, Mapping):
        return None
    raw_id = str(raw_handle.get("id") or "").strip()
    if raw_id != snapshot_id:
        return None
    return {
        "id": raw_id,
        "submesh_count": int(_index(raw_handle.get("submesh_count")) or 0),
        "vertex_count": int(_index(raw_handle.get("vertex_count")) or 0),
        "face_count": int(_index(raw_handle.get("face_count")) or 0),
    }


def _export_native_submesh_snapshot_handle(
    snapshot: Mapping[str, object],
    *,
    stop_event: threading.Event | None,
    timeout_seconds: float,
) -> dict[str, object] | None:
    handle = snapshot.get("handle")
    if not isinstance(handle, Mapping):
        return None
    snapshot_id = str(handle.get("id") or "").strip()
    if not snapshot_id:
        return None
    raw_submeshes = snapshot.get("submeshes")
    if not isinstance(raw_submeshes, list):
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    requested: list[dict[str, object]] = []
    metadata_by_index: dict[int, tuple[dict[str, object], int, int]] = {}
    empty_items: dict[int, dict[str, object]] = {}
    for raw_item in raw_submeshes:
        if not isinstance(raw_item, Mapping):
            return None
        submesh_index = _index(raw_item.get("index"))
        vertex_count = _index(raw_item.get("vertex_count"))
        face_count = _index(raw_item.get("face_count"))
        if submesh_index is None or vertex_count is None or face_count is None:
            return None
        metadata = dict(raw_item.get("metadata") or {}) if isinstance(raw_item.get("metadata"), Mapping) else {}
        if vertex_count <= 0:
            empty_items[submesh_index] = dict(raw_item)
            continue
        requested.append(
            {
                "index": submesh_index,
                "session_id": str(raw_item.get("session_id") or "").strip(),
                "vertices_output_path": _native_preview_delta_output_path("_snapshot_handle_vertices.bin"),
                "faces_output_path": _native_preview_delta_output_path("_snapshot_handle_faces.bin"),
                "source_face_indices_output_path": _native_preview_delta_output_path("_snapshot_handle_source_faces.bin"),
                "normals_output_path": _native_preview_delta_output_path("_snapshot_handle_normals.bin"),
                "uvs_output_path": _native_preview_delta_output_path("_snapshot_handle_uvs.bin"),
                "tangents_output_path": _native_preview_delta_output_path("_snapshot_handle_tangents.bin"),
                "tangent_signs_output_path": _native_preview_delta_output_path("_snapshot_handle_tangent_signs.bin"),
                "bone_counts_output_path": _native_preview_delta_output_path("_snapshot_handle_bone_counts.bin"),
                "bone_indices_output_path": _native_preview_delta_output_path("_snapshot_handle_bone_indices.bin"),
                "bone_weights_output_path": _native_preview_delta_output_path("_snapshot_handle_bone_weights.bin"),
                "source_vertex_map_output_path": _native_preview_delta_output_path("_snapshot_handle_source_vertex_map.bin"),
                "source_vertex_offsets_output_path": _native_preview_delta_output_path("_snapshot_handle_source_vertex_offsets.bin"),
            }
        )
        metadata_by_index[submesh_index] = (metadata, vertex_count, face_count)
    if not requested:
        return None
    report = _run_native_mesh_core_service_job(
        binary,
        "snapshot-submeshes-json",
        {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "export_snapshot",
            "snapshot_id": snapshot_id,
            "submeshes": requested,
        },
        **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
    )
    if report is None:
        return None
    exported_items = dict(empty_items)
    for raw_exported in tuple(report.get("submeshes") or ()) if isinstance(report, Mapping) else ():
        if not isinstance(raw_exported, Mapping):
            continue
        submesh_index = _index(raw_exported.get("index"))
        if submesh_index is None or submesh_index not in metadata_by_index:
            continue
        metadata, expected_vertices, expected_faces = metadata_by_index[submesh_index]
        exported_item = _native_submesh_snapshot_item(
            raw_exported,
            metadata=metadata,
            expected_vertices=expected_vertices,
            expected_faces=expected_faces,
        )
        if exported_item is None:
            return None
        exported_items[submesh_index] = exported_item
    if len(exported_items) != len(raw_submeshes):
        return None
    return {
        "kind": "native_submesh_snapshot",
        "mesh": dict(snapshot.get("mesh") or {}) if isinstance(snapshot.get("mesh"), Mapping) else {},
        "handle": dict(handle),
        "submeshes": [exported_items[index] for index in sorted(exported_items)],
    }


def dispose_native_mesh_submesh_snapshot(
    snapshot: Mapping[str, object] | object,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 2.0,
) -> bool:
    if not isinstance(snapshot, Mapping) or snapshot.get("kind") != "native_submesh_snapshot":
        return False
    handle = snapshot.get("handle")
    if not isinstance(handle, Mapping):
        return False
    snapshot_id = str(handle.get("id") or "").strip()
    if not snapshot_id:
        return False
    binary = find_native_mesh_core_binary()
    if binary is None:
        return False
    try:
        report = _run_native_mesh_core_service_job(
            binary,
            "snapshot-submeshes-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "clear_snapshot",
                "snapshot_id": snapshot_id,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return False
    return isinstance(report, Mapping) and str(report.get("status") or "").strip().lower() == "ok"


def dispose_native_mesh_sparse_vertex_snapshot(
    snapshot: Mapping[str, object] | object,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 2.0,
) -> bool:
    if isinstance(snapshot, Mapping):
        handle = snapshot.get("handle") if isinstance(snapshot.get("handle"), Mapping) else snapshot
        snapshot_id = str(
            handle.get("native_sparse_snapshot_id")  # type: ignore[union-attr]
            or handle.get("sparse_snapshot_id")  # type: ignore[union-attr]
            or handle.get("id")  # type: ignore[union-attr]
            or ""
        ).strip()
    else:
        snapshot_id = str(snapshot or "").strip()
    if not snapshot_id:
        return False
    binary = find_native_mesh_core_binary()
    if binary is None:
        return False
    try:
        report = _run_native_mesh_core_service_job(
            binary,
            "snapshot-vertices-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "clear_sparse_snapshot",
                "sparse_snapshot_id": snapshot_id,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return False
    return isinstance(report, Mapping) and str(report.get("status") or "").strip().lower() == "ok"


def _mesh_snapshot_metadata(mesh: ParsedMesh) -> dict[str, object]:
    return {
        "path": str(getattr(mesh, "path", "") or ""),
        "format": str(getattr(mesh, "format", "") or ""),
        "bbox_min": _vec3(getattr(mesh, "bbox_min", (0.0, 0.0, 0.0)), fallback=0.0),
        "bbox_max": _vec3(getattr(mesh, "bbox_max", (0.0, 0.0, 0.0)), fallback=0.0),
    }


def _submesh_snapshot_metadata(submesh: object) -> dict[str, object]:
    metadata: dict[str, object] = {
        "name": str(getattr(submesh, "name", "") or ""),
        "material": str(getattr(submesh, "material", "") or ""),
        "texture": str(getattr(submesh, "texture", "") or ""),
        "source_index_offset": int(getattr(submesh, "source_index_offset", -1) or -1),
        "source_index_count": int(getattr(submesh, "source_index_count", 0) or 0),
        "source_vertex_stride": int(getattr(submesh, "source_vertex_stride", 0) or 0),
        "source_descriptor_offset": int(getattr(submesh, "source_descriptor_offset", -1) or -1),
        "source_bbox_min": _vec3(getattr(submesh, "source_bbox_min", (0.0, 0.0, 0.0)), fallback=0.0),
        "source_bbox_extent": _vec3(getattr(submesh, "source_bbox_extent", (0.0, 0.0, 0.0)), fallback=0.0),
        "source_lod_count": int(getattr(submesh, "source_lod_count", 0) or 0),
    }
    extra_attrs: dict[str, object] = {}
    for attr_name in _EXTRA_SUBMESH_ATTRS:
        if attr_name in _TRANSIENT_NATIVE_SUBMESH_ATTRS:
            continue
        if hasattr(submesh, attr_name):
            extra_attrs[attr_name] = _snapshot_metadata_value(getattr(submesh, attr_name))
    if extra_attrs:
        metadata["extra_attrs"] = extra_attrs
    return metadata


def _snapshot_metadata_value(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _snapshot_metadata_value(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _snapshot_metadata_value(item) for key, item in value.items()}
    if isinstance(value, (list, set, tuple)):
        return [_snapshot_metadata_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _native_submesh_snapshot_item(
    item: Mapping[str, object],
    *,
    metadata: Mapping[str, object],
    expected_vertices: int,
    expected_faces: int,
) -> dict[str, object] | None:
    submesh_index = _index(item.get("index"))
    vertex_count = _index(item.get("vertex_count"))
    face_count = _index(item.get("face_count"))
    if submesh_index is None or vertex_count != expected_vertices or face_count != expected_faces:
        return None
    vertices_binary = _native_binary_descriptor(item.get("vertices_binary"), expected_count=vertex_count, components=3, kind="f64")
    faces_binary = _native_binary_descriptor(item.get("faces_binary"), expected_count=face_count, components=3, kind="i32")
    if vertices_binary is None or faces_binary is None:
        return None
    result: dict[str, object] = {
        "index": submesh_index,
        "session_id": str(item.get("session_id") or "").strip(),
        "metadata": dict(metadata),
        "vertex_count": vertex_count,
        "face_count": face_count,
        "vertices_binary": vertices_binary,
        "faces_binary": faces_binary,
    }
    _copy_snapshot_descriptor(result, item, "source_face_indices_binary", expected_count=face_count, components=1, kind="i32")
    _copy_snapshot_i32_range(result, item, "source_face_start", "source_face_count", expected_count=face_count)
    for key, components, kind in (
        ("normals_binary", 3, "f64"),
        ("uvs_binary", 2, "f64"),
        ("tangents_binary", 3, "f64"),
        ("tangent_signs_binary", 1, "f64"),
        ("source_vertex_map_binary", 1, "i32"),
        ("source_vertex_offsets_binary", 1, "i32"),
        ("bone_counts_binary", 1, "i32"),
    ):
        _copy_snapshot_descriptor(result, item, key, expected_count=vertex_count, components=components, kind=kind)
    _copy_snapshot_i32_range(result, item, "source_vertex_map_start", "source_vertex_map_count", expected_count=vertex_count)
    _copy_snapshot_i32_stride_range(result, item, expected_count=vertex_count)
    raw_bone_indices = item.get("bone_indices_binary")
    raw_bone_weights = item.get("bone_weights_binary")
    bone_index_count = _index(raw_bone_indices.get("count")) if isinstance(raw_bone_indices, Mapping) else None
    bone_weight_count = _index(raw_bone_weights.get("count")) if isinstance(raw_bone_weights, Mapping) else None
    if bone_index_count is not None and bone_weight_count == bone_index_count:
        _copy_snapshot_descriptor(result, item, "bone_indices_binary", expected_count=bone_index_count, components=1, kind="i32")
        _copy_snapshot_descriptor(result, item, "bone_weights_binary", expected_count=bone_index_count, components=1, kind="f64")
    return result


def _copy_snapshot_descriptor(
    target: dict[str, object],
    source: Mapping[str, object],
    key: str,
    *,
    expected_count: int,
    components: int,
    kind: str,
) -> None:
    descriptor = _native_binary_descriptor(source.get(key), expected_count=expected_count, components=components, kind=kind)
    if descriptor is not None:
        target[key] = descriptor


def _copy_snapshot_i32_range(
    target: dict[str, object],
    source: Mapping[str, object],
    start_key: str,
    count_key: str,
    *,
    expected_count: int,
) -> None:
    start = _index(source.get(start_key))
    count = _index(source.get(count_key))
    if start is not None and start >= 0 and count == expected_count:
        target[start_key] = start
        target[count_key] = count


def _copy_snapshot_i32_stride_range(target: dict[str, object], source: Mapping[str, object], *, expected_count: int) -> None:
    start = _index(source.get("source_vertex_offsets_start"))
    count = _index(source.get("source_vertex_offsets_count"))
    stride = _index(source.get("source_vertex_offsets_stride"))
    if start is not None and start >= 0 and count == expected_count and stride is not None and stride > 0:
        target["source_vertex_offsets_start"] = start
        target["source_vertex_offsets_count"] = count
        target["source_vertex_offsets_stride"] = stride


def _submesh_from_native_snapshot_item(item: Mapping[str, object]) -> SubMesh | None:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
    vertex_count = _index(item.get("vertex_count"))
    face_count = _index(item.get("face_count"))
    if vertex_count is None or face_count is None or vertex_count < 0 or face_count < 0:
        return None
    if vertex_count:
        vertices = _read_vec3_binary_report_payload(item.get("vertices_binary"), expected_count=vertex_count)
        faces = _read_face_binary_report_payload(item.get("faces_binary"), expected_count=face_count, vertex_count=vertex_count)
        if vertices is None or faces is None:
            return None
    else:
        vertices = []
        faces = []
    normals = _read_vec3_binary_report_payload(item.get("normals_binary"), expected_count=vertex_count) or []
    uvs = _read_vec2_binary_report_payload(item.get("uvs_binary"), expected_count=vertex_count) or []
    tangents = _read_vec3_binary_report_payload(item.get("tangents_binary"), expected_count=vertex_count) or []
    tangent_signs = _read_f64_binary_report_payload(item.get("tangent_signs_binary"), expected_count=vertex_count) or []
    bones = None
    if item.get("bone_counts_binary") is not None:
        bones = _read_bone_binary_report_payloads(
            item.get("bone_counts_binary"),
            item.get("bone_indices_binary"),
            item.get("bone_weights_binary"),
            expected_count=vertex_count,
        )
        if bones is None:
            return None
    source_vertex_map = _read_i32_binary_report_payload(item.get("source_vertex_map_binary"), expected_count=vertex_count) or []
    if not source_vertex_map:
        source_vertex_map = list(
            _i32_range_report_values(
                item,
                start_key="source_vertex_map_start",
                count_key="source_vertex_map_count",
                max_count=1 << 30,
            )
            or ()
        )
        if source_vertex_map and len(source_vertex_map) != vertex_count:
            return None
    source_vertex_offsets = _read_i32_binary_report_payload(item.get("source_vertex_offsets_binary"), expected_count=vertex_count) or []
    if not source_vertex_offsets:
        source_vertex_offsets = list(_i32_stride_range_report_values(item, max_count=vertex_count) or ())
        if source_vertex_offsets and len(source_vertex_offsets) != vertex_count:
            return None
    submesh = SubMesh(
        name=str(metadata.get("name") or ""),
        material=str(metadata.get("material") or ""),
        texture=str(metadata.get("texture") or ""),
        vertices=list(vertices),
        uvs=list(uvs),
        normals=list(normals),
        tangents=list(tangents),
        faces=list(faces),
        bone_indices=list(bones[0]) if bones is not None else [],
        bone_weights=list(bones[1]) if bones is not None else [],
        source_vertex_map=list(source_vertex_map),
        vertex_count=len(vertices),
        face_count=len(faces),
        source_vertex_offsets=list(source_vertex_offsets),
        source_index_offset=int(metadata.get("source_index_offset") or -1),
        source_index_count=int(metadata.get("source_index_count") or 0),
        source_vertex_stride=int(metadata.get("source_vertex_stride") or 0),
        source_descriptor_offset=int(metadata.get("source_descriptor_offset") or -1),
        source_bbox_min=_vec3(metadata.get("source_bbox_min"), fallback=0.0),
        source_bbox_extent=_vec3(metadata.get("source_bbox_extent"), fallback=0.0),
        source_lod_count=int(metadata.get("source_lod_count") or 0),
    )
    if tangent_signs:
        setattr(submesh, "tangent_signs", list(tangent_signs))
    extra_attrs = metadata.get("extra_attrs")
    if isinstance(extra_attrs, Mapping):
        for raw_name, value in extra_attrs.items():
            attr_name = str(raw_name or "").strip()
            if attr_name and attr_name not in _TRANSIENT_NATIVE_SUBMESH_ATTRS:
                setattr(submesh, attr_name, _snapshot_metadata_value(value))
    return submesh


def _mesh_session_item_from_native_snapshot(item: Mapping[str, object]) -> dict[str, object] | None:
    submesh_index = _index(item.get("index"))
    if submesh_index is None:
        return None
    session_item: dict[str, object] = {"index": submesh_index}
    for key in (
        "vertices_binary",
        "faces_binary",
        "source_face_indices_binary",
        "normals_binary",
        "uvs_binary",
        "tangents_binary",
        "tangent_signs_binary",
        "bone_counts_binary",
        "bone_indices_binary",
        "bone_weights_binary",
        "source_vertex_map_binary",
        "source_vertex_offsets_binary",
    ):
        if isinstance(item.get(key), Mapping):
            session_item[key] = item[key]
    if "source_face_indices_binary" not in session_item:
        source_face_start = _index(item.get("source_face_start"))
        source_face_count = _index(item.get("source_face_count"))
        if source_face_start is not None and source_face_start >= 0 and source_face_count is not None and source_face_count >= 0:
            session_item["source_face_start"] = source_face_start
            session_item["source_face_count"] = source_face_count
    if "source_vertex_map_binary" not in session_item:
        source_vertex_map_start = _index(item.get("source_vertex_map_start"))
        source_vertex_map_count = _index(item.get("source_vertex_map_count"))
        if (
            source_vertex_map_start is not None
            and source_vertex_map_start >= 0
            and source_vertex_map_count is not None
            and source_vertex_map_count >= 0
        ):
            session_item["source_vertex_map_start"] = source_vertex_map_start
            session_item["source_vertex_map_count"] = source_vertex_map_count
    if "source_vertex_offsets_binary" not in session_item:
        source_vertex_offsets_start = _index(item.get("source_vertex_offsets_start"))
        source_vertex_offsets_count = _index(item.get("source_vertex_offsets_count"))
        source_vertex_offsets_stride = _index(item.get("source_vertex_offsets_stride"))
        if (
            source_vertex_offsets_start is not None
            and source_vertex_offsets_start >= 0
            and source_vertex_offsets_count is not None
            and source_vertex_offsets_count >= 0
            and source_vertex_offsets_stride is not None
            and source_vertex_offsets_stride > 0
        ):
            session_item["source_vertex_offsets_start"] = source_vertex_offsets_start
            session_item["source_vertex_offsets_count"] = source_vertex_offsets_count
            session_item["source_vertex_offsets_stride"] = source_vertex_offsets_stride
    return session_item if "vertices_binary" in session_item and "faces_binary" in session_item else None


def apply_native_mesh_selection(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, set[int]],
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    selected_faces_by_submesh: Mapping[int, set[int]] | None = None,
    source_indices: Sequence[int] = (),
    operation: str,
    iterations: int = 1,
    stop_event: threading.Event | None = None,
    metrics_out: dict[str, float] | None = None,
    timeout_seconds: float = 5.0,
) -> dict[int, set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    normalized_operation = str(operation or "").strip().lower()
    if normalized_operation not in {"grow", "shrink", "smooth", "invert", "all"}:
        return None
    selected_edges_by_submesh = selected_edges_by_submesh or {}
    selected_faces_by_submesh = selected_faces_by_submesh or {}
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_selection_"))
    try:
        submeshes = []
        requested_sources = {
            parsed
            for raw in source_indices or ()
            for parsed in (_index(raw),)
            if parsed is not None and 0 <= parsed < len(mesh.submeshes)
        }
        target_indices = set(requested_sources)
        for mapping in (selected_vertices_by_submesh, selected_edges_by_submesh, selected_faces_by_submesh):
            for raw_index in mapping:
                parsed = _index(raw_index)
                if parsed is not None:
                    target_indices.add(parsed)
        for submesh_index in sorted(target_indices):
            if not 0 <= int(submesh_index) < len(mesh.submeshes):
                continue
            submesh_index = int(submesh_index)
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(submesh.vertices)
            face_count = len(submesh.faces or ())
            kept = sorted(
                index
                for raw_index in selected_vertices_by_submesh.get(submesh_index, set())
                for index in (_index(raw_index),)
                if index is not None and 0 <= index < vertex_count
            )
            kept_edges = sorted(
                (min(left, right), max(left, right))
                for raw_edge in selected_edges_by_submesh.get(submesh_index, set())
                if isinstance(raw_edge, (tuple, list)) and len(raw_edge) >= 2
                for left in (_index(raw_edge[0]),)
                for right in (_index(raw_edge[1]),)
                if left is not None and right is not None and 0 <= left < vertex_count and 0 <= right < vertex_count and left != right
            )
            kept_faces = sorted(
                index
                for raw_index in selected_faces_by_submesh.get(submesh_index, set())
                for index in (_index(raw_index),)
                if index is not None and 0 <= index < face_count
            )
            selected_all_vertices = normalized_operation != "invert" and submesh_index in requested_sources
            invert_scope = normalized_operation == "invert" and submesh_index in requested_sources
            if vertex_count <= 0 or (face_count <= 0 and not selected_all_vertices) or not (kept or kept_edges or kept_faces or selected_all_vertices or invert_scope):
                continue
            prefix = sidecar_root / f"selection_{submesh_index}"
            item: dict[str, object] = {"index": submesh_index}
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                faces = _face_json(submesh.faces, vertex_count)
                if not faces:
                    continue
                item["vertex_count"] = vertex_count
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
            if kept:
                _put_i32_range_or_binary_payload(
                    item,
                    values=kept,
                    start_key="selected_vertex_start",
                    count_key="selected_vertex_count",
                    binary_key="selected_vertices_binary",
                    binary_path=prefix.with_name(prefix.name + "_selected.bin"),
                    max_count=vertex_count,
                )
            if kept_edges:
                item["selected_edges_binary"] = _write_edge_binary_payload(prefix.with_name(prefix.name + "_selected_edges.bin"), kept_edges)
            if kept_faces:
                _put_i32_range_or_binary_payload(
                    item,
                    values=kept_faces,
                    start_key="selected_face_start",
                    count_key="selected_face_count",
                    binary_key="selected_faces_binary",
                    binary_path=prefix.with_name(prefix.name + "_selected_faces.bin"),
                    max_count=face_count,
                )
            if selected_all_vertices:
                item["selected_all_vertices"] = True
            item["selected_vertices_output_path"] = _native_preview_delta_output_path("_selection_vertices.bin")
            submeshes.append(item)
        if not submeshes:
            return {}
        report = _run_native_mesh_core_job(
            binary,
            "selection-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "selection",
                "selection": {
                    "operation": normalized_operation,
                    "iterations": max(0, _index(iterations) or 0),
                },
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    if metrics_out is not None:
        metrics_out.update(_native_report_metrics(report))
    return _apply_selection_report(mesh, report)


def build_native_mesh_selection_groups(
    mesh: ParsedMesh,
    *,
    vertices_by_submesh: Mapping[int, set[int]],
    edges_by_submesh: Mapping[int, set[tuple[int, int]]],
    faces_by_submesh: Mapping[int, set[int]],
    source_indices: Sequence[int] = (),
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> list[dict[str, object]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_selection_preview_"))
    try:
        requested_sources = {
            int(index)
            for index in source_indices or ()
            if isinstance(index, int) and 0 <= int(index) < len(mesh.submeshes)
        }
        target_indices = set(vertices_by_submesh) | set(edges_by_submesh) | set(faces_by_submesh) | requested_sources
        submeshes = []
        for submesh_index in sorted(target_indices):
            if not 0 <= int(submesh_index) < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[int(submesh_index)]
            vertex_count = len(submesh.vertices or [])
            selected_vertices = sorted(index for index in vertices_by_submesh.get(int(submesh_index), set()) if 0 <= index < vertex_count)
            selected_edges = sorted(
                (min(int(left), int(right)), max(int(left), int(right)))
                for left, right in edges_by_submesh.get(int(submesh_index), set())
                if 0 <= int(left) < vertex_count and 0 <= int(right) < vertex_count and int(left) != int(right)
            )
            selected_faces = sorted(
                face_index
                for raw_index in faces_by_submesh.get(int(submesh_index), set())
                if (face_index := _index(raw_index)) is not None and face_index >= 0
            )
            selected_all_vertices = int(submesh_index) in requested_sources
            if vertex_count <= 0 or not (selected_vertices or selected_edges or selected_faces or selected_all_vertices):
                continue
            prefix = sidecar_root / f"selection_preview_{submesh_index}"
            item: dict[str, object] = {
                "index": int(submesh_index),
                "selection_preview_output_path": _native_preview_delta_output_path("_selection.bin"),
            }
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                int(submesh_index),
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                faces, source_face_indices = _face_json_with_source_indices(submesh.faces, vertex_count)
                item["vertex_count"] = vertex_count
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                _put_source_face_indices_payload(item, prefix, source_face_indices)
            if selected_vertices:
                _put_i32_range_or_binary_payload(
                    item,
                    values=selected_vertices,
                    start_key="selected_vertex_start",
                    count_key="selected_vertex_count",
                    binary_key="selected_vertices_binary",
                    binary_path=prefix.with_name(prefix.name + "_selected_vertices.bin"),
                    max_count=vertex_count,
                )
            if selected_edges:
                item["selected_edges_binary"] = _write_edge_binary_payload(prefix.with_name(prefix.name + "_selected_edges.bin"), selected_edges)
            if selected_faces:
                _put_i32_range_or_binary_payload(
                    item,
                    values=selected_faces,
                    start_key="selected_face_start",
                    count_key="selected_face_count",
                    binary_key="selected_faces_binary",
                    binary_path=prefix.with_name(prefix.name + "_selected_faces.bin"),
                )
            if selected_all_vertices:
                item["selected_all_vertices"] = True
            submeshes.append(item)
        if not submeshes:
            return []
        report = _run_native_mesh_core_job(
            binary,
            "selection-preview-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "selection_preview",
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
        if report is None:
            return None
        raw_groups = report.get("groups")
        if not isinstance(raw_groups, list):
            return None
        groups: list[dict[str, object]] = []
        for raw_group in raw_groups:
            if not isinstance(raw_group, Mapping):
                continue
            source_submesh_index = _index(raw_group.get("source_submesh_index"))
            if source_submesh_index is None or not 0 <= source_submesh_index < len(mesh.submeshes):
                continue
            group = _native_selection_preview_group(raw_group, source_submesh_index)
            if group is None:
                continue
            groups.append(group)
        return groups
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def _native_selection_operation(value: object) -> str:
    operation = str(value or "replace").strip().lower()
    if operation == "extend":
        operation = "add"
    elif operation == "remove":
        operation = "subtract"
    return operation if operation in {"add", "subtract", "toggle"} else "replace"


def _combine_native_selection_sources(
    submesh_count: int,
    current: Sequence[int],
    incoming: Sequence[int],
    operation: str,
) -> tuple[int, ...]:
    current_set = {
        index
        for raw_index in (current if current is not None else ())
        if (index := _index(raw_index)) is not None and 0 <= index < submesh_count
    }
    incoming_set = {
        index
        for raw_index in (incoming if incoming is not None else ())
        if (index := _index(raw_index)) is not None and 0 <= index < submesh_count
    }
    if operation == "add":
        current_set.update(incoming_set)
        return tuple(sorted(current_set))
    if operation == "subtract":
        current_set.difference_update(incoming_set)
        return tuple(sorted(current_set))
    if operation == "toggle":
        for index in incoming_set:
            if index in current_set:
                current_set.remove(index)
            else:
                current_set.add(index)
        return tuple(sorted(current_set))
    return tuple(sorted(incoming_set))


def select_native_mesh_uv_vertices(
    mesh: ParsedMesh,
    *,
    mode: str,
    uv_min: Sequence[object] = (0.0, 0.0),
    uv_max: Sequence[object] = (0.0, 0.0),
    points: Sequence[Sequence[object]] = (),
    timeout_seconds: float = 5.0,
) -> dict[int, set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    selection_mode = str(mode or "region").strip().lower()
    if selection_mode not in {"region", "lasso"}:
        return None
    polygon = [_vec2_json(point) for point in points or ()]
    if selection_mode == "lasso" and len(polygon) < 3:
        return {}
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_uv_selection_"))
    try:
        submeshes: list[dict[str, object]] = []
        for submesh_index, submesh in enumerate(mesh.submeshes or ()):
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            if vertex_count <= 0:
                continue
            prefix = sidecar_root / f"uv_selection_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "selected_vertices_output_path": _native_preview_delta_output_path("_uv_selected_vertices.bin"),
            }
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                uvs = getattr(submesh, "uvs", ()) or ()
                if len(uvs) != vertex_count:
                    continue
                item["vertex_count"] = vertex_count
                item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), uvs)
            submeshes.append(item)
        if not submeshes:
            return {}
        report = _run_native_mesh_core_job(
            binary,
            "uv-selection-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "uv_selection",
                "mode": selection_mode,
                "uv_min": _vec2_json(uv_min),
                "uv_max": _vec2_json(uv_max),
                "points": polygon,
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    return _apply_selection_report(mesh, report)


def summarize_native_mesh_uvs(
    mesh: ParsedMesh,
    selection: object | None = None,
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    selected_vertices_by_submesh: Mapping[int, set[int]] = {}
    selected_faces_by_submesh: Mapping[int, set[int]] = {}
    selected_source_indices: set[int] = set()
    if selection is not None:
        try:
            selected_vertices_by_submesh = selection.vertex_map()  # type: ignore[assignment,union-attr]
            selected_faces_by_submesh = selection.face_map()  # type: ignore[assignment,union-attr]
            selected_source_indices = {
                index
                for raw_index in getattr(selection, "source_indices", ()) or ()
                if (index := _index(raw_index)) is not None and index >= 0
            }
        except AttributeError:
            selected_vertices_by_submesh = {}
            selected_faces_by_submesh = {}
            selected_source_indices = set()
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_uv_summary_"))
    try:
        submeshes: list[dict[str, object]] = []
        for submesh_index, submesh in enumerate(mesh.submeshes or ()):
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            if vertex_count <= 0:
                continue
            prefix = sidecar_root / f"uv_summary_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "part_name": str(getattr(submesh, "name", "") or f"part_{submesh_index}"),
                "material": str(getattr(submesh, "material", "") or ""),
                "texture": str(getattr(submesh, "texture", "") or ""),
                "source_selected": submesh_index in selected_source_indices,
            }
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                uvs = getattr(submesh, "uvs", ()) or ()
                raw_faces = getattr(submesh, "faces", ()) or ()
                if len(uvs) != vertex_count or not raw_faces:
                    continue
                faces, source_face_indices = _face_json_with_source_indices(raw_faces, vertex_count)
                if not faces:
                    continue
                item["vertex_count"] = vertex_count
                item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), uvs)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                _put_source_face_indices_payload(item, prefix, source_face_indices)
            selected_vertices = sorted(
                index
                for raw_index in selected_vertices_by_submesh.get(submesh_index, set())
                if (index := _index(raw_index)) is not None and 0 <= index < vertex_count
            )
            selected_faces = sorted(
                index
                for raw_index in selected_faces_by_submesh.get(submesh_index, set())
                if (index := _index(raw_index)) is not None and index >= 0
            )
            if selected_vertices:
                _put_i32_range_or_binary_payload(
                    item,
                    values=selected_vertices,
                    start_key="selected_vertex_start",
                    count_key="selected_vertex_count",
                    binary_key="selected_vertices_binary",
                    binary_path=prefix.with_name(prefix.name + "_selected_vertices.bin"),
                    max_count=vertex_count,
                )
            if selected_faces:
                _put_i32_range_or_binary_payload(
                    item,
                    values=selected_faces,
                    start_key="selected_face_start",
                    count_key="selected_face_count",
                    binary_key="selected_faces_binary",
                    binary_path=prefix.with_name(prefix.name + "_selected_faces.bin"),
                )
            submeshes.append(item)
        if not submeshes:
            return {"status": "ok", "operation": "uv_summary", "island_count": 0, "selected_island_count": 0, "islands": []}
        report = _run_native_mesh_core_job(
            binary,
            "uv-summary-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "uv_summary",
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if not isinstance(report, dict):
        return None
    if str(report.get("operation") or "") != "uv_summary":
        return None
    return report


def prune_native_mesh_selection(
    mesh: ParsedMesh,
    *,
    vertices_by_submesh: Mapping[int, set[int]],
    edges_by_submesh: Mapping[int, set[tuple[int, int]]],
    faces_by_submesh: Mapping[int, set[int]],
    selected_all_vertices_by_submesh: Sequence[int] = (),
    source_indices: Sequence[int] = (),
    current_vertices_by_submesh: Mapping[int, set[int]] | None = None,
    current_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    current_faces_by_submesh: Mapping[int, set[int]] | None = None,
    current_source_indices: Sequence[int] = (),
    selection_operation: object = "replace",
    metrics_out: dict[str, float] | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    operation = _native_selection_operation(selection_operation)
    valid_sources = _combine_native_selection_sources(
        len(mesh.submeshes),
        current_source_indices,
        source_indices,
        operation,
    )
    current_vertices_by_submesh = current_vertices_by_submesh or {}
    current_edges_by_submesh = current_edges_by_submesh or {}
    current_faces_by_submesh = current_faces_by_submesh or {}
    selected_all_vertex_sources: set[int] = set()
    for raw_index in (selected_all_vertices_by_submesh if selected_all_vertices_by_submesh is not None else ()):
        index = _index(raw_index)
        if index is not None and 0 <= index < len(mesh.submeshes):
            selected_all_vertex_sources.add(index)
    target_indices = (
        set(vertices_by_submesh)
        | set(edges_by_submesh)
        | set(faces_by_submesh)
        | selected_all_vertex_sources
        | set(current_vertices_by_submesh)
        | set(current_edges_by_submesh)
        | set(current_faces_by_submesh)
    )
    if not target_indices:
        return {
            "vertices_by_submesh": {},
            "edges_by_submesh": {},
            "faces_by_submesh": {},
            "source_indices": valid_sources,
        }
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_selection_prune_"))
    try:
        submeshes = []
        for raw_submesh_index in sorted(target_indices):
            submesh_index = _index(raw_submesh_index)
            if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            face_count = len(getattr(submesh, "faces", ()) or ())
            selected_vertices = sorted(
                index
                for raw_index in vertices_by_submesh.get(submesh_index, set())
                if (index := _index(raw_index)) is not None and 0 <= index < vertex_count
            )
            selected_edges = sorted(
                (min(left, right), max(left, right))
                for raw_edge in edges_by_submesh.get(submesh_index, set())
                if isinstance(raw_edge, (tuple, list)) and len(raw_edge) >= 2
                for left in (_index(raw_edge[0]),)
                for right in (_index(raw_edge[1]),)
                if left is not None and right is not None and 0 <= left < vertex_count and 0 <= right < vertex_count and left != right
            )
            selected_faces = sorted(
                index
                for raw_index in faces_by_submesh.get(submesh_index, set())
                if (index := _index(raw_index)) is not None and index >= 0
            )
            current_selected_vertices = sorted(
                index
                for raw_index in current_vertices_by_submesh.get(submesh_index, set())
                if (index := _index(raw_index)) is not None and 0 <= index < vertex_count
            )
            current_selected_edges = sorted(
                (min(left, right), max(left, right))
                for raw_edge in current_edges_by_submesh.get(submesh_index, set())
                if isinstance(raw_edge, (tuple, list)) and len(raw_edge) >= 2
                for left in (_index(raw_edge[0]),)
                for right in (_index(raw_edge[1]),)
                if left is not None and right is not None and 0 <= left < vertex_count and 0 <= right < vertex_count and left != right
            )
            current_selected_faces = sorted(
                index
                for raw_index in current_faces_by_submesh.get(submesh_index, set())
                if (index := _index(raw_index)) is not None and index >= 0
            )
            selected_all_vertices = submesh_index in selected_all_vertex_sources
            if vertex_count <= 0 or not (
                selected_vertices
                or selected_edges
                or selected_faces
                or selected_all_vertices
                or current_selected_vertices
                or current_selected_edges
                or current_selected_faces
            ):
                continue
            prefix = sidecar_root / f"selection_prune_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "face_count": face_count,
                "selection_operation": operation,
                "selected_vertices_output_path": _native_preview_delta_output_path("_pruned_vertices.bin"),
                "selected_edges_output_path": _native_preview_delta_output_path("_pruned_edges.bin"),
                "selected_faces_output_path": _native_preview_delta_output_path("_pruned_faces.bin"),
            }
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                faces, source_face_indices = _face_json_with_source_indices(submesh.faces, vertex_count)
                item["vertex_count"] = vertex_count
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                _put_source_face_indices_payload(item, prefix, source_face_indices)
            if selected_vertices:
                _put_i32_range_or_binary_payload(
                    item,
                    values=selected_vertices,
                    start_key="selected_vertex_start",
                    count_key="selected_vertex_count",
                    binary_key="selected_vertices_binary",
                    binary_path=prefix.with_name(prefix.name + "_selected_vertices.bin"),
                    max_count=vertex_count,
                )
            if selected_all_vertices:
                item["selected_all_vertices"] = True
            if selected_edges:
                item["selected_edges_binary"] = _write_edge_binary_payload(prefix.with_name(prefix.name + "_selected_edges.bin"), selected_edges)
            if selected_faces:
                _put_i32_range_or_binary_payload(
                    item,
                    values=selected_faces,
                    start_key="selected_face_start",
                    count_key="selected_face_count",
                    binary_key="selected_faces_binary",
                    binary_path=prefix.with_name(prefix.name + "_selected_faces.bin"),
                )
            if operation != "replace":
                if current_selected_vertices:
                    _put_i32_range_or_binary_payload(
                        item,
                        values=current_selected_vertices,
                        start_key="current_selected_vertex_start",
                        count_key="current_selected_vertex_count",
                        binary_key="current_selected_vertices_binary",
                        binary_path=prefix.with_name(prefix.name + "_current_vertices.bin"),
                        max_count=vertex_count,
                    )
                if current_selected_edges:
                    item["current_selected_edges_binary"] = _write_edge_binary_payload(
                        prefix.with_name(prefix.name + "_current_edges.bin"),
                        current_selected_edges,
                    )
                if current_selected_faces:
                    _put_i32_range_or_binary_payload(
                        item,
                        values=current_selected_faces,
                        start_key="current_selected_face_start",
                        count_key="current_selected_face_count",
                        binary_key="current_selected_faces_binary",
                        binary_path=prefix.with_name(prefix.name + "_current_faces.bin"),
                    )
            submeshes.append(item)
        if not submeshes:
            return {
                "vertices_by_submesh": {},
                "edges_by_submesh": {},
                "faces_by_submesh": {},
                "source_indices": valid_sources,
            }
        report = _run_native_mesh_core_job(
            binary,
            "selection-prune-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "selection_prune",
                "selection_operation": operation,
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    if metrics_out is not None:
        metrics_out.update(_native_report_metrics(report))
    raw_items = report.get("submeshes")
    if not isinstance(raw_items, list):
        return None
    vertices: dict[int, set[int]] = {}
    edges: dict[int, set[tuple[int, int]]] = {}
    faces: dict[int, set[int]] = {}
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        submesh_index = _index(raw_item.get("index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        vertex_count = len(getattr(submesh, "vertices", ()) or ())
        face_count = len(getattr(submesh, "faces", ()) or ())

        selected_vertices = _i32_range_report_values(
            raw_item,
            start_key="selected_vertex_start",
            count_key="selected_vertex_count",
            max_count=vertex_count,
        )
        if selected_vertices is None:
            selected_vertices = _read_int_binary_report_payload(raw_item.get("selected_vertices_binary"), max_count=vertex_count)
        if selected_vertices is None:
            selected_vertices = [index for index in _int_list(raw_item.get("selected_vertices")) if 0 <= index < vertex_count]
        if selected_vertices:
            vertices[submesh_index] = set(selected_vertices)

        edge_count = _index((raw_item.get("selected_edges_binary") or {}).get("count")) if isinstance(raw_item.get("selected_edges_binary"), Mapping) else None
        raw_edges = (
            _read_i32_components_binary_report_payload(raw_item.get("selected_edges_binary"), expected_count=edge_count, components=2)
            if edge_count is not None
            else None
        )
        selected_edges = {
            (min(left, right), max(left, right))
            for left, right in (raw_edges if raw_edges is not None else _edge_list(raw_item.get("selected_edges")))
            if 0 <= left < vertex_count and 0 <= right < vertex_count and left != right
        }
        if selected_edges:
            edges[submesh_index] = selected_edges

        selected_faces = _i32_range_report_values(
            raw_item,
            start_key="selected_face_start",
            count_key="selected_face_count",
            max_count=face_count,
        )
        if selected_faces is None:
            selected_faces = _read_int_binary_report_payload(raw_item.get("selected_faces_binary"), max_count=face_count)
        if selected_faces is None:
            selected_faces = [index for index in _int_list(raw_item.get("selected_faces")) if 0 <= index < face_count]
        if selected_faces:
            faces[submesh_index] = set(selected_faces)
    return {
        "vertices_by_submesh": vertices,
        "edges_by_submesh": edges,
        "faces_by_submesh": faces,
        "source_indices": valid_sources,
    }


def build_native_mesh_preview_triangle_groups(
    mesh: ParsedMesh,
    source_indices: Sequence[int] | None = None,
    *,
    timeout_seconds: float = 5.0,
    _retry_missing: bool = True,
) -> list[dict[str, object]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    if source_indices is None:
        requested = range(len(mesh.submeshes))
    else:
        requested = (
            index
            for raw_index in source_indices or ()
            if (index := _index(raw_index)) is not None and 0 <= index < len(mesh.submeshes)
        )
    requested_indices = tuple(requested)
    submeshes: list[dict[str, object]] = []
    passthrough: list[dict[str, object]] = []
    for submesh_index in requested_indices:
        submesh = mesh.submeshes[submesh_index]
        if not (getattr(submesh, "vertices", ()) or ()) or not (getattr(submesh, "faces", ()) or ()):
            passthrough.append(
                {
                    "preview_backend": "cdmw_mesh_core",
                    "source_submesh_index": submesh_index,
                    "source_vertex_indices": [],
                    "source_face_indices": [],
                    "positions": [],
                    "normals": [],
                    "uvs": [],
                    "indices": [],
                }
            )
            continue
        session_id = _ensure_native_mesh_session_submesh(
            binary,
            mesh,
            submesh_index,
            timeout_seconds=timeout_seconds,
        )
        if not session_id:
            return None
        submeshes.append(
            {
                "index": submesh_index,
                "source_submesh_index": submesh_index,
                "session_id": session_id,
                "preview_triangle_output_path": _native_preview_delta_output_path("_triangles.bin"),
            }
        )
    if not submeshes:
        return passthrough
    report = _run_native_mesh_core_job(
        binary,
        "preview-triangle-groups-json",
        {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "preview_triangle_groups",
            "submeshes": submeshes,
        },
        timeout_seconds=timeout_seconds,
    )
    if report is None:
        _invalidate_native_mesh_session_submeshes(mesh, requested_indices)
        if _retry_missing:
            return build_native_mesh_preview_triangle_groups(
                mesh,
                source_indices=requested_indices,
                timeout_seconds=timeout_seconds,
                _retry_missing=False,
            )
        return None
    raw_groups = report.get("groups")
    if not isinstance(raw_groups, list):
        _invalidate_native_mesh_session_submeshes(mesh, requested_indices)
        if _retry_missing:
            return build_native_mesh_preview_triangle_groups(
                mesh,
                source_indices=requested_indices,
                timeout_seconds=timeout_seconds,
                _retry_missing=False,
            )
        return None
    groups = list(passthrough)
    expected = {int(item["source_submesh_index"]) for item in submeshes}
    seen: set[int] = set()
    for raw_group in raw_groups:
        if not isinstance(raw_group, Mapping):
            continue
        submesh_index = _index(raw_group.get("source_submesh_index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        group = _native_preview_triangle_group(raw_group, submesh_index)
        if group is None:
            return None
        groups.append(group)
        seen.add(submesh_index)
    missing = expected - seen
    if missing:
        _invalidate_native_mesh_session_submeshes(mesh, missing)
        if _retry_missing:
            return build_native_mesh_preview_triangle_groups(
                mesh,
                source_indices=requested_indices,
                timeout_seconds=timeout_seconds,
                _retry_missing=False,
            )
        return None
    return groups


def build_native_mesh_preview_vertex_update_groups(
    mesh: ParsedMesh,
    changed_vertices_by_submesh: Mapping[int, object],
    *,
    timeout_seconds: float = 5.0,
) -> list[dict[str, object]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    submeshes: list[dict[str, object]] = []
    for raw_submesh_index, raw_indices in (changed_vertices_by_submesh or {}).items():
        submesh_index = _index(raw_submesh_index)
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        vertex_count = len(getattr(submesh, "vertices", ()) or ())
        changed_descriptor = _changed_vertices_binary_descriptor(raw_indices, vertex_count)
        changed_range = _changed_vertex_range(raw_indices, vertex_count)
        changed_all_vertices = (
            changed_range is not None
            and changed_range[0] == 0
            and changed_range[1] == vertex_count
        )
        if changed_all_vertices:
            changed_vertices: tuple[int, ...] = ()
        elif changed_range is not None:
            changed_vertices = ()
        elif changed_descriptor is not None:
            changed_vertices = ()
        session_id = _ensure_native_mesh_session_submesh(
            binary,
            mesh,
            submesh_index,
            timeout_seconds=timeout_seconds,
        )
        if not session_id:
            return None
        item: dict[str, object] = {
            "index": submesh_index,
            "source_submesh_index": submesh_index,
            "session_id": session_id,
            "preview_vertex_output_path": _native_preview_delta_output_path("_preview_vertices.bin"),
        }
        if changed_all_vertices:
            item["changed_all_vertices"] = True
        elif changed_range is not None:
            item["changed_vertex_start"] = int(changed_range[0])
            item["changed_vertex_count"] = int(changed_range[1])
        elif changed_descriptor is not None:
            item["changed_vertices_binary"] = changed_descriptor
        else:
            indices_path = Path(_native_preview_delta_output_path("_preview_vertex_indices.bin"))
            written_descriptor = _write_int_binary_payload(
                indices_path,
                _iter_valid_changed_vertex_indices(raw_indices, vertex_count),
            )
            if _index(written_descriptor.get("count")) is None or int(written_descriptor["count"]) <= 0:
                try:
                    indices_path.unlink(missing_ok=True)
                except OSError:
                    pass
                continue
            item["changed_vertices_binary"] = written_descriptor
        submeshes.append(item)
    if not submeshes:
        return []
    report = _run_native_mesh_core_job(
        binary,
        "preview-vertex-update-groups-json",
        {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "preview_vertex_update_groups",
            "submeshes": submeshes,
        },
        timeout_seconds=timeout_seconds,
    )
    if report is None:
        return None
    raw_groups = report.get("groups")
    if not isinstance(raw_groups, list):
        return None
    groups: list[dict[str, object]] = []
    for raw_group in raw_groups:
        if not isinstance(raw_group, Mapping):
            continue
        submesh_index = _index(raw_group.get("source_submesh_index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        group = _native_preview_vertex_update_group(raw_group, submesh_index)
        if group is None:
            return None
        groups.append(group)
    return groups


def _changed_vertex_range(value: object, vertex_count: int) -> tuple[int, int] | None:
    if isinstance(value, Mapping):
        for start_key, count_key in (
            ("changed_vertex_start", "changed_vertex_count"),
            ("source_vertex_start", "source_vertex_count"),
        ):
            start = _index(value.get(start_key))
            count = _index(value.get(count_key))
            if start is None and count is None:
                continue
            if start is None or count is None or start < 0 or count <= 0 or start + count > vertex_count:
                return None
            return start, count
        return None
    return _contiguous_vertex_range(value, vertex_count)


def _changed_vertices_binary_descriptor(value: object, vertex_count: int) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if "changed_vertices_binary" in value:
        descriptor = value.get("changed_vertices_binary")
    elif "source_vertex_indices_binary" in value:
        descriptor = value.get("source_vertex_indices_binary")
    elif "path" in value:
        descriptor = value
    else:
        return None
    if not isinstance(descriptor, Mapping):
        return None
    count = _index(descriptor.get("count"))
    if count is None or count <= 0 or count > vertex_count:
        return None
    return _native_binary_descriptor(descriptor, expected_count=count, components=1, kind="i32")


def _iter_valid_changed_vertex_indices(value: object, vertex_count: int) -> Iterable[int]:
    if value is None:
        return
    try:
        iterator = iter(value)  # type: ignore[arg-type]
    except TypeError:
        return
    for raw_index in iterator:
        index = _index(raw_index)
        if index is not None and 0 <= index < vertex_count:
            yield index


def _contiguous_vertex_range(value: object, vertex_count: int) -> tuple[int, int] | None:
    if not isinstance(value, range) or value.step != 1:
        return None
    if value.start < 0 or value.stop > vertex_count or value.stop <= value.start:
        return None
    return int(value.start), int(value.stop - value.start)


def _iter_valid_face_triples(faces: object) -> Iterable[tuple[int, int, int]]:
    for face in faces or ():
        if not isinstance(face, (tuple, list)) or len(face) != 3:
            continue
        try:
            yield (int(face[0]), int(face[1]), int(face[2]))
        except (TypeError, ValueError, OverflowError):
            continue


def _count_valid_face_triples(faces: object) -> int:
    return sum(1 for _face in _iter_valid_face_triples(faces))


def summarize_native_mesh_submesh_metadata(
    submeshes: Sequence[SubMesh],
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_metadata_"))
    try:
        native_items: list[dict[str, object]] = []
        for submesh_index, submesh in enumerate(submeshes or ()):
            vertices = getattr(submesh, "vertices", ()) or ()
            faces = getattr(submesh, "faces", ()) or ()
            uvs = getattr(submesh, "uvs", ()) or ()
            item: dict[str, object] = {
                "index": submesh_index,
                "vertex_count": len(vertices),
                "face_count": len(faces),
                "uv_count": len(uvs),
                "has_uvs": bool(uvs),
            }
            if vertices:
                prefix = sidecar_root / f"metadata_{submesh_index}"
                item["vertices_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_vertices.bin"),
                    vertices,
                )
            native_items.append(item)
        report = _run_native_mesh_core_job(
            binary,
            "mesh-metadata-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "mesh_metadata",
                "submeshes": native_items,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "mesh_metadata":
        return None
    return dict(report)


def summarize_native_mesh_selection_bounds(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]],
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_selection_bounds_"))
    try:
        native_items: list[dict[str, object]] = []
        for raw_submesh_index, raw_vertices in (selected_vertices_by_submesh or {}).items():
            submesh_index = _index(raw_submesh_index)
            if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(submesh.vertices)
            selected = _selected_vertex_values(raw_vertices, vertex_count)
            if not selected:
                continue
            prefix = sidecar_root / f"selection_bounds_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
            }
            _put_selected_vertices_payload(item, prefix, selected, max_count=vertex_count)
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                item["vertices_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_vertices.bin"),
                    submesh.vertices,
                )
            native_items.append(item)
        if not native_items:
            return {
                "operation": "selection_bounds",
                "selected_vertex_count": 0,
                "has_bounds": False,
                "bbox_min": [0.0, 0.0, 0.0],
                "bbox_max": [0.0, 0.0, 0.0],
                "submeshes": [],
            }
        report = _run_native_mesh_core_job(
            binary,
            "selection-bounds-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "selection_bounds",
                "submeshes": native_items,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "selection_bounds":
        return None
    return dict(report)


def merge_native_mesh_submeshes(
    submeshes: Sequence[SubMesh],
    *,
    timeout_seconds: float = 5.0,
) -> SubMesh | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_merge_submeshes_"))
    try:
        native_items: list[dict[str, object]] = []
        for submesh_index, submesh in enumerate(submeshes or ()):
            vertices = getattr(submesh, "vertices", ()) or ()
            faces = getattr(submesh, "faces", ()) or ()
            prefix = sidecar_root / f"merge_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "vertices_binary": _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices),
                "faces_binary": _write_face_binary_payload(
                    prefix.with_name(prefix.name + "_faces.bin"),
                    _iter_valid_face_triples(faces),
                ),
            }
            normals = getattr(submesh, "normals", ()) or ()
            if len(normals) == len(vertices):
                item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), normals)
            uvs = getattr(submesh, "uvs", ()) or ()
            if len(uvs) == len(vertices):
                item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), uvs)
            native_items.append(item)
        report = _run_native_mesh_core_job(
            binary,
            "merge-submeshes-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "merge_submeshes",
                "vertices_output_path": _native_preview_delta_output_path("_merge_vertices.bin"),
                "faces_output_path": _native_preview_delta_output_path("_merge_faces.bin"),
                "normals_output_path": _native_preview_delta_output_path("_merge_normals.bin"),
                "uvs_output_path": _native_preview_delta_output_path("_merge_uvs.bin"),
                "submeshes": native_items,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "merge_submeshes":
        return None
    vertex_count = _index(report.get("vertex_count"))
    face_count = _index(report.get("face_count"))
    if vertex_count is None or face_count is None or vertex_count < 0 or face_count < 0:
        return None
    vertices = _read_vec3_binary_report_payload(report.get("vertices_binary"), expected_count=vertex_count)
    faces = _read_face_binary_report_payload(report.get("faces_binary"), expected_count=face_count, vertex_count=vertex_count)
    normals = _read_vec3_binary_report_payload(report.get("normals_binary"), expected_count=vertex_count) or []
    uvs = _read_vec2_binary_report_payload(report.get("uvs_binary"), expected_count=vertex_count) or []
    if vertices is None or faces is None:
        return None
    return SubMesh(
        vertices=list(vertices),
        faces=list(faces),
        normals=list(normals),
        uvs=list(uvs),
        vertex_count=vertex_count,
        face_count=face_count,
    )


def decimate_native_mesh_preview_submeshes(
    submeshes: list[SubMesh],
    max_faces: int,
    *,
    timeout_seconds: float = 5.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    try:
        face_limit = int(max_faces)
    except (TypeError, ValueError):
        return None
    if face_limit <= 0:
        return set()
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_preview_decimate_"))
    try:
        native_items: list[dict[str, object]] = []
        for submesh_index, submesh in enumerate(submeshes or ()):
            vertices = getattr(submesh, "vertices", ()) or ()
            faces = getattr(submesh, "faces", ()) or ()
            try:
                face_count = len(faces)
            except TypeError:
                face_count = _count_valid_face_triples(faces)
            if not vertices or face_count <= face_limit:
                continue
            prefix = sidecar_root / f"decimate_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "max_faces": face_limit,
                "vertices_binary": _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices),
                "faces_binary": _write_face_binary_payload(
                    prefix.with_name(prefix.name + "_faces.bin"),
                    _iter_valid_face_triples(faces),
                ),
                "vertices_output_path": _native_preview_delta_output_path("_preview_decimate_vertices.bin"),
                "faces_output_path": _native_preview_delta_output_path("_preview_decimate_faces.bin"),
                "uvs_output_path": _native_preview_delta_output_path("_preview_decimate_uvs.bin"),
                "normals_output_path": _native_preview_delta_output_path("_preview_decimate_normals.bin"),
                "bone_counts_output_path": _native_preview_delta_output_path("_preview_decimate_bone_counts.bin"),
                "bone_indices_output_path": _native_preview_delta_output_path("_preview_decimate_bone_indices.bin"),
                "bone_weights_output_path": _native_preview_delta_output_path("_preview_decimate_bone_weights.bin"),
                "source_vertex_map_output_path": _native_preview_delta_output_path("_preview_decimate_source_map.bin"),
            }
            uvs = getattr(submesh, "uvs", ()) or ()
            if len(uvs) == len(vertices):
                item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), uvs)
            normals = getattr(submesh, "normals", ()) or ()
            if len(normals) == len(vertices):
                item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), normals)
            bone_payloads = _write_bone_binary_payloads(
                prefix,
                getattr(submesh, "bone_indices", None),
                getattr(submesh, "bone_weights", None),
            )
            if bone_payloads is not None:
                item.update(bone_payloads)
            source_vertex_map = getattr(submesh, "source_vertex_map", ()) or ()
            if len(source_vertex_map) == len(vertices):
                _put_source_vertex_map_payload(item, prefix, source_vertex_map)
            native_items.append(item)
        if not native_items:
            return set()
        report = _run_native_mesh_core_job(
            binary,
            "preview-decimate-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "preview_decimate",
                "submeshes": native_items,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "preview_decimate":
        return None
    raw_items = report.get("submeshes")
    if not isinstance(raw_items, list):
        return None
    from .static_mesh_clone import _clone_submesh_fast

    changed: set[int] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        submesh_index = _index(raw_item.get("index"))
        vertex_count = _index(raw_item.get("vertex_count"))
        face_count = _index(raw_item.get("face_count"))
        if (
            submesh_index is None
            or vertex_count is None
            or face_count is None
            or not 0 <= submesh_index < len(submeshes)
            or vertex_count <= 0
            or face_count <= 0
        ):
            continue
        vertices = _read_vec3_binary_report_payload(raw_item.get("vertices_binary"), expected_count=vertex_count)
        faces = _read_face_binary_report_payload(raw_item.get("faces_binary"), expected_count=face_count, vertex_count=vertex_count)
        if vertices is None or faces is None:
            return None
        source = submeshes[submesh_index]
        preview = _clone_submesh_fast(source)
        preview.vertices = list(vertices)
        preview.faces = list(faces)
        preview.uvs = _read_vec2_binary_report_payload(raw_item.get("uvs_binary"), expected_count=vertex_count) or []
        preview.normals = _read_vec3_binary_report_payload(raw_item.get("normals_binary"), expected_count=vertex_count) or []
        bones = _read_bone_binary_report_payloads(
            raw_item.get("bone_counts_binary"),
            raw_item.get("bone_indices_binary"),
            raw_item.get("bone_weights_binary"),
            expected_count=vertex_count,
        )
        if bones is None:
            preview.bone_indices = []
            preview.bone_weights = []
        else:
            preview.bone_indices = list(bones[0])
            preview.bone_weights = list(bones[1])
        preview.source_vertex_map = (
            _read_i32_binary_report_payload(raw_item.get("source_vertex_map_binary"), expected_count=vertex_count) or []
        )
        preview.vertex_count = len(preview.vertices)
        preview.face_count = len(preview.faces)
        preview.source_vertex_offsets = []
        preview.source_index_offset = -1
        preview.source_index_count = len(preview.faces) * 3
        submeshes[submesh_index] = preview
        changed.add(submesh_index)
    return changed


def apply_native_mesh_affine_transform_submeshes(
    submeshes: Sequence[SubMesh],
    *,
    position_matrices_by_index: Mapping[int, Sequence[float]] | None = None,
    normal_matrices_by_index: Mapping[int, Sequence[float]] | None = None,
    source_part_adjustments_by_index: Mapping[int, object] | None = None,
    reverse_face_winding_by_index: Mapping[int, bool] | None = None,
    mirror_x_around_bounds_center_by_index: Mapping[int, bool] | None = None,
    timeout_seconds: float = 5.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    position_matrices = position_matrices_by_index or {}
    normal_matrices = normal_matrices_by_index or {}
    source_part_adjustments = source_part_adjustments_by_index or {}
    reverse_faces = reverse_face_winding_by_index or {}
    mirror_x = mirror_x_around_bounds_center_by_index or {}
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_affine_transform_"))
    try:
        native_items: list[dict[str, object]] = []
        requested_indices = {
            raw_index
            for mapping in (position_matrices, source_part_adjustments, mirror_x)
            for raw_index in mapping.keys()
        }
        for raw_submesh_index in sorted(requested_indices, key=lambda value: str(value)):
            submesh_index = _index(raw_submesh_index)
            if submesh_index is None or not 0 <= submesh_index < len(submeshes):
                continue
            matrix: tuple[float, ...] | None = None
            if raw_submesh_index in position_matrices or submesh_index in position_matrices:
                raw_matrix = position_matrices.get(raw_submesh_index, position_matrices.get(submesh_index))
                matrix = _finite_float_sequence(raw_matrix, expected_count=12)
            raw_adjustment = source_part_adjustments.get(raw_submesh_index, source_part_adjustments.get(submesh_index))
            adjustment_payload = _source_part_adjustment_payload(raw_adjustment)
            if matrix is None and adjustment_payload is None:
                return None
            submesh = submeshes[submesh_index]
            vertices = getattr(submesh, "vertices", ()) or ()
            if not vertices:
                continue
            prefix = sidecar_root / f"affine_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "vertices_binary": _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices),
                "vertices_output_path": _native_preview_delta_output_path("_affine_vertices.bin"),
            }
            if matrix is not None:
                item["position_matrix"] = list(matrix)
            if adjustment_payload is not None:
                pivot_vertices = _source_part_adjustment_pivot_vertices(raw_adjustment)
                if pivot_vertices:
                    adjustment_payload["pivot_vertices_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_pivot_vertices.bin"),
                        pivot_vertices,
                    )
                item["source_part_adjustment"] = adjustment_payload
            mirror_after_transform = bool(mirror_x.get(raw_submesh_index, mirror_x.get(submesh_index, False)))
            if mirror_after_transform:
                item["mirror_x_around_bounds_center"] = True
            normals = getattr(submesh, "normals", ()) or ()
            normal_matrix = _finite_float_sequence(normal_matrices.get(submesh_index), expected_count=9)
            if len(normals) == len(vertices) and (normal_matrix is not None or adjustment_payload is not None):
                if normal_matrix is not None:
                    item["normal_matrix"] = list(normal_matrix)
                item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), normals)
                item["normals_output_path"] = _native_preview_delta_output_path("_affine_normals.bin")
            if mirror_after_transform or bool(reverse_faces.get(submesh_index, reverse_faces.get(str(submesh_index), False))):
                faces = getattr(submesh, "faces", ()) or ()
                if faces:
                    item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                    item["faces_output_path"] = _native_preview_delta_output_path("_affine_faces.bin")
                    if bool(reverse_faces.get(submesh_index, reverse_faces.get(str(submesh_index), False))):
                        item["reverse_face_winding"] = True
            native_items.append(item)
        if not native_items:
            return set()
        report = _run_native_mesh_core_job(
            binary,
            "affine-transform-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "affine_transform",
                "submeshes": native_items,
            },
            timeout_seconds=timeout_seconds,
        )
    except (IndexError, OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "affine_transform":
        return None
    raw_items = report.get("submeshes")
    if not isinstance(raw_items, list):
        return None
    changed: set[int] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        submesh_index = _index(raw_item.get("index"))
        vertex_count = _index(raw_item.get("vertex_count"))
        if submesh_index is None or vertex_count is None or not 0 <= submesh_index < len(submeshes):
            continue
        submesh = submeshes[submesh_index]
        vertices = _read_vec3_binary_report_payload(raw_item.get("vertices_binary"), expected_count=vertex_count)
        if vertices is None:
            return None
        submesh.vertices = list(vertices)
        submesh.vertex_count = len(vertices)
        normals = _read_vec3_binary_report_payload(raw_item.get("normals_binary"), expected_count=vertex_count)
        if normals is not None:
            submesh.normals = list(normals)
        face_count = _index(raw_item.get("face_count"))
        if face_count is not None:
            faces = _read_face_binary_report_payload(
                raw_item.get("faces_binary"),
                expected_count=face_count,
                vertex_count=vertex_count,
            )
            if faces is None:
                return None
            submesh.faces = list(faces)
            submesh.face_count = len(faces)
        else:
            submesh.face_count = len(getattr(submesh, "faces", ()) or ())
        changed.add(submesh_index)
    return changed


def clone_native_mesh_affine_transformed_submesh(
    submesh: object,
    *,
    source_part_adjustment: object | None = None,
    position_matrix: Sequence[float] | None = None,
    normal_matrix: Sequence[float] | None = None,
    reverse_face_winding: bool = False,
    mirror_x_around_bounds_center: bool = False,
    timeout_seconds: float = 5.0,
) -> SubMesh | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    adjustment_payload = _source_part_adjustment_payload(source_part_adjustment)
    parsed_position_matrix = _finite_float_sequence(position_matrix, expected_count=12)
    parsed_normal_matrix = _finite_float_sequence(normal_matrix, expected_count=9)
    if adjustment_payload is None and parsed_position_matrix is None:
        return None
    vertices = getattr(submesh, "vertices", ()) or ()
    if not vertices:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_affine_clone_"))
    try:
        prefix = sidecar_root / "affine_clone_0"
        item: dict[str, object] = {
            "index": 0,
            "vertices_binary": _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices),
            "vertices_output_path": _native_preview_delta_output_path("_affine_clone_vertices.bin"),
        }
        if parsed_position_matrix is not None:
            item["position_matrix"] = list(parsed_position_matrix)
        if adjustment_payload is not None:
            item["source_part_adjustment"] = adjustment_payload
            pivot_vertices = _source_part_adjustment_pivot_vertices(source_part_adjustment)
            if pivot_vertices:
                adjustment_payload["pivot_vertices_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_pivot_vertices.bin"),
                    pivot_vertices,
                )
        normals = getattr(submesh, "normals", ()) or ()
        if len(normals) == len(vertices) and (adjustment_payload is not None or parsed_normal_matrix is not None):
            item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), normals)
            item["normals_output_path"] = _native_preview_delta_output_path("_affine_clone_normals.bin")
            if parsed_normal_matrix is not None:
                item["normal_matrix"] = list(parsed_normal_matrix)
        faces = getattr(submesh, "faces", ()) or ()
        if faces:
            item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
            item["faces_output_path"] = _native_preview_delta_output_path("_affine_clone_faces.bin")
            if reverse_face_winding:
                item["reverse_face_winding"] = True
        if mirror_x_around_bounds_center:
            item["mirror_x_around_bounds_center"] = True
        report = _run_native_mesh_core_job(
            binary,
            "affine-transform-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "affine_transform",
                "submeshes": [item],
            },
            timeout_seconds=timeout_seconds,
        )
    except (IndexError, OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "affine_transform":
        return None
    raw_items = report.get("submeshes")
    if not isinstance(raw_items, list) or not raw_items or not isinstance(raw_items[0], Mapping):
        return None
    raw_item = raw_items[0]
    vertex_count = _index(raw_item.get("vertex_count"))
    if vertex_count is None:
        return None
    transformed_vertices = _read_vec3_binary_report_payload(raw_item.get("vertices_binary"), expected_count=vertex_count)
    if transformed_vertices is None:
        return None
    transformed_normals = _read_vec3_binary_report_payload(raw_item.get("normals_binary"), expected_count=vertex_count)
    normals = list(transformed_normals) if transformed_normals is not None else list(getattr(submesh, "normals", ()) or ())
    face_count = _index(raw_item.get("face_count"))
    transformed_faces = None
    if face_count is not None:
        transformed_faces = _read_face_binary_report_payload(
            raw_item.get("faces_binary"),
            expected_count=face_count,
            vertex_count=vertex_count,
        )
        if transformed_faces is None:
            return None
    source_faces = getattr(submesh, "faces", ()) or ()
    cloned = SubMesh(
        name=str(getattr(submesh, "name", "") or ""),
        material=str(getattr(submesh, "material", "") or ""),
        texture=str(getattr(submesh, "texture", "") or ""),
        vertices=list(transformed_vertices),
        uvs=list(getattr(submesh, "uvs", ()) or ()),
        normals=normals,
        tangents=list(getattr(submesh, "tangents", ()) or ()),
        faces=[tuple(face) for face in (transformed_faces if transformed_faces is not None else source_faces)],
        bone_indices=list(getattr(submesh, "bone_indices", ()) or ()),
        bone_weights=list(getattr(submesh, "bone_weights", ()) or ()),
        source_vertex_map=list(getattr(submesh, "source_vertex_map", ()) or ()),
        vertex_count=len(transformed_vertices),
        face_count=len(transformed_faces) if transformed_faces is not None else len(source_faces),
        source_vertex_offsets=list(getattr(submesh, "source_vertex_offsets", ()) or ()),
        source_index_offset=int(getattr(submesh, "source_index_offset", -1) or -1),
        source_index_count=int(getattr(submesh, "source_index_count", 0) or 0),
        source_vertex_stride=int(getattr(submesh, "source_vertex_stride", 0) or 0),
        source_descriptor_offset=int(getattr(submesh, "source_descriptor_offset", -1) or -1),
        source_bbox_min=_vec3(getattr(submesh, "source_bbox_min", (0.0, 0.0, 0.0)), fallback=0.0),
        source_bbox_extent=_vec3(getattr(submesh, "source_bbox_extent", (0.0, 0.0, 0.0)), fallback=0.0),
        source_lod_count=int(getattr(submesh, "source_lod_count", 0) or 0),
    )
    for attr_name in _EXTRA_SUBMESH_ATTRS:
        if hasattr(submesh, attr_name):
            setattr(cloned, attr_name, _snapshot_metadata_value(getattr(submesh, attr_name)))
    return cloned


def _native_selection_preview_group(value: Mapping[str, object], source_submesh_index: int) -> dict[str, object] | None:
    source_vertex_indices = _int_list(value.get("source_vertex_indices"))
    raw_source_vertices_binary = value.get("source_vertex_indices_binary")
    source_vertex_count = len(source_vertex_indices)
    source_vertex_start = _index(value.get("source_vertex_start"))
    source_vertex_range_count = _index(value.get("source_vertex_count"))
    has_source_vertex_range = (
        source_vertex_start is not None
        and source_vertex_start >= 0
        and source_vertex_range_count is not None
        and source_vertex_range_count > 0
    )
    if source_vertex_count == 0 and isinstance(raw_source_vertices_binary, Mapping):
        source_vertex_count = _index(raw_source_vertices_binary.get("count")) or 0
    if source_vertex_count == 0 and has_source_vertex_range:
        source_vertex_count = int(source_vertex_range_count or 0)
    if source_vertex_count <= 0:
        return None
    group: dict[str, object] = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": source_submesh_index,
    }
    if source_vertex_indices:
        group["source_vertex_indices"] = source_vertex_indices
    source_vertices_binary = _native_binary_descriptor(
        raw_source_vertices_binary,
        expected_count=source_vertex_count,
        components=1,
        kind="i32",
    )
    if source_vertices_binary is not None:
        group["source_vertex_indices_binary"] = source_vertices_binary
    elif has_source_vertex_range:
        group["source_vertex_start"] = int(source_vertex_start or 0)
        group["source_vertex_count"] = int(source_vertex_range_count or 0)

    source_edges = _edge_list(value.get("source_edges"))
    raw_source_edges_binary = value.get("source_edges_binary")
    source_edge_count = len(source_edges)
    if source_edge_count == 0 and isinstance(raw_source_edges_binary, Mapping):
        source_edge_count = _index(raw_source_edges_binary.get("count")) or 0
    if source_edges:
        group["source_edges"] = [[left, right] for left, right in source_edges]
    source_edges_binary = _native_binary_descriptor(
        raw_source_edges_binary,
        expected_count=source_edge_count,
        components=2,
        kind="i32",
    )
    if source_edges_binary is not None:
        group["source_edges_binary"] = source_edges_binary

    source_face_indices = _int_list(value.get("source_face_indices"))
    raw_source_faces_binary = value.get("source_face_indices_binary")
    source_face_count = len(source_face_indices)
    source_face_start = _index(value.get("source_face_start"))
    source_face_range_count = _index(value.get("source_face_count"))
    has_source_face_range = (
        source_face_start is not None
        and source_face_start >= 0
        and source_face_range_count is not None
        and source_face_range_count > 0
    )
    if source_face_count == 0 and isinstance(raw_source_faces_binary, Mapping):
        source_face_count = _index(raw_source_faces_binary.get("count")) or 0
    if source_face_count == 0 and has_source_face_range:
        source_face_count = int(source_face_range_count or 0)
    if source_face_indices:
        group["source_face_indices"] = source_face_indices
    source_faces_binary = _native_binary_descriptor(
        raw_source_faces_binary,
        expected_count=source_face_count,
        components=1,
        kind="i32",
    )
    if source_faces_binary is not None:
        group["source_face_indices_binary"] = source_faces_binary
    elif has_source_face_range:
        group["source_face_start"] = int(source_face_start or 0)
        group["source_face_count"] = int(source_face_range_count or 0)
    return group


def _write_vec3_binary_payload(path: Path, values: object, *, fallback: float = 0.0) -> dict[str, object]:
    data = array("d")
    append = data.append
    count = 0
    fallback_value = _finite_float(fallback, 0.0)
    for value in values or ():
        if isinstance(value, (tuple, list)) and len(value) >= 3:
            x = _finite_float(value[0], fallback_value)
            y = _finite_float(value[1], fallback_value)
            z = _finite_float(value[2], fallback_value)
        else:
            x = y = z = fallback_value
        append(x)
        append(y)
        append(z)
        count += 1
    with path.open("wb") as handle:
        data.tofile(handle)
    return {"path": str(path), "count": count, "components": 3, "type": "f64"}


def _read_vec3_binary_payload(path: Path, *, expected_count: int, finite_checked: bool = False) -> list[Vec3] | None:
    if expected_count < 0:
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) != expected_count * 3 * 8:
        return None
    result = list(struct.iter_unpack("=ddd", raw))
    if finite_checked:
        return result
    for x, y, z in result:
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            return None
    return result


def _read_vec3_binary_report_payload(value: object, *, expected_count: int) -> list[Vec3] | None:
    if not isinstance(value, Mapping):
        return None
    raw_path = str(value.get("path") or "").strip()
    if not raw_path:
        return None
    count = _index(value.get("count"))
    if count is not None and count != expected_count:
        return None
    return _read_vec3_binary_payload(
        Path(raw_path),
        expected_count=expected_count,
        finite_checked=bool(value.get("finite_checked")),
    )


def _read_vec2_binary_report_payload(value: object, *, expected_count: int) -> list[Vec2] | None:
    descriptor = _native_binary_descriptor(value, expected_count=expected_count, components=2, kind="f64")
    if descriptor is None:
        return None
    try:
        raw = Path(str(descriptor["path"])).read_bytes()
    except OSError:
        return None
    if len(raw) != expected_count * 2 * 8:
        return None
    result = list(struct.iter_unpack("=dd", raw))
    if bool(value.get("finite_checked")):
        return result
    for u, v in result:
        if not (math.isfinite(u) and math.isfinite(v)):
            return None
    return result


def _native_binary_descriptor(value: object, *, expected_count: int, components: int, kind: str) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    raw_path = str(value.get("path") or "").strip()
    if not raw_path:
        return None
    count = _index(value.get("count"))
    if count is not None and count != expected_count:
        return None
    raw_components = _index(value.get("components"))
    if raw_components is not None and raw_components != components:
        return None
    raw_kind = str(value.get("type") or kind).strip().lower()
    if raw_kind and raw_kind != kind:
        return None
    descriptor: dict[str, object] = {
        "path": raw_path,
        "count": expected_count,
        "components": components,
        "type": kind,
    }
    if bool(value.get("delete_after")):
        descriptor["delete_after"] = True
    return descriptor


def _native_existing_binary_descriptor(
    value: object,
    *,
    components: int,
    kinds: set[str],
    expected_count: int | None = None,
) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    raw_path = str(value.get("path") or "").strip()
    if not raw_path:
        return None
    count = _index(value.get("count"))
    if count is None or count <= 0:
        return None
    if expected_count is not None and count != expected_count:
        return None
    raw_components = _index(value.get("components"))
    if raw_components is not None and raw_components != components:
        return None
    kind = str(value.get("type") or "").strip().lower()
    if kind not in kinds:
        return None
    try:
        if not Path(raw_path).is_file():
            return None
    except OSError:
        return None
    descriptor: dict[str, object] = {
        "path": raw_path,
        "count": count,
        "components": components,
        "type": kind,
    }
    if bool(value.get("delete_after")):
        descriptor["delete_after"] = True
    return descriptor


def _read_face_binary_report_payload(value: object, *, expected_count: int, vertex_count: int) -> list[Face] | None:
    descriptor = _native_binary_descriptor(value, expected_count=expected_count, components=3, kind="i32")
    if descriptor is None:
        return None
    try:
        raw = Path(str(descriptor["path"])).read_bytes()
    except OSError:
        return None
    if len(raw) != expected_count * 3 * 4:
        return None
    faces = list(struct.iter_unpack("=iii", raw))
    for x, y, z in faces:
        if x < 0 or y < 0 or z < 0 or x >= vertex_count or y >= vertex_count or z >= vertex_count:
            return None
    return faces


def _read_int_binary_report_payload(value: object, *, max_count: int) -> list[int] | None:
    if not isinstance(value, Mapping):
        return None
    count = _index(value.get("count"))
    if count is None or count < 0:
        return None
    descriptor = _native_binary_descriptor(value, expected_count=count, components=1, kind="i32")
    if descriptor is None:
        return None
    data = array("i")
    if data.itemsize != 4:
        raise RuntimeError("native int sidecar requires 32-bit array('i')")
    try:
        raw = Path(str(descriptor["path"])).read_bytes()
    except OSError:
        return None
    if len(raw) != count * data.itemsize:
        return None
    data.frombytes(raw)
    values = data.tolist()
    if any(index < 0 or index >= max_count for index in values):
        return None
    return values


def _read_i32_binary_report_payload(value: object, *, expected_count: int) -> list[int] | None:
    descriptor = _native_binary_descriptor(value, expected_count=expected_count, components=1, kind="i32")
    if descriptor is None:
        return None
    data = array("i")
    if data.itemsize != 4:
        raise RuntimeError("native i32 sidecar requires 32-bit array('i')")
    try:
        raw = Path(str(descriptor["path"])).read_bytes()
    except OSError:
        return None
    if len(raw) != expected_count * data.itemsize:
        return None
    data.frombytes(raw)
    return data.tolist()


def _read_i32_components_binary_report_payload(value: object, *, expected_count: int, components: int) -> list[tuple[int, ...]] | None:
    descriptor = _native_binary_descriptor(value, expected_count=expected_count, components=components, kind="i32")
    if descriptor is None:
        return None
    data = array("i")
    if data.itemsize != 4:
        raise RuntimeError("native i32 sidecar requires 32-bit array('i')")
    try:
        raw = Path(str(descriptor["path"])).read_bytes()
    except OSError:
        return None
    if len(raw) != expected_count * components * data.itemsize:
        return None
    data.frombytes(raw)
    values = [int(value) for value in data]
    return [tuple(values[index : index + components]) for index in range(0, len(values), components)]


def _read_f64_binary_report_payload(value: object, *, expected_count: int) -> list[float] | None:
    descriptor = _native_binary_descriptor(value, expected_count=expected_count, components=1, kind="f64")
    if descriptor is None:
        return None
    data = array("d")
    if data.itemsize != 8:
        raise RuntimeError("native f64 sidecar requires 64-bit array('d')")
    try:
        raw = Path(str(descriptor["path"])).read_bytes()
    except OSError:
        return None
    if len(raw) != expected_count * data.itemsize:
        return None
    data.frombytes(raw)
    values = data.tolist()
    if any(not math.isfinite(value) for value in values):
        return None
    return values


def _read_bone_binary_report_payloads(
    counts_value: object,
    indices_value: object,
    weights_value: object,
    *,
    expected_count: int,
) -> tuple[list[tuple[int, ...]], list[tuple[float, ...]]] | None:
    counts = _read_i32_binary_report_payload(counts_value, expected_count=expected_count)
    if counts is None or any(count < 0 for count in counts):
        return None
    flat_count = sum(counts)
    flat_indices = _read_i32_binary_report_payload(indices_value, expected_count=flat_count)
    flat_weights = _read_f64_binary_report_payload(weights_value, expected_count=flat_count)
    if flat_indices is None or flat_weights is None or any(index < 0 for index in flat_indices):
        return None
    bone_indices: list[tuple[int, ...]] = []
    bone_weights: list[tuple[float, ...]] = []
    offset = 0
    for count in counts:
        next_offset = offset + count
        bone_indices.append(tuple(flat_indices[offset:next_offset]))
        bone_weights.append(tuple(flat_weights[offset:next_offset]))
        offset = next_offset
    return bone_indices, bone_weights


def _native_history_vertex_delta(
    item: Mapping[str, object],
    submesh_index: int,
    changed_vertices: Sequence[int],
) -> dict[str, object] | None:
    native_sparse_snapshot_id = str(item.get("native_sparse_snapshot_id") or "").strip()
    if not changed_vertices:
        return None
    vertex_payload = _native_history_vertex_payload(changed_vertices)
    if not vertex_payload:
        return None
    before_positions_binary = item.get("before_positions_binary")
    if before_positions_binary is None:
        if native_sparse_snapshot_id:
            return {
                "source_submesh_index": int(submesh_index),
                **vertex_payload,
                "native_sparse_snapshot_id": native_sparse_snapshot_id,
            }
        return None
    descriptor = _native_binary_descriptor(
        before_positions_binary,
        expected_count=len(changed_vertices),
        components=3,
        kind="f64",
    )
    if descriptor is None:
        return None
    result: dict[str, object] = {
        "source_submesh_index": int(submesh_index),
        **vertex_payload,
        "before_positions_binary": descriptor,
    }
    if native_sparse_snapshot_id:
        result["native_sparse_snapshot_id"] = native_sparse_snapshot_id
    return result


def _native_history_vertex_payload(changed_vertices: Sequence[int]) -> dict[str, object]:
    if isinstance(changed_vertices, range):
        compact_range = _contiguous_i32_range(changed_vertices)
        if compact_range is not None:
            return {"vertex_index_start": compact_range[0], "vertex_index_count": compact_range[1]}
    return {"vertex_indices": tuple(int(index) for index in changed_vertices)}


def _native_history_delta_vertex_payload(delta: Mapping[str, object]) -> dict[str, object]:
    start = _index(delta.get("vertex_index_start"))
    count = _index(delta.get("vertex_index_count"))
    if start is not None and count is not None and start >= 0 and count > 0:
        return {"vertex_index_start": start, "vertex_index_count": count}
    return {"vertex_indices": tuple(delta.get("vertex_indices") or ())}


def _vertex_indices_from_history_descriptor(value: Mapping[str, object], vertex_count: int) -> Sequence[int] | None:
    ranged = _i32_range_report_values(
        value,
        start_key="vertex_index_start",
        count_key="vertex_index_count",
        max_count=max(0, int(vertex_count)),
    )
    if ranged is not None:
        return ranged
    raw_indices = value.get("vertex_indices")
    if not isinstance(raw_indices, (tuple, list, range)):
        return None
    indices: list[int] = []
    seen_indices: set[int] = set()
    for raw_vertex_index in raw_indices:
        vertex_index = _index(raw_vertex_index)
        if vertex_index is None or vertex_index < 0 or vertex_index >= vertex_count or vertex_index in seen_indices:
            return None
        indices.append(vertex_index)
        seen_indices.add(vertex_index)
    return tuple(indices) if indices else None


def native_mesh_history_delta_positions(raw_delta: object) -> tuple[Vec3, ...] | None:
    if not isinstance(raw_delta, Mapping):
        return None
    raw_indices = _vertex_indices_from_history_descriptor(raw_delta, 1 << 30)
    if raw_indices is None:
        return None
    raw_positions = raw_delta.get("before_positions")
    if isinstance(raw_positions, (tuple, list)):
        positions = tuple(_vec3(position) for position in raw_positions)
        return positions if len(positions) == len(raw_indices) else None
    raw_positions_binary = raw_delta.get("before_positions_binary")
    positions = _read_vec3_binary_report_payload(raw_positions_binary, expected_count=len(raw_indices))
    return tuple(positions) if positions is not None else None


def _changed_vertices_from_report_item(item: Mapping[str, object], vertex_count: int) -> Sequence[int] | None:
    if "changed_vertex_start" in item or "changed_vertex_count" in item:
        try:
            raw_start = item.get("changed_vertex_start", -1)
            raw_count = item.get("changed_vertex_count", 0)
            start = int(raw_start if raw_start is not None else -1)
            count = int(raw_count if raw_count is not None else 0)
        except (TypeError, ValueError, OverflowError):
            return None
        if count == 0 and start >= 0:
            return range(start, start)
        if start < 0 or count < 0 or start + count > max(0, int(vertex_count)):
            return None
        return range(start, start + count)
    raw_changed_binary = item.get("changed_vertices_binary")
    raw_changed = item.get("changed_vertices")
    if isinstance(raw_changed_binary, Mapping):
        raw_values = _read_int_binary_report_payload(raw_changed_binary, max_count=vertex_count)
        if raw_values is None:
            return None
    elif isinstance(raw_changed, list):
        raw_values = raw_changed
    else:
        return None
    changed: list[int] = []
    seen: set[int] = set()
    for raw_index in raw_values:
        index = _index(raw_index)
        if index is not None and 0 <= index < vertex_count and index not in seen:
            changed.append(index)
            seen.add(index)
    return changed


def _changed_vertices_for_report(indices: Sequence[int] | None) -> Sequence[int] | set[int]:
    if not indices:
        return set()
    return indices if isinstance(indices, range) else set(indices)


def _bounded_changed_vertices(indices: Sequence[int] | set[int], vertex_count: int) -> Sequence[int] | set[int]:
    if isinstance(indices, range) and indices.step == 1:
        start = max(0, int(indices.start))
        stop = min(int(indices.stop), max(0, int(vertex_count)))
        if start >= stop:
            return range(0, 0)
        if start == indices.start and stop == indices.stop:
            return indices
        return range(start, stop)
    return {int(index) for index in indices if 0 <= int(index) < vertex_count}


def _write_vec2_binary_payload(path: Path, values: object, *, fallback: float = 0.0) -> dict[str, object]:
    data = array("d")
    append = data.append
    count = 0
    fallback_value = _finite_float(fallback, 0.0)
    for value in values or ():
        if isinstance(value, (tuple, list)) and len(value) >= 2:
            x = _finite_float(value[0], fallback_value)
            y = _finite_float(value[1], fallback_value)
        else:
            x = y = fallback_value
        append(x)
        append(y)
        count += 1
    with path.open("wb") as handle:
        data.tofile(handle)
    return {"path": str(path), "count": count, "components": 2, "type": "f64"}


def _write_f64_binary_payload(path: Path, values: object, *, fallback: float = 1.0) -> dict[str, object]:
    data = array("d")
    count = 0
    for value in values or ():
        data.append(_finite_float(value, fallback))
        count += 1
    with path.open("wb") as handle:
        data.tofile(handle)
    return {"path": str(path), "count": count, "components": 1, "type": "f64"}


def _write_bone_binary_payloads(prefix: Path, bone_indices: object, bone_weights: object) -> dict[str, dict[str, object]] | None:
    if not isinstance(bone_indices, (list, tuple)) or not isinstance(bone_weights, (list, tuple)) or len(bone_indices) != len(bone_weights):
        return None
    counts: list[int] = []
    flat_indices: list[int] = []
    flat_weights: list[float] = []
    try:
        for raw_indices, raw_weights in zip(bone_indices, bone_weights):
            indices = tuple(int(value) for value in tuple(raw_indices or ()))
            weights = tuple(float(value) for value in tuple(raw_weights or ()))
            if len(indices) != len(weights) or any(index < 0 for index in indices) or any(not math.isfinite(weight) for weight in weights):
                return None
            counts.append(len(indices))
            flat_indices.extend(indices)
            flat_weights.extend(weights)
    except (TypeError, ValueError, OverflowError):
        return None
    return {
        "bone_counts_binary": _write_int_binary_payload(prefix.with_name(prefix.name + "_bone_counts.bin"), counts),
        "bone_indices_binary": _write_int_binary_payload(prefix.with_name(prefix.name + "_bone_indices.bin"), flat_indices),
        "bone_weights_binary": _write_f64_binary_payload(prefix.with_name(prefix.name + "_bone_weights.bin"), flat_weights, fallback=0.0),
    }


def _write_face_binary_payload(path: Path, faces: object) -> dict[str, object]:
    data = array("i")
    if data.itemsize != 4:
        raise RuntimeError("native face sidecar requires 32-bit array('i')")
    append = data.append
    count = 0
    for face in faces or ():
        append(int(face[0]))
        append(int(face[1]))
        append(int(face[2]))
        count += 1
    with path.open("wb") as handle:
        data.tofile(handle)
    return {"path": str(path), "count": count, "components": 3, "type": "i32"}


def _write_face_binary_payload_with_source_indices(
    path: Path,
    faces: object,
    vertex_count: int,
) -> tuple[dict[str, object], list[int]]:
    data = array("i")
    if data.itemsize != 4:
        raise RuntimeError("native face sidecar requires 32-bit array('i')")
    append = data.append
    source_face_indices: list[int] = []
    raw_faces = faces if isinstance(faces, list) else ()
    for source_face_index, face in enumerate(raw_faces):
        if not isinstance(face, (tuple, list)) or len(face) < 3:
            continue
        raw_a = face[0]
        raw_b = face[1]
        raw_c = face[2]
        if (
            isinstance(raw_a, int)
            and not isinstance(raw_a, bool)
            and isinstance(raw_b, int)
            and not isinstance(raw_b, bool)
            and isinstance(raw_c, int)
            and not isinstance(raw_c, bool)
        ):
            a = raw_a
            b = raw_b
            c = raw_c
        else:
            parsed = _valid_face_triplet(face, vertex_count)
            if parsed is None:
                continue
            a, b, c = parsed
        if a < 0 or b < 0 or c < 0 or a >= vertex_count or b >= vertex_count or c >= vertex_count:
            continue
        append(a)
        append(b)
        append(c)
        source_face_indices.append(source_face_index)
    with path.open("wb") as handle:
        data.tofile(handle)
    return {"path": str(path), "count": len(source_face_indices), "components": 3, "type": "i32"}, source_face_indices


def _write_int_binary_payload(path: Path, values: Iterable[int]) -> dict[str, object]:
    data = array("i", (int(value) for value in values))
    if data.itemsize != 4:
        raise RuntimeError("native int sidecar requires 32-bit array('i')")
    with path.open("wb") as handle:
        data.tofile(handle)
    return {"path": str(path), "count": len(data), "components": 1, "type": "i32"}


def _contiguous_i32_range(values: Sequence[int], max_count: int | None = None) -> tuple[int, int] | None:
    if isinstance(values, range):
        if values.step != 1 or not values:
            return None
        start = int(values.start)
        count = len(values)
        if start < 0:
            return None
        if max_count is not None and start + count > max(0, int(max_count)):
            return None
        return start, count
    try:
        iterator = iter(values)
        first = int(next(iterator))
    except (StopIteration, TypeError, ValueError, OverflowError):
        return None
    start = first
    if start < 0:
        return None
    count = 1
    for offset, raw_value in enumerate(iterator, start=1):
        try:
            value = int(raw_value)
        except (TypeError, ValueError, OverflowError):
            return None
        if value != start + offset:
            return None
        count += 1
    if max_count is not None and start + count > max(0, int(max_count)):
        return None
    return start, count


def _is_identity_i32_sequence(values: Sequence[int]) -> bool:
    for offset, raw_value in enumerate(values):
        try:
            value = int(raw_value)
        except (TypeError, ValueError, OverflowError):
            return False
        if value != offset:
            return False
    return True


def _contiguous_i32_stride_range(values: Sequence[int]) -> tuple[int, int, int] | None:
    try:
        iterator = iter(values)
        start = int(next(iterator))
    except (StopIteration, TypeError, ValueError, OverflowError):
        return None
    if start < 0:
        return None
    try:
        second = int(next(iterator))
    except StopIteration:
        return start, 1, 1
    except (TypeError, ValueError, OverflowError):
        return None
    stride = second - start
    if stride <= 0:
        return None
    count = 2
    for offset, raw_value in enumerate(iterator, start=2):
        try:
            value = int(raw_value)
        except (TypeError, ValueError, OverflowError):
            return None
        if value < 0 or value != start + offset * stride:
            return None
        count += 1
    return start, count, stride


def _put_i32_range_or_binary_payload(
    item: dict[str, object],
    *,
    values: Sequence[int],
    start_key: str,
    count_key: str,
    binary_key: str,
    binary_path: Path,
    max_count: int | None = None,
) -> None:
    compact_range = _contiguous_i32_range(values, max_count=max_count)
    if compact_range is not None:
        start, count = compact_range
        item[start_key] = start
        item[count_key] = count
        return
    item[binary_key] = _write_int_binary_payload(binary_path, values)


def _put_source_vertex_map_payload(item: dict[str, object], prefix: Path, values: Sequence[int]) -> None:
    _put_i32_range_or_binary_payload(
        item,
        values=values,
        start_key="source_vertex_map_start",
        count_key="source_vertex_map_count",
        binary_key="source_vertex_map_binary",
        binary_path=prefix.with_name(prefix.name + "_source_vertex_map.bin"),
    )


def _put_source_vertex_indices_payload(item: dict[str, object], prefix: Path, values: Sequence[int]) -> None:
    _put_i32_range_or_binary_payload(
        item,
        values=values,
        start_key="source_vertex_start",
        count_key="source_vertex_count",
        binary_key="source_vertex_indices_binary",
        binary_path=prefix.with_name(prefix.name + "_source_vertices.bin"),
    )


def _put_source_vertex_offsets_payload(item: dict[str, object], prefix: Path | None, values: Sequence[int]) -> None:
    compact_range = _contiguous_i32_stride_range(values)
    if compact_range is not None:
        start, count, stride = compact_range
        item["source_vertex_offsets_start"] = start
        item["source_vertex_offsets_count"] = count
        item["source_vertex_offsets_stride"] = stride
        return
    if prefix is None:
        item["source_vertex_offsets"] = [int(value) for value in values]
        return
    item["source_vertex_offsets_binary"] = _write_int_binary_payload(
        prefix.with_name(prefix.name + "_source_vertex_offsets.bin"),
        values,
    )


def _put_source_face_indices_payload(item: dict[str, object], prefix: Path, values: Sequence[int]) -> None:
    _put_i32_range_or_binary_payload(
        item,
        values=values,
        start_key="source_face_start",
        count_key="source_face_count",
        binary_key="source_face_indices_binary",
        binary_path=prefix.with_name(prefix.name + "_source_faces.bin"),
    )


def _put_source_face_indices_json_payload(item: dict[str, object], values: Sequence[int]) -> None:
    compact_range = _contiguous_i32_range(values)
    if compact_range is not None:
        item["source_face_start"], item["source_face_count"] = compact_range
        return
    item["source_face_indices"] = [int(index) for index in values]


def _put_vertex_indices_payload(
    item: dict[str, object],
    prefix: Path,
    values: Sequence[int],
    *,
    max_count: int | None = None,
) -> None:
    _put_i32_range_or_binary_payload(
        item,
        values=values,
        start_key="vertex_index_start",
        count_key="vertex_index_count",
        binary_key="vertex_indices_binary",
        binary_path=prefix.with_name(prefix.name + "_indices.bin"),
        max_count=max_count,
    )


def _put_selected_vertices_payload(
    item: dict[str, object],
    prefix: Path,
    values: Sequence[int],
    *,
    max_count: int | None = None,
) -> None:
    _put_i32_range_or_binary_payload(
        item,
        values=values,
        start_key="selected_vertex_start",
        count_key="selected_vertex_count",
        binary_key="selected_vertices_binary",
        binary_path=prefix.with_name(prefix.name + "_selected.bin"),
        max_count=max_count,
    )


def _selected_edge_values(raw_edges: object, vertex_count: int) -> tuple[tuple[int, int], ...]:
    vertex_limit = max(0, int(vertex_count))
    if vertex_limit <= 0:
        return ()
    selected: set[tuple[int, int]] = set()
    try:
        values = iter(raw_edges or ())  # type: ignore[arg-type]
    except TypeError:
        return ()
    for raw_edge in values:
        if not isinstance(raw_edge, (tuple, list)) or len(raw_edge) < 2:
            continue
        left = _index(raw_edge[0])
        right = _index(raw_edge[1])
        if left is None or right is None or left == right:
            continue
        if 0 <= left < vertex_limit and 0 <= right < vertex_limit:
            selected.add((min(left, right), max(left, right)))
    return tuple(sorted(selected))


def _selected_face_values(raw_faces: object, face_count: int) -> Sequence[int]:
    face_limit = max(0, int(face_count))
    if face_limit <= 0:
        return ()
    if isinstance(raw_faces, range) and raw_faces.step == 1:
        start = max(0, int(raw_faces.start))
        stop = min(face_limit, int(raw_faces.stop))
        return range(start, stop) if start < stop else ()
    selected: set[int] = set()
    try:
        values = iter(raw_faces or ())  # type: ignore[arg-type]
    except TypeError:
        return ()
    for raw_value in values:
        index = _index(raw_value)
        if index is not None and 0 <= index < face_limit:
            selected.add(index)
    return tuple(sorted(selected))


def _put_selected_edit_domain_payload(
    item: dict[str, object],
    prefix: Path,
    *,
    selected_vertices: object,
    selected_edges: object,
    selected_faces: object,
    selected_all_vertices: bool,
    vertex_count: int,
    face_count: int,
) -> bool:
    wrote_selection = False
    kept_vertices = _selected_vertex_values(selected_vertices, vertex_count)
    if kept_vertices:
        _put_selected_vertices_payload(item, prefix, kept_vertices, max_count=vertex_count)
        wrote_selection = True
    kept_edges = _selected_edge_values(selected_edges, vertex_count)
    if kept_edges:
        item["selected_edges_binary"] = _write_edge_binary_payload(prefix.with_name(prefix.name + "_selected_edges.bin"), kept_edges)
        wrote_selection = True
    kept_faces = _selected_face_values(selected_faces, face_count)
    if kept_faces:
        _put_i32_range_or_binary_payload(
            item,
            values=kept_faces,
            start_key="selected_face_start",
            count_key="selected_face_count",
            binary_key="selected_faces_binary",
            binary_path=prefix.with_name(prefix.name + "_selected_faces.bin"),
            max_count=face_count,
        )
        wrote_selection = True
    if selected_all_vertices:
        item["selected_all_vertices"] = True
        wrote_selection = True
    return wrote_selection


def _selected_vertex_values(raw_values: object, vertex_count: int) -> Sequence[int]:
    vertex_limit = max(0, int(vertex_count))
    if vertex_limit <= 0:
        return ()
    if isinstance(raw_values, range) and raw_values.step == 1:
        start = max(0, int(raw_values.start))
        stop = min(vertex_limit, int(raw_values.stop))
        return range(start, stop) if start < stop else ()
    selected: set[int] = set()
    try:
        values = iter(raw_values or ())  # type: ignore[arg-type]
    except TypeError:
        return ()
    for raw_value in values:
        index = _index(raw_value)
        if index is not None and 0 <= index < vertex_limit:
            selected.add(index)
    return tuple(sorted(selected))


def _i32_range_report_values(
    item: Mapping[object, object],
    *,
    start_key: str,
    count_key: str,
    max_count: int,
) -> Sequence[int] | None:
    try:
        raw_start = item.get(start_key, -1)
        raw_count = item.get(count_key, 0)
        start = int(raw_start if raw_start is not None else -1)
        count = int(raw_count if raw_count is not None else 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if start < 0 or count <= 0 or start + count > max(0, int(max_count)):
        return None
    return range(start, start + count)


def _i32_stride_range_report_values(item: Mapping[object, object], *, max_count: int) -> Sequence[int] | None:
    try:
        start = int(item.get("source_vertex_offsets_start", -1) or -1)
        count = int(item.get("source_vertex_offsets_count", 0) or 0)
        stride = int(item.get("source_vertex_offsets_stride", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if start < 0 or count <= 0 or count > max(0, int(max_count)) or stride <= 0:
        return None
    return range(start, start + count * stride, stride)


def _source_vertex_map_report_values(item: Mapping[object, object], vertex_count: int) -> list[int] | None:
    raw_binary = item.get("source_vertex_map_binary")
    if isinstance(raw_binary, Mapping):
        values = _read_i32_binary_report_payload(raw_binary, expected_count=vertex_count)
        return values if values is not None and len(values) == vertex_count else None
    values_from_range = _i32_range_report_values(
        item,
        start_key="source_vertex_map_start",
        count_key="source_vertex_map_count",
        max_count=1 << 30,
    )
    if values_from_range is not None:
        values = list(values_from_range)
        return values if len(values) == vertex_count else None
    raw_values = item.get("source_vertex_map")
    if isinstance(raw_values, list):
        values = _int_list(raw_values)
        return values if len(values) == vertex_count else None
    return []


def _source_vertex_offsets_report_values(item: Mapping[object, object], vertex_count: int) -> list[int] | None:
    raw_binary = item.get("source_vertex_offsets_binary")
    if isinstance(raw_binary, Mapping):
        values = _read_i32_binary_report_payload(raw_binary, expected_count=vertex_count)
        return values if values is not None and len(values) == vertex_count else None
    values_from_range = _i32_stride_range_report_values(item, max_count=vertex_count)
    if values_from_range is not None:
        values = list(values_from_range)
        return values if len(values) == vertex_count else None
    raw_values = item.get("source_vertex_offsets")
    if isinstance(raw_values, list):
        values = _int_list(raw_values)
        return values if len(values) == vertex_count else None
    return []


def _write_edge_binary_payload(path: Path, values: Sequence[tuple[int, int]]) -> dict[str, object]:
    data = array("i")
    if data.itemsize != 4:
        raise RuntimeError("native edge sidecar requires 32-bit array('i')")
    for left, right in values:
        data.extend((int(left), int(right)))
    with path.open("wb") as handle:
        data.tofile(handle)
    return {"path": str(path), "count": len(values), "components": 2, "type": "i32"}


def _native_mesh_editor_index_values(values: object) -> tuple[int, ...]:
    if isinstance(values, Mapping):
        raw_values = values.get("indices", values.get("vertices", values.get("faces", ())))
    else:
        raw_values = values
    try:
        iterator = iter(raw_values or ())  # type: ignore[arg-type]
    except TypeError:
        return ()
    selected: set[int] = set()
    for raw in iterator:
        index = _index(raw)
        if index is not None and index >= 0:
            selected.add(index)
    return tuple(sorted(selected))


def _native_mesh_editor_index_payload(values: object, path: Path) -> dict[str, object]:
    if isinstance(values, Mapping) and (
        "indices_binary" in values
        or "selected_vertices_binary" in values
        or "selected_faces_binary" in values
        or "start" in values
        or "count" in values
    ):
        return dict(values)
    indices = _native_mesh_editor_index_values(values)
    compact = _contiguous_i32_range(indices)
    if compact is not None:
        start, count = compact
        return {"start": start, "count": count}
    if len(indices) > 2048:
        return {"indices_binary": _write_int_binary_payload(path, indices)}
    return {"indices": list(indices)}


def _native_mesh_editor_edge_values(values: object) -> tuple[tuple[int, int], ...]:
    if isinstance(values, Mapping):
        raw_values = values.get("edges", values.get("indices", ()))
    else:
        raw_values = values
    try:
        iterator = iter(raw_values or ())  # type: ignore[arg-type]
    except TypeError:
        return ()
    edges: set[tuple[int, int]] = set()
    for raw_edge in iterator:
        if not isinstance(raw_edge, (tuple, list)) or len(raw_edge) < 2:
            continue
        left = _index(raw_edge[0])
        right = _index(raw_edge[1])
        if left is None or right is None or left < 0 or right < 0 or left == right:
            continue
        edges.add((min(left, right), max(left, right)))
    return tuple(sorted(edges))


def _native_mesh_editor_edge_payload(values: object, path: Path) -> dict[str, object]:
    if isinstance(values, Mapping) and (
        "edges_binary" in values
        or "selected_edges_binary" in values
        or "indices_binary" in values
    ):
        return dict(values)
    edges = _native_mesh_editor_edge_values(values)
    if len(edges) > 2048:
        return {"edges_binary": _write_edge_binary_payload(path, edges)}
    return {"edges": [list(edge) for edge in edges]}


def _native_mesh_editor_index_groups(values: object, name: str, root: Path) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    if isinstance(values, Mapping):
        iterable = values.items()
    else:
        try:
            iterable = tuple(enumerate(values or ()))  # type: ignore[arg-type]
        except TypeError:
            iterable = ()
    for raw_index, raw_values in iterable:
        if isinstance(raw_values, Mapping):
            submesh_index = _index(raw_values.get("index", raw_values.get("submesh_index", raw_index)))
        else:
            submesh_index = _index(raw_index)
        if submesh_index is None or submesh_index < 0:
            continue
        payload = _native_mesh_editor_index_payload(raw_values, root / f"{name}_{submesh_index}.bin")
        groups.append({"index": submesh_index, **payload})
    return groups


def _native_mesh_editor_edge_groups(values: object, root: Path) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    if isinstance(values, Mapping):
        iterable = values.items()
    else:
        try:
            iterable = tuple(enumerate(values or ()))  # type: ignore[arg-type]
        except TypeError:
            iterable = ()
    for raw_index, raw_values in iterable:
        if isinstance(raw_values, Mapping):
            submesh_index = _index(raw_values.get("index", raw_values.get("submesh_index", raw_index)))
        else:
            submesh_index = _index(raw_index)
        if submesh_index is None or submesh_index < 0:
            continue
        payload = _native_mesh_editor_edge_payload(raw_values, root / f"edges_{submesh_index}.bin")
        groups.append({"index": submesh_index, **payload})
    return groups


def _native_mesh_editor_selection_payload(selection: Mapping[str, object], root: Path) -> dict[str, object]:
    payload = dict(selection)
    if "vertices_by_submesh" in payload:
        payload["vertices_by_submesh"] = _native_mesh_editor_index_groups(payload["vertices_by_submesh"], "vertices", root)
    if "faces_by_submesh" in payload:
        payload["faces_by_submesh"] = _native_mesh_editor_index_groups(payload["faces_by_submesh"], "faces", root)
    if "edges_by_submesh" in payload:
        payload["edges_by_submesh"] = _native_mesh_editor_edge_groups(payload["edges_by_submesh"], root)
    if "source_indices" in payload:
        payload["source_indices"] = _native_mesh_editor_index_payload(payload["source_indices"], root / "source_indices.bin")
    return payload


def _native_mesh_session_token(mesh: ParsedMesh) -> str:
    token = getattr(mesh, _NATIVE_MESH_SESSION_TOKEN_ATTR, "")
    if isinstance(token, str) and token:
        return token
    token = f"py-mesh-{uuid4().hex}"
    try:
        setattr(mesh, _NATIVE_MESH_SESSION_TOKEN_ATTR, token)
    except Exception:
        return f"py-mesh-{uuid4().hex}"
    return token


def _native_mesh_session_cache_key(mesh: ParsedMesh, submesh_index: int) -> tuple[str, int]:
    return (_native_mesh_session_token(mesh), int(submesh_index))


def _native_mesh_session_id(mesh: ParsedMesh, submesh_index: int) -> str:
    return f"{_native_mesh_session_token(mesh)}-{int(submesh_index)}"


def _cached_native_mesh_session_submesh(mesh: ParsedMesh, submesh_index: int) -> str | None:
    if not 0 <= int(submesh_index) < len(getattr(mesh, "submeshes", ()) or ()):
        return None
    signature = _native_mesh_session_signature(mesh.submeshes[int(submesh_index)])
    cache_key = _native_mesh_session_cache_key(mesh, int(submesh_index))
    with _native_mesh_core_session_cache_lock:
        cached = _native_mesh_core_session_cache.get(cache_key)
    if cached is None or cached[0] != signature:
        return None
    return str(cached[1] or "").strip() or None


def _native_mesh_session_signature(submesh: object) -> tuple[object, ...]:
    vertices = getattr(submesh, "vertices", ()) or ()
    faces = getattr(submesh, "faces", ()) or ()
    normals = getattr(submesh, "normals", ()) or ()
    uvs = getattr(submesh, "uvs", ()) or ()
    tangents = getattr(submesh, "tangents", ()) or ()
    tangent_signs = getattr(submesh, "tangent_signs", ()) or ()
    bone_indices = getattr(submesh, "bone_indices", ()) or ()
    bone_weights = getattr(submesh, "bone_weights", ()) or ()
    source_vertex_map = getattr(submesh, "source_vertex_map", ()) or ()
    source_vertex_offsets = getattr(submesh, "source_vertex_offsets", ()) or ()
    extra_attrs = tuple(
        (attr_name, _snapshot_metadata_value(getattr(submesh, attr_name)))
        for attr_name in _EXTRA_SUBMESH_ATTRS
        if hasattr(submesh, attr_name)
    )
    return (
        str(getattr(submesh, "name", "") or ""),
        str(getattr(submesh, "material", "") or ""),
        str(getattr(submesh, "texture", "") or ""),
        extra_attrs,
        len(vertices),
        len(faces),
        id(vertices),
        id(faces),
        len(normals),
        id(normals),
        len(uvs),
        id(uvs),
        len(tangents),
        id(tangents),
        len(tangent_signs),
        id(tangent_signs),
        len(bone_indices),
        id(bone_indices),
        len(bone_weights),
        id(bone_weights),
        len(source_vertex_map),
        id(source_vertex_map),
        len(source_vertex_offsets),
        id(source_vertex_offsets),
    )


def _mark_native_mesh_session_submeshes_current(mesh: ParsedMesh, submesh_indices: object) -> None:
    with _native_mesh_core_session_cache_lock:
        for index in _iter_valid_submesh_indices(mesh, submesh_indices):
            key = _native_mesh_session_cache_key(mesh, index)
            cached = _native_mesh_core_session_cache.get(key)
            if cached is None:
                continue
            _old_signature, session_id = cached
            _native_mesh_core_session_cache[key] = (_native_mesh_session_signature(mesh.submeshes[index]), session_id)


def _invalidate_native_mesh_session_submeshes(mesh: ParsedMesh, submesh_indices: object) -> None:
    with _native_mesh_core_session_cache_lock:
        for index in _iter_valid_submesh_indices(mesh, submesh_indices):
            _native_mesh_core_session_cache.pop(_native_mesh_session_cache_key(mesh, index), None)


def invalidate_native_mesh_session_submeshes(mesh: ParsedMesh, submesh_indices: object) -> None:
    _invalidate_native_mesh_session_submeshes(mesh, submesh_indices)


def _native_mesh_session_store_item(submesh: SubMesh, submesh_index: int, prefix: Path) -> dict[str, object] | None:
    if not submesh.vertices:
        return None
    vertex_count = len(submesh.vertices)
    faces_binary, source_face_indices = _write_face_binary_payload_with_source_indices(
        prefix.with_name(prefix.name + "_faces.bin"),
        submesh.faces,
        vertex_count,
    )
    item: dict[str, object] = {
        "index": submesh_index,
        "name": str(getattr(submesh, "name", "") or ""),
        "material": str(getattr(submesh, "material", "") or ""),
        "texture": str(getattr(submesh, "texture", "") or ""),
        "vertices_binary": _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices),
        "faces_binary": faces_binary,
    }
    extra_attrs = {
        attr_name: _snapshot_metadata_value(getattr(submesh, attr_name))
        for attr_name in _EXTRA_SUBMESH_ATTRS
        if hasattr(submesh, attr_name)
    }
    if extra_attrs:
        item["extra_attrs"] = extra_attrs
    _put_i32_range_or_binary_payload(
        item,
        values=source_face_indices,
        start_key="source_face_start",
        count_key="source_face_count",
        binary_key="source_face_indices_binary",
        binary_path=prefix.with_name(prefix.name + "_source_faces.bin"),
        max_count=len(submesh.faces),
    )
    if len(submesh.normals) == len(submesh.vertices):
        item["normals_binary"] = _write_vec3_binary_payload(
            prefix.with_name(prefix.name + "_normals.bin"),
            submesh.normals,
            fallback=0.0,
        )
    if len(submesh.uvs) == len(submesh.vertices):
        item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), submesh.uvs)
    if len(getattr(submesh, "tangents", ()) or ()) == len(submesh.vertices):
        item["tangents_binary"] = _write_vec3_binary_payload(
            prefix.with_name(prefix.name + "_tangents.bin"),
            getattr(submesh, "tangents", ()) or (),
            fallback=0.0,
        )
    if len(getattr(submesh, "tangent_signs", ()) or ()) == len(submesh.vertices):
        item["tangent_signs_binary"] = _write_f64_binary_payload(
            prefix.with_name(prefix.name + "_tangent_signs.bin"),
            getattr(submesh, "tangent_signs", ()) or (),
        )
    if (
        len(getattr(submesh, "bone_indices", ()) or ()) == len(submesh.vertices)
        and len(getattr(submesh, "bone_weights", ()) or ()) == len(submesh.vertices)
    ):
        bone_payload = _write_bone_binary_payloads(
            prefix,
            getattr(submesh, "bone_indices", ()) or (),
            getattr(submesh, "bone_weights", ()) or (),
        )
        if bone_payload is not None:
            item.update(bone_payload)
    if len(getattr(submesh, "source_vertex_map", ()) or ()) == len(submesh.vertices):
        _put_source_vertex_map_payload(item, prefix, getattr(submesh, "source_vertex_map", ()) or ())
    if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == len(submesh.vertices):
        _put_source_vertex_offsets_payload(item, prefix, getattr(submesh, "source_vertex_offsets", ()) or ())
    return item


def _ensure_native_mesh_session_submesh(
    binary: Path,
    mesh: ParsedMesh,
    submesh_index: int,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float,
) -> str | None:
    if not _native_mesh_core_service_enabled(stop_event=stop_event):
        return None
    if not _native_mesh_core_service_running(binary):
        _clear_native_mesh_core_session_cache()
    if not 0 <= submesh_index < len(mesh.submeshes):
        return None
    submesh = mesh.submeshes[submesh_index]
    signature = _native_mesh_session_signature(submesh)
    cache_key = _native_mesh_session_cache_key(mesh, submesh_index)
    with _native_mesh_core_session_cache_lock:
        cached = _native_mesh_core_session_cache.get(cache_key)
        if cached is not None and cached[0] == signature:
            return cached[1]
    session_id = _native_mesh_session_id(mesh, submesh_index)
    try:
        with tempfile.TemporaryDirectory(prefix="cdmw_mesh_core_session_") as sidecar_root_raw:
            sidecar_root = Path(sidecar_root_raw)
            prefix = sidecar_root / f"session_{submesh_index}"
            item = _native_mesh_session_store_item(submesh, submesh_index, prefix)
            if item is None:
                return None
            service_kwargs: dict[str, object] = {"timeout_seconds": timeout_seconds}
            if stop_event is not None:
                service_kwargs["stop_event"] = stop_event
            report = _run_native_mesh_core_service_job(
                binary,
                "mesh-session-json",
                {
                    "version": 1,
                    "backend": NATIVE_MESH_CORE_BACKEND_ID,
                    "operation": "store",
                    "session_id": session_id,
                    "submeshes": [item],
                },
                **service_kwargs,
            )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    if report is None:
        return None
    if _native_mesh_core_service_known_for_binary(binary) and not _native_mesh_core_service_running(binary):
        return None
    with _native_mesh_core_session_cache_lock:
        _native_mesh_core_session_cache[cache_key] = (signature, session_id)
    return session_id


def native_mesh_editor_session_command(
    command: str,
    session_id: str,
    payload: Mapping[str, object] | None = None,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None or not _native_mesh_core_service_enabled(stop_event=stop_event):
        return None
    session_text = str(session_id or "").strip()
    command_text = str(command or "").strip().lower()
    if not session_text or not command_text:
        return None
    request: dict[str, object] = dict(payload or {})
    request.update(
        {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "protocol": "mesh-editor-session-json",
            "command": command_text,
            "session_id": session_text,
        }
    )
    return _run_native_mesh_core_service_job(
        binary,
        "mesh-editor-session-json",
        request,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )


def open_native_mesh_editor_session(
    mesh: ParsedMesh,
    session_id: str,
    *,
    submesh_indices: object = None,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None or not _native_mesh_core_service_enabled(stop_event=stop_event):
        return None
    indices = _sorted_unique_valid_submesh_indices(mesh, submesh_indices, all_when_none=True)
    if not indices:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="cdmw_mesh_editor_session_") as sidecar_root_raw:
            sidecar_root = Path(sidecar_root_raw)
            items: list[dict[str, object]] = []
            for submesh_index in indices:
                cached_session_id = _cached_native_mesh_session_submesh(mesh, submesh_index)
                item = {"index": submesh_index, "session_id": cached_session_id} if cached_session_id else None
                if item is None:
                    item = _native_mesh_session_store_item(
                        mesh.submeshes[submesh_index],
                        submesh_index,
                        sidecar_root / f"editor_{submesh_index}",
                    )
                if item is not None:
                    items.append(item)
            if not items:
                return None
            return _run_native_mesh_core_service_job(
                binary,
                "mesh-editor-session-json",
                {
                    "version": 1,
                    "backend": NATIVE_MESH_CORE_BACKEND_ID,
                    "protocol": "mesh-editor-session-json",
                    "command": "open",
                    "session_id": str(session_id or "").strip(),
                    "submeshes": items,
                },
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None


def select_native_mesh_editor_session(
    session_id: str,
    selection: Mapping[str, object],
    *,
    operation: object = "replace",
    iterations: object = 1,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 2.0,
) -> dict[str, object] | None:
    try:
        with tempfile.TemporaryDirectory(prefix="cdmw_mesh_editor_selection_") as sidecar_root_raw:
            sidecar_root = Path(sidecar_root_raw)
            payload: dict[str, object] = {
                "selection": _native_mesh_editor_selection_payload(selection, sidecar_root),
                "selection_operation": str(operation or "replace").strip().lower() or "replace",
                "selection_output_dir": _native_preview_delta_output_dir(),
            }
            selected_iterations = _index(iterations)
            if selected_iterations is not None:
                payload["iterations"] = max(0, selected_iterations)
            return native_mesh_editor_session_command(
                "select",
                session_id,
                payload,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None


def native_mesh_editor_session_selection_from_report(report: Mapping[str, object]) -> dict[str, object] | None:
    raw_items = report.get("submeshes")
    if not isinstance(raw_items, list):
        return None
    max_index = 2_147_483_647
    vertices: dict[int, set[int]] = {}
    edges: dict[int, set[tuple[int, int]]] = {}
    faces: dict[int, set[int]] = {}
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        submesh_index = _index(raw_item.get("index"))
        if submesh_index is None or submesh_index < 0:
            continue
        selected_vertices = _i32_range_report_values(
            raw_item,
            start_key="selected_vertex_start",
            count_key="selected_vertex_count",
            max_count=max_index,
        )
        if selected_vertices is None:
            selected_vertices = _read_int_binary_report_payload(raw_item.get("selected_vertices_binary"), max_count=max_index)
        if selected_vertices is None:
            selected_vertices = [index for index in _int_list(raw_item.get("selected_vertices")) if 0 <= index < max_index]
        if selected_vertices:
            vertices[submesh_index] = set(selected_vertices)

        edge_count = _index((raw_item.get("selected_edges_binary") or {}).get("count")) if isinstance(raw_item.get("selected_edges_binary"), Mapping) else None
        raw_edges = (
            _read_i32_components_binary_report_payload(raw_item.get("selected_edges_binary"), expected_count=edge_count, components=2)
            if edge_count is not None
            else None
        )
        selected_edges = {
            (min(left, right), max(left, right))
            for left, right in (raw_edges if raw_edges is not None else _edge_list(raw_item.get("selected_edges")))
            if 0 <= left < max_index and 0 <= right < max_index and left != right
        }
        if selected_edges:
            edges[submesh_index] = selected_edges

        selected_faces = _i32_range_report_values(
            raw_item,
            start_key="selected_face_start",
            count_key="selected_face_count",
            max_count=max_index,
        )
        if selected_faces is None:
            selected_faces = _read_int_binary_report_payload(raw_item.get("selected_faces_binary"), max_count=max_index)
        if selected_faces is None:
            selected_faces = [index for index in _int_list(raw_item.get("selected_faces")) if 0 <= index < max_index]
        if selected_faces:
            faces[submesh_index] = set(selected_faces)
    return {
        "vertices_by_submesh": vertices,
        "edges_by_submesh": edges,
        "faces_by_submesh": faces,
        "source_indices": tuple(index for index in _int_list(report.get("source_indices")) if index >= 0),
    }


def native_mesh_editor_session_selection_groups_from_report(report: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    raw_groups = report.get("selection_groups")
    if not isinstance(raw_groups, list):
        raw_groups = report.get("groups")
    if not isinstance(raw_groups, list):
        return ()
    groups: list[Mapping[str, object]] = []
    for raw_group in raw_groups:
        if not isinstance(raw_group, Mapping):
            continue
        submesh_index = _index(raw_group.get("source_submesh_index"))
        if submesh_index is None or submesh_index < 0:
            continue
        group = _native_selection_preview_group(raw_group, submesh_index)
        if group is not None:
            groups.append(group)
    return tuple(groups)


def apply_native_mesh_editor_session(
    session_id: str,
    edit: Mapping[str, object],
    *,
    selection: Mapping[str, object] | None = None,
    capture_deltas: bool = True,
    include_preview_deltas: bool = True,
    stroke_phase: str | None = None,
    stroke_id: str | None = None,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, object] | None:
    edit_payload = dict(edit)
    if stroke_phase is not None:
        edit_payload["stroke_phase"] = str(stroke_phase or "").strip().lower()
    if stroke_id is not None:
        edit_payload["stroke_id"] = str(stroke_id or "").strip()
    payload: dict[str, object] = {"edit": edit_payload}
    if capture_deltas:
        payload["delta_output_dir"] = _native_preview_delta_output_dir()
        payload["include_edit_report"] = True
        payload["include_preview_deltas"] = bool(include_preview_deltas)
    try:
        if selection is None:
            return native_mesh_editor_session_command(
                "apply",
                session_id,
                payload,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
        with tempfile.TemporaryDirectory(prefix="cdmw_mesh_editor_selection_") as sidecar_root_raw:
            payload["selection"] = _native_mesh_editor_selection_payload(selection, Path(sidecar_root_raw))
            return native_mesh_editor_session_command(
                "apply",
                session_id,
                payload,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None


def native_mesh_editor_source_normals_payload(
    source_mesh: ParsedMesh,
    submesh_indices: Iterable[int],
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    source_submeshes = tuple(getattr(source_mesh, "submeshes", ()) or ())
    for raw_index in submesh_indices:
        submesh_index = _index(raw_index)
        if submesh_index is None or not 0 <= submesh_index < len(source_submeshes):
            continue
        source = source_submeshes[submesh_index]
        normals = tuple(getattr(source, "normals", ()) or ())
        vertices = tuple(getattr(source, "vertices", ()) or ())
        if not vertices or len(normals) != len(vertices):
            continue
        result[str(submesh_index)] = _write_vec3_binary_payload(
            Path(_native_preview_delta_output_path(f"_copy_normals_source_{submesh_index}.bin")),
            normals,
            fallback=0.0,
        )
    return result


def _apply_native_material_report_attrs(submesh: SubMesh, item: Mapping[str, object]) -> None:
    if "name" in item:
        submesh.name = str(item.get("name") or "")
    if "material" in item:
        submesh.material = str(item.get("material") or "")
    if "texture" in item:
        submesh.texture = str(item.get("texture") or "")
    raw_extra_attrs = item.get("extra_attrs")
    if not isinstance(raw_extra_attrs, Mapping):
        return
    for attr_name in _NATIVE_MATERIAL_REPORT_ATTRS:
        if attr_name in raw_extra_attrs:
            setattr(submesh, attr_name, _snapshot_metadata_value(raw_extra_attrs[attr_name]))
        elif hasattr(submesh, attr_name):
            delattr(submesh, attr_name)


def _apply_native_material_edit_report(
    mesh: ParsedMesh,
    report: Mapping[str, object],
    edit_report: Mapping[str, object],
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    raw_items = edit_report.get("submeshes")
    if not isinstance(raw_items, list):
        return None
    items = [item for item in raw_items if isinstance(item, Mapping)]
    geometry_items = [
        item
        for item in items
        if not bool(item.get("append_submesh"))
        and bool(item.get("topology_changed"))
    ]
    append_items = [item for item in items if bool(item.get("append_submesh"))]
    affected: set[int] = set()
    changed: dict[int, Sequence[int] | set[int]] = {}
    if geometry_items:
        geometry_report = dict(edit_report)
        geometry_report["submeshes"] = geometry_items
        applied = _apply_mesh_edit_report(mesh, geometry_report, skip_topology_normals=True)
        if applied is None:
            return None
        _geometry_affected, geometry_changed = applied
        changed.update(geometry_changed)
    if append_items:
        append_report = dict(edit_report)
        append_report["submeshes"] = append_items
        appended = _append_native_duplicate_report_submeshes(
            mesh,
            append_report,
            recompute_normals=False,
            copy_extra_attrs=True,
            reset_source_descriptors=True,
        )
        if appended is None:
            return None
        affected.update(appended)
    for item in items:
        submesh_index = _index(item.get("index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        has_material_metadata = "material" in item or "texture" in item or isinstance(item.get("extra_attrs"), Mapping)
        if not has_material_metadata:
            continue
        _apply_native_material_report_attrs(mesh.submeshes[submesh_index], item)
        affected.add(submesh_index)
    raw_affected = report.get("affected_submesh_indices")
    if not affected and isinstance(raw_affected, list):
        affected = {
            index
            for index in (_index(value) for value in raw_affected)
            if index is not None and 0 <= index < len(mesh.submeshes)
        } or affected
    _reconcile_native_editor_submesh_count(mesh, report)
    _refresh_mesh_totals(mesh)
    return affected, changed


def native_mesh_editor_session_preview_triangle_groups(
    report: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(report, Mapping):
        return ()
    edit_report = report.get("edit_report")
    if not isinstance(edit_report, Mapping):
        return ()
    raw_items = edit_report.get("submeshes")
    if not isinstance(raw_items, list):
        return ()
    groups: list[Mapping[str, object]] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        submesh_index = _index(item.get("index"))
        if submesh_index is None:
            continue
        group = _native_preview_triangle_group(item.get("preview_triangle_group"), submesh_index)
        if group is not None:
            groups.append(_native_preview_triangle_group_with_report_material(group, item, submesh_index))
    return tuple(groups)


def native_mesh_editor_session_preview_vertex_update_groups(
    report: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(report, Mapping):
        return ()
    edit_report = report.get("edit_report")
    if not isinstance(edit_report, Mapping):
        return ()
    raw_items = edit_report.get("submeshes")
    if not isinstance(raw_items, list):
        return ()
    groups: list[Mapping[str, object]] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        submesh_index = _index(item.get("index"))
        if submesh_index is None:
            continue
        group = _native_preview_vertex_update_group(item.get("preview_vertex_update_group"), submesh_index)
        if group is not None:
            groups.append(group)
    return tuple(groups)


def _native_preview_triangle_group_with_report_material(
    group: Mapping[str, object],
    item: Mapping[str, object],
    submesh_index: int,
) -> dict[str, object]:
    result = dict(group)
    if "material" in item or "name" in item:
        result.setdefault("material_name", str(item.get("material") or item.get("name") or f"part_{submesh_index}"))
    if "texture" in item:
        result.setdefault("texture_name", str(item.get("texture") or ""))
    source_index = _index(item.get("source_index"))
    if source_index is not None and bool(item.get("append_submesh")):
        result.setdefault("material_source_submesh_index", source_index)
    raw_extra_attrs = item.get("extra_attrs")
    if isinstance(raw_extra_attrs, Mapping):
        material_source = _index(raw_extra_attrs.get("cdmw_mesh_edit_material_source_submesh_index"))
        if material_source is not None:
            result["material_source_submesh_index"] = material_source
        for attr_name in ("preview_alpha_mode", "preview_texture_flip_vertical", "preview_double_sided"):
            if attr_name in raw_extra_attrs:
                result.setdefault(attr_name, raw_extra_attrs[attr_name])
        overrides = raw_extra_attrs.get("preview_native_material_overrides")
        if isinstance(overrides, Mapping):
            for key in _NATIVE_PREVIEW_MATERIAL_OVERRIDE_KEYS:
                if key in overrides:
                    result.setdefault(key, overrides[key])
    return result


def _reconcile_native_editor_submesh_count(mesh: ParsedMesh, report: Mapping[str, object]) -> None:
    count = _index(report.get("submesh_count"))
    if count is None or count < 0:
        return
    if count < len(mesh.submeshes):
        del mesh.submeshes[count:]


def summarize_native_mesh_editor_session(
    session_id: str,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 2.0,
) -> dict[str, object] | None:
    return native_mesh_editor_session_command(
        "summary",
        session_id,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )


def undo_native_mesh_editor_session(
    session_id: str,
    *,
    capture_deltas: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, object] | None:
    payload: dict[str, object] = {}
    if capture_deltas:
        payload["delta_output_dir"] = _native_preview_delta_output_dir()
        payload["include_edit_report"] = True
    return native_mesh_editor_session_command(
        "undo",
        session_id,
        payload,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )


def redo_native_mesh_editor_session(
    session_id: str,
    *,
    capture_deltas: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, object] | None:
    payload: dict[str, object] = {}
    if capture_deltas:
        payload["delta_output_dir"] = _native_preview_delta_output_dir()
        payload["include_edit_report"] = True
    return native_mesh_editor_session_command(
        "redo",
        session_id,
        payload,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )


def export_native_mesh_editor_session_snapshot(
    session_id: str,
    submeshes: Sequence[Mapping[str, object]] | None = None,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, object] | None:
    payload: dict[str, object] = {}
    if submeshes is not None:
        payload["submeshes"] = [dict(item) for item in submeshes]
    return native_mesh_editor_session_command(
        "export_snapshot",
        session_id,
        payload,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )


def export_native_mesh_editor_session_to_mesh(
    mesh: ParsedMesh,
    session_id: str,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 10.0,
) -> bool:
    if not isinstance(mesh, ParsedMesh):
        return False
    summary = export_native_mesh_editor_session_snapshot(
        session_id,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )
    raw_summary_items = summary.get("submeshes") if isinstance(summary, Mapping) else None
    summary_by_index: dict[int, Mapping[str, object]] = {}
    if isinstance(raw_summary_items, list):
        for raw_item in raw_summary_items:
            if not isinstance(raw_item, Mapping):
                continue
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is not None and submesh_index >= 0:
                summary_by_index[submesh_index] = raw_item
    requested = tuple(sorted(summary_by_index)) or tuple(range(len(getattr(mesh, "submeshes", ()) or ())))
    if not requested:
        return True
    job_submeshes: list[dict[str, object]] = []
    metadata_by_index: dict[int, dict[str, object]] = {}
    for submesh_index in requested:
        if 0 <= submesh_index < len(mesh.submeshes):
            metadata = _submesh_snapshot_metadata(mesh.submeshes[submesh_index])
        else:
            metadata = _submesh_snapshot_metadata(SubMesh())
        summary_item = summary_by_index.get(submesh_index, {})
        for key in ("name", "material", "texture"):
            if key in summary_item:
                metadata[key] = str(summary_item.get(key) or "")
        if isinstance(summary_item.get("extra_attrs"), Mapping):
            metadata["extra_attrs"] = dict(summary_item["extra_attrs"])
        else:
            metadata.pop("extra_attrs", None)
        metadata_by_index[submesh_index] = metadata
        job_submeshes.append(
            {
                "index": submesh_index,
                "vertices_output_path": _native_preview_delta_output_path("_editor_snapshot_vertices.bin"),
                "faces_output_path": _native_preview_delta_output_path("_editor_snapshot_faces.bin"),
                "source_face_indices_output_path": _native_preview_delta_output_path("_editor_snapshot_source_faces.bin"),
                "normals_output_path": _native_preview_delta_output_path("_editor_snapshot_normals.bin"),
                "uvs_output_path": _native_preview_delta_output_path("_editor_snapshot_uvs.bin"),
                "tangents_output_path": _native_preview_delta_output_path("_editor_snapshot_tangents.bin"),
                "tangent_signs_output_path": _native_preview_delta_output_path("_editor_snapshot_tangent_signs.bin"),
                "bone_counts_output_path": _native_preview_delta_output_path("_editor_snapshot_bone_counts.bin"),
                "bone_indices_output_path": _native_preview_delta_output_path("_editor_snapshot_bone_indices.bin"),
                "bone_weights_output_path": _native_preview_delta_output_path("_editor_snapshot_bone_weights.bin"),
                "source_vertex_map_output_path": _native_preview_delta_output_path("_editor_snapshot_source_vertex_map.bin"),
                "source_vertex_offsets_output_path": _native_preview_delta_output_path("_editor_snapshot_source_vertex_offsets.bin"),
            }
        )
    report = export_native_mesh_editor_session_snapshot(
        session_id,
        job_submeshes,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )
    raw_items = report.get("submeshes") if isinstance(report, Mapping) else None
    if not isinstance(raw_items, list):
        return False
    snapshot_items: dict[int, dict[str, object]] = {}
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            return False
        submesh_index = _index(raw_item.get("index"))
        vertex_count = _index(raw_item.get("vertex_count"))
        face_count = _index(raw_item.get("face_count"))
        if submesh_index is None or vertex_count is None or face_count is None:
            return False
        if submesh_index not in metadata_by_index:
            return False
        metadata = dict(metadata_by_index[submesh_index])
        for key in ("name", "material", "texture"):
            if key in raw_item:
                metadata[key] = str(raw_item.get(key) or "")
        if isinstance(raw_item.get("extra_attrs"), Mapping):
            metadata["extra_attrs"] = dict(raw_item["extra_attrs"])
        else:
            metadata.pop("extra_attrs", None)
        snapshot_item = _native_submesh_snapshot_item(
            raw_item,
            metadata=metadata,
            expected_vertices=vertex_count,
            expected_faces=face_count,
        )
        if snapshot_item is None:
            return False
        snapshot_items[submesh_index] = snapshot_item
    if set(snapshot_items) != set(requested):
        return False
    return restore_native_mesh_submesh_snapshot(
        mesh,
        {
            "kind": "native_submesh_snapshot",
            "mesh": _mesh_snapshot_metadata(mesh),
            "submeshes": [snapshot_items[index] for index in requested],
        },
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )


def close_native_mesh_editor_session(
    session_id: str,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 2.0,
) -> dict[str, object] | None:
    return native_mesh_editor_session_command(
        "close",
        session_id,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )


def apply_native_morph_slider_values(
    base_mesh: ParsedMesh,
    deltas: Sequence[object],
    values: Mapping[str, float],
    post_edit_deltas: object = None,
    *,
    timeout_seconds: float = 20.0,
) -> ParsedMesh | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_morph_apply_"))

    def submesh_values(raw: object, submesh_index: int) -> object:
        if raw is None:
            return ()
        try:
            if isinstance(raw, Mapping):
                return raw.get(submesh_index, ())
            return raw[submesh_index]  # type: ignore[index]
        except Exception:
            return ()

    try:
        submeshes: list[dict[str, object]] = []
        for submesh_index, submesh in enumerate(base_mesh.submeshes):
            prefix = sidecar_root / f"submesh_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "output_vertices_path": str(prefix.with_name(prefix.name + "_out_vertices.bin")),
                "output_normals_path": str(prefix.with_name(prefix.name + "_out_normals.bin")),
            }
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                base_mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                vertices = submesh.vertices or ()
                faces = _face_json(submesh.faces, len(vertices))
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
            post_values = submesh_values(post_edit_deltas, submesh_index) or ()
            if post_values:
                item["post_edit_deltas_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_post_edit_deltas.bin"),
                    post_values,
                    fallback=0.0,
                )
            submeshes.append(item)
        if not submeshes:
            return None

        native_deltas: list[dict[str, object]] = []
        for delta_index, delta in enumerate(deltas or ()):
            slider_id = str(getattr(delta, "slider_id", "") or "")
            default_percent = _finite_float(getattr(delta, "default_percent", 0.0), 0.0)
            raw_percent = values.get(slider_id, default_percent) if isinstance(values, Mapping) else default_percent
            percent = _finite_float(raw_percent, default_percent)
            min_percent = _finite_float(getattr(delta, "min_percent", -100.0), -100.0)
            max_percent = _finite_float(getattr(delta, "max_percent", 100.0), 100.0)
            if min_percent > max_percent:
                min_percent, max_percent = max_percent, min_percent
            factor = max(min_percent, min(max_percent, percent)) / 100.0
            if abs(factor) <= 1e-15:
                continue
            delta_submeshes: list[dict[str, object]] = []
            for submesh_index, raw_submesh_deltas in enumerate(getattr(delta, "deltas", ()) or ()):
                if not 0 <= submesh_index < len(base_mesh.submeshes):
                    continue
                prefix = sidecar_root / f"delta_{delta_index}_{submesh_index}"
                delta_submeshes.append(
                    {
                        "index": submesh_index,
                        "deltas_binary": _write_vec3_binary_payload(
                            prefix.with_name(prefix.name + "_deltas.bin"),
                            raw_submesh_deltas,
                            fallback=0.0,
                        ),
                    }
                )
            native_deltas.append({"slider_id": slider_id, "factor": factor, "submeshes": delta_submeshes})

        report = _run_native_mesh_core_job(
            binary,
            "morph-apply-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "morph_apply",
                "submeshes": submeshes,
                "deltas": native_deltas,
            },
            timeout_seconds=timeout_seconds,
        )
        if report is None:
            return None
        raw_reports = report.get("submeshes")
        if not isinstance(raw_reports, list):
            return None
        outputs: dict[int, tuple[list[Vec3], list[Vec3]]] = {}
        for raw_item in raw_reports:
            if not isinstance(raw_item, Mapping):
                return None
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is None or not 0 <= submesh_index < len(base_mesh.submeshes):
                return None
            vertex_count = _index(raw_item.get("vertex_count"))
            normal_count = _index(raw_item.get("normal_count"))
            if vertex_count is None or normal_count is None:
                return None
            vertices_path = Path(str(raw_item.get("vertices_binary") or ""))
            normals_path = Path(str(raw_item.get("normals_binary") or ""))
            vertices = _read_vec3_binary_payload(vertices_path, expected_count=vertex_count)
            normals = _read_vec3_binary_payload(normals_path, expected_count=normal_count)
            if vertices is None or normals is None or len(normals) != len(vertices):
                return None
            if len(vertices) != len(base_mesh.submeshes[submesh_index].vertices):
                return None
            outputs[submesh_index] = (vertices, normals)
        if len(outputs) != len(base_mesh.submeshes):
            return None

        from cdmw.modding.scene_importer import refresh_parsed_mesh_totals

        base_snapshot = snapshot_native_mesh_submeshes(base_mesh, timeout_seconds=timeout_seconds)
        if not isinstance(base_snapshot, Mapping):
            return None
        result = ParsedMesh()
        try:
            if not restore_native_mesh_submesh_snapshot(result, base_snapshot, timeout_seconds=timeout_seconds):
                return None
        finally:
            dispose_native_mesh_submesh_snapshot(
                base_snapshot,
                timeout_seconds=min(float(timeout_seconds or 20.0), 2.0),
            )
        if len(result.submeshes) != len(base_mesh.submeshes):
            return None
        for submesh_index, (vertices, normals) in outputs.items():
            submesh = result.submeshes[submesh_index]
            submesh.vertices = vertices
            submesh.normals = normals
            submesh.vertex_count = len(vertices)
            submesh.face_count = len(submesh.faces)
        _invalidate_native_mesh_session_submeshes(result, range(len(result.submeshes)))
        refresh_parsed_mesh_totals(result)
        return result
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def build_native_morph_post_edit_deltas(
    working_mesh: object,
    slider_only_mesh: object,
    *,
    timeout_seconds: float = 20.0,
) -> list[list[Vec3]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    working_submeshes = getattr(working_mesh, "submeshes", ()) or ()
    slider_submeshes = getattr(slider_only_mesh, "submeshes", ()) or ()
    if not working_submeshes or not slider_submeshes:
        return []
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_morph_post_delta_"))
    try:
        submeshes: list[dict[str, object]] = []
        expected_counts: dict[int, int] = {}
        for submesh_index, (working_submesh, slider_submesh) in enumerate(zip(working_submeshes, slider_submeshes)):
            working_vertices = getattr(working_submesh, "vertices", ()) or ()
            slider_vertices = getattr(slider_submesh, "vertices", ()) or ()
            if len(working_vertices) != len(slider_vertices):
                return None
            prefix = sidecar_root / f"submesh_{submesh_index}"
            expected_counts[submesh_index] = len(working_vertices)
            submeshes.append(
                {
                    "index": submesh_index,
                    "working_vertices_binary": _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_working_vertices.bin"),
                        working_vertices,
                    ),
                    "slider_vertices_binary": _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_slider_vertices.bin"),
                        slider_vertices,
                    ),
                    "deltas_output_path": str(prefix.with_name(prefix.name + "_deltas.bin")),
                }
            )
        if not submeshes:
            return []
        report = _run_native_mesh_core_job(
            binary,
            "morph-post-edit-delta-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "morph_post_edit_delta",
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        if report is None:
            return None
        raw_reports = report.get("submeshes")
        if not isinstance(raw_reports, list):
            return None
        outputs: list[list[Vec3]] = [[] for _submesh in submeshes]
        seen: set[int] = set()
        for raw_item in raw_reports:
            if not isinstance(raw_item, Mapping):
                return None
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is None or submesh_index not in expected_counts:
                return None
            vertex_count = _index(raw_item.get("vertex_count"))
            if vertex_count is None or vertex_count != expected_counts[submesh_index]:
                return None
            if bool(raw_item.get("zero_delta")):
                outputs[submesh_index] = []
                seen.add(submesh_index)
                continue
            deltas = _read_vec3_binary_report_payload(raw_item.get("deltas_binary"), expected_count=vertex_count)
            if deltas is None:
                return None
            outputs[submesh_index] = deltas
            seen.add(submesh_index)
        if seen != set(expected_counts):
            return None
        return outputs
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def build_native_morph_target_delta(
    base_mesh: ParsedMesh,
    target_mesh: ParsedMesh,
    *,
    timeout_seconds: float = 20.0,
) -> tuple[tuple[Vec3, ...], ...] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    if not isinstance(base_mesh, ParsedMesh) or not isinstance(target_mesh, ParsedMesh):
        return None
    base_submeshes = getattr(base_mesh, "submeshes", ()) or ()
    target_submeshes = getattr(target_mesh, "submeshes", ()) or ()
    if len(base_submeshes) != len(target_submeshes):
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_morph_target_delta_"))
    try:
        submeshes: list[dict[str, object]] = []
        expected_counts: dict[int, int] = {}
        for submesh_index, (base_submesh, target_submesh) in enumerate(zip(base_submeshes, target_submeshes)):
            base_vertices = getattr(base_submesh, "vertices", ()) or ()
            target_vertices = getattr(target_submesh, "vertices", ()) or ()
            if len(base_vertices) != len(target_vertices):
                return None
            base_faces = _face_json(getattr(base_submesh, "faces", ()) or (), len(base_vertices))
            target_faces = _face_json(getattr(target_submesh, "faces", ()) or (), len(target_vertices))
            prefix = sidecar_root / f"submesh_{submesh_index}"
            expected_counts[submesh_index] = len(base_vertices)
            submeshes.append(
                {
                    "index": submesh_index,
                    "base_vertices_binary": _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_base_vertices.bin"),
                        base_vertices,
                    ),
                    "target_vertices_binary": _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_target_vertices.bin"),
                        target_vertices,
                    ),
                    "base_faces_binary": _write_face_binary_payload(
                        prefix.with_name(prefix.name + "_base_faces.bin"),
                        base_faces,
                    ),
                    "target_faces_binary": _write_face_binary_payload(
                        prefix.with_name(prefix.name + "_target_faces.bin"),
                        target_faces,
                    ),
                    "deltas_output_path": str(prefix.with_name(prefix.name + "_deltas.bin")),
                }
            )
        report = _run_native_mesh_core_job(
            binary,
            "morph-target-delta-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "morph_target_delta",
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        if report is None:
            return None
        raw_reports = report.get("submeshes")
        if not isinstance(raw_reports, list):
            return None
        outputs: list[tuple[Vec3, ...]] = [tuple() for _submesh in submeshes]
        seen: set[int] = set()
        for raw_item in raw_reports:
            if not isinstance(raw_item, Mapping):
                return None
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is None or submesh_index not in expected_counts:
                return None
            vertex_count = _index(raw_item.get("vertex_count"))
            if vertex_count is None or vertex_count != expected_counts[submesh_index]:
                return None
            deltas = _read_vec3_binary_report_payload(raw_item.get("deltas_binary"), expected_count=vertex_count)
            if deltas is None:
                return None
            outputs[submesh_index] = tuple(deltas)
            seen.add(submesh_index)
        if seen != set(expected_counts):
            return None
        return tuple(outputs)
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def build_native_static_donor_indices(
    original_submesh: SubMesh,
    new_submesh: SubMesh,
    *,
    timeout_seconds: float = 20.0,
) -> list[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    original_vertices = getattr(original_submesh, "vertices", ()) or ()
    new_vertices = getattr(new_submesh, "vertices", ()) or ()
    if not new_vertices:
        return []
    if not original_vertices:
        return [0] * len(new_vertices)
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_static_donor_"))
    try:
        prefix = sidecar_root / "submesh_0"
        report = _run_native_mesh_core_job(
            binary,
            "static-donor-indices-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "static_donor_indices",
                "submeshes": [
                    {
                        "index": 0,
                        "original_vertices_binary": _write_vec3_binary_payload(
                            prefix.with_name(prefix.name + "_original_vertices.bin"),
                            original_vertices,
                        ),
                        "new_vertices_binary": _write_vec3_binary_payload(
                            prefix.with_name(prefix.name + "_new_vertices.bin"),
                            new_vertices,
                        ),
                        "donor_indices_output_path": str(prefix.with_name(prefix.name + "_donor_indices.bin")),
                    }
                ],
            },
            timeout_seconds=timeout_seconds,
        )
        if report is None:
            return None
        raw_reports = report.get("submeshes")
        if not isinstance(raw_reports, list) or len(raw_reports) != 1:
            return None
        raw_item = raw_reports[0]
        if not isinstance(raw_item, Mapping):
            return None
        if _index(raw_item.get("index")) != 0:
            return None
        if _index(raw_item.get("new_vertex_count")) != len(new_vertices):
            return None
        donor_indices = _read_i32_binary_report_payload(
            raw_item.get("donor_indices_binary"),
            expected_count=len(new_vertices),
        )
        if donor_indices is None:
            return None
        if any(index < 0 or index >= len(original_vertices) for index in donor_indices):
            return None
        return donor_indices
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def _apply_native_skin_weight_report(
    mesh: ParsedMesh,
    report: Mapping[str, object],
    expected_counts: Mapping[int, int],
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]]:
    raw_reports = report.get("submeshes")
    if not isinstance(raw_reports, list):
        raise ValueError("invalid native skin weight reports")
    affected: set[int] = set()
    changed_vertices_by_submesh: dict[int, Sequence[int] | set[int]] = {}
    for raw_item in raw_reports:
        if not isinstance(raw_item, Mapping):
            raise ValueError("invalid native skin weight report")
        submesh_index = _index(raw_item.get("index"))
        if submesh_index is None or submesh_index not in expected_counts:
            raise ValueError("invalid native skin weight submesh")
        vertex_count = _index(raw_item.get("vertex_count"))
        if vertex_count is None or vertex_count != expected_counts[submesh_index]:
            raise ValueError("invalid native skin weight vertex count")
        changed_count = _index(raw_item.get("changed_count"))
        if changed_count is None or changed_count < 0:
            raise ValueError("invalid native skin weight changed count")
        changed_vertices = _changed_vertices_from_report_item(raw_item, vertex_count)
        if (
            changed_vertices is None
            or len(changed_vertices) != changed_count
        ):
            raise ValueError("invalid native skin weight changed vertices")
        bones = _read_bone_binary_report_payloads(
            raw_item.get("bone_counts_binary"),
            raw_item.get("bone_indices_binary"),
            raw_item.get("bone_weights_binary"),
            expected_count=vertex_count,
        )
        if bones is None:
            raise ValueError("invalid native skin weight bones")
        bone_indices, bone_weights = bones
        submesh = mesh.submeshes[submesh_index]
        submesh.bone_indices = list(bone_indices)
        submesh.bone_weights = list(bone_weights)
        affected.add(submesh_index)
        changed_vertices_by_submesh[submesh_index] = _changed_vertices_for_report(changed_vertices)
    if affected:
        _mark_native_mesh_session_submeshes_current(mesh, affected)
    return affected, changed_vertices_by_submesh


def _native_pose_preview_bones_payload(skeleton: object) -> list[dict[str, object]]:
    bones: list[dict[str, object]] = []
    for ordinal, bone in enumerate(tuple(getattr(skeleton, "bones", ()) or ())):
        index = _index(getattr(bone, "index", ordinal))
        if index is None or index < 0:
            index = ordinal
        parent_index = _index(getattr(bone, "parent_index", -1))
        if parent_index is None:
            parent_index = -1
        item: dict[str, object] = {
            "index": int(index),
            "parent_index": int(parent_index),
            "position": _vec3_json(getattr(bone, "position", (0.0, 0.0, 0.0))),
        }
        bind_matrix = _native_pose_preview_matrix_payload(getattr(bone, "bind_matrix", ()))
        if bind_matrix is not None:
            item["bind_matrix"] = bind_matrix
        inv_bind_matrix = _native_pose_preview_matrix_payload(getattr(bone, "inv_bind_matrix", ()))
        if inv_bind_matrix is not None:
            item["inv_bind_matrix"] = inv_bind_matrix
        bones.append(item)
    return bones


def _native_pose_preview_matrix_payload(value: object) -> list[float] | None:
    try:
        raw = tuple(float(component) for component in value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    if len(raw) != 16 or any(not math.isfinite(component) for component in raw):
        return None
    if not any(abs(component) > 1e-12 for component in raw):
        return None
    return list(raw)


def _native_pose_preview_rotations_payload(
    pose_rotations: Mapping[int, Sequence[object]] | Mapping[object, object] | None,
) -> list[dict[str, object]]:
    rotations: list[dict[str, object]] = []
    for raw_index, raw_rotation in dict(pose_rotations or {}).items():
        index = _index(raw_index)
        if index is None or index < 0:
            continue
        rotation = _vec3(raw_rotation)
        if not any(abs(component) > 1e-6 for component in rotation):
            continue
        rotations.append({"bone_index": int(index), "rotation_degrees": [rotation[0], rotation[1], rotation[2]]})
    return rotations


def apply_native_mesh_pose_preview(
    mesh: ParsedMesh,
    skeleton: object | None,
    pose_rotations: Mapping[int, Sequence[object]] | Mapping[object, object] | None,
    *,
    timeout_seconds: float = 20.0,
) -> dict[int, tuple[Vec3, ...]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None or not isinstance(mesh, ParsedMesh) or skeleton is None:
        return None
    bones = _native_pose_preview_bones_payload(skeleton)
    rotations = _native_pose_preview_rotations_payload(pose_rotations)
    if not bones or not rotations:
        return {}

    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_pose_preview_"))
    sent_indices: set[int] = set()
    expected_counts: dict[int, int] = {}
    try:
        submeshes: list[dict[str, object]] = []
        for submesh_index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            if vertex_count <= 0:
                continue
            if (
                len(getattr(submesh, "bone_indices", ()) or ()) != vertex_count
                or len(getattr(submesh, "bone_weights", ()) or ()) != vertex_count
            ):
                continue
            prefix = sidecar_root / f"submesh_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "vertex_count": vertex_count,
                "vertices_output_path": str(prefix.with_name(prefix.name + "_vertices.bin")),
                "changed_vertices_output_path": str(prefix.with_name(prefix.name + "_changed_vertices.bin")),
            }
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                item["vertices_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_input_vertices.bin"),
                    getattr(submesh, "vertices", ()) or (),
                )
                bone_payload = _write_bone_binary_payloads(
                    prefix,
                    getattr(submesh, "bone_indices", ()) or (),
                    getattr(submesh, "bone_weights", ()) or (),
                )
                if bone_payload is None:
                    continue
                item.update(bone_payload)
            submeshes.append(item)
            sent_indices.add(submesh_index)
            expected_counts[submesh_index] = vertex_count
        if not submeshes:
            return {}

        report = _run_native_mesh_core_job(
            binary,
            "pose-preview-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "bones": bones,
                "rotations": rotations,
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        if report is None:
            _invalidate_native_mesh_session_submeshes(mesh, sent_indices)
            return None
        raw_reports = report.get("submeshes")
        if not isinstance(raw_reports, list):
            return None
        deformed: dict[int, tuple[Vec3, ...]] = {}
        for raw_item in raw_reports:
            if not isinstance(raw_item, Mapping):
                return None
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is None or submesh_index not in expected_counts:
                return None
            vertex_count = _index(raw_item.get("vertex_count"))
            if vertex_count is None or vertex_count != expected_counts[submesh_index]:
                return None
            changed_count = _index(raw_item.get("changed_count"))
            changed_vertices = _changed_vertices_from_report_item(raw_item, vertex_count)
            if changed_count is None or changed_vertices is None or len(changed_vertices) != changed_count:
                return None
            vertices = _read_vec3_binary_report_payload(raw_item.get("vertices_binary"), expected_count=vertex_count)
            if vertices is None:
                return None
            deformed[submesh_index] = tuple(vertices)
        return deformed
    except (OSError, OverflowError, RuntimeError, ValueError):
        _invalidate_native_mesh_session_submeshes(mesh, sent_indices)
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def write_native_pose_preview_geometry_blob(
    output_path: Path | str,
    *,
    mesh: ParsedMesh,
    skeleton: object | None,
    pose_rotations: Mapping[int, Sequence[object]] | Mapping[object, object] | None,
    identity_output_path: Path | str | None = None,
    timeout_seconds: float = 20.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None or not isinstance(mesh, ParsedMesh) or skeleton is None:
        return None
    bones = _native_pose_preview_bones_payload(skeleton)
    rotations = _native_pose_preview_rotations_payload(pose_rotations)
    if not bones or not rotations:
        return None
    path = Path(output_path)
    pose_sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_pose_preview_geometry_"))
    sent_indices: set[int] = set()
    try:
        pose_submeshes: list[dict[str, object]] = []
        session_ids: dict[int, str] = {}
        expected_counts: dict[int, int] = {}
        for submesh_index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            if vertex_count <= 0:
                continue
            if (
                len(getattr(submesh, "bone_indices", ()) or ()) != vertex_count
                or len(getattr(submesh, "bone_weights", ()) or ()) != vertex_count
            ):
                continue
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if not session_id:
                _invalidate_native_mesh_session_submeshes(mesh, (submesh_index,))
                return None
            prefix = pose_sidecar_root / f"submesh_{submesh_index}"
            pose_submeshes.append(
                {
                    "index": submesh_index,
                    "vertex_count": vertex_count,
                    "session_id": session_id,
                    "vertices_output_path": str(prefix.with_name(prefix.name + "_vertices.bin")),
                    "changed_vertices_output_path": str(prefix.with_name(prefix.name + "_changed_vertices.bin")),
                }
            )
            session_ids[submesh_index] = session_id
            expected_counts[submesh_index] = vertex_count
            sent_indices.add(submesh_index)
        if not pose_submeshes:
            return None
        pose_report = _run_native_mesh_core_job(
            binary,
            "pose-preview-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "bones": bones,
                "rotations": rotations,
                "submeshes": pose_submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        if pose_report is None:
            _invalidate_native_mesh_session_submeshes(mesh, sent_indices)
            return None
        raw_reports = pose_report.get("submeshes")
        if not isinstance(raw_reports, list):
            return None
        preview_meshes: list[dict[str, object]] = []
        for raw_item in raw_reports:
            if not isinstance(raw_item, Mapping):
                return None
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is None or submesh_index not in expected_counts:
                return None
            vertex_count = _index(raw_item.get("vertex_count"))
            if vertex_count is None or vertex_count != expected_counts[submesh_index]:
                return None
            positions_binary = _native_binary_descriptor(
                raw_item.get("vertices_binary"),
                expected_count=vertex_count,
                components=3,
                kind="f64",
            )
            if positions_binary is None:
                return None
            preview_meshes.append(
                {
                    "index": submesh_index,
                    "source_submesh_index": submesh_index,
                    "session_id": session_ids[submesh_index],
                    "positions_binary": positions_binary,
                    "color": (0.25, 0.55, 0.85),
                }
            )
        if not preview_meshes:
            return None
        return write_native_preview_geometry_blob(
            path,
            meshes=preview_meshes,
            identity_output_path=identity_output_path,
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        _invalidate_native_mesh_session_submeshes(mesh, sent_indices)
        return None
    finally:
        shutil.rmtree(pose_sidecar_root, ignore_errors=True)


def apply_native_mesh_skin_weights(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | Mapping[object, object],
    *,
    operation: str,
    bone_index: int = -1,
    delta: float = 0.0,
    timeout_seconds: float = 20.0,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    operation = str(operation or "").strip().lower()
    if operation not in {"adjust", "normalize"}:
        return None
    if operation == "adjust" and int(bone_index) < 0:
        return None
    if not isinstance(mesh, ParsedMesh):
        return None

    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_skin_weights_"))
    sent_indices: set[int] = set()
    try:
        submeshes: list[dict[str, object]] = []
        expected_counts: dict[int, int] = {}
        for raw_submesh_index, raw_vertices in (selected_vertices_by_submesh or {}).items():
            submesh_index = _index(raw_submesh_index)
            if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            if vertex_count <= 0:
                continue
            selected = _selected_vertex_values(raw_vertices, vertex_count)
            if not selected:
                continue
            prefix = sidecar_root / f"submesh_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "vertex_count": vertex_count,
                "changed_vertices_output_path": str(prefix.with_name(prefix.name + "_changed_vertices.bin")),
                "bone_counts_output_path": str(prefix.with_name(prefix.name + "_bone_counts.bin")),
                "bone_indices_output_path": str(prefix.with_name(prefix.name + "_bone_indices.bin")),
                "bone_weights_output_path": str(prefix.with_name(prefix.name + "_bone_weights.bin")),
            }
            _put_selected_vertices_payload(item, prefix, selected, max_count=vertex_count)
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if not session_id:
                _invalidate_native_mesh_session_submeshes(mesh, (submesh_index,))
                return None
            item["session_id"] = session_id
            submeshes.append(item)
            sent_indices.add(submesh_index)
            expected_counts[submesh_index] = vertex_count
        if not submeshes:
            return set(), {}

        report = _run_native_mesh_core_job(
            binary,
            "skin-weights-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": operation,
                "bone_index": int(bone_index),
                "delta": _finite_float(delta, 0.0),
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        if report is None:
            _invalidate_native_mesh_session_submeshes(mesh, sent_indices)
            return None
        return _apply_native_skin_weight_report(mesh, report, expected_counts)
    except (OSError, OverflowError, RuntimeError, ValueError):
        _invalidate_native_mesh_session_submeshes(mesh, sent_indices)
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def transfer_native_mesh_skin_weights_from_source(
    target_mesh: ParsedMesh,
    source_mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | Mapping[object, object],
    selected_all_submeshes: Iterable[int] = (),
    *,
    bone_remap: Mapping[int, int] | None = None,
    timeout_seconds: float = 20.0,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    if not isinstance(target_mesh, ParsedMesh) or not isinstance(source_mesh, ParsedMesh):
        return None

    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_skin_transfer_"))
    sent_indices: set[int] = set()
    try:
        selected_map = selected_vertices_by_submesh if isinstance(selected_vertices_by_submesh, Mapping) else {}
        selected_all: set[int] = set()
        for value in (selected_all_submeshes if selected_all_submeshes is not None else ()):
            index = _index(value)
            if index is not None:
                selected_all.add(index)
        target_indices: set[int] = {index for index in selected_all if index is not None}
        for raw_index in selected_map:
            submesh_index = _index(raw_index)
            if submesh_index is not None:
                target_indices.add(submesh_index)

        submeshes: list[dict[str, object]] = []
        expected_counts: dict[int, int] = {}
        for submesh_index in sorted(target_indices):
            if not 0 <= submesh_index < len(target_mesh.submeshes):
                continue
            if not 0 <= submesh_index < len(source_mesh.submeshes):
                continue
            target = target_mesh.submeshes[submesh_index]
            source = source_mesh.submeshes[submesh_index]
            target_vertices = getattr(target, "vertices", ()) or ()
            source_vertices = getattr(source, "vertices", ()) or ()
            target_vertex_count = len(target_vertices)
            source_vertex_count = len(source_vertices)
            if target_vertex_count <= 0 or source_vertex_count <= 0:
                continue
            source_bone_indices = list(getattr(source, "bone_indices", ()) or ())
            source_bone_weights = list(getattr(source, "bone_weights", ()) or ())
            if not source_bone_indices or not source_bone_weights:
                continue
            if len(source_bone_indices) < source_vertex_count:
                source_bone_indices.extend([()] * (source_vertex_count - len(source_bone_indices)))
            if len(source_bone_weights) < source_vertex_count:
                source_bone_weights.extend([()] * (source_vertex_count - len(source_bone_weights)))
            source_bone_indices = source_bone_indices[:source_vertex_count]
            source_bone_weights = source_bone_weights[:source_vertex_count]

            if submesh_index in selected_all:
                selected_all_vertices = True
            else:
                selected_all_vertices = False
                raw_values = selected_map.get(submesh_index, selected_map.get(str(submesh_index), ()))
                selected = _selected_vertex_values(raw_values, target_vertex_count)
                if not selected:
                    continue

            prefix = sidecar_root / f"submesh_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "vertex_count": target_vertex_count,
                "source_vertices_binary": _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_source_vertices.bin"),
                    source_vertices,
                ),
                "changed_vertices_output_path": str(prefix.with_name(prefix.name + "_changed_vertices.bin")),
                "bone_counts_output_path": str(prefix.with_name(prefix.name + "_bone_counts.bin")),
                "bone_indices_output_path": str(prefix.with_name(prefix.name + "_bone_indices.bin")),
                "bone_weights_output_path": str(prefix.with_name(prefix.name + "_bone_weights.bin")),
            }
            source_bone_payload = _write_bone_binary_payloads(
                prefix.with_name(prefix.name + "_source"),
                source_bone_indices,
                source_bone_weights,
            )
            if source_bone_payload is None:
                continue
            item["source_bone_counts_binary"] = source_bone_payload["bone_counts_binary"]
            item["source_bone_indices_binary"] = source_bone_payload["bone_indices_binary"]
            item["source_bone_weights_binary"] = source_bone_payload["bone_weights_binary"]
            if selected_all_vertices:
                item["selected_all_vertices"] = True
            else:
                _put_selected_vertices_payload(item, prefix, selected, max_count=target_vertex_count)
            if bone_remap is not None:
                pairs = sorted(
                    (int(source_bone), int(target_bone))
                    for source_bone, target_bone in dict(bone_remap).items()
                    if int(source_bone) >= 0 and int(target_bone) >= 0
                )
                item["bone_remap_enabled"] = True
                item["bone_remap_source_binary"] = _write_int_binary_payload(
                    prefix.with_name(prefix.name + "_bone_remap_source.bin"),
                    [source_bone for source_bone, _target_bone in pairs],
                )
                item["bone_remap_target_binary"] = _write_int_binary_payload(
                    prefix.with_name(prefix.name + "_bone_remap_target.bin"),
                    [target_bone for _source_bone, target_bone in pairs],
                )
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                target_mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if not session_id:
                _invalidate_native_mesh_session_submeshes(target_mesh, (submesh_index,))
                return None
            item["session_id"] = session_id
            source_vertex_map = getattr(target, "source_vertex_map", ()) or ()
            if len(source_vertex_map) == target_vertex_count:
                _put_source_vertex_map_payload(item, prefix, source_vertex_map)
            submeshes.append(item)
            sent_indices.add(submesh_index)
            expected_counts[submesh_index] = target_vertex_count
        if not submeshes:
            return set(), {}

        report = _run_native_mesh_core_job(
            binary,
            "skin-weights-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "transfer",
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        if report is None:
            _invalidate_native_mesh_session_submeshes(target_mesh, sent_indices)
            return None
        return _apply_native_skin_weight_report(target_mesh, report, expected_counts)
    except (OSError, OverflowError, RuntimeError, ValueError):
        _invalidate_native_mesh_session_submeshes(target_mesh, sent_indices)
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def build_native_region_volume_delta(
    base_mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | Iterable[int],
    amount: float,
    feather: int,
    *,
    timeout_seconds: float = 20.0,
) -> tuple[tuple[Vec3, ...], ...] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    if not isinstance(base_mesh, ParsedMesh):
        return None
    selected_map: Mapping[object, object]
    if isinstance(selected_vertices_by_submesh, Mapping):
        selected_map = selected_vertices_by_submesh
    else:
        selected_map = {0: selected_vertices_by_submesh}
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_region_volume_"))

    def selected_for_submesh(submesh_index: int, vertex_count: int) -> Sequence[int]:
        raw_values = selected_map.get(submesh_index, selected_map.get(str(submesh_index), ()))
        return _selected_vertex_values(raw_values, vertex_count)

    try:
        submeshes: list[dict[str, object]] = []
        expected_counts: dict[int, int] = {}
        for submesh_index, submesh in enumerate(base_mesh.submeshes):
            vertices = getattr(submesh, "vertices", ()) or ()
            vertex_count = len(vertices)
            expected_counts[submesh_index] = vertex_count
            if vertex_count <= 0:
                continue
            prefix = sidecar_root / f"submesh_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "deltas_output_path": str(prefix.with_name(prefix.name + "_deltas.bin")),
            }
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                base_mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                faces = _face_json(getattr(submesh, "faces", ()) or (), vertex_count)
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
            selected = selected_for_submesh(submesh_index, vertex_count)
            if selected:
                _put_selected_vertices_payload(item, prefix, selected, max_count=vertex_count)
            submeshes.append(item)
        if not submeshes:
            return None
        report = _run_native_mesh_core_job(
            binary,
            "region-volume-delta-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "region_volume_delta",
                "amount": _finite_float(amount, 0.0),
                "feather": max(0, int(_finite_float(feather, 0.0))),
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        if report is None:
            return None
        raw_reports = report.get("submeshes")
        if not isinstance(raw_reports, list):
            return None
        outputs: list[tuple[Vec3, ...]] = [tuple() for _submesh in base_mesh.submeshes]
        seen: set[int] = set()
        for raw_item in raw_reports:
            if not isinstance(raw_item, Mapping):
                return None
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is None or not 0 <= submesh_index < len(outputs):
                return None
            vertex_count = _index(raw_item.get("vertex_count"))
            if vertex_count is None or vertex_count != expected_counts.get(submesh_index, -1):
                return None
            deltas = _read_vec3_binary_report_payload(raw_item.get("deltas_binary"), expected_count=vertex_count)
            if deltas is None:
                return None
            outputs[submesh_index] = tuple(deltas)
            seen.add(submesh_index)
        expected_non_empty = {index for index, count in expected_counts.items() if count > 0}
        if seen != expected_non_empty:
            return None
        return tuple(outputs)
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def _native_brush_edit_payload(params: Mapping[str, object], sidecar_root: Path | None = None) -> dict[str, object]:
    edit_payload: dict[str, object] = {
        "operation": "brush",
        "tool": str(params.get("tool", "grab") or "grab"),
        "center": _vec3_json(params.get("center", (0.0, 0.0, 0.0))),
        "radius": max(0.0, _finite_float(params.get("radius", 1.0), 1.0)),
        "strength": max(0.0, min(1.0, _finite_float(params.get("strength", 1.0), 1.0))),
        "drag_delta": _vec3_json(params.get("drag_delta", params.get("delta", (0.0, 0.0, 0.0)))),
        "amount": _finite_float(params.get("amount", 0.0), 0.0),
        "falloff": str(params.get("falloff", "smooth") or "smooth"),
        "mirror_x": bool(params.get("mirror_x", False)),
        "invert": bool(params.get("invert", False)),
        "iterations": max(1, _index(params.get("iterations", 1)) or 1),
        "sparse_output": True,
    }
    weight_sidecars = _vertex_weights_binary_payloads(sidecar_root, params.get("vertex_weights"))
    if weight_sidecars is not None:
        edit_payload.update(weight_sidecars)
    else:
        vertex_weights = _vertex_weights_json(params.get("vertex_weights"))
        if vertex_weights:
            edit_payload["vertex_weights"] = vertex_weights
    return edit_payload


def apply_native_mesh_brush(
    mesh: ParsedMesh,
    vertices_by_submesh: Mapping[int, set[int] | None],
    params: Mapping[str, object],
    *,
    history_delta: bool = False,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="cdmw_mesh_core_brush_") as sidecar_root_raw:
            sidecar_root = Path(sidecar_root_raw)
            submeshes = []
            for submesh_index, selected in sorted(vertices_by_submesh.items()):
                if not 0 <= submesh_index < len(mesh.submeshes):
                    continue
                submesh = mesh.submeshes[submesh_index]
                vertex_count = len(submesh.vertices)
                if vertex_count <= 0:
                    continue
                prefix = sidecar_root / f"submesh_{submesh_index}"
                item: dict[str, object] = {
                    "index": submesh_index,
                    "selection_restricts_vertices": selected is not None,
                    "changed_vertices_output_path": _native_preview_delta_output_path("_changed_vertices.bin"),
                    "changed_positions_output_path": _native_preview_delta_output_path("_positions.bin"),
                }
                if history_delta:
                    item["before_positions_output_path"] = _native_preview_delta_output_path("_before_positions.bin")
                session_id = _ensure_native_mesh_session_submesh(
                    binary,
                    mesh,
                    submesh_index,
                    timeout_seconds=timeout_seconds,
                ) if stop_event is None else None
                if session_id:
                    item["session_id"] = session_id
                    item["sparse_output"] = True
                    mirror_pairs = _mirror_pairs_json(params.get("mirror_pairs_by_submesh"), submesh_index)
                    if mirror_pairs:
                        item["mirror_pairs"] = mirror_pairs
                else:
                    faces = _face_json(submesh.faces, vertex_count)
                    item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
                    item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                    item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), submesh.normals, fallback=0.0)
                    item["mirror_pairs"] = _mirror_pairs_json(params.get("mirror_pairs_by_submesh"), submesh_index)
                    if len(submesh.uvs) == len(submesh.vertices):
                        item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), submesh.uvs)
                if selected is not None:
                    kept = sorted(index for index in selected if 0 <= index < vertex_count)
                    if not kept:
                        continue
                    _put_selected_vertices_payload(item, prefix, kept, max_count=vertex_count)
                submeshes.append(item)
            if not submeshes:
                return {}

            payload: dict[str, object] = {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "brush",
                "edit": _native_brush_edit_payload(params, sidecar_root),
                "submeshes": submeshes,
            }
            if history_delta:
                payload["sparse_snapshot_id"] = _new_native_sparse_vertex_snapshot_id("brush")
            report = _run_native_mesh_core_job(
                binary,
                "edit-json",
                payload,
                **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
            )
            if report is None:
                return None
            changed = _apply_mesh_edit_report(mesh, report)
            if changed is None:
                return None
            _mark_native_mesh_session_submeshes_current(mesh, changed[0])
            if bool(params.get("recompute_normals", True)):
                _recompute_normals_native_or_fallback(mesh, changed[0], timeout_seconds=timeout_seconds)
            return changed[1]
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None


def apply_native_mesh_brush_binary_selection(
    mesh: ParsedMesh,
    *,
    selected_vertices_binary_by_submesh: Mapping[object, object],
    vertex_weights_binary_by_submesh: Mapping[object, object] | None,
    params: Mapping[str, object],
    history_delta: bool = False,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    if not selected_vertices_binary_by_submesh:
        return None
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_brush_binary_selection_"))
    try:
        submeshes: list[dict[str, object]] = []
        weight_descriptors: dict[int, dict[str, object]] = {}
        for raw_submesh_index, raw_descriptor in sorted(selected_vertices_binary_by_submesh.items(), key=lambda item: str(item[0])):
            submesh_index = _index(raw_submesh_index)
            if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
                continue
            selected_descriptor = _native_existing_binary_descriptor(
                raw_descriptor,
                components=1,
                kinds={"i32"},
            )
            vertex_count = len(getattr(mesh.submeshes[submesh_index], "vertices", ()) or ())
            selected_range = _native_i32_range_descriptor(raw_descriptor, max_count=vertex_count)
            if selected_descriptor is None and selected_range is None:
                continue
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            if not session_id:
                return None
            item: dict[str, object] = {
                "index": submesh_index,
                "session_id": session_id,
                "selection_restricts_vertices": True,
                "sparse_output": True,
                "changed_vertices_output_path": _native_preview_delta_output_path("_changed_vertices.bin"),
                "changed_positions_output_path": _native_preview_delta_output_path("_positions.bin"),
            }
            if selected_descriptor is not None:
                item["selected_vertices_binary"] = selected_descriptor
            elif selected_range is not None:
                item["selected_vertex_start"] = selected_range[0]
                item["selected_vertex_count"] = selected_range[1]
            if history_delta:
                item["before_positions_output_path"] = _native_preview_delta_output_path("_before_positions.bin")
            mirror_pairs = _mirror_pairs_json(params.get("mirror_pairs_by_submesh"), submesh_index)
            if mirror_pairs:
                item["mirror_pairs"] = mirror_pairs
            raw_weight_descriptor = (
                vertex_weights_binary_by_submesh.get(submesh_index, vertex_weights_binary_by_submesh.get(str(submesh_index)))
                if isinstance(vertex_weights_binary_by_submesh, Mapping)
                else None
            )
            weight_descriptor = (
                _native_existing_binary_descriptor(
                    raw_weight_descriptor,
                    components=1,
                    kinds={"f32", "f64"},
                    expected_count=int(selected_descriptor["count"]),
                )
                if selected_descriptor is not None
                else None
            )
            if weight_descriptor is not None:
                weight_descriptors[submesh_index] = weight_descriptor
            submeshes.append(item)
        if not submeshes:
            return {}
        if weight_descriptors and len(submeshes) != 1:
            return None
        edit_payload = _native_brush_edit_payload(params, sidecar_root)
        if weight_descriptors:
            submesh_index = int(submeshes[0]["index"])
            edit_payload["vertex_weight_indices_binary"] = submeshes[0]["selected_vertices_binary"]
            edit_payload["vertex_weights_binary"] = weight_descriptors[submesh_index]
            edit_payload.pop("vertex_weights", None)

        payload: dict[str, object] = {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "brush",
            "edit": edit_payload,
            "submeshes": submeshes,
        }
        if history_delta:
            payload["sparse_snapshot_id"] = _new_native_sparse_vertex_snapshot_id("brush-binary")
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            payload,
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
        if report is None:
            return None
        changed = _apply_mesh_edit_report(mesh, report)
        if changed is None:
            return None
        _mark_native_mesh_session_submeshes_current(mesh, changed[0])
        if bool(params.get("recompute_normals", True)):
            _recompute_normals_native_or_fallback(mesh, changed[0], timeout_seconds=timeout_seconds)
        return changed[1]
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def apply_native_mesh_brush_selection(
    mesh: ParsedMesh,
    *,
    vertices_by_submesh: Mapping[int, set[int]],
    edges_by_submesh: Mapping[int, set[tuple[int, int]]],
    faces_by_submesh: Mapping[int, set[int]],
    source_indices: Sequence[int],
    params: Mapping[str, object],
    history_delta: bool = False,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_brush_selection_"))
    try:
        submeshes = _selection_domain_submesh_items(
            mesh,
            vertices_by_submesh=vertices_by_submesh,
            edges_by_submesh=edges_by_submesh,
            faces_by_submesh=faces_by_submesh,
            source_indices=source_indices,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if submeshes is None:
            return None
        if not submeshes:
            return {}
        for item in submeshes:
            item["selection_restricts_vertices"] = True
            item["sparse_output"] = True
            submesh_index = _index(item.get("index"))
            if submesh_index is not None:
                item["changed_vertices_output_path"] = _native_preview_delta_output_path("_changed_vertices.bin")
                item["changed_positions_output_path"] = _native_preview_delta_output_path("_positions.bin")
                if history_delta:
                    item["before_positions_output_path"] = _native_preview_delta_output_path("_before_positions.bin")
            mirror_pairs = _mirror_pairs_json(params.get("mirror_pairs_by_submesh"), int(item["index"]))
            if mirror_pairs:
                item["mirror_pairs"] = mirror_pairs
        payload: dict[str, object] = {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "brush",
            "edit": _native_brush_edit_payload(params, sidecar_root),
            "submeshes": submeshes,
        }
        if history_delta:
            payload["sparse_snapshot_id"] = _new_native_sparse_vertex_snapshot_id("brush-selection")
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            payload,
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
        if report is None:
            return None
        changed = _apply_mesh_edit_report(mesh, report)
        if changed is None:
            return None
        _mark_native_mesh_session_submeshes_current(mesh, changed[0])
        if bool(params.get("recompute_normals", True)):
            _recompute_normals_native_or_fallback(mesh, changed[0], timeout_seconds=timeout_seconds)
        return changed[1]
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def apply_native_mesh_delete(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]] | None = None,
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    selected_vertices_binary_by_submesh: Mapping[object, object] | None = None,
    all_faces_by_submesh: set[int] | None = None,
    remove_orphans: bool = True,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            selected_faces_by_submesh,
            selected_vertices_by_submesh or {},
            selected_edges_by_submesh or {},
            all_faces_by_submesh or set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
            selected_vertices_binary_by_submesh=selected_vertices_binary_by_submesh,
        )
        if not submeshes:
            return set()
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "delete",
                "edit": {"operation": "delete", "remove_orphans": bool(remove_orphans)},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, _changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected


def apply_native_mesh_dissolve(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]] | None = None,
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    all_faces_by_submesh: set[int] | None = None,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            selected_faces_by_submesh,
            selected_vertices_by_submesh or {},
            selected_edges_by_submesh or {},
            all_faces_by_submesh or set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set()
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "dissolve",
                "edit": {"operation": "dissolve"},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, _changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected


def apply_native_mesh_extrude(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]] | None,
    params: Mapping[str, object],
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    all_faces_by_submesh: set[int] | None = None,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            selected_faces_by_submesh,
            selected_vertices_by_submesh or {},
            selected_edges_by_submesh or {},
            all_faces_by_submesh or set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set(), {}
        offset = params.get("offset", params.get("delta", (0.0, 0.0, 0.25)))
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "extrude",
                "edit": {"operation": "extrude", "offset": _vec3_json(offset)},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected, changed_vertices


def apply_native_mesh_inset(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]] | None,
    params: Mapping[str, object],
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    all_faces_by_submesh: set[int] | None = None,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            selected_faces_by_submesh,
            selected_vertices_by_submesh or {},
            selected_edges_by_submesh or {},
            all_faces_by_submesh or set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set(), {}
        amount = max(0.0, min(0.95, _finite_float(params.get("amount", 0.25), 0.25)))
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "inset",
                "edit": {"operation": "inset", "amount": amount},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected, changed_vertices


def apply_native_mesh_compact_orphans(
    mesh: ParsedMesh,
    submesh_indices: object = None,
    *,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> MeshFaceDeleteResult | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    target_indices = _sorted_unique_valid_submesh_indices(mesh, submesh_indices, all_when_none=True)
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes: list[dict[str, object]] = []
        for submesh_index in target_indices:
            submesh = mesh.submeshes[submesh_index]
            prefix = sidecar_root / f"compact_{submesh_index}"
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            item: dict[str, object] = {"index": submesh_index}
            item["changed_vertices_output_path"] = _native_preview_delta_output_path("_topology_changed_vertices.bin")
            item["vertices_output_path"] = _native_preview_delta_output_path("_topology_vertices.bin")
            item["faces_output_path"] = _native_preview_delta_output_path("_topology_faces.bin")
            if not recompute_normals and len(submesh.normals) == len(submesh.vertices):
                item["normals_output_path"] = _native_preview_delta_output_path("_topology_normals.bin")
            if len(submesh.uvs) == len(submesh.vertices):
                item["uvs_output_path"] = _native_preview_delta_output_path("_topology_uvs.bin")
            if len(getattr(submesh, "tangents", ()) or ()) == len(submesh.vertices):
                item["tangents_output_path"] = _native_preview_delta_output_path("_topology_tangents.bin")
            if len(getattr(submesh, "tangent_signs", ()) or ()) == len(submesh.vertices):
                item["tangent_signs_output_path"] = _native_preview_delta_output_path("_topology_tangent_signs.bin")
            if (
                len(getattr(submesh, "bone_indices", ()) or ()) == len(submesh.vertices)
                and len(getattr(submesh, "bone_weights", ()) or ()) == len(submesh.vertices)
            ):
                item["bone_counts_output_path"] = _native_preview_delta_output_path("_topology_bone_counts.bin")
                item["bone_indices_output_path"] = _native_preview_delta_output_path("_topology_bone_indices.bin")
                item["bone_weights_output_path"] = _native_preview_delta_output_path("_topology_bone_weights.bin")
            if len(getattr(submesh, "source_vertex_map", ()) or ()) == len(submesh.vertices):
                item["source_vertex_map_output_path"] = _native_preview_delta_output_path("_topology_source_vertex_map.bin")
            if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == len(submesh.vertices):
                item["source_vertex_offsets_output_path"] = _native_preview_delta_output_path("_topology_source_vertex_offsets.bin")
            item["suppress_vertex_remap_report"] = True
            if session_id:
                item["session_id"] = session_id
            else:
                faces = _face_json(submesh.faces, len(submesh.vertices))
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                if not recompute_normals and len(submesh.normals) == len(submesh.vertices):
                    item["normals_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_normals.bin"),
                        submesh.normals,
                        fallback=0.0,
                    )
                if len(submesh.uvs) == len(submesh.vertices):
                    item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), submesh.uvs)
                if len(getattr(submesh, "tangents", ()) or ()) == len(submesh.vertices):
                    item["tangents_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_tangents.bin"),
                        getattr(submesh, "tangents", ()) or (),
                        fallback=0.0,
                    )
                if len(getattr(submesh, "tangent_signs", ()) or ()) == len(submesh.vertices):
                    item["tangent_signs_binary"] = _write_f64_binary_payload(
                        prefix.with_name(prefix.name + "_tangent_signs.bin"),
                        getattr(submesh, "tangent_signs", ()) or (),
                    )
                if (
                    len(getattr(submesh, "bone_indices", ()) or ()) == len(submesh.vertices)
                    and len(getattr(submesh, "bone_weights", ()) or ()) == len(submesh.vertices)
                ):
                    bone_payload = _write_bone_binary_payloads(
                        prefix,
                        getattr(submesh, "bone_indices", ()) or (),
                        getattr(submesh, "bone_weights", ()) or (),
                    )
                    if bone_payload is not None:
                        item.update(bone_payload)
                if len(getattr(submesh, "source_vertex_map", ()) or ()) == len(submesh.vertices):
                    _put_source_vertex_map_payload(item, prefix, getattr(submesh, "source_vertex_map", ()) or ())
                if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == len(submesh.vertices):
                    _put_source_vertex_offsets_payload(item, prefix, getattr(submesh, "source_vertex_offsets", ()) or ())
            submeshes.append(item)
        if not submeshes:
            return MeshFaceDeleteResult()
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "compact_orphans",
                "edit": {"operation": "compact_orphans"},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    removed_vertex_count = _mesh_edit_removed_count(report, "removed_vertices")
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, _changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    emptied = tuple(index for index in sorted(affected) if 0 <= index < len(mesh.submeshes) and not mesh.submeshes[index].faces)
    return MeshFaceDeleteResult(
        affected_submesh_indices=tuple(sorted(affected)),
        emptied_submesh_indices=emptied,
        removed_vertex_count=removed_vertex_count,
    )


def apply_native_mesh_fix_winding(
    mesh: ParsedMesh,
    submesh_indices: object = None,
    *,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    target_indices = _sorted_unique_valid_submesh_indices(mesh, submesh_indices, all_when_none=True)
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            {},
            {},
            {},
            target_indices,
            preserve_normals=True,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set()
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "fix_winding",
                "edit": {"operation": "fix_winding"},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, _changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected


def apply_native_mesh_fill_holes(
    mesh: ParsedMesh,
    submesh_indices: object = None,
    *,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    target_indices = _sorted_unique_valid_submesh_indices(mesh, submesh_indices, all_when_none=True)
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            {},
            {},
            {},
            target_indices,
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set()
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "fill_holes",
                "edit": {"operation": "fill_holes"},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, _changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected


def apply_native_mesh_fill(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, set[int]],
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            {},
            selected_vertices_by_submesh or {},
            selected_edges_by_submesh or {},
            set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
            allow_empty_faces_for_selected_vertices=True,
        )
        if not submeshes:
            return set()
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "fill",
                "edit": {"operation": "fill"},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, _changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected


def apply_native_mesh_edge_split(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]] | None = None,
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            selected_faces_by_submesh,
            selected_vertices_by_submesh or {},
            selected_edges_by_submesh or {},
            set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set(), {}
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "edge_split",
                "edit": {"operation": "edge_split"},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected, changed_vertices


def _native_loop_cut_edit(params: Mapping[str, object] | None) -> dict[str, object]:
    edit: dict[str, object] = {"operation": "loop_cut"}
    if not isinstance(params, Mapping):
        return edit
    for key in ("cuts", "count", "segments"):
        if key not in params:
            continue
        value = _index(params.get(key))
        if value is not None:
            edit[key] = value
            break
    for key in ("factor", "position"):
        if key in params:
            edit[key] = _finite_float(params.get(key), 0.5)
            break
    return edit


def apply_native_mesh_loop_cut(
    mesh: ParsedMesh,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]],
    params: Mapping[str, object] | None = None,
    *,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    if not selected_edges_by_submesh:
        return set(), {}
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            {},
            {},
            selected_edges_by_submesh,
            set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set(), {}
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "loop_cut",
                "edit": _native_loop_cut_edit(params),
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected, changed_vertices


def apply_native_mesh_merge(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]] | None = None,
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    all_faces_by_submesh: set[int] | None = None,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            selected_faces_by_submesh,
            selected_vertices_by_submesh or {},
            selected_edges_by_submesh or {},
            all_faces_by_submesh or set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set(), {}
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "merge",
                "edit": {"operation": "merge"},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected, changed_vertices


def apply_native_mesh_weld(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]] | None = None,
    *,
    threshold: float,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    all_faces_by_submesh: set[int] | None = None,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            selected_faces_by_submesh,
            selected_vertices_by_submesh or {},
            selected_edges_by_submesh or {},
            all_faces_by_submesh or set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set(), {}
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "weld",
                "edit": {"operation": "weld", "threshold": _finite_float(threshold, 1e-5)},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected, changed_vertices


def _display_face_json(faces: object) -> list[list[object]]:
    if not isinstance(faces, list):
        return []
    return [list(face) for face in faces if isinstance(face, (tuple, list))]


def apply_native_mesh_triangulate_display(
    mesh: ParsedMesh,
    submesh_indices: object = None,
    *,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    target_indices = _sorted_unique_valid_submesh_indices(mesh, submesh_indices, all_when_none=True)
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes: list[dict[str, object]] = []
        for submesh_index in target_indices:
            submesh = mesh.submeshes[submesh_index]
            display_faces = _display_face_json(submesh.faces)
            if not submesh.vertices or not display_faces:
                continue
            prefix = sidecar_root / f"triangulate_{submesh_index}"
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            item: dict[str, object] = {
                "index": submesh_index,
                "display_faces": display_faces,
                "changed_vertices_output_path": _native_preview_delta_output_path("_topology_changed_vertices.bin"),
                "vertices_output_path": _native_preview_delta_output_path("_topology_vertices.bin"),
                "faces_output_path": _native_preview_delta_output_path("_topology_faces.bin"),
                "preview_triangle_output_path": _native_preview_delta_output_path("_triangles.bin"),
                "suppress_vertex_remap_report": True,
            }
            if not recompute_normals and len(submesh.normals) == len(submesh.vertices):
                item["normals_output_path"] = _native_preview_delta_output_path("_topology_normals.bin")
            if len(submesh.uvs) == len(submesh.vertices):
                item["uvs_output_path"] = _native_preview_delta_output_path("_topology_uvs.bin")
            if len(getattr(submesh, "tangents", ()) or ()) == len(submesh.vertices):
                item["tangents_output_path"] = _native_preview_delta_output_path("_topology_tangents.bin")
            if len(getattr(submesh, "tangent_signs", ()) or ()) == len(submesh.vertices):
                item["tangent_signs_output_path"] = _native_preview_delta_output_path("_topology_tangent_signs.bin")
            if (
                len(getattr(submesh, "bone_indices", ()) or ()) == len(submesh.vertices)
                and len(getattr(submesh, "bone_weights", ()) or ()) == len(submesh.vertices)
            ):
                item["bone_counts_output_path"] = _native_preview_delta_output_path("_topology_bone_counts.bin")
                item["bone_indices_output_path"] = _native_preview_delta_output_path("_topology_bone_indices.bin")
                item["bone_weights_output_path"] = _native_preview_delta_output_path("_topology_bone_weights.bin")
            if len(getattr(submesh, "source_vertex_map", ()) or ()) == len(submesh.vertices):
                item["source_vertex_map_output_path"] = _native_preview_delta_output_path("_topology_source_vertex_map.bin")
            if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == len(submesh.vertices):
                item["source_vertex_offsets_output_path"] = _native_preview_delta_output_path("_topology_source_vertex_offsets.bin")
            if session_id:
                item["session_id"] = session_id
            else:
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
                if not recompute_normals and len(submesh.normals) == len(submesh.vertices):
                    item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), submesh.normals)
                if len(submesh.uvs) == len(submesh.vertices):
                    item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), submesh.uvs)
                if len(getattr(submesh, "tangents", ()) or ()) == len(submesh.vertices):
                    item["tangents_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_tangents.bin"),
                        getattr(submesh, "tangents", ()) or (),
                    )
                if len(getattr(submesh, "tangent_signs", ()) or ()) == len(submesh.vertices):
                    item["tangent_signs_binary"] = _write_f64_binary_payload(
                        prefix.with_name(prefix.name + "_tangent_signs.bin"),
                        getattr(submesh, "tangent_signs", ()) or (),
                    )
                if (
                    len(getattr(submesh, "bone_indices", ()) or ()) == len(submesh.vertices)
                    and len(getattr(submesh, "bone_weights", ()) or ()) == len(submesh.vertices)
                ):
                    bone_payload = _write_bone_binary_payloads(
                        prefix,
                        getattr(submesh, "bone_indices", ()) or (),
                        getattr(submesh, "bone_weights", ()) or (),
                    )
                    if bone_payload is not None:
                        item.update(bone_payload)
                if len(getattr(submesh, "source_vertex_map", ()) or ()) == len(submesh.vertices):
                    _put_source_vertex_map_payload(item, prefix, getattr(submesh, "source_vertex_map", ()) or ())
                if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == len(submesh.vertices):
                    _put_source_vertex_offsets_payload(item, prefix, getattr(submesh, "source_vertex_offsets", ()) or ())
            submeshes.append(item)
        if not submeshes:
            return set()
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "triangulate_display",
                "edit": {"operation": "triangulate_display"},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, _changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected


def _append_native_duplicate_report_submeshes(
    mesh: ParsedMesh,
    report: Mapping[str, object],
    *,
    recompute_normals: bool,
    copy_extra_attrs: bool = False,
    reset_source_descriptors: bool = False,
) -> dict[int, int] | None:
    submesh_reports = report.get("submeshes")
    if not isinstance(submesh_reports, list):
        return None
    appended: dict[int, int] = {}
    for item in submesh_reports:
        if not isinstance(item, Mapping) or not bool(item.get("append_submesh")):
            continue
        source_index = _index(item.get("source_index", item.get("index")))
        if source_index is None or not 0 <= source_index < len(mesh.submeshes):
            return None
        source = mesh.submeshes[source_index]

        raw_vertices = item.get("vertices")
        raw_vertices_binary = item.get("vertices_binary")
        if isinstance(raw_vertices_binary, Mapping):
            vertex_count = _index(raw_vertices_binary.get("count"))
            if vertex_count is None or vertex_count < 0:
                return None
            vertices = _read_vec3_binary_report_payload(raw_vertices_binary, expected_count=vertex_count)
            if vertices is None:
                return None
        elif isinstance(raw_vertices, list):
            vertices = [_vec3(value) for value in raw_vertices]
            vertex_count = len(vertices)
        else:
            return None

        raw_faces = item.get("faces")
        raw_faces_binary = item.get("faces_binary")
        if isinstance(raw_faces_binary, Mapping):
            face_count = _index(raw_faces_binary.get("count"))
            if face_count is None or face_count < 0:
                return None
            faces = _read_face_binary_report_payload(raw_faces_binary, expected_count=face_count, vertex_count=vertex_count)
            if faces is None:
                return None
        elif isinstance(raw_faces, list):
            faces = _face_json(raw_faces, vertex_count)
            if len(faces) != len(raw_faces):
                return None
        else:
            return None

        normals: list[Vec3] = []
        raw_normals_binary = item.get("normals_binary")
        raw_normals = item.get("normals")
        if isinstance(raw_normals_binary, Mapping):
            normals = _read_vec3_binary_report_payload(raw_normals_binary, expected_count=vertex_count) or []
            if len(normals) != vertex_count:
                return None
        elif isinstance(raw_normals, list):
            if len(raw_normals) != vertex_count:
                return None
            normals = [_vec3(value) for value in raw_normals]

        uvs: list[Vec2] = []
        raw_uvs_binary = item.get("uvs_binary")
        raw_uvs = item.get("uvs")
        if isinstance(raw_uvs_binary, Mapping):
            uvs = _read_vec2_binary_report_payload(raw_uvs_binary, expected_count=vertex_count) or []
            if len(uvs) != vertex_count:
                return None
        elif isinstance(raw_uvs, list):
            if len(raw_uvs) != vertex_count:
                return None
            uvs = [_vec2(value) for value in raw_uvs]

        tangents: list[Vec3] = []
        raw_tangents_binary = item.get("tangents_binary")
        raw_tangents = item.get("tangents")
        if isinstance(raw_tangents_binary, Mapping):
            tangents = _read_vec3_binary_report_payload(raw_tangents_binary, expected_count=vertex_count) or []
            if len(tangents) != vertex_count:
                return None
        elif isinstance(raw_tangents, list):
            if len(raw_tangents) != vertex_count:
                return None
            tangents = [_vec3(value) for value in raw_tangents]

        tangent_signs: list[float] = []
        raw_tangent_signs_binary = item.get("tangent_signs_binary")
        raw_tangent_signs = item.get("tangent_signs")
        if isinstance(raw_tangent_signs_binary, Mapping):
            tangent_signs = _read_f64_binary_report_payload(raw_tangent_signs_binary, expected_count=vertex_count) or []
            if len(tangent_signs) != vertex_count:
                return None
        elif isinstance(raw_tangent_signs, list):
            if len(raw_tangent_signs) != vertex_count:
                return None
            tangent_signs = [_finite_float(value, 1.0) for value in raw_tangent_signs]

        bone_indices: list[tuple[int, ...]] = []
        bone_weights: list[tuple[float, ...]] = []
        raw_bone_counts_binary = item.get("bone_counts_binary")
        raw_bone_indices_binary = item.get("bone_indices_binary")
        raw_bone_weights_binary = item.get("bone_weights_binary")
        if (
            isinstance(raw_bone_counts_binary, Mapping)
            and isinstance(raw_bone_indices_binary, Mapping)
            and isinstance(raw_bone_weights_binary, Mapping)
        ):
            native_bones = _read_bone_binary_report_payloads(
                raw_bone_counts_binary,
                raw_bone_indices_binary,
                raw_bone_weights_binary,
                expected_count=vertex_count,
            )
            if native_bones is None:
                return None
            bone_indices, bone_weights = native_bones

        source_vertex_map: list[int] = []
        parsed_source_vertex_map = _source_vertex_map_report_values(item, vertex_count)
        if parsed_source_vertex_map is None:
            return None
        source_vertex_map = parsed_source_vertex_map

        source_vertex_offsets: list[int] = []
        parsed_source_vertex_offsets = _source_vertex_offsets_report_values(item, vertex_count)
        if parsed_source_vertex_offsets is None:
            return None
        source_vertex_offsets = parsed_source_vertex_offsets

        suffix = str(item.get("name_suffix") or " duplicate")
        name = str(item.get("name")) if "name" in item else f"{source.name or 'part'}{suffix}"
        material = str(item.get("material")) if "material" in item else str(source.material or "")
        texture = str(item.get("texture")) if "texture" in item else str(source.texture or "")
        submesh_kwargs: dict[str, object] = {
            "name": name,
            "material": material,
            "texture": texture,
            "vertices": vertices,
            "uvs": uvs,
            "normals": normals,
            "tangents": tangents,
            "faces": [tuple(face) for face in faces],
            "bone_indices": bone_indices,
            "bone_weights": bone_weights,
            "source_vertex_map": source_vertex_map,
            "source_vertex_offsets": source_vertex_offsets,
            "source_vertex_stride": int(source.source_vertex_stride or 0),
            "source_lod_count": int(source.source_lod_count or 0),
        }
        if reset_source_descriptors:
            submesh_kwargs.update(
                {
                    "source_index_offset": -1,
                    "source_index_count": 0,
                    "source_descriptor_offset": -1,
                    "source_bbox_min": _vec3(getattr(source, "source_bbox_min", (0.0, 0.0, 0.0)), fallback=0.0),
                    "source_bbox_extent": _vec3(getattr(source, "source_bbox_extent", (0.0, 0.0, 0.0)), fallback=0.0),
                }
            )
        new_submesh = SubMesh(**submesh_kwargs)  # type: ignore[arg-type]
        new_submesh.vertex_count = len(new_submesh.vertices)
        new_submesh.face_count = len(new_submesh.faces)
        setattr(new_submesh, "cdmw_mesh_edit_topology_source_submesh_index", source_index)
        raw_extra_attrs = item.get("extra_attrs")
        if isinstance(raw_extra_attrs, Mapping):
            for raw_name, value in raw_extra_attrs.items():
                attr_name = str(raw_name or "").strip()
                if attr_name in _EXTRA_SUBMESH_ATTRS:
                    setattr(new_submesh, attr_name, _snapshot_metadata_value(value))
        elif copy_extra_attrs:
            for attr_name in _EXTRA_SUBMESH_ATTRS:
                if hasattr(source, attr_name):
                    setattr(new_submesh, attr_name, _snapshot_metadata_value(getattr(source, attr_name)))
        if tangent_signs:
            setattr(new_submesh, "tangent_signs", tangent_signs)
        if recompute_normals and not new_submesh.normals:
            recompute_submesh_normals(new_submesh)
        mesh.submeshes.append(new_submesh)
        new_index = len(mesh.submeshes) - 1
        preview_triangle_group = _native_preview_triangle_group(item.get("preview_triangle_group"), new_index)
        if preview_triangle_group is not None:
            setattr(new_submesh, "cdmw_native_preview_triangle_group", preview_triangle_group)
        appended[new_index] = source_index
    return appended


def apply_native_mesh_duplicate(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]] | None = None,
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    all_faces_by_submesh: set[int] | None = None,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[set[int], dict[int, int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            selected_faces_by_submesh,
            selected_vertices_by_submesh or {},
            selected_edges_by_submesh or {},
            all_faces_by_submesh or set(),
            preserve_normals=True,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set(), {}
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "duplicate",
                "edit": {"operation": "duplicate"},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    appended = _append_native_duplicate_report_submeshes(
        mesh,
        report,
        recompute_normals=recompute_normals,
        copy_extra_attrs=True,
    )
    if appended is None:
        return None
    _refresh_mesh_totals(mesh)
    return set(appended), appended


def apply_native_mesh_mirror(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]] | None = None,
    *,
    axis: object = "x",
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    all_faces_by_submesh: set[int] | None = None,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[set[int], dict[int, int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    axis_text = str(axis or "x").strip().lower()
    if axis_text not in {"x", "y", "z"}:
        axis_text = "x"
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            selected_faces_by_submesh,
            selected_vertices_by_submesh or {},
            selected_edges_by_submesh or {},
            all_faces_by_submesh or set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set(), {}
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "mirror",
                "edit": {"operation": "mirror", "axis": axis_text},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    appended = _append_native_duplicate_report_submeshes(
        mesh,
        report,
        recompute_normals=recompute_normals,
        copy_extra_attrs=True,
    )
    if appended is None:
        return None
    _refresh_mesh_totals(mesh)
    return set(appended), appended


def apply_native_mesh_separate(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]] | None = None,
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> MeshPartSplitResult | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            selected_faces_by_submesh,
            selected_vertices_by_submesh or {},
            selected_edges_by_submesh or {},
            set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return MeshPartSplitResult()
        if len(submeshes) != 1:
            return None
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "separate",
                "edit": {"operation": "separate"},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    raw_items = report.get("submeshes")
    if not isinstance(raw_items, list):
        return None
    source_items = [item for item in raw_items if isinstance(item, Mapping) and not bool(item.get("append_submesh"))]
    append_items = [item for item in raw_items if isinstance(item, Mapping) and bool(item.get("append_submesh"))]
    if not source_items and not append_items:
        return MeshPartSplitResult()
    source_report = dict(report)
    source_report["submeshes"] = source_items
    changed = _apply_mesh_edit_report(mesh, source_report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, _changed_vertices = changed
    append_report = dict(report)
    append_report["submeshes"] = append_items
    appended = _append_native_duplicate_report_submeshes(
        mesh,
        append_report,
        recompute_normals=False,
        copy_extra_attrs=True,
        reset_source_descriptors=True,
    )
    if appended is None:
        return None
    new_index = min(appended) if appended else -1
    source_index = appended.get(new_index, -1) if new_index >= 0 else (min(affected) if affected else -1)
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        normal_targets = set(affected) | set(appended)
        _recompute_normals_native_or_fallback(mesh, normal_targets, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    moved_face_count = 0
    moved_vertex_count = 0
    if append_items:
        moved_face_count = _index(append_items[0].get("added_faces")) or 0
        moved_vertex_count = _index(append_items[0].get("added_vertices")) or 0
    return MeshPartSplitResult(
        source_submesh_index=source_index,
        new_submesh_index=new_index,
        moved_face_count=moved_face_count,
        moved_vertex_count=moved_vertex_count,
    )


def apply_native_mesh_bridge(
    mesh: ParsedMesh,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]],
    *,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            {},
            {},
            selected_edges_by_submesh or {},
            set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set()
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "bridge",
                "edit": {"operation": "bridge"},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, _changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected


def apply_native_mesh_split(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]] | None = None,
    params: Mapping[str, object] | None = None,
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    all_faces_by_submesh: set[int] | None = None,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            selected_faces_by_submesh,
            selected_vertices_by_submesh or {},
            selected_edges_by_submesh or {},
            all_faces_by_submesh or set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set(), {}
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "split",
                "edit": {"operation": "split"},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected, changed_vertices


def apply_native_mesh_subdivide(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]],
    params: Mapping[str, object],
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    all_faces_by_submesh: set[int] | None = None,
    refine: bool = False,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    operation = "refine_smooth" if refine else "subdivide"
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            selected_faces_by_submesh,
            selected_vertices_by_submesh,
            selected_edges_by_submesh or {},
            all_faces_by_submesh or set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set(), {}
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": operation,
                "edit": {
                    "operation": operation,
                    "max_faces_per_submesh": max(1, _index(params.get("max_faces_per_submesh", 256)) or 256),
                    "smooth_strength": max(0.0, min(1.0, _finite_float(params.get("smooth_strength", params.get("strength", 0.5)), 0.5))),
                    "smooth_iterations": max(1, min(12, _index(params.get("smooth_iterations", params.get("iterations", 2))) or 2)),
                },
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected, changed_vertices


def _allow_python_normal_recompute_fallback(mesh: ParsedMesh, submesh_indices: set[int]) -> bool:
    if not submesh_indices:
        return False
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip() or find_native_mesh_core_binary() is None:
        return True
    vertex_count = _native_mesh_core_count_hint(mesh, "total_vertices")
    face_count = _native_mesh_core_count_hint(mesh, "total_faces")
    record_native_mesh_core_fallback(
        "normals.recalculate.blocked",
        "Python normal recompute fallback blocked while native mesh core is available",
        vertex_count=vertex_count,
        face_count=face_count,
        submesh_indices=tuple(sorted(submesh_indices)),
    )
    return False


def _recompute_normals_native_or_fallback(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    timeout_seconds: float,
) -> None:
    if not submesh_indices:
        return
    native_affected = apply_native_mesh_recalculate_normals(mesh, submesh_indices, timeout_seconds=timeout_seconds)
    if native_affected is not None:
        return
    if not _allow_python_normal_recompute_fallback(mesh, submesh_indices):
        return
    record_native_mesh_core_fallback(
        "normals.recalculate",
        "native normal recompute unavailable inside native wrapper",
        vertex_count=_native_mesh_core_count_hint(mesh, "total_vertices"),
        face_count=_native_mesh_core_count_hint(mesh, "total_faces"),
        submesh_indices=tuple(sorted(submesh_indices)),
    )
    for submesh_index in submesh_indices:
        if 0 <= submesh_index < len(mesh.submeshes):
            recompute_submesh_normals(mesh.submeshes[submesh_index])


def apply_native_mesh_copy_normals(
    mesh: ParsedMesh,
    source_mesh: ParsedMesh,
    vertices_by_submesh: Mapping[int, Sequence[int] | set[int]] | None = None,
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    selected_faces_by_submesh: Mapping[int, set[int]] | None = None,
    source_indices: Sequence[int] = (),
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    vertices_by_submesh = vertices_by_submesh or {}
    selected_edges_by_submesh = selected_edges_by_submesh or {}
    selected_faces_by_submesh = selected_faces_by_submesh or {}
    requested_sources = {
        parsed
        for raw_index in source_indices or ()
        for parsed in (_index(raw_index),)
        if parsed is not None and 0 <= parsed < len(mesh.submeshes)
    }
    target_indices = set(requested_sources)
    for mapping in (vertices_by_submesh, selected_edges_by_submesh, selected_faces_by_submesh):
        for raw_index in mapping:
            parsed = _index(raw_index)
            if parsed is not None:
                target_indices.add(parsed)
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_copy_normals_"))
    try:
        submeshes = []
        for submesh_index in sorted(target_indices):
            if not (0 <= submesh_index < len(mesh.submeshes) and 0 <= submesh_index < len(source_mesh.submeshes)):
                continue
            target = mesh.submeshes[submesh_index]
            source = source_mesh.submeshes[submesh_index]
            vertex_count = len(target.vertices)
            face_count = len(target.faces or ())
            if vertex_count <= 0 or len(source.normals) != len(source.vertices):
                continue
            prefix = sidecar_root / f"copy_normals_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "normals_output_path": _native_preview_delta_output_path("_copy_normals.bin"),
                "changed_vertices_output_path": _native_preview_delta_output_path("_copy_normals_changed_vertices.bin"),
                "preview_vertex_output_path": _native_preview_delta_output_path("_copy_normals_vertices.bin"),
                "source_normals_binary": _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_source_normals.bin"),
                    source.normals,
                    fallback=0.0,
                ),
            }
            if not _put_selected_edit_domain_payload(
                item,
                prefix,
                selected_vertices=vertices_by_submesh.get(submesh_index, ()),
                selected_edges=selected_edges_by_submesh.get(submesh_index, ()),
                selected_faces=selected_faces_by_submesh.get(submesh_index, ()),
                selected_all_vertices=submesh_index in requested_sources,
                vertex_count=vertex_count,
                face_count=face_count,
            ):
                continue
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), target.vertices)
                faces = _face_json(target.faces, vertex_count)
                if faces:
                    item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                if len(target.normals) == vertex_count:
                    item["normals_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_normals.bin"),
                        target.normals,
                        fallback=0.0,
                    )
                if len(target.uvs) == vertex_count:
                    item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), target.uvs)
            submeshes.append(item)
        if not submeshes:
            return {}
        report = _run_native_mesh_core_job(
            binary,
            "recalculate-normals-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "copy_normals",
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_recalculate_normals_report(mesh, report, return_changed_vertices=True)
    if changed:
        _mark_native_mesh_session_submeshes_current(mesh, changed.keys())
    return changed


def apply_native_mesh_recalculate_normals(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    return_changed_vertices: bool = False,
    timeout_seconds: float = 5.0,
) -> set[int] | dict[int, Sequence[int] | set[int]] | None:
    return _apply_native_mesh_normal_edit(
        mesh,
        submesh_indices,
        operation="recalculate_normals",
        return_changed_vertices=return_changed_vertices,
        timeout_seconds=timeout_seconds,
    )


def apply_native_mesh_weighted_normals(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    return _apply_native_mesh_normal_edit(
        mesh,
        submesh_indices,
        operation="weighted_normals",
        include_existing_normals=True,
        return_changed_vertices=True,
        timeout_seconds=timeout_seconds,
    )


def apply_native_mesh_flip_normals(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    selected_faces_by_submesh: Mapping[int, set[int]] | None = None,
    timeout_seconds: float = 5.0,
) -> set[int] | None:
    return _apply_native_mesh_normal_edit(
        mesh,
        submesh_indices,
        operation="flip_normals",
        selected_faces_by_submesh=selected_faces_by_submesh,
        include_existing_normals=True,
        timeout_seconds=timeout_seconds,
    )


def apply_native_mesh_sharpen_normals(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    *,
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    submesh_indices = set(selected_faces_by_submesh)
    if not submesh_indices:
        return {}
    return _apply_native_mesh_normal_edit(
        mesh,
        submesh_indices,
        operation="sharpen_normals",
        selected_faces_by_submesh=selected_faces_by_submesh,
        include_existing_normals=True,
        return_changed_vertices=True,
        timeout_seconds=timeout_seconds,
    )


def _apply_native_mesh_normal_edit(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    operation: str,
    selected_faces_by_submesh: Mapping[int, set[int]] | None = None,
    include_existing_normals: bool = False,
    return_changed_vertices: bool = False,
    timeout_seconds: float = 5.0,
) -> set[int] | dict[int, Sequence[int] | set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_normals_"))
    try:
        submeshes = []
        for submesh_index in sorted(submesh_indices):
            if not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(submesh.vertices)
            face_count = len(submesh.faces or ())
            if vertex_count <= 0 or face_count <= 0:
                continue
            prefix = sidecar_root / f"normals_{submesh_index}"
            item: dict[str, object] = {"index": submesh_index}
            item["normals_output_path"] = _native_preview_delta_output_path("_normals.bin")
            item["changed_vertices_output_path"] = _native_preview_delta_output_path("_changed_vertices.bin")
            if return_changed_vertices and operation != "flip_normals":
                item["preview_vertex_output_path"] = _native_preview_delta_output_path("_normal_vertices.bin")
            if operation == "flip_normals":
                item["faces_output_path"] = _native_preview_delta_output_path("_faces.bin")
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                faces = _face_json(submesh.faces, vertex_count)
                if not faces:
                    continue
                face_count = len(faces)
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
            if include_existing_normals and not session_id and len(submesh.normals) == len(submesh.vertices):
                item["normals_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_normals.bin"),
                    submesh.normals,
                    fallback=0.0,
                )
            if operation in {"flip_normals", "sharpen_normals"}:
                selected_faces = set((selected_faces_by_submesh or {}).get(submesh_index, set()))
                kept_faces = sorted(index for index in selected_faces if 0 <= index < face_count)
                if kept_faces:
                    _put_i32_range_or_binary_payload(
                        item,
                        values=kept_faces,
                        start_key="selected_face_start",
                        count_key="selected_face_count",
                        binary_key="selected_faces_binary",
                        binary_path=prefix.with_name(prefix.name + "_selected_faces.bin"),
                        max_count=face_count,
                    )
                else:
                    item["selected_all_faces"] = True
            submeshes.append(item)
        if not submeshes:
            return set()

        report = _run_native_mesh_core_job(
            binary,
            "recalculate-normals-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": operation,
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    applied = _apply_recalculate_normals_report(mesh, report, return_changed_vertices=return_changed_vertices)
    if applied is not None:
        _mark_native_mesh_session_submeshes_current(mesh, submesh_indices)
    return applied


def apply_native_mesh_generate_tangents(
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
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_tangents_"))
    try:
        submeshes = []
        for submesh_index in sorted(submesh_indices):
            if not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(submesh.vertices)
            face_count = len(submesh.faces or ())
            if vertex_count <= 0 or len(submesh.uvs) != vertex_count or face_count <= 0:
                continue
            prefix = sidecar_root / f"tangents_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "vertices_output_path": _native_preview_delta_output_path("_generated_vertices.bin"),
                "faces_output_path": _native_preview_delta_output_path("_generated_faces.bin"),
                "uvs_output_path": _native_preview_delta_output_path("_generated_uvs.bin"),
                "normals_output_path": _native_preview_delta_output_path("_generated_normals.bin"),
                "tangents_output_path": _native_preview_delta_output_path("_generated_tangents.bin"),
                "tangent_signs_output_path": _native_preview_delta_output_path("_generated_tangent_signs.bin"),
                "changed_vertices_output_path": _native_preview_delta_output_path("_generated_changed_vertices.bin"),
            }
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                faces = _face_json(submesh.faces, vertex_count)
                if not faces:
                    continue
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
                item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), submesh.uvs)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                if len(submesh.normals) == vertex_count:
                    item["normals_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_normals.bin"),
                        submesh.normals,
                        fallback=0.0,
                    )
                if len(getattr(submesh, "tangents", ()) or ()) == vertex_count:
                    item["tangents_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_tangents.bin"),
                        getattr(submesh, "tangents", ()) or (),
                        fallback=0.0,
                    )
            if (
                not session_id
                and len(getattr(submesh, "bone_indices", ()) or ()) == vertex_count
                and len(getattr(submesh, "bone_weights", ()) or ()) == vertex_count
            ):
                bone_payload = _write_bone_binary_payloads(
                    prefix,
                    getattr(submesh, "bone_indices", ()) or (),
                    getattr(submesh, "bone_weights", ()) or (),
                )
                if bone_payload is not None:
                    item.update(bone_payload)
            if len(getattr(submesh, "bone_indices", ()) or ()) == vertex_count and len(getattr(submesh, "bone_weights", ()) or ()) == vertex_count:
                item["bone_counts_output_path"] = _native_preview_delta_output_path("_generated_bone_counts.bin")
                item["bone_indices_output_path"] = _native_preview_delta_output_path("_generated_bone_indices.bin")
                item["bone_weights_output_path"] = _native_preview_delta_output_path("_generated_bone_weights.bin")
            if not session_id and len(getattr(submesh, "source_vertex_map", ()) or ()) == vertex_count:
                _put_source_vertex_map_payload(item, prefix, getattr(submesh, "source_vertex_map", ()) or ())
            if len(getattr(submesh, "source_vertex_map", ()) or ()) == vertex_count:
                item["source_vertex_map_output_path"] = _native_preview_delta_output_path("_generated_source_vertex_map.bin")
            if not session_id and len(getattr(submesh, "source_vertex_offsets", ()) or ()) == vertex_count:
                _put_source_vertex_offsets_payload(item, prefix, getattr(submesh, "source_vertex_offsets", ()) or ())
            if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == vertex_count:
                item["source_vertex_offsets_output_path"] = _native_preview_delta_output_path("_generated_source_vertex_offsets.bin")
            submeshes.append(item)
        if not submeshes:
            return set()

        report = _run_native_mesh_core_job(
            binary,
            "generate-tangents-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "generate_tangents",
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    return _apply_generate_tangents_report(mesh, report)


def apply_native_mesh_remove_doubles(
    mesh: ParsedMesh,
    vertices_by_submesh: Mapping[int, set[int] | None],
    *,
    threshold: float,
    timeout_seconds: float = 5.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_cleanup_"))
    try:
        submeshes = []
        for submesh_index, selected in sorted(vertices_by_submesh.items()):
            if not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            prefix = sidecar_root / f"cleanup_{submesh_index}"
            vertex_count = len(submesh.vertices)
            selected_all_vertices = selected is None
            if selected_all_vertices:
                if vertex_count < 2:
                    continue
                kept: list[int] = []
            else:
                kept = sorted(index for index in selected if 0 <= index < vertex_count)
                if len(kept) < 2:
                    continue
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            item: dict[str, object] = {
                "index": submesh_index,
                "vertices_output_path": _native_preview_delta_output_path("_cleanup_vertices.bin"),
                "faces_output_path": _native_preview_delta_output_path("_cleanup_faces.bin"),
                "normals_output_path": _native_preview_delta_output_path("_cleanup_normals.bin"),
                "suppress_index_map_report": True,
            }
            if selected_all_vertices:
                item["selected_all_vertices"] = True
            else:
                _put_selected_vertices_payload(item, prefix, kept, max_count=vertex_count)
            if session_id:
                item["session_id"] = session_id
            else:
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
                item["faces_binary"] = _write_face_binary_payload(
                    prefix.with_name(prefix.name + "_faces.bin"),
                    _face_json(submesh.faces, vertex_count),
                )
            if len(submesh.uvs) == vertex_count:
                if not session_id:
                    item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), submesh.uvs)
                item["uvs_output_path"] = _native_preview_delta_output_path("_cleanup_uvs.bin")
            if len(getattr(submesh, "tangents", ()) or ()) == vertex_count:
                if not session_id:
                    item["tangents_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_tangents.bin"),
                        getattr(submesh, "tangents", ()) or (),
                    )
                item["tangents_output_path"] = _native_preview_delta_output_path("_cleanup_tangents.bin")
            if len(getattr(submesh, "tangent_signs", ()) or ()) == vertex_count:
                if not session_id:
                    item["tangent_signs_binary"] = _write_f64_binary_payload(
                        prefix.with_name(prefix.name + "_tangent_signs.bin"),
                        getattr(submesh, "tangent_signs", ()) or (),
                        fallback=1.0,
                    )
                item["tangent_signs_output_path"] = _native_preview_delta_output_path("_cleanup_tangent_signs.bin")
            has_bones = (
                len(getattr(submesh, "bone_indices", ()) or ()) == vertex_count
                and len(getattr(submesh, "bone_weights", ()) or ()) == vertex_count
            )
            if has_bones and not session_id:
                bone_payload = _write_bone_binary_payloads(
                    prefix,
                    getattr(submesh, "bone_indices", ()) or (),
                    getattr(submesh, "bone_weights", ()) or (),
                )
                if bone_payload is None:
                    has_bones = False
                else:
                    item.update(bone_payload)
            if has_bones:
                item["bone_counts_output_path"] = _native_preview_delta_output_path("_cleanup_bone_counts.bin")
                item["bone_indices_output_path"] = _native_preview_delta_output_path("_cleanup_bone_indices.bin")
                item["bone_weights_output_path"] = _native_preview_delta_output_path("_cleanup_bone_weights.bin")
            if len(getattr(submesh, "source_vertex_map", ()) or ()) == vertex_count:
                if not session_id:
                    _put_source_vertex_map_payload(item, prefix, getattr(submesh, "source_vertex_map", ()) or ())
                item["source_vertex_map_output_path"] = _native_preview_delta_output_path("_cleanup_source_vertex_map.bin")
            if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == vertex_count:
                if not session_id:
                    _put_source_vertex_offsets_payload(item, prefix, getattr(submesh, "source_vertex_offsets", ()) or ())
                item["source_vertex_offsets_output_path"] = _native_preview_delta_output_path("_cleanup_source_vertex_offsets.bin")
            submeshes.append(item)
        if not submeshes:
            return set()

        report = _run_native_mesh_core_job(
            binary,
            "cleanup-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "cleanup",
                "cleanup": {"threshold": _finite_float(threshold, 1e-5)},
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    return _apply_cleanup_report(mesh, report)


def native_mesh_auto_uv_report(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    resolution: int = 0,
    timeout_seconds: float = 15.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_auto_uv_"))
    try:
        submeshes = []
        for submesh_index in sorted(submesh_indices):
            if not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(submesh.vertices)
            if vertex_count <= 0:
                continue
            prefix = sidecar_root / f"auto_uv_{submesh_index}"
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            item: dict[str, object] = {
                "index": submesh_index,
                "vertices_output_path": _native_preview_delta_output_path("_auto_uv_vertices.bin"),
                "vertex_remap_output_path": _native_preview_delta_output_path("_auto_uv_vertex_remap.bin"),
                "faces_output_path": _native_preview_delta_output_path("_auto_uv_faces.bin"),
                "uvs_output_path": _native_preview_delta_output_path("_auto_uv_uvs.bin"),
                "changed_vertices_output_path": _native_preview_delta_output_path("_auto_uv_changed_vertices.bin"),
                "normals_output_path": _native_preview_delta_output_path("_auto_uv_normals.bin"),
            }
            if session_id:
                item["session_id"] = session_id
            else:
                faces = _face_json(submesh.faces, vertex_count)
                if not faces:
                    continue
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
            if not session_id and len(submesh.normals) == vertex_count:
                item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), submesh.normals)
            if len(getattr(submesh, "tangents", ()) or ()) == vertex_count:
                if not session_id:
                    item["tangents_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_tangents.bin"),
                        tuple(getattr(submesh, "tangents", ()) or ()),
                    )
                item["tangents_output_path"] = _native_preview_delta_output_path("_auto_uv_tangents.bin")
            if len(getattr(submesh, "tangent_signs", ()) or ()) == vertex_count:
                if not session_id:
                    item["tangent_signs_binary"] = _write_f64_binary_payload(
                        prefix.with_name(prefix.name + "_tangent_signs.bin"),
                        tuple(getattr(submesh, "tangent_signs", ()) or ()),
                        fallback=1.0,
                    )
                item["tangent_signs_output_path"] = _native_preview_delta_output_path("_auto_uv_tangent_signs.bin")
            has_bones = (
                len(getattr(submesh, "bone_indices", ()) or ()) == vertex_count
                and len(getattr(submesh, "bone_weights", ()) or ()) == vertex_count
            )
            if has_bones:
                if not session_id:
                    bone_payload = _write_bone_binary_payloads(
                        prefix,
                        getattr(submesh, "bone_indices", ()) or (),
                        getattr(submesh, "bone_weights", ()) or (),
                    )
                    if bone_payload is None:
                        has_bones = False
                    else:
                        item.update(bone_payload)
            if has_bones:
                item["bone_counts_output_path"] = _native_preview_delta_output_path("_auto_uv_bone_counts.bin")
                item["bone_indices_output_path"] = _native_preview_delta_output_path("_auto_uv_bone_indices.bin")
                item["bone_weights_output_path"] = _native_preview_delta_output_path("_auto_uv_bone_weights.bin")
            if len(getattr(submesh, "source_vertex_map", ()) or ()) == vertex_count:
                if not session_id:
                    _put_source_vertex_map_payload(item, prefix, getattr(submesh, "source_vertex_map", ()) or ())
                item["source_vertex_map_output_path"] = _native_preview_delta_output_path("_auto_uv_source_vertex_map.bin")
            if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == vertex_count:
                if not session_id:
                    _put_source_vertex_offsets_payload(item, prefix, getattr(submesh, "source_vertex_offsets", ()) or ())
                item["source_vertex_offsets_output_path"] = _native_preview_delta_output_path("_auto_uv_source_vertex_offsets.bin")
            submeshes.append(item)
        if not submeshes:
            return {"status": "ok", "backend": NATIVE_MESH_CORE_BACKEND_ID, "operation": "auto_uv", "unwrap_backend": "xatlas", "submeshes": []}

        return _run_native_mesh_core_job(
            binary,
            "auto-uv-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "auto_uv",
                "auto_uv": {"resolution": max(0, _index(resolution) or 0)},
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def native_scene_import_report(
    source_path: Path | str,
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    source = Path(source_path).expanduser()
    if not source.is_file():
        return None
    return _run_native_mesh_core_job(
        binary,
        "import-scene-json",
        {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "import_scene",
            "source_path": str(source),
        },
        timeout_seconds=timeout_seconds,
    )


def native_mesh_optimization_report(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    simplify_ratio: float = 1.0,
    target_error: float = 0.01,
    timeout_seconds: float = 15.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_optimize_"))
    try:
        submeshes = []
        for submesh_index in sorted(submesh_indices):
            if not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            if not submesh.vertices:
                continue
            prefix = sidecar_root / f"optimize_{submesh_index}"
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            item: dict[str, object] = {"index": submesh_index}
            if session_id:
                item["session_id"] = session_id
            else:
                faces = _face_json(submesh.faces, len(submesh.vertices))
                if not faces:
                    continue
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
            submeshes.append(item)
        if not submeshes:
            return {
                "status": "ok",
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "optimize",
                "optimization_backend": "meshoptimizer",
                "topology_changed": False,
                "totals": {
                    "input_vertex_count": 0,
                    "referenced_vertex_count": 0,
                    "input_index_count": 0,
                    "output_index_count": 0,
                    "input_triangle_count": 0,
                    "output_triangle_count": 0,
                },
                "submeshes": [],
            }

        return _run_native_mesh_core_job(
            binary,
            "optimize-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "optimize",
                "optimize": {
                    "simplify_ratio": max(0.0, min(1.0, _finite_float(simplify_ratio, 1.0))),
                    "target_error": max(0.0, _finite_float(target_error, 0.01)),
                },
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)


def apply_native_mesh_auto_uv(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    resolution: int = 0,
    allow_topology_change: bool = False,
    timeout_seconds: float = 15.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    report = native_mesh_auto_uv_report(
        mesh,
        submesh_indices,
        resolution=resolution,
        timeout_seconds=timeout_seconds,
    )
    if report is None:
        return None
    if bool(report.get("topology_changed")) and not allow_topology_change:
        return None
    return _apply_auto_uv_report(mesh, report)


def apply_native_mesh_uv_transform(
    mesh: ParsedMesh,
    vertices_by_submesh: Mapping[int, Sequence[int] | set[int]] | None = None,
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    selected_faces_by_submesh: Mapping[int, set[int]] | None = None,
    source_indices: Sequence[int] = (),
    offset: Vec2,
    scale: Vec2,
    rotate_degrees: float,
    flip_u: bool = False,
    flip_v: bool = False,
    pivot: Vec2 = (0.0, 0.0),
    projection: str = "",
    plane: str = "",
    axis: str = "",
    normalize: bool = False,
    target_min: Vec2 = (0.0, 0.0),
    target_max: Vec2 = (1.0, 1.0),
    pack: bool = False,
    pack_columns: int = 0,
    padding: float = 0.02,
    align_u: object = None,
    align_v: object = None,
    snap_step: Vec2 = (0.0, 0.0),
    initialize_missing_uvs: bool = False,
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    vertices_by_submesh = vertices_by_submesh or {}
    selected_edges_by_submesh = selected_edges_by_submesh or {}
    selected_faces_by_submesh = selected_faces_by_submesh or {}
    requested_sources = {
        parsed
        for raw_index in source_indices or ()
        for parsed in (_index(raw_index),)
        if parsed is not None and 0 <= parsed < len(mesh.submeshes)
    }
    target_indices = set(requested_sources)
    for mapping in (vertices_by_submesh, selected_edges_by_submesh, selected_faces_by_submesh):
        for raw_index in mapping:
            parsed = _index(raw_index)
            if parsed is not None:
                target_indices.add(parsed)
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_uv_transform_"))
    try:
        submeshes = []
        transform_payload = _native_uv_transform_payload(
            {
                "offset": offset,
                "scale": scale,
                "rotate": rotate_degrees,
                "flip_u": flip_u,
                "flip_v": flip_v,
                "pivot": pivot,
                "projection": projection,
                "plane": plane,
                "axis": axis,
                "normalize": normalize,
                "target_min": target_min,
                "target_max": target_max,
                "pack": pack,
                "pack_columns": pack_columns,
                "padding": padding,
                "align_u": align_u,
                "align_v": align_v,
                "snap_step": snap_step,
                "initialize_missing_uvs": initialize_missing_uvs,
            }
        )
        if transform_payload is None:
            return None
        needs_projection = bool(str(projection or "").strip())
        needs_missing_uv_init = bool(initialize_missing_uvs or needs_projection)
        needs_faces = bool(pack)
        needs_normals = str(projection or "").strip().lower() in {"box", "cube"}
        for submesh_index in sorted(target_indices):
            if not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(submesh.vertices)
            face_count = len(submesh.faces or ())
            if len(submesh.uvs) != vertex_count and not needs_missing_uv_init:
                continue
            prefix = sidecar_root / f"uv_transform_{submesh_index}"
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            item: dict[str, object] = {
                "index": submesh_index,
                "uvs_output_path": _native_preview_delta_output_path("_uv_transform_uvs.bin"),
                "changed_vertices_output_path": _native_preview_delta_output_path("_uv_transform_changed_vertices.bin"),
            }
            if not _put_selected_edit_domain_payload(
                item,
                prefix,
                selected_vertices=vertices_by_submesh.get(submesh_index, ()),
                selected_edges=selected_edges_by_submesh.get(submesh_index, ()),
                selected_faces=selected_faces_by_submesh.get(submesh_index, ()),
                selected_all_vertices=submesh_index in requested_sources,
                vertex_count=vertex_count,
                face_count=face_count,
            ):
                continue
            if session_id:
                item["session_id"] = session_id
            else:
                item["vertex_count"] = vertex_count
                uvs = submesh.uvs if len(submesh.uvs) == vertex_count else [(0.0, 0.0)] * vertex_count
                item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), uvs)
            if not session_id and needs_projection:
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
            if not session_id and (needs_faces or selected_edges_by_submesh.get(submesh_index) or selected_faces_by_submesh.get(submesh_index)):
                item["faces_binary"] = _write_face_binary_payload(
                    prefix.with_name(prefix.name + "_faces.bin"),
                    _face_json(submesh.faces, vertex_count),
                )
            if not session_id and needs_normals and len(submesh.normals) == vertex_count:
                item["normals_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_normals.bin"),
                    submesh.normals,
                    fallback=0.0,
                )
            submeshes.append(item)
        if not submeshes:
            return {}

        report = _run_native_mesh_core_job(
            binary,
            "uv-transform-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "uv_transform",
                "uv_transform": transform_payload,
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_uv_transform_report(mesh, report)
    if changed:
        _mark_native_mesh_session_submeshes_current(mesh, changed.keys())
    return changed


def apply_native_mesh_uv_transform_submeshes(
    submeshes: Sequence[SubMesh],
    transforms_by_index: Mapping[int, Mapping[str, object]],
    *,
    timeout_seconds: float = 5.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_submesh_uv_transform_"))
    try:
        native_items: list[dict[str, object]] = []
        for raw_submesh_index, raw_transform in sorted((transforms_by_index or {}).items()):
            submesh_index = _index(raw_submesh_index)
            if submesh_index is None or not 0 <= submesh_index < len(submeshes):
                continue
            transform_payload = _native_uv_transform_payload(raw_transform)
            if transform_payload is None:
                return None
            submesh = submeshes[submesh_index]
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            if vertex_count <= 0 or len(getattr(submesh, "uvs", ()) or ()) != vertex_count:
                continue
            prefix = sidecar_root / f"submesh_uv_transform_{submesh_index}"
            native_items.append(
                {
                    "index": submesh_index,
                    "vertex_count": vertex_count,
                    "selected_all_vertices": True,
                    "uvs_binary": _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), submesh.uvs),
                    "uvs_output_path": _native_preview_delta_output_path("_submesh_uv_transform_uvs.bin"),
                    "changed_vertices_output_path": _native_preview_delta_output_path("_submesh_uv_transform_changed_vertices.bin"),
                    "uv_transform": transform_payload,
                }
            )
        if not native_items:
            return set()
        report = _run_native_mesh_core_job(
            binary,
            "uv-transform-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "uv_transform",
                "uv_transform": _native_uv_transform_payload({}) or {},
                "submeshes": native_items,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "uv_transform":
        return None
    for raw_item in tuple(report.get("submeshes") or ()):
        if not isinstance(raw_item, Mapping):
            continue
        status = str(raw_item.get("status") or "ok").strip().lower()
        if status and status != "ok":
            raw_uv = raw_item.get("invalid_uv")
            invalid_uv = _vec2(raw_uv) if raw_uv is not None else (0.0, 0.0)
            raise ValueError(str(raw_item.get("error") or status), invalid_uv)
    mesh = ParsedMesh(path="", format="", submeshes=list(submeshes))
    changed = _apply_uv_transform_report(mesh, report)
    if changed is None:
        return None
    processed: set[int] = set()
    for raw_item in tuple(report.get("submeshes") or ()):
        if not isinstance(raw_item, Mapping):
            continue
        submesh_index = _index(raw_item.get("index"))
        if submesh_index is not None and 0 <= submesh_index < len(submeshes):
            processed.add(submesh_index)
    return processed


def apply_native_mesh_uv_atlas_submesh(
    submesh: SubMesh,
    *,
    offset: Vec2,
    scale: Vec2,
    timeout_seconds: float = 5.0,
) -> bool | None:
    processed = apply_native_mesh_uv_transform_submeshes(
        [submesh],
        {
            0: {
                "offset": offset,
                "scale": scale,
                "input_bounds_min": (-1.0e-4, -1.0e-4),
                "input_bounds_max": (1.0001, 1.0001),
                "clamp_input_uv": True,
                "input_clamp_min": (0.0, 0.0),
                "input_clamp_max": (1.0, 1.0),
            }
        },
        timeout_seconds=timeout_seconds,
    )
    if processed is None:
        return None
    return 0 in processed


def _topology_edit_submeshes(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]],
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    all_faces_by_submesh: set[int] | None = None,
    *,
    binary: Path | None = None,
    sidecar_root: Path | None = None,
    preserve_normals: bool = False,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
    selected_vertices_binary_by_submesh: Mapping[object, object] | None = None,
    allow_empty_faces_for_selected_vertices: bool = False,
) -> list[dict[str, object]]:
    selected_edges_by_submesh = selected_edges_by_submesh or {}
    all_faces_by_submesh = all_faces_by_submesh or set()
    selected_vertices_binary_by_submesh = selected_vertices_binary_by_submesh or {}
    target_indices = set(selected_faces_by_submesh) | set(selected_vertices_by_submesh) | set(selected_edges_by_submesh) | set(all_faces_by_submesh)
    for raw_submesh_index in selected_vertices_binary_by_submesh:
        submesh_index = _index(raw_submesh_index)
        if submesh_index is not None:
            target_indices.add(submesh_index)
    submeshes = []
    for submesh_index in sorted(target_indices):
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        vertex_count = len(submesh.vertices)
        face_count = len(submesh.faces or ())
        edge_selected = bool(selected_edges_by_submesh.get(submesh_index))
        vertex_selected = bool(selected_vertices_by_submesh.get(submesh_index))
        if vertex_count <= 0 or (
            face_count <= 0
            and not edge_selected
            and not (allow_empty_faces_for_selected_vertices and vertex_selected)
        ):
            continue
        item: dict[str, object] = {"index": submesh_index}
        item["name"] = str(getattr(submesh, "name", "") or "")
        item["material"] = str(getattr(submesh, "material", "") or "")
        item["texture"] = str(getattr(submesh, "texture", "") or "")
        extra_attrs = {
            attr_name: _snapshot_metadata_value(getattr(submesh, attr_name))
            for attr_name in _EXTRA_SUBMESH_ATTRS
            if attr_name not in _TRANSIENT_NATIVE_SUBMESH_ATTRS and hasattr(submesh, attr_name)
        }
        if extra_attrs:
            item["extra_attrs"] = extra_attrs
        item["changed_vertices_output_path"] = _native_preview_delta_output_path("_topology_changed_vertices.bin")
        item["vertices_output_path"] = _native_preview_delta_output_path("_topology_vertices.bin")
        item["faces_output_path"] = _native_preview_delta_output_path("_topology_faces.bin")
        if preserve_normals and len(submesh.normals) == len(submesh.vertices):
            item["normals_output_path"] = _native_preview_delta_output_path("_topology_normals.bin")
        if len(submesh.uvs) == len(submesh.vertices):
            item["uvs_output_path"] = _native_preview_delta_output_path("_topology_uvs.bin")
        if len(getattr(submesh, "tangents", ()) or ()) == len(submesh.vertices):
            item["tangents_output_path"] = _native_preview_delta_output_path("_topology_tangents.bin")
        if len(getattr(submesh, "tangent_signs", ()) or ()) == len(submesh.vertices):
            item["tangent_signs_output_path"] = _native_preview_delta_output_path("_topology_tangent_signs.bin")
        if (
            len(getattr(submesh, "bone_indices", ()) or ()) == len(submesh.vertices)
            and len(getattr(submesh, "bone_weights", ()) or ()) == len(submesh.vertices)
        ):
            item["bone_counts_output_path"] = _native_preview_delta_output_path("_topology_bone_counts.bin")
            item["bone_indices_output_path"] = _native_preview_delta_output_path("_topology_bone_indices.bin")
            item["bone_weights_output_path"] = _native_preview_delta_output_path("_topology_bone_weights.bin")
        if len(getattr(submesh, "source_vertex_map", ()) or ()) == len(submesh.vertices):
            item["source_vertex_map_output_path"] = _native_preview_delta_output_path("_topology_source_vertex_map.bin")
        if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == len(submesh.vertices):
            item["source_vertex_offsets_output_path"] = _native_preview_delta_output_path("_topology_source_vertex_offsets.bin")
        item["preview_triangle_output_path"] = _native_preview_delta_output_path("_triangles.bin")
        item["suppress_vertex_remap_report"] = True
        source_face_indices: list[int] | None = None
        session_id = (
            _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            if binary is not None
            else None
        )
        if session_id:
            item["session_id"] = session_id
        elif sidecar_root is not None:
            prefix = sidecar_root / f"topology_{submesh_index}"
            faces, source_face_indices = _face_json_with_source_indices(submesh.faces, vertex_count)
            if not faces and not edge_selected and not (allow_empty_faces_for_selected_vertices and vertex_selected):
                continue
            face_count = len(faces)
            item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
            item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
            if not _is_identity_i32_sequence(source_face_indices):
                _put_source_face_indices_payload(item, prefix, source_face_indices)
            if preserve_normals and len(submesh.normals) == len(submesh.vertices):
                item["normals_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_normals.bin"),
                    submesh.normals,
                    fallback=0.0,
                )
            if len(submesh.uvs) == len(submesh.vertices):
                item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), submesh.uvs)
            if len(getattr(submesh, "tangents", ()) or ()) == len(submesh.vertices):
                item["tangents_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_tangents.bin"),
                    getattr(submesh, "tangents", ()) or (),
                    fallback=0.0,
                )
            if len(getattr(submesh, "tangent_signs", ()) or ()) == len(submesh.vertices):
                item["tangent_signs_binary"] = _write_f64_binary_payload(
                    prefix.with_name(prefix.name + "_tangent_signs.bin"),
                    getattr(submesh, "tangent_signs", ()) or (),
                )
            if (
                len(getattr(submesh, "bone_indices", ()) or ()) == len(submesh.vertices)
                and len(getattr(submesh, "bone_weights", ()) or ()) == len(submesh.vertices)
            ):
                bone_payload = _write_bone_binary_payloads(
                    prefix,
                    getattr(submesh, "bone_indices", ()) or (),
                    getattr(submesh, "bone_weights", ()) or (),
                )
                if bone_payload is not None:
                    item.update(bone_payload)
            if len(getattr(submesh, "source_vertex_map", ()) or ()) == len(submesh.vertices):
                _put_source_vertex_map_payload(item, prefix, getattr(submesh, "source_vertex_map", ()) or ())
            if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == len(submesh.vertices):
                _put_source_vertex_offsets_payload(item, prefix, getattr(submesh, "source_vertex_offsets", ()) or ())
        else:
            faces, source_face_indices = _face_json_with_source_indices(submesh.faces, vertex_count)
            if not faces and not edge_selected and not (allow_empty_faces_for_selected_vertices and vertex_selected):
                continue
            face_count = len(faces)
            item["vertices"] = [_vec3_json(vertex) for vertex in submesh.vertices]
            item["faces"] = faces
            if not _is_identity_i32_sequence(source_face_indices):
                _put_source_face_indices_json_payload(item, source_face_indices)
            if preserve_normals and len(submesh.normals) == len(submesh.vertices):
                item["normals"] = [_vec3_json(normal) for normal in submesh.normals]
            if len(submesh.uvs) == len(submesh.vertices):
                item["uvs"] = [_vec2_json(uv) for uv in submesh.uvs]
            if len(getattr(submesh, "tangents", ()) or ()) == len(submesh.vertices):
                item["tangents"] = [_vec3_json(tangent) for tangent in tuple(getattr(submesh, "tangents", ()) or ())]
            if len(getattr(submesh, "tangent_signs", ()) or ()) == len(submesh.vertices):
                item["tangent_signs"] = [_finite_float(value, 1.0) for value in tuple(getattr(submesh, "tangent_signs", ()) or ())]
            # Bone influences stay binary-only on native paths; JSON fallback lets Python remap them.
            if len(getattr(submesh, "source_vertex_map", ()) or ()) == len(submesh.vertices):
                item["source_vertex_map"] = [int(value) for value in tuple(getattr(submesh, "source_vertex_map", ()) or ())]
            if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == len(submesh.vertices):
                _put_source_vertex_offsets_payload(item, None, getattr(submesh, "source_vertex_offsets", ()) or ())
        raw_selected_faces = selected_faces_by_submesh.get(submesh_index, set())
        if raw_selected_faces:
            selection_source_face_indices = source_face_indices
            if selection_source_face_indices is None:
                _, selection_source_face_indices = _face_json_with_source_indices(submesh.faces, vertex_count)
            if not _is_identity_i32_sequence(selection_source_face_indices):
                face_offset_by_source = {
                    source_face_index: face_offset
                    for face_offset, source_face_index in enumerate(selection_source_face_indices)
                }
                selected_faces = sorted(
                    face_offset_by_source[index]
                    for index in raw_selected_faces
                    if index in face_offset_by_source
                )
            else:
                selected_faces = sorted(index for index in raw_selected_faces if 0 <= index < face_count)
        else:
            selected_faces = []
        selected_vertices = sorted(
            index
            for index in selected_vertices_by_submesh.get(submesh_index, set())
            if 0 <= index < vertex_count
        )
        raw_selected_vertices_binary = selected_vertices_binary_by_submesh.get(
            submesh_index,
            selected_vertices_binary_by_submesh.get(str(submesh_index)),
        )
        selected_vertices_binary = _native_i32_descriptor(raw_selected_vertices_binary)
        if selected_vertices_binary is not None:
            try:
                selected_vertex_count = int(selected_vertices_binary.get("count", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                selected_vertices_binary = None
            else:
                if selected_vertex_count <= 0 or selected_vertex_count > vertex_count:
                    selected_vertices_binary = None
        selected_edges = sorted(
            {
                (min(int(left), int(right)), max(int(left), int(right)))
                for left, right in selected_edges_by_submesh.get(submesh_index, set())
                if 0 <= int(left) < vertex_count
                and 0 <= int(right) < vertex_count
                and int(left) != int(right)
            }
        )
        selected_all_faces = submesh_index in all_faces_by_submesh
        if sidecar_root is not None:
            prefix = sidecar_root / f"topology_{submesh_index}"
            if selected_faces:
                _put_i32_range_or_binary_payload(
                    item,
                    values=selected_faces,
                    start_key="selected_face_start",
                    count_key="selected_face_count",
                    binary_key="selected_faces_binary",
                    binary_path=prefix.with_name(prefix.name + "_selected_faces.bin"),
                    max_count=face_count,
                )
            if selected_vertices_binary is not None:
                item["selected_vertices_binary"] = selected_vertices_binary
            elif selected_vertices:
                _put_i32_range_or_binary_payload(
                    item,
                    values=selected_vertices,
                    start_key="selected_vertex_start",
                    count_key="selected_vertex_count",
                    binary_key="selected_vertices_binary",
                    binary_path=prefix.with_name(prefix.name + "_selected_vertices.bin"),
                    max_count=vertex_count,
                )
            if selected_edges:
                item["selected_edges_binary"] = _write_edge_binary_payload(prefix.with_name(prefix.name + "_selected_edges.bin"), selected_edges)
        if selected_all_faces:
            item["selected_all_faces"] = True
        if selected_faces and "selected_faces_binary" not in item and "selected_face_start" not in item:
            item["selected_faces"] = selected_faces
        if selected_edges and "selected_edges_binary" not in item:
            item["selected_edges"] = [[left, right] for left, right in selected_edges]
        if selected_vertices and "selected_vertices_binary" not in item and "selected_vertex_start" not in item:
            item["selected_vertices"] = selected_vertices
        if selected_faces or selected_edges or selected_vertices or selected_vertices_binary is not None or selected_all_faces:
            submeshes.append(item)
    return submeshes


def _mesh_edit_removed_count(report: Mapping[str, object], key: str) -> int:
    total = 0
    submesh_reports = report.get("submeshes")
    if not isinstance(submesh_reports, list):
        return 0
    for item in submesh_reports:
        if not isinstance(item, dict):
            continue
        value = _index(item.get(key))
        if value is not None and value > 0:
            total += value
    return total


def _apply_mesh_edit_report(
    mesh: ParsedMesh,
    report: Mapping[str, object],
    *,
    skip_topology_normals: bool = False,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    affected: set[int] = set()
    changed_vertices_by_submesh: dict[int, Sequence[int] | set[int]] = {}
    submesh_reports = report.get("submeshes")
    if not isinstance(submesh_reports, list):
        return None
    for item in submesh_reports:
        if not isinstance(item, dict):
            continue
        submesh_index = _index(item.get("index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        raw_vertices = item.get("vertices")
        raw_vertices_binary = item.get("vertices_binary")
        raw_faces = item.get("faces")
        raw_faces_binary = item.get("faces_binary")
        raw_normals = item.get("normals")
        raw_normals_binary = item.get("normals_binary")
        raw_uvs = item.get("uvs")
        raw_uvs_binary = item.get("uvs_binary")
        raw_tangents = item.get("tangents")
        raw_tangents_binary = item.get("tangents_binary")
        raw_tangent_signs = item.get("tangent_signs")
        raw_tangent_signs_binary = item.get("tangent_signs_binary")
        raw_bone_counts_binary = item.get("bone_counts_binary")
        raw_bone_indices_binary = item.get("bone_indices_binary")
        raw_bone_weights_binary = item.get("bone_weights_binary")
        raw_source_vertex_map = item.get("source_vertex_map")
        raw_source_vertex_map_binary = item.get("source_vertex_map_binary")
        raw_source_vertex_offsets = item.get("source_vertex_offsets")
        raw_source_vertex_offsets_binary = item.get("source_vertex_offsets_binary")
        raw_changed_positions = item.get("changed_positions")
        raw_changed_positions_binary = item.get("changed_positions_binary")
        raw_before_positions_binary = item.get("before_positions_binary")
        raw_preview_triangle_group = item.get("preview_triangle_group")
        raw_preview_vertex_update_group = item.get("preview_vertex_update_group")

        old_vertex_count = len(submesh.vertices)
        topology_changed = bool(item.get("topology_changed"))
        changed_ordered = _changed_vertices_from_report_item(item, (1 << 30) if topology_changed else old_vertex_count)
        if changed_ordered is None:
            changed_ordered = []
        changed: Sequence[int] | set[int] = _changed_vertices_for_report(changed_ordered)
        history_delta = None if topology_changed else _native_history_vertex_delta(item, submesh_index, changed_ordered)
        if raw_before_positions_binary is not None and history_delta is None:
            return None
        non_topology_uvs: list[Vec2] | None = None
        sparse_positions = False
        if isinstance(raw_vertices, list):
            vertices = [_vec3(value) for value in raw_vertices]
        elif isinstance(raw_vertices_binary, Mapping):
            vertex_count = _index(raw_vertices_binary.get("count"))
            if vertex_count is None or vertex_count < 0:
                return None
            parsed_vertices = _read_vec3_binary_report_payload(raw_vertices_binary, expected_count=vertex_count)
            if parsed_vertices is None:
                return None
            vertices = parsed_vertices
        elif topology_changed or changed_ordered is None:
            return None
        else:
            if raw_changed_positions_binary is not None:
                raw_changed_positions = _read_vec3_binary_report_payload(
                    raw_changed_positions_binary,
                    expected_count=len(changed_ordered),
                )
            if not isinstance(raw_changed_positions, list):
                return None
            if len(raw_changed_positions) != len(changed_ordered):
                return None
            vertices = list(submesh.vertices or [])
            changed_here: Sequence[int] | set[int] = changed_ordered if isinstance(changed_ordered, range) else set()
            changed_count = 0
            for index, raw_position in zip(changed_ordered, raw_changed_positions):
                vertices[index] = _vec3(raw_position)
                changed_count += 1
                if not isinstance(changed_here, range):
                    changed_here.add(index)
            changed = changed_here if changed_count == len(changed_ordered) else set()
            sparse_positions = True

        if not topology_changed:
            if isinstance(raw_uvs_binary, Mapping):
                if _index(raw_uvs_binary.get("count")) != 0:
                    non_topology_uvs = _read_vec2_binary_report_payload(raw_uvs_binary, expected_count=len(vertices))
                    if non_topology_uvs is None:
                        return None
            elif isinstance(raw_uvs, list):
                if len(raw_uvs) != len(vertices):
                    return None
                non_topology_uvs = [_vec2(uv) for uv in raw_uvs]

        if topology_changed:
            native_normals: list[Vec3] | None = None
            native_uvs: list[Vec2] | None = None
            native_tangents: list[Vec3] | None = None
            native_tangent_signs: list[float] | None = None
            native_bones: tuple[list[tuple[int, ...]], list[tuple[float, ...]]] | None = None
            native_source_vertex_map: list[int] | None = None
            native_source_vertex_offsets: list[int] | None = None
            if isinstance(raw_normals_binary, Mapping):
                native_normals = _read_vec3_binary_report_payload(raw_normals_binary, expected_count=len(vertices))
                if native_normals is None:
                    return None
            elif isinstance(raw_normals, list):
                if len(raw_normals) != len(vertices):
                    return None
                native_normals = [_vec3(normal) for normal in raw_normals]
            if isinstance(raw_uvs_binary, Mapping):
                native_uvs = _read_vec2_binary_report_payload(raw_uvs_binary, expected_count=len(vertices))
                if native_uvs is None:
                    return None
            elif isinstance(raw_uvs, list):
                if len(raw_uvs) != len(vertices):
                    return None
                native_uvs = [_vec2(uv) for uv in raw_uvs]
            if isinstance(raw_tangents_binary, Mapping):
                native_tangents = _read_vec3_binary_report_payload(raw_tangents_binary, expected_count=len(vertices))
                if native_tangents is None:
                    return None
            elif isinstance(raw_tangents, list):
                if len(raw_tangents) != len(vertices):
                    return None
                native_tangents = [_vec3(tangent) for tangent in raw_tangents]
            if isinstance(raw_tangent_signs_binary, Mapping):
                native_tangent_signs = _read_f64_binary_report_payload(raw_tangent_signs_binary, expected_count=len(vertices))
                if native_tangent_signs is None:
                    return None
            elif isinstance(raw_tangent_signs, list):
                if len(raw_tangent_signs) != len(vertices):
                    return None
                native_tangent_signs = [_finite_float(value, 1.0) for value in raw_tangent_signs]
            if (
                isinstance(raw_bone_counts_binary, Mapping)
                and isinstance(raw_bone_indices_binary, Mapping)
                and isinstance(raw_bone_weights_binary, Mapping)
            ):
                native_bones = _read_bone_binary_report_payloads(
                    raw_bone_counts_binary,
                    raw_bone_indices_binary,
                    raw_bone_weights_binary,
                    expected_count=len(vertices),
                )
                if native_bones is None:
                    return None
            native_source_vertex_map = _source_vertex_map_report_values(item, len(vertices))
            if native_source_vertex_map is None:
                return None
            native_source_vertex_offsets = _source_vertex_offsets_report_values(item, len(vertices))
            if native_source_vertex_offsets is None:
                return None
            has_native_source_vertex_map = bool(native_source_vertex_map)
            has_native_source_vertex_offsets = bool(native_source_vertex_offsets)
            copy_indices = _copy_vertex_indices_from_report_item(item, len(vertices))
            if copy_indices is None:
                return None
            vertex_blends = _vertex_blends_from_report_item(item)
            if vertex_blends is None:
                return None
            if copy_indices and len(copy_indices) != len(vertices):
                return None
            if copy_indices:
                _apply_vertex_aligned_topology_result(
                    submesh,
                    copy_indices,
                    vertex_blends,
                    old_vertex_count,
                    skip_normals=skip_topology_normals or native_normals is not None,
                    skip_uvs=native_uvs is not None,
                    skip_tangents=native_tangents is not None,
                    skip_tangent_signs=native_tangent_signs is not None,
                    skip_bones=native_bones is not None,
                    skip_source_vertex_map=has_native_source_vertex_map,
                    skip_source_vertex_offsets=has_native_source_vertex_offsets,
                )
            elif not vertices:
                _clear_vertex_aligned_topology_result(submesh)
            if native_normals is not None:
                submesh.normals = native_normals  # type: ignore[attr-defined]
            if native_uvs is not None:
                submesh.uvs = native_uvs
            if native_tangents is not None:
                submesh.tangents = native_tangents  # type: ignore[attr-defined]
            if native_tangent_signs is not None:
                setattr(submesh, "tangent_signs", native_tangent_signs)
            if native_bones is not None:
                submesh.bone_indices, submesh.bone_weights = native_bones  # type: ignore[attr-defined]
            if has_native_source_vertex_map:
                submesh.source_vertex_map = native_source_vertex_map  # type: ignore[attr-defined]
            if has_native_source_vertex_offsets:
                submesh.source_vertex_offsets = native_source_vertex_offsets  # type: ignore[attr-defined]
            if isinstance(raw_faces, list):
                faces = _face_json(raw_faces, len(vertices))
                if len(faces) != len(raw_faces):
                    return None
                submesh.faces = [tuple(face) for face in faces]
                submesh.face_count = len(submesh.faces)
            elif isinstance(raw_faces_binary, Mapping):
                face_count = _index(raw_faces_binary.get("count"))
                if face_count is None or face_count < 0:
                    return None
                faces = _read_face_binary_report_payload(
                    raw_faces_binary,
                    expected_count=face_count,
                    vertex_count=len(vertices),
                )
                if faces is None:
                    return None
                submesh.faces = faces
                submesh.face_count = len(submesh.faces)
            else:
                return None
        elif len(vertices) != old_vertex_count:
            return None

        if sparse_positions:
            if changed:
                submesh.vertices = vertices
                submesh.vertex_count = len(vertices)
        elif raw_vertices is not None or raw_vertices_binary is not None:
            submesh.vertices = vertices
            submesh.vertex_count = len(vertices)
        if non_topology_uvs is not None:
            submesh.uvs = non_topology_uvs
        if topology_changed:
            submesh.vertices = vertices
            submesh.vertex_count = len(vertices)
            affected.add(submesh_index)

        changed = _bounded_changed_vertices(changed, len(vertices))
        if changed:
            changed_vertices_by_submesh[submesh_index] = changed
            affected.add(submesh_index)
        preview_triangle_group = _native_preview_triangle_group(raw_preview_triangle_group, submesh_index)
        if preview_triangle_group is not None:
            setattr(submesh, "cdmw_native_preview_triangle_group", preview_triangle_group)
        elif hasattr(submesh, "cdmw_native_preview_triangle_group"):
            delattr(submesh, "cdmw_native_preview_triangle_group")
        preview_vertex_update_group = _native_preview_vertex_update_group(raw_preview_vertex_update_group, submesh_index)
        if preview_vertex_update_group is not None:
            setattr(submesh, "cdmw_native_preview_vertex_update_group", preview_vertex_update_group)
        elif hasattr(submesh, "cdmw_native_preview_vertex_update_group"):
            delattr(submesh, "cdmw_native_preview_vertex_update_group")
        if history_delta is not None:
            setattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR, history_delta)
        elif hasattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR):
            delattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR)
    return affected, changed_vertices_by_submesh


def _native_preview_triangle_group(value: object, submesh_index: int) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if str(value.get("preview_backend") or "") != "cdmw_mesh_core":
        return None
    source_index = _index(value.get("source_submesh_index"))
    if source_index != submesh_index:
        return None
    group: dict[str, object] = {"preview_backend": "cdmw_mesh_core", "source_submesh_index": submesh_index}
    source_vertices = _int_list(value.get("source_vertex_indices"))
    source_vertex_count = len(source_vertices)
    source_vertex_start = _index(value.get("source_vertex_start"))
    source_vertex_range_count = _index(value.get("source_vertex_count"))
    has_source_vertex_range = (
        source_vertex_start is not None
        and source_vertex_start >= 0
        and source_vertex_range_count is not None
        and source_vertex_range_count > 0
    )
    raw_source_vertices_binary = value.get("source_vertex_indices_binary")
    if source_vertex_count == 0 and isinstance(raw_source_vertices_binary, Mapping):
        source_vertex_count = _index(raw_source_vertices_binary.get("count")) or 0
    if source_vertex_count == 0 and has_source_vertex_range:
        source_vertex_count = int(source_vertex_range_count or 0)
    if source_vertices:
        group["source_vertex_indices"] = source_vertices
    source_vertices_binary = _native_binary_descriptor(raw_source_vertices_binary, expected_count=source_vertex_count, components=1, kind="i32")
    if source_vertices_binary is not None:
        group["source_vertex_indices_binary"] = source_vertices_binary
    elif has_source_vertex_range:
        group["source_vertex_start"] = int(source_vertex_start or 0)
        group["source_vertex_count"] = int(source_vertex_range_count or 0)

    source_faces = _int_list(value.get("source_face_indices"))
    source_face_count = len(source_faces)
    source_face_start = _index(value.get("source_face_start"))
    source_face_range_count = _index(value.get("source_face_count"))
    has_source_face_range = (
        source_face_start is not None
        and source_face_start >= 0
        and source_face_range_count is not None
        and source_face_range_count > 0
    )
    raw_source_faces_binary = value.get("source_face_indices_binary")
    if source_face_count == 0 and isinstance(raw_source_faces_binary, Mapping):
        source_face_count = _index(raw_source_faces_binary.get("count")) or 0
    if source_face_count == 0 and has_source_face_range:
        source_face_count = int(source_face_range_count or 0)
    if source_faces:
        group["source_face_indices"] = source_faces
    source_faces_binary = _native_binary_descriptor(raw_source_faces_binary, expected_count=source_face_count, components=1, kind="i32")
    if source_faces_binary is not None:
        group["source_face_indices_binary"] = source_faces_binary
    elif has_source_face_range:
        group["source_face_start"] = int(source_face_start or 0)
        group["source_face_count"] = int(source_face_range_count or 0)

    positions = value.get("positions")
    positions_binary = _native_binary_descriptor(value.get("positions_binary"), expected_count=source_vertex_count, components=3, kind="f64")
    if positions_binary is None:
        if not isinstance(positions, list) or len(positions) != source_vertex_count * 3:
            return None
        group["positions"] = list(positions)
    else:
        group["positions_binary"] = positions_binary

    normals = value.get("normals")
    normals_binary = _native_binary_descriptor(value.get("normals_binary"), expected_count=source_vertex_count, components=3, kind="f64")
    if normals_binary is not None:
        group["normals_binary"] = normals_binary
    elif isinstance(normals, list):
        if normals and len(normals) != source_vertex_count * 3:
            return None
        group["normals"] = list(normals)
    elif source_vertex_count > 0:
        return None

    uvs = value.get("uvs")
    uvs_binary = _native_binary_descriptor(value.get("uvs_binary"), expected_count=source_vertex_count, components=2, kind="f64")
    if uvs_binary is not None:
        group["uvs_binary"] = uvs_binary
    elif isinstance(uvs, list):
        if uvs and len(uvs) != source_vertex_count * 2:
            return None
        group["uvs"] = list(uvs)
    elif source_vertex_count > 0:
        return None

    indices = _int_list(value.get("indices"))
    raw_indices_binary = value.get("indices_binary")
    index_count = len(indices)
    if index_count == 0 and isinstance(raw_indices_binary, Mapping):
        index_count = _index(raw_indices_binary.get("count")) or 0
    if indices:
        group["indices"] = indices
    indices_binary = _native_binary_descriptor(raw_indices_binary, expected_count=index_count, components=1, kind="i32")
    if indices_binary is not None:
        group["indices_binary"] = indices_binary
    elif index_count > 0 and not indices:
        return None
    if source_vertex_count == 0:
        for key in ("source_vertex_indices", "source_face_indices", "positions", "normals", "uvs", "indices"):
            group.setdefault(key, [])
    return group


def _native_preview_vertex_update_group(value: object, submesh_index: int) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if str(value.get("preview_backend") or "") != "cdmw_mesh_core":
        return None
    source_index = _index(value.get("source_submesh_index"))
    if source_index != submesh_index:
        return None
    source_vertices = _int_list(value.get("source_vertex_indices"))
    raw_source_vertices_binary = value.get("source_vertex_indices_binary")
    source_vertex_count = len(source_vertices)
    source_vertex_start = _index(value.get("source_vertex_start"))
    source_vertex_range_count = _index(value.get("source_vertex_count"))
    has_source_vertex_range = (
        source_vertex_start is not None
        and source_vertex_start >= 0
        and source_vertex_range_count is not None
        and source_vertex_range_count > 0
    )
    if source_vertex_count == 0 and isinstance(raw_source_vertices_binary, Mapping):
        source_vertex_count = _index(raw_source_vertices_binary.get("count")) or 0
    if source_vertex_count == 0 and has_source_vertex_range:
        source_vertex_count = int(source_vertex_range_count or 0)
    source_vertices_binary = _native_binary_descriptor(
        raw_source_vertices_binary,
        expected_count=source_vertex_count,
        components=1,
        kind="i32",
    )
    if source_vertex_count > 0 and not source_vertices and source_vertices_binary is None and not has_source_vertex_range:
        return None
    positions = value.get("positions")
    positions_binary = _native_binary_descriptor(
        value.get("positions_binary"),
        expected_count=source_vertex_count,
        components=3,
        kind="f64",
    )
    normals = value.get("normals")
    normals_binary = _native_binary_descriptor(
        value.get("normals_binary"),
        expected_count=source_vertex_count,
        components=3,
        kind="f64",
    )
    uvs = value.get("uvs")
    uvs_binary = _native_binary_descriptor(
        value.get("uvs_binary"),
        expected_count=source_vertex_count,
        components=2,
        kind="f64",
    )
    if positions_binary is None and not isinstance(positions, list):
        return None
    if isinstance(positions, list) and len(positions) != source_vertex_count * 3:
        return None
    if isinstance(normals, list) and normals and len(normals) != source_vertex_count * 3:
        return None
    if isinstance(uvs, list) and uvs and len(uvs) != source_vertex_count * 2:
        return None
    group: dict[str, object] = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": submesh_index,
    }
    if source_vertices_binary is not None:
        group["source_vertex_indices_binary"] = source_vertices_binary
    elif has_source_vertex_range:
        group["source_vertex_start"] = int(source_vertex_start or 0)
        group["source_vertex_count"] = int(source_vertex_range_count or 0)
    else:
        group["source_vertex_indices"] = source_vertices
    if positions_binary is not None:
        group["positions_binary"] = positions_binary
    else:
        group["positions"] = list(positions or [])
    if normals_binary is not None:
        group["normals_binary"] = normals_binary
    else:
        group["normals"] = list(normals) if isinstance(normals, list) else []
    if uvs_binary is not None:
        group["uvs_binary"] = uvs_binary
    else:
        group["uvs"] = list(uvs) if isinstance(uvs, list) else []
    return group


def _copy_vertex_indices_from_report_item(item: Mapping[str, object], output_vertex_count: int) -> list[int] | None:
    raw_copy_binary = item.get("copy_vertex_indices_binary")
    if isinstance(raw_copy_binary, Mapping):
        return _read_i32_binary_report_payload(raw_copy_binary, expected_count=output_vertex_count)
    return _int_list(item.get("copy_vertex_indices"))


def _vertex_blends_from_report_item(item: Mapping[str, object]) -> dict[int, tuple[int, int, float]] | None:
    raw_indices_binary = item.get("vertex_blend_indices_binary")
    raw_factors_binary = item.get("vertex_blend_factors_binary")
    if isinstance(raw_indices_binary, Mapping) or isinstance(raw_factors_binary, Mapping):
        if not isinstance(raw_indices_binary, Mapping) or not isinstance(raw_factors_binary, Mapping):
            return None
        count = _index(raw_indices_binary.get("count"))
        if count is None or count < 0:
            return None
        if _index(raw_factors_binary.get("count")) != count:
            return None
        indices = _read_i32_components_binary_report_payload(raw_indices_binary, expected_count=count, components=3)
        factors = _read_f64_binary_report_payload(raw_factors_binary, expected_count=count)
        if indices is None or factors is None:
            return None
        return {
            int(index): (int(left), int(right), max(0.0, min(1.0, float(factor))))
            for (index, left, right), factor in zip(indices, factors)
        }
    return _vertex_blends(item.get("vertex_blends"))


def _vertex_weights_binary_payloads(sidecar_root: Path | None, value: object) -> dict[str, object] | None:
    if sidecar_root is None or value is None:
        return None
    items = value.items() if isinstance(value, Mapping) else value
    try:
        iterator = iter(items)  # type: ignore[arg-type]
    except TypeError:
        return None
    indices: list[int] = []
    weights: list[float] = []
    for item in iterator:
        try:
            raw_index, raw_weight = item  # type: ignore[misc]
        except (TypeError, ValueError):
            continue
        index = _index(raw_index)
        if index is None or index < 0:
            continue
        indices.append(index)
        weights.append(max(0.0, min(1.0, _finite_float(raw_weight, 0.0))))
    if not indices:
        return None
    prefix = sidecar_root / "brush_vertex_weights"
    return {
        "vertex_weight_indices_binary": _write_int_binary_payload(prefix.with_name(prefix.name + "_indices.bin"), indices),
        "vertex_weights_binary": _write_f64_binary_payload(prefix.with_name(prefix.name + "_weights.bin"), weights, fallback=0.0),
    }


def _refresh_mesh_totals(mesh: ParsedMesh) -> None:
    mesh.total_vertices = sum(len(submesh.vertices or []) for submesh in mesh.submeshes or [])
    mesh.total_faces = sum(len(submesh.faces or []) for submesh in mesh.submeshes or [])
    mesh.has_uvs = any(bool(submesh.uvs) for submesh in mesh.submeshes or [])
    mesh.has_bones = any(bool(submesh.bone_indices) or bool(submesh.bone_weights) for submesh in mesh.submeshes or [])
    for submesh in mesh.submeshes or []:
        submesh.vertex_count = len(submesh.vertices or [])
        submesh.face_count = len(submesh.faces or [])


def _apply_transform_report(mesh: ParsedMesh, report: Mapping[str, object]) -> dict[int, Sequence[int] | set[int]] | None:
    changed: dict[int, Sequence[int] | set[int]] = {}
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
        changed_positions = item.get("changed_positions")
        changed_positions_binary = item.get("changed_positions_binary")
        raw_preview_vertex_update_group = item.get("preview_vertex_update_group")
        raw_before_positions_binary = item.get("before_positions_binary")
        submesh = mesh.submeshes[submesh_index]
        parsed_changed_ordered = _changed_vertices_from_report_item(item, len(submesh.vertices))
        if parsed_changed_ordered is None:
            continue
        parsed_changed = _changed_vertices_for_report(parsed_changed_ordered)
        history_delta = _native_history_vertex_delta(item, submesh_index, parsed_changed_ordered)
        if raw_before_positions_binary is not None and history_delta is None:
            return None
        if isinstance(vertices, list):
            if len(vertices) != len(submesh.vertices):
                return None
            parsed_vertices = [_vec3(value) for value in vertices]
            if parsed_changed:
                submesh.vertices = parsed_vertices
                submesh.vertex_count = len(parsed_vertices)
                _merge_changed_vertices(
                    changed,
                    submesh_index,
                    parsed_changed,
                )
        else:
            if changed_positions_binary is not None:
                changed_positions = _read_vec3_binary_report_payload(
                    changed_positions_binary,
                    expected_count=len(parsed_changed_ordered),
                )
            if not isinstance(changed_positions, list):
                if parsed_changed:
                    return None
                changed_positions = []
            if len(changed_positions) != len(parsed_changed_ordered):
                return None
            changed_here: Sequence[int] | set[int] = parsed_changed_ordered if isinstance(parsed_changed_ordered, range) else set()
            changed_count = 0
            vertices_copy = list(submesh.vertices or [])
            for index, raw_position in zip(parsed_changed_ordered, changed_positions):
                vertices_copy[index] = _vec3(raw_position)
                changed_count += 1
                if not isinstance(changed_here, range):
                    changed_here.add(index)
            if changed_here:
                submesh.vertices = vertices_copy
                submesh.vertex_count = len(vertices_copy)
                _merge_changed_vertices(
                    changed,
                    submesh_index,
                    changed_here if changed_count == len(parsed_changed_ordered) else set(),
                )
        preview_vertex_update_group = _native_preview_vertex_update_group(raw_preview_vertex_update_group, submesh_index)
        if preview_vertex_update_group is not None:
            setattr(submesh, "cdmw_native_preview_vertex_update_group", preview_vertex_update_group)
        elif hasattr(submesh, "cdmw_native_preview_vertex_update_group"):
            delattr(submesh, "cdmw_native_preview_vertex_update_group")
        if history_delta is not None:
            setattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR, history_delta)
        elif hasattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR):
            delattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR)
    return changed


def _native_report_metrics(report: Mapping[str, object]) -> dict[str, float]:
    raw_metrics = report.get("metrics")
    if not isinstance(raw_metrics, Mapping):
        return {}
    metrics: dict[str, float] = {}
    for key, value in raw_metrics.items():
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(number):
            metrics[str(key)] = max(0.0, number)
    return metrics


def _apply_selection_report(mesh: ParsedMesh, report: Mapping[str, object]) -> dict[int, set[int]] | None:
    selected_by_submesh: dict[int, set[int]] = {}
    submesh_reports = report.get("submeshes")
    if not isinstance(submesh_reports, list):
        return None
    for item in submesh_reports:
        if not isinstance(item, dict):
            continue
        submesh_index = _index(item.get("index"))
        raw_selected = item.get("selected_vertices")
        raw_selected_binary = item.get("selected_vertices_binary")
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        vertex_count = len(mesh.submeshes[submesh_index].vertices)
        selected_range = _i32_range_report_values(
            item,
            start_key="selected_vertex_start",
            count_key="selected_vertex_count",
            max_count=vertex_count,
        )
        if selected_range is not None:
            selected = set(selected_range)
        elif isinstance(raw_selected_binary, Mapping):
            selected_values = _read_int_binary_report_payload(raw_selected_binary, max_count=vertex_count)
            if selected_values is None:
                return None
            selected = set(selected_values)
        elif isinstance(raw_selected, list):
            selected = {
                index
                for raw_index in raw_selected
                for index in [_index(raw_index)]
                if index is not None and 0 <= index < vertex_count
            }
        else:
            continue
        if selected:
            selected_by_submesh[submesh_index] = selected
    return selected_by_submesh


def _apply_recalculate_normals_report(
    mesh: ParsedMesh,
    report: Mapping[str, object],
    *,
    return_changed_vertices: bool = False,
) -> set[int] | dict[int, Sequence[int] | set[int]] | None:
    affected: set[int] = set()
    changed: dict[int, Sequence[int] | set[int]] = {}
    operation = str(report.get("operation") or "")
    submesh_reports = report.get("submeshes")
    if not isinstance(submesh_reports, list):
        return None
    for item in submesh_reports:
        if not isinstance(item, dict):
            continue
        submesh_index = _index(item.get("index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        raw_normals = item.get("normals")
        if isinstance(raw_normals, list):
            if len(raw_normals) != len(submesh.vertices):
                return None
            parsed_normals = [_vec3(value, fallback=0.0) for value in raw_normals]
        else:
            parsed_normals = _read_vec3_binary_report_payload(
                item.get("normals_binary"),
                expected_count=len(submesh.vertices),
            )
            if parsed_normals is None:
                continue
        parsed_changed_ordered = _changed_vertices_from_report_item(item, len(parsed_normals))
        has_native_changed_vertices = parsed_changed_ordered is not None
        parsed_changed = _changed_vertices_for_report(parsed_changed_ordered)
        before_normals = () if has_native_changed_vertices else tuple(_vec3(normal, fallback=0.0) for normal in submesh.normals or ())
        faces = item.get("faces")
        faces_binary = item.get("faces_binary")
        faces_changed = False
        if isinstance(faces, list):
            parsed_faces = _face_json(faces, len(submesh.vertices))
            if len(parsed_faces) != len(faces):
                return None
            next_faces = [tuple(face) for face in parsed_faces]
            submesh.faces = next_faces
            faces_changed = True
        elif isinstance(faces_binary, Mapping):
            parsed_faces = _read_face_binary_report_payload(
                faces_binary,
                expected_count=len(submesh.faces or ()),
                vertex_count=len(submesh.vertices),
            )
            if parsed_faces is None:
                return None
            next_faces = [tuple(face) for face in parsed_faces]
            submesh.faces = next_faces
            faces_changed = True
        submesh.normals = parsed_normals
        normals_changed = bool(parsed_changed) if has_native_changed_vertices else False
        if not has_native_changed_vertices:
            normals_changed = not _same_vec3_tuple(before_normals, tuple(parsed_normals))
        if faces_changed or normals_changed:
            affected.add(submesh_index)
        if has_native_changed_vertices:
            if parsed_changed:
                _merge_changed_vertices(
                    changed,
                    submesh_index,
                    parsed_changed,
                )
        elif normals_changed:
            _merge_changed_vertices(changed, submesh_index, range(len(parsed_normals)))
        if return_changed_vertices:
            preview_vertex_update_group = _native_preview_vertex_update_group(
                item.get("preview_vertex_update_group"),
                submesh_index,
            )
            if preview_vertex_update_group is not None:
                setattr(submesh, "cdmw_native_preview_vertex_update_group", preview_vertex_update_group)
            elif hasattr(submesh, "cdmw_native_preview_vertex_update_group"):
                delattr(submesh, "cdmw_native_preview_vertex_update_group")
        elif operation == "flip_normals" and hasattr(submesh, "cdmw_native_preview_vertex_update_group"):
            delattr(submesh, "cdmw_native_preview_vertex_update_group")
    return changed if return_changed_vertices else affected


def _apply_generate_tangents_report(mesh: ParsedMesh, report: Mapping[str, object]) -> set[int] | None:
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
        submesh = mesh.submeshes[submesh_index]
        if bool(item.get("clear_tangents")):
            had_tangents = bool(getattr(submesh, "tangents", None))
            submesh.tangents = []
            if hasattr(submesh, "tangent_signs"):
                setattr(submesh, "tangent_signs", [])
            if hasattr(submesh, "tangent_face_corner_report"):
                delattr(submesh, "tangent_face_corner_report")
            if had_tangents:
                affected.add(submesh_index)
            continue
        if not bool(item.get("vertex_storage_safe", True)):
            if _apply_native_tangent_split_result(submesh, item) is None:
                if _apply_face_corner_tangent_split(submesh, item) is None:
                    return None
            setattr(
                submesh,
                "tangent_face_corner_report",
                _tangent_face_corner_report(
                    item,
                    len(submesh.tangents),
                    vertex_storage_safe=True,
                    topology_split_applied=True,
                ),
            )
            affected.add(submesh_index)
            continue
        tangents = item.get("tangents")
        raw_tangents_binary = item.get("tangents_binary")
        if isinstance(raw_tangents_binary, Mapping):
            parsed_tangents = _read_vec3_binary_report_payload(raw_tangents_binary, expected_count=len(submesh.vertices))
            if parsed_tangents is None:
                return None
        elif isinstance(tangents, list):
            if len(tangents) != len(submesh.vertices):
                return None
            parsed_tangents = [_vec3(value, fallback=0.0) for value in tangents]
        else:
            continue
        parsed_changed_ordered = _changed_vertices_from_report_item(item, len(parsed_tangents))
        has_native_changed_vertices = parsed_changed_ordered is not None
        parsed_changed = _changed_vertices_for_report(parsed_changed_ordered)
        before = () if has_native_changed_vertices else tuple(_vec3(tangent, fallback=0.0) for tangent in tuple(getattr(submesh, "tangents", ()) or ()))
        submesh.tangents = parsed_tangents
        setattr(submesh, "tangent_face_corner_report", _tangent_face_corner_report(item, len(parsed_tangents)))
        if (has_native_changed_vertices and parsed_changed) or (
            not has_native_changed_vertices and not _same_vec3_tuple(before, tuple(parsed_tangents))
        ):
            affected.add(submesh_index)
    return affected


def _report_count(value: object) -> int | None:
    if not isinstance(value, Mapping):
        return None
    count = _index(value.get("count"))
    return count if count is not None and count >= 0 else None


def _apply_native_tangent_split_result(submesh: object, item: Mapping[str, object]) -> bool | None:
    if not bool(item.get("topology_split_applied")):
        return None
    vertex_count = _index(item.get("output_vertex_count"))
    if vertex_count is None:
        vertex_count = _report_count(item.get("vertices_binary"))
    face_count = _index(item.get("output_face_count"))
    if face_count is None:
        face_count = _report_count(item.get("faces_binary"))
    if vertex_count is None or face_count is None:
        return None
    vertices = _read_vec3_binary_report_payload(item.get("vertices_binary"), expected_count=vertex_count)
    faces = _read_face_binary_report_payload(item.get("faces_binary"), expected_count=face_count, vertex_count=vertex_count)
    uvs = _read_vec2_binary_report_payload(item.get("uvs_binary"), expected_count=vertex_count)
    normals = _read_vec3_binary_report_payload(item.get("normals_binary"), expected_count=vertex_count)
    tangents = _read_vec3_binary_report_payload(item.get("tangents_binary"), expected_count=vertex_count)
    tangent_signs = _read_f64_binary_report_payload(item.get("tangent_signs_binary"), expected_count=vertex_count)
    if vertices is None or faces is None or uvs is None or normals is None or tangents is None or tangent_signs is None:
        return None

    bone_indices: list[tuple[int, ...]] = []
    bone_weights: list[tuple[float, ...]] = []
    if (
        isinstance(item.get("bone_counts_binary"), Mapping)
        or isinstance(item.get("bone_indices_binary"), Mapping)
        or isinstance(item.get("bone_weights_binary"), Mapping)
    ):
        bone_payload = _read_bone_binary_report_payloads(
            item.get("bone_counts_binary"),
            item.get("bone_indices_binary"),
            item.get("bone_weights_binary"),
            expected_count=vertex_count,
        )
        if bone_payload is None:
            return None
        bone_indices, bone_weights = bone_payload

    source_vertex_map: list[int] = []
    source_vertex_offsets: list[int] = []
    if isinstance(item.get("source_vertex_map_binary"), Mapping):
        parsed_source_map = _read_i32_binary_report_payload(item.get("source_vertex_map_binary"), expected_count=vertex_count)
        if parsed_source_map is None:
            return None
        source_vertex_map = parsed_source_map
    if isinstance(item.get("source_vertex_offsets_binary"), Mapping):
        parsed_source_offsets = _read_i32_binary_report_payload(item.get("source_vertex_offsets_binary"), expected_count=vertex_count)
        if parsed_source_offsets is None:
            return None
        source_vertex_offsets = parsed_source_offsets

    submesh.vertices = vertices
    submesh.uvs = uvs
    submesh.normals = normals
    submesh.tangents = tangents
    submesh.faces = list(faces)
    submesh.bone_indices = bone_indices
    submesh.bone_weights = bone_weights
    submesh.source_vertex_map = source_vertex_map
    submesh.source_vertex_offsets = source_vertex_offsets
    submesh.vertex_count = len(vertices)
    submesh.face_count = len(faces)
    setattr(submesh, "tangent_signs", tangent_signs)
    return True


def _tangent_face_corner_report(
    item: Mapping[str, object],
    tangent_count: int,
    *,
    vertex_storage_safe: bool | None = None,
    topology_split_applied: bool = False,
) -> dict[str, object]:
    source_safe = bool(item.get("vertex_storage_safe", True))
    return {
        "backend": item.get("tangent_backend"),
        "face_corner_remap": item.get("face_corner_remap"),
        "vertex_storage_safe": source_safe if vertex_storage_safe is None else bool(vertex_storage_safe),
        "source_vertex_storage_safe": source_safe,
        "topology_split_applied": bool(topology_split_applied),
        "split_required_vertices": tuple(
            index
            for raw_index in item.get("split_required_vertices", [])
            for index in [_index(raw_index)]
            if index is not None and 0 <= index < max(0, tangent_count)
        ),
    }


def _apply_face_corner_tangent_split(submesh: object, item: Mapping[str, object]) -> bool | None:
    old_vertices = list(getattr(submesh, "vertices", ()) or ())
    old_faces = list(getattr(submesh, "faces", ()) or ())
    old_vertex_count = len(old_vertices)
    face_corners = _parsed_face_corner_tangents(item, old_faces, old_vertex_count)
    if face_corners is None:
        return None

    old_uvs = list(getattr(submesh, "uvs", ()) or ())
    old_normals = list(getattr(submesh, "normals", ()) or ())
    old_bone_indices = list(getattr(submesh, "bone_indices", ()) or ())
    old_bone_weights = list(getattr(submesh, "bone_weights", ()) or ())
    old_source_vertex_map = list(getattr(submesh, "source_vertex_map", ()) or ())
    old_source_vertex_offsets = list(getattr(submesh, "source_vertex_offsets", ()) or ())

    has_uvs = len(old_uvs) == old_vertex_count
    has_normals = len(old_normals) == old_vertex_count
    has_bone_indices = len(old_bone_indices) == old_vertex_count
    has_bone_weights = len(old_bone_weights) == old_vertex_count
    has_source_vertex_map = len(old_source_vertex_map) == old_vertex_count
    has_source_vertex_offsets = len(old_source_vertex_offsets) == old_vertex_count

    new_vertices: list[object] = []
    new_uvs: list[object] = []
    new_normals: list[object] = []
    new_tangents: list[Vec3] = []
    new_tangent_signs: list[float] = []
    new_bone_indices: list[object] = []
    new_bone_weights: list[object] = []
    new_source_vertex_map: list[int] = []
    new_source_vertex_offsets: list[int] = []
    new_faces: list[tuple[int, int, int]] = []
    corner_index_by_key: dict[tuple[int, Vec3, float], int] = {}

    for face_index in range(len(old_faces)):
        vertices, tangents, signs = face_corners.get(face_index, ((), (), ()))
        if len(vertices) != 3 or len(tangents) != 3 or len(signs) != 3:
            return None
        new_face: list[int] = []
        for old_index, tangent, sign in zip(vertices, tangents, signs):
            key = (old_index, tangent, sign)
            new_index = corner_index_by_key.get(key)
            if new_index is None:
                new_index = len(new_vertices)
                corner_index_by_key[key] = new_index
                new_vertices.append(old_vertices[old_index])
                new_uvs.append(old_uvs[old_index] if has_uvs else (0.0, 0.0))
                new_normals.append(old_normals[old_index] if has_normals else (0.0, 0.0, 1.0))
                new_tangents.append(tangent)
                new_tangent_signs.append(sign)
                if has_bone_indices:
                    new_bone_indices.append(old_bone_indices[old_index])
                if has_bone_weights:
                    new_bone_weights.append(old_bone_weights[old_index])
                if has_source_vertex_map:
                    new_source_vertex_map.append(int(old_source_vertex_map[old_index]))
                if has_source_vertex_offsets:
                    new_source_vertex_offsets.append(int(old_source_vertex_offsets[old_index]))
            new_face.append(new_index)
        new_faces.append((new_face[0], new_face[1], new_face[2]))

    submesh.vertices = new_vertices
    submesh.uvs = new_uvs
    submesh.normals = new_normals
    submesh.tangents = new_tangents
    submesh.faces = new_faces
    submesh.bone_indices = new_bone_indices
    submesh.bone_weights = new_bone_weights
    submesh.source_vertex_map = new_source_vertex_map
    submesh.source_vertex_offsets = new_source_vertex_offsets
    submesh.vertex_count = len(new_vertices)
    submesh.face_count = len(new_faces)
    setattr(submesh, "tangent_signs", new_tangent_signs)
    return True


def _parsed_face_corner_tangents(
    item: Mapping[str, object],
    old_faces: list[object],
    old_vertex_count: int,
) -> dict[int, tuple[tuple[int, int, int], tuple[Vec3, Vec3, Vec3], tuple[float, float, float]]] | None:
    raw_face_corners = item.get("face_corner_tangents")
    if not isinstance(raw_face_corners, list) or len(raw_face_corners) != len(old_faces):
        return None
    result: dict[int, tuple[tuple[int, int, int], tuple[Vec3, Vec3, Vec3], tuple[float, float, float]]] = {}
    for raw_item in raw_face_corners:
        if not isinstance(raw_item, Mapping):
            return None
        face_index = _index(raw_item.get("face_index"))
        if face_index is None or not 0 <= face_index < len(old_faces) or face_index in result:
            return None
        actual_face = _valid_face_tuple(old_faces[face_index], old_vertex_count)
        vertices = _valid_face_tuple(raw_item.get("vertices"), old_vertex_count)
        if actual_face is None or vertices is None or vertices != actual_face:
            return None
        raw_tangents = raw_item.get("tangents")
        raw_signs = raw_item.get("signs")
        if not isinstance(raw_tangents, list) or len(raw_tangents) != 3:
            return None
        signs_source = raw_signs if isinstance(raw_signs, list) and len(raw_signs) == 3 else [1.0, 1.0, 1.0]
        result[face_index] = (
            vertices,
            tuple(_vec3(value, fallback=0.0) for value in raw_tangents),  # type: ignore[assignment]
            tuple(1.0 if _finite_float(value, 1.0) >= 0.0 else -1.0 for value in signs_source),  # type: ignore[assignment]
        )
    return result if len(result) == len(old_faces) else None


def _valid_face_tuple(face: object, vertex_count: int) -> tuple[int, int, int] | None:
    if not isinstance(face, (tuple, list)) or len(face) < 3:
        return None
    a = _index(face[0])
    b = _index(face[1])
    c = _index(face[2])
    if a is None or b is None or c is None:
        return None
    if not (0 <= a < vertex_count and 0 <= b < vertex_count and 0 <= c < vertex_count):
        return None
    return a, b, c


def _apply_cleanup_report(mesh: ParsedMesh, report: Mapping[str, object]) -> set[int] | None:
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
        submesh = mesh.submeshes[submesh_index]
        old_vertex_count = len(submesh.vertices)
        raw_vertices_binary = item.get("vertices_binary")
        raw_faces_binary = item.get("faces_binary")
        raw_index_map_binary = item.get("index_map_binary")
        raw_normals_binary = item.get("normals_binary")
        raw_uvs_binary = item.get("uvs_binary")
        raw_tangents_binary = item.get("tangents_binary")
        raw_tangent_signs_binary = item.get("tangent_signs_binary")
        raw_bone_counts_binary = item.get("bone_counts_binary")
        raw_bone_indices_binary = item.get("bone_indices_binary")
        raw_bone_weights_binary = item.get("bone_weights_binary")
        raw_source_vertex_map_binary = item.get("source_vertex_map_binary")
        raw_source_vertex_offsets_binary = item.get("source_vertex_offsets_binary")
        vertices = item.get("vertices")
        faces = item.get("faces")
        raw_index_map = item.get("index_map")
        if isinstance(raw_vertices_binary, Mapping):
            vertex_count = _index(raw_vertices_binary.get("count"))
            if vertex_count is None or vertex_count < 0:
                return None
            parsed_vertices = _read_vec3_binary_report_payload(raw_vertices_binary, expected_count=vertex_count)
            if parsed_vertices is None:
                return None
        elif isinstance(vertices, list):
            parsed_vertices = [_vec3(value) for value in vertices]
        else:
            continue
        if isinstance(raw_faces_binary, Mapping):
            face_count = _index(raw_faces_binary.get("count"))
            if face_count is None or face_count < 0:
                return None
            parsed_faces = _read_face_binary_report_payload(raw_faces_binary, expected_count=face_count, vertex_count=len(parsed_vertices))
            if parsed_faces is None:
                return None
        elif isinstance(faces, list):
            parsed_faces = _face_json(faces, len(parsed_vertices))
        else:
            continue
        index_map: list[int] | None = None
        if isinstance(raw_index_map_binary, Mapping):
            index_map = _read_i32_binary_report_payload(raw_index_map_binary, expected_count=old_vertex_count)
            if index_map is None:
                return None
        elif isinstance(raw_index_map, list):
            index_map = []
            for value in raw_index_map:
                parsed_index = _index(value)
                index_map.append(parsed_index if parsed_index is not None else -1)
        if index_map is not None and len(index_map) != old_vertex_count:
            return None
        if index_map is not None and any(new_index < -1 or new_index >= len(parsed_vertices) for new_index in index_map):
            return None
        native_normals = (
            _read_vec3_binary_report_payload(raw_normals_binary, expected_count=len(parsed_vertices))
            if isinstance(raw_normals_binary, Mapping)
            else None
        )
        if isinstance(raw_normals_binary, Mapping) and native_normals is None:
            return None
        native_uvs = (
            _read_vec2_binary_report_payload(raw_uvs_binary, expected_count=len(parsed_vertices))
            if isinstance(raw_uvs_binary, Mapping)
            else None
        )
        if isinstance(raw_uvs_binary, Mapping) and native_uvs is None:
            return None
        native_tangents = (
            _read_vec3_binary_report_payload(raw_tangents_binary, expected_count=len(parsed_vertices))
            if isinstance(raw_tangents_binary, Mapping)
            else None
        )
        if isinstance(raw_tangents_binary, Mapping) and native_tangents is None:
            return None
        native_tangent_signs = (
            _read_f64_binary_report_payload(raw_tangent_signs_binary, expected_count=len(parsed_vertices))
            if isinstance(raw_tangent_signs_binary, Mapping)
            else None
        )
        if isinstance(raw_tangent_signs_binary, Mapping) and native_tangent_signs is None:
            return None
        native_bones = None
        if (
            isinstance(raw_bone_counts_binary, Mapping)
            and isinstance(raw_bone_indices_binary, Mapping)
            and isinstance(raw_bone_weights_binary, Mapping)
        ):
            native_bones = _read_bone_binary_report_payloads(
                raw_bone_counts_binary,
                raw_bone_indices_binary,
                raw_bone_weights_binary,
                expected_count=len(parsed_vertices),
            )
            if native_bones is None:
                return None
        native_source_vertex_map = (
            _read_i32_binary_report_payload(raw_source_vertex_map_binary, expected_count=len(parsed_vertices))
            if isinstance(raw_source_vertex_map_binary, Mapping)
            else None
        )
        if isinstance(raw_source_vertex_map_binary, Mapping) and native_source_vertex_map is None:
            return None
        native_source_vertex_offsets = (
            _read_i32_binary_report_payload(raw_source_vertex_offsets_binary, expected_count=len(parsed_vertices))
            if isinstance(raw_source_vertex_offsets_binary, Mapping)
            else None
        )
        if isinstance(raw_source_vertex_offsets_binary, Mapping) and native_source_vertex_offsets is None:
            return None
        if index_map is None:
            if native_normals is None:
                return None
            if len(submesh.uvs) == old_vertex_count and native_uvs is None:
                return None
            if len(getattr(submesh, "tangents", ()) or ()) == old_vertex_count and native_tangents is None:
                return None
            if len(getattr(submesh, "tangent_signs", ()) or ()) == old_vertex_count and native_tangent_signs is None:
                return None
            if (
                len(getattr(submesh, "bone_indices", ()) or ()) == old_vertex_count
                and len(getattr(submesh, "bone_weights", ()) or ()) == old_vertex_count
                and native_bones is None
            ):
                return None
            if len(getattr(submesh, "source_vertex_map", ()) or ()) == old_vertex_count and native_source_vertex_map is None:
                return None
            if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == old_vertex_count and native_source_vertex_offsets is None:
                return None
        submesh.vertices = parsed_vertices
        submesh.faces = [tuple(face) for face in parsed_faces]
        submesh.uvs = native_uvs if native_uvs is not None else (_remap_vertex_aligned_list(submesh.uvs, index_map) if index_map is not None else [])  # type: ignore[assignment]
        submesh.normals = native_normals if native_normals is not None else (_remap_vertex_aligned_list(submesh.normals, index_map) if index_map is not None else [])  # type: ignore[assignment]
        submesh.tangents = native_tangents if native_tangents is not None else (_remap_vertex_aligned_list(submesh.tangents, index_map) if index_map is not None else [])  # type: ignore[assignment]
        if native_tangent_signs is not None:
            setattr(submesh, "tangent_signs", native_tangent_signs)
        elif index_map is not None and getattr(submesh, "tangent_signs", None):
            setattr(submesh, "tangent_signs", _remap_vertex_aligned_list(getattr(submesh, "tangent_signs"), index_map))
        else:
            setattr(submesh, "tangent_signs", [])
        if native_bones is not None:
            submesh.bone_indices, submesh.bone_weights = native_bones  # type: ignore[assignment]
        elif index_map is not None:
            submesh.bone_indices = _remap_vertex_aligned_list(submesh.bone_indices, index_map)  # type: ignore[assignment]
            submesh.bone_weights = _remap_vertex_aligned_list(submesh.bone_weights, index_map)  # type: ignore[assignment]
        else:
            submesh.bone_indices = []
            submesh.bone_weights = []
        submesh.source_vertex_map = native_source_vertex_map if native_source_vertex_map is not None else (_remap_vertex_aligned_list(submesh.source_vertex_map, index_map) if index_map is not None else [])  # type: ignore[assignment]
        submesh.source_vertex_offsets = native_source_vertex_offsets if native_source_vertex_offsets is not None else (_remap_vertex_aligned_list(submesh.source_vertex_offsets, index_map) if index_map is not None else [])  # type: ignore[assignment]
        submesh.vertex_count = len(submesh.vertices)
        submesh.face_count = len(submesh.faces)
        if native_normals is None:
            recompute_submesh_normals(submesh)
        affected.add(submesh_index)
    return affected


def _apply_auto_uv_report(mesh: ParsedMesh, report: Mapping[str, object]) -> dict[int, Sequence[int] | set[int]] | None:
    changed: dict[int, Sequence[int] | set[int]] = {}
    submesh_reports = report.get("submeshes")
    if not isinstance(submesh_reports, list):
        return None
    for item in submesh_reports:
        if not isinstance(item, dict) or str(item.get("status") or "ok").lower() != "ok":
            continue
        submesh_index = _index(item.get("index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        raw_remap_binary = item.get("vertex_remap_binary")
        raw_vertices_binary = item.get("vertices_binary")
        raw_uvs_binary = item.get("uvs_binary")
        raw_faces_binary = item.get("faces_binary")
        raw_normals_binary = item.get("normals_binary")
        raw_tangents_binary = item.get("tangents_binary")
        raw_tangent_signs_binary = item.get("tangent_signs_binary")
        raw_bone_counts_binary = item.get("bone_counts_binary")
        raw_bone_indices_binary = item.get("bone_indices_binary")
        raw_bone_weights_binary = item.get("bone_weights_binary")
        raw_source_vertex_map_binary = item.get("source_vertex_map_binary")
        raw_source_vertex_offsets_binary = item.get("source_vertex_offsets_binary")
        raw_remap = item.get("vertex_remap")
        raw_uvs = item.get("uvs")
        raw_faces = item.get("faces")
        if isinstance(raw_remap_binary, Mapping):
            output_count = _index(raw_remap_binary.get("count"))
            if output_count is None:
                output_count = _index(item.get("output_vertex_count"))
            if output_count is None or output_count < 0:
                return None
            remap = _read_i32_binary_report_payload(raw_remap_binary, expected_count=output_count)
            if remap is None:
                return None
        elif isinstance(raw_remap, list):
            remap = []
            for value in raw_remap:
                old_index = _index(value)
                if old_index is None:
                    return None
                remap.append(old_index)
        else:
            continue
        if any(old_index < 0 or old_index >= len(submesh.vertices) for old_index in remap):
            return None
        if isinstance(raw_vertices_binary, Mapping):
            parsed_vertices = _read_vec3_binary_report_payload(raw_vertices_binary, expected_count=len(remap))
            if parsed_vertices is None:
                return None
        else:
            parsed_vertices = [submesh.vertices[old_index] for old_index in remap]
        if isinstance(raw_uvs_binary, Mapping):
            parsed_uvs = _read_vec2_binary_report_payload(raw_uvs_binary, expected_count=len(remap))
            if parsed_uvs is None:
                return None
        elif isinstance(raw_uvs, list):
            parsed_uvs = [_vec2(value) for value in raw_uvs]
        else:
            continue
        if len(parsed_uvs) != len(remap):
            return None
        if isinstance(raw_faces_binary, Mapping):
            face_count = _index(raw_faces_binary.get("count"))
            if face_count is None:
                face_count = _index(item.get("output_face_count"))
            if face_count is None or face_count < 0:
                return None
            parsed_faces = _read_face_binary_report_payload(raw_faces_binary, expected_count=face_count, vertex_count=len(parsed_uvs))
            if parsed_faces is None:
                return None
        elif isinstance(raw_faces, list):
            parsed_faces = _face_json(raw_faces, len(parsed_uvs))
            if len(parsed_faces) != len(raw_faces):
                return None
        else:
            continue

        native_normals = (
            _read_vec3_binary_report_payload(raw_normals_binary, expected_count=len(remap))
            if isinstance(raw_normals_binary, Mapping)
            else None
        )
        if isinstance(raw_normals_binary, Mapping) and native_normals is None:
            return None
        native_tangents = (
            _read_vec3_binary_report_payload(raw_tangents_binary, expected_count=len(remap))
            if isinstance(raw_tangents_binary, Mapping)
            else None
        )
        if isinstance(raw_tangents_binary, Mapping) and native_tangents is None:
            return None
        native_tangent_signs = (
            _read_f64_binary_report_payload(raw_tangent_signs_binary, expected_count=len(remap))
            if isinstance(raw_tangent_signs_binary, Mapping)
            else None
        )
        if isinstance(raw_tangent_signs_binary, Mapping) and native_tangent_signs is None:
            return None
        native_bones = None
        if (
            isinstance(raw_bone_counts_binary, Mapping)
            and isinstance(raw_bone_indices_binary, Mapping)
            and isinstance(raw_bone_weights_binary, Mapping)
        ):
            native_bones = _read_bone_binary_report_payloads(
                raw_bone_counts_binary,
                raw_bone_indices_binary,
                raw_bone_weights_binary,
                expected_count=len(remap),
            )
            if native_bones is None:
                return None
        native_source_vertex_map = (
            _read_i32_binary_report_payload(raw_source_vertex_map_binary, expected_count=len(remap))
            if isinstance(raw_source_vertex_map_binary, Mapping)
            else None
        )
        if isinstance(raw_source_vertex_map_binary, Mapping) and native_source_vertex_map is None:
            return None
        native_source_vertex_offsets = (
            _read_i32_binary_report_payload(raw_source_vertex_offsets_binary, expected_count=len(remap))
            if isinstance(raw_source_vertex_offsets_binary, Mapping)
            else None
        )
        if isinstance(raw_source_vertex_offsets_binary, Mapping) and native_source_vertex_offsets is None:
            return None

        parsed_changed_ordered = _changed_vertices_from_report_item(item, len(parsed_uvs))
        has_native_changed_vertices = parsed_changed_ordered is not None
        parsed_changed = _changed_vertices_for_report(parsed_changed_ordered)
        old_vertex_count = len(submesh.vertices)
        old_face_count = len(submesh.faces)
        old_uvs = () if has_native_changed_vertices else (
            tuple(_vec2(uv) for uv in submesh.uvs) if len(submesh.uvs) == old_vertex_count else ()
        )
        submesh.vertices = parsed_vertices
        submesh.uvs = parsed_uvs
        submesh.faces = [tuple(face) for face in parsed_faces]
        submesh.normals = native_normals if native_normals is not None else _copy_vertex_aligned_list(submesh.normals, remap)  # type: ignore[assignment]
        submesh.tangents = native_tangents if native_tangents is not None else _copy_vertex_aligned_list(submesh.tangents, remap)  # type: ignore[assignment]
        if native_tangent_signs is not None:
            setattr(submesh, "tangent_signs", native_tangent_signs)
        elif getattr(submesh, "tangent_signs", None):
            setattr(submesh, "tangent_signs", _copy_vertex_aligned_list(getattr(submesh, "tangent_signs"), remap))
        if native_bones is not None:
            submesh.bone_indices, submesh.bone_weights = native_bones  # type: ignore[assignment]
        else:
            submesh.bone_indices = _copy_vertex_aligned_list(submesh.bone_indices, remap)  # type: ignore[assignment]
            submesh.bone_weights = _copy_vertex_aligned_list(submesh.bone_weights, remap)  # type: ignore[assignment]
        submesh.source_vertex_map = native_source_vertex_map if native_source_vertex_map is not None else _copy_vertex_aligned_list(submesh.source_vertex_map, remap)  # type: ignore[assignment]
        submesh.source_vertex_offsets = native_source_vertex_offsets if native_source_vertex_offsets is not None else _copy_vertex_aligned_list(submesh.source_vertex_offsets, remap)  # type: ignore[assignment]
        if len(submesh.normals) != len(submesh.vertices):
            recompute_submesh_normals(submesh)
        submesh.vertex_count = len(submesh.vertices)
        submesh.face_count = len(submesh.faces)
        changed_vertices: Sequence[int] | set[int] = (
            parsed_changed_ordered if isinstance(parsed_changed_ordered, range) else parsed_changed
        ) if has_native_changed_vertices else ()
        if not has_native_changed_vertices and (
            submesh.vertex_count != old_vertex_count
            or submesh.face_count != old_face_count
            or tuple(parsed_uvs) != old_uvs
        ):
            changed_vertices = range(len(submesh.vertices))
        if changed_vertices:
            _merge_changed_vertices(changed, submesh_index, changed_vertices)
            setattr(
                submesh,
                "auto_uv_report",
                {
                    "unwrap_backend": item.get("unwrap_backend"),
                    "topology_changed": bool(item.get("topology_changed")),
                    "chart_count": _index(item.get("chart_count")) or 0,
                    "vertex_remap": tuple(remap),
                },
            )
    return changed


def _apply_uv_transform_report(mesh: ParsedMesh, report: Mapping[str, object]) -> dict[int, Sequence[int] | set[int]] | None:
    changed: dict[int, Sequence[int] | set[int]] = {}
    submesh_reports = report.get("submeshes")
    if not isinstance(submesh_reports, list):
        return None
    for item in submesh_reports:
        if not isinstance(item, dict):
            continue
        submesh_index = _index(item.get("index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        parsed_changed_ordered = _changed_vertices_from_report_item(item, len(submesh.vertices))
        if bool(item.get("clear_uvs")):
            if parsed_changed_ordered is not None and parsed_changed_ordered:
                submesh.uvs = []
                mesh.has_uvs = any(bool(getattr(candidate, "uvs", None)) for candidate in mesh.submeshes)
                _merge_changed_vertices(changed, submesh_index, parsed_changed_ordered)
            continue
        expected_uv_count = len(submesh.uvs)
        if expected_uv_count != len(submesh.vertices):
            expected_uv_count = len(submesh.vertices)
        raw_uvs_binary = item.get("uvs_binary")
        raw_uvs = item.get("uvs")
        if isinstance(raw_uvs_binary, Mapping):
            parsed_uvs = _read_vec2_binary_report_payload(raw_uvs_binary, expected_count=expected_uv_count)
            if parsed_uvs is None:
                return None
        elif isinstance(raw_uvs, list):
            if len(raw_uvs) != expected_uv_count:
                return None
            parsed_uvs = [_vec2(value) for value in raw_uvs]
        else:
            continue
        parsed_changed_ordered = _changed_vertices_from_report_item(item, len(parsed_uvs))
        if parsed_changed_ordered is None:
            continue
        if parsed_changed_ordered:
            submesh.uvs = parsed_uvs
            if len(parsed_uvs) == len(submesh.vertices) and parsed_uvs:
                mesh.has_uvs = True
            _merge_changed_vertices(
                changed,
                submesh_index,
                parsed_changed_ordered,
            )
    return changed


def _merge_changed_vertices(
    changed: dict[int, Sequence[int] | set[int]],
    submesh_index: int,
    indices: Sequence[int] | set[int],
) -> None:
    if not indices:
        return
    current = changed.get(submesh_index)
    if not current:
        changed[submesh_index] = indices
        return
    merged = {int(index) for index in current}
    merged.update(int(index) for index in indices)
    if merged:
        changed[submesh_index] = merged


def _native_job_kwargs(*, stop_event: threading.Event | None, timeout_seconds: float) -> dict[str, object]:
    kwargs: dict[str, object] = {"timeout_seconds": timeout_seconds}
    if stop_event is not None:
        kwargs["stop_event"] = stop_event
    return kwargs


def _run_native_mesh_core_service_job(
    binary: Path,
    command: str,
    payload: Mapping[str, object],
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float,
) -> dict[str, object] | None:
    if str(command or "").strip().lower() == "mesh-editor-session-json":
        inline_report = _run_native_mesh_core_service_inline_job(
            binary,
            command,
            payload,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if inline_report is not None:
            return inline_report
    job_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_service_"))
    job_path = job_root / "job.json"
    report_path = job_root / "report.json"
    try:
        job_path.write_text(json.dumps(dict(payload), separators=(",", ":"), allow_nan=False), encoding="utf-8")
        service_kwargs: dict[str, object] = {"timeout_seconds": max(0.5, float(timeout_seconds))}
        if stop_event is not None:
            service_kwargs["stop_event"] = stop_event
        _get_native_mesh_core_service(binary).run_job(
            command,
            job_path,
            report_path,
            **service_kwargs,
        )
        if not report_path.is_file():
            return None
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(report, dict) or str(report.get("status") or "").lower() != "ok":
            return None
        return report
    except RunCancelled:
        raise
    except Exception:
        shutdown_native_mesh_core_service()
        return None
    finally:
        shutil.rmtree(job_root, ignore_errors=True)


def _run_native_mesh_core_service_inline_job(
    binary: Path,
    command: str,
    payload: Mapping[str, object],
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float,
) -> dict[str, object] | None:
    try:
        response = _get_native_mesh_core_service(binary).run_inline_job(
            command,
            payload,
            timeout_seconds=max(0.5, float(timeout_seconds)),
            stop_event=stop_event,
        )
        report = response.get("inline_report")
        if not isinstance(report, dict) or str(report.get("status") or "").lower() != "ok":
            return None
        return report
    except RunCancelled:
        raise
    except Exception:
        shutdown_native_mesh_core_service()
        return None


def _run_native_mesh_core_job(
    binary: Path,
    command: str,
    payload: Mapping[str, object],
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float,
) -> dict[str, object] | None:
    job_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_"))
    job_path = job_root / "job.json"
    report_path = job_root / "report.json"
    try:
        job_path.write_text(json.dumps(dict(payload), separators=(",", ":"), allow_nan=False), encoding="utf-8")
        returncode = 0
        use_service = _native_mesh_core_service_enabled(stop_event=stop_event)
        if use_service:
            try:
                service_kwargs: dict[str, object] = {"timeout_seconds": max(0.5, float(timeout_seconds))}
                if stop_event is not None:
                    service_kwargs["stop_event"] = stop_event
                _get_native_mesh_core_service(binary).run_job(
                    command,
                    job_path,
                    report_path,
                    **service_kwargs,
                )
            except ProcessTimeoutExpired:
                raise
            except RunCancelled:
                raise
            except Exception:
                shutdown_native_mesh_core_service()
                returncode, _stdout, _stderr = run_process_with_cancellation(
                    [str(binary), command, str(job_path), str(report_path)],
                    stop_event=stop_event,
                    timeout_seconds=max(0.5, float(timeout_seconds)),
                )
        else:
            returncode, _stdout, _stderr = run_process_with_cancellation(
                [str(binary), command, str(job_path), str(report_path)],
                stop_event=stop_event,
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
    except RunCancelled:
        raise
    except Exception:
        return None
    finally:
        shutil.rmtree(job_root, ignore_errors=True)


atexit.register(shutdown_native_mesh_core_service)
atexit.register(_cleanup_native_preview_delta_paths)


__all__ = [
    "NATIVE_MESH_CORE_BACKEND_ID",
    "NATIVE_MESH_CORE_BINARY_NAME",
    "apply_native_mesh_auto_uv",
    "apply_native_mesh_affine_transform_submeshes",
    "apply_native_mesh_editor_session",
    "apply_native_mesh_bridge",
    "apply_native_mesh_brush",
    "apply_native_mesh_brush_binary_selection",
    "apply_native_mesh_brush_selection",
    "apply_native_mesh_compact_orphans",
    "apply_native_mesh_copy_normals",
    "apply_native_mesh_delete",
    "apply_native_mesh_dissolve",
    "apply_native_mesh_duplicate",
    "apply_native_mesh_edge_split",
    "apply_native_mesh_extrude",
    "apply_native_mesh_fill",
    "apply_native_mesh_fill_holes",
    "apply_native_mesh_fix_winding",
    "apply_native_mesh_generate_tangents",
    "apply_native_mesh_flip_normals",
    "apply_native_mesh_inset",
    "apply_native_mesh_loop_cut",
    "apply_native_mesh_merge",
    "apply_native_mesh_mirror",
    "apply_native_morph_slider_values",
    "apply_native_mesh_pose_preview",
    "apply_native_mesh_recalculate_normals",
    "apply_native_mesh_remove_doubles",
    "apply_native_mesh_selection",
    "apply_native_mesh_separate",
    "apply_native_mesh_sharpen_normals",
    "apply_native_mesh_skin_weights",
    "apply_native_mesh_sparse_vertex_restore",
    "apply_native_mesh_split",
    "apply_native_mesh_subdivide",
    "apply_native_mesh_transform",
    "apply_native_mesh_transform_binary_selection",
    "apply_native_mesh_transform_selection",
    "apply_native_mesh_triangulate_display",
    "apply_native_mesh_uv_atlas_submesh",
    "apply_native_mesh_uv_transform",
    "apply_native_mesh_uv_transform_submeshes",
    "apply_native_mesh_weld",
    "apply_native_mesh_weighted_normals",
    "build_native_preview_model_in_original_frame",
    "build_native_fbx_geometry_arrays",
    "build_native_mesh_preview_triangle_groups",
    "build_native_mesh_preview_vertex_update_groups",
    "build_native_morph_post_edit_deltas",
    "build_native_morph_target_delta",
    "build_native_region_volume_delta",
    "build_native_static_donor_indices",
    "build_native_mesh_selection_groups",
    "close_native_mesh_editor_session",
    "decimate_native_mesh_preview_submeshes",
    "default_native_mesh_core_path",
    "dispose_native_mesh_sparse_vertex_snapshot",
    "dispose_native_mesh_submesh_snapshot",
    "export_native_fbx",
    "export_native_mesh_editor_session_to_mesh",
    "export_native_mesh_editor_session_snapshot",
    "export_native_obj",
    "find_native_mesh_core_binary",
    "invalidate_native_mesh_session_submeshes",
    "merge_native_mesh_submeshes",
    "native_mesh_auto_uv_report",
    "native_mesh_core_available",
    "native_mesh_editor_source_normals_payload",
    "native_mesh_editor_session_command",
    "native_mesh_editor_session_preview_triangle_groups",
    "native_mesh_editor_session_preview_vertex_update_groups",
    "native_mesh_editor_session_selection_from_report",
    "native_mesh_editor_session_selection_groups_from_report",
    "native_mesh_optimization_report",
    "native_mesh_history_delta_positions",
    "native_scene_import_report",
    "prune_native_mesh_selection",
    "restore_native_mesh_submeshes_from_mesh",
    "restore_native_mesh_submesh_snapshot",
    "open_native_mesh_editor_session",
    "redo_native_mesh_editor_session",
    "select_native_mesh_uv_vertices",
    "select_native_mesh_editor_session",
    "snapshot_native_mesh_submeshes",
    "snapshot_native_mesh_sparse_vertex_positions",
    "summarize_native_mesh_selection_bounds",
    "summarize_native_mesh_editor_session",
    "summarize_native_mesh_submesh_metadata",
    "summarize_native_mesh_uvs",
    "transfer_native_mesh_skin_weights_from_source",
    "undo_native_mesh_editor_session",
    "write_native_pose_preview_geometry_blob",
    "write_native_preview_geometry_blob",
    "write_native_preview_identity_blob",
    "write_native_obj_roundtrip_manifest",
]
