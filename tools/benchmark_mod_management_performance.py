"""Compare synthetic Mod Management workloads against an explicit source snapshot.

Default workloads use synthetic data. Optional --retained-root reads existing
retired ownership journals through Details; it never changes game files or
launches a renderer/game process. Run one variant at a time after build work
stops. The Qt delays model scheduling, not actual game I/O or full opening time.
"""
import argparse
import gc
import hashlib
import io
import json
import os
from pathlib import Path
import random
import statistics
import sys
import tempfile
import time
import tracemalloc
from unittest.mock import patch
import zipfile


def pump(app, predicate, timeout=8):
    deadline = time.perf_counter() + timeout
    while not predicate() and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.001)
    if not predicate():
        raise TimeoutError('The synthetic workload did not finish before its deadline.')


def inventory_workload(runtime_root, samples, status_delay, inventory_delay):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.domain.virtual_loader import VirtualSessionStatus
    from cdmw.services.archive_overlay_manager import InstalledOverlay
    from cdmw.ui.tools.mod_management import ModManagementTab

    app = QApplication.instance() or QApplication([])
    results = []
    with tempfile.TemporaryDirectory(prefix='inventory-', dir=runtime_root) as folder:
        for _ in range(samples):
            counts = {'inventory_reads': 0, 'cancelled_inventory_reads': 0, 'status_reads': 0}

            def inventory(_root, *, stop_event):
                counts['inventory_reads'] += 1
                if stop_event.wait(inventory_delay):
                    counts['cancelled_inventory_reads'] += 1
                    raise_if_cancelled(stop_event)
                return (InstalledOverlay('synthetic-overlay', 'Synthetic overlay', (), '0041', 2, 1),)

            def status(_root, *, stop_event, **_kwargs):
                counts['status_reads'] += 1
                stop_event.wait(status_delay)
                raise_if_cancelled(stop_event)
                return VirtualSessionStatus('unavailable', 'Synthetic runtime status')

            with patch('cdmw.ui.new_item.overlay_manager_dialog.list_installed_overlays', inventory), \
                    patch('cdmw.services.overlay_inventory_details.external_overlay_summary', return_value=''), \
                    patch('cdmw.ui.tools.mod_management_overview.mounted_archive_status', return_value=()), \
                    patch('cdmw.services.mod_management_inventory.mod_sources', return_value=({}, (), False)), \
                    patch('cdmw.services.virtual_loader_runtime.runtime_status', status), \
                    patch('cdmw.services.virtual_loader_state.load_profile', return_value=None):
                tab = ModManagementTab(get_package_root=lambda: folder)
                try:
                    started = time.perf_counter()
                    tab.show()
                    pump(app, lambda: bool(tab.inventory._entries))
                    first_row = time.perf_counter() - started
                    pump(app, lambda: not tab.controller.busy
                         and not getattr(tab.virtual_page, '_status_reading', False)
                         and not tab.virtual_page._source_lane.busy
                         and not tab.inventory._inventory_lane.busy)
                    results.append({'first_inventory_row_seconds': first_row,
                                    'all_reads_finished_seconds': time.perf_counter() - started, **counts})
                finally:
                    tab.request_shutdown()
                    pump(app, lambda: not tab.iter_shutdown_workers())
                    tab.deleteLater()
                    app.sendPostedEvents(None, QEvent.DeferredDelete)
    return {'kind': 'synthetic_headless_qt_read_scheduling',
            'configured_status_delay_seconds': status_delay,
            'configured_inventory_delay_seconds': inventory_delay,
            'samples': results,
            'median_first_inventory_row_seconds': statistics.median(
                row['first_inventory_row_seconds'] for row in results),
            'median_all_reads_finished_seconds': statistics.median(
                row['all_reads_finished_seconds'] for row in results)}


