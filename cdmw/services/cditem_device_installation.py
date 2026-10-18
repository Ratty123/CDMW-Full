"""Exact rollback of four existing CDMW files for development device tests.

Preparation only retains before/after bytes. Installation still belongs to the
supported profile publisher and runtime setup services. No archive is written.
"""
from dataclasses import dataclass
from pathlib import Path
import os
import re
import time

from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.services import cditem_device_saves as saves
from cdmw.services.cditem_device_live_saves import _native_processes
from cdmw.services.independent_item_package import canonical, digest
from cdmw.services.installation_lane import installation_lane
from cdmw.services.virtual_loader_state import decode, target

FORMAT = 'cdmw_cditem_installation_recovery_v1'
FILES = ('.cdmw/virtual-loader/profile.json', '.cdmw/independent-items.json',
         'bin64/CDMWVirtualLoader.asi', '.cdmw/virtual-loader/runtime-owner.json')
LIMIT = 64 * 1024 * 1024


@dataclass(frozen=True)
class InstallationRecovery:
    directory: Path
    manifest_sha256: str


def _raw(path):
    path = saves._absolute(path)
    if not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size > LIMIT:
        raise VirtualLoaderError('Installation recovery requires bounded independent regular files.')
    with path.open('rb') as source:
        raw = source.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise VirtualLoaderError('Installation recovery file grew beyond its size limit.')
    return raw


def _quiet(root):
    census = _native_processes()  # Failing/incomplete native enumeration refuses.
    if (any(name.casefold() in {'crimsondesert.exe', 'cdmw_virtual_session.exe'}
            or re.fullmatch('[a-f0-9]{64}\\.exe', name.casefold()) for _, _, name in census)
            or target(root, '.cdmw/virtual-loader/transaction.json').exists()):
        raise VirtualLoaderError('Settle the game and supported profile transaction before installation recovery.')


def prepare_installation_recovery(root, directory, *, run_id, proposed):
    """Pin exact proposed bytes before supported setup; changes no installed file."""
    root, directory = saves._absolute(root), saves._offline(directory)
    if (not re.fullmatch('[A-Za-z0-9_-]{8,96}', run_id)
            or set(proposed) != set(FILES) or not directory.parent.is_dir()
            or saves._overlap(root, directory)
            or any(not isinstance(raw, bytes) or len(raw) > LIMIT for raw in proposed.values())):
        raise VirtualLoaderError('Invalid exact CDMW installation recovery request.')
    with installation_lane(root):
        _quiet(root)
        before = {name: _raw(target(root, name)) for name in FILES}
        metadata = {name: target(root, name).stat().st_mtime_ns for name in FILES}
        directory.mkdir()
        records = {}
        for index, name in enumerate(FILES):
            records[name] = {'mtime_ns': metadata[name]}
            for side, raw in (('before', before[name]), ('after', proposed[name])):
                path = directory / side / str(index)
                path.parent.mkdir(exist_ok=True)
                with path.open('xb') as writer:
                    writer.write(raw)
                    writer.flush()
                    os.fsync(writer.fileno())
                if _raw(path) != raw:
                    raise VirtualLoaderError('Installation recovery readback failed.')
                records[name][side] = {'sha256': digest(raw), 'size': len(raw)}
        if any(_raw(target(root, name)) != raw for name, raw in before.items()):
            raise VirtualLoaderError('Installed CDMW files changed during recovery preparation.')
        manifest = {'format': FORMAT, 'run_id': run_id, 'root': str(root), 'files': records}
        raw = canonical(manifest)
        atomic_write_bytes(directory / 'manifest.json', raw)
        context = InstallationRecovery(directory, digest(raw))
        _journal(context, 'prepared')
        return context


def _journal(context, phase):
    atomic_write_bytes(context.directory / 'journal.json', canonical({
        'format': FORMAT, 'manifest_sha256': context.manifest_sha256, 'phase': phase}))


