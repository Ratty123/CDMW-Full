"""Pure body-region segmentation driven by skin weights.

A skinned body already carries an anatomically correct, artist-tuned partition
of its own surface: the skin weights. This module turns those weights plus the
bone names from the matching skeleton into named body regions with per-vertex
weights, so a slider can be generated for "the left thigh" without anyone
painting a vertex selection first.

Region weight for one vertex is the sum of its normalized bone weights over the
bones a region claims, which keeps the rig's own falloff and makes overlapping
regions a partition of unity: summed over every region plus the unmapped
remainder, each vertex contributes exactly 1.0.

Bone naming is rig-specific, so the mapping table is data, not control flow, and
anything it fails to claim is reported rather than silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Iterable, Mapping, Sequence

from .morph import MeshMorphVertexWeight, mesh_topology_fingerprint


BODY_REGION_MAP_FORMAT = "cdmw.body_region_map.v1"
BODY_REGION_SIDES = ("center", "left", "right")
BODY_REGION_GROUPS = ("Torso", "Arms", "Legs", "Head")
DEFAULT_MINIMUM_REGION_WEIGHT = 1.0e-3

Vec3 = tuple[float, float, float]

_LEFT_TOKENS = frozenset({"l", "lt", "lf", "left"})
_RIGHT_TOKENS = frozenset({"r", "rt", "rg", "right"})
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


def _normalize_name(value: object) -> str:
    return _NON_ALPHANUMERIC.sub("_", str(value or "").strip().lower()).strip("_")


@dataclass(frozen=True, slots=True)
class BodyRegionRule:
    """One claim on a set of bones, matched by substring against bone names."""

    region_id: str
    label: str
    group: str
    patterns: tuple[str, ...]
    sided: bool = True
    priority: int = 0

    def __post_init__(self) -> None:
        region_id = str(self.region_id or "").strip().lower()
        if not region_id:
            raise ValueError("Body region rule requires a region_id.")
        if self.group not in BODY_REGION_GROUPS:
            raise ValueError(f"Unsupported body region group: {self.group!r}")
        patterns = tuple(dict.fromkeys(_normalize_name(pattern) for pattern in self.patterns))
        if not patterns or any(not pattern for pattern in patterns):
            raise ValueError(f"Body region rule {region_id!r} requires non-empty patterns.")
        object.__setattr__(self, "region_id", region_id)
        object.__setattr__(self, "label", str(self.label or region_id).strip() or region_id)
        object.__setattr__(self, "patterns", patterns)


@dataclass(frozen=True, slots=True)
class BodyRegionAxis:
    """Local frame for a region, used as the pivot and axis of generated sliders."""

    origin: Vec3 = (0.0, 0.0, 0.0)
    direction: Vec3 = (0.0, 1.0, 0.0)
    length: float = 0.0
    source: str = "default"


@dataclass(frozen=True, slots=True)
class BodyRegionWeights:
    """Sparse per-vertex region weights inside one submesh."""

    submesh_index: int
    vertex_indices: tuple[int, ...] = ()
    weights: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if len(self.vertex_indices) != len(self.weights):
            raise ValueError("Body region weights require one weight per vertex index.")


@dataclass(frozen=True, slots=True)
class BodyRegion:
    """One resolved body region and the surface it claims."""

    region_id: str
    label: str
    group: str
    side: str = "center"
    bone_indices: tuple[int, ...] = ()
    bone_names: tuple[str, ...] = ()
    parts: tuple[BodyRegionWeights, ...] = ()
    axis: BodyRegionAxis = BodyRegionAxis()
    vertex_count: int = 0
    dominant_vertex_count: int = 0
    peak_weight: float = 0.0
    total_weight: float = 0.0

    @property
    def empty(self) -> bool:
        return self.vertex_count == 0


@dataclass(frozen=True, slots=True)
class BodyRegionMap:
    """Every region resolved against one mesh, plus what could not be claimed."""

    topology_fingerprint: str
    regions: tuple[BodyRegion, ...] = ()
    format: str = BODY_REGION_MAP_FORMAT
    skeleton_source: str = ""
    skeleton_bone_count: int = 0
    mapped_bone_count: int = 0
    unmapped_bone_names: tuple[str, ...] = ()
    unmapped_weight_fraction: float = 0.0
    skinned_vertex_count: int = 0
    unskinned_vertex_count: int = 0
    diagnostics: tuple[str, ...] = ()

    def region(self, region_id: object) -> BodyRegion | None:
        wanted = str(region_id or "").strip().lower()
        for region in self.regions:
            if region.region_id == wanted:
                return region
        return None

    @property
    def populated_regions(self) -> tuple[BodyRegion, ...]:
        return tuple(region for region in self.regions if not region.empty)


DEFAULT_BODY_REGION_RULES: tuple[BodyRegionRule, ...] = (
    # Torso. "spine1"/"spine2" outrank "spine" because the longest matched
    # pattern wins, so the upper/lower split does not need explicit ordering.
    BodyRegionRule("pelvis", "Pelvis", "Torso", ("pelvis", "hips"), sided=False),
    BodyRegionRule(
        "spine_lower",
        "Lower Torso",
        "Torso",
        ("spine", "spine0", "spine_00", "waist", "abdomen"),
        sided=False,
    ),
    BodyRegionRule(
        "spine_upper",
        "Upper Torso",
        "Torso",
        ("spine1", "spine2", "spine_01", "spine_02", "ribcage"),
        sided=False,
    ),
    # Priority lifts these above the torso rules regardless of pattern length,
    # so a rig that names them as spine children still splits them out.
    # Biped rigs drive the breasts from sided "Chest" bones (Bip01 L Chest,
    # R Chest_Muscle, R Chest Side), which is why "chest" belongs here and not
    # on the upper torso.
    BodyRegionRule("breast", "Breast", "Torso", ("breast", "bust", "boob", "chest"), priority=10),
    BodyRegionRule("glute", "Glute", "Torso", ("glute", "buttock", "butt"), priority=10),
    BodyRegionRule("hip", "Hip", "Torso", ("hip",), priority=5),
    # Arms.
    BodyRegionRule("clavicle", "Clavicle", "Arms", ("clavicle", "shoulder", "scapula", "collar")),
    # Most upper-arm and forearm skin rides twist and muscle helpers rather than
    # the joint bones themselves, so those names have to be claimed too.
    BodyRegionRule(
        "upper_arm",
        "Upper Arm",
        "Arms",
        ("upperarm", "upper_arm", "uparm", "humerus", "upperfmuscle", "upperbmuscle"),
    ),
    BodyRegionRule(
        "forearm",
        "Forearm",
        "Arms",
        ("forearm", "fore_arm", "foretwist", "fore_twist", "lowerarm", "lower_arm", "ulna", "elbow"),
    ),
    BodyRegionRule(
        "hand",
        "Hand",
        "Arms",
        ("hand", "palm", "finger", "thumb", "index", "middle", "pinky", "little"),
    ),
    # Legs.
    BodyRegionRule("thigh", "Thigh", "Legs", ("thigh", "upleg", "upperleg", "upper_leg", "femur")),
    BodyRegionRule(
        "calf",
        "Calf",
        "Legs",
        ("calf", "lowerleg", "lower_leg", "shin", "tibia", "knee"),
    ),
    BodyRegionRule("foot", "Foot", "Legs", ("foot", "ankle")),
    BodyRegionRule("toe", "Toe", "Legs", ("toe",)),
    # Head. "forehead" resolves here too, which is what we want.
    BodyRegionRule("neck", "Neck", "Head", ("neck",), sided=False),
    BodyRegionRule(
        "head",
        "Head",
        "Head",
        ("head", "skull", "jaw", "face", "eye", "brow", "lip", "tongue", "teeth", "cheek", "nose"),
    ),
    BodyRegionRule("ear", "Ear", "Head", ("ear",), priority=5),
)


def bone_side(bone_name: object) -> str:
    """Return 'left', 'right', or 'center' from a bone's name tokens.

    Only whole tokens count, so 'Bip01_L_Thigh' is left while 'Clavicle' and
    'Ribcage' stay center instead of matching a stray leading letter.
    """

    normalized = _normalize_name(bone_name)
    if not normalized:
        return "center"
    tokens = normalized.split("_")
    for token in tokens:
        if token in _LEFT_TOKENS:
            return "left"
        if token in _RIGHT_TOKENS:
            return "right"
    if "left" in normalized:
        return "left"
    if "right" in normalized:
        return "right"
    return "center"


def classify_bone(
    bone_name: object,
    rules: Sequence[BodyRegionRule] = DEFAULT_BODY_REGION_RULES,
) -> tuple[BodyRegionRule | None, str]:
    """Pick the rule claiming a bone.

    Ranked by whole-token match, then rule priority, then pattern length. Token
    matches have to win first: 'Forearm' contains 'ear', and no amount of
    priority tuning on the ear rule should be able to steal a bone whose name
    names the forearm outright.
    """

    normalized = _normalize_name(bone_name)
    if not normalized:
        return None, ""
    tokens = set(normalized.split("_"))
    best: tuple[tuple[int, int, int], BodyRegionRule, str] | None = None
    for rule in rules:
        for pattern in rule.patterns:
            if pattern not in normalized:
                continue
            rank = (1 if pattern in tokens else 0, rule.priority, len(pattern))
            if best is None or rank > best[0]:
                best = (rank, rule, pattern)
    if best is None:
        return None, ""
    return best[1], best[2]


def sided_region_id(rule: BodyRegionRule, side: str) -> str:
    if not rule.sided or side == "center":
        return rule.region_id
    return f"{rule.region_id}_{'l' if side == 'left' else 'r'}"


def sided_region_label(rule: BodyRegionRule, side: str) -> str:
    if not rule.sided or side == "center":
        return rule.label
    return f"{rule.label} ({'Left' if side == 'left' else 'Right'})"


def build_body_region_map(
    mesh: object,
    skeleton: object | None,
    *,
    rules: Sequence[BodyRegionRule] = DEFAULT_BODY_REGION_RULES,
    minimum_weight: float = DEFAULT_MINIMUM_REGION_WEIGHT,
    submesh_indices: Iterable[int] | None = None,
    bone_palette: Sequence[int] | None = None,
    primary_influence_only: bool = True,
) -> BodyRegionMap:
    """Segment a skinned mesh into named body regions using its skin weights.

    ``bone_palette`` maps a mesh's influence slots to skeleton bone indices;
    PAC meshes need it because their slots are per-mesh tokens, not bone
    indices. Pass the result of ``resolve_pac_bone_palette``. Without it the
    slots are taken as bone indices directly, which is only right for formats
    that store them that way.

    ``primary_influence_only`` keeps just each vertex's heaviest influence.
    PAC weights are sorted descending and only the first slot decodes reliably
    today, so the default trades the rig's soft falloff for regions that are
    anatomically correct. Turn it off for formats whose every influence
    decodes.
    """

    bones = tuple(getattr(skeleton, "bones", ()) or ())
    diagnostics: list[str] = []
    if not bones:
        diagnostics.append(
            "No skeleton bones were available; region segmentation needs the matching .pab."
        )
    palette = tuple(int(value) for value in bone_palette) if bone_palette else ()
    # An empty palette when one was asked for means the slots could not be
    # resolved. Falling back to slots-as-bone-indices would silently label the
    # wrong anatomy, so claim nothing instead.
    palette_unresolved = bone_palette is not None and not palette
    if palette_unresolved:
        diagnostics.append(
            "No bone palette resolved for this mesh, so no influence slot could be named. "
            "Regions are left empty rather than guessed."
        )
    if primary_influence_only:
        diagnostics.append(
            "Only each vertex's heaviest influence was used, so regions carry no falloff."
        )
    threshold = max(0.0, float(minimum_weight))

    assignments, unmapped_bone_names = _assign_bones(bones, rules)
    if bones and not assignments:
        diagnostics.append(
            "No bone name matched a region rule; the rig naming is unknown to the rule table."
        )

    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    selected = _selected_submesh_indices(submeshes, submesh_indices)

    accumulator = _WeightAccumulator(threshold, palette, bool(primary_influence_only))
    if not palette_unresolved:
        for submesh_index in selected:
            accumulator.add_submesh(submesh_index, submeshes[submesh_index], assignments)

    origins = _bone_origins(bones)
    regions = _build_regions(assignments, accumulator, bones, origins, accumulator.live_bones)

    if accumulator.unskinned_vertex_count:
        diagnostics.append(
            f"{accumulator.unskinned_vertex_count} vertices carry no usable skin weights "
            "and were left out of every region."
        )
    if unmapped_bone_names:
        diagnostics.append(
            f"{len(unmapped_bone_names)} bone names matched no rule; "
            f"{accumulator.unmapped_weight_fraction * 100.0:.1f}% of skin weight is unclaimed."
        )

    return BodyRegionMap(
        topology_fingerprint=mesh_topology_fingerprint(mesh, selected or None),
        regions=regions,
        skeleton_source=str(getattr(skeleton, "path", "") or ""),
        skeleton_bone_count=len(bones),
        mapped_bone_count=sum(len(indices) for indices, _rule, _side in assignments.values()),
        unmapped_bone_names=unmapped_bone_names,
        unmapped_weight_fraction=accumulator.unmapped_weight_fraction,
        skinned_vertex_count=accumulator.skinned_vertex_count,
        unskinned_vertex_count=accumulator.unskinned_vertex_count,
        diagnostics=tuple(diagnostics),
    )


def body_region_morph_selection(region: BodyRegion) -> tuple[MeshMorphVertexWeight, ...]:
    """Convert a region into the weighted selection a morph definition expects."""

    return tuple(
        MeshMorphVertexWeight(part.submesh_index, vertex_index, weight)
        for part in region.parts
        for vertex_index, weight in zip(part.vertex_indices, part.weights)
    )


def body_region_local_basis(region: BodyRegion) -> tuple[Vec3, Vec3, Vec3]:
    """Orthonormal basis for a region, with the bone axis on Y.

    Morph rules address the basis by axis name, and ``MESH_MORPH_AXES`` puts Y
    at index 1, so a rule with ``axis="y"`` acts along the limb while X and Z
    span the cross-section a size slider expands.
    """

    axis_y = _normalized(region.axis.direction) or (0.0, 1.0, 0.0)
    helper: Vec3 = (1.0, 0.0, 0.0) if abs(axis_y[0]) < 0.9 else (0.0, 0.0, 1.0)
    axis_x = _normalized(_cross(helper, axis_y))
    if axis_x is None:
        axis_x = (1.0, 0.0, 0.0)
    axis_z = _cross(axis_x, axis_y)
    return (axis_x, axis_y, axis_z)


def dominant_region_by_vertex(region_map: BodyRegionMap) -> dict[tuple[int, int], str]:
    """Map every claimed vertex to the region holding the largest share of it."""

    best: dict[tuple[int, int], tuple[float, str]] = {}
    for region in region_map.regions:
        for part in region.parts:
            for vertex_index, weight in zip(part.vertex_indices, part.weights):
                key = (part.submesh_index, vertex_index)
                current = best.get(key)
                if current is None or weight > current[0]:
                    best[key] = (weight, region.region_id)
    return {key: region_id for key, (_weight, region_id) in best.items()}


def _selected_submesh_indices(
    submeshes: Sequence[object],
    submesh_indices: Iterable[int] | None,
) -> tuple[int, ...]:
    if submesh_indices is None:
        return tuple(range(len(submeshes)))
    selected: set[int] = set()
    for raw_index in submesh_indices:
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(submeshes):
            selected.add(index)
    return tuple(sorted(selected))


def _assign_bones(
    bones: Sequence[object],
    rules: Sequence[BodyRegionRule],
) -> tuple[dict[str, tuple[tuple[int, ...], BodyRegionRule, str]], tuple[str, ...]]:
    """Group bone indices by resolved region id, and collect what matched nothing."""

    grouped: dict[str, tuple[list[int], BodyRegionRule, str]] = {}
    unmapped: list[str] = []
    for bone_index, bone in enumerate(bones):
        name = str(getattr(bone, "name", "") or "")
        index = _coerce_bone_index(getattr(bone, "index", bone_index), bone_index)
        rule, _pattern = classify_bone(name, rules)
        if rule is None:
            if name:
                unmapped.append(name)
            continue
        side = bone_side(name) if rule.sided else "center"
        region_id = sided_region_id(rule, side)
        entry = grouped.get(region_id)
        if entry is None:
            grouped[region_id] = ([index], rule, side)
        else:
            entry[0].append(index)
    assignments = {
        region_id: (tuple(sorted(set(indices))), rule, side)
        for region_id, (indices, rule, side) in grouped.items()
    }
    return assignments, tuple(dict.fromkeys(unmapped))


def _coerce_bone_index(value: object, fallback: int) -> int:
    try:
        index = int(value)
    except (TypeError, ValueError):
        return fallback
    return index if index >= 0 else fallback


class _WeightAccumulator:
    """Accumulates normalized per-vertex region weight across submeshes."""

    def __init__(
        self,
        threshold: float,
        palette: Sequence[int] = (),
        primary_influence_only: bool = False,
    ) -> None:
        self._threshold = threshold
        self._palette = tuple(palette)
        self._primary_only = bool(primary_influence_only)
        self._parts: dict[str, dict[int, list[tuple[int, float]]]] = {}
        self._resolved: dict[str, tuple[BodyRegionWeights, ...]] = {}
        self.live_bones: set[int] = set()
        self.skinned_vertex_count = 0
        self.unskinned_vertex_count = 0
        self._claimed_weight = 0.0
        self._total_weight = 0.0

    @property
    def unmapped_weight_fraction(self) -> float:
        if self._total_weight <= 0.0:
            return 0.0
        return max(0.0, 1.0 - (self._claimed_weight / self._total_weight))

    def add_submesh(
        self,
        submesh_index: int,
        submesh: object,
        assignments: Mapping[str, tuple[tuple[int, ...], BodyRegionRule, str]],
    ) -> None:
        region_by_bone: dict[int, str] = {
            bone_index: region_id
            for region_id, (bone_indices, _rule, _side) in assignments.items()
            for bone_index in bone_indices
        }
        vertex_count = len(tuple(getattr(submesh, "vertices", ()) or ()))
        all_indices = tuple(getattr(submesh, "bone_indices", ()) or ())
        all_weights = tuple(getattr(submesh, "bone_weights", ()) or ())
        for vertex_index in range(vertex_count):
            influences = self._resolved_influences(all_indices, all_weights, vertex_index)
            total = sum(weight for _bone, weight in influences)
            if total <= 0.0 or not math.isfinite(total):
                self.unskinned_vertex_count += 1
                continue
            self.skinned_vertex_count += 1
            self._total_weight += 1.0
            shares: dict[str, float] = {}
            for bone_index, weight in influences:
                self.live_bones.add(bone_index)
                region_id = region_by_bone.get(bone_index)
                if region_id is None:
                    continue
                shares[region_id] = shares.get(region_id, 0.0) + (weight / total)
            for region_id, share in shares.items():
                self._claimed_weight += share
                if share < self._threshold:
                    continue
                self._parts.setdefault(region_id, {}).setdefault(submesh_index, []).append(
                    (vertex_index, min(1.0, share))
                )

    def _resolved_influences(
        self,
        all_indices: Sequence[object],
        all_weights: Sequence[object],
        vertex_index: int,
    ) -> tuple[tuple[int, float], ...]:
        """Slots through the palette, optionally reduced to the heaviest one."""

        influences = _influences(all_indices, all_weights, vertex_index)
        if self._primary_only and influences:
            influences = (max(influences, key=lambda item: item[1]),)
        if not self._palette:
            return influences
        resolved: list[tuple[int, float]] = []
        for slot, weight in influences:
            if 0 <= slot < len(self._palette):
                resolved.append((self._palette[slot], weight))
        return tuple(resolved)

    def parts_for(self, region_id: str) -> tuple[BodyRegionWeights, ...]:
        cached = self._resolved.get(region_id)
        if cached is not None:
            return cached
        resolved: list[BodyRegionWeights] = []
        for submesh_index, rows in sorted(self._parts.get(region_id, {}).items()):
            ordered = sorted(rows)
            resolved.append(
                BodyRegionWeights(
                    submesh_index=submesh_index,
                    vertex_indices=tuple(vertex_index for vertex_index, _weight in ordered),
                    weights=tuple(weight for _vertex_index, weight in ordered),
                )
            )
        parts = tuple(resolved)
        self._resolved[region_id] = parts
        return parts


def _influences(
    all_indices: Sequence[object],
    all_weights: Sequence[object],
    vertex_index: int,
) -> tuple[tuple[int, float], ...]:
    if vertex_index >= len(all_indices) or vertex_index >= len(all_weights):
        return ()
    raw_indices = tuple(all_indices[vertex_index] or ())
    raw_weights = tuple(all_weights[vertex_index] or ())
    influences: list[tuple[int, float]] = []
    for raw_index, raw_weight in zip(raw_indices, raw_weights):
        try:
            bone_index = int(raw_index)
            weight = float(raw_weight)
        except (TypeError, ValueError, OverflowError):
            continue
        if bone_index < 0 or not math.isfinite(weight) or weight <= 0.0:
            continue
        influences.append((bone_index, weight))
    return tuple(influences)


def _build_regions(
    assignments: Mapping[str, tuple[tuple[int, ...], BodyRegionRule, str]],
    accumulator: _WeightAccumulator,
    bones: Sequence[object],
    origins: Mapping[int, Vec3],
    live_bones: Sequence[int] | set[int] = (),
) -> tuple[BodyRegion, ...]:
    regions: list[BodyRegion] = []
    dominant = _dominant_counts(assignments, accumulator)
    for region_id, (bone_indices, rule, side) in assignments.items():
        parts = accumulator.parts_for(region_id)
        weights = tuple(weight for part in parts for weight in part.weights)
        regions.append(
            BodyRegion(
                region_id=region_id,
                label=sided_region_label(rule, side),
                group=rule.group,
                side=side,
                bone_indices=bone_indices,
                bone_names=tuple(
                    str(getattr(bones[index], "name", "") or "")
                    for index in bone_indices
                    if 0 <= index < len(bones)
                ),
                parts=parts,
                axis=_region_axis(bone_indices, bones, origins, live_bones),
                vertex_count=len(weights),
                dominant_vertex_count=dominant.get(region_id, 0),
                peak_weight=max(weights, default=0.0),
                total_weight=math.fsum(weights),
            )
        )
    regions.sort(key=lambda region: (BODY_REGION_GROUPS.index(region.group), region.region_id))
    return tuple(regions)


def _dominant_counts(
    assignments: Mapping[str, tuple[tuple[int, ...], BodyRegionRule, str]],
    accumulator: _WeightAccumulator,
) -> dict[str, int]:
    best: dict[tuple[int, int], tuple[float, str]] = {}
    for region_id in assignments:
        for part in accumulator.parts_for(region_id):
            for vertex_index, weight in zip(part.vertex_indices, part.weights):
                key = (part.submesh_index, vertex_index)
                current = best.get(key)
                if current is None or weight > current[0]:
                    best[key] = (weight, region_id)
    counts: dict[str, int] = {}
    for _weight, region_id in best.values():
        counts[region_id] = counts.get(region_id, 0) + 1
    return counts


def _bone_origins(bones: Sequence[object]) -> dict[int, Vec3]:
    """World bind translation per bone index.

    ``bind_matrix`` is the global bind pose here, matching how the skinning
    summary treats it, but the row/column storage order varies by source file,
    so the larger-magnitude translation wins the same way the model preview
    resolves it.
    """

    origins: dict[int, Vec3] = {}
    for bone_index, bone in enumerate(bones):
        index = _coerce_bone_index(getattr(bone, "index", bone_index), bone_index)
        matrix = tuple(getattr(bone, "bind_matrix", ()) or ())
        candidates: list[tuple[float, Vec3]] = []
        if len(matrix) >= 16:
            for slots in ((12, 13, 14), (3, 7, 11)):
                point = _vec3(tuple(matrix[slot] for slot in slots))
                if point is not None:
                    candidates.append((_length(point), point))
        if candidates:
            origins[index] = max(candidates, key=lambda item: item[0])[1]
            continue
        local = _vec3(tuple(getattr(bone, "position", ()) or ()))
        if local is not None:
            origins[index] = local
    return origins


def _region_axis(
    bone_indices: Sequence[int],
    bones: Sequence[object],
    origins: Mapping[int, Vec3],
    live_bones: Sequence[int] | set[int] = (),
) -> BodyRegionAxis:
    """Derive a pivot and axis from the region's own bones.

    The origin is the region's root joint; the direction points at the next
    joint down the chain, which is the axis a limb slider needs to scale along
    or taper toward.

    Only bones that actually carry skin steer the direction. Rigs hang helper
    bones off one side and not the other — the left thigh here owns an extra
    glute helper — and letting those vote makes a left slider behave measurably
    differently from its mirror.
    """

    members = {int(index) for index in bone_indices}
    placed = [index for index in sorted(members) if index in origins]
    if not placed:
        return BodyRegionAxis()

    parents = _parent_indices(bones)
    roots = [index for index in placed if parents.get(index, -1) not in members]
    origin = _mean(tuple(origins[index] for index in (roots or placed)))

    live = {int(index) for index in live_bones}
    outgoing_bones = [
        child
        for child, parent in parents.items()
        if parent in members and child not in members and child in origins
    ]
    if outgoing_bones:
        # Follow the joint that continues the limb, not the mean of every
        # child. Rigs hang helpers off one side only — the left thigh here
        # carries an extra glute bone — and averaging them in tilts a slider's
        # axis away from its mirror. The continuing joint is the one carrying
        # the rest of the skeleton beneath it.
        subtree = _subtree_sizes(bones, parents)
        best = max(
            outgoing_bones,
            key=lambda child: (child in live, subtree.get(child, 0), -child),
        )
        return _axis_between(origin, origins[best], "child_joint")

    interior = [origins[index] for index in placed if index not in roots]
    if interior:
        return _axis_between(origin, _mean(tuple(interior)), "region_extent")

    for root in roots:
        parent = parents.get(root, -1)
        if parent in origins:
            axis = _axis_between(origins[parent], origin, "parent_axis")
            return BodyRegionAxis(origin, axis.direction, axis.length, "parent_axis")
    return BodyRegionAxis(origin=origin)


def _subtree_sizes(bones: Sequence[object], parents: Mapping[int, int]) -> dict[int, int]:
    """Bone count beneath each bone, itself included."""

    children: dict[int, list[int]] = {}
    for child, parent in parents.items():
        if parent in parents and parent != child:
            children.setdefault(parent, []).append(child)
    sizes: dict[int, int] = {}

    def measure(index: int, seen: frozenset[int]) -> int:
        if index in sizes:
            return sizes[index]
        if index in seen:
            return 0
        total = 1
        for child in children.get(index, ()):
            total += measure(child, seen | {index})
        sizes[index] = total
        return total

    for index in parents:
        measure(index, frozenset())
    return sizes


def _parent_indices(bones: Sequence[object]) -> dict[int, int]:
    parents: dict[int, int] = {}
    for bone_index, bone in enumerate(bones):
        index = _coerce_bone_index(getattr(bone, "index", bone_index), bone_index)
        try:
            parent = int(getattr(bone, "parent_index", -1))
        except (TypeError, ValueError):
            parent = -1
        parents[index] = parent
    return parents


def _axis_between(origin: Vec3, tip: Vec3, source: str) -> BodyRegionAxis:
    delta = (tip[0] - origin[0], tip[1] - origin[1], tip[2] - origin[2])
    length = _length(delta)
    if length <= 1.0e-9:
        return BodyRegionAxis(origin=origin, source="degenerate")
    return BodyRegionAxis(
        origin=origin,
        direction=(delta[0] / length, delta[1] / length, delta[2] / length),
        length=length,
        source=source,
    )


def _mean(points: Sequence[Vec3]) -> Vec3:
    if not points:
        return (0.0, 0.0, 0.0)
    count = float(len(points))
    return (
        math.fsum(point[0] for point in points) / count,
        math.fsum(point[1] for point in points) / count,
        math.fsum(point[2] for point in points) / count,
    )


def _cross(left: Vec3, right: Vec3) -> Vec3:
    return (
        (left[1] * right[2]) - (left[2] * right[1]),
        (left[2] * right[0]) - (left[0] * right[2]),
        (left[0] * right[1]) - (left[1] * right[0]),
    )


def _normalized(value: Vec3) -> Vec3 | None:
    length = _length(value)
    if length <= 1.0e-9:
        return None
    return (value[0] / length, value[1] / length, value[2] / length)


def _length(value: Vec3) -> float:
    return math.sqrt((value[0] * value[0]) + (value[1] * value[1]) + (value[2] * value[2]))


def _vec3(value: object) -> Vec3 | None:
    try:
        point = (float(value[0]), float(value[1]), float(value[2]))  # type: ignore[index]
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    return point if all(math.isfinite(component) for component in point) else None
