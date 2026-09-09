"""Transport work budgets and reusable loading without changing preview results."""
import os
import threading
from dataclasses import replace
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage

from tests.test_placement_studio_loading import studio, until
from tools.paa_motion.format import BoneTrack, MotionClip
from tools.placement_studio.background import _retained
from tools.placement_studio.corpus import Baseline, BaselineRecord
from tools.placement_studio.loading import MeshRequest, prepare_meshes


def clip():
    return MotionClip((2, 3), 0, '', 1., '', 1., 0, 1, 0,
                      (BoneTrack(1, translation=((0, (0., 0., 0.)), (30, (1., 0., 0.)))),))


def load_transport(studio, monkeypatch):
    frames = []
    studio._playback.load(clip(), 'synthetic')
    studio._playback_slider.setMaximum(30)
    studio._playback_slider.setEnabled(True)
    monkeypatch.setattr(studio, '_apply_playback_frame', lambda: frames.append(studio._playback.frame))
    return frames


def test_transport_targets_60_hz_and_paces_with_deferred_paint(studio, monkeypatch):
    frames = load_transport(studio, monkeypatch)
    studio._on_playback_toggle()
    assert studio._playback_timer.interval() <= 1000 / 60
    assert studio._playback_timer.timerType() == Qt.PreciseTimer
    studio._playback.advance(.016)
    assert studio._playback.frame == pytest.approx(.48)
    studio._playback_last_tick = 5.
    studio._playback_timer.stop()
    studio._playback_paint_pending = True
    monkeypatch.setattr('tools.placement_studio.window_playback.time.monotonic', lambda: 5.018)
    studio._pace(.006)
    assert not studio._playback_timer.isActive()  # No new pose before the last one paints.
    studio._viewport.frame_painted.emit(.012)
    assert studio._playback_timer.isActive() and studio._playback_timer.interval() == 1
    studio._playback_timer.stop()
    studio._viewport.frame_painted.emit(.012)  # Hover repaints cannot schedule a second tick.
    assert not studio._playback_timer.isActive()
    studio._playback_paint_pending = True
    monkeypatch.setattr('tools.placement_studio.window_playback.time.monotonic', lambda: 5.003)
    studio._pace(.001)
    studio._viewport.frame_painted.emit(.002)
    assert studio._playback_timer.interval() <= 1000 / 60
    assert frames == []


def test_scrub_coalesces_changes_and_release_publishes_exact_final_frame(studio, monkeypatch):
    frames = load_transport(studio, monkeypatch)
    slider = studio._playback_slider
    slider.setSliderDown(True)
    for value in range(1, 20):
        slider.setValue(value)
    assert studio._viewport._moving
    assert studio._scrub_timer.isActive()
    assert frames == []
    until(lambda: frames)
    assert frames == [19]
    slider.setValue(27)
    slider.setSliderDown(False)
    assert frames == [19, 27]
    assert not studio._scrub_timer.isActive()
    assert not studio._viewport._moving


def test_switching_to_paused_clip_stops_old_transport(studio, monkeypatch):
    frames = load_transport(studio, monkeypatch)
    session = SimpleNamespace(hierarchy=object())
    studio._session = session
    studio._on_playback_toggle()
    monkeypatch.setattr('tools.placement_studio.window_clips.coverage', lambda *_: 1.)
    entry = SimpleNamespace(name='cd_phm_other', rig='rig')
    studio._clip_prepared((session, entry, clip(), False), '')
    assert frames == [0]
    assert not studio._playback_timer.isActive()
    assert not studio._playback.playing and not studio._viewport._moving
    studio._on_playback_tick()  # A queued timeout cannot restart a paused scene.
    assert frames == [0]
    studio._session = None


def test_failed_clip_keeps_current_playback_and_bind_cancels_scrub(studio, monkeypatch):
    load_transport(studio, monkeypatch)
    studio._session = SimpleNamespace(hierarchy=object(), clear_pose=lambda: None)
    studio._on_playback_toggle()
    original = studio._playback.clip
    studio._clip_prepared(None, 'fixture decode failure')
    assert studio._playback.clip is original and studio._playback_timer.isActive()
    studio._on_playback_toggle()
    studio._playback_slider.setSliderDown(True)
    studio._playback_slider.setValue(15)
    monkeypatch.setattr(studio, '_refresh_scene', lambda: None)
    studio._on_playback_clear()
    assert not studio._scrub_timer.isActive() and not studio._viewport._moving
    assert not studio._playback.loaded
    studio._session = None


def test_paint_timing_is_recorded_and_reset_when_detail_mode_changes(studio):
    view = studio._viewport
    image = QImage(view.size(), QImage.Format_ARGB32_Premultiplied)
    view.render(image)
    assert view.last_paint_seconds > 0
    view.set_moving(True)
    assert view.last_paint_seconds == 0


