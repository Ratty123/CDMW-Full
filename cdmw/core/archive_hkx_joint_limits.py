"""Ragdoll and physics-system joint limits in Crimson Desert's HKX files.

Constraint data in the 2024.2 files is a fixed sequence of Havok constraint
atoms, each starting with a u16 atom type. Across every installed
``character/bin__/havokphysics`` file the atoms sit at fixed offsets per class
(all 945 hinges, 2,135 of 2,137 ragdoll constraints), so a limit is located by
its atom type rather than guessed from a float's value:

* ``hknpLimitedHingeConstraintData``: angular friction (type 17) at 256 and the
  hinge angle limit (type 14) at 272, min/max radians at +8/+12.
* ``hknpRagdollConstraintData``: angular friction (17) at 304, twist limit (15)
  at 320 with min/max at +8/+12, cone limit (16) at 352 with its maximum at +24,
  and plane limit (16) at 400 with min/max at +20/+24.

Friction torque sits at +8 of the friction atom. Cone and plane limits also
cache ``1/cos`` and ``tan`` of their angles at +28/+32 and +36/+40. The game's
values match that rule within a few float32 ulps for every angle between 1 and
85 degrees and between 95 and 179 degrees; 0, 90 and 180 degrees use clamped or
sentinel values, so edits are limited to the regular ranges and a disabled
limit (sentinel angle) stays disabled.

Names come from ``hknpConstraintCinfo``: a PTCH pointer to the constraint data
at +0, body indices at +8 (child) and +16 (parent), and an ``hkStringPtr`` name
at +32; body names are the ``hkStringPtr`` at +24 of each
``hknpPhysicsSystemData::ExtendedBodyCinfo``.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple

from cdmw.core.archive_hkx_tagfile_model import (
    HkxTagfileModel,
    HkxTagfileRefused,
    copy_hkx_tagfile_model,
)

HINGE_CLASS = "hknpLimitedHingeConstraintData"
RAGDOLL_CLASS = "hknpRagdollConstraintData"
BREAKABLE_CLASS = "hknpBreakableConstraintData"
_CINFO_CLASS = "hknpConstraintCinfo"
_CINFO_STRIDE = 48
_BODY_CLASS = "hknpPhysicsSystemData::ExtendedBodyCinfo"
_BODY_STRIDE = 208

_FRICTION_ATOM = 17
_ANG_LIMIT_ATOM = 14
_TWIST_LIMIT_ATOM = 15
_CONE_LIMIT_ATOM = 16

_MAX_FRICTION_TORQUE = 1.0e6


@dataclass(frozen=True)
class HkxJointFieldSpec:
    key: str
    atom_offset: int
    atom_type: int
    value_offset: int
    kind: str  # "angle" or "torque"
    pair: Optional[str] = None  # the other end of a min/max range
    cached: bool = False  # cone/plane limits cache 1/cos and tan of the angle


_FIELD_SPECS: Mapping[str, Tuple[HkxJointFieldSpec, ...]] = {
    HINGE_CLASS: (
        HkxJointFieldSpec("bend_min", 272, _ANG_LIMIT_ATOM, 8, "angle", pair="bend_max"),
        HkxJointFieldSpec("bend_max", 272, _ANG_LIMIT_ATOM, 12, "angle", pair="bend_min"),
        HkxJointFieldSpec("friction", 256, _FRICTION_ATOM, 8, "torque"),
    ),
    RAGDOLL_CLASS: (
        HkxJointFieldSpec("twist_min", 320, _TWIST_LIMIT_ATOM, 8, "angle", pair="twist_max"),
        HkxJointFieldSpec("twist_max", 320, _TWIST_LIMIT_ATOM, 12, "angle", pair="twist_min"),
        HkxJointFieldSpec("cone_max", 352, _CONE_LIMIT_ATOM, 24, "angle", cached=True),
        HkxJointFieldSpec("plane_min", 400, _CONE_LIMIT_ATOM, 20, "angle", pair="plane_max", cached=True),
        HkxJointFieldSpec("plane_max", 400, _CONE_LIMIT_ATOM, 24, "angle", pair="plane_min", cached=True),
        HkxJointFieldSpec("friction", 304, _FRICTION_ATOM, 8, "torque"),
    ),
}

# Editable ranges in degrees. Cached limits avoid the clamped 0/90/180 degree values.
_ANGLE_RANGES: Mapping[str, Tuple[float, float]] = {
    "bend_min": (-180.0, 180.0),
    "bend_max": (-180.0, 180.0),
    "twist_min": (-180.0, 180.0),
    "twist_max": (-180.0, 180.0),
    "cone_max": (1.0, 85.0),
    "plane_min": (1.0, 85.0),
    "plane_max": (95.0, 179.0),
}


@dataclass(frozen=True)
class HkxJointField:
    key: str
    value: float  # degrees for angles, torque for friction
    editable: bool
    reason: str = ""
    minimum: float = 0.0
    maximum: float = 0.0


@dataclass(frozen=True)
class HkxJoint:
    index: int  # position in the constraint list
    data_item: int  # constraint data ITEM holding the limits
    class_name: str
    name: str
    child_body: str
    parent_body: str
    breakable: bool
    fields: Tuple[HkxJointField, ...]
    note: str = ""


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def hkx_limit_angle_cache(angle: float) -> Tuple[float, float]:
    """Return the (1/cos, tan) pair the game caches for a cone or plane limit angle in radians."""

    return _f32(1.0 / math.cos(angle)), _f32(math.tan(angle))


def _read_f32(payload: bytes, offset: int) -> float:
    return struct.unpack_from("<f", payload, offset)[0]


def _atom_type(payload: bytes, offset: int) -> int:
    return struct.unpack_from("<H", payload, offset)[0]


def _string_at(model: HkxTagfileModel, item_index: int, offset: int) -> str:
    for reference in model.references_from(item_index):
        if reference.offset == offset and reference.is_patch and 0 < reference.target_item < len(model.items):
            if model.type_name(reference.target_item) == "char":
                return bytes(model.items[reference.target_item].payload).rstrip(b"\0").decode("utf-8", "replace")
    return ""


def short_body_name(name: str) -> str:
    """'_Leg_Ragdoll_Bip01 L Thigh' -> 'L Thigh'; other names are returned unchanged."""

    marker = "Bip01 "
    if marker in name:
        return name.split(marker, 1)[1].strip() or name
    return name


def _first_item(model: HkxTagfileModel, type_name: str) -> Optional[int]:
    return next((index for index in range(1, len(model.items)) if model.type_name(index) == type_name), None)


def _body_names(model: HkxTagfileModel) -> List[str]:
    body_item = _first_item(model, _BODY_CLASS)
    if body_item is None:
        return []
    names = [""] * model.items[body_item].count
    for reference in model.references_from(body_item):
        element, local = divmod(reference.offset, _BODY_STRIDE)
        if local == 24 and reference.is_patch and model.type_name(reference.target_item) == "char":
            names[element] = bytes(model.items[reference.target_item].payload).rstrip(b"\0").decode("utf-8", "replace")
    return names


def _resolve_constraint_data(model: HkxTagfileModel, item_index: int) -> Tuple[int, bool]:
    if model.type_name(item_index) != BREAKABLE_CLASS:
        return item_index, False
    for reference in model.references_from(item_index):
        if reference.offset == 40 and not reference.is_patch:
            return reference.target_item, True
    return item_index, True


def _field_value(spec: HkxJointFieldSpec, payload: bytes) -> float:
    raw = _read_f32(payload, spec.atom_offset + spec.value_offset)
    return math.degrees(raw) if spec.kind == "angle" else raw


def _field_state(spec: HkxJointFieldSpec, payload: bytes) -> Tuple[bool, str]:
    if len(payload) < spec.atom_offset + 48 or _atom_type(payload, spec.atom_offset) != spec.atom_type:
        return False, "The limit is not at the position every shipped file uses."
    if spec.kind == "torque":
        return True, ""
    if not spec.cached:
        return True, ""
    degrees_range = _ANGLE_RANGES[spec.key]
    value = _field_value(spec, payload)
    if not degrees_range[0] <= round(value, 4) <= degrees_range[1]:
        return False, "This limit is switched off or at a special angle the game stores differently."
    for cached_spec in _FIELD_SPECS[RAGDOLL_CLASS]:
        if cached_spec.atom_offset == spec.atom_offset and cached_spec.key != spec.key and cached_spec.pair == spec.key:
            other = _field_value(cached_spec, payload)
            other_range = _ANGLE_RANGES[cached_spec.key]
            if not other_range[0] <= round(other, 4) <= other_range[1]:
                return False, "The other end of this range is switched off, so the range stays as shipped."
    return True, ""


def read_hkx_joints(model: HkxTagfileModel) -> List[HkxJoint]:
    """List every constraint of a physics system with its readable limits."""

    cinfo_item = _first_item(model, _CINFO_CLASS)
    if cinfo_item is None:
        return []
    bodies = _body_names(model)
    cinfo = bytes(model.items[cinfo_item].payload)
    data_items: Dict[int, int] = {}
    for reference in model.references_from(cinfo_item):
        element, local = divmod(reference.offset, _CINFO_STRIDE)
        if local == 0 and reference.is_patch:
            data_items[element] = reference.target_item
    joints = []
    for element in range(model.items[cinfo_item].count):
        child_index, parent_index = struct.unpack_from("<I4xI", cinfo, element * _CINFO_STRIDE + 8)
        child = bodies[child_index] if child_index < len(bodies) else f"body {child_index}"
        parent = bodies[parent_index] if parent_index < len(bodies) else f"body {parent_index}"
        name = _string_at(model, cinfo_item, element * _CINFO_STRIDE + 32)
        target = data_items.get(element, 0)
        if not target:
            joints.append(HkxJoint(element, 0, "", name, child, parent, False, (), "No constraint data."))
            continue
        data_item, breakable = _resolve_constraint_data(model, target)
        class_name = model.type_name(data_item)
        payload = bytes(model.items[data_item].payload)
        fields = []
        for spec in _FIELD_SPECS.get(class_name, ()):
            editable, reason = _field_state(spec, payload)
            value = _field_value(spec, payload) if len(payload) >= spec.atom_offset + spec.value_offset + 4 else 0.0
            if spec.kind == "angle":
                low, high = _ANGLE_RANGES[spec.key]
            else:
                low, high = 0.0, _MAX_FRICTION_TORQUE
            fields.append(HkxJointField(spec.key, value, editable, reason, low, high))
        note = "" if class_name in _FIELD_SPECS else "This joint type has no adjustable limits."
        joints.append(HkxJoint(element, data_item, class_name, name, child, parent, breakable, tuple(fields), note))
    return joints


def apply_hkx_joint_edits(model: HkxTagfileModel, edits: Mapping[Tuple[int, str], float]) -> HkxTagfileModel:
    """Return a copy of ``model`` with joint fields changed.

    ``edits`` maps (constraint data item, field key) to a value in degrees for
    angles or in the file's torque units for friction. Every edit is checked
    against the reading rules above; nothing is written if any edit is refused.
    """

    joints_by_item = {joint.data_item: joint for joint in read_hkx_joints(model) if joint.data_item}
    edited = copy_hkx_tagfile_model(model)
    pending: Dict[int, Dict[str, float]] = {}
    for (data_item, key), value in edits.items():
        joint = joints_by_item.get(data_item)
        if joint is None:
            raise HkxTagfileRefused("bad_edit", f"Item {data_item} is not the constraint data of a listed joint.")
        field = next((candidate for candidate in joint.fields if candidate.key == key), None)
        if field is None:
            raise HkxTagfileRefused("bad_edit", f"{joint.class_name} has no {key} limit.")
        if not field.editable:
            raise HkxTagfileRefused("unproven_edit", field.reason or f"{key} cannot be edited.")
        if not math.isfinite(value) or not field.minimum <= value <= field.maximum:
            raise HkxTagfileRefused("bad_edit", f"{key} must be between {field.minimum:g} and {field.maximum:g}.")
        pending.setdefault(data_item, {})[key] = float(value)
    for data_item, changes in pending.items():
        joint = joints_by_item[data_item]
        current = {field.key: field.value for field in joint.fields}
        current.update(changes)
        specs = {spec.key: spec for spec in _FIELD_SPECS[joint.class_name]}
        for key in changes:
            pair = specs[key].pair
            if pair is not None:
                low_key, high_key = (key, pair) if key.endswith("_min") else (pair, key)
                if current[low_key] > current[high_key] + 1e-6:
                    raise HkxTagfileRefused("bad_edit", f"{joint.name or joint.child_body}: the minimum is above the maximum.")
        payload = edited.items[data_item].payload
        for key, value in changes.items():
            spec = specs[key]
            stored = _f32(math.radians(value) if spec.kind == "angle" else value)
            if stored == _read_f32(payload, spec.atom_offset + spec.value_offset):
                continue
            struct.pack_into("<f", payload, spec.atom_offset + spec.value_offset, stored)
            if spec.cached:
                secant, tangent = hkx_limit_angle_cache(_f32(stored))
                cache_slot = spec.value_offset - 20  # min (+20) -> +28/+36, max (+24) -> +32/+40
                struct.pack_into("<f", payload, spec.atom_offset + 28 + cache_slot, secant)
                struct.pack_into("<f", payload, spec.atom_offset + 36 + cache_slot, tangent)
    return edited


def hkx_joint_cache_deviation_ulps(payload: bytes, atom_offset: int) -> List[int]:
    """Largest float32 ulp gap between a shipped cone/plane cache and ``hkx_limit_angle_cache`` (for research)."""

    def bits(value: float) -> int:
        return struct.unpack("<i", struct.pack("<f", value))[0]

    gaps = []
    for value_offset, cache_slot in ((20, 0), (24, 4)):
        angle = _read_f32(payload, atom_offset + value_offset)
        if not math.radians(1.0) - 1e-6 <= abs(angle) <= math.radians(179.0) + 1e-6 or abs(math.degrees(angle) - 90.0) < 5.0 - 1e-6:
            continue
        secant, tangent = hkx_limit_angle_cache(angle)
        gaps.append(abs(bits(secant) - bits(_read_f32(payload, atom_offset + 28 + cache_slot))))
        gaps.append(abs(bits(tangent) - bits(_read_f32(payload, atom_offset + 36 + cache_slot))))
    return gaps


__all__ = [
    "HINGE_CLASS",
    "RAGDOLL_CLASS",
    "HkxJoint",
    "HkxJointField",
    "apply_hkx_joint_edits",
    "hkx_joint_cache_deviation_ulps",
    "hkx_limit_angle_cache",
    "read_hkx_joints",
    "short_body_name",
]
