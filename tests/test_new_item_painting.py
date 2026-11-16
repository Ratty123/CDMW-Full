"""Create New Item's painting template, planned over a small synthetic game.

Every table row, text table, prefab and mesh here is synthetic (no game bytes). The
mesh parser is replaced by a canvas quad; textures and icons by fixed stand-ins.
"""
import json
import struct
from pathlib import Path

import pytest
from PIL import Image

from cdmw.core.compact_static import field_payload, read_compact_layout
from cdmw.core.item_layout import read_item_layout
from cdmw.core.paloc_format import LocalizationEntry, LocalizationTable, encode_paloc, parse_paloc
from cdmw.core.painting_records import gimmick_text_key, housing_group_members
from cdmw.core.stringinfo_table import build_stringinfo_row, stringinfo_key
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.models import ArchiveEntry
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.new_item_painting import (
    PaintingPlanError,
    PaintingRequest,
    PaintingSource,
    discover_painting_frames,
    plan_paintings,
    read_painting_mod,
)
from tests.compact_item_fixtures import item, table, text
from tests.test_gimmickinfo_patch_layout import gimmick, record
from tests.test_prefab_binary_edit import _build as prefab_naming

BIN = "gamedata/binarystaticinfo__/bin/"
ITEM, GIMMICK, HOUSING, GROUP = 1001295, 1001509, 17227, 16968
NAME = "Collection_Prop_Picture_0001"
PREFAB_VALUE = "/object/cd_gimmick/00_common/interior/dpw/gimmick_in_dpw_picture_01_painting_01.prefab"
PREFAB_FILE = "object/bin__/cd_gimmick/00_common/interior/dpw/gimmick_in_dpw_picture_01_painting_01.prefab"
PAMI = "object/00_common/interior/decopropw/cd_in_dpw_picture_01_painting_01.pami"
MESH = "object/00_common/interior/decopropw/cd_in_dpw_picture_01.pam"
PICTURE = "object/texture/cd_in_picture_04.dds"
ICON_STRING = "ItemIcon_" + NAME
ICON_FILE = "ui/texture/icon/itemicon_collection_prop_picture_0001.dds"
NAME_KEY, DESC_KEY = str(ITEM << 32 | 0x70), str(ITEM << 32 | 0x71)
REGISTRY = "ui/xml/texture/cd_item_icon.xml"
PAMI_TEXT = f"""<StaticMeshInstance Version="1">
\t<StaticMesh Path="{MESH}"/>
\t<MaterialData>
\t\t<Material PrimitiveName="cd_in_picture_09">
\t\t\t<Parameters>
\t\t\t\t<MaterialParameterTexture Name="_baseColorTexture" Value="{PICTURE}"/>
\t\t\t</Parameters>
\t\t</Material>
\t\t<Material PrimitiveName="cd_bg_wood_01">
\t\t\t<Parameters>
\t\t\t\t<MaterialParameterTexture Name="_baseColorTexture" Value="object/texture/cd_bg_wood_01.dds"/>
\t\t\t</Parameters>
\t\t</Material>
\t</MaterialData>
</StaticMeshInstance>
"""


def paloc(*entries):
    return encode_paloc(LocalizationTable(entries=tuple(LocalizationEntry(category=7, key=k, text=t) for k, t in entries)))


def dds_header(width, height):
    return b"DDS " + struct.pack("<II", 124, 0) + struct.pack("<II", height, width) + bytes(108)


