"""Model family discovery: from an ItemInfo row to the files a cloned item needs.

An item does not name its meshes. Its row carries `hashlittle(stem, 0xC5EDE)` for
each character-part prefab it equips; StringInfo turns the hash back into a stem;
`character/bin__/partprefabtable.pappt` turns the stem into a prefab path; and the
prefab carries the explicit `character/model/.../<mesh>.pac` path, from which the
`.pac_xml` and `.hkx` follow by convention. The icon is a StringInfo string of the
form `ItemIcon_Prefab_<Stem>` whose lower-case spelling is the `.dds` name.

Some of the parts an item equips are not its own: Ziane's sword draws
`cd_phm_01_sword_0109_r/_l` and borrows `cd_phm_01_sword_0168_*_in_index01` for its
sheath; a helm equips one part per body type; an armour set carries a generic
drop-item mesh. A clone copies the owned family under a new stem and keeps borrowing
the rest, so the discovery has to say which is which.

Measured on the shipped tables (2026-08-17): the icon string names the family. It
is usually a part stem (`ItemIcon_Prefab_CD_PHM_01_Sword_0016_R`) and sometimes the
mesh stem itself (`ItemIcon_Prefab_CD_PHM_01_Sword_0109`); the mesh that part
resolves to is the family stem, and every part whose mesh starts with it is owned.
That resolves an owned mesh for the great majority of rows with an icon; the rest
fall back to the mesh the most parts share, and every choice is written into the
result's notes so a caller can see how it was made.

The module is pure: the archive is reached only through the callables the caller
passes in, so it can be tested on synthetic tables and gated on the shipped corpus.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Tuple

from cdmw.core.iteminfo_row import ItemInfoRow
from cdmw.core.pappt_format import PartPrefabRecord, PartPrefabTable
from cdmw.core.prefab_binary import PrefabBinaryError, decode_prefab_binary

ICON_STRING_PREFIX = "ItemIcon_Prefab_"
ICON_FOLDER = "ui/texture/icon"
MODEL_ROOT = "character/model"
MODEL_PROPERTY_ROOT = "character/modelproperty"
MESH_PHYSICS_ROOT = "character/bin__/meshphysics"

#: File roles a family clone copies, in the order the plan lists them.
FILE_ROLES = ("pac", "pac_xml", "hkx", "prefab", "icon")

ReadEntry = Callable[[str], Optional[bytes]]


class ItemModelFamilyError(ValueError):
    """Raised when a row's model family cannot be resolved."""


@dataclass(frozen=True, slots=True)
class FamilyPart:
    """One character part the item equips, resolved as far as the archive allows."""

    stem: str
    hash: int
    record: Optional[PartPrefabRecord]
    #: The `.pac` path the prefab names, or "" when the prefab was not readable.
    pac_path: str
    owned: bool

    @property
    def prefab_path(self) -> str:
        return self.record.prefab_path if self.record is not None else ""

    @property
    def pac_stem(self) -> str:
        return _stem_of(self.pac_path)


@dataclass(frozen=True, slots=True)
class FamilyFile:
    """One file the owned family consists of."""

    role: str
    path: str
    exists: bool
    #: Whether the payload spells its own stem, so a byte copy would not be self-contained.
    #: None when the payload was not read.
    mentions_stem: Optional[bool] = None


