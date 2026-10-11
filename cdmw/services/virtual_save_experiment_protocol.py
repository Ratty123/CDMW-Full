"""Bounded preparation and copied-file retention for a reviewed save experiment.

This module never reads the configured live save tree, launches a game, restores
a save, changes a profile, or treats a copy checksum as producer evidence.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import stat
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.independent import package_id
from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.domain.virtual_save_evidence import (
    CLAIMS, FORMAT as CAPTURE_FORMAT, MAX_RECORD, STAGES, checksum, compare,
    encoded, seal, validate as validate_capture,
)
from cdmw.services.virtual_loader_saves import MAX_BYTES, MAX_FILES, _copy, _plain, _records
from cdmw.services.virtual_loader_state import decode as decode_json, target

FORMAT = 'cdmw_virtual_save_experiment_protocol_v1'
RETENTION_FORMAT = 'cdmw_virtual_save_attempt_copy_v1'
UNKNOWNS = {
    'slot_membership': 'unknown', 'slot_layout_sha256': None,
    'save_finalization': 'unobserved', 'producer': 'unknown',
    'produced_context': 'unknown', 'ancestry': 'unknown',
    'live_trial': 'requires_separate_review',
}
ACTIONS = (
    'Preserve the original recovery copy and record the provider-present baseline.',
    'Prepare the provider-absent profile and the copied original input before loading.',
    'After the separately authorized load-only attempt, close the game and capture its copied result.',
    'After the separately authorized save attempt, close the game, capture its copied result, then retain it.',
    'Restore the exact provider and bindings; use the retained post-attempt selected files as input.',
    'After loading that post-attempt input without saving, close the game and capture its copied result.',
)
CONTINUITY = (
    'The selected working files equal the separate retained original recovery files.',
    'The selected input equals the baseline. The provider is absent and other package identities are retained.',
    'Compare every selected member with absent_before_load; preserve autosave, failure and uncertainty.',
    'Keep changed, unchanged and missing selected members. A reported save or changed hash does not prove a writer.',
    'Match absent_saved exactly, including missing members. Never substitute the original recovery copy.',
    'Match restored_before_load exactly. Record object observations and any further file changes or load failure.',
)


def _hash(value):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None


def _text(value):
    return isinstance(value, str) and 1 <= len(value) <= 4096 and not any(ord(c) < 32 for c in value)


def _absolute(value):
    path = Path(value).absolute()
    if not _text(str(path)):
        raise VirtualLoaderError('Use bounded plain paths for the copied-save experiment.')
    return path


def _member(value):
    if not _text(value):
        raise VirtualLoaderError('Select bounded relative save-member paths.')
    parts = value.split('/')
    if (value.startswith('/') or any(part in ('', '.', '..') or ':' in part or '\\' in part
            or part.rstrip(' .') != part for part in parts)):
        raise VirtualLoaderError('Select canonical relative save-member paths using forward slashes.')
    return value


def _members(values):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 32:
        raise VirtualLoaderError('Select one to 32 copied save members.')
    result = sorted(_member(value) for value in values)
    if len({name.casefold() for name in result}) != len(result):
        raise VirtualLoaderError('Selected save-member paths contain duplicates or case aliases.')
    return result


def _directory(value):
    path = _absolute(value)
    for part in (path, *path.parents):
        _plain(part)
    if not path.is_dir():
        raise VirtualLoaderError('Copied-save inputs and output parents must be existing plain directories.')
    return path.resolve()


def _file(value):
    path = _absolute(value)
    for part in (path, *path.parents):
        _plain(part)
    if not stat.S_ISREG(path.stat().st_mode):
        raise VirtualLoaderError('An experiment input must be a plain regular file.')
    return path.resolve()


def _new_path(value):
    path = _absolute(value)
    parent = _directory(path.parent)
    result = target(parent, path.name)
    if result.exists() or result.is_symlink():
        raise VirtualLoaderError('Choose a new experiment output; existing files and folders are never replaced.')
    return result


def _overlap(left, right):
    return left.is_relative_to(right) or right.is_relative_to(left)


def _outside_live(paths):
    # Normalize lexical aliases without opening or inspecting the live tree.
    local = os.environ.get('LOCALAPPDATA', '')
    if local and Path(local).is_absolute():
        live = Path(os.path.abspath(Path(local) / 'Pearl Abyss/CD/save'))
        if any(_overlap(Path(os.path.abspath(path)), live) for path in paths):
            raise VirtualLoaderError('Use disposable copies outside the live save folder.')


def _copy_roles(root, working, original, retained, output, *, new):
    root, working, original = (_directory(path) for path in (root, working, original))
    retained = _new_path(retained) if new else target(_directory(Path(retained).parent), Path(retained).name)
    output = _new_path(output) if new else _file(output)
    roles = (root, working, original, retained)
    if any(_overlap(left, right) for index, left in enumerate(roles) for right in roles[index + 1:]):
        raise VirtualLoaderError('Game, working copy, original recovery and retained attempt must be separate folders.')
    if any(output.is_relative_to(path) for path in roles):
        raise VirtualLoaderError('Put the protocol and reports outside every game or copied-save input folder.')
    _outside_live((working, original, retained))
    return root, working, original, retained, output


def _hashed(records):
    return {checksum(name.encode('utf-8')): row for name, row in records.items()}


def _independent_members(working, original, members):
    for folder in (working, original):
        for name in members:
            path = target(folder, name)
            if path.exists() and _plain(path).st_nlink != 1:
                raise VirtualLoaderError('Selected working and original recovery members must be independent copies, without hard links.')


def _validate_records(files, *, hashed):
    if not isinstance(files, dict) or len(files) > MAX_FILES:
        raise VirtualLoaderError('The copied-save file set exceeds its supported bounds.')
    total, names = 0, set()
    for name, row in files.items():
        if (not (_hash(name) if hashed else _member(name) == name)
                or not isinstance(row, dict) or set(row) != {'size', 'sha256'}
                or type(row['size']) is not int or row['size'] < 0 or not _hash(row['sha256'])):
            raise VirtualLoaderError('Invalid copied-save member observations.')
        folded = name.casefold()
        if folded in names:
            raise VirtualLoaderError('Copied-save members contain case aliases.')
        names.add(folded)
        total += row['size']
        if total > MAX_BYTES:
            raise VirtualLoaderError('The copied-save file set exceeds its supported bounds.')


def _read_json(path):
    path = _file(path)
    with path.open('rb') as reader:
        raw = reader.read(MAX_RECORD + 1)
    if len(raw) > MAX_RECORD:
        raise VirtualLoaderError('The experiment record exceeds its size limit.')
    return raw, decode_json(raw, limit=MAX_RECORD)


def powershell_command(argv):
    """Render each argument literally, including apostrophes, dollars and backticks."""
    return '& ' + ' '.join("'" + part.replace("'", "''") + "'" for part in argv)


def capture_path(protocol, stage):
    path = Path(protocol['path'])
    return path.with_name(path.stem + '_' + str(STAGES.index(stage) + 1).zfill(2) + '_' + stage + '.json')


def _command(argv):
    return {'argv': argv, 'powershell': powershell_command(argv)}


def _commands(protocol):
    paths, baseline = protocol['paths'], protocol['baseline']
    tool = [protocol['tool']['python'], protocol['tool']['script']]
    rows = []
    for index, stage in enumerate(STAGES):
        outcome = 'prepared' if stage in ('baseline', 'absent_before_load', 'restored_before_load') else 'unknown'
        argv = tool + ['capture', '--protocol', protocol['path'], '--game-root', paths['game_root'],
            '--save-copy', paths['save_copy'], '--output', str(capture_path(protocol, stage)),
            '--stage', stage, '--provider', baseline['provider'], '--outcome', outcome,
            '--notes', 'Operator observation pending; no game result or save producer is asserted.']
        if index:
            argv += ['--previous', str(capture_path(protocol, STAGES[index - 1]))]
        else:
            for name in protocol['members']:
                argv += ['--slot', name]
        row = {'stage': stage, 'action': ACTIONS[index], 'continuity': CONTINUITY[index], **_command(argv)}
        if stage == 'absent_saved':
            row['retain_after_capture'] = _command(tool + ['retain-attempt', '--protocol', protocol['path'],
                '--capture', str(capture_path(protocol, stage))])
        rows.append(row)
    return rows


def validate_protocol(value):
    error = 'Invalid or changed copied-save experiment protocol.'
    if (not isinstance(value, dict) or set(value) != {
            'format', 'identity', 'path', 'baseline', 'paths', 'members', 'recovery_files',
            'backup', 'unknowns', 'tool', 'commands'} or value['format'] != FORMAT
            or not _hash(value['identity']) or value['unknowns'] != UNKNOWNS):
        raise VirtualLoaderError(error)
    baseline = validate_capture(value['baseline'])
    if baseline['stage'] != 'baseline':
        raise VirtualLoaderError(error)
    members = _members(value['members'])
    if (members != value['members'] or sorted(checksum(name.encode()) for name in members) != baseline['selected']
            or baseline['provider'] not in baseline['context']['items']
            or baseline['provider'] in baseline['context']['physical_items']
            or baseline['context']['provider_binding'] is None):
        raise VirtualLoaderError(error)
    paths, tool = value['paths'], value['tool']
    if (not isinstance(paths, dict) or set(paths) != {'game_root', 'save_copy', 'original_copy', 'post_attempt_copy'}
            or not isinstance(tool, dict) or set(tool) != {'python', 'script'}):
        raise VirtualLoaderError(error)
    if any(not _text(path) or not Path(path).is_absolute()
           for path in [value['path'], *paths.values(), *tool.values()]):
        raise VirtualLoaderError(error)
    _validate_records(value['recovery_files'], hashed=True)
    if any(baseline['files'].get(name) is None or baseline['files'][name] != value['recovery_files'].get(name)
           for name in baseline['selected']):
        raise VirtualLoaderError(error)
    backup = value['backup']
    if backup is not None and (not isinstance(backup, dict) or set(backup) != {
            'manifest', 'manifest_sha256', 'selected_files_sha256', 'association'}
            or backup['association'] != 'verified-selected-copy-association'
            or not _text(backup['manifest']) or not Path(backup['manifest']).is_absolute()
            or not _hash(backup['manifest_sha256']) or not _hash(backup['selected_files_sha256'])):
        raise VirtualLoaderError(error)
    if value['commands'] != _commands(value):
        raise VirtualLoaderError(error)
    raw = encoded({key: row for key, row in value.items() if key != 'identity'})
    if len(encoded(value)) > MAX_RECORD or checksum(raw) != value['identity']:
        raise VirtualLoaderError(error)
    return value


def read_protocol(path):
    _, value = _read_json(path)
    try:
        return validate_protocol(value)
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise VirtualLoaderError('Invalid or changed copied-save experiment protocol.') from exc


def inspect_receipt_file(path):
    """Inspect a bounded local receipt; never import a trusted commit witness."""
    from cdmw.domain.virtual_session_receipt import decode_receipt, inspect_receipt
    path = _file(path)
    with path.open('rb') as reader:
        raw = reader.read(MAX_RECORD + 1)
    if len(raw) > MAX_RECORD:
        raise VirtualLoaderError('The session receipt exceeds its size limit.')
    return inspect_receipt(decode_receipt(raw))


def _backup_association(manifest, expected, root, baseline, members, original, stop_event):
    if manifest is None and expected is None:
        return None
    if manifest is None or not _hash(expected):
        raise VirtualLoaderError('Supply the exact backup manifest and its SHA-256 together.')
    _outside_live((manifest, Path(manifest).parent / 'files'))
    raw, value = _read_json(manifest)
    if (checksum(raw) != expected or not isinstance(value, dict) or set(value) != {
            'format', 'source', 'game_root', 'generation', 'profile_sha256', 'files'}
            or value['format'] != 'cdmw_virtual_save_backup_v1' or not _text(value['source'])
            or value['game_root'] != str(root) or value['generation'] != baseline['context']['generation']
            or value['profile_sha256'] != baseline['context']['profile_sha256']):
        raise VirtualLoaderError('The backup manifest does not match the reviewed baseline profile.')
    _validate_records(value['files'], hashed=False)
    retained = _records(_directory(Path(manifest).parent / 'files'), stop_event)
    if retained != value['files'] or any(retained.get(name) != original.get(name) for name in members):
        raise VirtualLoaderError('The retained backup does not match the selected original recovery files.')
    if _read_json(manifest)[0] != raw:
        raise VirtualLoaderError('The retained backup manifest changed during inspection.')
    return {'manifest': str(_file(manifest)), 'manifest_sha256': expected,
            'selected_files_sha256': checksum(encoded({name: retained[name] for name in members})),
            'association': 'verified-selected-copy-association'}


def prepare_experiment(root, save_copy, original_copy, post_attempt_copy, output, *, provider, slots,
                       backup_manifest=None, backup_sha256=None, stop_event=None):
    """Resolve an operator-reviewable protocol from explicit existing copies only."""
    from cdmw.services.new_item_service import game_is_running
    from cdmw.services.virtual_loader_save_evidence import _context, _publish

    members = _members(slots)
    package_id(provider)
    root, working, original, retained, output = _copy_roles(
        root, save_copy, original_copy, post_attempt_copy, output, new=True)
    if game_is_running():
        raise VirtualLoaderError('Close the game before preparing a copied-save experiment.')
    raise_if_cancelled(stop_event)
    context = _context(root, provider, stop_event)
    working_files, original_files = _records(working, stop_event), _records(original, stop_event)
    _independent_members(working, original, members)
    _validate_records(working_files, hashed=False)
    _validate_records(original_files, hashed=False)
    if (provider not in context['items'] or provider in context['physical_items']
            or context['provider_binding'] is None
            or any(name not in working_files or working_files[name] != original_files.get(name) for name in members)):
        raise VirtualLoaderError('The baseline must select the virtual provider and matching original recovery members.')
    baseline = seal({'format': CAPTURE_FORMAT, 'experiment': uuid4().hex, 'parent': None,
        'stage': 'baseline', 'provider': provider,
        'captured_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'context': context, 'files': _hashed(working_files),
        'selected': sorted(checksum(name.encode()) for name in members),
        'observation': {'outcome': 'prepared', 'notes': 'Selected disposable copies and recovery identities prepared; no game trial observed.'},
        'claims': dict(CLAIMS)})
    backup = _backup_association(backup_manifest, backup_sha256, root, baseline, members, original_files, stop_event)
    value = {'format': FORMAT, 'path': str(output), 'baseline': baseline,
        'paths': {'game_root': str(root), 'save_copy': str(working),
                  'original_copy': str(original), 'post_attempt_copy': str(retained)},
        'members': members, 'recovery_files': _hashed(original_files), 'backup': backup,
        'unknowns': dict(UNKNOWNS), 'tool': {'python': str(Path(sys.executable).resolve()),
            'script': str(Path(__file__).resolve().parents[2] / 'scripts/capture_virtual_save_evidence.py')}}
    value['commands'] = _commands(value)
    value = seal(value)
    validate_protocol(value)
    for stage in STAGES:
        _new_path(capture_path(value, stage))
    if (_records(working, stop_event) != working_files or _records(original, stop_event) != original_files
            or _context(root, provider, stop_event) != context):
        raise VirtualLoaderError('The copied files or prepared context changed during experiment preflight.')
    if game_is_running():
        raise VirtualLoaderError('Close the game before preparing a copied-save experiment.')
    _publish(output, value, stop_event)
    return value


def _recovery(protocol, stop_event):
    _independent_members(Path(protocol['paths']['save_copy']), Path(protocol['paths']['original_copy']),
                         protocol['members'])
    original = _records(_directory(protocol['paths']['original_copy']), stop_event)
    if _hashed(original) != protocol['recovery_files']:
        raise VirtualLoaderError('The retained original recovery copy changed. Preserve it before continuing.')
    backup = protocol['backup']
    if backup is not None and _backup_association(backup['manifest'], backup['manifest_sha256'],
            Path(protocol['paths']['game_root']), protocol['baseline'], protocol['members'], original, stop_event) != backup:
        raise VirtualLoaderError('The retained backup association changed.')
    return original


def capture_parameters(protocol_path, root, save_copy, output, *, stage, provider, slots, previous, stop_event=None):
    """Bind caller-supplied paths; do not hide adverse post-action observations."""
    protocol = read_protocol(protocol_path)
    if _file(protocol_path) != Path(protocol['path']):
        raise VirtualLoaderError('Use the exact reviewed protocol path.')
    paths = protocol['paths']
    _copy_roles(paths['game_root'], paths['save_copy'], paths['original_copy'],
                paths['post_attempt_copy'], protocol['path'], new=False)
    if (stage not in STAGES or Path(root).resolve() != Path(paths['game_root'])
            or Path(save_copy).resolve() != Path(paths['save_copy'])
            or Path(output).absolute() != capture_path(protocol, stage)
            or (provider is not None and provider != protocol['baseline']['provider'])
            or (slots and _members(slots) != protocol['members'])):
        raise VirtualLoaderError('Capture parameters do not match the reviewed experiment protocol.')
    index = STAGES.index(stage)
    expected = capture_path(protocol, STAGES[index - 1]) if index else None
    if (Path(previous).absolute() if previous is not None else None) != expected:
        raise VirtualLoaderError('Use the exact previous capture named by the experiment protocol.')
    _recovery(protocol, stop_event)
    return protocol


def _chain(protocol, through):
    from cdmw.services.virtual_loader_save_evidence import read_capture
    values = [read_capture(capture_path(protocol, stage)) for stage in STAGES[:STAGES.index(through) + 1]]
    compare(values)
    if (values[0]['experiment'] != protocol['baseline']['experiment']
            or values[0]['provider'] != protocol['baseline']['provider']
            or values[0]['selected'] != protocol['baseline']['selected']
            or values[0]['context'] != protocol['baseline']['context']
            or values[0]['files'] != protocol['baseline']['files']):
        raise VirtualLoaderError('The captures do not belong to the reviewed experiment protocol.')
    return values


def _read_retained(protocol, capture, stop_event=None):
    folder = _directory(protocol['paths']['post_attempt_copy'])
    names = set()
    for path in folder.iterdir():
        if path.name not in {'manifest.json', 'files'}:
            raise VirtualLoaderError('The retained attempt contains unexpected or incomplete files.')
        names.add(path.name)
    if names != {'manifest.json', 'files'}:
        raise VirtualLoaderError('The retained attempt contains unexpected or incomplete files.')
    _, manifest = _read_json(folder / 'manifest.json')
    if (not isinstance(manifest, dict) or set(manifest) != {
            'format', 'identity', 'protocol_identity', 'capture_identity', 'files', 'selected',
            'missing_selected_files', 'claims'} or manifest['format'] != RETENTION_FORMAT
            or manifest['protocol_identity'] != protocol['identity']
            or manifest['capture_identity'] != capture['identity'] or manifest['claims'] != CLAIMS
            or manifest['selected'] != capture['selected']
            or manifest['missing_selected_files'] != sorted(set(capture['selected']) - set(capture['files']))):
        raise VirtualLoaderError('The retained attempt manifest does not match absent_saved.')
    _validate_records(manifest['files'], hashed=False)
    if (checksum(encoded({key: row for key, row in manifest.items() if key != 'identity'})) != manifest['identity']
            or _hashed(manifest['files']) != capture['files']
            or _records(_directory(folder / 'files'), stop_event) != manifest['files']):
        raise VirtualLoaderError('The retained post-attempt copied files changed.')
    return manifest


def validate_protocol_capture(protocol, value, *, stop_event=None):
    """Check pre-action identities while retaining actual post-action failures."""
    stage = value['stage']
    if (value['experiment'] != protocol['baseline']['experiment']
            or value['provider'] != protocol['baseline']['provider']
            or value['selected'] != protocol['baseline']['selected']):
        raise VirtualLoaderError('The capture identity does not match the reviewed experiment.')
    _recovery(protocol, stop_event)
    if stage == 'baseline':
        if value['context'] != protocol['baseline']['context'] or value['files'] != protocol['baseline']['files']:
            raise VirtualLoaderError('The prepared baseline changed. Prepare a new experiment protocol.')
        return
    values = _chain(protocol, STAGES[STAGES.index(stage) - 1]) + [value]
    result = compare(values)
    if stage in ('absent_before_load', 'restored_before_load'):
        relevant = {stage + suffix for suffix in (':provider', ':bindings', ':environment', ':other-packages', ':restored-context')}
        relevant |= {'absent-load-input'} if stage == 'absent_before_load' else {'restore-new-save-input', 'restore-save-attempt-input'}
        if any(not row['consistent'] for row in result['checks'] if row['check'] in relevant):
            raise VirtualLoaderError('The pre-load files or provider context do not match the experiment protocol.')
    if stage in ('restored_before_load', 'restored_loaded'):
        _read_retained(protocol, values[3], stop_event)


def _publish_retained(staged, destination, files, manifest, stop_event):
    """Publish an exclusive verified file set, then its complete marker last."""
    from cdmw.services.virtual_loader_composition import hash_file
    created_files, created_dirs = [], {}
    committed = False

    def directory(path):
        identity = created_dirs.get(path)
        if identity is not None:
            if not os.path.samestat(_plain(path), identity):
                raise VirtualLoaderError('A retained-copy output directory changed during publication.')
            return
        _directory(path.parent)
        path.mkdir()
        created_dirs[path] = _plain(path)

    try:
        directory(destination)
        directory(destination / 'files')
        for name, row in files.items():
            raise_if_cancelled(stop_event)
            relative = Path(name)
            parent = destination / 'files'
            for part in relative.parts[:-1]:
                parent /= part
                directory(parent)
            for owned in (parent, *parent.parents):
                if not owned.is_relative_to(destination):
                    break
                directory(owned)
            source, output = staged / 'files' / relative, destination / 'files' / relative
            os.link(source, output)
            created_files.append((output, source, row['sha256']))
        if _records(destination / 'files', stop_event) != files:
            raise VirtualLoaderError('The retained attempt changed before publication.')
        for owned in created_dirs:
            directory(owned)
        raise_if_cancelled(stop_event)
        expected = encoded(manifest)
        os.link(staged / 'manifest.json', destination / 'manifest.json')
        # From this point retain linked content even when final evidence is
        # unavailable. Readback failure is not a verified publication or rollback.
        committed = True
        try:
            raw, published = _read_json(destination / 'manifest.json')
            if raw != expected or published != manifest:
                raise VirtualLoaderError('The retained attempt changed before publication.')
        except (OSError, ValueError) as exc:
            raise VirtualLoaderError('Copied output is retained, but its complete manifest could not be verified. '
                                     'Preserve it for inspection: ' + str(destination)) from exc
    finally:
        if not committed:
            for output, source, expected in reversed(created_files):
                try:
                    _directory(output.parent)
                    if (stat.S_ISREG(output.lstat().st_mode) and os.path.samestat(output.stat(), source.stat())
                            and hash_file(output, None) == expected):
                        output.unlink()
                except (OSError, VirtualLoaderError):
                    pass
            for folder, identity in reversed(created_dirs.items()):
                try:
                    if os.path.samestat(folder.lstat(), identity):
                        folder.rmdir()
                except OSError:
                    pass


def retain_attempt(protocol_path, capture_path_value, *, stop_event=None):
    """Retain only a copied absent_saved observation, never a live or original save."""
    from cdmw.services.new_item_service import game_is_running

    protocol = read_protocol(protocol_path)
    paths = protocol['paths']
    root, working, original, retained, _ = _copy_roles(paths['game_root'], paths['save_copy'],
        paths['original_copy'], paths['post_attempt_copy'], protocol['path'], new=False)
    if (_file(protocol_path) != Path(protocol['path'])
            or _file(capture_path_value) != capture_path(protocol, 'absent_saved')):
        raise VirtualLoaderError('Use the exact protocol and absent_saved capture paths.')
    _new_path(retained)
    if game_is_running():
        raise VirtualLoaderError('Close the game before retaining a copied save attempt.')
    capture = _chain(protocol, 'absent_saved')[-1]
    _recovery(protocol, stop_event)
    files = _records(working, stop_event)
    _validate_records(files, hashed=False)
    if _hashed(files) != capture['files']:
        raise VirtualLoaderError('The working copy changed after absent_saved. Do not substitute another save.')
    manifest = seal({'format': RETENTION_FORMAT, 'protocol_identity': protocol['identity'],
        'capture_identity': capture['identity'], 'files': files, 'selected': capture['selected'],
        'missing_selected_files': sorted(set(capture['selected']) - set(capture['files'])),
        'claims': dict(CLAIMS)})
    if len(encoded(manifest)) > MAX_RECORD:
        raise VirtualLoaderError('The retained attempt manifest exceeds its size limit.')
    committed, diagnostics = False, []
    try:
        with TemporaryDirectory(prefix='.cdmw-save-attempt-', dir=retained.parent) as temporary:
            staged = Path(temporary)
            (staged / 'files').mkdir()
            for name, row in files.items():
                digest = _copy(target(working, name), target(staged, 'files/' + name), row['size'], stop_event)
                if digest != row['sha256']:
                    raise VirtualLoaderError('The copied save attempt changed during retention.')
            if _records(staged / 'files', stop_event) != files or _records(working, stop_event) != files:
                raise VirtualLoaderError('The copied save attempt changed during retention.')
            _recovery(protocol, stop_event)
            with (staged / 'manifest.json').open('xb') as writer:
                writer.write(encoded(manifest))
                writer.flush()
                os.fsync(writer.fileno())
            if game_is_running():
                raise VirtualLoaderError('Close the game before retaining a copied save attempt.')
            _publish_retained(staged, retained, files, manifest, stop_event)
            committed = True
    except OSError as exc:
        if not committed:
            raise
        diagnostics.append('The retained attempt was published; temporary cleanup reported: ' + str(exc))
    return {'retained_copy': str(retained), 'identity': manifest['identity'],
            'capture_identity': capture['identity'], 'missing_selected_files': manifest['missing_selected_files'],
            'claims': dict(CLAIMS), 'diagnostics': diagnostics,
            'restoration': 'Use files/ as the post-attempt input under separate live-operation review. Preserve missing members; do not fill them from the original recovery copy.'}