def game_files():
    item_row = item(fields={"_stringKey": text(NAME), "_gimmickInfo": struct.pack("<I", GIMMICK),
                            "_itemIconList": struct.pack("<III", 1, stringinfo_key(ICON_STRING), 0xEAC5E173) + bytes(6)})
    gimmick_row = gimmick(GIMMICK, NAME, fields={
        "_prefabPath": text(PREFAB_VALUE),
        "_gimmickName": b"\x20" + struct.pack("<Q", gimmick_text_key(GIMMICK)) + text(str(gimmick_text_key(GIMMICK))),
        "_convertItemInfo": struct.pack("<I", ITEM), "_housingObjectInfo": struct.pack("<H", HOUSING)})
    housing_row = record("housingobjectinfo", {"_stringKey": text(NAME), "_key": struct.pack("<H", HOUSING),
                                               "_gimmickInfo": struct.pack("<I", GIMMICK)})
    group_row = record("housingobjectgroupinfo", {"_stringKey": text("HousingGroup_Collection_Picture"),
                                                  "_key": struct.pack("<H", GROUP),
                                                  "_housingObjectInfoList": struct.pack("<IH", 1, HOUSING)})
    other_group = record("housingobjectgroupinfo", {"_stringKey": text("HousingGroup_Other"), "_key": struct.pack("<H", 16969)})
    files = {}

    def put(stem, rows, width=4):
        files[BIN + stem + ".staticinfobody"], files[BIN + stem + ".staticinfoheader"] = table(rows, width)

    put("iteminfo", [(ITEM, item_row)])
    put("iteminfo.dlc_01", [(1990000, item(fields={"_stringKey": text("Dlc_Item")}))])
    put("gimmickinfo", [(GIMMICK, gimmick_row)])
    put("gimmickinfo.dlc_01", [(1990001, gimmick(1990001, "Dlc_Gimmick"))])
    put("housingobjectinfo", [(HOUSING, housing_row)], 2)
    put("housingobjectgroupinfo", [(GROUP, group_row), (16969, other_group)], 2)
    put("stringinfo", [(stringinfo_key(ICON_STRING), build_stringinfo_row(ICON_STRING))])
    for language, frame in (("eng", "Picture Frame"), ("kor", "액자")):
        root = f"gamedata/stringtable/binary__/{language}/"
        files[root + "item.paloc"] = paloc(("100", "x"), (NAME_KEY, f"{language} name"), (DESC_KEY, f"{language} desc"))
        files[root + "gimmick.paloc"] = paloc((str(gimmick_text_key(GIMMICK)), frame))
    files[REGISTRY] = (b'<Texture Name="' + ICON_STRING.encode() + b'"\tFilename="UI/texture/icon/'
                       + ICON_FILE.rsplit("/", 1)[1].encode() + b'" Type="Image" GetRect="0,0,256,256"/>\r\n')
    files[PREFAB_FILE] = prefab_naming(PAMI)
    files[PAMI] = PAMI_TEXT.encode()
    files[MESH] = b"PAR mesh stand-in"
    files[PICTURE] = dds_header(512, 256)
    files[ICON_FILE] = dds_header(256, 256)
    return files


def entry(path):
    return ArchiveEntry(path=path, pamt_path=Path("game/0008/0.pamt"), paz_file=Path("game/0008/0.paz"),
                        offset=0, comp_size=0, orig_size=0, flags=0, paz_index=0)


def source(files=None, overlay=None):
    files = game_files() if files is None else files
    tables = {stem: (BIN + stem + ".staticinfobody", BIN + stem + ".staticinfoheader")
              for stem in ("iteminfo", "iteminfo.dlc_01", "gimmickinfo", "gimmickinfo.dlc_01", "housingobjectinfo",
                           "housingobjectgroupinfo", "stringinfo")}
    return PaintingSource(
        entry_of=lambda path: entry(path) if path.lower() in files else None,
        read_game=lambda path: files[path.lower()],
        tables=tables,
        item_paloc={language: f"gamedata/stringtable/binary__/{language}/item.paloc" for language in ("eng", "kor")},
        overlay={path: (lambda data=data: data) for path, data in (overlay or {}).items()},
    )