@dataclass(frozen=True, slots=True)
class ItemModelFamily:
    item_key: int
    #: The stem the family's mesh files share, e.g. `cd_phm_01_sword_0109`.
    model_stem: str
    #: The folder under `character/model` the pac sits in, e.g. `1_pc/1_phm/weapon/1_onehandweapon`.
    model_folder: str
    parts: Tuple[FamilyPart, ...]
    files: Tuple[FamilyFile, ...]
    icon_string: Optional[str]
    icon_hash: Optional[int]
    notes: Tuple[str, ...] = ()

    @property
    def owned_parts(self) -> Tuple[FamilyPart, ...]:
        return tuple(part for part in self.parts if part.owned)

    @property
    def borrowed_parts(self) -> Tuple[FamilyPart, ...]:
        return tuple(part for part in self.parts if not part.owned)

    @property
    def owned_stems(self) -> Tuple[str, ...]:
        return tuple(part.stem for part in self.owned_parts)

    @property
    def borrowed_stems(self) -> Tuple[str, ...]:
        return tuple(part.stem for part in self.borrowed_parts)

    @property
    def missing_files(self) -> Tuple[FamilyFile, ...]:
        return tuple(item for item in self.files if not item.exists)

    def files_for(self, role: str) -> Tuple[FamilyFile, ...]:
        return tuple(item for item in self.files if item.role == role)

    def rename_stem(self, stem: str, new_model_stem: str) -> str:
        """The stem a family member takes when the family moves to `new_model_stem`.

        A stem that starts with the model stem keeps its suffix (`_r`, `_l`,
        `_r_in_index01`). One that only shares a token prefix with it, as a prefab
        named `cd_t0000_boardpaper_0258` does with its mesh `cd_t0000_boardpaper_0002`,
        keeps everything after the shared prefix instead, so the result is unique per
        new model stem and still deterministic. No shared prefix at all is refused.
        """

        target = str(new_model_stem or "").strip()
        if not target:
            raise ItemModelFamilyError("a new model stem is required")
        text = str(stem or "")
        if text.lower().startswith(self.model_stem.lower()):
            return target + text[len(self.model_stem):]
        shared = _common_token_prefix(text.lower(), self.model_stem.lower())
        if not shared:
            raise ItemModelFamilyError(f"{text!r} shares no name with the family stem {self.model_stem!r}")
        return target + text[len(shared):]

    def renamed(self, new_model_stem: str) -> Tuple[Tuple[str, str, str], ...]:
        """(role, old path, new path) for every family file under `new_model_stem`."""

        out = []
        for item in self.files:
            folder, _, name = item.path.rpartition("/")
            stem, dot, ext = name.partition(".")
            if item.role == "icon":
                new_stem = _icon_file_stem(self._renamed_icon_stem(new_model_stem))
            else:
                new_stem = self.rename_stem(stem, new_model_stem)
            new_name = new_stem + dot + ext
            out.append((item.role, item.path, f"{folder}/{new_name}" if folder else new_name))
        return tuple(out)

    def renamed_icon_string(self, new_model_stem: str) -> Optional[str]:
        """The `ItemIcon_Prefab_*` string for the moved family, or None without an icon."""

        if not self.icon_string:
            return None
        return ICON_STRING_PREFIX + self._renamed_icon_stem(new_model_stem)

    def _renamed_icon_stem(self, new_model_stem: str) -> str:
        """Icons named after the family follow it; ones named after something else
        (`gimmick_trap_bomb_01`) simply take the new model stem, which is as unique."""

        try:
            return self.rename_stem(_icon_stem(self.icon_string or ""), new_model_stem)
        except ItemModelFamilyError:
            target = str(new_model_stem or "").strip()
            if not target:
                raise
            return target


def _stem_of(path: str) -> str:
    name = str(path or "").replace("\\", "/").rsplit("/", 1)[-1]
    return name.split(".", 1)[0] if "." in name else name


def _icon_stem(icon_string: str) -> str:
    text = str(icon_string or "")
    return text[len(ICON_STRING_PREFIX):] if text.startswith(ICON_STRING_PREFIX) else text


def _icon_file_stem(icon_stem: str) -> str:
    return (ICON_STRING_PREFIX + icon_stem).lower()


def _common_token_prefix(a: str, b: str) -> str:
    """The longest `_`-separated prefix `a` and `b` share, e.g. `cd_t0000_boardpaper`."""

    left, right = a.split("_"), b.split("_")
    shared = []
    for x, y in zip(left, right):
        if x != y:
            break
        shared.append(x)
    return "_".join(shared)


def _prefab_pac_path(read_entry: ReadEntry, prefab_path: str) -> str:
    data = read_entry(prefab_path)
    if not data:
        return ""
    try:
        document = decode_prefab_binary(bytes(data))
    except PrefabBinaryError:
        return ""
    for item in document.resource_strings():
        text = item.text.replace("\\", "/").strip()
        if text.lower().endswith(".pac"):
            return text
    return ""


