"""Experimental Build Mod option: stop an edited garment cutting chosen layers underneath.

The game cuts underlying clothing through shrink rules in ``partshrinkdesc.xml``:
each prefab component names a shrink tag, and the tag's rule lists the receiver
layers it cuts. An in-place PAC replacement keeps its item identity, so only the
geometry-cut half of New Item's Underlying parts applies here. Every prefab
component that binds the edited PAC moves to an output-owned, same-length tag
whose cloned rule omits the kept layers. Whole-part hide rules match prefab name
suffixes shared with other items and stay unchanged. Archives are only read.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping

from cdmw.core.equipment_visibility import SHRINK_PATH, clone_shrink_rules, shrink_rule_names
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.body_visibility import BodyVisibilityChoice
from cdmw.services.new_item_body_visibility import (
    component_shrink_tags, profile_record, retag_prefab_components, rule_receivers_reader, unlisted_layer_warnings,
)

PREFAB_ROOT = "character/bin__/prefab/"
# Clothing receivers in the shipped descriptor (game 2.04), grouped by body region.
# Skin and hair are left out: their whole-part hide rules cannot be isolated here.
# The *_Hair upper-body names are shirt layers, not hair. Matching ignores case,
# so Shoulder_Belt also keeps the rule spelling Shoulder_belt.
CLOTHING_LAYERS = (
    "Underwear",
    "Upperbody", "Upperbody_Up", "Upperbody_Belt", "Upperbody_Acc", "Upperbody_Hair", "Upperbody_Up_Hair",
    "Vest", "Vest_Belt", "Vest_Acc", "Jacket", "Jacket_Belt", "Jacket_Acc",
    "Shoulder", "Shoulder_Under", "Shoulder_Belt", "Cloak", "Cloak_Belt", "Necklace",
    "Lowerbody", "Lowerbody_Up",
    "Hand", "Hand_Down", "Hand_Belt", "Hand_Acc", "Fist",
    "Foot", "Foot_Down", "Foot_Belt",
    "Helm", "Helm_Mask", "Helm_Belt", "Mask", "Mask_Belt", "Mask_Acc", "Earring", "Acc",
)
_MAX_PREFAB_BYTES = 16 * 1024 * 1024


def _key(path: str) -> str:
    return str(path).replace("\\", "/").strip("/").casefold()


@dataclass(frozen=True)
class LayerVisibilityOutput:
    #: (archive entry, replacement bytes) for each prefab and the shrink descriptor
    patches: tuple
    notes: tuple[str, ...]
    record: dict


def _candidate_tag(pac_path, old, layers, attempt):
    # Same byte length as the original tag, so the prefab edit moves no pointer.
    size = len(old.encode("utf-8"))
    digest = hashlib.shake_256(f"mesh|{_key(pac_path)}|{old}|{layers}|{attempt}".encode())
    return "V" + digest.hexdigest(size)[:size - 1]


def _allocator(pac_path, known):
    taken = {tag.casefold() for tag in known}
    chosen = {}

    def allocate(old, choice):
        key = (old, choice)
        if key in chosen:
            return chosen[key]
        size = len(old.encode("utf-8"))
        layers = ",".join(sorted(choice.keep_receivers))
        for attempt in range(1000):
            tag = _candidate_tag(pac_path, old, layers, attempt)
            if tag.casefold() not in taken:
                taken.add(tag.casefold())
                chosen[key] = tag
                return tag
        raise ValueError(f"No unused {size}-byte visibility tag is available for {old}.")

    return allocate


def prepare_layer_visibility(
    pac_path: str,
    keep_layers,
    entries: Mapping[str, object],
    read: Callable[[object], bytes],
    *,
    stop_event=None,
    on_log: Callable[[str], None] | None = None,
) -> LayerVisibilityOutput:
    """Plan the prefab and descriptor patches for ``pac_path``.

    ``entries`` maps normalized archive paths to entries of the mounted game, and
    ``read`` returns an entry's bytes. Refuses rather than guessing.
    """
    choice = BodyVisibilityChoice(keep_receivers=frozenset(keep_layers))
    choice.validate()
    if not choice.keep_receivers:
        raise ValueError("Choose at least one layer to keep underneath.")
    shrink_entry = entries.get(_key(SHRINK_PATH))
    if shrink_entry is None:
        raise ValueError(f"The mounted game has no {SHRINK_PATH}.")
    shrink = read(shrink_entry)
    known = shrink_rule_names(shrink)
    target = _key(pac_path)
    prefabs = sorted(path for path in entries if path.startswith(PREFAB_ROOT) and path.endswith(".prefab"))
    if on_log:
        on_log(f"Finding the prefabs that use {PurePosixPath(target).name} ({len(prefabs)} prefabs)...")
    allocate = _allocator(pac_path, known)
    rule_receivers = rule_receivers_reader(shrink)
    profiles, patches, prefab_records, warnings, cut = [], [], [], [], set()
    for index, path in enumerate(prefabs):
        if index % 256 == 0:
            raise_if_cancelled(stop_event, "Layer visibility lookup cancelled.")
        entry = entries[path]
        if int(getattr(entry, "orig_size", 0) or 0) > _MAX_PREFAB_BYTES:
            continue
        data = read(entry)
        # Cheap byte test first: most prefabs never mention this mesh.
        if PurePosixPath(target).name.encode() not in data.lower():
            continue
        # A prefab that may bind this mesh but cannot be read exactly would keep
        # cutting in that item; refuse instead of shipping a partial change.
        try:
            bound = component_shrink_tags(data, (target,))
        except ValueError as exc:
            raise ValueError(f"{entry.path} mentions this mesh but cannot be read exactly: {exc}") from exc
        if not bound:
            continue
        retag = retag_prefab_components(entry.path, data, {target: choice}, known, allocate, profiles, rule_receivers)
        cut |= retag.cut
        warnings.extend(retag.warnings)
        if retag.data != data:
            patches.append((entry, retag.data))
        prefab_records.append({"prefab": entry.path, "components": retag.details})
    if not prefab_records:
        raise ValueError(f"No prefab binds {pac_path}; there is no shrink rule to change.")
    unlisted = sorted(name for name in choice.keep_receivers if name.casefold() not in cut)
    if not profiles:
        if cut and unlisted:
            raise ValueError(f"The shrink rules this mesh uses do not cut {', '.join(unlisted)}; there is nothing to change.")
        raise ValueError("The prefabs that use this mesh have no shrink tag CDMW can change.")
    changed = clone_shrink_rules(shrink, tuple(profiles))
    patches.append((shrink_entry, changed))
    # Generic notes first: the status bar keeps the last message, which should be
    # the one about this mesh.
    notes = [
        "Layers underneath is experimental and needs in-game testing. The preview does not simulate shrink rules.",
        "Whole-part hide rules are unchanged; other equipment can still hide or cut these layers.",
        "This mod ships its own partshrinkdesc.xml. Another mod that ships that file replaces these rules, or loses its own.",
        *warnings, *unlisted_layer_warnings(choice.keep_receivers, cut),
    ]
    record = {"experimental": True, "mesh": pac_path, "keep_layers": sorted(choice.keep_receivers),
              "prefabs": prefab_records, "profiles": [profile_record(p) for p in profiles]}
    return LayerVisibilityOutput(tuple(patches), tuple(dict.fromkeys(notes)), record)


def mounted_entries(game_root, wanted: Callable[[str], bool], *, stop_event=None) -> dict[str, object]:
    """Entries of the mounted game whose normalized path ``wanted`` accepts; DLC copies win."""
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.core.papgt_format import read_papgt_directories

    root = Path(game_root)
    layers = []
    dlc = root / "dlc"
    for layer in sorted(dlc.glob("dlc_*")) if dlc.is_dir() else ():
        if (layer / "meta/0.papgt").is_file():
            layers.append((layer, read_papgt_directories((layer / "meta/0.papgt").read_bytes())))
    mounts = read_papgt_directories((root / "meta/0.papgt").read_bytes())
    if not mounts:
        raise ValueError("A valid game mount catalogue is required.")
    entries = {}
    for folder, mount in [(layer, row) for layer, rows in layers for row in rows] + [(root, row) for row in mounts]:
        raise_if_cancelled(stop_event, "Layer visibility lookup cancelled.")
        if Path(mount.name).name != mount.name or mount.name in {".", ".."}:
            raise ValueError("The game mount catalogue contains an unsafe directory.")
        for pamt in sorted((folder / mount.name).glob("*.pamt")):
            for item in parse_archive_pamt(pamt):
                key = _key(item.path)
                if wanted(key):
                    entries.setdefault(key, item)
    return entries


def wanted_for_layers(path: str) -> bool:
    return path == _key(SHRINK_PATH) or (path.startswith(PREFAB_ROOT) and path.endswith(".prefab"))
