"""What an imported model inherits from its template's part prefabs.

A New Item clone keeps the template's part-prefab records and prefabs, only re-pathed
to the new mesh, so the template (the baseline) decides which character parts the item
occupies and which other meshes it draws beside its own. Helms are where that shows: the
Northern Fighter's Plate Helm occupies `CD_Helm_Small` and `CD_Item_Hair` and its prefab
carries a second SkinnedMeshComponent with a helmet hair mesh, so the face stays drawn
under it; the Unyielding Warrior's and Canta helms occupy `CD_Helm_Small` alone and the
head under them was hidden in game (which field hides it is not identified). An import
inherits whichever it is cloned from, so the studio names it and leaves the choice open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from cdmw.core.item_model_family import ItemModelFamily
from cdmw.core.prefab_binary import PrefabBinaryError, decode_prefab_binary

__all__ = ["BaselineFacts", "baseline_facts", "baseline_lines"]

ReadPayload = Callable[[str], bytes]


@dataclass(frozen=True, slots=True)
class BaselineFacts:
    """What the template's owned part prefabs carry, as an import inherits it."""

    #: Part slot names in record order, e.g. ("CD_Helm_Small", "CD_Item_Hair").
    slots: Tuple[str, ...]
    #: Meshes the owned prefabs draw besides the family's own (a helm's helmet hair).
    companion_meshes: Tuple[str, ...]
    #: SkinnedMeshComponents across the owned prefabs.
    mesh_components: int
    #: Owned prefabs that could not be decoded, by path.
    unreadable: Tuple[str, ...] = ()

    @property
    def brings_hair(self) -> bool:
        return any("/hair/" in path.lower() for path in self.companion_meshes)


def baseline_facts(family: ItemModelFamily, read_payload: ReadPayload) -> BaselineFacts:
    """Read the owned parts' records and prefabs of `family`.

    `read_payload` returns an archive entry's bytes and may raise for a missing one; a
    prefab that cannot be read or decoded is listed under `unreadable` rather than raised.
    """

    slots: list[str] = []
    companions: list[str] = []
    unreadable: list[str] = []
    components = 0
    own_meshes = {item.path.lower() for item in family.files_for("pac")}
    own_meshes.update(part.pac_path.lower() for part in family.parts if part.pac_path)
    for part in family.owned_parts:
        record = part.record
        if record is None:
            continue
        for slot in record.parts:
            if slot.name not in slots:
                slots.append(slot.name)
        try:
            document = decode_prefab_binary(read_payload(record.prefab_path))
        except (PrefabBinaryError, ValueError, KeyError, OSError):
            unreadable.append(record.prefab_path)
            continue
        components += sum(1 for obj in document.objects if obj.component_type == "SkinnedMeshComponent")
        for text in document.resource_strings():
            path = text.text
            if path.lower().endswith(".pac") and path.lower() not in own_meshes and path not in companions:
                companions.append(path)
    return BaselineFacts(tuple(slots), tuple(companions), components, tuple(unreadable))


def baseline_lines(facts: Optional[BaselineFacts]) -> Tuple[str, ...]:
    """Summary lines for the studio: the slots, the companion meshes, and the fact that an
    import inherits them."""

    if facts is None or (not facts.slots and not facts.companion_meshes):
        return ()
    lines = [f"baseline parts: {', '.join(facts.slots) or 'none named'} ({facts.mesh_components} mesh component(s)); an imported model inherits them"]
    if facts.companion_meshes:
        names = ", ".join(path.rsplit("/", 1)[-1] for path in facts.companion_meshes)
        what = "a helmet hair mesh" if facts.brings_hair else "another mesh"
        lines.append(f"the baseline's prefab draws {what} beside its own: {names}; the clone keeps drawing it")
    if facts.unreadable:
        lines.append(f"unreadable prefab(s): {', '.join(facts.unreadable)}")
    return tuple(lines)
