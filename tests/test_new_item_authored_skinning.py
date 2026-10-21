"""Authored GLB -> New Item import -> real shared PAC output, without a body."""

from dataclasses import replace

import pytest

from cdmw.domain.mesh.skin_policy import SkinningChoice, reduce_influences
from cdmw.modding.mesh_parser import parse_pac
from cdmw.modding.mesh_skinning import pack_pac_skin_weights, ensure_final_target_skin_weights
from cdmw.modding.static_mesh_build import build_static_mesh_replacement
from cdmw.modding.static_mesh_types import StaticSubmeshMapping
from cdmw.services.mesh_replacement_output import manual_replacement_options
from cdmw.services.mesh_skinning_preflight import preflight_imported_skin
from cdmw.ui.new_item.model_import import ModelImportSource, ModelPlacement, load_model_import_source
from tests.test_mesh_replacement_imported_skinning import editor, source_glb
from tests.test_new_item_model_apply import studio, _finish


def _prepare(editor, path, choices=()):
    service, sid, _order = editor
    snapshot = service.capture_export_snapshot(sid)
    source = load_model_import_source(path)
    try:
        mapped, reports = preflight_imported_skin(source.scene.mesh, snapshot.original_data,
            snapshot.mesh.interchange_skeleton, snapshot.mesh.path, choices=choices)
        return snapshot, mapped, reports
    finally:
        source.cleanup()


def _write(snapshot, mapped):
    mappings = [StaticSubmeshMapping(i, part.name, [0] if i == 0 else [], i)
                for i, part in enumerate(snapshot.mesh.submeshes)]
    output, report = build_static_mesh_replacement(snapshot.original_data, snapshot.mesh, mapped,
                                                  manual_replacement_options(mappings))
    assert not report.errors
    return parse_pac(output, snapshot.mesh.path)


def test_new_item_reader_keeps_bind_geometry_and_authored_weights_through_pac(editor, tmp_path):
    snapshot, mapped, reports = _prepare(editor, source_glb(tmp_path))
    assert mapped.submeshes[0].vertices == [(10, 0, 0), (12, 0, 0), (10, 2, 0)]
    assert reports[0].policy == "preserve"
    result = _write(snapshot, mapped).submeshes[0]
    assert dict(zip(result.bone_indices[0], result.bone_weights[0])) == pytest.approx({1: .25, 2: .75}, abs=1/255)
    assert reports[0].maximum_quantization_change < .01


def test_multi_set_import_requires_explicit_reduction_and_reports_actual_loss(editor, tmp_path):
    path = source_glb(tmp_path, seven_influences=True)
    with pytest.raises(ValueError, match="at most six"):
        _prepare(editor, path)
    snapshot, mapped, reports = _prepare(editor, path, (SkinningChoice(0, "reduce"),))
    assert reports[0].reduced_vertices == 3
    assert reports[0].maximum_removed_mass == pytest.approx(1/7)
    assert reports[0].removed_bones == ("bone6",)
    result = _write(snapshot, mapped).submeshes[0]
    assert all(len(row) == 6 for row in result.bone_indices)
    assert all(sum(row) == pytest.approx(1) for row in result.bone_weights)


def test_reduction_combines_duplicate_identities_and_uses_stable_ties():
    result = reduce_influences((0, 1, 0, 2, 3), (.1, .2, .1, .2, .4), 2, ("z", "a", "b", "c"))
    assert result[:2] == ((3, 1), pytest.approx((2/3, 1/3)))
    assert result[2] == pytest.approx(.4)
    with pytest.raises(ValueError, match="zero"):
        reduce_influences((0,), (0.,), 6, ("z",))


def test_writer_never_silently_trims_seven_positive_influences():
    record = bytearray(40)
    record[39] = 63
    with pytest.raises(ValueError, match="explicitly reduce"):
        pack_pac_skin_weights(record, range(7), [1/7]*7, context="authored import")