def test_armour_change_reuses_unchanged_sources_and_rejects_rewritten_file(tmp_path, monkeypatch):
    from tools.placement_studio import skinning
    names = ('body.pac', 'head.pac', 'coat_a.pac', 'coat_b.pac')
    for name in names:
        (tmp_path / name).write_bytes(b'original')
    baseline = Baseline(tmp_path, {name: BaselineRecord(name, '', 8, '') for name in names})
    decoded = []
    monkeypatch.setattr(skinning, 'load_skinned', lambda data, path, rig: decoded.append(path) or object())
    first = MeshRequest(baseline, 'rig', SimpleNamespace(parsed=object()),
                        (('body.pac', None), ('head.pac', None)), (('coat_a.pac', None),), ('', None))
    a = prepare_meshes(first, lambda: False, lambda *_: None)
    second = replace(first, armour=(('coat_b.pac', None),), cached_parts=a.cached_parts)
    b = prepare_meshes(second, lambda: False, lambda *_: None)
    assert decoded == ['body.pac', 'head.pac', 'coat_a.pac', 'coat_b.pac']
    assert b.skinned[:2] == a.skinned[:2] and b.body_count == 2
    before = (tmp_path / 'body.pac').stat()
    (tmp_path / 'body.pac').write_bytes(b'modified')
    os.utime(tmp_path / 'body.pac', ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
    c = prepare_meshes(replace(second, cached_parts=b.cached_parts), lambda: False, lambda *_: None)
    assert decoded[-1] == 'body.pac' and len(decoded) == 5
    assert c.skinned[0] is not b.skinned[0] and c.skinned[1] is b.skinned[1]


def test_mesh_cache_is_bounded_by_count_and_bytes(studio):
    studio._remember_mesh_parts(tuple((str(i), ((), object(), None)) for i in range(40)))
    assert len(studio._mesh_part_cache) == 32
    oversized = SimpleNamespace(rest=SimpleNamespace(nbytes=65 * 1024 * 1024))
    studio._remember_mesh_parts((('large', ((), oversized, None)),))
    assert not studio._mesh_part_cache


def test_bulk_topology_preparation_preserves_piece_offsets_in_both_previews():
    from tests.test_placement_studio_skinning import _mesh
    from tests.test_placement_studio_prepared_move import setup
    from tools.placement_studio.prepared_move import prepare_move
    from tools.placement_studio.scene_preparation import build_scene
    from tools.placement_studio.window import PlacementStudioWindow
    meshes = tuple(_mesh([(0., 0., 0.)] * 3, [[0, 0, 0, 0]] * 3,
                         [[1., 0., 0., 0.]] * 3) for _ in range(2))
    state = SimpleNamespace(_skinned_faces=(), _skinned_body_count=1)
    PlacementStudioWindow._build_skinned_faces(state, meshes)
    session, edits, plan, read = setup()
    scene = build_scene(session, prepare_move(session, edits.capture(), plan, read=read), body=meshes)
    assert state._skinned_faces == scene.body_faces == ((0, 1, 2), (3, 4, 5))
    assert state._skinned_groups.tolist() == [0, 1]


def test_archive_piece_cache_checks_package_files_and_entry_location(tmp_path, monkeypatch):
    from tools.placement_studio import armour, skinning
    package, archive = tmp_path / 'index.pamt', tmp_path / 'data.paz'
    package.write_bytes(b'table')
    archive.write_bytes(b'mesh')
    entry = SimpleNamespace(pamt_path=package, paz_file=archive, offset=0, comp_size=4,
                            orig_size=4, flags=0, prepared_path=None, prepared_sha256=None)
    reads = []
    monkeypatch.setattr(armour, 'read_entry', lambda e: reads.append(e.offset) or b'mesh')
    monkeypatch.setattr(skinning, 'load_skinned', lambda *_: object())
    request = MeshRequest(Baseline(tmp_path, {}), 'rig', SimpleNamespace(parsed=object()),
                          (('body.pac', entry),), (), ('', None))
    first = prepare_meshes(request, lambda: False, lambda *_: None)
    request = replace(request, cached_parts=first.cached_parts)
    second = prepare_meshes(request, lambda: False, lambda *_: None)
    assert reads == [0] and second.skinned[0] is first.skinned[0]
    entry.offset = 1
    third = prepare_meshes(request, lambda: False, lambda *_: None)
    assert reads == [0, 1] and third.skinned[0] is not first.skinned[0]
    request = replace(request, cached_parts=third.cached_parts)
    archive.write_bytes(b'rewritten archive')
    fourth = prepare_meshes(request, lambda: False, lambda *_: None)
    assert len(reads) == 3 and fourth.skinned[0] is not third.skinned[0]


def test_comparison_waits_for_both_visible_paints_and_pause_rejects_late_paint():
    from tools.placement_studio.move_preview import MovePreview
    widget = MovePreview()
    try:
        widget._playing = True
        widget._last_tick = 0.
        widget._awaiting_paint = {0, 1}
        widget._frame_update_seconds = .004
        widget._views[0].frame_painted.emit(.005)
        assert not widget._timer.isActive()
        widget._views[1].frame_painted.emit(.005)
        assert widget._timer.isActive()
        widget.stop()
        widget._views[1].frame_painted.emit(.005)
        assert not widget._timer.isActive()
    finally:
        widget.close()


def test_mesh_cache_does_not_cross_rig_or_source_index(studio, monkeypatch):
    from tools.placement_studio import window_loading
    requests = []
    monkeypatch.setattr(window_loading, 'prepare_meshes',
                        lambda request, *_: requests.append(request))
    monkeypatch.setattr(studio, '_base_body_paths', lambda _: [])
    studio._session = SimpleNamespace(model='rig', weapon=None,
                                     hierarchy=SimpleNamespace(parsed=object()))
    studio._mesh_cache_context = (studio._session.hierarchy.parsed, None, studio._baseline)
    studio._mesh_part_cache['old'] = ((), object(), None)
    studio._armour_index = object()  # A refreshed archive index invalidates resident pieces.
    studio._ensure_meshes_prepared()
    until(lambda: requests)
    assert requests[0].cached_parts == ()
    until(lambda: not studio._mesh_task.busy)
    studio._mesh_part_cache['old'] = ((), object(), None)
    studio._session.hierarchy.parsed = object()
    studio._ensure_meshes_prepared()
    until(lambda: len(requests) == 2)
    assert requests[1].cached_parts == ()
    studio._session = None


def test_cached_rotation_keys_keep_replacement_and_fractional_sampling_independent():
    from tools.paa_motion.pose import sample_delta
    first = replace(clip(), tracks=(BoneTrack(1, rotation=(
        (0, (0., 0., 0., 1.)), (30, (0., 1., 0., 1.)))),))
    second = replace(first, tracks=(BoneTrack(1, rotation=(
        (0, (0., 0., 0., 1.)), (30, (0., 0., 1., 1.)))),))
    a = sample_delta(first, 1, 15).rotation
    b = sample_delta(second, 1, 15).rotation
    assert a == pytest.approx((0., .3826834323650898, 0., .9238795325112867))
    assert b == pytest.approx((0., 0., .3826834323650898, .9238795325112867))
    assert sample_delta(first, 1, 15).rotation == a


def test_comparison_scrub_coalesces_and_restores_full_detail(monkeypatch):
    from tests.test_placement_studio_prepared_move import setup
    from tools.placement_studio.prepared_move import prepare_move
    from tools.placement_studio.move_preview import MovePreview, build_scene
    session, edits, plan, read = setup()
    widget = MovePreview()
    widget.set_scene(build_scene(session, prepare_move(session, edits.capture(), plan, read=read)))
    frames = []
    render = widget.render
    monkeypatch.setattr(widget, 'render', lambda: (frames.append(widget.seconds), render()))
    try:
        assert widget._timer.interval() <= 1000 / 60
        widget.slider.setSliderDown(True)
        widget.slider.setValue(100)
        widget.slider.setValue(300)
        assert not frames and all(v._moving for v in widget._views)
        widget.slider.setSliderDown(False)
        assert frames == [.3] and all(not v._moving for v in widget._views)
        assert not widget._scrub_timer.isActive()
    finally:
        widget.close()


def test_clip_index_runs_off_ui_and_close_rejects_its_result(studio, monkeypatch, tmp_path):
    from tools.placement_studio import clips, corpus
    entered, release = threading.Event(), threading.Event()
    thread = threading.get_ident()
    published = []

    def scan(root, **kwargs):
        assert threading.get_ident() != thread
        entered.set()
        assert release.wait(3)
        yield 1, 1, clips.ClipIndex()

    monkeypatch.setattr(clips, 'scan_archives', scan)
    monkeypatch.setattr(corpus, 'game_root', lambda: tmp_path)
    monkeypatch.setattr(studio, '_populate_clip_rigs', lambda: published.append('published'))
    studio._ensure_clip_index()
    try:
        until(entered.is_set)
        assert not studio.clip_index_ready
        studio.close()
        release.set()
        until(lambda: not _retained)
        assert not published
    finally:
        release.set()


def test_clip_index_publishes_on_ui_and_runs_waiting_action(studio, monkeypatch, tmp_path):
    from tools.placement_studio import clips, corpus
    main = threading.get_ident()
    ran = []

    def scan(root, **kwargs):
        assert threading.get_ident() != main
        yield 1, 1, clips.ClipIndex()

    monkeypatch.setattr(clips, 'scan_archives', scan)
    monkeypatch.setattr(corpus, 'game_root', lambda: tmp_path)
    studio._when_clips_ready('review', lambda: ran.append(threading.get_ident()))
    until(lambda: ran)
    assert studio.clip_index_ready and ran == [main]


def test_compatibility_index_wait_returns_on_close_without_waiting_for_worker(studio, monkeypatch, tmp_path):
    from tools.placement_studio import clips, corpus
    entered, release = threading.Event(), threading.Event()

    def scan(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        yield 1, 1, clips.ClipIndex()

    monkeypatch.setattr(clips, 'scan_archives', scan)
    monkeypatch.setattr(corpus, 'game_root', lambda: tmp_path)
    studio._ensure_clip_index()
    try:
        until(entered.is_set)
        QTimer.singleShot(0, studio.close)
        studio._ensure_clip_index(wait=True)
        assert studio._clip_index_task.busy  # The close returned before its blocked read.
    finally:
        release.set()
        until(lambda: not _retained)
