"""UI heartbeats, immutable inputs, and stale/closed Studio preparation results."""
import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication, QLineEdit

from tools.placement_studio.background import _retained
from tools.placement_studio.corpus import Baseline

_app = QApplication.instance() or QApplication([])


def until(predicate):
    end = time.monotonic() + 4
    while not predicate() and time.monotonic() < end:
        loop = QEventLoop()
        QTimer.singleShot(5, loop.quit)
        loop.exec()
    assert predicate(), 'Timed out waiting for Qt delivery'


def test_bootstrap_reads_the_current_archive_workspace_path(tmp_path):
    from tools.placement_studio.tab import PlacementStudioTab
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.IniFormat)
    settings.setValue('archive/package_root', 'saved-installation')
    edit = QLineEdit('current-installation')
    owner = SimpleNamespace(
        _settings=settings,
        _window=SimpleNamespace(archive=SimpleNamespace(archive_package_root_edit=edit)),
    )
    assert PlacementStudioTab._game_root(owner) == 'current-installation'
    edit.setText('changed-installation')
    assert PlacementStudioTab._game_root(owner) == 'changed-installation'


def test_bootstrap_reads_the_canonical_saved_archive_path(tmp_path):
    from tools.placement_studio.tab import PlacementStudioTab
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.IniFormat)
    settings.setValue('archive/package_root', 'configured-installation')
    settings.setValue('archive_package_root', 'stale-legacy-installation')
    owner = SimpleNamespace(_settings=settings, _window=None)
    assert PlacementStudioTab._game_root(owner) == 'configured-installation'


def test_cached_baseline_preparation_does_not_import_qt_window_modules(monkeypatch, tmp_path):
    import builtins
    from tools.placement_studio import tab as module
    baseline = Baseline(tmp_path, {'present': object()})
    monkeypatch.setattr(Baseline, 'load', lambda: baseline)
    original_import = builtins.__import__

    def checked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'window' and level == 1 and (globals or {}).get('__package__') == 'tools.placement_studio':
            raise AssertionError('Baseline workers must not import Qt window classes')
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, '__import__', checked_import)
    assert module._prepare_startup('', lambda: False, lambda *_: None) is baseline


def test_bootstrap_retry_uses_the_current_live_archive_path(monkeypatch, tmp_path):
    from tools.placement_studio import tab as module
    main = threading.get_ident()
    prepared, installed = [], []
    baseline = Baseline(tmp_path, {'present': object()})
    edit = QLineEdit('first-installation')
    shell = SimpleNamespace(archive=SimpleNamespace(archive_package_root_edit=edit))

    def prepare(root, cancelled, progress):
        assert threading.get_ident() != main
        prepared.append(root)
        if root == 'first-installation':
            raise ValueError('Fixture preparation failure')
        return baseline

    def install(owner, value):
        assert threading.get_ident() == main
        installed.append(value)

    monkeypatch.setattr(module, '_prepare_startup', prepare)
    monkeypatch.setattr(module.PlacementStudioTab, '_install', install)
    owner = module.PlacementStudioTab(window=shell)
    try:
        until(lambda: prepared and not owner._startup_task.busy)
        assert owner._action.text() == 'Try again'
        assert owner._action.isEnabled()
        edit.setText('second-installation')
        owner._action.click()
        until(lambda: installed and not owner._startup_task.busy)
        assert prepared == ['first-installation', 'second-installation']
        assert installed == [baseline]
    finally:
        owner.shutdown()
        until(lambda: not _retained)
        owner.close()
        owner.deleteLater()


@pytest.fixture
def studio(monkeypatch, tmp_path):
    from tools.placement_studio.window import PlacementStudioWindow
    monkeypatch.setattr(PlacementStudioWindow, '_start_armour_index', lambda self: None)
    monkeypatch.setattr(PlacementStudioWindow, '_start_archive_content_load', lambda *a, **k: None)
    monkeypatch.setattr(PlacementStudioWindow, '_load_models', lambda self: None)
    window = PlacementStudioWindow(Baseline(tmp_path, {}), background_loading=True)
    yield window
    window.close()
    until(lambda: not _retained)
    window.deleteLater()


def test_cached_bootstrap_reads_off_ui_and_close_rejects_late_result(monkeypatch, tmp_path):
    from tools.placement_studio import tab as module
    started, release = threading.Event(), threading.Event()
    main = threading.get_ident()
    published, beats = [], []

    def load(*_):
        assert threading.get_ident() != main
        started.set()
        assert release.wait(3)
        return Baseline(tmp_path, {'present': object()})

    monkeypatch.setattr(Baseline, 'load', load)
    monkeypatch.setattr(module.PlacementStudioTab, '_install', lambda self, value: published.append(value))
    owner = module.PlacementStudioTab()
    try:
        until(started.is_set)
        QTimer.singleShot(0, lambda: beats.append(True))
        until(lambda: beats)
        threads = owner.iter_shutdown_workers()
        assert any(name == 'baseline_preparation' for name, *_ in threads)
        before = time.monotonic()
        owner.shutdown()
        assert time.monotonic() - before < .1
    finally:
        release.set()
        until(lambda: not _retained)
        owner.close()
    assert published == []


