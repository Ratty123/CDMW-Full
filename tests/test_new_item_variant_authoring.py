from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
import pytest

from cdmw.core.pappt_format import parse_pappt
from cdmw.core.stringinfo_table import stringinfo_key
from cdmw.domain.new_item.authoring import VariantAppearance
from cdmw.services.new_item_planning import ModelFiles
from cdmw.services.new_item_variants import variant_bindings, prepare_variant_models
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.model_import import ModelPlacement, ModelImportSource
from tests.test_new_item_provenance import setup_game, spec
from tests.test_new_item_service import TEMPLATE
from tests.test_new_item_socket_authoring import planned_row


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


def test_two_variant_imports_keep_distinct_assets_and_missing_build_is_rejected(tmp_path):
    service,snapshot,_ = setup_game(tmp_path)
    choices = tuple(replace(value,custom_model=True) for value in selections(snapshot)[:2])
    builds = {choices[0].identity:ModelFiles(b"import A", notes=("Transferred armour weights",), warnings=("Check fit A",)),
              choices[1].identity:ModelFiles(b"import B", warnings=("Check fit B",))}
    with patch("cdmw.services.new_item_variants.validate_variant_rig") as validate:
        plan = service.plan(replace(spec(),variants=choices),snapshot,variant_models=builds)
    assert validate.call_count==2
    assert [call.kwargs["prefab_path"] for call in validate.call_args_list] == [choice.prefab_path for choice in choices]
    paths = [entry["output_model"] for entry in plan.manifest["variants"] if "output_model" in entry]
    assert len(paths)==2 and len(set(paths))==2
    assert {plan.loose_files[path] for path in paths}=={b"import A",b"import B"}
    assert any("Transferred armour weights" in line for line in plan.summary_lines)
    assert f"{choices[0].model_path}: Check fit A" in plan.warnings
    assert f"{choices[1].model_path}: Check fit B" in plan.warnings
    with pytest.raises(ValueError,match="Apply the imported model"):
        prepare_variant_models(replace(spec(),variants=(choices[0],)),snapshot,{}, {})


def test_variant_allocation_avoids_an_occupied_string_hash(tmp_path):
    service,snapshot,_=setup_game(tmp_path)
    choice=selections(snapshot)[0]
    first=service.plan(replace(spec(),variants=(choice,)),snapshot)
    name=next(iter(first.manifest["pappt_records"].values()))
    snapshot.stringinfo_texts=dict(snapshot.stringinfo_texts)
    snapshot.stringinfo_texts[stringinfo_key(name)]="Existing string with colliding hash"
    second=service.plan(replace(spec(),variants=(choice,)),snapshot)
    assert next(iter(second.manifest["pappt_records"].values()))==name+"_2"


def test_variant_switch_preserves_placement_and_sources_until_shutdown(tmp_path):
    app = QApplication.instance() or QApplication([])
    _,snapshot,_ = setup_game(tmp_path)
    controller = NewItemStudioController(synchronous=True)
    controller.snapshot=snapshot
    controller.set_template(TEMPLATE)
    first,second = [value.identity for value in selections(snapshot)[:2]]
    controller.select_variant(first)
    source=ModelImportSource(Path("first.obj"),Path("first.obj"),SimpleNamespace(),None,None)
    controller.model_import=source
    controller.set_model_placement(ModelPlacement(offset=(1.0,2.0,3.0)))
    controller.select_variant(second)
    assert controller.model_import is None and not source._retired
    controller.select_variant(first)
    assert controller.model_import is source
    assert controller.model_placement.offset==(1.0,2.0,3.0)
    assert controller.template_primary_entry().path.casefold()==first[1]
    assert controller.template_prefab_entries()[0].path.casefold()==first[0]
    controller.shutdown()
    assert source._retired