@pytest.fixture(autouse=True)
def canvas_mesh(monkeypatch):
    """parse_pam returns a frame whose canvas maps 0.775 x 0.639 m onto u 0.134..0.909, v 0.003..0.993."""
    def parse(data, filename=""):
        w, h = 0.775, 0.639
        canvas = SubMesh(name="c", material="cd_in_picture_09",
                         vertices=[(-w / 2, h, 0), (w / 2, h, 0), (-w / 2, 0, 0), (w / 2, 0, 0)],
                         uvs=[(0.134, 0.003), (0.909, 0.003), (0.134, 0.993), (0.909, 0.993)], faces=[(0, 1, 2)])
        wood = SubMesh(name="w", material="cd_bg_wood_01", vertices=[(-0.43, 0.75, 0), (0.43, 0.75, 0), (-0.43, 0, 0)],
                       uvs=[(1, 0), (0, 0), (1, 1)], faces=[(0, 1, 2)])
        return ParsedMesh(path=filename, format="pam", bbox_min=(-0.428, 0.003, -0.1), bbox_max=(0.428, 0.756, 0.0),
                          submeshes=[canvas, wood])
    monkeypatch.setattr("cdmw.modding.mesh_parser.parse_pam", parse)


ENCODED = []


def encode(image, plan, frame):
    ENCODED.append((image.size, plan))
    return dds_header(plan.width, plan.height) + b"bc1"


def icon(picture, reference_entry, reference, icon_string):
    return f"ui/texture/icon/{icon_string.lower()}.dds", dds_header(256, 256)


@pytest.fixture
def picture(tmp_path):
    path = tmp_path / "my picture.png"
    Image.new("RGB", (300, 200), (10, 20, 30)).save(path)
    return path


def rows(plan, stem):
    files = plan.loose_files
    body, header = files[BIN + stem + ".staticinfobody"], files[BIN + stem + ".staticinfoheader"]
    return {r.row_id: body[s:e] for r, s, e in parse_pabgh_table(header, payload=body).row_spans(len(body))}


def test_the_frames_come_from_the_picture_group_with_their_canvas_and_source():
    catalogue = discover_painting_frames(source())
    assert [frame.mesh for frame in catalogue.frames] == [MESH]
    frame = catalogue.frames[0]
    assert frame.canvas.material == "cd_in_picture_09"
    assert frame.texture_size == (512, 256)
    assert (frame.source.item_key, frame.source.gimmick_key, frame.source.housing_key) == (ITEM, GIMMICK, HOUSING)
    assert (frame.source.pami, frame.source.prefab_file, frame.source.picture_texture) == (PAMI, PREFAB_FILE, PICTURE)
    assert frame.label == "0.86 x 0.75 m frame, picture 0.77 x 0.64 m (cd_in_dpw_picture_01)"


