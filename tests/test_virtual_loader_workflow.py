"""Focused performance and presentation contracts for virtual preparation."""
import hashlib
import os
from pathlib import Path
import random
import threading
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

from cdmw.core import archive_accelerator
from cdmw.core.pathc_format import pathc_checksum
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services import virtual_loader_composition as composition
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
from cdmw.ui.new_item.virtual_loader_page import VirtualLoaderPage
from cdmw.ui.tools.mod_management import ModManagementTab
from tests.test_new_item_rust_ui import _send
from tests.test_virtual_loader import packages, game_bytes


def test_native_path_hashes_match_scalar_for_unicode_and_block_boundaries():
    if archive_accelerator.find_native_archive_accelerator() is None:
        pytest.skip('Build the archive accelerator to check the native path checksum command.')
    rng = random.Random(217)
    paths = ['', '/', '\\folder\\file.dds', 'character/å/頭盔.pac', 'A/Case.PAC']
    paths += ['x' * n for n in range(130)]
    paths += [''.join(rng.choices('abcDEF019/_- é龍', k=rng.randrange(1, 320))) for _ in range(1000)]
    result = archive_accelerator.path_checksums_native(paths)
    assert result is not None, 'Rebuild the native helper with path-checksum-job support.'
    assert list(result) == [pathc_checksum(path) for path in paths]


def test_native_path_hash_job_rejects_malformed_and_oversized_input(tmp_path):
    binary = archive_accelerator.find_native_archive_accelerator()
    if binary is None:
        pytest.skip('Build the archive accelerator to check the native path checksum command.')
    magic = b'CDPH\x01\0\0\0'
    one = magic + (1).to_bytes(4, 'little')
    invalid = [b'bad header', magic, magic + (4194305).to_bytes(4, 'little'),
               one, one + (32769).to_bytes(4, 'little'),
               one + (4).to_bytes(4, 'little') + b'ab',
               magic + (0).to_bytes(4, 'little') + b'trailing']
    for index, raw in enumerate(invalid):
        job, result = tmp_path / f'{index}.bin', tmp_path / f'{index}.out'
        job.write_bytes(raw)
        code, _, stderr = archive_accelerator.run_process_with_cancellation(
            [str(binary), 'path-checksum-job', str(job), str(result)],
            timeout_seconds=10, background=True)
        assert code != 0 and 'checksum' in stderr, (index, code, stderr)