def test_single_model_adapter_targets_primary_and_variant_glow_is_separate(tmp_path):
    service,snapshot,_=setup_game(tmp_path)
    with patch("cdmw.services.new_item_variants.validate_variant_rig"):
        plan=service.plan(spec(),snapshot,model=ModelFiles(b"primary only"))
    assert len(plan.spec.variants)==1
    assert sum(v["appearance"]=="custom model" for v in plan.manifest["variants"])==1
    choice=replace(selections(snapshot)[0],custom_model=True,glow_parts=("blade",),glow_color=(1,0,0))
    result=SimpleNamespace(rebuilt_data=b"applied",supplemental_file_specs=())
    with patch("cdmw.services.new_item_variants.validate_variant_rig"), patch("cdmw.services.new_item_materials.route_model_files",return_value=ModelFiles(b"applied")) as route:
        prepare_variant_models(replace(spec(),variants=(choice,)),snapshot,{choice.identity:result},{})
    assert route.call_args.kwargs["glow"].color==(1,0,0)


def test_variant_plan_holds_all_sources_until_worker_exit(tmp_path):
    import threading,time
    app=QApplication.instance() or QApplication([])
    controller=NewItemStudioController()
    sources=[]
    for i in range(2):
        directory=tmp_path/str(i)
        directory.mkdir()
        (directory/"model.obj").write_text("model")
        sources.append(ModelImportSource(directory/"model.obj",directory/"model.obj",None,None,None,extract_root=directory,owns_extract_root=True))
    started,release=threading.Event(),threading.Event()
    def work(log,stop):
        started.set()
        release.wait(3)
        assert all(source.model_path.exists() for source in sources)
        return None
    assert controller._run("plan",work,lambda result:None,lambda error:None,source_owners=tuple(sources))
    assert started.wait(2)
    for source in sources:
        controller._cleanup_model_source(source)
    controller.request_shutdown()
    assert all(source.model_path.exists() for source in sources)
    release.set()
    deadline=time.monotonic()+3
    while controller.iter_shutdown_workers() and time.monotonic()<deadline:
        app.processEvents()
        time.sleep(.01)
    assert not controller.iter_shutdown_workers()
    assert all(not source.model_path.exists() for source in sources)


def test_variant_selector_restores_camera_only_for_matching_ready_package(tmp_path):
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QWidget,QCheckBox
    from unittest.mock import Mock
    from cdmw.ui.new_item.variant_selector import VariantSelector
    class Preview(QObject):
        ready=Signal()
    app=QApplication.instance() or QApplication([])
    _,snapshot,_=setup_game(tmp_path)
    controller=NewItemStudioController(synchronous=True)
    controller.snapshot=snapshot
    controller.set_template(TEMPLATE)
    first,second=[choice.identity for choice in selections(snapshot)[:2]]
    controller.select_variant(first)
    panel=QWidget()
    panel.preview=Preview()
    panel.preview.host=Mock()
    panel.preview.host.view_state_snapshot.return_value={"yaw":17}
    panel._preview_mesh_token=None
    panel._sync_placement_numbers=lambda placement:None
    panel.refresh_preview=lambda:None
    panel.plain_pbr,panel.keep_physics=QCheckBox(),QCheckBox()
    selector=VariantSelector(controller,panel)
    assert selector.choice.currentData()==first
    second_index=next(i for i in range(selector.choice.count()) if selector.choice.itemData(i)==second)
    selector.choice.setCurrentIndex(second_index)
    assert controller._variant_states[first].camera=={"yaw":17}
    first_index=next(i for i in range(selector.choice.count()) if selector.choice.itemData(i)==first)
    selector.choice.setCurrentIndex(first_index)
    panel._preview_mesh_token="current"
    panel.preview._loaded_token="stale"
    panel.preview.ready.emit()
    panel.preview.host.restore_view_state.assert_not_called()
    panel.preview._loaded_token="current"
    panel.preview.ready.emit()
    panel.preview.host.restore_view_state.assert_called_once_with({"yaw":17})
    controller.shutdown()
