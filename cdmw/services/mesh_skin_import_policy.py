"""Keep, reduce or transfer an imported model's skin weights against a PAC rig.

Create New Item and the Mesh Editor's Import Replacement both use these, so the
same choice gives the same weights whichever route imported the model.

* ``preserve`` keeps the authored weights. Every used joint must name one PAC
  palette bone and the rig must share the game skeleton's bind frame.
* ``reduce`` keeps the six strongest influences per vertex, renormalizes, then
  keeps them as ``preserve`` does.
* ``transfer`` drops the authored weights. The geometry moves into game bind
  space when the rig proves that frame, and is otherwise used as authored; the
  weights then come from the nearest original surface.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace

from cdmw.domain.mesh.skin_policy import reduce_influences
from cdmw.modding.mesh_parser import PAC_SKIN_PALETTE_SLOTS
from cdmw.modding.mesh_skinning import SOURCE_VERTEX_MAP_TOPOLOGY

POLICIES = ("preserve", "reduce", "transfer")


def has_authored_rows(part) -> bool:
    return bool(part.interchange_skin or part.bone_indices or part.bone_weights)


def joint_names(part) -> tuple[str, ...]:
    """The imported rig's joint names, indexed as the part's influence rows are."""
    skin = part.interchange_skin
    if not skin:
        raise ValueError(f"{part.name} has weights without their imported rig identity.")
    return tuple(str(skin["nodes"][joint].get("name", "")) for joint in skin["joints"])


def over_capacity_vertices(part, capacity: int = PAC_SKIN_PALETTE_SLOTS) -> int:
    """Vertices whose positive influences name more joints than a PAC row holds."""
    return sum(len({joint for joint, weight in zip(joints, weights) if weight > 0}) > capacity
               for joints, weights in zip(part.bone_indices, part.bone_weights))


def reduce_part(part, capacity: int, identities) -> tuple[object, dict]:
    """Keep each vertex's strongest ``capacity`` influences; report what was lost."""
    rows = [reduce_influences(joints, weights, capacity, identities)
            for joints, weights in zip(part.bone_indices, part.bone_weights, strict=True)]
    part = copy.copy(part)
    part.bone_indices = [row[0] for row in rows]
    part.bone_weights = [row[1] for row in rows]
    return part, {
        "reduced_vertices": sum(row[2] > 0 for row in rows),
        "maximum_removed_mass": max((row[2] for row in rows), default=0.),
        "over_one_percent": sum(row[2] > .01 for row in rows),
        "over_five_percent": sum(row[2] > .05 for row in rows),
        "removed_bones": tuple(sorted({name for row in rows for name in row[3]})),
        "maximum_normalization_change": max((row[4] for row in rows), default=0.),
        "required_bones": tuple(sorted({identities[joint] for joints in part.bone_indices for joint in joints})),
    }


def bind_for_transfer(part, skeleton) -> tuple[object, str]:
    """Move a part into game bind space when its rig proves the frame.

    Transfer replaces the authored weights, so a foreign rig only loses its
    placement proof: the geometry is then kept as authored, like an unrigged
    model, and the returned note says so.
    """
    from cdmw.modding.mesh_glb_assets import skeleton_skin
    from cdmw.modding.scene_geometry_utils import _copy_submesh_with_transform
    from cdmw.services.mesh_replacement_skinning import _target_bind_frame

    if not tuple(getattr(skeleton, "bones", ()) or ()):
        return part, ("No game skeleton is attached, so the imported rig cannot be compared with it; "
                      "the model is used as authored, so check its placement.")
    try:
        # Only the bones the part is weighted to must match closely; others may drift.
        frame = _target_bind_frame(part.interchange_skin, skeleton_skin(skeleton),
                                   {joint for row in part.bone_indices for joint in row})
    except ValueError as exc:
        return part, (f"The imported rig does not match the game skeleton ({exc}); "
                      "the model is used as authored, so check its placement.")
    return _copy_submesh_with_transform(part, frame), ""


def clear_authored_skin(part):
    """The part without its imported weights, ready for a transfer."""
    part = copy.copy(part)
    part.bone_indices, part.bone_weights, part.interchange_skin = [], [], {}
    part.source_vertex_map, part.source_vertex_map_authority = [], SOURCE_VERTEX_MAP_TOPOLOGY
    return part


@dataclass(frozen=True, slots=True)
class SkinPolicyOption:
    policy: str
    available: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class SkinImportAssessment:
    """What each weights choice would do with one imported model."""

    rigged_parts: tuple[str, ...] = ()
    options: tuple[SkinPolicyOption, ...] = ()
    over_capacity: int = 0
    summary: str = ""
    # The original has no weights, so there is nothing to keep or match.
    static_target: bool = False

    @property
    def rigged(self) -> bool:
        return bool(self.rigged_parts)

    def option(self, policy: str) -> SkinPolicyOption:
        for option in self.options:
            if option.policy == policy:
                return option
        raise ValueError("Choose Keep Imported Weights, Reduce to Six Influences or Transfer from Original.")

    @property
    def default_policy(self) -> str:
        """Keep when it works; otherwise the user must choose."""
        if not self.rigged or self.static_target:
            return "transfer"
        return "preserve" if self.option("preserve").available else ""

    def payload(self) -> dict:
        return {"rigged": self.rigged, "static_target": self.static_target, "parts": list(self.rigged_parts), "default": self.default_policy,
                "summary": self.summary, "over_capacity": self.over_capacity,
                "options": [{"policy": option.policy, "enabled": option.available, "reason": option.reason}
                            for option in self.options]}