def test_a_painting_adds_its_rows_group_entry_texts_and_files_to_the_base_tables_only(picture):
    src = source()
    plan = plan_paintings(src, discover_painting_frames(src),
                          [PaintingRequest(frame=MESH, picture=picture, names={"eng": "My Painting"},
                                           descriptions={"eng": "Painted by me."})],
                          encode_texture=encode, build_icon=icon)
    painting = plan.manifest["paintings"][0]
    item_key, gimmick_key, housing_key = painting["item_key"], painting["gimmick_key"], painting["housing_key"]
    # Free of the base and DLC rows alike, item and gimmick never sharing a number.
    assert (item_key, gimmick_key, housing_key) == (1990002, 1990003, 20000)
    assert not [request.entry.path for request in plan.patches if ".dlc_" in request.entry.path]
    item_row = read_item_layout(rows(plan, "iteminfo")[item_key])
    gimmick_row = read_compact_layout(rows(plan, "gimmickinfo")[gimmick_key], "gimmickinfo")
    housing_row = read_compact_layout(rows(plan, "housingobjectinfo")[housing_key], "housingobjectinfo")
    assert field_payload(item_row, "_gimmickInfo") == struct.pack("<I", gimmick_key)
    assert field_payload(gimmick_row, "_convertItemInfo") == struct.pack("<I", item_key)
    assert field_payload(gimmick_row, "_housingObjectInfo") == struct.pack("<H", housing_key)
    assert field_payload(housing_row, "_gimmickInfo") == struct.pack("<I", gimmick_key)
    assert set(rows(plan, "iteminfo")) == {ITEM, item_key}
    assert housing_group_members(rows(plan, "housingobjectgroupinfo")[GROUP]) == (HOUSING, housing_key)
    assert rows(plan, "housingobjectgroupinfo")[16969] == rows(plan, "housingobjectgroupinfo")[16969]
    # Texts: the user's in English, English again where a language has none; the gimmick keeps its frame text.
    for language, frame_text in (("eng", "Picture Frame"), ("kor", "액자")):
        items = parse_paloc(plan.loose_files[f"gamedata/stringtable/binary__/{language}/item.paloc"]).index()
        gimmicks = parse_paloc(plan.loose_files[f"gamedata/stringtable/binary__/{language}/gimmick.paloc"]).index()
        assert items[str(item_key << 32 | 0x70)].text == "My Painting"
        assert items[str(item_key << 32 | 0x71)].text == "Painted by me."
        assert items[str(item_key << 32 | 0x70)].category == items[NAME_KEY].category
        assert gimmicks[str(gimmick_key << 32 | 0x200)].text == frame_text
    # Files at new paths: picture, material, prefab and icon.
    assert sorted(plan.new_paths) == sorted([
        f"object/texture/cd_in_picture_cdmw_{item_key}.dds",
        f"object/00_common/interior/decopropw/cd_in_dpw_picture_cdmw_{item_key}.pami",
        f"object/bin__/cd_gimmick/00_common/interior/dpw/gimmick_in_dpw_picture_cdmw_{item_key}.prefab",
        f"ui/texture/icon/itemicon_prefab_cdmw_painting_{item_key}.dds"])
    pami = plan.loose_files[painting["files"]["pami"]].decode()
    assert f"object/texture/cd_in_picture_cdmw_{item_key}.dds" in pami and PICTURE not in pami
    assert painting["files"]["pami"].encode() in plan.loose_files[painting["files"]["prefab"]]
    assert b"ItemIcon_Prefab_cdmw_painting_1990002" in plan.loose_files[REGISTRY]
    # The texture plan: the source picture's size, BC1, full mips, the canvas rectangle.
    assert painting["texture"] == {"width": 512, "height": 256, "format": "BC1_UNORM", "mips": 10, "rect": [68, 0, 466, 255]}
    assert ENCODED[-1][0] == (512, 256)


def test_two_paintings_get_their_own_keys_and_both_join_the_group(picture):
    src = source()
    requests = [PaintingRequest(frame=MESH, picture=picture, names={"eng": f"Painting {n}"}) for n in (1, 2)]
    plan = plan_paintings(src, discover_painting_frames(src), requests, encode_texture=encode, build_icon=icon)
    first, second = plan.manifest["paintings"]
    assert len({first["item_key"], first["gimmick_key"], second["item_key"], second["gimmick_key"]}) == 4
    assert first["housing_key"] != second["housing_key"]
    assert housing_group_members(rows(plan, "housingobjectgroupinfo")[GROUP]) == (HOUSING, first["housing_key"], second["housing_key"])
    items = parse_paloc(plan.loose_files["gamedata/stringtable/binary__/eng/item.paloc"]).index()
    # No description given: the name stands in for it.
    assert items[str(second["item_key"] << 32 | 0x71)].text == "Painting 2"