def make_journal(root, payload_mib):
    from cdmw.services import archive_overlay_manager as overlays

    rng = random.Random(1729)
    size = payload_mib * 1024 * 1024
    changes = {'textures/synthetic_' + str(index) + '.dds': {
        'before': rng.randbytes(size), 'after': rng.randbytes(size), 'flags': 0}
        for index in range(2)}
    raw = overlays._pack_changes(changes)
    # Fix ZIP timestamps so each source variant receives byte-identical input.
    normalized = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, \
            zipfile.ZipFile(normalized, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as target:
        for member in source.infolist():
            info = zipfile.ZipInfo(member.filename, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, source.read(member), compresslevel=1)
    raw = normalized.getvalue()
    layer = {'id': '1' * 32, 'label': 'Synthetic overlay', 'item_keys': [],
             'dependencies': [], 'active': True, 'created_at': 1, 'legacy': False,
             'file_count': len(changes), 'sha256': overlays._digest(raw)}
    state = {'format': overlays._FORMAT, 'directory': '0041', 'layers': [layer],
             'sources': {}, 'published': {}}
    path = root / overlays.overlay_journal_path(layer)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    (root / overlays.INDEX_PATH).write_bytes(overlays._inventory_bytes(state))
    return layer['id'], {'journal_bytes': len(raw), 'journal_sha256': hashlib.sha256(raw).hexdigest(),
                         'uncompressed_payload_bytes': size * 4, 'payload_count': 4}


def details_samples(root, identity, samples):
    from cdmw.services.overlay_inventory_details import overlay_details

    results = []
    for _ in range(samples):
        gc.collect()
        counts = {'payload_read_count': 0, 'payload_bytes_read': 0}
        original_read = zipfile.ZipFile.read

        def read(archive, name, *args, **kwargs):
            data = original_read(archive, name, *args, **kwargs)
            filename = name.filename if isinstance(name, zipfile.ZipInfo) else name
            if filename.startswith('payloads/'):
                counts['payload_read_count'] += 1
                counts['payload_bytes_read'] += len(data)
            return data

        tracemalloc.start()
        try:
            with patch.object(zipfile.ZipFile, 'read', read):
                started = time.perf_counter()
                text = overlay_details(root, identity)
                elapsed = time.perf_counter() - started
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        results.append({'seconds': elapsed, 'peak_python_traced_bytes': peak,
                        'details_sha256': hashlib.sha256(text.encode()).hexdigest(), **counts})
    if len({row['details_sha256'] for row in results}) != 1:
        raise AssertionError('The same journal input produced different Details text.')
    return {'samples': results,
            'median_seconds': statistics.median(row['seconds'] for row in results),
            'median_peak_python_traced_bytes': statistics.median(
                row['peak_python_traced_bytes'] for row in results)}


def journal_workload(runtime_root, samples, payload_mib):
    with tempfile.TemporaryDirectory(prefix='journal-', dir=runtime_root) as folder:
        root = Path(folder).resolve()
        identity, fixture = make_journal(root, payload_mib)
        return {'kind': 'synthetic_journal_details', **fixture,
                **details_samples(root, identity, samples)}


def fingerprint(path):
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise RuntimeError('A read-only input changed while its digest was being calculated.')
    return {'bytes': after.st_size, 'mtime_ns': after.st_mtime_ns,
            'ctime_ns': after.st_ctime_ns, 'sha256': digest.hexdigest()}


def retained_journal_workload(root, samples):
    from cdmw.services import archive_overlay_manager as overlays

    root = root.resolve()
    index_path = overlays._target(root, overlays.INDEX_PATH)
    index_before = fingerprint(index_path)
    state = overlays._load_index(root)
    layers = [layer for layer in state['layers']
              if not layer['active'] and not layer.get('disabled', False)] if state else []
    if not layers:
        raise ValueError('The explicit retained root has no retired ownership journals.')
    journals = []
    for layer in layers:
        relative = overlays.overlay_journal_path(layer)
        path = overlays._target(root, relative)
        before = fingerprint(path)
        if before['sha256'] != layer['sha256']:
            raise ValueError('A retained journal differs from its authoritative inventory digest.')
        with zipfile.ZipFile(path) as archive:
            payloads = [member for member in archive.infolist()
                        if member.filename.startswith('payloads/')]
        measurement = details_samples(root, layer['id'], samples)
        after = fingerprint(path)
        if before != after:
            raise RuntimeError('A retained journal changed during the read-only comparison.')
        journals.append({'overlay_id': layer['id'], 'journal_relative_path': relative,
                         'before': before, 'after': after,
                         'payload_count': len(payloads),
                         'declared_uncompressed_payload_bytes': sum(p.file_size for p in payloads),
                         **measurement})
    index_after = fingerprint(index_path)
    if index_before != index_after:
        raise RuntimeError('The ownership inventory changed during the read-only comparison.')
    return {'kind': 'retained_journal_details_read_only',
            'evidence_limit': 'Retired-journal Details calls, not the current visible mod list opening.',
            'root': str(root), 'index_before': index_before, 'index_after': index_after,
            'journals': journals}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--retained-root', type=Path,
                        help='Explicit game root whose retired journals may be read without changing it.')
    parser.add_argument('--samples', type=int, default=5)
    parser.add_argument('--payload-mib', type=int, default=8)
    parser.add_argument('--status-delay', type=float, default=0.2)
    parser.add_argument('--inventory-delay', type=float, default=0.08)
    args = parser.parse_args()
    if not 1 <= args.samples <= 20 or not 1 <= args.payload_mib <= 32:
        parser.error('Use 1-20 samples and 1-32 MiB per payload.')
    if not 0 < args.status_delay <= 2 or not 0 < args.inventory_delay <= 2:
        parser.error('Synthetic read delays must be greater than zero and no more than 2 seconds.')
    source = args.source_root.resolve()
    if not (source / 'cdmw/ui/tools/mod_management.py').is_file():
        parser.error('The source root must be an explicit CDMW source snapshot.')
    runtime = args.runtime_root.resolve()
    for key, suffix in (('TEMP', 'temp'), ('TMP', 'temp'), ('APPDATA', 'roaming'),
                        ('LOCALAPPDATA', 'local'), ('CDMW_TEMP_CACHE_ROOT', 'cache')):
        directory = runtime / suffix
        directory.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(directory)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    tempfile.tempdir = str(runtime / 'temp')
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source))
    os.chdir(source)
    evidence = {'format': 'cdmw_mod_management_synthetic_performance_v1',
                'source_root': str(source),
                'evidence_limit': 'Synthetic workloads and optional retained-journal Details. No game mutation, full UI opening, or rendered gameplay acceptance.',
                'source_sha256': {path: hashlib.sha256((source / path).read_bytes()).hexdigest()
                    for path in ('cdmw/ui/tools/mod_management_list.py',
                                 'cdmw/ui/new_item/virtual_loader_page.py',
                                 'cdmw/services/archive_overlay_manager.py',
                                 'cdmw/services/overlay_inventory_details.py')}}
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    try:
        evidence['inventory'] = inventory_workload(runtime / 'temp', args.samples,
                                                   args.status_delay, args.inventory_delay)
        evidence['journal'] = journal_workload(runtime / 'temp', args.samples, args.payload_mib)
        if args.retained_root is not None:
            evidence['retained_journals'] = retained_journal_workload(args.retained_root, args.samples)
    finally:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.shutdown()
        from cdmw.core.owned_temp import close_owned_temp_directory_locks
        close_owned_temp_directory_locks()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output),
                      'median_first_inventory_row_seconds': evidence['inventory']['median_first_inventory_row_seconds'],
                      'median_journal_seconds': evidence['journal']['median_seconds'],
                      'median_peak_python_traced_bytes': evidence['journal']['median_peak_python_traced_bytes']}))


if __name__ == '__main__':
    main()
