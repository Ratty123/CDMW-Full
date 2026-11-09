"""Cloth paint on an imported model reaches the built PAC as template-guide bindings."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.modding.mesh_deformer import copy_extra_submesh_attrs
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.pac_cloth import decode_pac_cloth_binding, pac_cloth_lods
from cdmw.modding.scene_geometry_utils import _copy_submesh_with_transform
from cdmw.services.new_item_cloth_paint import (
    apply_import_cloth_paint, import_cloth_paint_samples, mesh_has_cloth_paint, part_cloth_paint,
)
from tests.test_pac_cloth_paint import cloth_template

IDENTITY = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)


def imported(vertices, paint):
    part = SubMesh(name="dress", material="cloth", vertices=list(vertices),
                   faces=[(0, 1, 2), (1, 3, 2)][:max(1, len(vertices) - 2)])
    part.cloth_paint = list(paint)
    return ParsedMesh(format="obj", submeshes=[part])


def test_paint_is_read_only_when_it_fits_the_vertices():
    mesh = imported(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), (0., 1., 2.))
    assert part_cloth_paint(mesh.submeshes[0]) == [0., 1., 1.]
    mesh.submeshes[0].cloth_paint = [1.]
    assert part_cloth_paint(mesh.submeshes[0]) == [] and not mesh_has_cloth_paint(mesh)


def test_samples_follow_the_placement_matrix_and_unpainted_parts_count_as_bones():
    mesh = imported(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), (1., 1., 1.))
    other = SubMesh(name="belt", vertices=[(5., 5., 5.)], faces=[])
    mesh.submeshes.append(other)
    moved = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 10., 0., 0., 1.)
    samples = import_cloth_paint_samples(mesh, moved)
    assert samples.positions[1] == (11., 0., 0.) and samples.positions[-1] == (15., 5., 5.)
    assert samples.values == (1., 1., 1., 0.)


def test_paint_survives_copies_and_transforms():
    mesh = imported(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), (0., .5, 1.))
    target = SubMesh(name="copy")
    copy_extra_submesh_attrs(mesh.submeshes[0], target)
    assert target.cloth_paint == [0., .5, 1.]
    moved = _copy_submesh_with_transform(mesh.submeshes[0], IDENTITY)
    assert moved.cloth_paint == [0., .5, 1.]


def test_service_rewrites_the_built_pac_and_reports_it():
    data = cloth_template()
    dress = pac_cloth_lods(data)[0].submeshes[1]
    result = SimpleNamespace(rebuilt_data=data, summary_lines=[])
    assert apply_import_cloth_paint(result, imported(dress.vertices, [1.] * len(dress.vertices)), IDENTITY)
    for offset in dress.source_vertex_offsets:
        assert decode_pac_cloth_binding(result.rebuilt_data, offset)[0] == 0
    assert "Cloth paint:" in result.summary_lines[-1] and "test in game" in result.summary_lines[-1]
    untouched = SimpleNamespace(rebuilt_data=data, summary_lines=[])
    assert not apply_import_cloth_paint(untouched, imported(dress.vertices, [0.] * len(dress.vertices)), IDENTITY)
    assert untouched.rebuilt_data == data and not untouched.summary_lines


def test_misplaced_paint_is_refused_instead_of_painting_the_wrong_vertices():
    data = cloth_template()
    dress = pac_cloth_lods(data)[0].submeshes[1]
    result = SimpleNamespace(rebuilt_data=data, summary_lines=[])
    far = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 50., 0., 0., 1.)
    with pytest.raises(ValueError, match="does not line up with"):
        apply_import_cloth_paint(result, imported(dress.vertices, [1.] * len(dress.vertices)), far)
    assert result.rebuilt_data == data


def test_real_static_build_with_the_new_item_placement_lines_up_with_the_hook_matrix():
    # The New Item hook places samples with ModelPlacement.matrix(); the builder places
    # geometry with ModelPlacement.build_transform(). Run the real geometry build.
    from cdmw.modding.mesh_parser import parse_pac
    from cdmw.modding.static_mesh_build import build_static_mesh_replacement
    from cdmw.modding.static_mesh_types import StaticMeshReplacementOptions, StaticSubmeshMapping
    from cdmw.ui.new_item.model_import import ModelPlacement

    raw = cloth_template()
    original = parse_pac(raw, "cloth.pac")
    template = pac_cloth_lods(raw)[0].submeshes[1]
    origin = (0., 0., 0.)
    placement = ModelPlacement(offset=(.25, 0., .5), rotation=(0., 0., 90.))
    inverse = _inverse_rows(placement.matrix(origin=origin))
    vertices = [_row(point, inverse) for point in template.vertices]
    mesh = imported(vertices, [1.] * len(vertices))
    mesh.submeshes[0].uvs = [(0., 0.)] * len(vertices)
    options = StaticMeshReplacementOptions(
        complete_external_swap=True,
        transform=placement.build_transform(origin=origin),
        submesh_mappings=[StaticSubmeshMapping(index, part.name, [0] if index == 1 else [], index)
                          for index, part in enumerate(original.submeshes)],
    )
    output, report = build_static_mesh_replacement(raw, original, mesh, options)
    assert not report.errors
    result = SimpleNamespace(rebuilt_data=output, summary_lines=[])
    assert apply_import_cloth_paint(result, mesh, placement.matrix(origin=origin))
    bound = [decode_pac_cloth_binding(result.rebuilt_data, offset)
             for level in pac_cloth_lods(result.rebuilt_data) for offset in level.submeshes[1].source_vertex_offsets]
    assert bound and all(binding is not None and binding[0] == 0 for binding in bound)


def _row(point, m):
    x, y, z = point
    return (x * m[0] + y * m[4] + z * m[8] + m[12], x * m[1] + y * m[5] + z * m[9] + m[13],
            x * m[2] + y * m[6] + z * m[10] + m[14])


def _inverse_rows(m):
    import numpy as np
    return tuple(float(v) for v in np.linalg.inv(np.asarray(m, dtype=float).reshape(4, 4)).reshape(16))


def test_mesh_editor_sets_cloth_paint_on_the_selection_with_undo_and_redo():
    from cdmw.domain.mesh.editing import MeshEditSelection
    from cdmw.services.mesh_service import MeshService

    service = MeshService()
    mesh = imported(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (1., 1., 0.)), ())
    sid = service.open_edit_session(mesh).session_id
    try:
        session = service._session(sid)
        session.selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 3)})
        assert service.set_selected_vertex_cloth_paint(sid, .75) == 2
        assert session.working_mesh.submeshes[0].cloth_paint == [0., .75, 0., .75]
        assert service.set_selected_vertex_cloth_paint(sid, .75) == 0  # no-op leaves history alone
        service.undo(sid)
        assert part_cloth_paint(service._session(sid).working_mesh.submeshes[0]) in ([], [0.] * 4)
        service.redo(sid)
        assert service._session(sid).working_mesh.submeshes[0].cloth_paint == [0., .75, 0., .75]
        with pytest.raises(ValueError, match="between 0 and 1"):
            service.set_selected_vertex_cloth_paint(sid, 2)
    finally:
        service.close_edit_session(sid)


def _authoring_for(mesh):
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
    from cdmw.services.mesh_service import MeshService

    service = MeshService()
    sid = service.open_edit_session(mesh).session_id
    authoring = SimpleNamespace(shadow_service=service, shadow_session_id=sid)
    authoring._apply_explicit_rig_selection = lambda args, **kwargs: (
        RustMeshAuthoringSession._apply_explicit_rig_selection(authoring, args, **kwargs))
    return authoring


def _selection(vertices):
    return {"vertices_by_submesh": {"0": list(vertices)}, "edges_by_submesh": {},
            "faces_by_submesh": {}, "source_indices": []}


def test_editor_command_paints_the_sent_selection_and_publishes_painted_rows():
    from cdmw.services.mesh_rust_authoring import RustMeshValidationError
    from cdmw.services.mesh_rust_cloth_paint import cloth_paint_state, run_cloth_paint_command
    from cdmw.services.mesh_rust_state_cache import RustMeshStateCache

    authoring = _authoring_for(imported(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (1., 1., 0.)), ()))
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    try:
        session = service._session(sid)
        cache = RustMeshStateCache()
        empty = cloth_paint_state(session, cache)
        assert empty["supported"] and empty["painted_vertex_count"] == 0
        assert run_cloth_paint_command(authoring, {"selection": _selection((0, 2)), "value": .6}) == {
            "changed_vertex_count": 2}
        state = cloth_paint_state(session, cache)
        assert state["painted_vertex_count"] == 2
        assert state["parts"] == [{"submesh_index": 0, "values": [[0, .6], [2, .6]]}]
        assert cloth_paint_state(session, cache) is state  # cached until the next edit
        with pytest.raises(RustMeshValidationError, match="Select one or more vertices"):
            run_cloth_paint_command(authoring, {"selection": _selection(()), "value": 1})
        with pytest.raises(RustMeshValidationError, match="between 0 and 1"):
            run_cloth_paint_command(authoring, {"selection": _selection((1,)), "value": -1})
    finally:
        service.close_edit_session(sid)


def test_game_models_do_not_offer_cloth_paint():
    from cdmw.services.mesh_rust_cloth_paint import cloth_paint_state
    state = cloth_paint_state(SimpleNamespace(mesh_format="pac"))
    assert not state["supported"] and "Create New Item" in state["reason"]


def test_paint_survives_the_editor_clone_that_publishes_to_create_new_item():
    from cdmw.services.mesh_workflow_service import clone_mesh_for_editing
    authoring = _authoring_for(imported(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), ()))
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    try:
        from cdmw.services.mesh_rust_cloth_paint import run_cloth_paint_command
        run_cloth_paint_command(authoring, {"selection": _selection((1,)), "value": 1})
        published = service.working_mesh(sid, clone=True)
        assert published.submeshes[0].cloth_paint == [0., 1., 0.]
        assert clone_mesh_for_editing(published).submeshes[0].cloth_paint == [0., 1., 0.]
    finally:
        service.close_edit_session(sid)


def test_whole_parts_from_the_parts_list_paint_every_vertex():
    from cdmw.services.mesh_rust_cloth_paint import run_cloth_paint_command
    authoring = _authoring_for(imported(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), ()))
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    try:
        parts = {"vertices_by_submesh": {}, "edges_by_submesh": {}, "faces_by_submesh": {}, "source_indices": [0]}
        assert run_cloth_paint_command(authoring, {"selection": parts, "value": .5}) == {"changed_vertex_count": 3}
        assert service._session(sid).working_mesh.submeshes[0].cloth_paint == [.5, .5, .5]
    finally:
        service.close_edit_session(sid)


def test_paint_whole_model_covers_every_part_and_clears_everywhere():
    from cdmw.services.mesh_rust_authoring import RustMeshValidationError
    from cdmw.services.mesh_rust_cloth_paint import run_cloth_paint_command
    authoring = _authoring_for(imported(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), ()))
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    empty = {"vertices_by_submesh": {}, "edges_by_submesh": {}, "faces_by_submesh": {}, "source_indices": []}
    try:
        assert run_cloth_paint_command(authoring, {"selection": empty, "value": .75, "whole_model": True}) == {
            "changed_vertex_count": 3}
        assert service._session(sid).working_mesh.submeshes[0].cloth_paint == [.75, .75, .75]
        run_cloth_paint_command(authoring, {"selection": empty, "value": 0., "whole_model": True})
        assert service._session(sid).working_mesh.submeshes[0].cloth_paint == [0., 0., 0.]
        with pytest.raises(RustMeshValidationError, match="whole_model"):
            run_cloth_paint_command(authoring, {"selection": empty, "value": 1., "whole_model": "yes"})
    finally:
        service.close_edit_session(sid)


def _placed_with_influences(tmp_path, monkeypatch, paint, *, own_guides=False, stop_event=None):
    from cdmw.models import ArchiveEntry
    from cdmw.modding.scene_import_result_ops import SceneImportResult
    from cdmw.ui.new_item.model_import import ModelImportSource, ModelPlacement, build_placed_import

    data = cloth_template()
    template = pac_cloth_lods(data)[0].submeshes[1]
    mesh = imported(template.vertices, [paint] * len(template.vertices))
    part = mesh.submeshes[0]
    part.bone_indices = [(0, 1, 2, 3, 4)] * len(part.vertices)  # five bones, as a template transfer gives
    part.bone_weights = [(.2,) * 5] * len(part.vertices)
    monkeypatch.setattr("cdmw.services.preview_workflow_service.build_mesh_import_preview",
                        lambda *_a, **_k: SimpleNamespace(rebuilt_data=data, summary_lines=[], palette_extension=None,
                                                          skeleton_edit=None, cloth_paint_report=None))
    source = ModelImportSource(tmp_path / "s.obj", tmp_path / "s.obj", SceneImportResult(mesh=mesh), None, None)
    entry = ArchiveEntry("character/model/test/target.pac", Path("0.pamt"), Path("0.paz"), 0, 0, 0, 0, 0)
    source.own_cloth_guides = own_guides
    return build_placed_import(entry, source, ModelPlacement(), keep_template_physics=True,
                               stop_event=stop_event)


def test_apply_placement_builds_own_cloth_guides_and_honours_cancel(tmp_path, monkeypatch):
    """The own-guides route runs inside Apply placement with the worker's stop event."""
    import threading

    from cdmw.domain.cancellation import RunCancelled

    calls = []

    def build_guides(_result, _mesh, _matrix, *, profile="", check_cancelled=lambda: None):
        # Large painted areas are reduced, and the reduction polls this between collapses.
        check_cancelled()
        calls.append(profile)
        return True

    monkeypatch.setattr("cdmw.services.new_item_cloth_guides.apply_import_cloth_guides", build_guides)
    _placed_with_influences(tmp_path, monkeypatch, 1., own_guides=True, stop_event=threading.Event())
    assert calls == [""]
    stopped = threading.Event()
    stopped.set()
    with pytest.raises(RunCancelled):
        _placed_with_influences(tmp_path, monkeypatch, 1., own_guides=True, stop_event=stopped)


