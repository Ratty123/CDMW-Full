"""The complete review set, private comparison state and explicit equipment identity."""
import os
import sys
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from tools.placement_studio.carry import AnimationReplacement
from tools.placement_studio.clips import ClipEntry, companion_path
from tools.placement_studio.equipment_assets import EquipmentModel, model_variants
from tools.placement_studio.move_file_model import MoveFileModel
from tools.placement_studio.resolver import WeaponSocketFile

_app = QApplication.instance() or QApplication([])


def entry(path):
    return ClipEntry(path, '1_pc/1_phm', 'draw', path.endswith('_lod.paa'))


def test_every_row_is_accessible_and_manual_companion_choice_survives_refresh():
    root = 'character/motion/1_pc/1_phm/'
    a, b, c = (entry(root + name + '.paa') for name in ('target', 'donor_a', 'donor_b'))
    lod_a, lod_b, lod_c = (entry(companion_path(e.path)) for e in (a,b,c))
    rows = [AnimationReplacement(a,b,options=(b,c)), AnimationReplacement(lod_a,lod_b,options=(lod_b,lod_c))]
    rows += [AnimationReplacement(entry(root+f'target_{i}.paa'),b) for i in range(2000)]
    model = MoveFileModel(); model.set_rows(rows)
    assert model.rowCount() == 2002 and len(model.chosen()) == 2002
    assert model.data(model.index(2001,1)) == root+'target_1999.paa'
    assert model.setData(model.index(0,2),c.path)
    assert model.donor(rows[1]).path == lod_c.path
    assert model.setData(model.index(1,2),lod_b.path)
    model.setData(model.index(0,2),b.path)
    model.setData(model.index(0,2),c.path)
    model.setData(model.index(2001,0),Qt.Unchecked,Qt.CheckStateRole)
    model.set_rows(rows)
    assert model.donor(rows[0]) == c and model.donor(rows[1]) == lod_b
    assert len(model.chosen()) == 2001


def test_mesh_variants_keep_the_explicit_socket_template():
    sockets='character/descriptors/socketbonedata/1_pc/1_phm/weapon/3_shield/shield_0001.sockets.xml'
    weapon=WeaponSocketFile(sockets,'shield_0001','1_phm','shield',{})
    models=(EquipmentModel('character/model/1_pc/1_phm/weapon/3_shield/shield_0002.pac',sockets,'two.prefab'),
            EquipmentModel('character/model/1_pc/1_phm/weapon/3_shield/shield_0007.pac',sockets,'seven.prefab'))
    result=model_variants([weapon],models)
    assert [w.weapon_id for w in result] == ['shield_0002','shield_0007']
    assert all(w.game_path == sockets for w in result)
    assert [(w.mesh_path,w.prefab_path) for w in result] == [(m.mesh,m.prefab) for m in models]


def test_comparison_preserves_playhead_camera_loop_and_speed_without_editing():
    from test_placement_studio_prepared_move import setup
    from tools.placement_studio.prepared_move import prepare_move
    from tools.placement_studio.move_preview import MovePreview, build_scene
    session,edits,plan,read=setup(); original=edits.capture()
    prepared=prepare_move(session,original,plan,read=read)
    scene=build_scene(session,prepared)
    widget=MovePreview();widget.set_scene(scene)
    widget.seek(500);widget.speed.setValue(1.7);widget.loop.setChecked(False)
    camera=widget._views[0]._camera
    target=camera.target
    for mode in ('Before','Compare','After'):
        widget.view_mode.setCurrentText(mode)
        assert widget.seconds == .5 and widget.speed.value() == 1.7 and not widget.loop.isChecked()
        assert widget._views[0]._camera is widget._views[1]._camera is camera
        assert camera.target == target
    assert edits.capture() == original
    assert widget.clip_box.count() == len(plan.request.replacements)
    widget.close()


