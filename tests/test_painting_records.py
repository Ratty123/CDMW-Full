"""A new painting's rows: keys, names and the fields a clone changes.

Rows are synthetic, written field by field from the closed schema (no game bytes).
"""
import struct

import pytest

from cdmw.core.compact_static import read_compact_layout
from cdmw.core.item_layout import read_item_layout
from cdmw.core.painting_records import (
    PaintingKeys,
    PaintingRecordError,
    add_housing_group_member,
    allocate_painting_keys,
    clone_painting_gimmick,
    clone_painting_housing,
    clone_painting_item,
    gimmick_prefab_file,
    gimmick_text_key,
    housing_group_members,
    painting_paths,
    retarget_pami_picture,
)
from cdmw.core.stringinfo_table import stringinfo_key
from tests.compact_item_fixtures import item, text
from tests.test_gimmickinfo_patch_layout import gimmick, record

SOURCE_ITEM, SOURCE_GIMMICK, SOURCE_HOUSING = 1001295, 1001509, 17227
SOURCE_NAME = "Collection_Prop_Picture_0001"
PREFAB = "/object/cd_gimmick/00_common/interior/dpw/gimmick_in_dpw_picture_01_painting_01.prefab"
ICON = stringinfo_key("ItemIcon_Collection_Prop_Picture_0001")
NEW = PaintingKeys(item=1990000, gimmick=1990001, housing=20000)


def gimmick_name(key):
    return b"\x20" + struct.pack("<Q", gimmick_text_key(key)) + text(str(gimmick_text_key(key)))


def source_gimmick(**overrides):
    fields = {"_prefabPath": text(PREFAB), "_gimmickName": gimmick_name(SOURCE_GIMMICK),
              "_convertItemInfo": struct.pack("<I", SOURCE_ITEM), "_housingObjectInfo": struct.pack("<H", SOURCE_HOUSING),
              "_initScale": struct.pack("<f", 1.0)}
    fields.update(overrides)
    return gimmick(SOURCE_GIMMICK, SOURCE_NAME, fields=fields)


def source_housing(gimmick_key=SOURCE_GIMMICK):
    return record("housingobjectinfo", {"_stringKey": text(SOURCE_NAME), "_key": struct.pack("<H", SOURCE_HOUSING),
                                        "_gimmickInfo": struct.pack("<I", gimmick_key)})


def group(members):
    return record("housingobjectgroupinfo", {"_stringKey": text("HousingGroup_Collection_Picture"),
                                             "_key": struct.pack("<H", 16968),
                                             "_housingObjectInfoList": struct.pack("<I", len(members))
                                             + b"".join(struct.pack("<H", m) for m in members)})


def source_item(gimmick_key=SOURCE_GIMMICK):
    return item(fields={"_gimmickInfo": struct.pack("<I", gimmick_key), "_knowledgeInfo": struct.pack("<I", 1000212),
                        "_itemIconList": struct.pack("<III", 1, ICON, 0xEAC5E173) + bytes(6)})


def changed(kind, before, after):
    a, b = read_compact_layout(before, kind), read_compact_layout(after, kind)
    assert set(a.fields) == set(b.fields)
    return {name for name in a.fields if a.data(name) != b.data(name)}


def test_keys_avoid_every_used_number_and_two_paintings_get_different_keys():
    first, second = allocate_painting_keys(2, item_keys={1990000, 1990002}, gimmick_keys={1990003},
                                           housing_keys={20000, 20001})
    assert first == PaintingKeys(item=1990001, gimmick=1990004, housing=20002)
    assert second == PaintingKeys(item=1990005, gimmick=1990006, housing=20003)
    assert len({first.item, first.gimmick, second.item, second.gimmick}) == 4
    assert first.name == "Collection_Prop_Picture_CDMW_1990001"


def test_reserved_numbers_are_taken_by_no_key():
    (keys,) = allocate_painting_keys(1, item_keys=(), gimmick_keys=(), housing_keys=(), reserved={1990000, 1990001, 20000})
    assert keys == PaintingKeys(item=1990002, gimmick=1990003, housing=20001)


def test_new_paths_sit_beside_the_source_files_and_map_the_prefab_to_bin():
    paths = painting_paths(NEW, prefab_value=PREFAB, pami="object/00_common/interior/decopropw/cd_in_dpw_picture_01_painting_01.pami")
    assert paths.prefab_value == "/object/cd_gimmick/00_common/interior/dpw/gimmick_in_dpw_picture_cdmw_1990000.prefab"
    assert paths.prefab_file == "object/bin__/cd_gimmick/00_common/interior/dpw/gimmick_in_dpw_picture_cdmw_1990000.prefab"
    assert paths.pami == "object/00_common/interior/decopropw/cd_in_dpw_picture_cdmw_1990000.pami"
    assert paths.texture == "object/texture/cd_in_picture_cdmw_1990000.dds"
    assert paths.icon_string == "ItemIcon_Prefab_cdmw_painting_1990000"
    assert gimmick_prefab_file(PREFAB) == "object/bin__/cd_gimmick/00_common/interior/dpw/gimmick_in_dpw_picture_01_painting_01.prefab"


