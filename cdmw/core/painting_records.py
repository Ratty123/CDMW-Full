"""The table rows and file names of a new painting, cloned from a shipped one.

A shipped painting (`Collection_Prop_Picture_0001` to `_0078`) is a chain of rows that
name each other by key, read from game 1.0.0.3663 with CDMW's own readers
(`.work/research/2026-11-16-paintings-build/links.txt` of the branch that built this):

* ItemInfo `_gimmickInfo` names the GimmickInfo row;
* GimmickInfo `_convertItemInfo` names the item and `_housingObjectInfo` the housing
  object (a u16 key); `_gimmickName` carries a text key `gimmick key << 32 | 0x200`
  that `gimmick.paloc` resolves ("Picture Frame");
* HousingObjectInfo `_gimmickInfo` names the gimmick;
* HousingObjectGroupInfo `HousingGroup_Collection_Picture` lists the housing key.

All three rows also share one `_stringKey`. On all 78 paintings these are the only
fields that hold the item, gimmick or housing key, so a clone changes exactly them,
plus the gimmick's prefab path, and leaves every other byte of the source row alone.
Three gimmick rows hold their housing key's two bytes inside
`_gimmickInteractionOverrideDataList`; those are the low half of a u32
`_originInteractionInfo` (an interaction key), not a housing reference.

Nothing here reads or writes an archive; callers pass row bytes and get row bytes.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Tuple

from cdmw.core.compact_static import field_bytes, field_payload, read_compact_layout
from cdmw.core.item_layout import counted_integers, read_item_layout, replace_layout_fields
from cdmw.core.new_item_record import RecordError, text_bytes
from cdmw.domain.new_item.allocation import DEFAULT_ITEM_KEY_RANGE

__all__ = [
    "GIMMICK_TEXT_TAG",
    "HOUSING_KEY_RANGE",
    "PAINTING_NAME_PREFIX",
    "PaintingKeys",
    "PaintingPaths",
    "PaintingRecordError",
    "add_housing_group_member",
    "allocate_painting_keys",
    "clone_painting_gimmick",
    "clone_painting_housing",
    "clone_painting_item",
    "gimmick_prefab_file",
    "gimmick_text_key",
    "housing_group_members",
    "painting_paths",
    "retarget_pami_picture",
]

#: Internal name of every row a painting adds: item, gimmick and housing object alike.
PAINTING_NAME_PREFIX = "Collection_Prop_Picture_CDMW_"
#: The low word of a gimmick's text key, on every shipped gimmick name.
GIMMICK_TEXT_TAG = 0x200
#: Housing object keys are u16. Shipped base and DLC keys stop at 18378; new ones start
#: well above that so a later game update is less likely to reach them.
HOUSING_KEY_RANGE = range(20000, 0xFFFF)


class PaintingRecordError(ValueError):
    """A source row is not shaped like a shipped painting's, or a clone cannot be made."""


@dataclass(frozen=True, slots=True)
class PaintingKeys:
    """The three keys one new painting owns."""

    item: int
    gimmick: int
    housing: int

    @property
    def name(self) -> str:
        """The `_stringKey` of the painting's item, gimmick and housing rows."""

        return f"{PAINTING_NAME_PREFIX}{self.item}"

    @property
    def gimmick_text_key(self) -> int:
        return gimmick_text_key(self.gimmick)


@dataclass(frozen=True, slots=True)
class PaintingPaths:
    """Where a new painting's files go, all at paths the game does not ship."""

    texture: str
    pami: str
    prefab_file: str
    prefab_value: str
    icon_string: str


def gimmick_text_key(key: int) -> int:
    """`gimmick key << 32 | 0x200`: the `gimmick.paloc` key a gimmick's name resolves through."""

    return (int(key) << 32) | GIMMICK_TEXT_TAG


def _free(candidates: Iterable[int], taken: set, what: str) -> int:
    for value in candidates:
        if value not in taken:
            taken.add(value)
            return value
    raise PaintingRecordError(f"No free {what} key is left.")