def test_model_loading_is_bounded_and_publishes_only_latest_on_ui(studio, monkeypatch):
    from tools.placement_studio.session import PlacementSession
    from tools.placement_studio.editing import EditSession
    started, release = threading.Event(), threading.Event()
    main, ran, published = threading.get_ident(), [], []
    studio._edits = EditSession({})

    def load(_baseline, model):
        assert threading.get_ident() != main
        ran.append(model)
        if model == 'old':
            started.set()
            assert release.wait(3)
        from tools.placement_studio.resolver import PlacementResolver
        return PlacementSession(model, None, PlacementResolver())

    monkeypatch.setattr(PlacementSession, 'from_baseline', load)
    monkeypatch.setattr(studio, '_populate_armour', lambda: None)
    monkeypatch.setattr(studio, '_populate_weapons',
                        lambda **_: published.append((studio._session.model, threading.get_ident())))
    old_scene = object()
    studio._viewport._body = old_scene
    try:
        studio._request_model('old')
        until(started.is_set)
        studio._request_model('discarded')
        studio._request_model('new')
        assert studio._viewport._body is old_scene
        release.set()
        until(lambda: not studio._model_task.busy)
        assert ran == ['old', 'new']
        assert published == [('new', main)]
    finally:
        release.set()


@pytest.mark.parametrize("background", [False, True])
def test_character_reload_replays_pending_edits_and_preserves_redo(studio, monkeypatch, tmp_path, background):
    from tests.test_placement_studio_operations import BODY, DESC, FILES, MODEL, _Baseline, _edits
    from tools.placement_studio.model import Vec3

    baseline = _Baseline(FILES)
    baseline.root = tmp_path
    studio._baseline = baseline
    studio._background_loading = background
    edits = studio._edits = _edits()
    socket = edits.socket(BODY, "Pelvis_R_Socket")
    moved = Vec3(socket.translation.x + 1.0, socket.translation.y, socket.translation.z)
    edits.set_translation(BODY, socket.name, moved)
    edits.set_route(DESC, "CD_TwoHandWeapon_Sword", "in_socket", "Pelvis_R_Socket")
    edits.set_translation(BODY, socket.name, Vec3(99.0, 0.0, 0.0))
    assert edits.undo() and edits.can_redo
    captured = edits.capture()
    monkeypatch.setattr(studio, '_populate_armour', lambda: None)
    monkeypatch.setattr(studio, '_populate_weapons', lambda **_: None)

    for model in (MODEL, 'other', MODEL):
        if background:
            studio._request_model(model)
            until(lambda: not studio._model_task.busy)
        else:
            studio._model_box.blockSignals(True)
            studio._model_box.clear()
            studio._model_box.addItem(model, model)
            studio._model_box.blockSignals(False)
            studio._on_model_changed(0)
        assert studio._session.model == model
    displayed = next(item for item in studio._session.body_sockets() if item.name == socket.name)
    assert displayed.translation == moved
    binding = next(item for item in studio._session.bindings() if item.part_name == "CD_TwoHandWeapon_Sword")
    assert binding.part.in_socket == "Pelvis_R_Socket"
    assert studio._edits is edits and edits.capture() == captured and edits.can_redo
    assert edits.redo()
    studio._rebuild_session_from_edits()
    displayed = next(item for item in studio._session.body_sockets() if item.name == socket.name)
    assert displayed.translation.x == 99.0


def test_model_load_retries_changed_history_without_publishing_stale_bindings(studio, monkeypatch, tmp_path):
    from tests.test_placement_studio_operations import BODY, FILES, MODEL, _Baseline, _edits
    from tools.placement_studio.model import Vec3
    from tools.placement_studio.session import PlacementSession

    baseline = _Baseline(FILES)
    baseline.root = tmp_path
    studio._baseline, studio._edits = baseline, _edits()
    started, release = threading.Event(), threading.Event()
    main, calls, published = threading.get_ident(), [], []
    original = PlacementSession.with_edited_files

    def replay(session, files):
        assert threading.get_ident() != main
        calls.append(files)
        if len(calls) == 1:
            started.set()
            assert release.wait(3)
        return original(session, files)

    monkeypatch.setattr(PlacementSession, 'with_edited_files', replay)
    monkeypatch.setattr(studio, '_populate_armour', lambda: None)
    monkeypatch.setattr(studio, '_populate_weapons', lambda **_: published.append(studio._session))
    try:
        studio._request_model(MODEL)
        until(started.is_set)
        studio._edits.set_translation(BODY, 'Pelvis_R_Socket', Vec3(7.0, 0.0, 0.0))
        release.set()
        until(lambda: not studio._model_task.busy)
        assert len(calls) == 2 and published == [studio._session]
        socket = next(item for item in studio._session.body_sockets() if item.name == 'Pelvis_R_Socket')
        assert socket.translation.x == 7.0
    finally:
        release.set()


