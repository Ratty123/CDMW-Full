"""Pure procedural morph and garment-refit contracts and rules."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Iterable, Mapping, Sequence


Vec3 = tuple[float, float, float]
MESH_MORPH_PROFILE_FORMAT = "cdmw.mesh_morph_profile.v2"
MESH_MORPH_PRESET_FORMAT = "cdmw.mesh_morph_value_preset.v2"
MESH_MORPH_RULES = ("volume", "scale", "move", "flatten", "taper", "twist")
MESH_MORPH_AXES = ("x", "y", "z")
MESH_MORPH_MIRROR_MODES = ("off", "x", "y", "z")
MESH_MORPH_FALLOFFS = ("constant", "linear", "smooth")


@dataclass(frozen=True, slots=True)
class MeshMorphVertexWeight:
    submesh_index: int
    vertex_index: int
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class MeshMorphRule:
    kind: str
    axis: str = "y"
    amount: float = 0.1
    falloff: str = "smooth"
    feather: int = 2
    parameters: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        kind = str(self.kind or "").strip().lower()
        axis = str(self.axis or "").strip().lower()
        falloff = str(self.falloff or "").strip().lower()
        if kind not in MESH_MORPH_RULES:
            raise ValueError(f"Unsupported procedural morph rule: {self.kind!r}")
        if axis not in MESH_MORPH_AXES:
            raise ValueError(f"Unsupported procedural morph axis: {self.axis!r}")
        if falloff not in MESH_MORPH_FALLOFFS:
            raise ValueError(f"Unsupported procedural morph falloff: {self.falloff!r}")
        if not math.isfinite(float(self.amount)):
            raise ValueError("Procedural morph amount must be finite.")
        if int(self.feather) < 0:
            raise ValueError("Procedural morph feather must be nonnegative.")
        parameters: list[tuple[str, float]] = []
        for raw_name, raw_value in self.parameters:
            name = str(raw_name or "").strip().lower()
            value = float(raw_value)
            if not name or not math.isfinite(value):
                raise ValueError("Procedural morph parameters require finite named values.")
            parameters.append((name, value))
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "axis", axis)
        object.__setattr__(self, "falloff", falloff)
        object.__setattr__(self, "amount", float(self.amount))
        object.__setattr__(self, "feather", int(self.feather))
        object.__setattr__(self, "parameters", tuple(sorted(parameters)))


@dataclass(frozen=True, slots=True)
class MeshMorphDefinition:
    definition_id: str
    label: str
    category: str
    vertices: tuple[MeshMorphVertexWeight, ...]
    pivot: Vec3
    local_basis: tuple[Vec3, Vec3, Vec3]
    rule: MeshMorphRule
    mirror_mode: str = "off"
    min_percent: float = -100.0
    max_percent: float = 100.0
    default_percent: float = 0.0

    def __post_init__(self) -> None:
        definition_id = str(self.definition_id or "").strip()
        if not definition_id:
            raise ValueError("Morph definition_id is required.")
        if not self.vertices:
            raise ValueError("Morph definition requires at least one weighted vertex.")
        pivot = _point3(self.pivot)
        if len(self.local_basis) != 3:
            raise ValueError("Morph definition local_basis must contain three axes.")
        basis = tuple(_normalized(_point3(axis)) for axis in self.local_basis)
        if abs(_dot(basis[0], basis[1])) > 1e-5 or abs(_dot(basis[0], basis[2])) > 1e-5 or abs(_dot(basis[1], basis[2])) > 1e-5:
            raise ValueError("Morph definition local_basis axes must be orthogonal.")
        normalized_vertices: list[MeshMorphVertexWeight] = []
        seen: set[tuple[int, int]] = set()
        for vertex in self.vertices:
            key = (int(vertex.submesh_index), int(vertex.vertex_index))
            weight = float(vertex.weight)
            if key[0] < 0 or key[1] < 0 or not math.isfinite(weight) or not 0.0 < weight <= 1.0:
                raise ValueError("Morph definition vertices require nonnegative indices and weights in (0, 1].")
            if key in seen:
                raise ValueError("Morph definition contains a duplicate weighted vertex.")
            seen.add(key)
            normalized_vertices.append(MeshMorphVertexWeight(key[0], key[1], weight))
        mirror_mode = str(self.mirror_mode or "off").strip().lower()
        if mirror_mode not in MESH_MORPH_MIRROR_MODES:
            raise ValueError(f"Unsupported mirror mode: {self.mirror_mode!r}")
        minimum = float(self.min_percent)
        maximum = float(self.max_percent)
        default = float(self.default_percent)
        if not all(math.isfinite(value) for value in (minimum, maximum, default)) or minimum >= maximum:
            raise ValueError("Morph slider range must be finite and increasing.")
        if not minimum <= default <= maximum:
            raise ValueError("Morph slider default must be inside its range.")
        object.__setattr__(self, "definition_id", definition_id)
        object.__setattr__(self, "label", str(self.label or definition_id).strip() or definition_id)
        object.__setattr__(self, "category", str(self.category or "General").strip() or "General")
        object.__setattr__(self, "mirror_mode", mirror_mode)
        object.__setattr__(self, "min_percent", minimum)
        object.__setattr__(self, "max_percent", maximum)
        object.__setattr__(self, "default_percent", default)
        object.__setattr__(self, "vertices", tuple(sorted(normalized_vertices, key=lambda item: (item.submesh_index, item.vertex_index))))
        object.__setattr__(self, "pivot", pivot)
        object.__setattr__(self, "local_basis", basis)


@dataclass(frozen=True, slots=True)
class MeshMorphSparseField:
    definition_id: str
    submesh_index: int
    vertex_indices: tuple[int, ...]
    deltas: tuple[Vec3, ...]


@dataclass(frozen=True, slots=True)
class MeshMorphProfile:
    profile_id: str
    name: str
    topology_fingerprint: str
    definitions: tuple[MeshMorphDefinition, ...] = ()
    format: str = MESH_MORPH_PROFILE_FORMAT
    migrated_from_version: int = 0
    requires_v2_save: bool = False

    def __post_init__(self) -> None:
        profile_id = str(self.profile_id or "").strip()
        fingerprint = str(self.topology_fingerprint or "").strip().lower()
        if not profile_id:
            raise ValueError("Morph profile_id is required.")
        if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
            raise ValueError("Morph profile topology_fingerprint must be an exact SHA-256 digest.")
        identifiers = [definition.definition_id for definition in self.definitions]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Morph profile definition ids must be unique.")
        object.__setattr__(self, "profile_id", profile_id)
        object.__setattr__(self, "name", str(self.name or profile_id).strip() or profile_id)
        object.__setattr__(self, "topology_fingerprint", fingerprint)


@dataclass(frozen=True, slots=True)
class MeshMorphValuePreset:
    preset_id: str
    name: str
    profile_id: str
    topology_fingerprint: str
    values: tuple[tuple[str, float], ...] = ()
    format: str = MESH_MORPH_PRESET_FORMAT

    def __post_init__(self) -> None:
        preset_id = str(self.preset_id or "").strip()
        profile_id = str(self.profile_id or "").strip()
        fingerprint = str(self.topology_fingerprint or "").strip().lower()
        if not preset_id or not profile_id:
            raise ValueError("Morph preset_id and profile_id are required.")
        if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
            raise ValueError("Morph preset topology_fingerprint must be an exact SHA-256 digest.")
        normalized: list[tuple[str, float]] = []
        seen: set[str] = set()
        for raw_definition_id, raw_value in self.values:
            definition_id = str(raw_definition_id or "").strip()
            value = float(raw_value)
            if not definition_id or definition_id in seen or not math.isfinite(value):
                raise ValueError("Morph preset values require unique definition ids and finite values.")
            seen.add(definition_id)
            normalized.append((definition_id, value))
        object.__setattr__(self, "preset_id", preset_id)
        object.__setattr__(self, "profile_id", profile_id)
        object.__setattr__(self, "name", str(self.name or preset_id).strip() or preset_id)
        object.__setattr__(self, "topology_fingerprint", fingerprint)
        object.__setattr__(self, "values", tuple(sorted(normalized)))


@dataclass(frozen=True, slots=True)
class MeshRefitBindingSummary:
    driver_submesh_indices: tuple[int, ...] = ()
    garment_submesh_indices: tuple[int, ...] = ()
    bound_vertex_count: int = 0
    maximum_distance: float = 0.0
    p95_distance: float = 0.0
    warning_distance: float = 0.0
    distance_warning: bool = False


@dataclass(frozen=True, slots=True)
class MeshMorphState:
    session_id: str = ""
    profile_id: str = ""
    preset_id: str = ""
    topology_fingerprint: str = ""
    definitions: tuple[MeshMorphDefinition, ...] = ()
    values: tuple[tuple[str, float], ...] = ()
    available_profiles: tuple[tuple[str, str], ...] = ()
    available_presets: tuple[tuple[str, str], ...] = ()
    driver_submesh_indices: tuple[int, ...] = ()
    refit: MeshRefitBindingSummary = field(default_factory=MeshRefitBindingSummary)
    unbaked: bool = False
    topology_blocked: bool = False
    busy: bool = False
    failure: str = ""
    diagnostics: tuple[str, ...] = ()
    state_revision: int = 0
    edit_revision: int = 0
    change_id: str = ""


def mesh_topology_fingerprint(mesh: object, submesh_indices: Iterable[int] | None = None) -> str:
    """Return an exact, position-independent fingerprint for selected topology."""

    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    indices = tuple(range(len(submeshes))) if submesh_indices is None else tuple(sorted({int(i) for i in submesh_indices}))
    payload: list[dict[str, object]] = []
    for submesh_index in indices:
        if not 0 <= submesh_index < len(submeshes):
            raise ValueError(f"Topology fingerprint submesh is out of range: {submesh_index}")
        submesh = submeshes[submesh_index]
        faces = []
        for face in tuple(getattr(submesh, "faces", ()) or ()):
            values = tuple(int(index) for index in face[:3])
            if len(values) == 3:
                faces.append(values)
        payload.append(
            {
                "index": submesh_index,
                "vertex_count": len(tuple(getattr(submesh, "vertices", ()) or ())),
                "faces": faces,
            }
        )
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def mesh_morph_driver_topology_fingerprint(
    mesh: object,
    definitions: Iterable[MeshMorphDefinition],
) -> str:
    """Fingerprint only the body/driver submeshes referenced by definitions."""

    indices = tuple(
        sorted(
            {
                vertex.submesh_index
                for definition in definitions
                for vertex in definition.vertices
            }
        )
    )
    return mesh_topology_fingerprint(mesh, indices or None)


def build_weighted_morph_selection(
    mesh: object,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]],
    *,
    feather: int = 0,
    falloff: str = "smooth",
    mirror_mode: str = "off",
    mirror_tolerance: float | None = None,
) -> tuple[MeshMorphVertexWeight, ...]:
    """Expand a selection by face-adjacency rings and optionally mirror it strictly."""

    falloff = str(falloff or "smooth").strip().lower()
    mirror_mode = str(mirror_mode or "off").strip().lower()
    if falloff not in MESH_MORPH_FALLOFFS:
        raise ValueError(f"Unsupported procedural morph falloff: {falloff!r}")
    if mirror_mode not in MESH_MORPH_MIRROR_MODES:
        raise ValueError(f"Unsupported mirror mode: {mirror_mode!r}")
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    weighted: dict[tuple[int, int], float] = {}
    rings = max(0, int(feather))
    for raw_submesh, raw_vertices in selected_vertices_by_submesh.items():
        submesh_index = int(raw_submesh)
        if not 0 <= submesh_index < len(submeshes):
            continue
        vertex_count = len(tuple(getattr(submeshes[submesh_index], "vertices", ()) or ()))
        selected = {int(index) for index in raw_vertices if 0 <= int(index) < vertex_count}
        if not selected:
            continue
        adjacency = _vertex_adjacency(submeshes[submesh_index], vertex_count)
        frontier = set(selected)
        visited = set(selected)
        for index in selected:
            weighted[submesh_index, index] = 1.0
        for depth in range(1, rings + 1):
            next_frontier = {
                neighbor
                for index in frontier
                for neighbor in adjacency[index]
                if neighbor not in visited
            }
            if not next_frontier:
                break
            linear = max(0.0, 1.0 - depth / float(rings + 1))
            weight = linear * linear * (3.0 - 2.0 * linear) if falloff == "smooth" else (1.0 if falloff == "constant" else linear)
            for index in next_frontier:
                weighted[submesh_index, index] = max(weighted.get((submesh_index, index), 0.0), weight)
            visited.update(next_frontier)
            frontier = next_frontier
    if not weighted:
        raise ValueError("Cannot create a procedural morph without selected vertices.")
    if mirror_mode != "off":
        weighted = _strict_mirror_weights(mesh, weighted, mirror_mode, mirror_tolerance)
    return tuple(
        MeshMorphVertexWeight(submesh_index, vertex_index, weight)
        for (submesh_index, vertex_index), weight in sorted(weighted.items())
    )


def procedural_morph_pivot(mesh: object, vertices: Sequence[MeshMorphVertexWeight]) -> Vec3:
    return _weighted_pivot(mesh, {(item.submesh_index, item.vertex_index): item.weight for item in vertices})


def generate_procedural_morph_fields(
    mesh: object,
    definition: MeshMorphDefinition,
) -> tuple[MeshMorphSparseField, ...]:
    """Generate deterministic sparse 100-percent deltas for one definition."""

    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    axis = _normalized(definition.local_basis[MESH_MORPH_AXES.index(definition.rule.axis)])
    selected_positions: list[Vec3] = []
    valid: list[tuple[MeshMorphVertexWeight, Vec3]] = []
    for item in definition.vertices:
        if not 0 <= item.submesh_index < len(submeshes):
            raise ValueError(f"Morph definition submesh is out of range: {item.submesh_index}")
        positions = tuple(getattr(submeshes[item.submesh_index], "vertices", ()) or ())
        if not 0 <= item.vertex_index < len(positions):
            raise ValueError(f"Morph definition vertex is out of range: {item.vertex_index}")
        position = _point3(positions[item.vertex_index])
        selected_positions.append(position)
        valid.append((item, position))
    projections = [_dot(_sub(position, definition.pivot), axis) for position in selected_positions]
    axial_extent = max((abs(value) for value in projections), default=0.0)
    if axial_extent <= 1e-12:
        axial_extent = 1.0
    fields: dict[int, list[tuple[int, Vec3]]] = {}
    for item, position in valid:
        delta = _rule_delta(position, definition.pivot, axis, definition.rule, axial_extent)
        weighted_delta = _scale(delta, max(0.0, min(1.0, float(item.weight))))
        if _length_squared(weighted_delta) <= 1e-30:
            continue
        fields.setdefault(item.submesh_index, []).append((item.vertex_index, weighted_delta))
    return tuple(
        MeshMorphSparseField(
            definition.definition_id,
            submesh_index,
            tuple(index for index, _delta in sorted(items)),
            tuple(delta for _index, delta in sorted(items)),
        )
        for submesh_index, items in sorted(fields.items())
    )


def clamp_morph_value(definition: MeshMorphDefinition, value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        number = definition.default_percent
    if not math.isfinite(number):
        number = definition.default_percent
    return max(definition.min_percent, min(definition.max_percent, number))


def _rule_delta(position: Vec3, pivot: Vec3, axis: Vec3, rule: MeshMorphRule, axial_extent: float) -> Vec3:
    local = _sub(position, pivot)
    projection = _dot(local, axis)
    axial = _scale(axis, projection)
    radial = _sub(local, axial)
    amount = float(rule.amount)
    if rule.kind == "move":
        return _scale(axis, amount)
    if rule.kind == "scale":
        return _scale(axial, amount)
    if rule.kind == "flatten":
        return _scale(axial, -amount)
    if rule.kind == "taper":
        return _scale(radial, amount * (projection / axial_extent))
    if rule.kind == "twist":
        angle = math.radians(amount) * (projection / axial_extent)
        rotated = _rodrigues(radial, axis, angle)
        return _sub(rotated, radial)
    radial_direction = _normalized(radial, fallback=axis)
    return _scale(radial_direction, amount)


def _vertex_adjacency(submesh: object, vertex_count: int) -> tuple[set[int], ...]:
    adjacency = [set() for _ in range(vertex_count)]
    for raw_face in tuple(getattr(submesh, "faces", ()) or ()):
        face = tuple(int(index) for index in raw_face[:3])
        if len(face) != 3 or any(index < 0 or index >= vertex_count for index in face):
            continue
        for left, right in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            adjacency[left].add(right)
            adjacency[right].add(left)
    return tuple(adjacency)


def _weighted_pivot(mesh: object, weighted: Mapping[tuple[int, int], float]) -> Vec3:
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    total = 0.0
    accum = [0.0, 0.0, 0.0]
    for (submesh_index, vertex_index), raw_weight in weighted.items():
        weight = max(0.0, float(raw_weight))
        if weight <= 0.0 or not 0 <= submesh_index < len(submeshes):
            continue
        vertices = tuple(getattr(submeshes[submesh_index], "vertices", ()) or ())
        if not 0 <= vertex_index < len(vertices):
            continue
        point = _point3(vertices[vertex_index])
        for axis in range(3):
            accum[axis] += point[axis] * weight
        total += weight
    if total <= 0.0:
        raise ValueError("Cannot determine a procedural morph pivot from an empty selection.")
    return accum[0] / total, accum[1] / total, accum[2] / total


def _strict_mirror_weights(
    mesh: object,
    weighted: Mapping[tuple[int, int], float],
    axis_name: str,
    tolerance: float | None,
) -> dict[tuple[int, int], float]:
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    points: list[tuple[int, int, Vec3]] = []
    point_by_key: dict[tuple[int, int], Vec3] = {}
    for submesh_index, submesh in enumerate(submeshes):
        for vertex_index, raw_point in enumerate(tuple(getattr(submesh, "vertices", ()) or ())):
            point = _point3(raw_point)
            points.append((submesh_index, vertex_index, point))
            point_by_key[submesh_index, vertex_index] = point
    if not points:
        raise ValueError("Cannot mirror an empty mesh.")
    minimum = tuple(min(point[2][axis] for point in points) for axis in range(3))
    maximum = tuple(max(point[2][axis] for point in points) for axis in range(3))
    diagonal = math.sqrt(sum((maximum[axis] - minimum[axis]) ** 2 for axis in range(3)))
    epsilon = max(1e-6, diagonal * 1e-7) if tolerance is None else max(1e-12, float(tolerance))
    buckets: dict[tuple[int, int, int], list[tuple[int, int, Vec3]]] = {}
    for item in points:
        buckets.setdefault(_cell(item[2], epsilon), []).append(item)
    result = dict(weighted)
    mirror_axis = MESH_MORPH_AXES.index(axis_name)
    mirror_center = (minimum[mirror_axis] + maximum[mirror_axis]) * 0.5
    missing: list[tuple[int, int]] = []
    for key, weight in weighted.items():
        point = point_by_key.get(key)
        if point is None:
            missing.append(key)
            continue
        reflected = list(point)
        reflected[mirror_axis] = (2.0 * mirror_center) - reflected[mirror_axis]
        reflected_point = tuple(reflected)  # type: ignore[assignment]
        cell = _cell(reflected_point, epsilon)
        candidates = (
            item
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for dz in (-1, 0, 1)
            for item in buckets.get((cell[0] + dx, cell[1] + dy, cell[2] + dz), ())
        )
        try:
            match = min(
                (item for item in candidates if _length_squared(_sub(item[2], reflected_point)) <= epsilon * epsilon),
                key=lambda item: (_length_squared(_sub(item[2], reflected_point)), item[0], item[1]),
            )
        except ValueError:
            missing.append(key)
            continue
        match_key = (match[0], match[1])
        result[match_key] = max(result.get(match_key, 0.0), float(weight))
    if missing:
        raise ValueError(f"Mirror creation failed: {len(missing)} selected vertices have no reflected match.")
    return result


def _cell(point: Vec3, epsilon: float) -> tuple[int, int, int]:
    return tuple(math.floor(component / epsilon) for component in point)  # type: ignore[return-value]


def _point3(value: object) -> Vec3:
    try:
        point = tuple(float(component) for component in value[:3])  # type: ignore[index]
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Morph geometry contains an invalid vertex.") from exc
    if len(point) != 3 or not all(math.isfinite(component) for component in point):
        raise ValueError("Morph geometry contains a non-finite vertex.")
    return point  # type: ignore[return-value]


def _add(left: Vec3, right: Vec3) -> Vec3:
    return tuple(left[index] + right[index] for index in range(3))  # type: ignore[return-value]


def _sub(left: Vec3, right: Vec3) -> Vec3:
    return tuple(left[index] - right[index] for index in range(3))  # type: ignore[return-value]


def _scale(value: Vec3, factor: float) -> Vec3:
    return tuple(component * factor for component in value)  # type: ignore[return-value]


def _dot(left: Vec3, right: Vec3) -> float:
    return sum(left[index] * right[index] for index in range(3))


def _length_squared(value: Vec3) -> float:
    return _dot(value, value)


def _normalized(value: Vec3, fallback: Vec3 = (0.0, 1.0, 0.0)) -> Vec3:
    length = math.sqrt(_length_squared(value))
    return _scale(value, 1.0 / length) if length > 1e-12 else fallback


def _rodrigues(value: Vec3, axis: Vec3, angle: float) -> Vec3:
    cosine = math.cos(angle)
    sine = math.sin(angle)
    cross = (
        axis[1] * value[2] - axis[2] * value[1],
        axis[2] * value[0] - axis[0] * value[2],
        axis[0] * value[1] - axis[1] * value[0],
    )
    return _add(_add(_scale(value, cosine), _scale(cross, sine)), _scale(axis, _dot(axis, value) * (1.0 - cosine)))


__all__ = [
    "MESH_MORPH_AXES",
    "MESH_MORPH_FALLOFFS",
    "MESH_MORPH_MIRROR_MODES",
    "MESH_MORPH_PRESET_FORMAT",
    "MESH_MORPH_PROFILE_FORMAT",
    "MESH_MORPH_RULES",
    "MeshMorphDefinition",
    "MeshMorphProfile",
    "MeshMorphRule",
    "MeshMorphSparseField",
    "MeshMorphState",
    "MeshMorphValuePreset",
    "MeshMorphVertexWeight",
    "MeshRefitBindingSummary",
    "build_weighted_morph_selection",
    "clamp_morph_value",
    "generate_procedural_morph_fields",
    "mesh_morph_driver_topology_fingerprint",
    "mesh_topology_fingerprint",
    "procedural_morph_pivot",
]