@pytest.mark.parametrize('failure', ['exit', 'header', 'truncated', 'count', 'cancel'])
def test_native_path_hash_result_is_complete_or_discarded(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(archive_accelerator, 'find_native_archive_accelerator', lambda: tmp_path / 'helper.exe')
    monkeypatch.setattr(archive_accelerator, '_native_archive_accelerator_ready', lambda _: True)
    def run(command, **kwargs):
        if failure == 'cancel':
            raise RunCancelled()
        header = Path(command[2]).read_bytes()[:12]
        if failure == 'header':
            header = b'bad!' + header[4:]
        if failure == 'count':
            header = header[:8] + (2).to_bytes(4, 'little')
        Path(command[3]).write_bytes(header + (b'' if failure == 'truncated' else b'\0' * 4))
        return (2 if failure == 'exit' else 0), '', ''
    monkeypatch.setattr(archive_accelerator, 'run_process_with_cancellation', run)
    if failure == 'cancel':
        with pytest.raises(RunCancelled):
            archive_accelerator.path_checksums_native(['one'])
    else:
        assert archive_accelerator.path_checksums_native(['one']) is None


def test_large_collision_index_uses_one_batch_and_keeps_ambiguity(monkeypatch):
    from cdmw.services.independent_item_install import _AssetHashes
    from cdmw.core import pathc_format
    seen = []
    names = [f'path/{i}' for i in range(4100)]
    def batch(paths, **kwargs):
        seen.append(tuple(paths))
        return [1] * len(paths)
    monkeypatch.setattr(archive_accelerator, 'path_checksums_native', batch)
    monkeypatch.setattr(pathc_format, 'pathc_checksum', lambda name: 1 if name.startswith('path/') else 2)
    index = _AssetHashes(iter(names))
    index.check({'safe'}, set())
    index.check({'safe'}, set())
    with pytest.raises(ValueError, match='asset hash collides'):
        index.check({names[0]}, set())
    assert seen == [tuple(names)]


def test_source_hashes_are_fresh_and_concurrency_is_bounded(tmp_path, monkeypatch):
    paths = []
    for i in range(6):
        path = tmp_path / str(i)
        path.write_bytes(bytes([i]) * 4096)
        paths.append(path)
    original = composition.hash_file
    barrier, lock = threading.Barrier(2), threading.Lock()
    active = peak = 0
    def hashed(path, stop):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            barrier.wait(5)
            return original(path, stop)
        finally:
            with lock:
                active -= 1
    monkeypatch.setattr(composition, 'hash_file', hashed)
    progress = []
    result = composition._hash_sources(paths, on_progress=lambda n, total: progress.append((n, total)))
    assert peak == 2 and active == 0
    assert result == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    assert progress == [(n, 6) for n in range(1, 7)]
    paths[0].write_bytes(b'changed')
    assert composition._hash_sources(paths)[str(paths[0])] != result[str(paths[0])]


def test_source_hash_cancellation_drains_workers(monkeypatch):
    stop = threading.Event()
    active = 0
    lock = threading.Lock()
    def hashed(path, event):
        nonlocal active
        with lock:
            active += 1
        try:
            stop.set()
            raise RunCancelled()
        finally:
            with lock:
                active -= 1
    monkeypatch.setattr(composition, 'hash_file', hashed)
    with pytest.raises(RunCancelled):
        composition._hash_sources(range(10), stop)
    assert active == 0


def test_prepare_reports_monotonic_progress_without_changing_output(tmp_path):
    root, files = packages(tmp_path, 2)
    before = game_bytes(root)
    events = []
    first = composition.prepare_profile(VirtualProfile(files), root,
        on_progress=lambda n, total, detail: events.append((n, total, detail)))
    second = composition.prepare_profile(VirtualProfile(files), root)
    assert events[0][0] == 0 and events[-1][0] == 100
    assert [n for n, _, _ in events] == sorted(n for n, _, _ in events)
    assert all(total == 100 and detail for _, total, detail in events)
    assert first.files == second.files and first.registry == second.registry
    assert game_bytes(root) == before and not (root / '.cdmw').exists()


def test_virtual_list_sorting_is_display_only_and_projects_progress(tmp_path, monkeypatch):
    from cdmw.services import virtual_loader_process
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=True)
    page = VirtualLoaderPage(controller, tmp_path)
    bridge = NewItemPresentationBridge(page)
    try:
        page.resize(1200, 820)
        page.show()
        paths = [tmp_path / 'z-last.cditem', tmp_path / 'a-first.cditem']
        page._append_selection('item', paths)
        original = page._profile()
        page._saved_selection = original
        page._runtime = SimpleNamespace(state='ready')
        for order in (1, 0, 2):
            _send(bridge, page.sort_choice, 'choose', order)
            assert page._profile() == original
            page._buttons()
            assert page.launch_button.isEnabled()
        assert page.selection.topLevelItem(0).text(0) == 'a-first.cditem'
        assert page.selection.topLevelItem(0).toolTip(0) == str(paths[1])
        _send(bridge, page.selection, 'sort', {'column': 0, 'descending': True})
        assert page.selection.topLevelItem(0).text(0) == 'z-last.cditem'
        assert page._profile() == original and page.launch_button.isEnabled()
        assert all(button.toolTip() for button in page.findChildren(QPushButton))
        assert page.tools_toggle.toolTip() and page.tools.isHidden()
        _send(bridge, page.tools_toggle, 'activate')
        assert not page.tools.isHidden()
        _send(bridge, page.tools_toggle, 'activate')
        app.processEvents()
        assert page.selection.height() > 500
        assert page.workspace.widget(1).x() > page.workspace.widget(0).x()
        def prepare(profile, root, *, on_log, stop_event, on_progress):
            assert profile == original
            on_progress(54, 100, 'Verifying source file integrity…')
            assert page.progress.value() == 54
            on_progress(12, 100, 'Reading game data…')
            assert page.progress.value() == 54
            return SimpleNamespace(summary=('Ready',))
        monkeypatch.setattr(virtual_loader_process, 'prepare_profile_in_subprocess', prepare)
        _send(bridge, page.prepare_button, 'activate')
        assert page.progress.value() == 100 and page.save_button.isEnabled()
        state = bridge.snapshot()
        projected = next(node for node in bridge.document.registry.current.values() if node['name'] == 'virtual_loader_progress')
        assert projected['props']['value'] == 100 and not state['unsupported']
        monkeypatch.setattr(controller, '_run', lambda *args, **kwargs: False)
        _send(bridge, page.prepare_button, 'activate')
        assert page.progress.isHidden() and not page._working
    finally:
        page.request_shutdown()
        controller.shutdown()
        page.close()


def test_virtual_workspace_avoids_duplicate_operation_controls(tmp_path, monkeypatch):
    from tests.test_mod_management import pump
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController()
    tab = ModManagementTab(controller=controller, get_package_root=lambda: str(tmp_path))
    monkeypatch.setattr(tab.virtual_page, 'refresh', lambda: None)
    monkeypatch.setattr(tab.overview, 'refresh', lambda *_: None)
    tab.open_page('virtual')
    entered, release = threading.Event(), threading.Event()
    def prepare(log, progress, stop):
        entered.set()
        assert release.wait(5)
        progress(50, 100, 'Reading game data…')
    try:
        tab.virtual_page._run(prepare, lambda _: None, with_progress=True)
        pump(app, entered.is_set)
        assert tab.operation_bar.isHidden()
        tab.open_page('installed')
        assert not tab.operation_bar.isHidden()
        tab.open_page('virtual')
        assert tab.operation_bar.isHidden()
        release.set()
        pump(app, lambda: not controller.busy)
        assert tab.operation_bar.isHidden() and tab.virtual_page.progress.value() == 100
    finally:
        release.set()
        tab.request_shutdown()
        controller.shutdown()
        tab.close()