def find_part_stems(
    row: ItemInfoRow,
    stringinfo: Mapping[int, str],
    pappt: PartPrefabTable,
) -> Tuple[Tuple[int, str], ...]:
    """(hash, stem) for every u32 in the row after its prefix that names a pappt stem.

    The hashes are not at fixed offsets and the row grammar between them is not
    decoded, so this scans every byte offset. A false hit needs a u32 that is both a
    StringInfo key and a pappt stem, and the shipped tables leave that at a few in a
    hundred thousand rows; a real hit is repeated when the game lists the same part
    twice, and duplicates are collapsed to first occurrence.
    """

    stems = pappt.index()
    raw = row.raw
    found: dict[int, str] = {}
    for offset in range(row.prefix_end, len(raw) - 3):
        value = int.from_bytes(raw[offset:offset + 4], "little")
        if value in found:
            continue
        text = stringinfo.get(value)
        if text is not None and text in stems:
            found[value] = text
    return tuple(found.items())


def find_icon_string(row: ItemInfoRow, stringinfo: Mapping[int, str]) -> Tuple[Optional[int], Optional[str]]:
    """(hash, text) of the row's `ItemIcon_Prefab_*` string, or (None, None)."""

    raw = row.raw
    for offset in range(row.prefix_end, len(raw) - 3):
        value = int.from_bytes(raw[offset:offset + 4], "little")
        text = stringinfo.get(value)
        if text is not None and text.startswith(ICON_STRING_PREFIX):
            return value, text
    return None, None


def discover_item_model_family(
    row: ItemInfoRow,
    *,
    stringinfo: Mapping[int, str],
    pappt: PartPrefabTable,
    read_entry: ReadEntry,
    path_exists: Optional[Callable[[str], bool]] = None,
) -> ItemModelFamily:
    """Resolve the model family of `row`.

    `stringinfo` is hash -> text; `read_entry` returns an archive payload or None; and
    `path_exists` answers whether a path is in the archive, defaulting to "read_entry
    returned something". Every file the owned family consists of is listed by
    convention, existing or not, so a caller can see exactly which convention failed.
    """

    exists = path_exists or (lambda path: bool(read_entry(path)))
    notes: list[str] = []
    stems = find_part_stems(row, stringinfo, pappt)
    if not stems:
        raise ItemModelFamilyError(f"item {row.key} ({row.string_key}) references no part-prefab stems")
    icon_hash, icon_string = find_icon_string(row, stringinfo)

    index = pappt.index()
    resolved: list[tuple[int, str, Optional[PartPrefabRecord], str]] = []
    for value, stem in stems:
        record = index.get(stem)
        pac_path = _prefab_pac_path(read_entry, record.prefab_path) if record is not None else ""
        if record is None:
            notes.append(f"{stem} is not in partprefabtable.pappt")
        elif not pac_path:
            notes.append(f"{record.prefab_path} names no .pac (unreadable, or not a mesh prefab)")
        resolved.append((value, stem, record, pac_path))

    model_stem, how = _choose_model_stem(icon_string, resolved, index, read_entry)
    notes.append(how)
    parts = _classify(model_stem, resolved)
    if not any(part.owned for part in parts):
        # The icon named a mesh no part draws (a helm whose icon shows a sibling tier, say).
        fallback, how = _choose_model_stem(None, resolved, index, read_entry)
        notes.append(f"no part draws {model_stem!r}; falling back: {how}")
        model_stem, parts = fallback, _classify(fallback, resolved)
    owned = [part for part in parts if part.owned]
    if not owned:
        raise ItemModelFamilyError(
            f"item {row.key} ({row.string_key}) has no part whose mesh starts with {model_stem!r}: "
            + ", ".join(f"{part.stem} -> {part.pac_path or '?'}" for part in parts)
        )
    pac_paths = sorted({part.pac_path for part in owned if part.pac_path}, key=str.lower)
    model_folder = _folder_under(pac_paths[0], MODEL_ROOT) if pac_paths else ""

    files: list[FamilyFile] = []
    for pac_path in pac_paths:
        stem = _stem_of(pac_path)
        folder = _folder_under(pac_path, MODEL_ROOT)
        files.append(_file("pac", pac_path, read_entry, exists, stem))
        files.append(_file("pac_xml", f"{MODEL_PROPERTY_ROOT}/{folder}/{stem}.pac_xml", read_entry, exists, stem))
        files.append(_file("hkx", f"{MESH_PHYSICS_ROOT}/{folder}/{stem}.hkx", read_entry, exists, stem))
    for part in owned:
        if part.record is not None:
            files.append(FamilyFile("prefab", part.prefab_path, exists(part.prefab_path), None))
    if icon_string:
        icon_path = f"{ICON_FOLDER}/{icon_string.lower()}.dds"
        files.append(FamilyFile("icon", icon_path, exists(icon_path), None))
    else:
        notes.append("no ItemIcon_Prefab_* string in the row; the icon is not part of the family")

    return ItemModelFamily(
        item_key=row.key,
        model_stem=model_stem,
        model_folder=model_folder,
        parts=parts,
        files=tuple(files),
        icon_string=icon_string,
        icon_hash=icon_hash,
        notes=tuple(notes),
    )