def allocate_painting_keys(
    count: int,
    *,
    item_keys: Iterable[int],
    gimmick_keys: Iterable[int],
    housing_keys: Iterable[int],
    reserved: Iterable[int] = (),
) -> Tuple[PaintingKeys, ...]:
    """`count` sets of free keys, lowest first.

    Item and gimmick keys come from Create New Item's range (1990000 up) and never repeat
    a number used in either table, so one number never names two things. Callers pass
    every key of the base and DLC layers and of the mod being extended, and in `reserved`
    the numbers CDMW already handed to mods the game does not have installed (Create New
    Item's issued identities); a reserved number is taken by no key of any kind.
    """

    taken = {int(value) for value in reserved}
    numbers = {int(value) for value in item_keys} | {int(value) for value in gimmick_keys} | taken
    housing = {int(value) for value in housing_keys} | taken
    result = []
    for _ in range(int(count)):
        item = _free(DEFAULT_ITEM_KEY_RANGE, numbers, "item")
        gimmick = _free(DEFAULT_ITEM_KEY_RANGE, numbers, "gimmick")
        result.append(PaintingKeys(item=item, gimmick=gimmick, housing=_free(HOUSING_KEY_RANGE, housing, "housing")))
    return tuple(result)


def gimmick_prefab_file(value: str) -> str:
    """The archive path of the prefab a GimmickInfo `_prefabPath` names.

    The row says `/object/cd_gimmick/...prefab`; the file is `object/bin__/cd_gimmick/...`.
    That held for all 78 shipped paintings.
    """

    text = str(value or "").replace("\\", "/").strip("/")
    head, _, rest = text.partition("/")
    if not head or not rest or not text.lower().endswith(".prefab") or rest.lower().startswith("bin__/"):
        raise PaintingRecordError(f"{value!r} is not a gimmick prefab path of the shipped shape.")
    return f"{head}/bin__/{rest}"


def painting_paths(keys: PaintingKeys, *, prefab_value: str, pami: str) -> PaintingPaths:
    """New paths beside the source painting's own files, named after the new item key."""

    stem = f"cdmw_{int(keys.item)}"
    folder, _, _name = str(prefab_value).rpartition("/")
    pami_folder = str(pami).replace("\\", "/").rpartition("/")[0]
    if not folder or not pami_folder:
        raise PaintingRecordError("The source painting's prefab or material path has no folder.")
    value = f"{folder}/gimmick_in_dpw_picture_{stem}.prefab"
    return PaintingPaths(
        texture=f"object/texture/cd_in_picture_{stem}.dds",
        pami=f"{pami_folder}/cd_in_dpw_picture_{stem}.pami",
        prefab_file=gimmick_prefab_file(value),
        prefab_value=value,
        icon_string=f"ItemIcon_Prefab_cdmw_painting_{int(keys.item)}",
    )


def _u(layout, field: str, width: int) -> int:
    payload = field_payload(layout, field)
    if payload is None or len(payload) != width:
        raise PaintingRecordError(f"{field} is not a {width * 8}-bit key in this row.")
    return int.from_bytes(payload, "little")


def _text(payload: Optional[bytes], field: str) -> str:
    if payload is None or len(payload) < 4 or struct.unpack_from("<I", payload)[0] != len(payload) - 4:
        raise PaintingRecordError(f"{field} is not a text value in this row.")
    return payload[4:].decode("utf-8")


def _read(raw: bytes, kind: str):
    try:
        return read_compact_layout(bytes(raw), kind)
    except RecordError as exc:
        raise PaintingRecordError(f"The source {kind} row cannot be read: {exc}") from exc


def _replace(layout, edits: Mapping[str, bytes]):
    try:
        return replace_layout_fields(layout, dict(edits))
    except RecordError as exc:
        raise PaintingRecordError(f"The {layout.kind} clone could not be written: {exc}") from exc