def test_the_gimmick_clone_changes_exactly_its_six_identity_fields():
    source = source_gimmick()
    new_prefab = painting_paths(NEW, prefab_value=PREFAB, pami="object/a/b.pami").prefab_value
    clone = clone_painting_gimmick(source, source_key=SOURCE_GIMMICK, source_item=SOURCE_ITEM,
                                   source_housing=SOURCE_HOUSING, keys=NEW, prefab_value=new_prefab)
    assert changed("gimmickinfo", source, clone) == {"_stringKey", "_key", "_prefabPath", "_gimmickName",
                                                    "_convertItemInfo", "_housingObjectInfo"}
    layout = read_compact_layout(clone, "gimmickinfo")
    assert layout.data("_key") == struct.pack("<I", NEW.gimmick)
    assert layout.data("_stringKey") == text(NEW.name)
    assert layout.data("_prefabPath") == text(new_prefab)
    assert layout.data("_gimmickName") == gimmick_name(NEW.gimmick)
    assert NEW.gimmick_text_key == NEW.gimmick << 32 | 0x200
    assert layout.data("_convertItemInfo") == struct.pack("<I", NEW.item)
    assert layout.data("_housingObjectInfo") == struct.pack("<H", NEW.housing)


@pytest.mark.parametrize("overrides, message", [
    ({"_convertItemInfo": struct.pack("<I", 5)}, "does not turn into item"),
    ({"_housingObjectInfo": struct.pack("<H", 5)}, "does not name housing object"),
    ({"_gimmickName": gimmick_name(42)}, "no name of the shipped painting shape"),
])
def test_a_gimmick_not_shaped_like_a_painting_is_refused(overrides, message):
    with pytest.raises(PaintingRecordError, match=message):
        clone_painting_gimmick(source_gimmick(**overrides), source_key=SOURCE_GIMMICK, source_item=SOURCE_ITEM,
                               source_housing=SOURCE_HOUSING, keys=NEW, prefab_value=PREFAB)


def test_the_housing_clone_changes_name_key_and_gimmick_only():
    source = source_housing()
    clone = clone_painting_housing(source, source_key=SOURCE_HOUSING, source_gimmick=SOURCE_GIMMICK, keys=NEW)
    assert changed("housingobjectinfo", source, clone) == {"_stringKey", "_key", "_gimmickInfo"}
    layout = read_compact_layout(clone, "housingobjectinfo")
    assert (layout.data("_key"), layout.data("_gimmickInfo")) == (struct.pack("<H", 20000), struct.pack("<I", 1990001))
    with pytest.raises(PaintingRecordError, match="does not name gimmick"):
        clone_painting_housing(source_housing(gimmick_key=7), source_key=SOURCE_HOUSING, source_gimmick=SOURCE_GIMMICK, keys=NEW)


def test_the_housing_group_gains_the_new_key_after_its_members():
    source = group((17227, 17228))
    grown = add_housing_group_member(source, NEW.housing)
    assert housing_group_members(grown) == (17227, 17228, 20000)
    assert changed("housingobjectgroupinfo", source, grown) == {"_housingObjectInfoList"}
    with pytest.raises(PaintingRecordError, match="already in this group"):
        add_housing_group_member(grown, NEW.housing)


def test_the_item_clone_takes_the_new_identity_icon_and_gimmick_and_keeps_the_rest():
    source = source_item()
    new_icon = stringinfo_key("ItemIcon_Prefab_cdmw_painting_1990000")
    clone = clone_painting_item(source, source_key=SOURCE_ITEM, source_gimmick=SOURCE_GIMMICK, keys=NEW,
                                name_key=str(NEW.item << 32 | 0x70), desc_key=str(NEW.item << 32 | 0x71),
                                icon_hashes={ICON: new_icon})
    before, after = read_item_layout(source), read_item_layout(clone)
    assert {n for n in before.fields if before.data(n) != after.data(n)} == {
        "_stringKey", "_key", "_itemName", "_itemDesc", "_itemIconList", "_gimmickInfo"}
    assert after.data("_gimmickInfo") == struct.pack("<I", NEW.gimmick)
    assert after.data("_knowledgeInfo") == struct.pack("<I", 1000212)
    assert struct.pack("<I", new_icon) in after.data("_itemIconList")
    assert str(NEW.item << 32 | 0x70).encode() in after.data("_itemName")
    with pytest.raises(PaintingRecordError, match="does not name gimmick"):
        clone_painting_item(source_item(gimmick_key=9), source_key=SOURCE_ITEM, source_gimmick=SOURCE_GIMMICK, keys=NEW,
                            name_key="1", desc_key="2", icon_hashes={})


PAMI = """<StaticMeshInstance Version="1">
\t<StaticMesh Path="object/00_common/interior/decopropw/cd_in_dpw_picture_01.pam"/>
\t<MaterialData>
\t\t<Material PrimitiveName="cd_in_picture_09">
\t\t\t<Parameters>
\t\t\t\t<MaterialParameterTexture Name="_baseColorTexture" Value="object/texture/cd_in_picture_04.dds"/>
\t\t\t\t<MaterialParameterTexture Name="_materialTexture" Value="object/texture/cd_in_picture_11_sp.dds"/>
\t\t\t</Parameters>
\t\t</Material>
\t\t<Material PrimitiveName="cd_bg_trimborder_wood_29">
\t\t\t<Parameters>
\t\t\t\t<MaterialParameterTexture Name="_baseColorTexture" Value="object/texture/cd_bg_trimborder_wood_29.dds"/>
\t\t\t</Parameters>
\t\t</Material>
\t</MaterialData>
</StaticMeshInstance>
"""


def test_the_material_file_points_only_the_canvas_at_the_new_picture():
    edited = retarget_pami_picture(PAMI, "cd_in_picture_09", "object/texture/cd_in_picture_cdmw_1990000.dds")
    assert edited == PAMI.replace("object/texture/cd_in_picture_04.dds", "object/texture/cd_in_picture_cdmw_1990000.dds")
    assert "cd_bg_trimborder_wood_29.dds" in edited and "cd_in_picture_11_sp.dds" in edited
    with pytest.raises(PaintingRecordError, match="0 materials named"):
        retarget_pami_picture(PAMI, "cd_missing", "x.dds")
