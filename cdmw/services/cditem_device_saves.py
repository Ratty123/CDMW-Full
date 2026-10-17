"""Journaled save-context rehearsal on independent, offline copied fixtures.

This does not establish live-game or Steam Cloud containment. Every mutation
refuses the configured live save tree (including its ancestors and children).
The caller owns the fixture and supplies fresh process/writer quiescence evidence.
Originals, experiment inputs and outputs remain separate independent files.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import stat

from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.services.independent_item_package import canonical, digest
from cdmw.services.installation_lane import installation_lane
from cdmw.services import virtual_loader_saves as saves
from cdmw.services.virtual_loader_state import decode, target

FORMAT = 'cdmw_cditem_offline_save_context_v1'
LIMIT = 4 * 1024 * 1024
LIVE_BLOCKER = 'Live save routing and Steam Cloud/writer containment have not been verified.'


@dataclass(frozen=True)
class OfflineSaveContext:
    directory: Path
    manifest_sha256: str


def _absolute(path):
    path = Path(path)
    if not path.is_absolute():
        raise VirtualLoaderError('Save-context paths must be absolute.')
    if os.name == 'nt' and str(path).startswith(('\\\\?\\', '\\\\.\\')):
        raise VirtualLoaderError('Offline save contexts do not support Windows device paths.')
    path = Path(os.path.abspath(path))
    # Check the supplied spelling before canonicalization, which would otherwise
    # hide a reparse point. Then canonicalize 8.3 aliases for overlap/owner keys.
    for candidate in (path, path.resolve()):
        for item in (candidate, *candidate.parents):
            try:
                info = saves._plain(item)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise VirtualLoaderError('Save contexts do not support hard links.')
    return path.resolve()


def _overlap(a, b):
    return a.is_relative_to(b) or b.is_relative_to(a)


def _offline(path):
    path = _absolute(path)
    if _overlap(path, _absolute(saves.save_root())):
        raise VirtualLoaderError('Offline save rehearsal cannot mutate the live save tree.')
    return path


def _metadata(root):
    result, pending = {}, [root]
    while pending:
        directory = pending.pop()
        info = saves._plain(directory)
        name = directory.relative_to(root).as_posix()
        result[name] = info.st_mtime_ns
        if len(result) > saves.MAX_FILES * 2:
            raise VirtualLoaderError('The save folder exceeds the supported backup size or file count.')
        for path in directory.iterdir():
            item = saves._plain(path)
            if stat.S_ISDIR(item.st_mode):
                pending.append(path)
            elif item.st_nlink != 1:
                raise VirtualLoaderError('Save contexts do not support hard links.')
    return dict(sorted(result.items()))


def snapshot_offline_root(root, *, stop_event=None):
    """Read a bounded whole-tree state, including empty directories and mtimes."""
    root = _absolute(root)
    if not root.exists():
        return {'exists': False, 'directories': {}, 'files': {}}
    if not root.is_dir():
        raise VirtualLoaderError('The save-context root must be a directory.')
    directories = _metadata(root)
    records = saves._records(root, stop_event)
    files = {name: {**row, 'mtime_ns': target(root, name).stat().st_mtime_ns}
             for name, row in records.items()}
    if (_metadata(root) != directories or saves._records(root, stop_event) != records
            or any(target(root, name).stat().st_mtime_ns != row['mtime_ns']
                   for name, row in files.items())):
        raise VirtualLoaderError('The save-context files changed during inspection.')
    return {'exists': True, 'directories': directories, 'files': files}


def _expect(root, expected, stop_event=None):
    observed = snapshot_offline_root(root, stop_event=stop_event)
    if observed != expected:
        raise VirtualLoaderError('Unexpected save-context state; retained files were not overwritten.')
    return observed


def _copy_snapshot(source, destination, expected, stop_event):
    if not expected['exists']:
        return
    destination.mkdir()
    for name in expected['directories']:
        if name != '.':
            target(destination, name).mkdir(parents=True, exist_ok=True)
    for name, row in expected['files'].items():
        copied = saves._copy(target(source, name), target(destination, name), row['size'], stop_event)
        if copied != row['sha256']:
            raise VirtualLoaderError('The save-context copy changed during preparation.')
        os.utime(target(destination, name), ns=(row['mtime_ns'], row['mtime_ns']))
    for name in sorted(expected['directories'], key=lambda v: v.count('/'), reverse=True):
        path = destination if name == '.' else target(destination, name)
        stamp = expected['directories'][name]
        os.utime(path, ns=(stamp, stamp))
    _expect(source, expected, stop_event)
    _expect(destination, expected, stop_event)


def _quiet(check):
    witness = check()
    if (not isinstance(witness, dict) or set(witness) != {'processes', 'writers', 'evidence'}
            or witness['processes'] != [] or witness['writers'] != []
            or not isinstance(witness['evidence'], str) or not witness['evidence'].strip()
            or len(witness['evidence']) > 4096):
        raise VirtualLoaderError('Fresh, empty process/writer inventories are required for save exchange.')
    return witness


def _read(path):
    saves._plain(path)
    if path.stat().st_size > LIMIT:
        raise VirtualLoaderError('The save-context journal exceeds its size limit.')
    return path.read_bytes()


def _load(context):
    directory = _offline(context.directory)
    raw = _read(directory / 'manifest.json')
    if digest(raw) != context.manifest_sha256:
        raise VirtualLoaderError('The save-context manifest changed.')
    manifest = decode(raw, limit=LIMIT)
    if (not isinstance(manifest, dict) or set(manifest) != {
            'format', 'offline_root', 'original', 'intended', 'live_ready'}
            or manifest['format'] != FORMAT or manifest['live_ready'] is not False):
        raise VirtualLoaderError('Unsupported offline save context.')
    root = _offline(manifest['offline_root'])
    if _overlap(root, directory):
        raise VirtualLoaderError('Save-context storage overlaps the fixture.')
    journal = decode(_read(directory / 'journal.json'), limit=LIMIT)
    if (not isinstance(journal, dict) or set(journal) != {
            'format', 'manifest_sha256', 'expected_current', 'output_state',
            'output_directory', 'phase', 'observed', 'quiescence'}
            or journal.get('format') != FORMAT
            or journal.get('manifest_sha256') != context.manifest_sha256
            or journal.get('phase') not in {'preparing', 'prepared', 'exchanging', 'active',
                                          'restoring', 'recovering', 'restored'}
            or journal.get('output_directory') not in (None, 'output')
            or journal.get('expected_current') not in (manifest['intended'], journal.get('output_state'))):
        raise VirtualLoaderError('Invalid save-context recovery journal.')
    return directory, root, manifest, journal


def _journal(directory, journal, phase, *, observed=None, witness=None):
    journal['phase'] = phase
    if observed is not None:
        journal['observed'] = observed
    if witness is not None:
        journal['quiescence'] = witness
    atomic_write_bytes(directory / 'journal.json', canonical(journal))


def _owner_path(root):
    key = digest(str(root).casefold().encode('utf-8'))[:24]
    return root.parent / ('.cdmw-offline-save-' + key + '.json')


def _owner(context):
    return {'format': FORMAT, 'directory': str(context.directory),
            'manifest_sha256': context.manifest_sha256}


def _check_owner(root, context=None, *, required=False):
    path = _owner_path(root)
    _absolute(path)
    if not path.exists():
        if required:
            raise VirtualLoaderError('The active save-context ownership record is missing; preserve all trees.')
        return False
    if context is None or decode(_read(path), limit=LIMIT) != _owner(context):
        raise VirtualLoaderError('Recover the active owned save context before preparing another exchange.')
    return True


def _claim(root, context):
    _check_owner(root)
    # The installation lane serializes claims; publish only a complete owner.
    # Creating the final path before writing it left a zero-byte claim on crash.
    atomic_write_bytes(_owner_path(root), canonical(_owner(context)))


def _release(root, context):
    if _check_owner(root, context):
        _owner_path(root).unlink()


def prepare_offline_context(offline_root, test_root, directory, *, quiescence, stop_event=None):
    """Prepare a whole copied fixture; never exchanges it or touches live saves."""
    root, test, directory = _offline(offline_root), _offline(test_root), _offline(directory)
    if any(_overlap(a, b) for a, b in ((root, test), (root, directory), (test, directory))):
        raise VirtualLoaderError('Save-context inputs and storage must be separate trees.')
    if not root.parent.is_dir() or not directory.parent.is_dir() or not test.is_dir():
        raise VirtualLoaderError('Save-context parents and the disposable input must exist.')
    if root.parent.stat().st_dev != directory.parent.stat().st_dev:
        raise VirtualLoaderError('Offline exchange requires storage on the fixture volume.')
    with installation_lane(root):
        _check_owner(root)
        witness = _quiet(quiescence)
        original = snapshot_offline_root(root, stop_event=stop_event)
        intended = snapshot_offline_root(test, stop_event=stop_event)
        directory.mkdir()
        manifest = {'format': FORMAT, 'offline_root': str(root), 'original': original,
                    'intended': intended, 'live_ready': False}
        raw = canonical(manifest)
        context = OfflineSaveContext(directory, digest(raw))
        atomic_write_bytes(directory / 'manifest.json', raw)
        journal = {'format': FORMAT, 'manifest_sha256': context.manifest_sha256,
                   'expected_current': intended, 'output_state': None, 'output_directory': None}
        _journal(directory, journal, 'preparing', observed=original, witness=witness)
        _copy_snapshot(root, directory / 'original', original, stop_event)
        _copy_snapshot(test, directory / 'input', intended, stop_event)
        _quiet(quiescence)
        _expect(root, original, stop_event)
        raise_if_cancelled(stop_event)
        _journal(directory, journal, 'prepared')
        return context


def inspect_offline_context(context):
    directory, root, manifest, journal = _load(context)
    return {'phase': journal['phase'], 'offline_root': str(root), 'live_ready': False,
            'live_blocker': LIVE_BLOCKER, 'original': manifest['original'],
            'intended': manifest['intended'], 'observed': journal.get('observed'),
            'output_directory': journal.get('output_directory'), 'directory': str(directory)}


def exchange_offline_context(context, *, quiescence, stop_event=None):
    directory, root, manifest, journal = _load(context)
    with installation_lane(root):
        directory, root, manifest, journal = _load(context)
        if journal['phase'] != 'prepared':
            raise VirtualLoaderError('Recover the unfinished save context before another exchange.')
        _check_owner(root)
        _quiet(quiescence)
        _expect(directory / 'original', manifest['original'], stop_event)
        _expect(directory / 'input', manifest['intended'], stop_event)
        absent = {'exists': False, 'directories': {}, 'files': {}}
        _expect(directory / 'parked-original', absent, stop_event)
        _expect(directory / 'parked-test', absent, stop_event)
        _expect(root, manifest['original'], stop_event)
        _copy_snapshot(directory / 'input', directory / 'staged-test', manifest['intended'], stop_event)
        witness = _quiet(quiescence)
        _expect(root, manifest['original'], stop_event)
        raise_if_cancelled(stop_event)
        _journal(directory, journal, 'exchanging', observed=manifest['original'], witness=witness)
        _claim(root, context)
        if manifest['original']['exists']:
            root.rename(directory / 'parked-original')
        # No cancellation inside the two-rename publication. The durable journal
        # and parked original permit recovery even if the interpreter terminates.
        (directory / 'staged-test').rename(root)
        _journal(directory, journal, 'active', observed=snapshot_offline_root(root))


def retain_offline_outputs(context, expected_current, *, quiescence, stop_event=None):
    """Seal explicitly observed outputs before restoration; hashes do not prove lineage."""
    directory, root, manifest, journal = _load(context)
    with installation_lane(root):
        directory, root, manifest, journal = _load(context)
        if journal['phase'] != 'active' or journal['output_directory'] is not None:
            raise VirtualLoaderError('The offline save context is not awaiting experiment outputs.')
        _check_owner(root, context, required=True)
        witness = _quiet(quiescence)
        _expect(root, expected_current, stop_event)
        _copy_snapshot(root, directory / 'output', expected_current, stop_event)
        _quiet(quiescence)
        _expect(root, expected_current, stop_event)
        raise_if_cancelled(stop_event)
        journal.update(expected_current=expected_current, output_state=expected_current,
                       output_directory='output')
        _journal(directory, journal, 'active', observed=expected_current, witness=witness)
        return directory / 'output'


def restore_offline_context(context, *, quiescence, stop_event=None):
    """Restore only the exact expected fixture; unknown writes are retained/refused."""
    directory, root, manifest, journal = _load(context)
    with installation_lane(root):
        directory, root, manifest, journal = _load(context)
        if journal['phase'] != 'active':
            raise VirtualLoaderError('Recover the unfinished save context before restoring it.')
        _check_owner(root, context, required=True)
        _restore(directory, root, manifest, journal, quiescence, stop_event)
        _release(root, context)


def _restore(directory, root, manifest, journal, quiescence, stop_event):
    _quiet(quiescence)
    _expect(directory / 'original', manifest['original'], stop_event)
    _expect(directory / 'parked-original', manifest['original'], stop_event)
    _expect(root, journal['expected_current'], stop_event)
    if journal['output_state'] is not None:
        _expect(directory / 'output', journal['output_state'], stop_event)
    _expect(directory / 'parked-test', {'exists': False, 'directories': {}, 'files': {}}, stop_event)
    witness = _quiet(quiescence)
    _expect(root, journal['expected_current'], stop_event)
    raise_if_cancelled(stop_event)
    _journal(directory, journal, 'restoring', observed=journal['expected_current'], witness=witness)
    if journal['expected_current']['exists']:
        root.rename(directory / 'parked-test')
    if manifest['original']['exists']:
        (directory / 'parked-original').rename(root)
    _journal(directory, journal, 'restored', observed=_expect(root, manifest['original']))


def recover_offline_context(context, *, quiescence, stop_event=None):
    """Recover an interrupted owned rehearsal, refusing every unknown current tree."""
    directory, root, manifest, journal = _load(context)
    with installation_lane(root):
        directory, root, manifest, journal = _load(context)
        _check_owner(root, context)
        witness = _quiet(quiescence)
        current = snapshot_offline_root(root, stop_event=stop_event)
        parked_original = snapshot_offline_root(directory / 'parked-original', stop_event=stop_event)
        parked_test = snapshot_offline_root(directory / 'parked-test', stop_event=stop_event)
        absent = {'exists': False, 'directories': {}, 'files': {}}
        original, expected = manifest['original'], journal['expected_current']
        if current == original and parked_original == absent and parked_test in (absent, expected):
            _journal(directory, journal, 'restored', observed=current, witness=witness)
        elif current == expected and parked_original == original and parked_test == absent:
            _check_owner(root, context, required=True)
            _restore(directory, root, manifest, journal, quiescence, stop_event)
        elif (current == absent and parked_original == original
              and parked_test in (absent, expected)):
            _check_owner(root, context, required=True)
            _expect(directory / 'original', original, stop_event)
            _quiet(quiescence)
            _expect(root, absent, stop_event)
            raise_if_cancelled(stop_event)
            _journal(directory, journal, 'recovering', observed=current, witness=witness)
            if original['exists']:
                (directory / 'parked-original').rename(root)
            _journal(directory, journal, 'restored', observed=_expect(root, original))
        else:
            raise VirtualLoaderError('Unknown concurrent save state; preserve all trees and investigate before recovery.')
        _release(root, context)
        return inspect_offline_context(context)
