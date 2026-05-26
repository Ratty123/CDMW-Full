"""Morph-target slider profiles for topology-preserving mesh edits."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .mesh_deformer import build_vertex_adjacency, clone_mesh_for_editing, recompute_mesh_normals
from .mesh_parser import ParsedMesh
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
    for raw_face in tuple(getattr(submesh, "faces", ()) or ()):
        if len(raw_face) < 3:
            continue
        faces.append((int(raw_face[0]), int(raw_face[1]), int(raw_face[2])))
    return tuple(faces)


def _topology_signature_payload(mesh: ParsedMesh) -> dict[str, object]:
    submeshes = []
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        submeshes.append(
            {
                "name": str(getattr(submesh, "name", "") or ""),
                "material": str(getattr(submesh, "material", "") or ""),
                "vertex_count": len(tuple(getattr(submesh, "vertices", ()) or ())),
                "face_count": len(_topology_faces(submesh)),
                "faces": [list(face) for face in _topology_faces(submesh)],
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

    base_submeshes = tuple(getattr(base_mesh, "submeshes", ()) or ())
    target_submeshes = tuple(getattr(target_mesh, "submeshes", ()) or ())
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
        base_vertices = tuple(getattr(base_submesh, "vertices", ()) or ())
        target_vertices = tuple(getattr(target_submesh, "vertices", ()) or ())
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
    validate_morph_target(base_mesh, target_mesh)
    delta_submeshes: list[tuple[Vec3, ...]] = []
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
        vertex_count = len(tuple(getattr(mesh.submeshes[submesh_index], "vertices", ()) or ()))
        selected: set[int] = set()
        for raw_vertex_index in tuple(raw_vertex_indices or ()):
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

    normal_mesh = clone_mesh_for_editing(base_mesh)
    recompute_mesh_normals(normal_mesh)
    amount_value = float(amount)
    delta_submeshes: list[tuple[Vec3, ...]] = []
    for submesh_index, submesh in enumerate(base_mesh.submeshes):
        vertices = [_vec3(vertex) for vertex in tuple(getattr(submesh, "vertices", ()) or ())]
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
        normal_submesh = normal_mesh.submeshes[submesh_index]
        normals = [_vec3(normal, (0.0, 1.0, 0.0)) for normal in tuple(getattr(normal_submesh, "normals", ()) or ())]
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
    normalized_id = _safe_slider_id(slider_id)
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


def apply_morph_slider_values(
    base_mesh: ParsedMesh,
    deltas: Sequence[MeshMorphSliderDelta],
    values: Mapping[str, float],
    post_edit_deltas: object = None,
) -> ParsedMesh:
    """Return a cloned mesh with slider percentages and optional post-edit deltas applied."""

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


def _language_entries(folder: Path) -> dict[str, str]:
    candidates: list[Path] = []
    current = folder
    for _depth in range(4):
        candidates.append(current / "language" / "en.json")
        if current.parent == current:
            break
        current = current.parent
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        entries: dict[str, str] = {}

        def visit(prefix: str, value: object) -> None:
            if isinstance(value, str):
                entries[prefix.strip().lower()] = value
                entries[re.sub(r"[^a-z0-9]+", "_", prefix.lower()).strip("_")] = value
                return
            if isinstance(value, Mapping):
                for key, child in value.items():
                    key_text = str(key or "")
                    visit(key_text if not prefix else f"{prefix}.{key_text}", child)

        visit("", payload)
        return entries
    return {}


def _label_from_language(slider_id: str, language_entries: Mapping[str, str]) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", slider_id.lower()).strip("_")
    candidates = (
        slider_id.lower(),
        normalized,
        f"slider_{normalized}",
        f"sliders_{normalized}",
    )
    for key in candidates:
        label = str(language_entries.get(key, "") or "").strip()
        if label:
            return label
    for key, label in language_entries.items():
        normalized_key = re.sub(r"[^a-z0-9]+", "_", str(key or "").lower()).strip("_")
        if normalized_key.endswith(normalized) or normalized_key.endswith(f"slider_{normalized}"):
            label_text = str(label or "").strip()
            if label_text:
                return label_text
    return _prettify_slider_label(slider_id)


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
    (profile.root_path / "profile.json").write_text(
        json.dumps(_profile_payload(profile), indent=2, sort_keys=True),
        encoding="utf-8",
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
            str(int(submesh_index)): sorted(int(vertex_index) for vertex_index in tuple(vertices or ()))
            for submesh_index, vertices in dict(selected_vertices_by_submesh or {}).items()
        },
        "deltas": [
            [[float(dx), float(dy), float(dz)] for dx, dy, dz in submesh_deltas]
            for submesh_deltas in delta.deltas
        ],
    }
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
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
        raw_values = tuple(raw_submesh_deltas or ())
        vertex_count = len(tuple(getattr(base_submesh, "vertices", ()) or ()))
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


def _candidate_body_slider_target_dirs(folder: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    target_root = folder / "target_mesh"
    if target_root.is_dir():
        candidates.extend(path for path in sorted(target_root.iterdir()) if path.is_dir())
    if folder.name.lower() == "target_mesh":
        candidates.extend(path for path in sorted(folder.iterdir()) if path.is_dir())
    if folder.parent.name.lower() == "target_mesh":
        candidates.append(folder)
    if any(folder.glob("*.obj")):
        candidates.append(folder)
    seen: set[str] = set()
    deduped: list[Path] = []
    for candidate in candidates:
        key = str(candidate.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return tuple(deduped)


def _copy_target_mesh(target_path: Path, target_root: Path, slider_id: str) -> str:
    target_root.mkdir(parents=True, exist_ok=True)
    safe_name = f"{_safe_slider_id(slider_id)}{target_path.suffix.lower()}"
    destination = target_root / safe_name
    counter = 2
    while destination.exists():
        destination = target_root / f"{_safe_slider_id(slider_id)}_{counter}{target_path.suffix.lower()}"
        counter += 1
    shutil.copy2(target_path, destination)
    return destination.relative_to(target_root.parent).as_posix()


def import_body_slider_profile(
    folder: str | Path,
    base_mesh: ParsedMesh,
    virtual_path: str,
    output_root: str | Path,
) -> MeshMorphSliderProfile:
    source_root = Path(folder).expanduser().resolve()
    if not source_root.is_dir():
        raise ValueError(f"Slider pack folder does not exist: {source_root}")
    language = _language_entries(source_root)
    target_files: list[Path] = []
    for target_dir in _candidate_body_slider_target_dirs(source_root):
        target_files.extend(sorted(target_dir.glob("*.obj")))
    if not target_files:
        raise ValueError(f"No Body Slider Pro OBJ targets found under {source_root}")

    compatible_targets: list[tuple[Path, str, str]] = []
    errors: list[str] = []
    used_ids: set[str] = set()
    for target_path in target_files:
        slider_id = _safe_slider_id(target_path.stem)
        original_slider_id = slider_id
        counter = 2
        while slider_id.lower() in used_ids:
            slider_id = f"{original_slider_id}_{counter}"
            counter += 1
        try:
            target_mesh = _target_mesh_from_path(target_path)
            validate_morph_target(base_mesh, target_mesh)
        except Exception as exc:
            errors.append(f"{target_path.name}: {exc}")
            continue
        used_ids.add(slider_id.lower())
        compatible_targets.append((target_path, slider_id, _label_from_language(slider_id, language)))

    if not compatible_targets:
        detail = "; ".join(errors[:6])
        raise ValueError(f"No compatible morph targets found in {source_root}" + (f": {detail}" if detail else ""))

    character_names = sorted({target_path.parent.name for target_path, _slider_id, _label in compatible_targets})
    character_label = ", ".join(character_names[:3])
    profile_name = f"Body Slider Pro - {character_label}" if character_label else "Body Slider Pro"
    profile_root = _new_profile_dir(Path(output_root).expanduser(), profile_name, virtual_path, str(source_root))
    targets_root = profile_root / "targets"
    sliders: list[MeshMorphSliderSpec] = []
    for target_path, slider_id, label in compatible_targets:
        relative_target_path = _copy_target_mesh(target_path, targets_root, slider_id)
        sliders.append(
            MeshMorphSliderSpec(
                slider_id=slider_id,
                label=label,
                target_path=relative_target_path,
            )
        )

    profile = MeshMorphSliderProfile(
        name=profile_name,
        root_path=profile_root,
        base_virtual_path=str(virtual_path or ""),
        base_basename=Path(str(virtual_path or "")).name,
        topology_signature=_topology_signature_payload(base_mesh),
        sliders=tuple(sliders),
    )
    _write_profile(profile)
    return profile


def import_single_morph_slider_profile(
    target_file: str | Path,
    base_mesh: ParsedMesh,
    virtual_path: str,
    output_root: str | Path,
    *,
    label: str = "",
) -> MeshMorphSliderProfile:
    target_path = Path(target_file).expanduser().resolve()
    target_mesh = _target_mesh_from_path(target_path)
    validate_morph_target(base_mesh, target_mesh)
    slider_id = _safe_slider_id(target_path.stem)
    profile_name = f"Manual Morph Slider - {_prettify_slider_label(slider_id)}"
    profile_root = _new_profile_dir(Path(output_root).expanduser(), profile_name, virtual_path, str(target_path))
    relative_target_path = _copy_target_mesh(target_path, profile_root / "targets", slider_id)
    profile = MeshMorphSliderProfile(
        name=profile_name,
        root_path=profile_root,
        base_virtual_path=str(virtual_path or ""),
        base_basename=Path(str(virtual_path or "")).name,
        topology_signature=_topology_signature_payload(base_mesh),
        sliders=(
            MeshMorphSliderSpec(
                slider_id=slider_id,
                label=label.strip() or _prettify_slider_label(slider_id),
                target_path=relative_target_path,
            ),
        ),
    )
    _write_profile(profile)
    return profile


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
