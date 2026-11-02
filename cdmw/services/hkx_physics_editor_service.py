"""Read and edit HKX physics files for the HKX Physics Editor.

The editor offers only edits the tagfile codec can prove at the byte level:

* joint limits and friction of ragdoll and physics-system constraints
  (``archive_hkx_joint_limits``), written in place;
* names reached through ``hkStringPtr`` at any length
  (``archive_hkx_structural_edits``), which relocates the file;
* replacing a collision file with another shipped collision file of the same
  container family, copied byte for byte.

``build_hkx_physics_edit`` parses its own output again and checks that every
requested change reads back and that joint edits touched nothing outside their
constraint records. Nothing here reads or writes game archives; callers pass
bytes in and package the result themselves.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_hkx_joint_limits import (
    HkxJoint,
    apply_hkx_joint_edits,
    read_hkx_joints,
    short_body_name,
)
from cdmw.core.archive_hkx_structural_edits import (
    hkx_string_items,
    replace_hkx_string_items,
)
from cdmw.core.archive_hkx_tagfile_model import (
    HkxTagfileModel,
    HkxTagfileRefused,
    parse_hkx_tagfile_model,
    serialize_hkx_tagfile_model,
)

KIND_RAGDOLL = "ragdoll"
KIND_PHYSICS_SYSTEM = "physics_system"
KIND_COLLISION = "collision"
KIND_OTHER = "other"

SHAPE_CLASSES = (
    "hknpConvexShape",
    "hknpBoxShape",
    "hknpCapsuleShape",
    "hknpSphereShape",
    "hknpCylinderShape",
    "hknpTriangleShape",
    "hknpMeshShape",
)

# Owner class of a string -> role key the dialog labels.
_NAME_ROLES = {
    "hkBone": "bone",
    "hknpPhysicsSystemData::ExtendedBodyCinfo": "body",
    "hknpConstraintCinfo": "joint",
    "hknpMaterial": "material",
    "hkRootLevelContainer::NamedVariant": "section",
    "hkSkeleton": "skeleton",
    "hknpRagdollData": "ragdoll",
    "HavokShapeNameProperty": "shape",
}

@dataclass(frozen=True)
class HkxNameRow:
    item: int
    text: str
    role: str


@dataclass(frozen=True)
class HkxCollisionSummary:
    pieces: Tuple[Tuple[str, int], ...]  # (shape class, count), most common first
    compound_children: int
    vertex_count: int


@dataclass(frozen=True)
class HkxPhysicsSession:
    path: str
    kind: str
    codec_status: str  # "exact", "refused" or "rebuild_mismatch"
    codec_message: str
    root_type: str
    has_patch_section: bool
    joints: Tuple[HkxJoint, ...] = ()
    names: Tuple[HkxNameRow, ...] = ()
    collision: Optional[HkxCollisionSummary] = None
    item_count: int = 0

    @property
    def editable(self) -> bool:
        return self.codec_status == "exact"

    @property
    def editable_joint_count(self) -> int:
        return sum(1 for joint in self.joints if any(item.editable for item in joint.fields))


@dataclass(frozen=True)
class HkxPhysicsEdits:
    joint_values: Mapping[Tuple[int, str], float] = field(default_factory=dict)
    renames: Mapping[int, str] = field(default_factory=dict)
    replacement: Optional[bytes] = None
    replacement_path: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.joint_values and not self.renames and self.replacement is None


@dataclass(frozen=True)
class HkxJointChange:
    joint: HkxJoint
    key: str
    old: float
    new: float


@dataclass(frozen=True)
class HkxPhysicsEditResult:
    data: bytes
    joint_changes: Tuple[HkxJointChange, ...] = ()
    renames: Tuple[Tuple[str, str], ...] = ()
    replaced_with: str = ""


def _classify(model: HkxTagfileModel) -> str:
    names = {model.type_name(index) for index in range(1, len(model.items))}
    if "hknpRagdollData" in names:
        return KIND_RAGDOLL
    if "hknpPhysicsSystemData" in names:
        return KIND_PHYSICS_SYSTEM
    if names & set(SHAPE_CLASSES):
        return KIND_COLLISION
    return KIND_OTHER


def _collision_summary(model: HkxTagfileModel) -> HkxCollisionSummary:
    counts: Counter[str] = Counter()
    compound_children = 0
    vertex_count = 0
    for index in range(1, len(model.items)):
        name = model.type_name(index)
        if name in SHAPE_CLASSES:
            counts[name] += 1
        elif name == "hkFreeListArrayElement<hknpShapeInstance>":
            compound_children += model.items[index].count
        elif name == "hkFloat3":
            vertex_count += model.items[index].count
    return HkxCollisionSummary(tuple(counts.most_common()), compound_children, vertex_count)


def _name_rows(model: HkxTagfileModel) -> Tuple[HkxNameRow, ...]:
    owners: Dict[int, str] = {}
    for reference in model.references:
        if reference.is_patch and reference.target_item not in owners:
            owners[reference.target_item] = _NAME_ROLES.get(model.type_name(reference.source_item), "other")
    return tuple(HkxNameRow(index, text, owners.get(index, "other")) for index, text in hkx_string_items(model))


def load_hkx_physics_session(data: bytes, path: str = "") -> HkxPhysicsSession:
    try:
        model = parse_hkx_tagfile_model(data)
    except HkxTagfileRefused as exc:
        return HkxPhysicsSession(path, KIND_OTHER, "refused", str(exc), "", False)
    root_type = model.type_name(1) if len(model.items) > 1 else ""
    kind = _classify(model)
    if serialize_hkx_tagfile_model(model) != data:
        return HkxPhysicsSession(path, kind, "rebuild_mismatch", "CDMW could not rebuild this file exactly.", root_type, model.has_patch_section)
    return HkxPhysicsSession(
        path=path,
        kind=kind,
        codec_status="exact",
        codec_message="",
        root_type=root_type,
        has_patch_section=model.has_patch_section,
        joints=tuple(read_hkx_joints(model)),
        names=_name_rows(model),
        collision=_collision_summary(model) if kind == KIND_COLLISION else None,
        item_count=len(model.items) - 1,
    )


def check_hkx_collision_replacement(target: HkxPhysicsSession, replacement_data: bytes) -> Tuple[bool, str]:
    """Return whether ``replacement_data`` can stand in for the collision file ``target``."""

    if target.kind != KIND_COLLISION:
        return False, "Only collision files can take another file's collision."
    candidate = load_hkx_physics_session(replacement_data)
    if candidate.codec_status != "exact":
        return False, f"The chosen file cannot be read safely: {candidate.codec_message}"
    if candidate.kind != KIND_COLLISION:
        return False, "The chosen file is not a collision file."
    if (candidate.root_type, candidate.has_patch_section) != (target.root_type, target.has_patch_section):
        return False, (
            f"The chosen file is laid out as {candidate.root_type}, this one as {target.root_type}. "
            "Pick a file from the same kind of folder."
        )
    return True, ""


def joint_display_name(joint: HkxJoint) -> str:
    """'L Calf - L Thigh' from the two body names, or the joint's own name."""

    child, parent = short_body_name(joint.child_body), short_body_name(joint.parent_body)
    return f"{child} - {parent}" if child and parent else joint.name or f"#{joint.index + 1}"