def _rigged_mesh(mesh, indices):
    return replace(mesh, submeshes=[copy.deepcopy(mesh.submeshes[index]) for index in indices])


def assess_imported_skin(mesh, snapshot, state, *, retain=None) -> SkinImportAssessment:
    """Try each choice on a copy so the mapping step can say what will happen.

    ``snapshot`` and ``state`` are what ``retain_imported_skinning`` takes. Only
    malformed rows raise; a rig that cannot be kept is reported, not refused.
    """
    if retain is None:
        from cdmw.services.mesh_replacement_skinning import (
            retain_imported_skinning as retain,
        )
    indices = tuple(index for index, part in enumerate(mesh.submeshes) if has_authored_rows(part))
    if not indices:
        return SkinImportAssessment()
    names = tuple(mesh.submeshes[index].name or f"Part {index}" for index in indices)
    over = sum(over_capacity_vertices(mesh.submeshes[index]) for index in indices)
    if over:
        keep = SkinPolicyOption("preserve", False,
                                f"{over:,} vertices use more than six bones; a game vertex holds six. "
                                "Choose Reduce to Six Influences, or limit influences to six in Blender.")
    else:
        try:
            retain(_rigged_mesh(mesh, indices), snapshot, state)
        except ValueError as exc:
            keep = SkinPolicyOption("preserve", False, str(exc))
        else:
            keep = SkinPolicyOption("preserve", True)
    if not over:
        reduce = SkinPolicyOption("reduce", False, "No vertex uses more than six bones, so there is nothing to reduce.")
    else:
        try:
            reduced = _rigged_mesh(mesh, indices)
            reduced.submeshes = [reduce_part(part, PAC_SKIN_PALETTE_SLOTS, joint_names(part))[0]
                                 for part in reduced.submeshes]
            retain(reduced, snapshot, state)
        except ValueError as exc:
            reduce = SkinPolicyOption("reduce", False, str(exc))
        else:
            reduce = SkinPolicyOption("reduce", True)
    # A static original takes no weights at all; transfer then just drops them.
    transfer = SkinPolicyOption("transfer", True)
    if not any(part.bone_weights for part in snapshot.mesh.submeshes):
        summary = "The original model has no skin weights, so the imported weights are dropped."
    elif keep.available:
        summary = "The imported rig matches the original skeleton, so its weights can be kept."
    elif reduce.available:
        summary = f"The imported rig matches the original skeleton, but {over:,} vertices use more than six bones."
    elif over:
        summary = "The imported weights cannot be kept or reduced: " + reduce.reason
    else:
        summary = "The imported weights cannot be kept: " + keep.reason
    static = not any(part.bone_weights for part in snapshot.mesh.submeshes)
    return SkinImportAssessment(names, (keep, reduce, transfer), over, summary, static)


def apply_skin_policy(mesh, snapshot, state, policy: str, *, retain=None) -> tuple[object, tuple[str, ...]]:
    """Return a copy of ``mesh`` with ``policy`` applied to its rigged parts, and notes.

    ``transfer`` leaves the parts without weights; the caller transfers from
    the original surface it maps each part onto.
    """
    if policy not in POLICIES:
        raise ValueError("Choose Keep Imported Weights, Reduce to Six Influences or Transfer from Original.")
    if retain is None:
        from cdmw.services.mesh_replacement_skinning import (
            retain_imported_skinning as retain,
        )
    indices = [index for index, part in enumerate(mesh.submeshes) if has_authored_rows(part)]
    if not indices:
        return mesh, ()
    source = replace(mesh, submeshes=list(mesh.submeshes))
    notes = []
    skeleton = getattr(snapshot.mesh, "interchange_skeleton", None)
    for index in indices:
        part = copy.deepcopy(source.submeshes[index])
        label = part.name or f"Part {index}"
        if policy == "reduce":
            part, loss = reduce_part(part, PAC_SKIN_PALETTE_SLOTS, joint_names(part))
            if loss["reduced_vertices"]:
                notes.append(f"{label}: reduced {loss['reduced_vertices']:,} vertices to six bones; "
                             f"up to {loss['maximum_removed_mass']:.2%} of a vertex's weight removed, "
                             f"{loss['over_five_percent']:,} vertices lost more than 5%. "
                             f"Removed bones: {', '.join(loss['removed_bones']) or 'none'}.")
        elif policy == "transfer":
            part, note = bind_for_transfer(part, skeleton)
            if note:
                notes.append(f"{label}: {note}")
            part = clear_authored_skin(part)
        source.submeshes[index] = part
    if policy != "transfer":
        source = retain(source, snapshot, state)
    else:
        from cdmw.modding.mesh_totals import refresh_mesh_totals
        refresh_mesh_totals(source)
        source.has_bones = any(part.bone_weights for part in source.submeshes)
    return source, tuple(notes)