def test_a_second_build_into_the_same_mod_keeps_the_first_painting(picture):
    src = source()
    first = plan_paintings(src, discover_painting_frames(src), [PaintingRequest(frame=MESH, picture=picture, names={"eng": "One"})],
                           encode_texture=encode, build_icon=icon)
    again = source(overlay=first.loose_files)
    second = plan_paintings(again, discover_painting_frames(again), [PaintingRequest(frame=MESH, picture=picture, names={"eng": "Two"})],
                            encode_texture=encode, build_icon=icon, earlier=first.manifest["paintings"])
    one, two = second.manifest["paintings"]
    assert one == first.manifest["paintings"][0]
    assert len({one["item_key"], one["gimmick_key"], two["item_key"], two["gimmick_key"]}) == 4
    assert {one["item_key"], two["item_key"]} <= set(rows(second, "iteminfo"))
    assert {one["gimmick_key"], two["gimmick_key"]} <= set(rows(second, "gimmickinfo"))
    assert housing_group_members(rows(second, "housingobjectgroupinfo")[GROUP]) == (HOUSING, one["housing_key"], two["housing_key"])
    items = parse_paloc(second.loose_files["gamedata/stringtable/binary__/kor/item.paloc"]).index()
    assert (items[str(one["item_key"] << 32 | 0x70)].text, items[str(two["item_key"] << 32 | 0x70)].text) == ("One", "Two")
    # The first painting's files stay in the mod; the second plan adds only its own.
    assert not set(first.new_paths) & set(second.new_paths)
    assert [frame.mesh for frame in discover_painting_frames(again).frames] == [MESH]


@pytest.mark.parametrize("change, message", [
    (dict(picture=""), "Painting 1: Choose a picture for the painting."),
    (dict(frame=""), "Painting 1: Choose a frame for the painting."),
    (dict(frame="object/other.pam"), "is not one CDMW can use"),
    (dict(names={"kor": "only Korean"}), "give the painting an English name"),
])
def test_refusals_name_what_to_change(picture, change, message):
    src = source()
    request = PaintingRequest(**{**dict(frame=MESH, picture=picture, names={"eng": "Name"}), **change})
    with pytest.raises(PaintingPlanError, match=message):
        plan_paintings(src, discover_painting_frames(src), [request], encode_texture=encode, build_icon=icon)


def test_an_unreadable_picture_and_an_empty_list_are_refused(tmp_path):
    src = source()
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"\xff\xd8 not really")
    with pytest.raises(PaintingPlanError, match="broken.jpg could not be read as a picture"):
        plan_paintings(src, discover_painting_frames(src), [PaintingRequest(frame=MESH, picture=broken, names={"eng": "A"})],
                       encode_texture=encode, build_icon=icon)
    with pytest.raises(PaintingPlanError, match="Add at least one painting"):
        plan_paintings(src, discover_painting_frames(src), [], encode_texture=encode, build_icon=icon)


def test_a_mod_folder_is_extended_only_when_it_is_a_painting_mod_with_all_its_files(tmp_path, monkeypatch):
    monkeypatch.setenv("CDMW_PROFILE_DIR", str(tmp_path / "profile"))
    assert read_painting_mod(tmp_path / "missing") == ({}, ())
    mod = tmp_path / "mod"
    (mod / "object/texture").mkdir(parents=True)
    (mod / "object/texture/cd_in_picture_cdmw_1990002.dds").write_bytes(b"dds")
    record = {"kind": "paintings", "paintings": [{"internal_name": "Collection_Prop_Picture_CDMW_1990002",
                                                  "files": {"texture": "object/texture/cd_in_picture_cdmw_1990002.dds"}}]}
    (mod / "new-item.json").write_text(json.dumps(record), encoding="utf-8")
    overlay, earlier = read_painting_mod(mod)
    assert overlay["object/texture/cd_in_picture_cdmw_1990002.dds"]() == b"dds"
    assert [p["internal_name"] for p in earlier] == ["Collection_Prop_Picture_CDMW_1990002"]
    (mod / "object/texture/cd_in_picture_cdmw_1990002.dds").unlink()
    (mod / "object/texture/other.dds").write_bytes(b"x")
    with pytest.raises(PaintingPlanError, match="has lost object/texture/cd_in_picture_cdmw_1990002.dds"):
        read_painting_mod(mod)
    (mod / "new-item.json").write_text(json.dumps({"item_key": 1990000}), encoding="utf-8")
    with pytest.raises(PaintingPlanError, match="holds another mod"):
        read_painting_mod(mod)