def _joint_changes(joints: Sequence[HkxJoint], edits: Mapping[Tuple[int, str], float]) -> Tuple[HkxJointChange, ...]:
    by_item = {joint.data_item: joint for joint in joints}
    changes = []
    for (data_item, key), value in sorted(edits.items()):
        joint = by_item.get(data_item)
        if joint is not None:
            old = next((item.value for item in joint.fields if item.key == key), math.nan)
            changes.append(HkxJointChange(joint, key, old, value))
    return tuple(changes)


def _verify_joint_locality(source: bytes, output: bytes, model: HkxTagfileModel, items: Sequence[int]) -> None:
    if len(source) != len(output):
        raise HkxTagfileRefused("verification_failed", "A joint edit changed the file size.")
    data_start = 32  # TAG0 header (8) + SDKV section (16) + DATA header (8)
    ranges = [(data_start + model.items[item].offset, data_start + model.items[item].offset + len(model.items[item].payload)) for item in items]
    for position in range(len(source)):
        if source[position] != output[position] and not any(start <= position < end for start, end in ranges):
            raise HkxTagfileRefused("verification_failed", f"A joint edit changed byte {position} outside the edited joints.")


def build_hkx_physics_edit(data: bytes, edits: HkxPhysicsEdits, path: str = "") -> HkxPhysicsEditResult:
    """Apply ``edits`` to ``data`` and return verified bytes plus readable change lines."""

    if edits.is_empty:
        raise HkxTagfileRefused("bad_edit", "There are no changes to save.")
    session = load_hkx_physics_session(data, path)
    if edits.replacement is not None:
        if edits.joint_values or edits.renames:
            raise HkxTagfileRefused("bad_edit", "Replacing the collision cannot be combined with other edits.")
        ok, reason = check_hkx_collision_replacement(session, edits.replacement)
        if not ok:
            raise HkxTagfileRefused("unproven_edit", reason)
        return HkxPhysicsEditResult(bytes(edits.replacement), replaced_with=edits.replacement_path)
    if not session.editable:
        raise HkxTagfileRefused("unproven_edit", session.codec_message or "This file cannot be edited.")
    model = parse_hkx_tagfile_model(data)
    joint_changes: Tuple[HkxJointChange, ...] = ()
    renames: Tuple[Tuple[str, str], ...] = ()
    if edits.joint_values:
        model = apply_hkx_joint_edits(model, edits.joint_values)
        joint_changes = _joint_changes(session.joints, edits.joint_values)
        if not edits.renames:
            output = serialize_hkx_tagfile_model(model)
            _verify_joint_locality(data, output, parse_hkx_tagfile_model(data), sorted({item for item, _ in edits.joint_values}))
    if edits.renames:
        old_names = {row.item: row.text for row in session.names}
        renames = tuple((old_names.get(item, ""), text) for item, text in sorted(edits.renames.items()))
        model = replace_hkx_string_items(model, edits.renames)
    output = serialize_hkx_tagfile_model(model)
    reparsed = parse_hkx_tagfile_model(output)
    if serialize_hkx_tagfile_model(reparsed) != output:
        raise HkxTagfileRefused("verification_failed", "The edited file does not rebuild exactly.")
    read_back = {joint.data_item: {item.key: item.value for item in joint.fields} for joint in read_hkx_joints(reparsed)}
    for (data_item, key), value in edits.joint_values.items():
        if abs(read_back.get(data_item, {}).get(key, math.inf) - value) > 1e-3:
            raise HkxTagfileRefused("verification_failed", f"{key} did not read back as {value:g}.")
    names_back = dict(hkx_string_items(reparsed))
    for item, text in edits.renames.items():
        if names_back.get(item) != text:
            raise HkxTagfileRefused("verification_failed", f"The name '{text}' did not read back.")
    return HkxPhysicsEditResult(output, joint_changes, renames)


__all__ = [
    "KIND_COLLISION",
    "KIND_OTHER",
    "KIND_PHYSICS_SYSTEM",
    "KIND_RAGDOLL",
    "SHAPE_CLASSES",
    "HkxCollisionSummary",
    "HkxJointChange",
    "HkxNameRow",
    "HkxPhysicsEditResult",
    "HkxPhysicsEdits",
    "HkxPhysicsSession",
    "build_hkx_physics_edit",
    "check_hkx_collision_replacement",
    "joint_display_name",
    "load_hkx_physics_session",
]
