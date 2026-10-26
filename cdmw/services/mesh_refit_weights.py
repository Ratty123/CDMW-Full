"""Skin weights for Fit to body's authored-body transfer.

Fitting moves an outfit onto the driver body, but the outfit's skin weights
still describe the body it was authored on. With this table the native fitter
gives garment vertices near the driver the driver's own weights (see
``native/cdmw_mesh_core/src/owners/session_refit_weights.cpp``).

The driver's bones reach a garment only through slots of that garment's own PAC
palette: a bone with the same name, else its nearest ancestor that the palette
names, else nothing. Palettes therefore never grow, and the exact PAC writer
can store the rows in place. Only Parts it can write that way take part:
unchanged 40-byte ``pac_slot_u10x6`` records whose current rows are already
valid. Parts shown in a character appearance keep their weights, because new
weights would also move their saved positions. Each vertex keeps at most the
influences its record holds: six, or four on cloth-simulated records.

The table also carries how the outfit and its authored body move in a few test
poses (:data:`cdmw.modding.mesh_refit_motion.DESIGN_POSES`), so the fitter can
leave alone cloth that was made not to follow the skin beneath it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from cdmw.modding.mesh_pac_skin_contract import (
    pac_skin_part_layout_matches,
    pac_skin_row_capacity,
    pac_skin_rows_safe,
)
from cdmw.modding.mesh_parser import resolve_pac_bone_palette
from cdmw.modding.mesh_refit_motion import DESIGN_POSES, rest_motion


@dataclass(frozen=True)
class RefitWeightTransfer:
    """Per-Part slot tables for ``morph_set_reference_body``'s ``weight_transfer``."""

    driver_bones: Mapping[int, tuple[int, ...]]
    garment_slots: Mapping[int, tuple[int, ...]]
    capacities: Mapping[int, tuple[int, ...]]
    palette_sizes: Mapping[int, int]
    # Why some garment Parts keep their own weights.
    kept: tuple[str, ...] = field(default=())
    # How far each authored body vertex and each garment vertex move in each
    # design pose, as authored: (vertices, poses, 3).
    reference_motion: np.ndarray | None = None
    garment_motion: Mapping[int, np.ndarray] = field(default_factory=dict)

    def payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "driver_bones": [{"submesh_index": index, "bones": list(bones)}
                             for index, bones in sorted(self.driver_bones.items())],
            "garments": [{"submesh_index": index, "slots": list(self.garment_slots[index]),
                          "capacities": list(self.capacities[index]),
                          **({"motion": _flat(self.garment_motion[index])} if index in self.garment_motion else {})}
                         for index in sorted(self.garment_slots)],
        }
        if self.reference_motion is not None and self.garment_motion:
            payload["motion_poses"] = int(self.reference_motion.shape[1])
            payload["reference_motion"] = _flat(self.reference_motion)
        return payload


def _flat(motion: np.ndarray) -> list[float]:
    return np.asarray(motion, dtype=np.float64).ravel().tolist()


def driver_bone_slots(target_skeleton: object, source_skeleton: object, palette: Sequence[int]) -> tuple[int, ...]:
    """For every driver bone, the garment palette slot that carries it (-1 for none).

    ``palette`` maps the garment's slots to ``source_skeleton`` bone ordinals.
    A driver bone the palette does not name uses its nearest ancestor that it does.
    """
    source_bones = tuple(source_skeleton.bones)
    target_bones = tuple(target_skeleton.bones)
    by_name: dict[str, int] = {}
    for slot, ordinal in enumerate(palette):
        if 0 <= int(ordinal) < len(source_bones):
            by_name.setdefault(str(source_bones[int(ordinal)].name), slot)
    slots = []
    for index in range(len(target_bones)):
        current, seen = index, set()
        while 0 <= current < len(target_bones) and current not in seen and str(target_bones[current].name) not in by_name:
            seen.add(current)
            current = int(target_bones[current].parent_index)
        slots.append(by_name[str(target_bones[current].name)] if 0 <= current < len(target_bones) and current not in seen else -1)
    return tuple(slots)


def build_refit_weight_transfer(
    target_skeleton: object,
    source_skeleton: object,
    driver: object,
    garments: Sequence[object],
    read,
    *,
    reference: tuple[Sequence[object], Sequence[int]] | None = None,
) -> tuple[RefitWeightTransfer | None, str]:
    """The table for ``garments`` (archive Refit assets) onto ``driver``, or why there is none.

    ``reference`` is the authored body's Parts and their palette in the
    garments' skeleton, the same Parts the reference body was built from; with
    it the fitter can tell where a garment was made to follow that body.
    """
    driver_palette = tuple(resolve_pac_bone_palette(read(driver.entry), target_skeleton))
    if not driver_palette:
        return None, "the body's bones do not match its skeleton"
    kept: list[str] = []
    garment_slots: dict[int, tuple[int, ...]] = {}
    capacities: dict[int, tuple[int, ...]] = {}
    palette_sizes: dict[int, int] = {}
    garment_motion: dict[int, np.ndarray] = {}
    for asset in garments:
        name = str(asset.entry.path).replace("\\", "/").rsplit("/", 1)[-1]
        if getattr(asset, "neutral_appearance", None) is not None:
            kept.append(f"{name} is shown in a character appearance")
            continue
        data = bytes(getattr(asset.source, "original_data", b"") or b"")
        palette = tuple(resolve_pac_bone_palette(data, source_skeleton)) if data else ()
        if not palette:
            kept.append(f"the bones of {name} do not match its skeleton")
            continue
        slots = driver_bone_slots(target_skeleton, source_skeleton, palette)
        parts = tuple(getattr(getattr(asset.source, "mesh", None), "submeshes", ()) or ())
        for local, combined in enumerate(asset.part_indices):
            part = parts[local] if local < len(parts) else None
            vertex_count = len(getattr(part, "vertices", ()) or ()) if part is not None else 0
            if (part is None or not pac_skin_part_layout_matches(part, part, data)
                    or not pac_skin_rows_safe(part, vertex_count, len(palette), data)):
                kept.append(f"{getattr(part, 'name', name)} cannot have its weights written in place")
                continue
            garment_slots[int(combined)] = slots
            capacities[int(combined)] = tuple(pac_skin_row_capacity(data, int(offset)) for offset in part.source_vertex_offsets)
            palette_sizes[int(combined)] = len(palette)
            if reference is not None:
                garment_motion[int(combined)] = rest_motion([part], palette, source_skeleton)
    if not garment_slots:
        return None, "; ".join(kept) or "no garment Part can take the body's weights"
    driver_bones = {int(index): driver_palette for index in driver.part_indices}
    reference_motion = None
    if reference is not None:
        parts, palette = reference
        # retarget_reference_body keeps only Parts with both vertices and faces.
        reference_motion = rest_motion([part for part in parts if len(part.vertices) and len(part.faces)],
                                       palette, source_skeleton)
    return RefitWeightTransfer(driver_bones, garment_slots, capacities, palette_sizes, tuple(kept),
                               reference_motion, garment_motion), ""


__all__ = ["DESIGN_POSES", "RefitWeightTransfer", "build_refit_weight_transfer", "driver_bone_slots"]
