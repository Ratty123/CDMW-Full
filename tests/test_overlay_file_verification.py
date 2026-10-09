"""Publication must compare exact files without allocating another whole archive."""
from dataclasses import replace
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from cdmw.domain.new_item.spec import ModelSource
from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.independent_item_install import prepare_install
from cdmw.services.independent_item_package import from_plan, package_bytes
from cdmw.services.new_item_planning import ModelFiles
from tests.test_archive_overlay_manager import Backups, shop_spec
from tests.test_independent_item_regressions import files_in
from tests.test_independent_items import setup_game
from tests.test_new_item_service import PAC_XML, STEM, imported_pac, _fake_dds


def prepared_rebuild(tmp_path):
    service, snapshot, _ = setup_game(tmp_path)
    model = ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML),
                       f'character/texture/1_pc/{STEM}_d.dds': _fake_dds(1024, 1024)})
    plan = service.plan(replace(shop_spec('LargeVerification'), model_source=ModelSource.IMPORTED),
                        snapshot, model=model, capture_independent=True)
    raw = package_bytes(from_plan(plan, uuid4().hex))
    root, backups = tmp_path / 'game', Backups(tmp_path)
    backups.apply(prepare_install((raw,), root).preparation)
    return root, backups, prepare_install((raw,), root, rebuild=True).preparation


@pytest.mark.parametrize('fail_write', [False, True])
def test_real_publication_and_rollback_verify_large_files_with_bounded_reads(tmp_path, monkeypatch, fail_write):
    root, backups, prepared = prepared_rebuild(tmp_path)
    before = files_in(root)
    reads, guarded = [], [True]
    original_open = Path.open
    class BoundedReader:
        def __init__(self, handle):
            self.handle = handle
        def __enter__(self):
            self.handle.__enter__()
            return self
        def __exit__(self, *args):
            return self.handle.__exit__(*args)
        def __getattr__(self, name):
            return getattr(self.handle, name)
        def read(self, size=-1):
            reads.append(size)
            assert 0 < size <= 1024 * 1024, 'Verification made an unbounded archive read'
            return self.handle.read(size)
        def readinto(self, buffer):
            reads.append(len(buffer))
            assert 0 < len(buffer) <= 1024 * 1024, 'Verification requested an unbounded buffer'
            return self.handle.readinto(buffer)
    def checked_open(path, *args, **kwargs):
        mode = args[0] if args else kwargs.get('mode', 'r')
        handle = original_open(path, *args, **kwargs)
        if guarded[0] and mode == 'rb' and path.stat().st_size > 1024 * 1024:
            return BoundedReader(handle)
        return handle
    def backup(paths, label):
        guarded[0] = False  # Test helper keeps assertion snapshots; it is not the verifier.
        try:
            return backups.backup_files(paths, description=label)
        finally:
            guarded[0] = True
    def restore(path):
        guarded[0] = False
        try:
            backups.restore_backup(path)
        finally:
            guarded[0] = True
    if fail_write:
        write = overlays.atomic_write_bytes
        def fail(path, payload):
            write(path, payload)
            if path.suffix == '.paz':
                raise OSError('injected staged archive failure')
        monkeypatch.setattr(overlays, 'atomic_write_bytes', fail)
    monkeypatch.setattr(Path, 'open', checked_open)
    if fail_write:
        with pytest.raises(OSError, match='injected staged archive'):
            overlays.apply_overlay_change(prepared, confirmed=True, backup=backup,
                restore_backup=restore, game_running=lambda: False)
    else:
        overlays.apply_overlay_change(prepared, confirmed=True, backup=backup,
            restore_backup=restore, game_running=lambda: False)
    guarded[0] = False
    assert reads and backups.count == 2
    if fail_write:
        assert files_in(root) == before
    else:
        assert all((root / name).read_bytes() == payload for name, payload in prepared.writes)


@pytest.mark.parametrize('change', ['same', 'tail', 'short', 'long', 'missing', 'directory'])
def test_exact_file_comparison_checks_full_length_and_content(tmp_path, change):
    expected = bytes(range(256)) * 8193
    path = tmp_path / 'archive.bin'
    path.write_bytes(expected)
    stamp = path.stat()
    if change == 'tail':
        path.write_bytes(expected[:-1] + bytes([expected[-1] ^ 1]))
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    elif change == 'short':
        path.write_bytes(expected[:-1])
    elif change == 'long':
        path.write_bytes(expected + b'\0')
    elif change in ('missing', 'directory'):
        path.unlink()
        if change == 'directory':
            path.mkdir()
    assert overlays._file_matches_bytes(path, expected) == (change == 'same')


def test_exact_file_comparison_distinguishes_absence_empty_file_and_directory(tmp_path):
    path = tmp_path / 'target'
    assert overlays._file_matches_bytes(path, None)
    assert not overlays._file_matches_bytes(path, b'')
    path.write_bytes(b'')
    assert overlays._file_matches_bytes(path, b'')
    assert not overlays._file_matches_bytes(path, None)
    path.unlink()
    path.mkdir()
    assert not overlays._file_matches_bytes(path, None)


def test_backup_tail_corruption_refuses_before_any_publication(tmp_path):
    root, backups, prepared = prepared_rebuild(tmp_path)
    before = files_in(root)
    def backup(paths, label):
        directory = backups.backup_files(paths, description=label)
        records = json.loads((directory / 'backup_manifest.json').read_text())['files']
        saved = Path(next(row['backup_path'] for row in records if row['original_path'].endswith('0.paz')))
        stamp = saved.stat()
        with saved.open('r+b') as handle:
            handle.seek(-1, 2)
            last = handle.read(1)
            handle.seek(-1, 2)
            handle.write(bytes([last[0] ^ 1]))
        os.utime(saved, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        return directory
    with pytest.raises(ValueError, match='backup did not preserve'):
        overlays.apply_overlay_change(prepared, confirmed=True, backup=backup,
            restore_backup=backups.restore_backup, game_running=lambda: False)
    assert files_in(root) == before