def test_chart_control_uses_decoded_times_and_manual_state_without_history_edits():
    from test_placement_studio_prepared_move import setup
    from tools.placement_studio.prepared_move import prepare_move
    from tools.placement_studio.move_preview import MovePreview, build_scene
    from tools.placement_studio.event_timeline import Timeline
    from tools.placement_studio.paac_events import SocketEvent
    from test_placement_studio_playback import _rig
    session, edits, plan, read = setup(); snapshot = edits.capture()
    session.hierarchy = _rig(); session._reposition()
    scene = build_scene(session, prepare_move(session, snapshot, plan, read=read))
    path = scene.preview_paths[0]
    timeline = Timeline((SocketEvent(.25, 0, plan.unit.primary_part, 1, '', '', 0., False),))
    scene.timelines = ({path:timeline}, {path:timeline})
    widget = MovePreview(); widget.set_scene(scene); widget.view_mode.setCurrentText('Compare')
    widget.seek(100)
    assert all('stowed' in view._attachments for view in widget._views)
    widget.seek(500)
    assert all('held' in view._attachments for view in widget._views)
    widget.chart_events.setChecked(False)
    assert all('stowed' in view._attachments for view in widget._views)
    widget.role.setCurrentText('Held'); widget.chart_events.setChecked(True); widget.seek(0)
    assert all('held' in view._attachments for view in widget._views)
    assert edits.capture() == snapshot
    widget.close()


def test_localized_preview_controls_preserve_raw_mode_and_attachment_state(tmp_path):
    from cdmw.ui.localization import UiLocalizer
    from test_placement_studio_motionblending import space
    from test_placement_studio_prepared_move import setup
    from test_placement_studio_playback import _rig
    from tools.placement_studio.prepared_move import prepare_move
    from tools.placement_studio.move_preview import MovePreview, build_scene
    session, edits, plan, read = setup()
    session.hierarchy = _rig(); session._reposition()
    snapshot = edits.capture()
    scene = build_scene(session, prepare_move(session,snapshot,plan,read=read))
    scene.blendspaces = (replace(space(), clips=(scene.preview_paths[0],)*3),)
    widget = MovePreview(); widget.set_scene(scene); widget.blend_box.setCurrentIndex(1)
    localizer = UiLocalizer(language_dir=tmp_path/'languages', language_code='de')
    try:
        localizer.activate_runtime_tracking(widget, application=_app)
        localizer.apply(widget)
        assert widget.chart_events.text() == 'Diagrammereignisse'
        assert widget.restart_blend.text() == 'Mischung neu starten'
        widget.view_mode.setCurrentIndex(widget.view_mode.findData('Compare'))
        widget.role.setCurrentIndex(widget.role.findData('Held')); widget.seek(0)
        assert widget.view_mode.currentText() != 'Compare' and widget.role.currentText() != 'Held'
        assert all(not widget.splitter.widget(i).isHidden() for i in range(2))
        assert all('held' in view._attachments for view in widget._views)
        localizer.load_language('fr'); localizer.apply_registered_roots(); widget.render()
        assert widget.view_mode.currentData() == 'Compare' and widget.role.currentData() == 'Held'
        assert widget.chart_events.text() == 'Événements du graphe'
        assert all('held' in view._attachments for view in widget._views)
        assert edits.capture() == snapshot
    finally:
        localizer.load_language('en'); localizer.apply_registered_roots()
        localizer.shutdown(); widget.close()


def test_comparison_blends_hold_shorter_endpoints_until_the_shared_clock_loops(monkeypatch):
    import pytest
    from test_placement_studio_prepared_move import setup
    from test_placement_studio_playback import _rig, _ROOT_HASH
    from test_placement_studio_motionblending import space
    from tools.paa_motion.format import MotionClip, BoneTrack
    from tools.placement_studio.prepared_move import prepare_move
    from tools.placement_studio import move_preview as module
    session, edits, plan, read = setup()
    session.hierarchy = _rig(); session._reposition()
    snapshot = edits.capture()
    scene = module.build_scene(session, prepare_move(session,snapshot,plan,read=read))
    path = scene.preview_paths[0]
    def clip(duration):
        return MotionClip((2,3),0,'',1,'',duration,0,1,0,(BoneTrack(_ROOT_HASH,
            translation=((0,(0.,0.,0.)),(round(duration*30),(duration,0.,0.)))),))
    scene.clips[path] = clip(1.)
    scene.after_clips[path] = clip(2.)
    scene.blendspaces = (replace(space(),clips=(path,)*3,phases=()),)
    widget = module.MovePreview(); widget.set_scene(scene)
    widget.view_mode.setCurrentIndex(widget.view_mode.findData('Compare'))
    widget.blend_box.setCurrentIndex(1); widget.loop.setChecked(True)
    widget.seek(1500)
    assert scene.before.pose_matrices[0][12] == pytest.approx(1.)
    assert scene.after.pose_matrices[0][12] == pytest.approx(1.5)
    widget.seek(2000)
    assert scene.before.pose_matrices[0][12] == pytest.approx(1.)
    assert scene.after.pose_matrices[0][12] == pytest.approx(2.)
    widget._last_tick = 10.
    monkeypatch.setattr(module.time,'monotonic',lambda:10.1)
    widget._tick()
    assert widget.seconds == pytest.approx(.1)
    assert all(s.pose_matrices[0][12] == pytest.approx(.1) for s in (scene.before,scene.after))
    assert edits.capture() == snapshot
    widget.close()


