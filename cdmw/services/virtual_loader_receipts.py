"""Immutable observations of virtual sessions, never save or launch authority.

Receipts live beside existing virtual-loader bookkeeping. Their sequence links
CDMW observations, not save ancestors. File reads are bounded and read-only.
"""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
from uuid import uuid4

from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled
from cdmw.domain.new_item.independent import package_id
from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.domain.virtual_session_receipt import (
    CLAIMS, FORMAT, MAX_RECORD, MAX_RECEIPTS, decode_receipt, empty_backup,
    empty_process, seal_receipt, snapshot_identity, validate_chain,
)
from cdmw.services.independent_item_package import canonical, digest
from cdmw.services.virtual_loader_composition import hash_file
from cdmw.services.virtual_loader_saves import BACKUP_PATH, CHUNK, MAX_BYTES, MAX_FILES, _inventory, _plain
from cdmw.services.virtual_loader_state import decode, target

RECEIPT_PATH = '.cdmw/virtual-loader/session-receipts'
MAX_CHAIN_BYTES = 32 * 1024 * 1024


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _plain_ancestors(path):
    for part in (path, *path.parents):
        _plain(part)


def _directory(root, attempt, *, create=False):
    package_id(attempt)
    root = Path(root).absolute()
    _plain_ancestors(root)
    path = target(root, RECEIPT_PATH + '/' + attempt)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _plain_ancestors(path)
        if not path.is_dir():
            raise VirtualLoaderError('The session receipt location is not a directory.')
    return path


def read_session_receipts(root, attempt, *, stop_event=None):
    """Read a complete local observation chain, without looking at game saves."""
    directory = _directory(root, attempt)
    if not directory.exists():
        return ()
    entries = []
    for path in directory.iterdir():
        if len(entries) >= MAX_RECEIPTS * 2:
            raise VirtualLoaderError('The session receipt directory exceeds its size limit.')
        entries.append(path)
    files = []
    for path in entries:
        if re.fullmatch(r'[0-9]{4}\.json', path.name):
            files.append(path)
        elif not re.fullmatch(r'\.pending-[a-zA-Z0-9_-]+\.tmp', path.name):
            raise VirtualLoaderError('The session receipt directory contains an unknown entry.')
    if len(files) > MAX_RECEIPTS:
        raise VirtualLoaderError('The session receipt chain exceeds its size limit.')
    receipts, total = [], 0
    for index, path in enumerate(sorted(files)):
        raise_if_cancelled(stop_event)
        if path.name != f'{index:04d}.json' or not stat.S_ISREG(_plain(path).st_mode):
            raise VirtualLoaderError('The session receipt chain is incomplete or changed.')
        with path.open('rb') as reader:
            raw = reader.read(MAX_RECORD + 1)
        total += len(raw)
        if total > MAX_CHAIN_BYTES:
            raise VirtualLoaderError('The session receipt chain exceeds its size limit.')
        receipt = decode_receipt(raw)
        if receipt.to_dict()['attempt'] != attempt:
            raise VirtualLoaderError('The session receipt belongs to another attempt.')
        receipts.append(receipt)
    return validate_chain(receipts) if receipts else ()