def _classify(
    model_stem: str, resolved: list[tuple[int, str, Optional[PartPrefabRecord], str]]
) -> Tuple[FamilyPart, ...]:
    return tuple(
        FamilyPart(stem=stem, hash=value, record=record, pac_path=pac_path, owned=_owns(model_stem, stem, pac_path))
        for value, stem, record, pac_path in resolved
    )


def _file(role: str, path: str, read_entry: ReadEntry, exists, stem: str) -> FamilyFile:
    if role in ("pac", "pac_xml"):
        data = read_entry(path)
        if data:
            return FamilyFile(role, path, True, stem.lower().encode("utf-8") in bytes(data).lower())
        return FamilyFile(role, path, exists(path), None)
    return FamilyFile(role, path, exists(path), None)


def _folder_under(path: str, root: str) -> str:
    text = str(path or "").replace("\\", "/")
    prefix = root.rstrip("/") + "/"
    if not text.lower().startswith(prefix.lower()):
        return text.rsplit("/", 1)[0] if "/" in text else ""
    rest = text[len(prefix):]
    return rest.rsplit("/", 1)[0] if "/" in rest else ""


def _owns(model_stem: str, part_stem: str, pac_path: str) -> bool:
    if not model_stem:
        return False
    if pac_path:
        return _stem_of(pac_path).lower().startswith(model_stem.lower())
    return part_stem.lower().startswith(model_stem.lower())


def _choose_model_stem(
    icon_string: Optional[str],
    resolved: list[tuple[int, str, Optional[PartPrefabRecord], str]],
    index: Mapping[str, PartPrefabRecord],
    read_entry: ReadEntry,
) -> Tuple[str, str]:
    """The family stem and a sentence saying how it was picked."""

    icon_stem = _icon_stem(icon_string or "").lower()
    pac_stems = [_stem_of(pac_path).lower() for _v, _s, _r, pac_path in resolved if pac_path]
    if icon_stem:
        record = index.get(icon_stem)
        if record is not None:
            pac_path = next((p for _v, s, _r, p in resolved if s == icon_stem), None)
            if pac_path is None:
                pac_path = _prefab_pac_path(read_entry, record.prefab_path)
            if pac_path:
                stem = _stem_of(pac_path).lower()
                return stem, f"model stem {stem!r} is the mesh of the icon's part {icon_stem!r}"
        if icon_stem in pac_stems:
            return icon_stem, f"model stem {icon_stem!r} is the icon string, and a part draws that mesh"
        named = [(stem, pac_path) for _v, stem, _r, pac_path in resolved if stem.lower().startswith(icon_stem)]
        if named:
            meshes = Counter(_stem_of(pac_path).lower() for _s, pac_path in named if pac_path)
            if meshes:
                stem = meshes.most_common(1)[0][0]
                return stem, f"model stem {stem!r} is the mesh of the parts the icon string {icon_stem!r} names"
            return icon_stem, f"model stem {icon_stem!r} is the icon string, matched on part stems (no pac read)"
    if pac_stems:
        stem, count = Counter(pac_stems).most_common(1)[0]
        why = "the icon string names none of the parts" if icon_stem else "no icon string"
        return stem, f"model stem {stem!r} is the mesh {count} part(s) share ({why})"
    stem = resolved[0][1].lower()
    return stem, f"model stem {stem!r} is the first part stem (no icon string and no readable prefab)"


__all__ = [
    "FILE_ROLES",
    "ICON_FOLDER",
    "ICON_STRING_PREFIX",
    "FamilyFile",
    "FamilyPart",
    "ItemModelFamily",
    "ItemModelFamilyError",
    "discover_item_model_family",
    "find_icon_string",
    "find_part_stems",
]