def test_painted_builds_skip_the_four_bone_gate_and_unpainted_builds_keep_it(tmp_path, monkeypatch):
    result = _placed_with_influences(tmp_path, monkeypatch, 1.)
    assert result.cloth_paint_report is not None and result.cloth_paint_report.cloth_vertices
    with pytest.raises(ValueError, match="Turn off Template cloth / physics"):
        _placed_with_influences(tmp_path, monkeypatch, 0.)


def test_planning_knows_a_model_was_cloth_painted():
    from cdmw.services.new_item_planning import model_files_from_import
    family = SimpleNamespace(files_for=lambda _role: ())
    painted = SimpleNamespace(rebuilt_data=b"PAR ", supplemental_file_specs=(),
                              summary_lines=["Cloth paint: 4 vertices follow the template's 4 cloth guides."],
                              cloth_paint_report=object())
    files = model_files_from_import(painted, family=family)
    assert files.cloth_painted and files.notes == ("Cloth paint: 4 vertices follow the template's 4 cloth guides.",)
    assert not model_files_from_import(SimpleNamespace(rebuilt_data=b"PAR "), family=family).cloth_painted


def test_create_new_item_editing_sessions_open_with_the_tools_unlocked():
    from cdmw.workers.new_item_mesh_session import prepare_new_item_mesh_session
    prepared = prepare_new_item_mesh_session(
        imported(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), ()), "new-item-model:test", None)
    try:
        assert prepared.view.authoring_enabled
        assert prepared.view.output_policy == "free_edit_rebuild"
        assert prepared.service._session(prepared.view.session_id).handoff_target == "new_item"
        destination = Path(prepared.view.output_destination)
        assert destination.parent.name == "cdmw-new-item-edits" and not destination.exists()
    finally:
        prepared.cleanup()


