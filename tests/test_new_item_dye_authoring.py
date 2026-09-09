"""Dye authoring preserves exact properties and shares preview/export preparation."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.core.item_dye_material import material_dye_bindings
from cdmw.core.partprefab_dye_table import (
    DyeMaterialBinding, DyeSubmesh, PrefabDyeRow, encode_prefab_dye_row,
    parse_prefab_dye_row, parse_prefab_dye_table,
)
from cdmw.domain.new_item.authoring import DyeAssignment
from cdmw.services.new_item_dyes import prepare_dye_assignments, prepare_dye_preview_table
from cdmw.services.new_item_mod_base import build_mod_base_snapshot
from cdmw.services.new_item_variants import xml_path
from tests.test_multichangeinfo_table import _table
from tests.test_new_item_provenance import current_files, spec
from tests.test_new_item_service import PAC, PAC_XML, build_package, _read
from tests.test_new_item_variant_authoring import selections
from tests.test_pac_xml_standard_material import wrapper, texture


def material(name="blade", properties=(0,2)):
    params = texture("_colorBlendingMaskTexture","1","character/texture/template_mask.dds",0)
    params += '<MaterialParameterFloat StringItemID="_dyeingGlobalOpacity" ItemID="2" _name="_dyeingGlobalOpacity" _value="1" Index="1"/>'
    return ('<ModelPropertyList>'+''.join(f'<ModelProperty Index="{index}">'+wrapper(name,"SkinnedMeshStandard_Ver2",params)+'</ModelProperty>' for index in properties)+'</ModelPropertyList>').encode()


def dye_row():
    binding = DyeMaterialBinding(("metal","cloth",""),bytes(12))
    row = PrefabDyeRow(0,"Blade",False,(DyeSubmesh("blade",(0,1,-1),binding,(replace(binding,property_index=2),)),),PAC)
    return row.for_model(PAC)


def test_dye_roundtrip_and_explicit_property_mask_mapping():
    row = dye_row()
    assert parse_prefab_dye_row(encode_prefab_dye_row(row)) == row
    assignments = (DyeAssignment("custom","blade",(4,3,2),"mask.dds"),)
    parts,result = prepare_dye_assignments(row,material("custom"),material(),assignments,
                                         imported=True,mask_paths={"custom":"character/texture/custom_mask.dds"})
    assert parts[0].name == "custom" and parts[0].slots == (4,3,2)
    assert parts[0].overrides == row.submeshes[0].overrides
    bindings = material_dye_bindings(result)
    assert set(bindings)=={(0,"custom"),(2,"custom")}
    assert all(w.textures["_colorBlendingMaskTexture"].endswith("custom_mask.dds") for w in bindings.values())
    assert prepare_dye_assignments(row,material(),material(),None,imported=False) == (row.submeshes,material())
    assert prepare_dye_assignments(row,material(),material(),(),imported=True)[0] == ()
    with pytest.raises(ValueError,match="explicit RGB mask"):
        prepare_dye_assignments(row,material("custom"),material(),assignments,imported=True)
    with pytest.raises(ValueError,match="exact source and target"):
        prepare_dye_assignments(row,material("Custom"),material(),assignments,imported=True)
    with pytest.raises(ValueError,match="property 3"):
        prepare_dye_assignments(row,material("custom",(0,3)),material(),assignments,imported=True,mask_paths={"custom":"x.dds"})


def test_preview_table_replaces_only_the_selected_dye_row():
    row = dye_row()
    other = row.for_model("character/model/other.pac")
    payload, header = _table([(value.key, encode_prefab_dye_row(value)) for value in (row, other)])
    index = SimpleNamespace(pair=SimpleNamespace(payload=payload, header=header))
    parts = (replace(row.submeshes[0], slots=(4, 3, 2)),)
    prepared, prepared_header = prepare_dye_preview_table(index, row, parts)
    assert parse_prefab_dye_table(prepared, prepared_header) == (replace(row, submeshes=parts), other)
    assert parse_prefab_dye_table(payload, header) == (row, other)


def test_incompatible_inherited_dyes_are_optional_only_for_imported_materials():
    row = dye_row()
    imported_material = material("custom")
    assert prepare_dye_assignments(row, imported_material, material(), None, imported=True) == ((), imported_material)
    with pytest.raises(ValueError, match="template wiring is incompatible"):
        prepare_dye_assignments(row, imported_material, material(), None, imported=False)


@pytest.mark.parametrize("imported_name", ["blade", "custom"])
def test_explicit_template_dyes_apply_when_compatible_and_warn_otherwise(tmp_path, imported_name):
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.services.new_item_planning import ModelFiles
    from cdmw.services.new_item_service import NewItemService
    from tests.test_new_item_variant_rig import _pac

    files = current_files()
    files[PAC], files[PAC_XML] = _pac(), material()
    base = "gamedata/binarystaticinfo__/bin/partprefabdyeslotinfo"
    row = dye_row()
    files[base+".staticinfobody"], files[base+".staticinfoheader"] = _table([(row.key, encode_prefab_dye_row(row))])
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(build_package(tmp_path/"game", files)), read_entry=_read)
    choice = replace(selections(snapshot)[0], custom_model=True, dyes=None)
    model = ModelFiles(files[PAC], {PAC_XML: material(imported_name)})
    messages = []

    plan = service.plan(replace(spec(), variants=(choice,)), snapshot,
                        variant_models={choice.identity: model}, on_log=messages.append)

    output = next(value["output_model"] for value in plan.manifest["variants"] if "output_model" in value)
    rows = parse_prefab_dye_table(plan.loose_files[base+".staticinfobody"], plan.loose_files[base+".staticinfoheader"])
    assert row in rows
    expected = row.submeshes if imported_name == "blade" else ()
    assert next(value for value in rows if value.model_path == output).submeshes == expected
    assert plan.loose_files[xml_path(output)] == material(imported_name)
    if imported_name == "custom":
        warning = next(message for message in plan.warnings if "Template dyes were omitted" in message)
        assert PAC in warning and warning in messages
    else:
        assert not plan.warnings


@pytest.mark.parametrize("imported_name", ["blade", "custom"])
@pytest.mark.parametrize("legacy_adapter", [False, True])
def test_imported_plan_never_inherits_dyes_by_default(tmp_path, imported_name, legacy_adapter):
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.services.new_item_planning import ModelFiles
    from cdmw.services.new_item_service import NewItemService
    from tests.test_new_item_variant_rig import _pac

    files = current_files()
    files[PAC], files[PAC_XML] = _pac(), material()
    base = "gamedata/binarystaticinfo__/bin/partprefabdyeslotinfo"
    original = dye_row()
    files[base+".staticinfobody"], files[base+".staticinfoheader"] = _table([(original.key, encode_prefab_dye_row(original))])
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(build_package(tmp_path/"game", files)), read_entry=_read)
    choice = replace(selections(snapshot)[0], custom_model=True)
    model = ModelFiles(files[PAC], {PAC_XML: material(imported_name)})
    assert choice.dyes == ()
    if legacy_adapter:
        plan = service.plan(spec(), snapshot, model=model)
    else:
        plan = service.plan(replace(spec(), variants=(choice,)), snapshot, variant_models={choice.identity: model})

    output = next(value["output_model"] for value in plan.manifest["variants"] if "output_model" in value)
    rows = parse_prefab_dye_table(plan.loose_files[base+".staticinfobody"], plan.loose_files[base+".staticinfoheader"])
    assert original in rows
    assert next(value for value in rows if value.model_path == output).submeshes == ()
    assert plan.loose_files[xml_path(output)] == material(imported_name)
    assert not plan.warnings
    assert prepare_dye_assignments(original, b"unused material boundary", material(), (), imported=True) == ((), b"unused material boundary")


def test_dye_variant_export_survives_second_item_base(tmp_path):
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.services.new_item_service import NewItemService
    files = current_files()
    files[PAC_XML] = material()
    base = "gamedata/binarystaticinfo__/bin/partprefabdyeslotinfo"
    row = dye_row()
    files[base+".staticinfobody"],files[base+".staticinfoheader"] = _table([(row.key,encode_prefab_dye_row(row))])
    service=NewItemService()
    snapshot=service.build_snapshot(parse_archive_pamt(build_package(tmp_path/"game",files)),read_entry=_read)
    choice=replace(selections(snapshot)[0],dyes=(DyeAssignment("blade","blade",(2,1,0)),))
    first=service.plan(replace(spec(),variants=(choice,)),snapshot)
    model=next(v["output_model"] for v in first.manifest["variants"] if "output_model" in v)
    authored=next(r for r in parse_prefab_dye_table(first.loose_files[base+".staticinfobody"],first.loose_files[base+".staticinfoheader"]) if r.model_path==model)
    assert authored.submeshes[0].slots==(2,1,0)
    expected=prepare_dye_assignments(row,material(),material(),choice.dyes,imported=False)[1]
    assert first.loose_files[xml_path(model)] == expected
    service.export_loose(first,tmp_path/"first",manager="JMM")
    inherited=build_mod_base_snapshot(service,snapshot,tmp_path/"first",read_entry=_read)
    second=service.plan(replace(spec("Second"),variants=(replace(choice,dyes=()),)),inherited)
    rows=parse_prefab_dye_table(second.loose_files[base+".staticinfobody"],second.loose_files[base+".staticinfoheader"])
    assert authored in rows and any(not r.submeshes for r in rows)
    assert second.loose_files[xml_path(model)] == first.loose_files[xml_path(model)]

    # A prior dye definition can survive even when its model asset is absent.
    # Its hash still reserves that variant identity.
    reserved=dye_row().for_model(model)
    files[base+".staticinfobody"],files[base+".staticinfoheader"]=_table([(row.key,encode_prefab_dye_row(row)),(reserved.key,encode_prefab_dye_row(reserved))])
    orphan_snapshot=service.build_snapshot(parse_archive_pamt(build_package(tmp_path/"orphan",files)),read_entry=_read)
    third=service.plan(replace(spec(),variants=(choice,)),orphan_snapshot)
    third_model=next(v["output_model"] for v in third.manifest["variants"] if "output_model" in v)
    assert third_model!=model
    assert reserved in parse_prefab_dye_table(third.loose_files[base+".staticinfobody"],third.loose_files[base+".staticinfoheader"])


def test_dye_controls_collapse_and_write_current_variant(tmp_path):
    from cdmw.ui.new_item.dye_editor import DyeEditor
    from cdmw.ui.new_item.controller import NewItemStudioController
    from tests.test_new_item_provenance import setup_game
    from tests.test_new_item_service import TEMPLATE
    from PySide6.QtWidgets import QWidget
    app=QApplication.instance() or QApplication([])
    _,snapshot,_=setup_game(tmp_path)
    controller=NewItemStudioController(synchronous=True)
    controller.snapshot=snapshot
    controller.set_template(TEMPLATE)
    parent=QWidget()
    parent.refresh_preview=lambda:None
    editor=DyeEditor(controller,parent)
    assert editor.contents.isHidden()
    editor.setChecked(True)
    assert not editor.contents.isHidden()
    editor._ready("dyes",SimpleNamespace(rows={PAC.casefold():dye_row()}))
    editor.slots[0].setValue(5)
    editor.add.click()
    assert controller.current_spec().variants[0].dyes[0].slots[0]==5
    editor.clear.click()
    assert controller.current_spec().variants[0].dyes==()
    controller.shutdown()


def test_template_dye_preview_ignores_retained_inactive_import(tmp_path):
    import threading
    from cdmw.ui.new_item.dye_preview import variant_dye_preview_source
    from cdmw.ui.new_item.controller import NewItemStudioController
    from tests.test_new_item_provenance import setup_game
    from tests.test_new_item_service import TEMPLATE
    app=QApplication.instance() or QApplication([])
    _,snapshot,_=setup_game(tmp_path)
    controller=NewItemStudioController(synchronous=True)
    controller.snapshot=snapshot
    controller.set_template(TEMPLATE)
    identity=controller.primary_variant_identity()
    controller.select_variant(identity)
    controller.model_result=SimpleNamespace(rebuilt_data=b"retained custom model")
    controller.set_variant_dyes(())
    with patch("cdmw.services.mesh_workflow_service.parse_pac") as parse:
        _token,preview=variant_dye_preview_source(controller)
        preview.geometry(threading.Event())
    assert parse.call_args.args[0]==snapshot.payload(identity[1])
    assert not controller.current_spec().variants[0].custom_model
    controller.shutdown()


def test_dye_mask_revisions_reject_stale_requests_and_invalidate_export(tmp_path):
    from cdmw.services.new_item_dyes import dye_mask_revision, read_dye_mask
    from cdmw.services.new_item_provenance import SourceTracker, StaleNewItemSource
    mask = tmp_path / "mask.dds"
    mask.write_bytes(b"initial DDS")
    revision = dye_mask_revision(mask)
    snapshot = SimpleNamespace(provenance=SourceTracker(lambda entry: b""))
    with patch("cdmw.core.dds_native.inspect_dds_native"):
        assert read_dye_mask(snapshot, mask, expected_revision=revision) == b"initial DDS"
    planned = snapshot.provenance.capture()
    mask.write_bytes(b"changed DDS bytes")
    with pytest.raises(StaleNewItemSource, match="Dye mask changed"):
        read_dye_mask(snapshot, mask, expected_revision=revision)
    with pytest.raises(StaleNewItemSource, match="Source changed"):
        planned.validate()


def test_dye_preview_token_changes_when_an_external_mask_is_replaced(tmp_path):
    from cdmw.ui.new_item.controller import NewItemStudioController
    from cdmw.ui.new_item.dye_preview import variant_dye_preview_source
    from tests.test_new_item_provenance import setup_game
    from tests.test_new_item_service import TEMPLATE
    app = QApplication.instance() or QApplication([])
    _, snapshot, _ = setup_game(tmp_path)
    controller = NewItemStudioController(synchronous=True)
    controller.snapshot = snapshot
    controller.set_template(TEMPLATE)
    controller.select_variant(controller.primary_variant_identity())
    mask = tmp_path / "mask.dds"
    mask.write_bytes(b"initial")
    controller.set_variant_dyes((DyeAssignment("blade", "blade", (1, 2, 0), str(mask)),))
    try:
        first, _ = variant_dye_preview_source(controller)
        mask.write_bytes(b"replacement")
        second, _ = variant_dye_preview_source(controller)
        assert first != second
    finally:
        controller.shutdown()