def _load(context):
    directory = saves._offline(context.directory)
    raw = saves._read(directory / 'manifest.json')
    if digest(raw) != context.manifest_sha256:
        raise VirtualLoaderError('Installation recovery manifest changed.')
    manifest = decode(raw)
    if (not isinstance(manifest, dict) or set(manifest) != {'format', 'run_id', 'root', 'files'}
            or manifest['format'] != FORMAT or set(manifest['files']) != set(FILES)
            or not re.fullmatch('[A-Za-z0-9_-]{8,96}', manifest['run_id'])):
        raise VirtualLoaderError('Unsupported installation recovery manifest.')
    root = saves._absolute(manifest['root'])
    if saves._overlap(root, directory):
        raise VirtualLoaderError('Installation recovery cannot overlap the game root.')
    journal = decode(saves._read(directory / 'journal.json'))
    if (not isinstance(journal, dict) or set(journal) != {'format', 'manifest_sha256', 'phase'}
            or journal['format'] != FORMAT or journal['manifest_sha256'] != context.manifest_sha256
            or journal['phase'] not in {'prepared', 'applied', 'restoring', 'restored'}):
        raise VirtualLoaderError('Invalid installation recovery journal.')
    values = {}
    for index, name in enumerate(FILES):
        row = manifest['files'][name]
        if set(row) != {'mtime_ns', 'before', 'after'} or type(row['mtime_ns']) is not int:
            raise VirtualLoaderError('Invalid installation recovery file metadata.')
        values[name] = {}
        for side in ('before', 'after'):
            raw = _raw(directory / side / str(index))
            if row[side] != {'sha256': digest(raw), 'size': len(raw)}:
                raise VirtualLoaderError('Installation recovery bytes changed; preserve installed state.')
            values[name][side] = raw
    return root, manifest, journal, values


def verify_installation_recovery(context, *, applied=False):
    """Read current bytes, never install or recover them."""
    root, manifest, journal, values = _load(context)
    observed = {}
    for name, sides in values.items():
        current = _raw(target(root, name))
        if applied and current != sides['after']:
            raise VirtualLoaderError('Supported setup did not produce the exact reviewed CDMW files.')
        if current not in sides.values():
            raise VirtualLoaderError('An installed CDMW file changed outside this run; preserve it.')
        observed[name] = digest(current)
    return {'run_id': manifest['run_id'], 'phase': journal['phase'], 'files': observed}


def seal_installation_recovery(context):
    """Record exact supported setup output; does not perform that setup."""
    root, _, _, _ = _load(context)
    with installation_lane(root), installation_lane(context.directory):
        _quiet(root)
        if _load(context)[2]['phase'] not in {'prepared', 'applied'}:
            raise VirtualLoaderError('A completed or interrupted recovery cannot be reopened for setup.')
        result = verify_installation_recovery(context, applied=True)
        _journal(context, 'applied')
        return result


def restore_installation_recovery(context):
    """Restore known bytes, rechecking ownership after brief Windows file locks."""
    root, _, _, _ = _load(context)
    with installation_lane(root), installation_lane(context.directory):
        _quiet(root)
        root, manifest, journal, values = _load(context)
        verify_installation_recovery(context)  # Check every target before any write.
        if journal['phase'] == 'restored':
            if any(_raw(target(root, name)) != sides['before'] for name, sides in values.items()):
                raise VirtualLoaderError('This completed recovery belongs to an earlier run; preserve the later setup.')
            return verify_installation_recovery(context)
        _journal(context, 'restoring')
        for name, sides in values.items():
            path = target(root, name)
            if _raw(path) not in sides.values():
                raise VirtualLoaderError('An installation recovery target changed; preserve remaining files.')
            if _raw(path) != sides['before']:
                for attempt in range(10):
                    try:
                        atomic_write_bytes(path, sides['before'])
                        break
                    except OSError as error:
                        if getattr(error, 'winerror', None) not in {5, 32, 33} or attempt == 9:
                            raise
                        time.sleep(0.2)
                        _quiet(root)
                        verify_installation_recovery(context)
                        if _raw(path) == sides['before']:
                            break
            stamp = manifest['files'][name]['mtime_ns']
            os.utime(path, ns=(stamp, stamp))
        if any(_raw(target(root, name)) != sides['before'] for name, sides in values.items()):
            raise VirtualLoaderError('Installation recovery readback failed; retain all recovery files.')
        _journal(context, 'restored')
        return verify_installation_recovery(context)