def test_placement_preview_includes_suffix_draws_without_defaulting_to_npc_story_clips():
    from test_placement_studio_prepared_move import setup, payload
    from tools.placement_studio.move_operation import plan_move
    from tools.placement_studio.prepared_move import prepare_move
    from tools.placement_studio.move_preview import build_scene
    from tools.placement_studio.relationships import Relationships, AnimationSet
    from tools.placement_studio.clips import ClipIndex
    session, edits, plan, read = setup()
    draw = plan.request.replacements[0].target_path.replace('character/animation/', 'character/motion/')
    guard = 'character/motion/1_pc/1_phm/guard.paa'
    story = guard.replace('guard.paa', '02_mission/guard.paa')
    npc = guard.replace('guard.paa', '00_mon/guard.paa')
    mapping = AnimationSet('set', ((guard,'missing.paa'),(story,'missing.paa'),(npc,'missing.paa')), '', '')
    graph = Relationships((guard, draw, story, npc), sets=(('set',mapping),), matches=(('*','set'),),
                          entries=((p, object()) for p in (guard, draw, story, npc)))
    placement = plan_move(session, edits, replace(plan.request, replacements=()))
    scene = build_scene(session, prepare_move(session, edits.capture(), placement), relationships=graph,
                        read_asset=lambda _:payload(0))
    assert draw in scene.preview_paths and guard in scene.preview_paths
    assert story not in scene.preview_paths and npc not in scene.preview_paths
    index = ClipIndex(entry(p) for p in (guard, story, npc))
    assert index.filter()[1] == 3  # Callable default remains compatible.
    assert index.filter(include_story=False)[1] == 1


def test_placement_preview_discovers_non_sword_handoffs_from_exact_part_events():
    from dataclasses import replace
    from test_placement_studio_prepared_move import setup, payload
    from tools.placement_studio.prepared_move import prepare_move
    from tools.placement_studio.move_operation import plan_move
    from tools.placement_studio.move_preview import build_scene
    from tools.placement_studio.relationships import Relationships
    from tools.placement_studio.paac_events import ActionEvents, ChartEvents, SocketEvent
    session, edits, plan, _ = setup()
    clip = 'character/motion/1_pc/1_phm/cd_phm_bow_weapon_in_00.paa'
    npc = clip.replace('/cd_phm_', '/00_mon/cd_phm_')
    event = SocketEvent(.2, 0, plan.unit.primary_part, 0, '', '', 0, False)
    chart = ChartEvents('test.paac', 'hash', tuple(ActionEvents(i,p,'',1.,(event,)) for i,p in enumerate((clip,npc))))
    graph = Relationships(paths=(clip,npc), entries=((p,object()) for p in (clip,npc)), charts=((chart.path,chart),))
    unit = replace(plan.unit, target_animation_families=())
    placement = plan_move(session, edits, replace(plan.request, unit=unit, replacements=()))
    scene = build_scene(session, prepare_move(session, edits.capture(), placement), relationships=graph,
                        read_asset=lambda _:payload(0))
    assert scene.preview_paths == (clip,)


def test_equipment_selector_resolves_without_changing_the_main_selection():
    from test_placement_studio_move_dialog import _Bench
    bench = _Bench()
    original = bench.session.weapon
    calls = []
    weapons = bench.session.weapons()
    def resolve(part, weapon):
        calls.append((part, weapon.weapon_id))
        return bench.session.resolve_equipment_unit(part, weapon=weapon), ''
    dialog = bench.dialog(unit_for=None, unit_for_weapon=resolve, weapons=weapons)
    dialog._asset_box.setCurrentIndex((dialog._asset_box.currentIndex() + 1) % len(weapons))
    assert calls and dialog._unit.weapon_id == calls[-1][1]
    assert bench.session.weapon is original
    assert dialog.prepared() is None and not dialog._accept.isEnabled()
    dialog.reject()


