"""Which authored frame a New Item equipment template already occupies."""

from __future__ import annotations

BODY_PLACEMENT_FRAME = "body"
HELD_PLACEMENT_FRAME = "held"
UNKNOWN_PLACEMENT_FRAME = "unknown"

_HELD_EQUIPMENT_TYPES = frozenset({"gauntlet", "lantern"})
_HELD_EQUIPMENT_PREFIXES = ("onehand", "twohand", "tool")


def equipment_placement_frame(equip_type_name: str = "", model_folder: str = "") -> str:
    """Return ``body``, ``held`` or ``unknown`` for one equipment template.

    ``EquipTypeInfo`` is the authority: the game's hand-carried families are the
    Gauntlet/Lantern types and the OneHand, TwoHand and Tool families. Everything
    else is worn or mounted and its mesh is already authored in a body, creature or
    vehicle bind frame. A folder is only a compatibility fallback for callers that
    do not have the selected template's equipment type.
    """

    equip_type = str(equip_type_name or "").strip().casefold()
    if equip_type:
        if equip_type in _HELD_EQUIPMENT_TYPES or equip_type.startswith(_HELD_EQUIPMENT_PREFIXES):
            return HELD_PLACEMENT_FRAME
        return BODY_PLACEMENT_FRAME

    folder = str(model_folder or "").replace("\\", "/")
    folder = f"/{folder.strip('/').casefold()}/"
    if "/armor/" in folder:
        return BODY_PLACEMENT_FRAME
    if "/weapon/" in folder:
        return HELD_PLACEMENT_FRAME
    return UNKNOWN_PLACEMENT_FRAME


__all__ = [
    "BODY_PLACEMENT_FRAME",
    "HELD_PLACEMENT_FRAME",
    "UNKNOWN_PLACEMENT_FRAME",
    "equipment_placement_frame",
]