def test_accepted_page_offers_the_way_back_only_for_the_linked_mesh():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.mesh_editor.rust_host import RustMeshEditorHostFrame

    app = QApplication.instance() or QApplication([])
    frame = RustMeshEditorHostFrame()
    try:
        button = frame._return_button
        assert button.isHidden()
        calls, linked = [], [True]
        saving = frame._result_groups["Save and reuse"]
        frame.set_return_action(lambda: calls.append("back"), lambda: linked[0])
        frame.show_result("")
        # Finish and return goes back by itself once the accepted page is up.
        assert calls == []
        app.processEvents()
        assert calls == ["back"]
        assert not button.isHidden() and button.text() == "Return to Create New Item"
        assert saving.isHidden() and frame._result_groups["Check or install"].isHidden()
        assert not frame._result_groups["Keep editing"].isHidden()
        button.click()
        assert calls == ["back", "back"]
        linked[0] = False  # the New Item mesh was closed; another mesh finished later
        frame.show_result("")
        app.processEvents()
        assert calls == ["back", "back"]
        assert button.isHidden() and not saving.isHidden()
        frame.set_return_action(None)
        assert button.isHidden()
    finally:
        frame.deleteLater()
        app.processEvents()


def test_return_shows_create_new_item_then_uses_the_changes():
    from cdmw.ui.new_item.tab import NewItemStudioTab
    events = []
    container = object()
    shell = SimpleNamespace(new_item_studio_tab=container,
                            _activate_tool_widget=lambda widget: events.append(("show", widget is container)))
    fake = SimpleNamespace(_window=SimpleNamespace(shell=shell),
                           _use_model_part_editor_changes=lambda: events.append(("use", True)))
    NewItemStudioTab._return_from_model_part_editor(fake)
    assert events == [("show", True), ("use", True)]


