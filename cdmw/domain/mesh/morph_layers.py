"""Independent anatomical macro values composed over retained manual morphs.

The catalogue coordinates the existing region Size definitions. It does not
infer a new anatomical axis or replace the mesh fitting engine.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Mapping, Sequence

from .body_region_sliders import DEFAULT_BODY_REGION_SLIDER_TEMPLATES
from .body_regions import DEFAULT_BODY_REGION_RULES
from .morph import MeshMorphDefinition, MeshMorphProfile, MeshMorphRule, MeshMorphValuePreset


MESH_MORPH_MACRO_MIN_PERCENT = -100.0
MESH_MORPH_MACRO_MAX_PERCENT = 100.0


def _named_values(
    values: Mapping[str, object] | Sequence[tuple[str, object]], label: str
) -> dict[str, float]:
    entries = values.items() if isinstance(values, Mapping) else values
    if not isinstance(values, (Mapping, list, tuple)):
        raise ValueError(f"{label}s must be a mapping or a sequence of named values.")
    normalized: dict[str, float] = {}
    for raw_key, raw_value in entries:
        if not isinstance(raw_key, str) or not raw_key or raw_key != raw_key.strip():
            raise ValueError(f"{label} requires an exact nonempty id.")
        if raw_key in normalized or isinstance(raw_value, bool):
            raise ValueError(f"{label} requires unique ids and finite numeric values.")
        try:
            value = float(raw_value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{label} must be finite.") from exc
        if not math.isfinite(value):
            raise ValueError(f"{label} must be finite.")
        normalized[raw_key] = value
    return normalized


@dataclass(frozen=True, slots=True)
class MeshMorphMacroDefinition:
    macro_id: str
    label: str
    description: str
    contributions: tuple[tuple[str, float], ...]
    min_percent: float = MESH_MORPH_MACRO_MIN_PERCENT
    max_percent: float = MESH_MORPH_MACRO_MAX_PERCENT

    def __post_init__(self) -> None:
        if not self.macro_id or not self.contributions or len(self.contributions) > 16:
            raise ValueError("Body controls require an id and a bounded set of contributions.")
        values = _named_values(self.contributions, "Body control contribution")
        if any(not 0.0 < abs(value) <= 1.0 for value in values.values()):
            raise ValueError("Body control coefficients must be nonzero and between -1 and 1.")
        if (self.min_percent, self.max_percent) != (-100.0, 100.0):
            raise ValueError("Body controls use the supported -100 to 100 percent range.")
        object.__setattr__(self, "contributions", tuple(values.items()))


# The Size rule expands across each region's own bone axis. Labels deliberately
# describe coordinated fullness/shape rather than claiming global width/depth.
_MACROS = (
    MeshMorphMacroDefinition(
        "shoulder_contour", "Shoulder contour",
        "Coordinates shoulder, upper torso and upper-arm fullness.",
        (("clavicle_l_size", 0.65), ("clavicle_r_size", 0.65),
         ("spine_upper_size", 0.20), ("upper_arm_l_size", 0.20),
         ("upper_arm_r_size", 0.20)),
    ),
    MeshMorphMacroDefinition(
        "waist_shape", "Waist shape",
        "Changes lower-torso fullness with a smaller pelvis and upper-torso transition.",
        (("spine_lower_size", 1.0), ("pelvis_size", 0.25),
         ("spine_upper_size", 0.20)),
    ),
    MeshMorphMacroDefinition(
        "hip_thigh_transition", "Hip-to-thigh transition",
        "Coordinates pelvis, hip and thigh fullness.",
        (("pelvis_size", 0.25), ("hip_l_size", 0.65), ("hip_r_size", 0.65),
         ("thigh_l_size", 0.45), ("thigh_r_size", 0.45)),
    ),
    MeshMorphMacroDefinition(
        "upper_body_balance", "Upper-body balance",
        "Coordinates upper torso, shoulders, upper arms and forearms.",
        (("spine_upper_size", 0.50), ("clavicle_l_size", 0.25),
         ("clavicle_r_size", 0.25), ("upper_arm_l_size", 0.40),
         ("upper_arm_r_size", 0.40), ("forearm_l_size", 0.15),
         ("forearm_r_size", 0.15)),
    ),
)


def _generated_template_matches(definition: MeshMorphDefinition, slider_id: str) -> bool:
    template = next(
        (item for item in DEFAULT_BODY_REGION_SLIDER_TEMPLATES if item.slider_id == slider_id),
        None,
    )
    return bool(
        template is not None
        and definition.source_kind == "procedural"
        and definition.mirror_mode == "off"
        and definition.rule == MeshMorphRule(
            kind=template.rule, axis=template.axis, amount=template.amount
        )
        and definition.min_percent == template.minimum_percent
        and definition.max_percent == template.maximum_percent
        and definition.default_percent == 0.0
    )


def mesh_morph_macros(profile: MeshMorphProfile) -> tuple[MeshMorphMacroDefinition, ...]:
    """Admit a control only when every required generated definition is present."""
    definitions = {item.definition_id: item for item in profile.definitions}
    return tuple(
        macro for macro in _MACROS
        if all(
            key in definitions and _generated_template_matches(definitions[key], "size")
            for key, _coefficient in macro.contributions
        )
    )


def compose_mesh_morph_values(
    profile: MeshMorphProfile,
    manual_values: Mapping[str, object] | Sequence[tuple[str, object]],
    macro_values: Mapping[str, object] | Sequence[tuple[str, object]] = (),
    *,
    symmetry_enabled: bool = False,
) -> dict[str, float]:
    """Compose without mutating either input; clamp only the evaluated result."""
    if not isinstance(symmetry_enabled, bool):
        raise ValueError("Body-control symmetry must be boolean.")
    manual = _validated_manual_values(profile, manual_values)
    if symmetry_enabled:
        pairs = mesh_morph_side_pairs(profile)
        if not pairs:
            raise ValueError("Linked sides require supported paired body controls.")
        for pair in pairs:
            mean = math.fsum((
                manual[pair.left_definition_id], manual[pair.right_definition_id]
            )) / 2.0
            manual[pair.left_definition_id] = mean
            manual[pair.right_definition_id] = mean
    macros = {item.macro_id: item for item in mesh_morph_macros(profile)}
    values = _named_values(macro_values, "Body control value")
    for key, value in values.items():
        if key not in macros:
            raise ValueError(f"Body control is unavailable for this profile: {key}")
        if not macros[key].min_percent <= value <= macros[key].max_percent:
            raise ValueError(f"Body control value is outside its range: {key}")
    contributions: dict[str, list[float]] = {key: [value] for key, value in manual.items()}
    for key in sorted(values):
        for definition_id, coefficient in macros[key].contributions:
            contributions[definition_id].append(values[key] * coefficient)
    return {
        definition.definition_id: min(
            definition.max_percent,
            max(definition.min_percent, math.fsum(contributions[definition.definition_id])),
        )
        for definition in profile.definitions
    }


@dataclass(frozen=True, slots=True)
class MeshMorphSidePair:
    pair_id: str
    label: str
    left_definition_id: str
    right_definition_id: str
    min_percent: float
    max_percent: float
    both_min_percent: float | None = None
    both_max_percent: float | None = None


def mesh_morph_side_pairs(profile: MeshMorphProfile) -> tuple[MeshMorphSidePair, ...]:
    """Pair only matching supported left/right region controls."""
    definitions = {item.definition_id: item for item in profile.definitions}
    pairs = []
    for region in DEFAULT_BODY_REGION_RULES:
        if not region.sided:
            continue
        for template in DEFAULT_BODY_REGION_SLIDER_TEMPLATES:
            left_id = f"{region.region_id}_l_{template.slider_id}"
            right_id = f"{region.region_id}_r_{template.slider_id}"
            if (
                left_id not in definitions or right_id not in definitions
                or not _generated_template_matches(definitions[left_id], template.slider_id)
                or not _generated_template_matches(definitions[right_id], template.slider_id)
            ):
                continue
            pairs.append(MeshMorphSidePair(
                pair_id=f"{region.region_id}_{template.slider_id}",
                label=f"{region.label} {template.label}",
                left_definition_id=left_id, right_definition_id=right_id,
                min_percent=template.minimum_percent,
                max_percent=template.maximum_percent,
            ))
    return tuple(pairs)


def mesh_morph_side_pair_limits(
    profile: MeshMorphProfile,
    manual_values: Mapping[str, object] | Sequence[tuple[str, object]],
    pair_id: str,
    *,
    side: str = "both",
) -> tuple[float, float]:
    """For Both, retain the side difference and expose its true movable range."""
    manual = _validated_manual_values(profile, manual_values)
    pair = _required_side_pair(profile, pair_id, side)
    if side != "both":
        return pair.min_percent, pair.max_percent
    left, right = manual[pair.left_definition_id], manual[pair.right_definition_id]
    mean = math.fsum((left, right)) / 2.0
    return (
        mean + max(pair.min_percent - left, pair.min_percent - right),
        mean + min(pair.max_percent - left, pair.max_percent - right),
    )


def update_mesh_morph_side_values(
    profile: MeshMorphProfile,
    manual_values: Mapping[str, object] | Sequence[tuple[str, object]],
    pair_id: str,
    percent: object,
    *,
    side: str = "both",
) -> dict[str, float]:
    """Set one side or shift both equally, refusing edits that erase offsets."""
    manual = _validated_manual_values(profile, manual_values)
    pair = _required_side_pair(profile, pair_id, side)
    value = _named_values(((pair_id, percent),), "Paired body control value")[pair_id]
    minimum, maximum = mesh_morph_side_pair_limits(profile, manual, pair_id, side=side)
    if not minimum <= value <= maximum:
        raise ValueError("Paired body control value is outside the range that preserves its side offsets.")
    if side == "left":
        manual[pair.left_definition_id] = value
    elif side == "right":
        manual[pair.right_definition_id] = value
    else:
        left, right = manual[pair.left_definition_id], manual[pair.right_definition_id]
        shift = value - math.fsum((left, right)) / 2.0
        manual[pair.left_definition_id] = left + shift
        manual[pair.right_definition_id] = right + shift
    return _validated_manual_values(profile, manual)


def _required_side_pair(profile: MeshMorphProfile, pair_id: str, side: str) -> MeshMorphSidePair:
    if side not in {"both", "left", "right"}:
        raise ValueError("Paired body control side must be both, left or right.")
    pair = next((item for item in mesh_morph_side_pairs(profile) if item.pair_id == pair_id), None)
    if pair is None:
        raise ValueError(f"Paired body control is unavailable for this profile: {pair_id}")
    return pair


def mesh_morph_profile_definition_fingerprint(profile: MeshMorphProfile) -> str:
    """Bind saved layers to deformation semantics, including authored geometry."""
    definitions = []
    for definition in sorted(profile.definitions, key=lambda item: item.definition_id):
        payload = asdict(definition)
        # A label change or a correction-only edit does not alter how a body
        # control addresses or combines the underlying body definitions.
        for key in (
            "label", "category", "garment_corrections",
            "correction_topology_fingerprint", "correction_base_geometry_fingerprint",
        ):
            payload.pop(key, None)
        definitions.append(payload)
    payload = {
        "topology_fingerprint": profile.topology_fingerprint,
        "definitions": definitions,
        "macro_catalog": [
            {"macro_id": item.macro_id, "contributions": item.contributions}
            for item in mesh_morph_macros(profile)
        ],
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_mesh_morph_layers(profile: MeshMorphProfile, preset: MeshMorphValuePreset) -> None:
    """Validate layered preset identity and reject a stale/forged effective result."""
    if preset.manual_values is None:
        return
    if (
        preset.profile_id != profile.profile_id
        or preset.topology_fingerprint != profile.topology_fingerprint
        or preset.profile_definition_fingerprint != mesh_morph_profile_definition_fingerprint(profile)
    ):
        raise ValueError("Body control layers do not match their profile definition identity.")
    expected = compose_mesh_morph_values(
        profile, preset.manual_values, preset.macro_values,
        symmetry_enabled=preset.symmetry_enabled,
    )
    actual = dict(preset.values)
    if set(actual) != set(expected) or any(
        not math.isclose(actual[key], value, rel_tol=0.0, abs_tol=1.0e-9)
        for key, value in expected.items()
    ):
        raise ValueError("Body control effective values do not match their retained layers.")


def _validated_manual_values(
    profile: MeshMorphProfile,
    values: Mapping[str, object] | Sequence[tuple[str, object]],
) -> dict[str, float]:
    manual = _named_values(values, "Manual morph value")
    definitions = {item.definition_id: item for item in profile.definitions}
    if set(manual) != set(definitions):
        raise ValueError("Manual values must identify every profile slider exactly once.")
    for key, value in manual.items():
        if not definitions[key].min_percent <= value <= definitions[key].max_percent:
            raise ValueError(f"Manual morph value is outside its slider range: {key}")
    return manual