def test_archive_reload_does_not_overlay_pending_socket_edits(studio, monkeypatch):
    from tests.test_placement_studio_operations import FILES, W2H, _edits, _session
    from tools.placement_studio.model import Vec3

    edits = studio._edits = _edits()
    edits.set_translation(W2H, 'Spine2_B_SubWeapon_ChildSocket', Vec3(3.0, 0.0, 0.0))
    session = studio._session = _session().with_edited_files(edits.current_files())
    monkeypatch.setattr(studio, '_refresh_animation', lambda: None)
    result = SimpleNamespace(errors=(), sockets=((W2H, FILES[W2H]),), charts=())
    list(studio._publish_archive_content(session, SimpleNamespace(weapons=False), result))
    weapons = [weapon for weapon in session.weapons() if weapon.game_path == W2H]
    assert len(weapons) == 1
    assert weapons[0].sockets['Spine2_B_SubWeapon_ChildSocket'].translation.x == 3.0


def test_mesh_request_does_not_read_on_ui_or_replace_scene_when_cancelled(studio, monkeypatch):
    from tools.placement_studio import window_loading
    from tools.placement_studio.loading import MeshResult
    from tools.placement_studio.session import PlacementSession
    from tools.placement_studio.resolver import PlacementResolver
    from tools.placement_studio.skeleton import BoneHierarchy
    started, release = threading.Event(), threading.Event()
    calls, main = [], threading.get_ident()
    studio._session = PlacementSession('rig', BoneHierarchy([]), PlacementResolver())
    old_scene = object()
    studio._viewport._body = old_scene
    def prepare(request, cancelled, progress):
        assert threading.get_ident() != main
        calls.append(request)
        started.set()
        assert release.wait(3)
        return MeshResult((), 0, '', None, None, 0, ())
    monkeypatch.setattr(window_loading, 'prepare_meshes', prepare)
    try:
        for _ in range(5):
            studio._refresh_scene()
        until(started.is_set)
        assert len(calls) == 1
        assert studio._viewport._body is old_scene
        studio._stop_loading()
        release.set()
        until(lambda: not studio._mesh_task.busy)
        assert studio._viewport._body is old_scene
    finally:
        release.set()


@pytest.mark.parametrize('failure', ['error', 'no_result'])
def test_failed_mesh_selection_can_retry_without_losing_previous_scene(studio, monkeypatch, failure):
    from tools.placement_studio import window_loading
    from tools.placement_studio.loading import MeshResult
    from tools.placement_studio.session import PlacementSession
    from tools.placement_studio.resolver import PlacementResolver
    from tools.placement_studio.skeleton import BoneHierarchy

    studio._session = PlacementSession('rig', BoneHierarchy([]), PlacementResolver())
    old_scene = studio._viewport._body = object()
    calls, published = [], []

    def prepare(request, cancelled, progress):
        calls.append(request)
        if len(calls) == 1:
            if failure == 'error':
                raise OSError('Transient mesh failure')
            return None
        return MeshResult((), 0, '', None, None, 0, ())

    monkeypatch.setattr(window_loading, 'prepare_meshes', prepare)
    monkeypatch.setattr(studio, '_refresh_scene', lambda: published.append(studio._mesh_ready))
    monkeypatch.setattr(studio, '_report_status', lambda: None)
    assert not studio._ensure_meshes_prepared()
    until(lambda: not studio._mesh_task.busy)
    assert studio._viewport._body is old_scene and published == []
    assert not studio._ensure_meshes_prepared()
    until(lambda: not studio._mesh_task.busy)
    assert len(calls) == 2
    assert studio._ensure_meshes_prepared()
    assert published == [studio._mesh_ready]
    assert studio._mesh_requested is None