def test_invalid_authored_rows_do_not_trigger_donor_transfer(editor):
    service, sid, _order = editor
    target = service.capture_export_snapshot(sid).mesh.submeshes[0]
    candidate = replace(target, bone_indices=[(0,)] * len(target.vertices),
                        bone_weights=[(.4,)] * len(target.vertices), source_vertex_map=[],
                        source_vertex_map_authority="topology")
    with pytest.raises(ValueError, match="explicit reduction or transfer"):
        ensure_final_target_skin_weights(candidate, target, target_index=0, summary=[])


def _controller_import(studio, editor, tmp_path, monkeypatch):
    app, tab = studio
    service, sid, _ = editor
    captured = service.capture_export_snapshot(sid)
    def prepare(mesh, _snapshot, _path, *, choices=(), stop_event=None, transfer_transform=None,
                palette_extension_bones=()):
        return preflight_imported_skin(mesh, captured.original_data, captured.mesh.interchange_skeleton,
            captured.mesh.path, choices=choices, transfer_transform=transfer_transform,
            palette_extension_bones=palette_extension_bones, stop_event=stop_event)
    monkeypatch.setattr("cdmw.services.mesh_skinning_preflight.prepare_new_item_skin", prepare)
    assert tab.controller.start_model_import(source_glb(tmp_path))
    _finish(app, tab.controller)
    assert tab.controller.model_import is not None
    return app, tab, prepare


def test_new_item_worker_publishes_authored_bind_geometry_with_identity_placement(studio, editor, tmp_path, monkeypatch):
    app, tab, _prepare = _controller_import(studio, editor, tmp_path, monkeypatch)
    source = tab.controller.model_import
    assert source.bake.is_identity and tab.controller.model_placement.is_identity
    assert source.scene.mesh.submeshes[0].vertices == [(10, 0, 0), (12, 0, 0), (10, 2, 0)]
    assert source.raw_import_mesh.submeshes[0].interchange_skin
    assert not source.scene.mesh.submeshes[0].interchange_skin
    assert tab.model_panel.skinning_button.isEnabled()
    tab.model_panel.skinning_button.click()
    dialog = tab.model_panel._skinning_dialog
    from PySide6.QtWidgets import QTableWidget
    table = dialog.findChild(QTableWidget)
    assert table.cellWidget(0, 1).currentData() == ("preserve", 6)
    dialog.reject()
    app.processEvents()


@pytest.mark.parametrize("change", ["mesh", "placement", "source", "failure", "cancel", "variant"])
def test_skinning_worker_keeps_previous_result_when_failed_or_stale(studio, editor, tmp_path, monkeypatch, change):
    import threading
    from cdmw.ui.new_item.model_import import ModelPlacement
    from cdmw.services.new_item_planning import ModelFiles
    app, tab, prepare = _controller_import(studio, editor, tmp_path, monkeypatch)
    controller, source = tab.controller, tab.controller.model_import
    scene, reports = source.scene, source.skinning_reports
    built = ModelFiles(b"last accepted result")
    controller.set_imported_model(controller.template_primary_entry(), built, source.scene)
    release = threading.Event()
    def blocked(*args, **kwargs):
        assert release.wait(3)
        if change == "failure":
            raise ValueError("owned preflight failure")
        return prepare(*args, **kwargs)
    monkeypatch.setattr("cdmw.services.mesh_skinning_preflight.prepare_new_item_skin", blocked)
    try:
        assert controller.start_model_skinning((SkinningChoice(0),))
        assert tab.model_panel.operation_label.text() == "Checking imported skin weights…"
        assert not tab.model_panel.skinning_button.isEnabled()
        if change == "mesh":
            source.mesh_generation += 1
        elif change == "placement":
            controller.set_model_placement(ModelPlacement(offset=(1., 0., 0.)))
        elif change == "source":
            controller.model_import = None
        elif change == "cancel":
            assert controller.cancel_operation("model_skinning")
        elif change == "variant":
            other = next(identity for identity, _ in controller.variant_choices()
                         if identity != controller.current_variant_identity())
            controller.select_variant(other)
    finally:
        release.set()
    _finish(app, controller)
    assert source.scene is scene and source.skinning_reports == reports
    if change == "cancel":
        assert controller.model_result is built
    if change == "failure":
        assert controller.model_result is built
        monkeypatch.setattr("cdmw.services.mesh_skinning_preflight.prepare_new_item_skin", prepare)
        assert controller.start_model_skinning((SkinningChoice(0),))
        _finish(app, controller)
        assert source.mesh_generation == 1
        assert controller.model_result is None


