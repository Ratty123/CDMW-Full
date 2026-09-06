"""UI heartbeats, immutable inputs, and stale/closed Studio preparation results."""
import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

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
        return SimpleNamespace(model=model)

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
