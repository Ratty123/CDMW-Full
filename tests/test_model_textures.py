"""The Textures panel's list, grouping, sharing rule and Make unique (decision 48, P6)."""
from __future__ import annotations

import pytest

from cdmw.domain.model_preview_materials import PreviewMaterialTextureInput as Slot
from cdmw.services.model_textures import (
    TEXTURE_GROUPS,
    make_texture_unique,
    model_texture_list,
    texture_group,
    texture_sharing,
    unique_texture_path,
)

SHARED = "character/texture/shared_cloth_n.dds"
SIDECAR = (
    "<Root>"
    + "".join(
        f'<SkinnedMeshMaterialWrapper _subMeshName="part{i}"><Material Name="_resourceMaterial" _materialName="M">'
        f'<Vector Name="_parameters">'
        f'<MaterialParameterTexture _name="_diffuseTexture" Index="0"><ResourceReferencePath_ITexture _path="character/texture/own{i}.dds"/></MaterialParameterTexture>'
        f'<MaterialParameterTexture _name="_normalTexture" Index="1"><ResourceReferencePath_ITexture _path="{SHARED}"/></MaterialParameterTexture>'
        "</Vector></Material></SkinnedMeshMaterialWrapper>"
        for i in range(2)
    )
    + "</Root>"
)


def _slots():
    rows = []
    for i in range(2):
        rows.append(Slot(slot_kind="base", parameter_name="_diffuseTexture", source_texture_path=f"character/texture/own{i}.dds",
                         material_name="M", part_name=f"part{i}"))
        rows.append(Slot(slot_kind="normal", parameter_name="_normalTexture", source_texture_path=SHARED,
                         material_name="M", part_name=f"part{i}"))
    rows.append(Slot(slot_kind="material", parameter_name="_materialTexture", source_texture_path="character/texture/own0_sp.dds",
                     part_name="part0"))
    rows.append(Slot(slot_kind="material_mask", source_texture_path="character/texture/own0_ma.dds", part_name="part0"))
    rows.append(Slot(slot_kind="base", layer_role="detail", source_texture_path="character/texture/cloth_detail.dds", part_name="part0"))
    rows.append(Slot(slot_kind="", source_texture_path="character/texture/cd_texturelayer_dirt.dds", part_name="part0"))
    rows.append(Slot(slot_kind="emissive", source_texture_path="character/texture/own0_e.dds", part_name="part0"))
    rows.append(Slot(slot_kind="", parameter_name="_mysteryTexture", source_texture_path="character/texture/x.dds", part_name="part0"))
    rows.append(Slot(slot_kind="base", source_texture_path="", part_name="part0"))  # no file: not listed
    return rows


def test_groups_follow_the_sidecars_slot_kinds_in_panel_order():
    groups = model_texture_list(_slots())
    assert [group.key for group in groups] == list(TEXTURE_GROUPS)
    by_group = {group.key: [texture.path for texture in group.textures] for group in groups}
    assert by_group["colour"] == ["character/texture/own0.dds", "character/texture/own1.dds"]
    assert by_group["normal"] == [SHARED]
    assert by_group["material_response"] == ["character/texture/own0_sp.dds"]
    assert by_group["masks"] == ["character/texture/own0_ma.dds"]
    assert by_group["detail"] == ["character/texture/cloth_detail.dds", "character/texture/cd_texturelayer_dirt.dds"]
    assert by_group["emissive"] == ["character/texture/own0_e.dds"]
    assert by_group["other"] == ["character/texture/x.dds"]


def test_a_texture_read_by_several_parts_is_one_row_with_every_part():
    normal = next(group for group in model_texture_list(_slots()) if group.key == "normal").textures[0]
    assert normal.parts == ("part0", "part1") and normal.slot_kinds == ("normal",)


def test_the_fallbacks_for_rows_without_a_slot_kind():
    assert texture_group(Slot(semantic_type="normal")) == "normal"
    assert texture_group(Slot(parameter_name="_emissiveColorTexture")) == "emissive"
    assert texture_group(Slot()) == "other"
    # A graph layer's normal map stays a normal map.
    assert texture_group(Slot(slot_kind="normal", layer_role="detail")) == "normal"


def _texture(path):
    return next(texture for group in model_texture_list(_slots()) for texture in group.textures if texture.path == path)


def test_a_texture_only_the_edited_parts_read_can_be_edited_in_place():
    sharing = texture_sharing(_texture("character/texture/own0.dds"), ["part0"])
    assert not sharing.needs_unique and sharing.reason == "" and sharing.other_files is None


def test_another_part_of_the_model_makes_it_shared():
    sharing = texture_sharing(_texture(SHARED), ["part0"])
    assert sharing.needs_unique and sharing.other_parts == ("part1",) and "part1" in sharing.reason
    assert not texture_sharing(_texture(SHARED), ["part0", "PART1"]).needs_unique


def test_a_stock_texture_name_is_always_shared():
    stock = Slot(slot_kind="base", source_texture_path="character/texture/cd_common_default_d.dds", part_name="part0")
    texture = model_texture_list([stock])[0].textures[0]
    assert texture.shared_name and texture_sharing(texture, ["part0"]).needs_unique


def test_the_archive_scan_counts_only_other_files_and_only_when_it_ran():
    texture = _texture("character/texture/own1.dds")
    own = ["character/model/thing.pac_xml"]
    assert not texture_sharing(texture, ["part1"], other_files=["CHARACTER/model/thing.pac_xml"], own_files=own).needs_unique
    sharing = texture_sharing(texture, ["part1"], other_files=[*own, "a.pac_xml", "b.pac_xml", "c.pac_xml", "d.pac_xml"], own_files=own)
    assert sharing.needs_unique and sharing.other_files == ("a.pac_xml", "b.pac_xml", "c.pac_xml", "d.pac_xml")
    assert "1 more" in sharing.reason


def test_make_unique_rewrites_only_the_chosen_parts_and_keeps_every_other_byte():
    made = make_texture_unique(SHARED, sidecar_path="character/modelproperty/thing.pac_xml", sidecar_data=SIDECAR.encode(),
                               parts=["part0"], stem="thing")
    assert made.new_path == unique_texture_path(SHARED, "thing")
    assert made.new_path.startswith("character/texture/thing_r") and made.new_path.endswith("_n.dds")
    text = made.sidecar_data.decode()
    assert text.count(made.new_path) == 1 and text.count(SHARED) == 1
    assert text.index(made.new_path) < text.index('_subMeshName="part1"') < text.index(SHARED)
    assert text.replace(made.new_path, SHARED) == SIDECAR
    assert made.parts == ("part0",)


def test_make_unique_refuses_a_taken_name_and_parts_that_do_not_use_the_texture():
    taken = unique_texture_path(SHARED, "thing")
    with pytest.raises(ValueError, match="already exists"):
        make_texture_unique(SHARED, sidecar_path="x.pac_xml", sidecar_data=SIDECAR.encode(), parts=["part0"], stem="thing",
                            existing_paths={taken})
    with pytest.raises(ValueError, match="None of the chosen parts"):
        make_texture_unique("character/texture/own1.dds", sidecar_path="x.pac_xml", sidecar_data=SIDECAR.encode(),
                            parts=["part0"], stem="thing")
    with pytest.raises(ValueError, match="at least one part"):
        make_texture_unique(SHARED, sidecar_path="x.pac_xml", sidecar_data=SIDECAR.encode(), parts=[], stem="thing")