def test_explicit_donor_restriction_keeps_close_surfaces_from_overriding_the_choice():
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.modding.skeleton_parser import Skeleton, Bone
    from tests.test_pac_cloth_guide_builder import guide_free_pac, PALETTE
    raw = bytearray(guide_free_pac(parts=2))
    target = parse_pac(bytes(raw))
    for offset in target.submeshes[1].source_vertex_offsets:
        record = bytearray(raw[offset:offset+40])
        pack_pac_skin_weights(record, (6,), (1.,), context="restricted surface")
        raw[offset:offset+40] = record
    source = ParsedMesh(format="obj", submeshes=[SubMesh(name="close layers", vertices=target.submeshes[0].vertices,
                                                        faces=target.submeshes[0].faces)])
    rig = Skeleton(bones=[Bone(index=i,name=f"bone{i}",name_hash=h) for i,h in enumerate(PALETTE)])
    mapped, reports = preflight_imported_skin(source, bytes(raw), rig, "target.pac",
        choices=(SkinningChoice(0, "transfer", donor_parts=(1,)),))
    assert mapped.submeshes[0].bone_indices == [(6,)] * 4
    assert "surface-distance" in reports[0].summary()
    assert not source.submeshes[0].bone_weights


def test_hidden_companion_retains_every_lod_and_never_changes_other_family_payloads():
    from types import SimpleNamespace
    from cdmw.services.new_item_skinning import hide_variant_geometry
    from cdmw.modding.pac_cloth import pac_cloth_lods
    from cdmw.modding.pac_palette_extension import palette_layout
    from tests.test_pac_cloth_guide_builder import guide_free_pac
    raw = guide_free_pac(parts=2)
    files = {"selected.pac":raw,"other.pac":guide_free_pac(parts=1)}
    before = dict(files)
    snapshot = SimpleNamespace(payload=files.__getitem__,has_entry=lambda path:path in files)
    result = hide_variant_geometry(snapshot,"selected.pac")
    assert palette_layout(result.pac_data)[3] == palette_layout(raw)[3]
    assert [[len(p.vertices) for p in lod.submeshes] for lod in pac_cloth_lods(result.pac_data)] == [[3,3]]*4
    assert files == before


def test_explicit_body_transfer_uses_verified_snapshot_and_reports_filtering():
    from cdmw.services.mesh_skinning_preflight import prepare_new_item_skin
    from tests.test_new_item_armour_import import _body_transfer_request
    snapshot, appearance, _result, scene, body_path = _body_transfer_request()
    mesh, reports = prepare_new_item_skin(scene.mesh, snapshot, appearance.model_path,
        choices=tuple(SkinningChoice(i, "body_transfer") for i in range(len(scene.mesh.submeshes))))
    assert all(part.bone_weights for part in mesh.submeshes)
    assert all(report.donor_path == body_path and report.target_path == appearance.model_path for report in reports)
    assert all("Donor filtering:" in report.summary() for report in reports)
    assert all(report.skeleton_sha256 and report.target_sha256 for report in reports)


def test_six_influences_require_explicit_skeletal_physics_policy(editor, tmp_path):
    from cdmw.models import ArchiveEntry
    from cdmw.ui.new_item.model_import import ModelImportSource, ModelPlacement, build_placed_import
    from cdmw.modding.scene_import_result_ops import SceneImportResult
    from pathlib import Path
    snapshot, mesh, reports = _prepare(editor, source_glb(tmp_path, seven_influences=True), (SkinningChoice(0, "reduce"),))
    source = ModelImportSource(Path("source.glb"), Path("source.glb"), SceneImportResult(mesh=mesh), None, None,
                               skinning_reports=reports, skinning_target=snapshot.mesh.path)
    entry = ArchiveEntry(snapshot.mesh.path, Path("0.pamt"), Path("0.paz"), 0, 0, 0, 0, 0)
    with pytest.raises(ValueError, match="Turn off Template cloth"):
        build_placed_import(entry, source, ModelPlacement(), keep_template_physics=True)


