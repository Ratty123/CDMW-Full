"""Worn model membership and primary selection for catalogue item scopes."""
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
import re

from cdmw.domain.archives.catalogue import ArchiveEntryDto

#: Model files one set session holds at most: the file the edit starts from and
#: 32 more (P5: one constant for the preview, the preparation and the session).
MAX_SET_FILES = 33

#: The body a file is built for, as its name says: `cd_phm_00_hel_00_0363` (human
#: male), `cd_phw_01_hel_00_0363` (human female), `cd_m0001_00_so_pom_ub_12005`. The
#: leading p or n (player or NPC build) is not part of the body.
_BODY_TOKEN = re.compile(r"(?:^|_)[pn]([hgtdo][mw])(?=_|$)")


def _path_key(path: str) -> str:
    return str(path or "").replace("\\", "/").strip("/").casefold()


def prefab_group(prefab_path: str) -> tuple[str, str]:
    """Who an item prefab dresses: its folder under `prefab/` (`1_pc` the playable
    characters, `2_mon` NPCs and creatures, `4_riding` mounts) and the body its name
    gives, else the folder below that."""

    key = _path_key(prefab_path)
    parts = key.split("/")
    after = parts[parts.index("prefab") + 1:] if "prefab" in parts else parts
    match = _BODY_TOKEN.search(PurePosixPath(key).stem)
    return (after[0] if len(after) > 1 else "",
            match.group(1) if match else (after[1] if len(after) > 2 else ""))


def worn_set_members(
    entries: tuple[ArchiveEntryDto, ...],
    item_prefabs: Sequence[tuple[str, Sequence[str]]] = (),
    kept_entry_ids: Collection[int] = (),
) -> tuple[ArchiveEntryDto, ...]:
    """The scope's worn models, primary first.

    ``item_prefabs`` pairs each of the item's own prefabs with the model paths it
    lists, in the order the item names them. An item's scope holds every wearer's
    copy of its pieces: the male and the female Kuku Marni Laser Helm, or the NPC
    robe Martial Monk's Cloth Robe was refitted from. The set is the wearer of the
    first prefab that lists a worn model: a file another wearer's prefab lists, and
    no prefab of that wearer does, is left out.

    A file no prefab lists stays, unless it is named like one of the wearer's prefabs
    that does not list it. The scope finds such a file by the item's name alone:
    Demeniss Honor Armor's prefab `cd_m0001_00_so_phm_ub_31067.prefab` lists
    `ub_31066.pac`, and the unrelated `ub_31067.pac` was drawn over it. Other unlisted
    files stay, as the St. Halssius Priest's Cloak, whose prefab lists only its
    shoulder piece, and the packs whose strap has a prefab of its own need.

    ``kept_entry_ids`` are files the user put in the set by hand (Add to scene, or
    the paths an MCP set names): each stays whatever its path or the prefabs say.
    """

    kept_ids = frozenset(int(entry_id) for entry_id in kept_entry_ids)
    models = tuple(entry for entry in entries if entry.extension.casefold() == ".pac")
    worn = tuple(entry for entry in models
                 if entry.entry_id in kept_ids or "dropitem" not in entry.path.casefold())
    candidates = worn or (models if len(models) == 1 else ())

    def rank(entry: ArchiveEntryDto) -> tuple[bool, int, str, int]:
        stem = PurePosixPath(entry.path.replace("\\", "/")).stem.casefold()
        return (not ("_ub_" in stem and "_ub_acc_" not in stem),
                -entry.original_size, entry.path.casefold(), entry.entry_id)

    ranked = tuple(sorted(candidates, key=rank))
    scoped = {_path_key(entry.path) for entry in ranked}
    listed = [(prefab_group(prefab), {_path_key(path) for path in paths}) for prefab, paths in item_prefabs]
    wearer = next((group for group, paths in listed if paths & scoped), None)
    if wearer is None:
        return ranked
    own = set().union(*(paths for group, paths in listed if group == wearer))
    others = set().union(*(paths for group, paths in listed if group != wearer))
    # A prefab that does not list the model named like it says that model is not the item's.
    named = {PurePosixPath(_path_key(prefab)).stem for prefab, _paths in item_prefabs
             if prefab_group(prefab) == wearer}

    def kept(entry: ArchiveEntryDto) -> bool:
        key = _path_key(entry.path)
        if key in own or entry.entry_id in kept_ids:
            return True
        return key not in others and PurePosixPath(key).stem not in named

    return tuple(entry for entry in ranked if kept(entry))


#: The name a scene collected by hand gets when the files had no set name before.
SCENE_LABEL = "Scene"


@dataclass(frozen=True, slots=True)
class SceneScope:
    """The files of one Browse scene, as the set scope takes them.

    A scene is a set scope (``apply_entry_id_scope(..., worn_set=True)``): Item
    Finder's or the NPC finder's worn set, or files collected with Add to scene.
    ``entry_ids`` is the whole scope, models and the item files that pick their
    material variant (prefabs, icons); ``model_ids`` the set's models as the
    preview resolved them, primary first. ``kept_ids`` are files added by hand,
    which ``worn_set_members`` keeps whatever their name. Adding or removing a
    file is the same scope with that one id more or less.
    """

    entry_ids: tuple[int, ...]
    model_ids: tuple[int, ...] = ()
    label: str = SCENE_LABEL
    prefab_stems: tuple[str, ...] = ()
    kept_ids: tuple[int, ...] = ()
    session_id: str = ""

    @classmethod
    def of_file(cls, entry_id: int, *, session_id: str = "", prefab_stems: Sequence[str] = ()) -> "SceneScope":
        """One model shown on its own, as the start of a scene."""

        entry_id = int(entry_id)
        return cls((entry_id,), (entry_id,), SCENE_LABEL, tuple(prefab_stems), (entry_id,), session_id)

    def add_reason(self, entry_id: int, extension: str) -> str:
        """Why ``entry_id`` cannot be added, or ""."""

        if str(extension or "").casefold() != ".pac":
            return "Only .pac models can be added to a scene."
        if int(entry_id) in self.model_ids:
            return "This model is already in the scene."
        if len(self.model_ids) + 1 > MAX_SET_FILES:
            return f"A scene holds at most {MAX_SET_FILES} model files."
        return ""

    def adding(self, entry_id: int) -> "SceneScope":
        entry_id = int(entry_id)
        return replace(
            self,
            entry_ids=tuple(dict.fromkeys((*self.entry_ids, entry_id))),
            model_ids=tuple(dict.fromkeys((*self.model_ids, entry_id))),
            label=self.label or SCENE_LABEL,
            kept_ids=tuple(dict.fromkeys((*self.kept_ids, entry_id))),
        )

    def removing(self, entry_id: int) -> "SceneScope":
        entry_id = int(entry_id)
        return replace(
            self,
            entry_ids=tuple(value for value in self.entry_ids if value != entry_id),
            model_ids=tuple(value for value in self.model_ids if value != entry_id),
            kept_ids=tuple(value for value in self.kept_ids if value != entry_id),
        )