def _finished_tab(*, painted, keep_physics, reapply, busy=False):
    from cdmw.ui.new_item.tab import NewItemStudioTab
    mesh = imported(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), (1., 1., 1.) if painted else ())
    source = SimpleNamespace(scene=SimpleNamespace(mesh=mesh))
    notes, applied = [], []
    fake = SimpleNamespace(
        _model_part_editor_source=source, _reapply_after_model_part_edit=reapply,
        model_panel=SimpleNamespace(keep_physics=SimpleNamespace(isChecked=lambda: keep_physics),
                                    set_part_editor_state=lambda active, message="": notes.append(message)),
        controller=SimpleNamespace(busy=busy, start_model_apply=lambda: applied.append(True)))
    NewItemStudioTab._model_part_edit_finished(fake, source)
    return notes[-1], applied, fake


def test_returning_edit_applies_the_placement_again_only_if_it_was_applied():
    message, applied, fake = _finished_tab(painted=False, keep_physics=False, reapply=True)
    assert applied == [True] and "Applying the placement again" in message
    assert fake._reapply_after_model_part_edit is False
    message, applied, _ = _finished_tab(painted=False, keep_physics=False, reapply=False)
    assert applied == [] and "Apply placement to build it" in message
    assert "cloth paint" not in message


def test_returning_painted_edit_asks_for_template_cloth_when_it_is_off():
    message, _applied, _ = _finished_tab(painted=True, keep_physics=False, reapply=False)
    assert "turn on Template cloth / physics" in message
    message, _applied, _ = _finished_tab(painted=True, keep_physics=True, reapply=False)
    assert "Template cloth" not in message


def test_material_routing_keeps_the_cloth_painted_flag():
    # Plan rebuilt the files for the material route and lost the flag, so Build plan
    # still refused a painted six-bone model with Template cloth / physics on.
    from cdmw.services.new_item_materials import route_model_files
    from cdmw.services.new_item_planning import ModelFiles
    from cdmw.domain.new_item.spec import MaterialRoute
    painted = ModelFiles(pac_data=b"PAR ", cloth_painted=True)
    assert route_model_files(painted, MaterialRoute.BUILDER).cloth_painted
    assert not route_model_files(ModelFiles(pac_data=b"PAR "), MaterialRoute.BUILDER).cloth_painted
