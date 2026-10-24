from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.pappt_format import encode_pappt, parse_pappt
from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.core.stringinfo_table import append_stringinfo_strings, stringinfo_key
from cdmw.domain.new_item.authoring import VariantAppearance
from cdmw.services.new_item_planning import ModelFiles
from cdmw.services.new_item_variants import variant_bindings, prepare_variant_models
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.model_import import ModelPlacement, ModelImportSource
from tests.test_new_item_provenance import current_files, setup_game, spec
from tests.test_new_item_service import TEMPLATE, STEM, build_package, _read
from tests.test_new_item_socket_authoring import planned_row
from tests.test_new_item_service import imported_pac
from tests.test_prefab_binary_edit import _build as build_prefab


def selections(snapshot):
    return tuple(VariantAppearance(part.prefab_path,path) for part,path in variant_bindings(snapshot.family(TEMPLATE)))


def test_selected_binding_gets_owned_resources_unselected_keeps_template(tmp_path):
    service,snapshot,_ = setup_game(tmp_path)
    choices = selections(snapshot)
    plan = service.plan(replace(spec(),variants=(choices[0],)),snapshot)
    variants = plan.manifest["variants"]
    assert any(v["prefab_path"]==choices[0].prefab_path and v["appearance"]=="owned template copy" for v in variants)
    assert any(v["prefab_path"]==choices[1].prefab_path and v["appearance"]=="template" for v in variants)
    mapping = plan.manifest["pappt_records"]
    assert len(mapping)==1
    row = planned_row(snapshot,plan)
    old,new = next(iter(mapping.items()))
    assert stringinfo_key(new).to_bytes(4,"little") in row.raw
    assert stringinfo_key(old).to_bytes(4,"little") not in row.raw
    assert choices[1].model_path not in plan.loose_files


@pytest.mark.parametrize("custom_model,keep_physics", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("composed", [False, True])
def test_armour_variant_physics_follows_exported_mesh_not_indexed_prefab(tmp_path, custom_model, keep_physics, composed):
    from cdmw.services.new_item_service import NewItemService

    files = current_files()
    pappt_path = "character/bin__/partprefabtable.pappt"
    table = parse_pappt(files[pappt_path])
    original_stem = STEM + "_r"
    record = replace(table.find(original_stem), stem="cd_phm_00_hand_0008_03_index02",
                     folder="1_pc/01_phm/armor/11_hand")
    files[pappt_path] = encode_pappt(replace(table, records=tuple(
        record if part.stem == original_stem else part for part in table.records)))
    body_path = "gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody"
    files[body_path] = files[body_path].replace(stringinfo_key(original_stem).to_bytes(4, "little"),
                                               stringinfo_key(record.stem).to_bytes(4, "little"))
    string_body = body_path.replace("iteminfo", "stringinfo")
    string_head = string_body.replace("staticinfobody", "staticinfoheader")
    files[string_body], files[string_head], _ = append_stringinfo_strings(
        files[string_body], files[string_head], (record.stem,))
    model = "character/model/1_pc/1_phm/armor/11_hand/cd_phm_00_hand_belt_0008_03.pac"
    physics = model.replace("character/model/", "character/bin__/meshphysics/").replace(".pac", ".hkx")
    wrong_physics = physics.replace("hand_belt", "hand")
    files[record.prefab_path] = build_prefab(model)
    files[model] = imported_pac()
    files[physics] = b"mesh-owned collision"
    files[wrong_physics] = b"unrelated prefab-slot collision"
    source_physics = {model: physics}
    if composed:
        from cdmw.core.prefab_component_graft import graft_prefab_component
        from tests.test_prefab_component_graft import build_prefab as build_component_prefab

        companion = model.replace("11_hand/cd_phm_00_hand_belt", "18_acc/cd_phm_00_hand_acc")
        companion_hkx = companion.replace("character/model/", "character/bin__/meshphysics/").replace(".pac", ".hkx")
        first = build_component_prefab(component="PrimaryMesh", member_kind="pointer", value=model,
                                       pointee_type="ResourceReferencePath_SkinnedMesh")
        second = build_component_prefab(component="CompanionMesh", member_kind="pointer", value=companion,
                                        pointee_type="ResourceReferencePath_SkinnedMesh")
        files[record.prefab_path] = graft_prefab_component(first, second, component_type="CompanionMesh").data
        files[companion] = imported_pac(200)
        files[companion_hkx] = b"companion-owned collision"
        source_physics[companion] = companion_hkx
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(build_package(tmp_path / "game", files)), read_entry=_read)
    choice = VariantAppearance(record.prefab_path, model, custom_model=custom_model,
                               keep_template_physics=keep_physics)
    models = {choice.identity: ModelFiles(imported_pac(100))} if custom_model else None
    plan = service.plan(replace(spec(), variants=(choice,)), snapshot, variant_models=models)
    outputs = {row["model_path"]: row["output_model"] for row in plan.manifest["variants"] if "output_model" in row}
    assert set(outputs) == set(source_physics)
    expected = {
        target.replace("character/model/", "character/bin__/meshphysics/").replace(".pac", ".hkx"): files[source_physics[source]]
        for source, target in outputs.items() if source != model or not custom_model or keep_physics
    }
    copied = {path: data for path, data in plan.loose_files.items() if path.endswith(".hkx")}
    assert copied == expected
    output_prefab = next(path for path in plan.new_paths if path.endswith(".prefab"))
    assert set(outputs.values()) <= {ref.text for ref in decode_prefab_binary(plan.loose_files[output_prefab]).resource_strings()}
    assert snapshot.payload(model) == files[model]
    assert snapshot.payload(physics) == files[physics]
    assert snapshot.payload(wrong_physics) == files[wrong_physics]
