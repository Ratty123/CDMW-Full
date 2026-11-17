"""Worn model membership and primary selection for catalogue item scopes."""
from collections.abc import Sequence
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
) -> tuple[ArchiveEntryDto, ...]:
    """The scope's worn models, primary first.

    ``item_prefabs`` pairs each of the item's own prefabs with the model paths it
    lists, in the order the item names them. An item's scope holds every wearer's
    copy of its pieces: the male and the female Kuku Marni Laser Helm, or the NPC
    robe Martial Monk's Cloth Robe was refitted from. The set is the wearer of the
    first prefab that lists a worn model: a file another wearer's prefab lists, and
    no prefab of that wearer does, is left out. Files no prefab lists stay.
    """

    models = tuple(entry for entry in entries if entry.extension.casefold() == ".pac")
    worn = tuple(entry for entry in models if "dropitem" not in entry.path.casefold())
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
    return tuple(entry for entry in ranked if _path_key(entry.path) not in others - own)