def _publish(path, receipt, stop_event):
    """Publish complete bytes exclusively; a later observer cannot replace them."""
    descriptor, name = tempfile.mkstemp(prefix='.pending-', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    committed = False
    try:
        with os.fdopen(descriptor, 'wb') as writer:
            writer.write(receipt.data)
            writer.flush()
            os.fsync(writer.fileno())
        raise_if_cancelled(stop_event)
        _plain_ancestors(path.parent)
        os.link(temporary, path)
        committed = True
        # No cancellation point after publication. Preserve the committed record.
        with path.open('rb') as reader:
            raw = reader.read(MAX_RECORD + 1)
        if raw != receipt.data:
            raise VirtualLoaderError('The published session receipt failed readback.')
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            if not committed:
                raise


def _template(attempt):
    return {'format': FORMAT, 'attempt': attempt, 'sequence': 0, 'previous': None,
        'captured_utc': _now(), 'event': 'begin', 'proposed': None,
        'backup': empty_backup(), 'selected': [], 'slot_layout_sha256': None,
        'membership_complete': False, 'before': None, 'after': None,
        'process': empty_process(attempt), 'readiness': 'unknown', 'terminal': 'pending',
        'save_attempt': 'unreported', 'indicators': [], 'evidence': [], 'diagnostics': [],
        'claims': dict(CLAIMS)}


def append_observation(root, attempt, event, *, updates=None, evidence=(), diagnostics=(), stop_event=None):
    """Append one observation, preserving all earlier records on failure or races."""
    directory = _directory(root, attempt, create=True)
    for _retry in range(4):
        chain = read_session_receipts(root, attempt, stop_event=stop_event)
        if len(chain) >= MAX_RECEIPTS:
            raise VirtualLoaderError('The session receipt chain exceeds its size limit.')
        value = chain[-1].to_dict() if chain else _template(attempt)
        value.pop('identity', None)
        value.update(sequence=len(chain), previous=chain[-1].identity if chain else None,
                     captured_utc=_now(), event=event)
        value.update(updates or {})
        # These lists describe this observation. Earlier evidence remains in the
        # immutable predecessor rather than growing quadratically on every poll.
        value['evidence'] = list(evidence)
        value['diagnostics'] = list(diagnostics)
        receipt = seal_receipt(value)
        if sum(len(row.data) for row in chain) + len(receipt.data) > MAX_CHAIN_BYTES:
            raise VirtualLoaderError('The session receipt chain exceeds its size limit.')
        path = directory / f'{len(chain):04d}.json'
        try:
            _publish(path, receipt, stop_event)
            return path, receipt
        except FileExistsError:
            continue
    raise VirtualLoaderError('Another observer is updating this session receipt. Try again.')


def proposed_context(root, profile, *, stop_event=None):
    """Record the prepared proposal, not proof that the game activated it."""
    from cdmw.services.archive_overlay_manager import _load_index
    root = Path(root).resolve()
    def observed_file(relative, required=False):
        path = target(root, relative)
        if not path.exists() and not required:
            return None
        if not stat.S_ISREG(_plain(path).st_mode):
            raise VirtualLoaderError('A proposed session input is not a regular file.')
        return hash_file(path, stop_event)
    physical = {row['independent_identity']: {'digest': row['independent_digest'],
        'binding_hash': row['independent_bindings']}
        for row in (_load_index(root) or {}).get('layers', ())
        if row['active'] and row.get('independent_identity')}
    return {'generation': profile['generation'], 'profile_sha256': digest(canonical(profile)),
        'compilation_identity': profile['compilation']['identity'],
        'compiler_sha256': digest(canonical(profile['compiler'])),
        'executable_sha256': observed_file('bin64/CrimsonDesert.exe', True),
        'game_build_sha256': observed_file('meta/0.paver'),
        'runtime': {'bootstrap': observed_file('bin64/winmm.dll'),
                    'loader': observed_file('bin64/CDMWVirtualLoader.asi'), 'host': None},
        'items': profile['items'], 'physical_items': physical,
        'sources_sha256': digest(canonical(profile['sources'])),
        'underlay_sha256': digest(canonical(profile['observed']))}


def begin_attempt(root, profile, *, attempt=None, stop_event=None):
    attempt = attempt or uuid4().hex
    diagnostics = []
    try:
        proposed = proposed_context(root, profile, stop_event=stop_event)
    except RunCancelled:
        raise
    except Exception as exc:
        proposed = None
        diagnostics.append('The proposed session context could not be fully observed: ' + str(exc)[:700])
    return append_observation(root, attempt, 'begin',
        updates={'proposed': proposed, 'indicators': ['unknown-slot-membership']},
        evidence=({'kind': 'cdmw-preparation', 'sha256': digest(canonical(profile)),
                   'detail': 'Prepared profile proposal; runtime activation and save producer are unverified.'},),
        diagnostics=diagnostics, stop_event=stop_event)


def _backup_manifest(root, backup_id, manifest_sha256):
    package_id(backup_id)
    path = target(root, BACKUP_PATH + '/' + backup_id + '/manifest.json')
    _plain_ancestors(path)
    if not stat.S_ISREG(_plain(path).st_mode):
        raise VirtualLoaderError('The receipt backup manifest is not a regular file.')
    with path.open('rb') as reader:
        raw = reader.read(MAX_RECORD + 1)
    if len(raw) > MAX_RECORD or digest(raw) != manifest_sha256:
        raise VirtualLoaderError('The receipt backup manifest is unavailable or changed.')
    value = decode(raw, limit=MAX_RECORD)
    if not isinstance(value, dict) or set(value) != {
            'format', 'source', 'game_root', 'generation', 'profile_sha256', 'files'}:
        raise VirtualLoaderError('The receipt backup manifest is unsupported.')
    if value['format'] != 'cdmw_virtual_save_backup_v1' or value['game_root'] != str(Path(root).resolve()):
        raise VirtualLoaderError('The receipt backup belongs to a different installation.')
    records = value['files']
    if not isinstance(records, dict) or not 1 <= len(records) <= MAX_FILES:
        raise VirtualLoaderError('The receipt backup has unsupported file membership.')
    total, aliases = 0, set()
    for name, row in records.items():
        if not isinstance(name, str) or name.casefold() in aliases:
            raise VirtualLoaderError('The receipt backup has ambiguous file membership.')
        aliases.add(name.casefold())
        target(root, name)  # Validate spelling without taking a path from receipt JSON.
        if (not isinstance(row, dict) or set(row) != {'size', 'sha256'}
                or type(row['size']) is not int or row['size'] < 0
                or not isinstance(row['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', row['sha256'])):
            raise VirtualLoaderError('The receipt backup has invalid file fingerprints.')
        total += row['size']
    if total > MAX_BYTES:
        raise VirtualLoaderError('The receipt backup exceeds its observation size limit.')
    return value


def record_backup(root, attempt, plan, backup, *, stop_event=None):
    """Use the file facts returned by the existing verified backup publication."""
    expected = target(root, BACKUP_PATH + '/' + backup.directory.name)
    if backup.directory != expected:
        raise VirtualLoaderError('The receipt backup is outside owned recovery storage.')
    manifest = _backup_manifest(root, backup.directory.name, backup.manifest_sha256)
    records = {name: {'size': size, 'sha256': checksum} for name, size, checksum in backup.verified_files}
    if (records != manifest['files'] or not backup.observed_utc
            or manifest['source'] != str(backup.source) or manifest['generation'] != plan.generation
            or manifest['profile_sha256'] != plan.manifest_sha256):
        raise VirtualLoaderError('The receipt does not have the verified backup file facts.')
    selected = sorted(digest(name.encode()) for name in records)
    before = {'observed_utc': backup.observed_utc, 'inventory_complete': True,
        'files': {digest(name.encode()): row for name, row in records.items()}, 'missing': [], 'errors': {}}
    association = {'status': 'verified', 'backup_id': backup.directory.name,
        'manifest_sha256': backup.manifest_sha256, 'save_set_sha256': snapshot_identity(before, selected)}
    return append_observation(root, attempt, 'backup-verified',
        updates={'backup': association, 'selected': selected, 'before': before},
        evidence=({'kind': 'verified-backup', 'sha256': backup.manifest_sha256,
                   'detail': 'Exact copies and source files were verified by the existing backup publication.'},),
        stop_event=stop_event)


def launch_attempt(root, profile, attempt, *, stop_event=None):
    """A reused reviewed plan starts a new attempt, retaining its backup facts.

    The caller has just run the existing exact backup and profile verification.
    This avoids reusing a native token or overwriting a prior launch's receipts.
    """
    chain = read_session_receipts(root, attempt, stop_event=stop_event)
    reserved = any(target(root, '.cdmw/virtual-loader/launches/' + attempt + suffix).exists()
                   for suffix in ('.bin', '.log'))
    consumed = reserved or bool(chain and (chain[-1].to_dict()['terminal'] != 'pending'
        or any(row.to_dict()['event'] == 'launch-started' for row in chain)))
    if chain and not consumed:
        return attempt, None
    prior = chain[-1].to_dict() if chain else None
    if consumed:
        attempt = uuid4().hex
    captured = begin_attempt(root, profile, attempt=attempt, stop_event=stop_event)
    if (prior and prior['backup']['status'] == 'verified' and prior['proposed']
            and prior['proposed']['profile_sha256'] == digest(canonical(profile))):
        captured = append_observation(root, attempt, 'backup-verified',
            updates={key: prior[key] for key in ('backup', 'selected', 'before',
                                                'slot_layout_sha256', 'membership_complete')},
            evidence=({'kind': 'verified-backup', 'sha256': prior['backup']['manifest_sha256'],
                       'detail': 'The existing backup was reverified for this new reviewed launch attempt.'},),
            stop_event=stop_event)
    return attempt, captured


def record_launch(root, attempt, host_pid, launch_sha256, host_sha256=None):
    chain = read_session_receipts(root, attempt)
    process = chain[-1].to_dict()['process'] if chain else empty_process(attempt)
    process['host_pid'] = host_pid
    updates = {'process': process, 'readiness': 'waiting'}
    proposed = chain[-1].to_dict()['proposed'] if chain else None
    if proposed is not None and host_sha256 is not None:
        proposed['runtime']['host'] = host_sha256
        updates['proposed'] = proposed
    return append_observation(root, attempt, 'launch-started',
        updates=updates,
        evidence=({'kind': 'local-process-launch', 'sha256': launch_sha256,
                   'detail': 'CDMW started the session host; game birth, image and save producer are unverified.'},))


def record_failure(root, attempt, error, *, backup_published=None):
    chain = read_session_receipts(root, attempt)
    if not chain:
        return None
    interrupted = isinstance(error, RunCancelled)
    value = chain[-1].to_dict()
    if value['terminal'] != 'pending':
        return _directory(root, attempt) / f"{value['sequence']:04d}.json", chain[-1]
    backup = value['backup']
    if backup['status'] == 'pending':
        backup = {**backup, 'status': 'failed' if backup_published is False else 'unknown'}
    return append_observation(root, attempt, 'interrupted' if interrupted else 'failed',
        updates={'terminal': 'interrupted' if interrupted else 'failed', 'backup': backup},
        diagnostics=(str(error)[:1000] or type(error).__name__,),
        evidence=({'kind': 'cdmw-diagnostic', 'sha256': None,
                   'detail': 'CDMW preparation or launch did not complete; no save-commit claim is made.'},))


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _stable_file(path, expected_size, stop_event):
    first = _plain(path)
    if not stat.S_ISREG(first.st_mode):
        raise VirtualLoaderError('not-regular-file')
    if first.st_size != expected_size:
        raise VirtualLoaderError('changed-during-read')
    hashes = []
    for _pass in range(2):
        checksum, size = hashlib.sha256(), 0
        with path.open('rb') as reader:
            opened = os.fstat(reader.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
                    first.st_dev, first.st_ino, first.st_size, first.st_mtime_ns):
                raise VirtualLoaderError('changed-during-read')
            while block := reader.read(CHUNK):
                raise_if_cancelled(stop_event)
                size += len(block)
                if size > expected_size:
                    raise VirtualLoaderError('changed-during-read')
                checksum.update(block)
            if _stamp(os.fstat(reader.fileno())) != _stamp(opened):
                raise VirtualLoaderError('changed-during-read')
        if size != expected_size or _stamp(_plain(path)) != _stamp(first):
            raise VirtualLoaderError('changed-during-read')
        hashes.append(checksum.hexdigest())
    if hashes[0] != hashes[1]:
        raise VirtualLoaderError('changed-during-read')
    return {'size': expected_size, 'sha256': hashes[0]}


def observe_files(source, selected_paths, *, stop_event=None):
    """Observe selected members and other files without claiming an atomic save."""
    source = Path(source).absolute()
    snapshot = {'observed_utc': _now(), 'inventory_complete': False,
                'files': {}, 'missing': [], 'errors': {}}
    diagnostics = []
    try:
        inventory = _inventory(source, stop_event)
        if len({name.casefold() for name in inventory}) != len(inventory):
            raise VirtualLoaderError('Ambiguous save file spelling.')
    except RunCancelled:
        raise
    except (OSError, ValueError) as exc:
        snapshot['errors'] = {name: 'not-observed' for name in selected_paths}
        return snapshot, ['The selected save files could not be inventoried: ' + str(exc)[:700]]
    complete, additional = True, 0
    for relative, size in sorted(inventory.items()):
        name = digest(relative.encode())
        if name not in selected_paths:
            if len(selected_paths) + additional >= MAX_FILES:
                complete = False
                continue
            additional += 1
        try:
            snapshot['files'][name] = _stable_file(target(source, relative), size, stop_event)
        except RunCancelled:
            raise
        except (OSError, ValueError) as exc:
            complete = False
            if name in selected_paths:
                code = str(exc) if str(exc) in ('not-regular-file', 'changed-during-read') else 'read-failed'
                snapshot['errors'][name] = code
    for name, relative in selected_paths.items():
        if relative not in inventory:
            snapshot['missing'].append(name)
    try:
        after = _inventory(source, stop_event)
        if after != inventory:
            complete = False
            for name, relative in selected_paths.items():
                if after.get(relative) != inventory.get(relative):
                    snapshot['files'].pop(name, None)
                    if name in snapshot['missing']:
                        snapshot['missing'].remove(name)
                    snapshot['errors'][name] = 'changed-during-read'
            diagnostics.append('The save inventory changed during observation; no atomic save set was established.')
    except RunCancelled:
        raise
    except (OSError, ValueError):
        complete = False
        diagnostics.append('The final save inventory could not be observed.')
    snapshot['missing'].sort()
    snapshot['inventory_complete'] = complete
    snapshot['observed_utc'] = _now()
    return snapshot, diagnostics


def _terminal_files(root, value, stop_event):
    from cdmw.services.virtual_loader_saves import save_root
    if value['backup']['status'] != 'verified' or not value['selected']:
        return None, ['No verified selected backup is associated with this session.']
    association = value['backup']
    manifest = _backup_manifest(root, association['backup_id'], association['manifest_sha256'])
    source = save_root()
    if manifest['source'] != str(source):
        raise VirtualLoaderError('The save folder changed after the session backup.')
    proposed = value['proposed']
    if proposed is None or (manifest['generation'] != proposed['generation']
            or manifest['profile_sha256'] != proposed['profile_sha256']):
        raise VirtualLoaderError('The backup and proposed session context do not match.')
    paths = {digest(name.encode()): name for name in manifest['files']}
    if set(paths) != set(value['selected']):
        raise VirtualLoaderError('The selected backup members changed.')
    observed_before = {'observed_utc': value['before']['observed_utc'], 'inventory_complete': True,
        'files': {digest(name.encode()): row for name, row in manifest['files'].items()},
        'missing': [], 'errors': {}}
    if snapshot_identity(observed_before, value['selected']) != association['save_set_sha256']:
        raise VirtualLoaderError('The selected backup file identities changed.')
    return observe_files(source, paths, stop_event=stop_event)


def record_status(root, attempt, status, *, host_pid=None, report=None, report_sha256=None, stop_event=None):
    chain = read_session_receipts(root, attempt, stop_event=stop_event)
    if not chain:
        return None
    previous = chain[-1].to_dict()
    if previous['terminal'] != 'pending':
        return _directory(root, attempt) / f"{previous['sequence']:04d}.json", chain[-1]
    process = dict(previous['process'])
    if host_pid is not None:
        process['host_pid'] = host_pid
    if isinstance(report, dict):
        process['reported_state'] = report.get('state')
        reported_pid = report.get('pid')
        process['reported_game_pid'] = reported_pid if type(reported_pid) is int and reported_pid > 0 else None
    readiness = {'starting': 'waiting', 'running': 'reported-ready', 'tracing': 'reported-tracing',
                 'blocked': 'reported-blocked'}.get(status.state, previous['readiness'])
    terminal = {'stopped': 'stopped', 'blocked': 'blocked'}.get(status.state, 'pending')
    if (process, readiness, terminal) == (previous['process'], previous['readiness'], previous['terminal']):
        return _directory(root, attempt) / f"{previous['sequence']:04d}.json", chain[-1]
    updates = {'process': process, 'readiness': readiness, 'terminal': terminal}
    evidence = [{'kind': 'runtime-status-file', 'sha256': report_sha256,
                 'detail': 'Reported runtime state; PID existence and readiness do not establish process birth or save producer.'}]
    diagnostics = []
    if terminal != 'pending':
        try:
            after, notes = _terminal_files(root, previous, stop_event)
            updates['after'] = after
            diagnostics.extend(notes)
            if after is not None:
                evidence.append({'kind': 'local-file-observation', 'sha256': digest(canonical(after)),
                                 'detail': 'Read-only terminal file observation; changed bytes do not establish a save commit.'})
        except RunCancelled:
            raise
        except Exception as exc:
            diagnostics.append('Terminal save observation is unavailable: ' + str(exc)[:700])
        if report is None or process['reported_state'] not in ('stopped', 'blocked'):
            updates['indicators'] = sorted(set(previous['indicators']) | {'missing-events'})
    return append_observation(root, attempt, 'terminal' if terminal != 'pending' else 'runtime-status',
        updates=updates, evidence=evidence, diagnostics=diagnostics, stop_event=stop_event)


def record_status_error(root, attempt, error):
    if not read_session_receipts(root, attempt):
        return None
    return append_observation(root, attempt, 'runtime-status',
        diagnostics=('Runtime observation failed: ' + str(error)[:700],),
        evidence=({'kind': 'cdmw-diagnostic', 'sha256': None,
                   'detail': 'The status observation is incomplete; terminal outcome and producer remain unverified.'},))


def attach_receipt(status, captured=None, diagnostics=()):
    """Do not replace status.detail: starting results carry the native session token."""
    path = str(captured[0]) if captured else status.receipt_path
    receipt_notes = tuple(captured[1].to_dict()['diagnostics']) if captured else ()
    notes = tuple(dict.fromkeys((*status.diagnostics, *diagnostics, *receipt_notes)))
    return replace(status, receipt_path=path, diagnostics=notes)