def clone_painting_gimmick(
    raw: bytes,
    *,
    source_key: int,
    source_item: int,
    source_housing: int,
    keys: PaintingKeys,
    prefab_value: str,
) -> bytes:
    """The source painting's GimmickInfo row with the new painting's identity.

    Changes `_stringKey`, `_key`, `_prefabPath`, `_gimmickName` (its text key and that key
    as text), `_convertItemInfo` and `_housingObjectInfo`; every other field keeps the
    source's bytes. The source must name exactly the item and housing object given, and
    its name must carry its own text key, as all 78 shipped painting gimmicks do.
    """

    layout = _read(raw, "gimmickinfo")
    if _u(layout, "_key", 4) != int(source_key):
        raise PaintingRecordError(f"GimmickInfo row {source_key} carries another key.")
    if _u(layout, "_convertItemInfo", 4) != int(source_item):
        raise PaintingRecordError(f"GimmickInfo {source_key} does not turn into item {source_item}.")
    if _u(layout, "_housingObjectInfo", 2) != int(source_housing):
        raise PaintingRecordError(f"GimmickInfo {source_key} does not name housing object {source_housing}.")
    name = layout.data("_gimmickName")
    old_text_key = gimmick_text_key(source_key)
    if len(name) < 13 or struct.unpack_from("<Q", name, 1)[0] != old_text_key or name[9:] != text_bytes(str(old_text_key)):
        raise PaintingRecordError(f"GimmickInfo {source_key} has no name of the shipped painting shape.")
    old_prefab = _text(field_payload(layout, "_prefabPath"), "_prefabPath")
    if not old_prefab.lower().endswith(".prefab") or not str(prefab_value).lower().endswith(".prefab"):
        raise PaintingRecordError(f"GimmickInfo {source_key} names no prefab.")
    if old_prefab.startswith("/") != str(prefab_value).startswith("/"):
        raise PaintingRecordError("The new prefab path must keep the source path's leading slash.")
    new_text_key = keys.gimmick_text_key
    edits = {
        "_key": field_bytes(layout, "_key", struct.pack("<I", keys.gimmick)),
        "_prefabPath": field_bytes(layout, "_prefabPath", text_bytes(str(prefab_value))),
        "_gimmickName": name[:1] + struct.pack("<Q", new_text_key) + text_bytes(str(new_text_key)),
        "_convertItemInfo": field_bytes(layout, "_convertItemInfo", struct.pack("<I", keys.item)),
        "_housingObjectInfo": field_bytes(layout, "_housingObjectInfo", struct.pack("<H", keys.housing)),
    }
    if "_stringKey" in layout.fields:
        edits["_stringKey"] = field_bytes(layout, "_stringKey", text_bytes(keys.name))
    return _replace(layout, edits).raw


def clone_painting_housing(raw: bytes, *, source_key: int, source_gimmick: int, keys: PaintingKeys) -> bytes:
    """The source painting's HousingObjectInfo row with the new name, key and gimmick."""

    layout = _read(raw, "housingobjectinfo")
    if _u(layout, "_key", 2) != int(source_key):
        raise PaintingRecordError(f"HousingObjectInfo row {source_key} carries another key.")
    if _u(layout, "_gimmickInfo", 4) != int(source_gimmick):
        raise PaintingRecordError(f"HousingObjectInfo {source_key} does not name gimmick {source_gimmick}.")
    edits = {
        "_key": field_bytes(layout, "_key", struct.pack("<H", keys.housing)),
        "_gimmickInfo": field_bytes(layout, "_gimmickInfo", struct.pack("<I", keys.gimmick)),
    }
    if "_stringKey" in layout.fields:
        edits["_stringKey"] = field_bytes(layout, "_stringKey", text_bytes(keys.name))
    return _replace(layout, edits).raw