def test_stale_mesh_failure_does_not_clear_the_newer_request(studio, monkeypatch):
    from tools.placement_studio import window_loading
    from tools.placement_studio.loading import MeshResult
    from tools.placement_studio.session import PlacementSession
    from tools.placement_studio.resolver import PlacementResolver
    from tools.placement_studio.skeleton import BoneHierarchy

    started, release = threading.Event(), threading.Event()
    calls, published = [], []
    studio._session = PlacementSession('old', BoneHierarchy([]), PlacementResolver())

    def prepare(request, cancelled, progress):
        calls.append(request.model)
        if request.model == 'old':
            started.set()
            assert release.wait(3)
            raise OSError('Obsolete failure')
        return MeshResult((), 0, '', None, None, 0, ())

    monkeypatch.setattr(window_loading, 'prepare_meshes', prepare)
    monkeypatch.setattr(studio, '_refresh_scene', lambda: published.append(studio._session.model))
    monkeypatch.setattr(studio, '_report_status', lambda: None)
    try:
        assert not studio._ensure_meshes_prepared()
        until(started.is_set)
        studio._session = PlacementSession('new', BoneHierarchy([]), PlacementResolver())
        assert not studio._ensure_meshes_prepared()
        newer_key = studio._mesh_requested
        studio._meshes_prepared(('obsolete-key', None), '')
        assert studio._mesh_requested == newer_key
        release.set()
        until(lambda: not studio._mesh_task.busy)
        assert calls == ['old', 'new']
        assert published == ['new']
        assert studio._mesh_ready == newer_key
        assert studio._ensure_meshes_prepared()
    finally:
        release.set()


def test_chart_cache_detects_changed_payload_with_same_history_count(studio, monkeypatch):
    from tools.placement_studio.editing import EditSession
    from tools.placement_studio import loading
    path = 'actionchart/bin__/test.paac'
    studio._edits = EditSession({path: b'one'})
    started, release = threading.Event(), threading.Event()
    calls = []
    original = loading.prepare_charts
    def prepare(sources, cancelled, progress):
        calls.append(sources)
        if len(calls) == 1:
            started.set()
            assert release.wait(3)
        return original(sources, cancelled, progress)
    monkeypatch.setattr(loading, 'prepare_charts', prepare)
    try:
        assert not studio._ensure_chart_indexes()
        until(started.is_set)
        studio._edits._charts[path] = b'two'
        assert not studio._ensure_chart_indexes()
        release.set()
        until(lambda: not studio._chart_task.busy)
        assert studio._chart_sources_ready == ((path, b'two'),)
        assert studio._ensure_chart_indexes()
        assert len(calls) == 2
    finally:
        release.set()


def test_mesh_decoder_checks_cancellation_between_files(monkeypatch, tmp_path):
    from tools.placement_studio.loading import MeshRequest, prepare_meshes
    from tools.placement_studio import skinning
    reads, stopped = [], threading.Event()
    class Source:
        def __contains__(self, path):
            return True
        def read(self, path):
            reads.append(path)
            stopped.set()
            return b'fixture'
    monkeypatch.setattr(skinning, 'load_skinned', lambda *_: object())
    request = MeshRequest(Source(), 'rig', SimpleNamespace(parsed=object()),
                          (('body', None), ('head', None)), (), ('weapon', None))
    assert prepare_meshes(request, stopped.is_set, lambda *_: None) is None
    assert reads == ['body']


def test_archive_preparation_cancels_between_reads_and_rejects_changed_installation(monkeypatch):
    from tools.placement_studio.archive_loading import ArchiveRequest, prepare_archive_content
    from tools.placement_studio import armour, corpus
    request = ArchiveRequest('fixture', 'rig', frozenset(), (), (),
                             (('a.paac', 'a'), ('b.paac', 'b')), frozenset(), False)
    reads, stored = [], []
    monkeypatch.setattr(armour, 'cached_content', lambda *_: None)
    monkeypatch.setattr(armour, 'read_entry', lambda entry: reads.append(entry) or b'chart')
    monkeypatch.setattr(armour, 'store_content', lambda *args, **kwargs: stored.append(args))
    monkeypatch.setattr(corpus, 'package_signature', lambda *_: 'identity')
    stopped = threading.Event()
    assert prepare_archive_content(request, stopped.is_set, lambda *_: stopped.set()) is None
    assert reads == ['a'] and stored == []
    signatures = iter(['old', 'new'])
    monkeypatch.setattr(corpus, 'package_signature', lambda *_: next(signatures))
    with pytest.raises(ValueError, match='changed'):
        prepare_archive_content(request, lambda: False, lambda *_: None)
    assert stored == []


def test_archive_publication_preserves_edits_made_while_loading(studio):
    from tools.placement_studio.editing import EditSession
    from tools.placement_studio.archive_loading import ArchiveResult
    studio._edits = EditSession({})
    studio._edits.replace_clip('motion/test.paa', b'after', original=b'before')
    commands = studio._edits.commands()
    result = ArchiveResult((), (), (('actionchart/bin__/test.paac', b'chart'),), ())
    list(studio._publish_archive_content(None, SimpleNamespace(weapons=False), result))
    assert studio._edits.commands() == commands
    assert studio._edits.chart_bytes('actionchart/bin__/test.paac') == b'chart'
