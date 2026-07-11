from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Mapping

from cdmw.modding.mesh_native_core_payload_helpers import _index
from cdmw.modding.mesh_native_payloads import _contiguous_i32_range


def _facade_attr(name: str):
    return getattr(import_module("cdmw.modding.mesh_native_core"), name)


def _write_edge_binary_payload(path: Path, values: object) -> dict[str, object]:
    return _facade_attr("_write_edge_binary_payload")(path, values)


def _write_int_binary_payload(path: Path, values: object) -> dict[str, object]:
    return _facade_attr("_write_int_binary_payload")(path, values)


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
