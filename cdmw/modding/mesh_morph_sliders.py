"""Morph-target slider profiles for topology-preserving mesh edits."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from cdmw.core.atomic_file import atomic_write_text

from .mesh_deformer import build_vertex_adjacency, clone_mesh_for_editing, recompute_mesh_normals
from .mesh_parser import ParsedMesh, _compute_smooth_normals
from .scene_importer import import_scene_mesh, refresh_parsed_mesh_totals


MESH_MORPH_SLIDER_PROFILE_FORMAT = "cdmw.mesh_morph_slider_profile.v1"
MESH_MORPH_TARGET_EXTENSIONS = {".obj", ".pac", ".pam", ".pamlod"}
MESH_MORPH_SLIDER_TYPE_MORPH_TARGET = "morph_target"
MESH_MORPH_SLIDER_TYPE_REGION_VOLUME = "region_volume"
Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class MeshMorphSliderSpec:
    slider_id: str
    label: str
    target_path: str = ""
    slider_type: str = MESH_MORPH_SLIDER_TYPE_MORPH_TARGET
    region_path: str = ""
    min_percent: float = -100.0
    max_percent: float = 100.0
    default_percent: float = 0.0


@dataclass(frozen=True)
class MeshMorphSliderProfile:
    name: str
    root_path: Path
    base_virtual_path: str
    base_basename: str
    topology_signature: Mapping[str, object]
    sliders: tuple[MeshMorphSliderSpec, ...] = ()
    format: str = MESH_MORPH_SLIDER_PROFILE_FORMAT


@dataclass(frozen=True)
class MeshMorphSliderDelta:
    slider_id: str
    label: str
    deltas: tuple[tuple[Vec3, ...], ...]
    min_percent: float = -100.0
    max_percent: float = 100.0
    default_percent: float = 0.0
    slider_type: str = MESH_MORPH_SLIDER_TYPE_MORPH_TARGET


def _normalize_virtual_path(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


def _submesh_identity(submesh: object) -> str:
    return str(
        getattr(submesh, "name", "")
        or getattr(submesh, "material", "")
        or ""
    ).strip()


def _normalized_submesh_identity(submesh: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _submesh_identity(submesh).lower()).strip("_")


def _topology_faces(submesh: object) -> tuple[tuple[int, int, int], ...]:
    faces: list[tuple[int, int, int]] = []
    for raw_face in getattr(submesh, "faces", ()) or ():
        if len(raw_face) < 3:
            continue
        faces.append((int(raw_face[0]), int(raw_face[1]), int(raw_face[2])))
    return tuple(faces)


def _topology_signature_payload(mesh: ParsedMesh) -> dict[str, object]:
    submeshes = []
    for submesh in getattr(mesh, "submeshes", ()) or ():
        faces = _topology_faces(submesh)
        submeshes.append(
            {
                "name": str(getattr(submesh, "name", "") or ""),
                "material": str(getattr(submesh, "material", "") or ""),
                "vertex_count": len(getattr(submesh, "vertices", ()) or ()),
                "face_count": len(faces),
                "faces": [list(face) for face in faces],
            }
        )
    return {
        "submesh_count": len(submeshes),
        "submeshes": submeshes,
    }


def _signature_matches(base_signature: Mapping[str, object], profile_signature: Mapping[str, object]) -> bool:
    return json.dumps(base_signature, sort_keys=True, separators=(",", ":")) == json.dumps(
        profile_signature,
        sort_keys=True,
        separators=(",", ":"),
    )


def validate_morph_target(base_mesh: ParsedMesh, target_mesh: ParsedMesh) -> None:
    """Raise ValueError if a morph target cannot be blended with base_mesh."""

    base_submeshes = getattr(base_mesh, "submeshes", ()) or ()
    target_submeshes = getattr(target_mesh, "submeshes", ()) or ()
    issues: list[str] = []
    if len(base_submeshes) != len(target_submeshes):
        issues.append(f"submesh count mismatch: base {len(base_submeshes)}, target {len(target_submeshes)}")

    for submesh_index, (base_submesh, target_submesh) in enumerate(zip(base_submeshes, target_submeshes)):
        base_name = _normalized_submesh_identity(base_submesh)
        target_name = _normalized_submesh_identity(target_submesh)
        if base_name and target_name and base_name != target_name:
            issues.append(
                f"submesh {submesh_index} name mismatch: base {_submesh_identity(base_submesh)!r}, "
                f"target {_submesh_identity(target_submesh)!r}"
            )
        base_vertices = getattr(base_submesh, "vertices", ()) or ()
        target_vertices = getattr(target_submesh, "vertices", ()) or ()
        if len(base_vertices) != len(target_vertices):
            issues.append(
                f"submesh {submesh_index} vertex count mismatch: base {len(base_vertices)}, target {len(target_vertices)}"
            )
        base_faces = _topology_faces(base_submesh)
        target_faces = _topology_faces(target_submesh)
        if len(base_faces) != len(target_faces):
            issues.append(
                f"submesh {submesh_index} face count mismatch: base {len(base_faces)}, target {len(target_faces)}"
            )
        elif base_faces != target_faces:
            issues.append(f"submesh {submesh_index} face topology mismatch")

    if issues:
        raise ValueError("Incompatible morph target: " + "; ".join(issues))


def _morph_target_basic_identity_compatible(base_mesh: ParsedMesh, target_mesh: ParsedMesh) -> bool:
    base_submeshes = getattr(base_mesh, "submeshes", ()) or ()
    target_submeshes = getattr(target_mesh, "submeshes", ()) or ()
    if len(base_submeshes) != len(target_submeshes):
        return False
    for base_submesh, target_submesh in zip(base_submeshes, target_submeshes):
        base_name = _normalized_submesh_identity(base_submesh)
        target_name = _normalized_submesh_identity(target_submesh)
        if base_name and target_name and base_name != target_name:
            return False
    return True


def _build_native_morph_delta(base_mesh: ParsedMesh, target_mesh: ParsedMesh) -> tuple[tuple[Vec3, ...], ...] | None:
    if not _morph_target_basic_identity_compatible(base_mesh, target_mesh):
        return None
    try:
        from .mesh_native_core import build_native_morph_target_delta
    except Exception:
        return None
    return build_native_morph_target_delta(base_mesh, target_mesh)


def _record_native_morph_delta_fallback(base_mesh: ParsedMesh) -> None:
    try:
        from .mesh_native_core import native_mesh_core_available, record_native_mesh_core_fallback
    except Exception:
        return
    if not native_mesh_core_available() or os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return
    record_native_mesh_core_fallback(
        "morph_target_delta",
        "native_result_unavailable",
        vertices=sum(len(submesh.vertices or ()) for submesh in base_mesh.submeshes),
        faces=sum(len(submesh.faces or ()) for submesh in base_mesh.submeshes),
    )


def _allow_python_morph_fallback(mesh: ParsedMesh, operation: str) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return True
    try:
        from .mesh_native_core import native_mesh_core_available, record_native_mesh_core_fallback
    except Exception:
        return True
    if not native_mesh_core_available():
        return True
    vertex_count = _mesh_count_hint(mesh, "total_vertices")
    face_count = _mesh_count_hint(mesh, "total_faces")
    record_native_mesh_core_fallback(
        f"{operation}.blocked",
        "Python morph fallback blocked while native mesh core is available",
        vertex_count=vertex_count,
        face_count=face_count,
    )
    return False


def _mesh_count_hint(mesh: ParsedMesh, attr: str) -> int:
    try:
        count = int(getattr(mesh, attr, 0) or 0)
    except (TypeError, ValueError, OverflowError):
        count = 0
    if count > 0:
        return count
    source = "vertices" if attr == "total_vertices" else "faces"
    return sum(len(getattr(submesh, source, ()) or ()) for submesh in getattr(mesh, "submeshes", ()) or ())


def build_morph_delta(
    base_mesh: ParsedMesh,
    target_mesh: ParsedMesh,
    slider_id: str,
    *,
    label: str = "",
    min_percent: float = -100.0,
    max_percent: float = 100.0,
    default_percent: float = 0.0,
) -> MeshMorphSliderDelta:
    native_deltas = _build_native_morph_delta(base_mesh, target_mesh)
    delta_submeshes: list[tuple[Vec3, ...]] = []
    if native_deltas is not None:
        delta_submeshes = list(native_deltas)
    else:
        if not _allow_python_morph_fallback(base_mesh, "morph_target_delta"):
            raise RuntimeError("native morph target delta failed and Python morph fallback was blocked")
        validate_morph_target(base_mesh, target_mesh)
        _record_native_morph_delta_fallback(base_mesh)
        for base_submesh, target_submesh in zip(base_mesh.submeshes, target_mesh.submeshes):
            submesh_deltas: list[Vec3] = []
            for base_vertex, target_vertex in zip(base_submesh.vertices, target_submesh.vertices):
                submesh_deltas.append(
                    (
                        float(target_vertex[0]) - float(base_vertex[0]),
                        float(target_vertex[1]) - float(base_vertex[1]),
                        float(target_vertex[2]) - float(base_vertex[2]),
                    )
                )
            delta_submeshes.append(tuple(submesh_deltas))
    normalized_id = _safe_slider_id(slider_id)
    return MeshMorphSliderDelta(
        slider_id=normalized_id,
        label=label.strip() or _prettify_slider_label(normalized_id),
        deltas=tuple(delta_submeshes),
        min_percent=float(min_percent),
        max_percent=float(max_percent),
        default_percent=float(default_percent),
        slider_type=MESH_MORPH_SLIDER_TYPE_MORPH_TARGET,
    )


def _vec3(value: Sequence[object], fallback: Vec3 = (0.0, 0.0, 0.0)) -> Vec3:
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except Exception:
        return fallback


def _vec_length(value: Vec3) -> float:
    return math.sqrt(value[0] * value[0] + value[1] * value[1] + value[2] * value[2])


def _normalize_vec(value: Vec3, fallback: Vec3 = (0.0, 1.0, 0.0)) -> Vec3:
    length = _vec_length(value)
    if length <= 1e-8:
        return fallback
    return (value[0] / length, value[1] / length, value[2] / length)


def _normalized_vertex_selection(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | Iterable[int],
) -> dict[int, set[int]]:
    result: dict[int, set[int]] = {}
    if not isinstance(selected_vertices_by_submesh, Mapping):
        selected_vertices_by_submesh = {0: selected_vertices_by_submesh}
    for raw_submesh_index, raw_vertex_indices in selected_vertices_by_submesh.items():
        try:
            submesh_index = int(raw_submesh_index)
        except (TypeError, ValueError):
            continue
        if not (0 <= submesh_index < len(mesh.submeshes)):
            continue
        vertex_count = len(getattr(mesh.submeshes[submesh_index], "vertices", ()) or ())
        selected: set[int] = set()
        for raw_vertex_index in raw_vertex_indices or ():
            try:
                vertex_index = int(raw_vertex_index)
            except (TypeError, ValueError):
                continue
            if 0 <= vertex_index < vertex_count:
                selected.add(vertex_index)
        if selected:
            result[submesh_index] = selected
    return result


def _feathered_selection_weights(submesh: object, selected: set[int], feather: int) -> dict[int, float]:
    if not selected:
        return {}
    weights: dict[int, float] = {index: 1.0 for index in selected}
    rings = max(0, int(feather or 0))
    if rings <= 0:
        return weights
    adjacency = build_vertex_adjacency(submesh)  # type: ignore[arg-type]
    frontier = set(selected)
    visited = set(selected)
    for depth in range(1, rings + 1):
        next_frontier: set[int] = set()
        for index in frontier:
            if 0 <= index < len(adjacency):
                next_frontier.update(int(neighbor) for neighbor in adjacency[index] if int(neighbor) not in visited)
        if not next_frontier:
            break
        weight = max(0.0, 1.0 - (float(depth) / float(rings + 1)))
        for index in next_frontier:
            weights[index] = max(weights.get(index, 0.0), weight)
        visited.update(next_frontier)
        frontier = next_frontier
    return weights


def _build_native_region_volume_delta(
    base_mesh: ParsedMesh,
    selection: Mapping[int, Iterable[int]],
    amount: float,
    feather: int,
) -> tuple[tuple[Vec3, ...], ...] | None:
    try:
        from .mesh_native_core import (
            build_native_region_volume_delta,
            native_mesh_core_available,
            record_native_mesh_core_fallback,
        )
    except Exception:
        return None
    native_result = build_native_region_volume_delta(base_mesh, selection, amount, feather)
    if native_result is None and native_mesh_core_available() and not os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        record_native_mesh_core_fallback(
            "region_volume_delta",
            "native_result_unavailable",
            vertices=sum(len(submesh.vertices or ()) for submesh in base_mesh.submeshes),
            faces=sum(len(submesh.faces or ()) for submesh in base_mesh.submeshes),
        )
    return native_result


def build_region_volume_delta(
    base_mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | Iterable[int],
    amount: float,
    feather: int,
    *,
    slider_id: str = "region_volume",
    label: str = "",
    min_percent: float = -100.0,
    max_percent: float = 100.0,
    default_percent: float = 0.0,
) -> MeshMorphSliderDelta:
    """Build an outward/inward volume delta from selected vertices and feather rings."""

    selection = _normalized_vertex_selection(base_mesh, selected_vertices_by_submesh)
    if not any(selection.values()):
        raise ValueError("Cannot create region slider without selected vertices.")

    normalized_id = _safe_slider_id(slider_id)
    native_deltas = _build_native_region_volume_delta(base_mesh, selection, amount, int(feather or 0))
    if native_deltas is not None:
        return MeshMorphSliderDelta(
            slider_id=normalized_id,
            label=label.strip() or _prettify_slider_label(normalized_id),
            deltas=native_deltas,
            min_percent=float(min_percent),
            max_percent=float(max_percent),
            default_percent=float(default_percent),
            slider_type=MESH_MORPH_SLIDER_TYPE_REGION_VOLUME,
        )

    if not _allow_python_morph_fallback(base_mesh, "region_volume_delta"):
        raise RuntimeError("native region volume delta failed and Python morph fallback was blocked")
    amount_value = float(amount)
    delta_submeshes: list[tuple[Vec3, ...]] = []
    for submesh_index, submesh in enumerate(base_mesh.submeshes):
        vertices = [_vec3(vertex) for vertex in (getattr(submesh, "vertices", ()) or ())]
        selected = selection.get(submesh_index, set())
        weights = _feathered_selection_weights(submesh, selected, int(feather or 0))
        if weights:
            center = (
                sum(vertices[index][0] for index in weights) / len(weights),
                sum(vertices[index][1] for index in weights) / len(weights),
                sum(vertices[index][2] for index in weights) / len(weights),
            )
        else:
            center = (0.0, 0.0, 0.0)
        normals = [_vec3(normal, (0.0, 1.0, 0.0)) for normal in _compute_smooth_normals(submesh.vertices, submesh.faces)]
        submesh_deltas: list[Vec3] = []
        for vertex_index, vertex in enumerate(vertices):
            weight = max(0.0, min(1.0, float(weights.get(vertex_index, 0.0) or 0.0)))
            if weight <= 0.0:
                submesh_deltas.append((0.0, 0.0, 0.0))
                continue
            normal = normals[vertex_index] if vertex_index < len(normals) else (0.0, 0.0, 0.0)
            radial = _normalize_vec(
                (vertex[0] - center[0], vertex[1] - center[1], vertex[2] - center[2]),
                (0.0, 1.0, 0.0),
            )
            direction = _normalize_vec(normal, radial)
            submesh_deltas.append(
                (
                    direction[0] * amount_value * weight,
                    direction[1] * amount_value * weight,
                    direction[2] * amount_value * weight,
                )
            )
        delta_submeshes.append(tuple(submesh_deltas))
    return MeshMorphSliderDelta(
        slider_id=normalized_id,
        label=label.strip() or _prettify_slider_label(normalized_id),
        deltas=tuple(delta_submeshes),
        min_percent=float(min_percent),
        max_percent=float(max_percent),
        default_percent=float(default_percent),
        slider_type=MESH_MORPH_SLIDER_TYPE_REGION_VOLUME,
    )


def _post_edit_delta_at(
    post_edit_deltas: object,
    submesh_index: int,
    vertex_index: int,
) -> Vec3:
    if post_edit_deltas is None:
        return (0.0, 0.0, 0.0)
    try:
        if isinstance(post_edit_deltas, Mapping):
            submesh_deltas = post_edit_deltas.get(submesh_index, ())
        else:
            submesh_deltas = post_edit_deltas[submesh_index]  # type: ignore[index]
        value = submesh_deltas[vertex_index]  # type: ignore[index]
        return (float(value[0]), float(value[1]), float(value[2]))
    except Exception:
        return (0.0, 0.0, 0.0)


def _apply_native_morph_slider_values(
    base_mesh: ParsedMesh,
    deltas: Sequence[MeshMorphSliderDelta],
    values: Mapping[str, float],
    post_edit_deltas: object,
) -> ParsedMesh | None:
    try:
        from .mesh_native_core import (
            apply_native_morph_slider_values,
            native_mesh_core_available,
            record_native_mesh_core_fallback,
        )
    except Exception:
        return None
    native_result = apply_native_morph_slider_values(base_mesh, deltas, values, post_edit_deltas)
    if native_result is None and native_mesh_core_available() and not os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        record_native_mesh_core_fallback(
            "morph_apply",
            "native_result_unavailable",
            vertices=sum(len(submesh.vertices or ()) for submesh in base_mesh.submeshes),
            faces=sum(len(submesh.faces or ()) for submesh in base_mesh.submeshes),
        )
    return native_result


def apply_morph_slider_values(
    base_mesh: ParsedMesh,
    deltas: Sequence[MeshMorphSliderDelta],
    values: Mapping[str, float],
    post_edit_deltas: object = None,
) -> ParsedMesh:
    """Return a cloned mesh with slider percentages and optional post-edit deltas applied."""

    native_result = _apply_native_morph_slider_values(base_mesh, deltas, values, post_edit_deltas)
    if native_result is not None:
        return native_result

    if not _allow_python_morph_fallback(base_mesh, "morph_apply"):
        raise RuntimeError("native morph apply failed and Python morph fallback was blocked")
    result = clone_mesh_for_editing(base_mesh)
    active_deltas = tuple(deltas or ())
    for submesh_index, submesh in enumerate(result.submeshes):
        base_submesh = base_mesh.submeshes[submesh_index]
        morphed_vertices: list[Vec3] = []
        for vertex_index, base_vertex in enumerate(base_submesh.vertices):
            x = float(base_vertex[0])
            y = float(base_vertex[1])
            z = float(base_vertex[2])
            for delta in active_deltas:
                raw_percent = float(values.get(delta.slider_id, delta.default_percent) or 0.0)
                clamped_percent = max(float(delta.min_percent), min(float(delta.max_percent), raw_percent))
                factor = clamped_percent / 100.0
                try:
                    dx, dy, dz = delta.deltas[submesh_index][vertex_index]
                except Exception:
                    continue
                x += float(dx) * factor
                y += float(dy) * factor
                z += float(dz) * factor
            px, py, pz = _post_edit_delta_at(post_edit_deltas, submesh_index, vertex_index)
            morphed_vertices.append((x + px, y + py, z + pz))
        submesh.vertices = morphed_vertices
        submesh.vertex_count = len(submesh.vertices)
        submesh.face_count = len(submesh.faces)
    refresh_parsed_mesh_totals(result)
    recompute_mesh_normals(result)
    return result


def _safe_slider_id(value: object) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("_.-")
    return candidate or "slider"


def _slugify(value: object) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("_.-")
    return slug[:64] or "morph_slider_profile"


def _prettify_slider_label(value: object) -> str:
    text = re.sub(r"^slider[_\-\s]+", "", str(value or ""), flags=re.IGNORECASE)
    text = re.sub(r"[_\-.]+", " ", text).strip()
    return text.title() if text else "Morph Slider"


def _target_mesh_from_path(path: Path) -> ParsedMesh:
    suffix = path.suffix.lower()
    if suffix not in MESH_MORPH_TARGET_EXTENSIONS:
        raise ValueError(f"Unsupported morph target format: {path.suffix or path.name}")
    return import_scene_mesh(path)


def _profile_from_payload(profile_path: Path, payload: Mapping[str, object]) -> MeshMorphSliderProfile:
    sliders: list[MeshMorphSliderSpec] = []
    for raw_slider in tuple(payload.get("sliders", ()) or ()):
        if not isinstance(raw_slider, Mapping):
            continue
        slider_id = _safe_slider_id(raw_slider.get("id") or raw_slider.get("slider_id"))
        slider_type = str(raw_slider.get("type") or raw_slider.get("slider_type") or MESH_MORPH_SLIDER_TYPE_MORPH_TARGET).strip().lower()
        if slider_type not in {MESH_MORPH_SLIDER_TYPE_MORPH_TARGET, MESH_MORPH_SLIDER_TYPE_REGION_VOLUME}:
            continue
        target_path = str(raw_slider.get("target_path") or "").strip()
        region_path = str(raw_slider.get("region_path") or "").strip()
        if slider_type == MESH_MORPH_SLIDER_TYPE_MORPH_TARGET and not target_path:
            continue
        if slider_type == MESH_MORPH_SLIDER_TYPE_REGION_VOLUME and not region_path:
            continue
        sliders.append(
            MeshMorphSliderSpec(
                slider_id=slider_id,
                label=str(raw_slider.get("label") or _prettify_slider_label(slider_id)),
                target_path=target_path,
                slider_type=slider_type,
                region_path=region_path,
                min_percent=float(raw_slider.get("min_percent", -100.0) or -100.0),
                max_percent=float(raw_slider.get("max_percent", 100.0) or 100.0),
                default_percent=float(raw_slider.get("default_percent", 0.0) or 0.0),
            )
        )
    return MeshMorphSliderProfile(
        name=str(payload.get("name") or profile_path.parent.name),
        root_path=profile_path.parent,
        base_virtual_path=str(payload.get("base_virtual_path") or ""),
        base_basename=str(payload.get("base_basename") or ""),
        topology_signature=dict(payload.get("topology_signature") or {}),
        sliders=tuple(sliders),
        format=str(payload.get("format") or ""),
    )


def _profile_payload(profile: MeshMorphSliderProfile) -> dict[str, object]:
    return {
        "format": MESH_MORPH_SLIDER_PROFILE_FORMAT,
        "name": profile.name,
        "base_virtual_path": profile.base_virtual_path,
        "base_basename": profile.base_basename,
        "topology_signature": dict(profile.topology_signature),
        "sliders": [
            {
                "id": slider.slider_id,
                "label": slider.label,
                "type": str(slider.slider_type or MESH_MORPH_SLIDER_TYPE_MORPH_TARGET),
                "target_path": slider.target_path,
                "region_path": slider.region_path,
                "min_percent": slider.min_percent,
                "max_percent": slider.max_percent,
                "default_percent": slider.default_percent,
            }
            for slider in profile.sliders
        ],
    }


def _write_profile(profile: MeshMorphSliderProfile) -> None:
    profile.root_path.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        profile.root_path / "profile.json",
        json.dumps(_profile_payload(profile), indent=2, sort_keys=True),
    )


def save_morph_slider_profile(profile: MeshMorphSliderProfile) -> None:
    _write_profile(profile)


def _write_region_delta_file(
    profile_root: Path,
    slider_id: str,
    delta: MeshMorphSliderDelta,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]],
    amount: float,
    feather: int,
) -> str:
    target_root = profile_root / "targets"
    target_root.mkdir(parents=True, exist_ok=True)
    destination = target_root / f"{_safe_slider_id(slider_id)}.region.json"
    counter = 2
    while destination.exists():
        destination = target_root / f"{_safe_slider_id(slider_id)}_{counter}.region.json"
        counter += 1
    payload = {
        "type": MESH_MORPH_SLIDER_TYPE_REGION_VOLUME,
        "slider_id": delta.slider_id,
        "label": delta.label,
        "amount": float(amount),
        "feather": int(feather or 0),
        "selected_vertices_by_submesh": {
            str(int(submesh_index)): sorted(int(vertex_index) for vertex_index in (vertices or ()))
            for submesh_index, vertices in (selected_vertices_by_submesh or {}).items()
        },
        "deltas": [
            [[float(dx), float(dy), float(dz)] for dx, dy, dz in submesh_deltas]
            for submesh_deltas in delta.deltas
        ],
    }
    atomic_write_text(destination, json.dumps(payload, indent=2, sort_keys=True))
    return destination.relative_to(profile_root).as_posix()


def _read_region_delta_file(base_mesh: ParsedMesh, profile: MeshMorphSliderProfile, spec: MeshMorphSliderSpec, slider_id: str) -> MeshMorphSliderDelta:
    region_path = Path(spec.region_path)
    if not region_path.is_absolute():
        region_path = profile.root_path / region_path
    payload = json.loads(region_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"Invalid region slider delta file: {region_path}")
    raw_deltas = tuple(payload.get("deltas", ()) or ())
    if len(raw_deltas) != len(base_mesh.submeshes):
        raise ValueError(
            f"Region slider submesh count mismatch: base {len(base_mesh.submeshes)}, delta {len(raw_deltas)}"
        )
    delta_submeshes: list[tuple[Vec3, ...]] = []
    for submesh_index, (raw_submesh_deltas, base_submesh) in enumerate(zip(raw_deltas, base_mesh.submeshes)):
        submesh_deltas: list[Vec3] = []
        raw_values = raw_submesh_deltas or ()
        vertex_count = len(getattr(base_submesh, "vertices", ()) or ())
        if len(raw_values) != vertex_count:
            raise ValueError(
                f"Region slider vertex count mismatch in submesh {submesh_index}: base {vertex_count}, delta {len(raw_values)}"
            )
        for raw_delta in raw_values:
            submesh_deltas.append(_vec3(raw_delta))
        delta_submeshes.append(tuple(submesh_deltas))
    return MeshMorphSliderDelta(
        slider_id=_safe_slider_id(slider_id),
        label=spec.label.strip() or _prettify_slider_label(slider_id),
        deltas=tuple(delta_submeshes),
        min_percent=float(spec.min_percent),
        max_percent=float(spec.max_percent),
        default_percent=float(spec.default_percent),
        slider_type=MESH_MORPH_SLIDER_TYPE_REGION_VOLUME,
    )


def load_morph_slider_delta(
    base_mesh: ParsedMesh,
    profile: MeshMorphSliderProfile,
    spec: MeshMorphSliderSpec,
    *,
    slider_id: str | None = None,
) -> MeshMorphSliderDelta:
    resolved_slider_id = _safe_slider_id(slider_id or spec.slider_id)
    slider_type = str(spec.slider_type or MESH_MORPH_SLIDER_TYPE_MORPH_TARGET).strip().lower()
    if slider_type == MESH_MORPH_SLIDER_TYPE_REGION_VOLUME:
        return _read_region_delta_file(base_mesh, profile, spec, resolved_slider_id)
    target_path = Path(spec.target_path)
    if not target_path.is_absolute():
        target_path = profile.root_path / target_path
    target_mesh = import_scene_mesh(target_path)
    return build_morph_delta(
        base_mesh,
        target_mesh,
        resolved_slider_id,
        label=spec.label,
        min_percent=spec.min_percent,
        max_percent=spec.max_percent,
        default_percent=spec.default_percent,
    )


def _new_profile_dir(output_root: Path, profile_name: str, virtual_path: str, extra_key: str = "") -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(
        (f"{_normalize_virtual_path(virtual_path)}\n{profile_name}\n{extra_key}").encode("utf-8")
    ).hexdigest()[:10]
    base = output_root / f"{_slugify(profile_name)}-{digest}"
    candidate = base
    counter = 2
    while candidate.exists():
        candidate = output_root / f"{base.name}-{counter}"
        counter += 1
    return candidate


def _matching_profile(profile: MeshMorphSliderProfile, base_signature: Mapping[str, object], virtual_path: str) -> bool:
    if profile.format != MESH_MORPH_SLIDER_PROFILE_FORMAT:
        return False
    if not _signature_matches(base_signature, profile.topology_signature):
        return False
    normalized_virtual_path = _normalize_virtual_path(virtual_path)
    normalized_basename = Path(normalized_virtual_path).name.lower()
    profile_virtual_path = _normalize_virtual_path(profile.base_virtual_path)
    profile_basename = str(profile.base_basename or "").strip().lower()
    if profile_virtual_path and profile_virtual_path == normalized_virtual_path:
        return True
    return bool(profile_basename and profile_basename == normalized_basename)


def load_morph_slider_profiles(root: str | Path, base_mesh: ParsedMesh, virtual_path: str) -> tuple[MeshMorphSliderProfile, ...]:
    base_root = Path(root).expanduser()
    if not base_root.is_dir():
        return ()
    base_signature = _topology_signature_payload(base_mesh)
    profiles: list[MeshMorphSliderProfile] = []
    for profile_path in sorted(base_root.glob("*/profile.json")):
        try:
            payload = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, Mapping):
            continue
        profile = _profile_from_payload(profile_path, payload)
        if _matching_profile(profile, base_signature, virtual_path):
            profiles.append(profile)
    return tuple(profiles)


def create_region_volume_slider_profile(
    base_mesh: ParsedMesh,
    virtual_path: str,
    output_root: str | Path,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | Iterable[int],
    *,
    name: str,
    amount: float,
    feather: int = 2,
    label: str = "",
) -> MeshMorphSliderProfile:
    selection = _normalized_vertex_selection(base_mesh, selected_vertices_by_submesh)
    if not any(selection.values()):
        raise ValueError("Cannot create region slider without selected vertices.")
    slider_id = _safe_slider_id(name)
    slider_label = label.strip() or _prettify_slider_label(slider_id)
    profile_name = f"Region Slider - {slider_label}"
    profile_root = _new_profile_dir(
        Path(output_root).expanduser(),
        profile_name,
        virtual_path,
        json.dumps({str(key): sorted(values) for key, values in selection.items()}, sort_keys=True),
    )
    delta = build_region_volume_delta(
        base_mesh,
        selection,
        amount,
        feather,
        slider_id=slider_id,
        label=slider_label,
    )
    region_path = _write_region_delta_file(profile_root, slider_id, delta, selection, amount, feather)
    profile = MeshMorphSliderProfile(
        name=profile_name,
        root_path=profile_root,
        base_virtual_path=str(virtual_path or ""),
        base_basename=Path(str(virtual_path or "")).name,
        topology_signature=_topology_signature_payload(base_mesh),
        sliders=(
            MeshMorphSliderSpec(
                slider_id=slider_id,
                label=slider_label,
                slider_type=MESH_MORPH_SLIDER_TYPE_REGION_VOLUME,
                region_path=region_path,
            ),
        ),
    )
    _write_profile(profile)
    return profile
