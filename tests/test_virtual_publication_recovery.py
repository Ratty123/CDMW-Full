"""Publication outcomes use owned fixtures and real queued Qt delivery."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import threading

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.domain.virtual_loader import VirtualLoaderError, VirtualProfile
from cdmw.services import virtual_loader_state as state
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.independent_item_install import load_registry
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.virtual_loader_page import VirtualLoaderPage
from tests.test_new_item_task_outcomes import pump
from tests.test_virtual_loader import packages, game_bytes


def after_commit_failure(monkeypatch, root, phase, stop=None, before_error=None):
    fired = []
    if phase in ('journal-cleanup', 'journal-removed'):
        original = Path.unlink
        def unlink(path, *args, **kwargs):
            if path == root / state.JOURNAL_PATH and not fired:
                fired.append(True)
                if phase == 'journal-removed':
                    original(path, *args, **kwargs)
                if stop:
                    stop.set()
                if before_error:
                    before_error()
                raise OSError('injected committed journal cleanup failure')
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'unlink', unlink)
    else:
        original = state.atomic_write_bytes
        def write(path, data):
            original(path, data)
            if path == root / state.PROFILE_PATH and not fired:
                fired.append(True)
                if stop:
                    stop.set()
                if before_error:
                    before_error()
                raise OSError('injected error after active profile replacement')
        monkeypatch.setattr(state, 'atomic_write_bytes', write)
    return fired


@pytest.mark.parametrize('phase', ['journal-cleanup', 'profile-replaced', 'journal-removed'])
def test_recovered_commit_returns_verified_profile_despite_late_cancel(tmp_path, monkeypatch, caplog, phase):
    root, files = packages(tmp_path, 1)
    before = game_bytes(root)
    prepared = prepare_profile(VirtualProfile(files), root)
    stop = threading.Event()
    fired = after_commit_failure(monkeypatch, root, phase, stop)
    result = state.publish_profile(prepared, stop_event=stop)
    assert fired and stop.is_set()
    assert result == state.load_profile(root, registry=load_registry(root))
    assert (root / state.PROFILE_PATH).read_bytes() == prepared.profile
    assert (root / state.REGISTRY).read_bytes() == prepared.registry
    assert not (root / state.JOURNAL_PATH).exists()
    assert 'injected' in caplog.text and 'committed' in caplog.text
    assert game_bytes(root) == before


@pytest.mark.parametrize('damage', ['missing-file', 'changed-file', 'manifest', 'ledger'])
def test_recovery_never_clears_journal_or_reports_commit_for_damaged_generation(tmp_path, monkeypatch, damage):
    root, files = packages(tmp_path, 1)
    prepared = prepare_profile(VirtualProfile(files), root)
    generation = state.generation_path(root, prepared.generation)
    def corrupt():
        if damage == 'ledger':
            (root / state.REGISTRY).write_bytes(b'foreign ledger bytes')
        elif damage == 'manifest':
            (generation / 'profile.json').write_bytes(b'foreign manifest')
        else:
            payload = generation / 'files' / prepared.files[0][0]
            if damage == 'missing-file':
                payload.unlink()
            else:
                payload.write_bytes(b'foreign generation payload')
    after_commit_failure(monkeypatch, root, 'journal-cleanup', before_error=corrupt)
    with pytest.raises(VirtualLoaderError, match='[Rr]ecover'):
        state.publish_profile(prepared)
    assert (root / state.JOURNAL_PATH).is_file()
    backup = root / '.cdmw/virtual-loader/recovery' / (prepared.generation + '.json')
    assert backup.is_file()
    with pytest.raises(VirtualLoaderError, match='Recover'):
        state.load_profile(root)


def test_recovery_readback_does_not_trust_a_writer_that_returned_without_restoring(tmp_path, monkeypatch):
    root, files = packages(tmp_path, 2)
    first = prepare_profile(VirtualProfile(files[:1]), root)
    state.publish_profile(first)
    before = {p: (root / p).read_bytes() for p in (state.REGISTRY, state.PROFILE_PATH)}
    prepared = prepare_profile(VirtualProfile(files), root)
    assert prepared.registry != before[state.REGISTRY]
    original = state.atomic_write_bytes
    def partial_publication(path, data):
        if path == root / state.PROFILE_PATH:
            raise OSError('injected profile write failure')
        if path == root / state.REGISTRY and data == before[state.REGISTRY]:
            return  # A broken restore must not be accepted without readback.
        original(path, data)
    monkeypatch.setattr(state, 'atomic_write_bytes', partial_publication)
    with pytest.raises(VirtualLoaderError, match='[Rr]ecover'):
        state.publish_profile(prepared)
    assert (root / state.JOURNAL_PATH).is_file()
    assert (root / state.PROFILE_PATH).read_bytes() == before[state.PROFILE_PATH]
    assert (root / state.REGISTRY).read_bytes() == prepared.registry


def test_real_queued_profile_apply_delivers_one_recovered_commit_and_diagnostic(tmp_path, monkeypatch):
    root, files = packages(tmp_path, 1)
    prepared = prepare_profile(VirtualProfile(files), root)
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController()
    page = VirtualLoaderPage(controller, root)
    page._prepared = prepared
    entered, release = threading.Event(), threading.Event()
    applied, messages, refreshed = [], [], []
    page.profile_applied.connect(lambda: applied.append(threading.get_ident()))
    controller.log_message.connect(messages.append)
    monkeypatch.setattr(page, '_queue', lambda callback: refreshed.append(callback))
    def pause():
        entered.set()
        assert release.wait(5), 'Owned publication was not released'
    after_commit_failure(monkeypatch, root, 'profile-replaced', before_error=pause)
    try:
        page._save()
        pump(app, entered.is_set)
        page._cancel()
        release.set()
        pump(app, lambda: not controller.busy)
        assert applied == [threading.get_ident()]
        assert len(refreshed) == 1 and page._prepared is None
        assert not page._error and page.progress.isHidden()
        assert any('injected error after active profile replacement' in message for message in messages)
        assert state.load_profile(root, registry=load_registry(root))['generation'] == prepared.generation
    finally:
        release.set()
        page.request_shutdown()
        controller.request_shutdown()
        pump(app, lambda: not controller.iter_shutdown_workers())
        page.close()


@pytest.mark.parametrize('selected', ['before', 'after'])
def test_recovery_journal_remove_then_error_preserves_verified_terminal_state(tmp_path, monkeypatch, selected):
    root, files = packages(tmp_path, 2)
    state.publish_profile(prepare_profile(VirtualProfile(files[:1]), root))
    original_profile = (root / state.PROFILE_PATH).read_bytes()
    prepared = prepare_profile(VirtualProfile(files), root)
    write = state.atomic_write_bytes
    def fail_publication(path, data):
        if path == root / state.PROFILE_PATH and data == prepared.profile:
            if selected == 'after':
                write(path, data)
            raise OSError('primary profile publication error')
        write(path, data)
    monkeypatch.setattr(state, 'atomic_write_bytes', fail_publication)
    after_commit_failure(monkeypatch, root, 'journal-removed')
    if selected == 'before':
        with pytest.raises(OSError, match='primary profile publication error'):
            state.publish_profile(prepared)
        assert (root / state.PROFILE_PATH).read_bytes() == original_profile
    else:
        result = state.publish_profile(prepared)
        assert result == state.load_profile(root, registry=load_registry(root))
        assert (root / state.PROFILE_PATH).read_bytes() == prepared.profile
    assert not (root / state.JOURNAL_PATH).exists()


@pytest.mark.parametrize('damage', ['generation', 'backup', 'ledger'])
def test_absent_journal_is_not_commit_evidence_without_exact_recovery_material(tmp_path, monkeypatch, damage):
    root, files = packages(tmp_path, 1)
    prepared = prepare_profile(VirtualProfile(files), root)
    def corrupt():
        if damage == 'generation':
            path = state.generation_path(root, prepared.generation) / 'files' / prepared.files[0][0]
        elif damage == 'backup':
            path = root / '.cdmw/virtual-loader/recovery' / (prepared.generation + '.json')
        else:
            path = root / state.REGISTRY
        path.write_bytes(b'changed evidence')
    after_commit_failure(monkeypatch, root, 'journal-removed', before_error=corrupt)
    with pytest.raises(VirtualLoaderError, match='[Rr]ecover'):
        state.publish_profile(prepared)