def housing_group_members(raw: bytes) -> Tuple[int, ...]:
    """The housing keys a HousingObjectGroupInfo row lists."""

    layout = _read(raw, "housingobjectgroupinfo")
    try:
        return counted_integers(layout, "_housingObjectInfoList", width=2)
    except RecordError as exc:
        raise PaintingRecordError(f"The housing group's member list cannot be read: {exc}") from exc


def add_housing_group_member(raw: bytes, housing_key: int) -> bytes:
    """The HousingObjectGroupInfo row with `housing_key` appended to its member list."""

    layout = _read(raw, "housingobjectgroupinfo")
    members = housing_group_members(raw)
    if int(housing_key) in members:
        raise PaintingRecordError(f"Housing object {housing_key} is already in this group.")
    values = (*members, int(housing_key))
    data = struct.pack("<I", len(values)) + b"".join(struct.pack("<H", value) for value in values)
    return _replace(layout, {"_housingObjectInfoList": field_bytes(layout, "_housingObjectInfoList", data)}).raw


def clone_painting_item(
    raw: bytes,
    *,
    source_key: int,
    source_gimmick: int,
    keys: PaintingKeys,
    name_key: str,
    desc_key: Optional[str],
    icon_hashes: Mapping[int, int],
) -> bytes:
    """The source painting's ItemInfo row as the new item: key, name, texts, icon, gimmick.

    The identity edits are Create New Item's own (`clone_iteminfo_row`); then
    `_gimmickInfo` is pointed at the new gimmick. The knowledge row, item groups, price
    and every other field stay the source painting's.
    """

    from cdmw.core.iteminfo_row import ItemInfoRowError, clone_iteminfo_row, parse_iteminfo_row

    try:
        row = parse_iteminfo_row(bytes(raw))
        if row.key != int(source_key):
            raise PaintingRecordError(f"ItemInfo row {source_key} carries another key.")
        cloned = clone_iteminfo_row(row, key=keys.item, string_key=keys.name, name_key=str(name_key),
                                    desc_key=desc_key, replace_hashes=dict(icon_hashes) or None)
        layout = read_item_layout(cloned)
    except (ItemInfoRowError, RecordError) as exc:
        raise PaintingRecordError(f"Item {source_key} cannot be cloned: {exc}") from exc
    if _u(layout, "_gimmickInfo", 4) != int(source_gimmick):
        raise PaintingRecordError(f"Item {source_key} does not name gimmick {source_gimmick}.")
    return _replace(layout, {"_gimmickInfo": field_bytes(layout, "_gimmickInfo", struct.pack("<I", keys.gimmick))}).raw


_MATERIAL = re.compile(r"<Material\b[^>]*>.*?</Material>", re.S)
_BASE_COLOR = re.compile(r'(<MaterialParameterTexture\s+Name="_baseColorTexture"\s+Value=")([^"]*)(")')
_PRIMITIVE = re.compile(r'PrimitiveName="([^"]*)"')


def _primitive_name(block: str) -> Optional[str]:
    match = _PRIMITIVE.search(block[: block.find(">") + 1])
    return match.group(1).strip() if match else None


def retarget_pami_picture(text: str, material: str, texture_path: str) -> str:
    """The `.pami` text with one material's `_baseColorTexture` pointed at `texture_path`.

    Exactly one `<Material>` must have `PrimitiveName` equal to `material`, and it must
    have exactly one `_baseColorTexture`; every other character stays as it was.
    """

    wanted = str(material).strip()
    blocks = [match for match in _MATERIAL.finditer(text) if _primitive_name(match.group(0)) == wanted]
    if len(blocks) != 1:
        raise PaintingRecordError(f"The frame's material file has {len(blocks)} materials named {wanted!r}, not one.")
    block = blocks[0]
    found = list(_BASE_COLOR.finditer(block.group(0)))
    if len(found) != 1:
        raise PaintingRecordError(f"Material {wanted!r} has {len(found)} base colour textures, not one.")
    edited = _BASE_COLOR.sub(lambda match: match.group(1) + str(texture_path) + match.group(3), block.group(0))
    return text[: block.start()] + edited + text[block.end():]