def test_stale_marker_survives_playback_and_a_new_preparation_cancels_freshness():
    from test_placement_studio_prepared_move import setup
    from test_placement_studio_move_dialog import _Bench
    from tools.placement_studio.prepared_move import prepare_move
    from tools.placement_studio.move_preview import build_scene
    session, edits, plan, read = setup()
    scene = build_scene(session, prepare_move(session, edits.capture(), plan, read=read))
    dialog = _Bench().dialog()
    dialog._preview.set_scene(scene)
    dialog._invalidate_preparation()
    message = dialog._preview.status.text()
    dialog._preview.seek(300)
    dialog._preview.render()
    assert dialog._preview.status.text() == message
    generation = dialog._freshness_task._generation
    dialog._prepare_selection()
    assert dialog._freshness_task._generation > generation
    dialog.reject()


def test_edit_rebuild_retains_archive_socket_templates_and_mesh_bindings():
    from test_placement_studio_prepared_move import setup
    from tools.placement_studio.window_editing import EditPanelMixin
    session, edits, plan, read = setup()
    socket_path = 'character/descriptors/socketbonedata/1_pc/1_phm/weapon/3_shield/new.sockets.xml'
    existing = session.weapon.game_path
    edits.add_base_files({socket_path: edits.current_files()[existing]})
    model = EquipmentModel('character/model/1_pc/1_phm/weapon/3_shield/new.pac', socket_path, 'new.prefab')
    session._equipment_models = (model,)
    session._equipment_model_errors = ('incomplete',)
    window = SimpleNamespace(_session=session, _edits=edits)
    EditPanelMixin._rebuild_session_from_edits(window)
    rebuilt = window._session
    assert any(w.game_path == socket_path and w.mesh_path == model.mesh for w in rebuilt.weapons())
    assert rebuilt.hierarchy is session.hierarchy and rebuilt.pose_matrices is session.pose_matrices
    assert rebuilt._bind_hierarchy is session._bind_hierarchy
    assert rebuilt.skeleton_path == session.skeleton_path
    assert rebuilt._equipment_model_errors == ('incomplete',)


def test_localized_review_keeps_raw_selection_and_translates_model_checks(tmp_path):
    from PySide6.QtWidgets import QWidget, QTableView
    from PySide6.QtCore import QSortFilterProxyModel
    from cdmw.ui.localization import UiLocalizer
    from cdmw.services.active_ui_translation import ACTIVE_UI_LOCALIZER_PROPERTY
    from test_placement_studio_prepared_move import setup, payload
    from tools.placement_studio.prepared_move import prepare_move
    session, edits, plan, _read = setup()
    prepared = prepare_move(session, edits.capture(), plan, read=lambda _:payload(0))
    root = QWidget(); table = QTableView(root); model = MoveFileModel(table)
    model.set_rows(plan.request.replacements); model.set_prepared(prepared)
    proxy = QSortFilterProxyModel(table); proxy.setSourceModel(model); table.setModel(proxy)
    chosen = model.chosen()
    localizer = UiLocalizer(language_dir=tmp_path/'languages', language_code='de')
    previous_owner = _app.property(ACTIVE_UI_LOCALIZER_PROPERTY)
    _app.setProperty(ACTIVE_UI_LOCALIZER_PROPERTY,localizer)
    try:
        localizer.activate_runtime_tracking(root, application=_app)
        localizer.apply(root)
        from tools.placement_studio.carry import SCOPE_LABELS
        assert all(localizer.translate_rendered(label) != label for label in SCOPE_LABELS.values())
        assert model.headerData(1,Qt.Horizontal) == 'Zieldatei'
        assert proxy.headerData(1,Qt.Horizontal) == 'Zieldatei'
        assert model.data(model.index(0,6)) == 'Bestanden · unverändert'
        assert proxy.data(proxy.index(0,6)) == 'Bestanden · unverändert'
        assert proxy.data(proxy.index(0,2),Qt.EditRole) == chosen[0].donor.path
        assert model.chosen() == chosen
        localizer.load_language('fr'); localizer.apply_registered_roots()
        assert model.headerData(1,Qt.Horizontal) == 'Fichier cible'
        assert model.data(model.index(0,6)) == 'Réussi · inchangé'
        assert model.chosen() == chosen
    finally:
        _app.setProperty(ACTIVE_UI_LOCALIZER_PROPERTY,previous_owner)
        localizer.load_language('en'); localizer.apply_registered_roots()
        localizer.shutdown(); root.close()
