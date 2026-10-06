"""Mount-list cleanup uses only owned fixtures and the real backup/restore service."""
import hashlib
import threading
from dataclasses import replace

import pytest

from cdmw.core import archive_patching
from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, PapgtDirectory, parse_papgt, serialize_papgt
from cdmw.models import RunCancelled
from cdmw.services.archive_mutation_service import ArchiveMutationService
from cdmw.services.archive_reference_cleanup import prepare_missing_reference_cleanup, apply_missing_reference_cleanup


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path / 'game'
    (root / 'meta').mkdir(parents=True)
    records = tuple(PapgtDirectory(name, PAPGT_DEFAULT_FLAGS | optional, index)
                    for index, (name, optional) in enumerate((('0037', 0), ('dmmgen', 0),
                        ('dmmsa', 0), ('0009', 0), ('0010', 0), ('0008', 1))))
    target = root / 'meta/0.papgt'
    target.write_bytes(serialize_papgt(records, header=b'head0000\x00\xab\xcd\xef'))
    for name in ('0037', '0009'):
        (root / name).mkdir()
        for extension in ('pamt', 'paz'):
            (root / name / ('0.' + extension)).write_bytes(b'owned fixture ' + name.encode())
    (root / 'dmmsa').mkdir()
    (root / 'dmmsa/leftover.txt').write_text('Keep this folder.')
    (root / '.cdmw').mkdir()
    (root / '.cdmw/independent-items.json').write_text('{"reserved":1990001}')
    monkeypatch.setattr(archive_patching, 'ARCHIVE_PATCH_BACKUP_ROOT', tmp_path / 'backups')
    return root, target, records, ArchiveMutationService()


def fingerprints(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


def test_cleanup_preserves_game_entries_payloads_identities_order_and_restores_exactly(installation):
    root, target, records, mutations = installation
    original, before = target.read_bytes(), fingerprints(root)
    prepared = prepare_missing_reference_cleanup(root)
    assert prepared.names == ('dmmgen', 'dmmsa')
    assert fingerprints(root) == before
    backup = apply_missing_reference_cleanup(prepared, confirmed=True, mutations=mutations, game_running=lambda: False)
    assert parse_papgt(target.read_bytes()) == tuple(row for row in records if row.name not in prepared.names)
    assert target.read_bytes()[:4] == original[:4] and target.read_bytes()[9:12] == original[9:12]
    after = fingerprints(root)
    assert {key: value for key, value in after.items() if key != 'meta/0.papgt'} == {
        key: value for key, value in before.items() if key != 'meta/0.papgt'}
    assert not prepare_missing_reference_cleanup(root).names
    mutations.restore_backup(backup, confirmed=True)
    assert fingerprints(root) == before


@pytest.mark.parametrize('change', ['list', 'index', 'game_entry'])
def test_changed_or_unreviewed_inputs_are_refused_before_backup(installation, change):
    root, target, records, mutations = installation
    prepared = prepare_missing_reference_cleanup(root)
    if change == 'list':
        target.write_bytes(serialize_papgt(records[::-1]))
    elif change == 'index':
        (root / 'dmmgen').mkdir()
        (root / 'dmmgen/0.pamt').write_bytes(b'reappeared')
    else:
        prepared = replace(prepared, names=('0010',))
    before = fingerprints(root)
    with pytest.raises(ValueError, match='changed'):
        apply_missing_reference_cleanup(prepared, confirmed=True, mutations=mutations, game_running=lambda: False)
    assert fingerprints(root) == before
    assert not mutations.backup_root.exists()


@pytest.mark.parametrize('when', ['before_backup', 'during_backup'])
@pytest.mark.parametrize('change', ['cancel', 'index', 'list', 'running'])
def test_cleanup_rechecks_cancellation_game_and_inputs_at_backup_boundary(installation, monkeypatch, when, change):
    root, target, records, mutations = installation
    prepared = prepare_missing_reference_cleanup(root)
    stop, running = threading.Event(), []
    expected = []
    def change_input():
        if change == 'cancel':
            stop.set()
        elif change == 'running':
            running.append(True)
        elif change == 'index':
            (root / 'dmmgen').mkdir()
            (root / 'dmmgen/0.pamt').write_bytes(b'reappeared')
        else:
            target.write_bytes(serialize_papgt(records[::-1]))
        expected.append(fingerprints(root))
    if when == 'before_backup':
        change_input()
    else:
        original_backup = ArchiveMutationService.backup_files
        def backup(self, *args, **kwargs):
            result = original_backup(self, *args, **kwargs)
            change_input()
            return result
        monkeypatch.setattr(ArchiveMutationService, 'backup_files', backup)
    error = RunCancelled if change == 'cancel' else RuntimeError if change == 'running' else ValueError
    with pytest.raises(error):
        apply_missing_reference_cleanup(prepared, confirmed=True, mutations=mutations,
                                        game_running=lambda: bool(running), stop_event=stop)
    assert fingerprints(root) == expected[-1]


def test_publication_failure_restores_verified_original(installation, monkeypatch):
    from cdmw.services import archive_reference_cleanup as cleanup
    root, target, _records, mutations = installation
    prepared, before = prepare_missing_reference_cleanup(root), fingerprints(root)
    def failed_write(path, payload):
        path.write_bytes(payload)
        raise OSError('fixture publication failure')
    monkeypatch.setattr(cleanup, 'atomic_write_bytes', failed_write)
    with pytest.raises(OSError, match='fixture publication failure'):
        apply_missing_reference_cleanup(prepared, confirmed=True, mutations=mutations, game_running=lambda: False)
    assert fingerprints(root) == before


def test_confirmation_and_verified_backup_are_required(installation, monkeypatch):
    root, _target, _records, mutations = installation
    prepared, before = prepare_missing_reference_cleanup(root), fingerprints(root)
    with pytest.raises(PermissionError):
        apply_missing_reference_cleanup(prepared, confirmed=False, mutations=mutations, game_running=lambda: False)
    monkeypatch.setattr(ArchiveMutationService, 'backup_files', lambda *_args, **_kwargs: root / 'invalid-backup')
    with pytest.raises(ValueError, match='backup manifest'):
        apply_missing_reference_cleanup(prepared, confirmed=True, mutations=mutations, game_running=lambda: False)
    assert fingerprints(root) == before
