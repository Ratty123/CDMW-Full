from __future__ import annotations

from array import array
import math
from pathlib import Path
import struct
from typing import Iterable, Mapping

from cdmw.modding.mesh_native_core_constants import Face, Vec2, Vec3
from cdmw.modding.mesh_native_core_payload_helpers import _finite_float, _index, _valid_face_triplet


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


def _write_edge_binary_payload(path: Path, values: Sequence[tuple[int, int]]) -> dict[str, object]:
    data = array("i")
    if data.itemsize != 4:
        raise RuntimeError("native edge sidecar requires 32-bit array('i')")
    for left, right in values:
        data.extend((int(left), int(right)))
    with path.open("wb") as handle:
        data.tofile(handle)
    return {"path": str(path), "count": len(values), "components": 2, "type": "i32"}