def test_hide_variant_button_changes_only_selected_slot_and_can_restore_template(studio, monkeypatch):
    from cdmw.domain.new_item.spec import ModelSource
    from cdmw.services.new_item_planning import ModelFiles
    app, tab = studio
    controller = tab.controller
    controller.select_variant(controller.primary_variant_identity())
    result = ModelFiles(b"owned hidden fixture",notes=("Hidden template geometry",))
    monkeypatch.setattr("cdmw.services.new_item_skinning.hide_variant_geometry",lambda *_a,**_k:result)
    tab.model_panel.hide_variant_button.click()
    _finish(app,controller)
    assert controller.model_result is result
    assert not controller.draft.keep_template_physics
    assert controller.variant_plan_inputs()[0][controller.current_variant_identity()] is result
    tab.model_panel.keep_model.setChecked(True)
    assert controller.draft.model_source is ModelSource.TEMPLATE


@pytest.mark.parametrize("change", ["cancel", "variant", "failure"])
def test_hide_worker_keeps_prior_output_on_cancel_switch_or_failure(studio, monkeypatch, change):
    import threading
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.services.new_item_planning import ModelFiles

    app, tab = studio
    controller = tab.controller
    controller.select_variant(controller.primary_variant_identity())
    identity = controller.current_variant_identity()
    previous = ModelFiles(b"last accepted variant")
    controller.set_imported_model(controller.template_primary_entry(), previous)
    release = threading.Event()

    def blocked(_snapshot, _path, *, stop_event=None):
        assert release.wait(3)
        raise_if_cancelled(stop_event)
        if change == "failure":
            raise ValueError("owned hide failure")
        return ModelFiles(b"stale hidden output")

    monkeypatch.setattr("cdmw.services.new_item_skinning.hide_variant_geometry", blocked)
    try:
        assert controller.start_hide_model_variant()
        assert tab.model_panel.operation_label.text() == "Hiding the selected variant…"
        if change == "cancel":
            assert controller.cancel_operation("model_hide")
        elif change == "variant":
            other = next(value for value, _ in controller.variant_choices() if value != identity)
            controller.select_variant(other)
    finally:
        release.set()
    _finish(app, controller)
    if change == "variant":
        controller.select_variant(identity)
    assert controller.model_result is previous


def test_skin_policy_does_not_restore_original_geometry_after_mesh_editor_edits(studio, editor, tmp_path, monkeypatch):
    _app, tab, _prepare = _controller_import(studio,editor,tmp_path,monkeypatch)
    source = tab.controller.model_import
    source.mesh_generation += 1
    tab.model_panel._show_model(None)
    tab.model_panel._busy_changed(False)
    assert not tab.model_panel.skinning_button.isEnabled()
    assert not tab.controller.start_model_skinning((SkinningChoice(0),))


