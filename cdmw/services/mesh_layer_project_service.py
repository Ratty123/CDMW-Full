"""Atomic native-binary persistence for Mesh Editor geometry layers."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import uuid4

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.modding.mesh_native_core import (
    _mesh_snapshot_metadata,
    _native_submesh_snapshot_item,
    export_native_mesh_editor_session_snapshot,
    restore_native_mesh_submesh_snapshot,
)
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services.atomic_file_service import atomic_write_text


MESH_LAYER_PROJECT_FORMAT = "mesh_layer_project_v1"
MESH_LAYER_GENERATION_FORMAT = "mesh_layer_generation_v1"

_BINARY_OUTPUT_KEYS = (
    ("vertices_output_path", "vertices"),
    ("faces_output_path", "faces"),
    ("source_face_indices_output_path", "source-faces"),
    ("normals_output_path", "normals"),
    ("uvs_output_path", "uvs"),
    ("tangents_output_path", "tangents"),
    ("tangent_signs_output_path", "tangent-signs"),
    ("bone_counts_output_path", "bone-counts"),
    ("bone_indices_output_path", "bone-indices"),
    ("bone_weights_output_path", "bone-weights"),
    ("source_vertex_map_output_path", "source-vertex-map"),
    ("source_vertex_offsets_output_path", "source-vertex-offsets"),
)


def discover_mesh_layer_project_context(mesh: ParsedMesh) -> dict[str, object]:
    """Read compatible Modify Original v1 metadata beside an imported clone."""

    source_path = Path(str(getattr(mesh, "path", "") or "")).expanduser()
    manifest_path = source_path.parent / "modify_original_workspace.json"
    if not manifest_path.is_file():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, Mapping) or payload.get("format") != "cdmw_modify_original_workspace_v1":
        return {}
    source_hash = str(payload.get("source_asset_sha256") or "").strip().lower()
    raw_project = str(payload.get("mesh_layer_project") or "").strip()
    project_path = (
        Path(raw_project).expanduser()
        if raw_project
        else manifest_path.parent / "mesh_layers" / "mesh_layer_project.json"
    )
    if not project_path.is_absolute():
        project_path = manifest_path.parent / project_path
    return {
        "manifest_path": manifest_path.resolve(),
        "project_path": project_path.resolve(),
        "source_asset_sha256": source_hash,
        "workspace_mode": str(payload.get("workspace_mode") or ""),
    }


def save_mesh_layer_project(
    *,
    session_id: str,
    mesh: ParsedMesh,
    project_path: Path,
    source_asset_sha256: str,
    layers: Sequence[Mapping[str, object]],
    active_layer_id: str,
    copy_counter: int,
    mesh_revision: int,
    layer_revision: int,
    object_transform: Mapping[str, object] | None = None,
    workspace_manifest_path: Path | None = None,
    promote_persistent_draft: bool = False,
    stop_event: threading.Event | None = None,
) -> dict[str, object]:
    """Write one complete generation, then atomically point the project at it."""

    stop = stop_event or threading.Event()
    source_hash = str(source_asset_sha256 or "").strip().lower()
    if len(source_hash) != 64:
        raise ValueError("Mesh layer project requires the exact source asset SHA-256")
    target = Path(project_path).expanduser().resolve()
    project_root = target.parent
    project_root.mkdir(parents=True, exist_ok=True)
    generation_name = f"generation-{time.time_ns()}-{uuid4().hex[:8]}"
    generation_dir = project_root / generation_name
    generation_dir.mkdir(parents=False, exist_ok=False)

    raise_if_cancelled(stop, "Mesh layer autosave cancelled.")
    summary = export_native_mesh_editor_session_snapshot(
        session_id,
        stop_event=stop,
        timeout_seconds=30.0,
    )
    raw_summary_items = summary.get("submeshes") if isinstance(summary, Mapping) else None
    if not isinstance(raw_summary_items, list):
        raise RuntimeError("Native Mesh Editor did not return a snapshot summary")
    summary_by_index: dict[int, Mapping[str, object]] = {}
    requests: list[dict[str, object]] = []
    for raw_item in raw_summary_items:
        if not isinstance(raw_item, Mapping):
            raise RuntimeError("Native Mesh Editor returned malformed snapshot metadata")
        index = _non_negative_int(raw_item.get("index"))
        if index is None:
            raise RuntimeError("Native Mesh Editor snapshot omitted a submesh index")
        summary_by_index[index] = raw_item
        request: dict[str, object] = {"index": index}
        for key, suffix in _BINARY_OUTPUT_KEYS:
            request[key] = str(generation_dir / f"submesh-{index:05d}-{suffix}.bin")
        requests.append(request)
    raise_if_cancelled(stop, "Mesh layer autosave cancelled.")
    report = export_native_mesh_editor_session_snapshot(
        session_id,
        requests,
        stop_event=stop,
        timeout_seconds=60.0,
    )
    raw_items = report.get("submeshes") if isinstance(report, Mapping) else None
    if not isinstance(raw_items, list) or len(raw_items) != len(summary_by_index):
        raise RuntimeError("Native Mesh Editor returned an incomplete snapshot generation")

    snapshot_items: list[dict[str, object]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            raise RuntimeError("Native Mesh Editor returned malformed snapshot payloads")
        index = _non_negative_int(raw_item.get("index"))
        summary_item = summary_by_index.get(index if index is not None else -1)
        if index is None or summary_item is None:
            raise RuntimeError("Native Mesh Editor snapshot payload did not match its summary")
        vertex_count = _non_negative_int(summary_item.get("vertex_count"))
        face_count = _non_negative_int(summary_item.get("face_count"))
        if vertex_count is None or face_count is None:
            raise RuntimeError("Native Mesh Editor snapshot counts were missing")
        metadata: dict[str, object] = {
            "name": str(summary_item.get("name") or ""),
            "material": str(summary_item.get("material") or ""),
            "texture": str(summary_item.get("texture") or ""),
        }
        if isinstance(summary_item.get("extra_attrs"), Mapping):
            metadata["extra_attrs"] = dict(summary_item["extra_attrs"])
        snapshot_item = _native_submesh_snapshot_item(
            raw_item,
            metadata=metadata,
            expected_vertices=vertex_count,
            expected_faces=face_count,
        )
        if snapshot_item is None:
            raise RuntimeError(f"Native Mesh Editor snapshot payload failed validation for submesh {index}")
        snapshot_items.append(snapshot_item)

    persisted_snapshot = _persisted_snapshot_payload(
        {
            "kind": "native_submesh_snapshot",
            "mesh": _mesh_snapshot_metadata(mesh),
            "submeshes": sorted(snapshot_items, key=lambda item: int(item["index"])),
        },
        project_root,
        stop,
    )
    generation_payload = {
        "format": MESH_LAYER_GENERATION_FORMAT,
        "source_asset_sha256": source_hash,
        "created_at": time.time(),
        "mesh_revision": int(mesh_revision),
        "layer_revision": int(layer_revision),
        "active_layer_id": str(active_layer_id or "base"),
        "copy_counter": max(0, int(copy_counter)),
        "layers": [dict(layer) for layer in layers],
        "object_transform": dict(object_transform or {}),
        "snapshot": persisted_snapshot,
    }
    generation_manifest = generation_dir / "generation.json"
    atomic_write_text(generation_manifest, json.dumps(generation_payload, indent=2, sort_keys=True))
    generation_sha256 = _sha256_file(generation_manifest)

    previous_generation = ""
    previous_generation_manifest_sha256 = ""
    if target.is_file():
        try:
            previous = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(previous, Mapping) and previous.get("format") == MESH_LAYER_PROJECT_FORMAT:
                previous_generation = str(previous.get("current_generation") or "")
                previous_generation_manifest_sha256 = str(
                    previous.get("current_generation_manifest_sha256") or ""
                ).strip().lower()
        except (OSError, ValueError):
            previous_generation = ""
            previous_generation_manifest_sha256 = ""
    descriptor = {
        "format": MESH_LAYER_PROJECT_FORMAT,
        "source_asset_sha256": source_hash,
        "current_generation": generation_name,
        "current_generation_manifest_sha256": generation_sha256,
        "previous_generation": previous_generation,
        "previous_generation_manifest_sha256": previous_generation_manifest_sha256,
        "saved_at": time.time(),
    }
    raise_if_cancelled(stop, "Mesh layer autosave cancelled.")
    atomic_write_text(target, json.dumps(descriptor, indent=2, sort_keys=True))
    if workspace_manifest_path is not None:
        _update_modify_original_manifest(
            workspace_manifest_path,
            project_path=target,
            source_asset_sha256=source_hash,
            promote_persistent_draft=promote_persistent_draft,
        )
    return descriptor


def load_mesh_layer_project(
    mesh: ParsedMesh,
    project_path: Path,
    *,
    expected_source_asset_sha256: str,
    stop_event: threading.Event | None = None,
) -> dict[str, object] | None:
    """Restore the newest valid exact-fingerprint generation, then its fallback."""

    stop = stop_event or threading.Event()
    target = Path(project_path).expanduser().resolve()
    if not target.is_file():
        return None
    descriptor = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(descriptor, Mapping) or descriptor.get("format") != MESH_LAYER_PROJECT_FORMAT:
        raise ValueError("Unsupported Mesh Editor layer project descriptor")
    expected_hash = str(expected_source_asset_sha256 or "").strip().lower()
    stored_hash = str(descriptor.get("source_asset_sha256") or "").strip().lower()
    if not expected_hash or stored_hash != expected_hash:
        raise ValueError("Mesh Editor layer project source fingerprint does not match this asset")
    candidates = (
        (
            str(descriptor.get("current_generation") or ""),
            str(descriptor.get("current_generation_manifest_sha256") or "").strip().lower(),
        ),
        (
            str(descriptor.get("previous_generation") or ""),
            str(descriptor.get("previous_generation_manifest_sha256") or "").strip().lower(),
        ),
    )
    failures: list[str] = []
    seen: set[str] = set()
    for generation_name, expected_manifest_sha256 in candidates:
        if not generation_name or generation_name in seen:
            continue
        seen.add(generation_name)
        raise_if_cancelled(stop, "Mesh layer project load cancelled.")
        try:
            payload = _load_generation(
                target.parent,
                generation_name,
                stored_hash,
                expected_manifest_sha256=expected_manifest_sha256,
            )
            snapshot = payload.get("snapshot")
            if not isinstance(snapshot, Mapping) or not restore_native_mesh_submesh_snapshot(
                mesh,
                snapshot,
                stop_event=stop,
                timeout_seconds=30.0,
            ):
                raise RuntimeError("native snapshot restore failed")
            return {**dict(payload), "loaded_generation": generation_name}
        except (OSError, RuntimeError, ValueError) as exc:
            failures.append(f"{generation_name}: {exc}")
    raise RuntimeError("No valid Mesh Editor layer-project generation: " + "; ".join(failures))


def _load_generation(
    project_root: Path,
    generation_name: str,
    source_hash: str,
    *,
    expected_manifest_sha256: str = "",
) -> dict[str, object]:
    generation_dir = (project_root / generation_name).resolve()
    if project_root.resolve() not in generation_dir.parents:
        raise ValueError("Layer generation path escapes the project")
    manifest_path = generation_dir / "generation.json"
    if expected_manifest_sha256 and _sha256_file(manifest_path) != expected_manifest_sha256:
        raise ValueError("layer generation manifest checksum mismatch")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or payload.get("format") != MESH_LAYER_GENERATION_FORMAT:
        raise ValueError("unsupported layer generation")
    if str(payload.get("source_asset_sha256") or "").strip().lower() != source_hash:
        raise ValueError("layer generation fingerprint mismatch")
    restored = copy.deepcopy(dict(payload))
    snapshot = restored.get("snapshot")
    if not isinstance(snapshot, Mapping):
        raise ValueError("layer generation omitted its native snapshot")
    restored["snapshot"] = _resolved_snapshot_payload(snapshot, project_root)
    return restored


def _persisted_snapshot_payload(
    snapshot: Mapping[str, object],
    project_root: Path,
    stop_event: threading.Event,
) -> dict[str, object]:
    result = copy.deepcopy(dict(snapshot))
    for descriptor in _binary_descriptors(result):
        raise_if_cancelled(stop_event, "Mesh layer autosave cancelled.")
        path = Path(str(descriptor.get("path") or "")).resolve()
        if not path.is_file() or project_root.resolve() not in path.parents:
            raise RuntimeError(f"Mesh layer snapshot blob is missing or outside the project: {path}")
        descriptor["path"] = path.relative_to(project_root.resolve()).as_posix()
        descriptor["size"] = path.stat().st_size
        descriptor["sha256"] = _sha256_file(path)
    return result


def _resolved_snapshot_payload(snapshot: Mapping[str, object], project_root: Path) -> dict[str, object]:
    result = copy.deepcopy(dict(snapshot))
    for descriptor in _binary_descriptors(result):
        relative = Path(str(descriptor.get("path") or ""))
        path = (project_root / relative).resolve()
        if project_root.resolve() not in path.parents or not path.is_file():
            raise RuntimeError(f"Mesh layer snapshot blob is unavailable: {relative}")
        expected_size = _non_negative_int(descriptor.get("size"))
        expected_hash = str(descriptor.get("sha256") or "").strip().lower()
        if expected_size is None or path.stat().st_size != expected_size or _sha256_file(path) != expected_hash:
            raise RuntimeError(f"Mesh layer snapshot blob checksum failed: {relative}")
        descriptor["path"] = str(path)
    return result


def _binary_descriptors(value: object):
    if isinstance(value, dict):
        if "path" in value and "count" in value and "type" in value:
            yield value
        for child in value.values():
            yield from _binary_descriptors(child)
    elif isinstance(value, list):
        for child in value:
            yield from _binary_descriptors(child)


def _update_modify_original_manifest(
    manifest_path: Path,
    *,
    project_path: Path,
    source_asset_sha256: str,
    promote_persistent_draft: bool,
) -> None:
    target = Path(manifest_path).expanduser().resolve()
    if not target.is_file():
        return
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or payload.get("format") != "cdmw_modify_original_workspace_v1":
        return
    updated = dict(payload)
    updated["mesh_layer_project"] = str(project_path)
    updated["source_asset_sha256"] = source_asset_sha256
    updated["updated_at"] = time.time()
    if promote_persistent_draft and str(updated.get("workspace_mode") or "") == "internal_app_session":
        updated["workspace_mode"] = "persistent_app_draft"
    atomic_write_text(target, json.dumps(updated, indent=2, sort_keys=True))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _non_negative_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


__all__ = [
    "MESH_LAYER_GENERATION_FORMAT",
    "MESH_LAYER_PROJECT_FORMAT",
    "discover_mesh_layer_project_context",
    "load_mesh_layer_project",
    "save_mesh_layer_project",
]