@pytest.mark.parametrize("bake,placement", [
    (ModelPlacement(), ModelPlacement(offset=(3., 0., 0.))),
    (ModelPlacement(), ModelPlacement(offset=(4., 1., 0.), rotation=(0., 0., 180.))),
    (ModelPlacement(offset=(7., -2., 0.), rotation=(0., 0., 90.), scale=(2., 2., 2.)),
     ModelPlacement(offset=(-4., 2., 0.), rotation=(0., 0., -90.), scale=(.5, .5, .5))),
])
def test_weight_transfer_samples_the_displayed_fit_and_placement(studio, tmp_path, monkeypatch, bake, placement):
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.modding.pac_cloth import pac_cloth_lods
    from cdmw.modding.scene_import_result_ops import SceneImportResult
    from tests.test_pac_cloth_guide_builder import guide_free_pac
    from tests.test_pac_palette_extension import rig

    app, tab = studio
    controller = tab.controller
    controller.select_variant(controller.primary_variant_identity())
    raw = bytearray(guide_free_pac(parts=2))
    for level in pac_cloth_lods(bytes(raw)):
        for index, part in enumerate(level.submeshes):
            for offset in part.source_vertex_offsets:
                record = bytearray(raw[offset:offset + 40])
                pack_pac_skin_weights(record, (0 if index == 0 else 6,), (1.,), context="placed donor fixture")
                raw[offset:offset + 40] = record
    target = parse_pac(bytes(raw), "target.pac")
    original = target.submeshes[0]
    mesh = ParsedMesh(format="obj", submeshes=[SubMesh(name="garment", vertices=list(original.vertices),
                                                     faces=list(original.faces))])
    source = ModelImportSource(tmp_path / "source.obj", tmp_path / "source.obj", SceneImportResult(mesh=mesh),
                               None, None, raw_import_mesh=mesh, skinning_target="target.pac")
    source.set_bake(bake)
    controller.model_import = source
    controller.set_model_placement(placement)

    def prepare(mesh, _snapshot, _path, **kwargs):
        return preflight_imported_skin(mesh, bytes(raw), rig(), "target.pac", **kwargs)

    monkeypatch.setattr("cdmw.services.mesh_skinning_preflight.prepare_new_item_skin", prepare)
    assert controller.start_model_skinning((SkinningChoice(0, "transfer"),))
    _finish(app, controller)
    # All three placements put this surface exactly over donor 1 (x=3..4).
    assert source.scene.mesh.submeshes[0].bone_indices == [(6,)] * len(original.vertices)
    assert source.scene.mesh.submeshes[0].vertices == original.vertices
    assert source.bake == bake and controller.model_placement == placement


@pytest.mark.parametrize("operation", ["skin", "hide"])
@pytest.mark.parametrize("change", ["keep", "keep_then_import", "draft", "discard", "none"])
def test_newer_model_choices_win_over_pending_skin_or_hide(studio, editor, tmp_path, monkeypatch, operation, change):
    import threading
    from cdmw.domain.new_item.spec import ModelSource
    from cdmw.services.new_item_planning import ModelFiles

    app, tab, prepare = _controller_import(studio, editor, tmp_path, monkeypatch)
    controller, source = tab.controller, tab.controller.model_import
    # The shared fixture switches work to async after construction. Cleanup must
    # use the same production mode when hiding retires a leased source.
    controller._model_cleanup_lane._synchronous = False
    scene, reports = source.scene, source.skinning_reports
    previous = ModelFiles(b"previous applied fixture")
    controller.set_imported_model(controller.template_primary_entry(), previous, source.scene)
    release, entered = threading.Event(), threading.Event()
    hidden = ModelFiles(b"hidden fixture")
    stops = []

    def blocked(*args, **kwargs):
        stops.append(kwargs["stop_event"])
        entered.set()
        assert release.wait(3)
        # A completed task may race cancellation; publication must reject it too.
        if operation == "hide":
            return hidden
        kwargs["stop_event"] = threading.Event()
        return prepare(*args, **kwargs)

    target = ("cdmw.services.mesh_skinning_preflight.prepare_new_item_skin" if operation == "skin"
              else "cdmw.services.new_item_skinning.hide_variant_geometry")
    monkeypatch.setattr(target, blocked)
    try:
        started = (controller.start_model_skinning((SkinningChoice(0),)) if operation == "skin"
                   else controller.start_hide_model_variant())
        assert started and entered.wait(3)
        if change in {"keep", "keep_then_import"}:
            assert tab.model_panel.keep_model.isEnabled()
            tab.model_panel.keep_model.setChecked(True)
            if change == "keep_then_import":
                tab.model_panel.import_model.setChecked(True)
        elif change == "draft":
            controller.draft.keep_template_physics = True
            controller.invalidate_plan()
        elif change == "discard":
            controller.discard_model()
        if change in {"keep", "keep_then_import", "discard"}:
            assert stops[0].is_set()
    finally:
        release.set()
    _finish(app, controller)
    if change == "none":
        if operation == "skin":
            assert source.scene is not scene and controller.model_result is None
        else:
            assert controller.model_import is None and controller.model_result is hidden
    else:
        assert source.scene is scene and source.skinning_reports is reports
        assert controller.model_result is (None if change == "discard" else previous)
        assert controller.draft.model_source is (ModelSource.TEMPLATE if change in {"keep", "discard"} else ModelSource.IMPORTED)
        if change == "draft":
            assert controller.draft.keep_template_physics
