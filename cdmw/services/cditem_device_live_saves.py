"""Explicit, evidence-bound live save exchange for the development device runner.

Known application writers must be normally stopped. This does not claim an OS
barrier against arbitrary local writers; actual unexpected states are preserved.
No function launches/stops a process or changes Steam's Cloud setting.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re

from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.domain.virtual_session_receipt import decode_receipt
from cdmw.services import cditem_device_saves as transaction
from cdmw.services.virtual_loader_receipts import read_session_receipts
from cdmw.services.independent_item_package import canonical, digest
from cdmw.services.installation_lane import installation_lane
from cdmw.services.virtual_loader_composition import hash_file
from cdmw.services.virtual_loader_state import decode

FORMAT = 'cdmw_cditem_live_save_context_v1'
REQUEST = 'cdmw_cditem_live_save_request_v1'
SHUTDOWN = 'cdmw_cditem_steam_shutdown_v1'
PREFIX = '.cdmw-live-save-'
APP_ID = '3321460'
ABSENT = {'exists': False, 'directories': {}, 'files': {}}


@dataclass(frozen=True)
class LiveSaveContext:
    directory: Path
    manifest_sha256: str


def _error(message):
    raise VirtualLoaderError(message)


def _hash(value):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None


def _reference(value):
    if not isinstance(value, dict) or set(value) != {'path', 'sha256'} or not _hash(value['sha256']):
        _error('A bounded, exact evidence path/hash is required for live save containment.')
    path = transaction._absolute(value['path'])
    raw = transaction._read(path)
    if digest(raw) != value['sha256']:
        _error('Live save evidence changed; preserve the current context.')
    return raw


def _json_reference(value):
    return decode(_reference(value), limit=transaction.LIMIT)


def _vdf(raw):
    """Read bounded quoted KeyValues; never expose unrelated account fields."""
    text = raw.decode('utf-8-sig')
    tokens, position = [], 0
    pattern = re.compile(r'\s*(?:"((?:\\.|[^"\\])*)"|([{}]))')
    while position < len(text):
        match = pattern.match(text, position)
        if match is None:
            if text[position:].strip():
                _error('Unsupported Steam configuration syntax.')
            break
        tokens.append(match.group(2) or re.sub(r'\\([\\"])', r'\1', match.group(1)))
        position = match.end()
    index = 0
    def object_(nested=False):
        nonlocal index
        result = {}
        while index < len(tokens):
            key = tokens[index]
            index += 1
            if key == '}':
                if not nested:
                    _error('Invalid Steam configuration structure.')
                return result
            if key == '{' or index >= len(tokens) or key.casefold() in result:
                _error('Invalid or duplicate Steam configuration field.')
            value = tokens[index]
            index += 1
            result[key.casefold()] = object_(True) if value == '{' else value
        if nested:
            _error('Incomplete Steam configuration structure.')
        return result
    return object_()


def _field(value, *names):
    for name in names:
        if not isinstance(value, dict):
            return None
        value = value.get(name.casefold())
    return value


def _known_save_root():
    if os.name != 'nt':
        _error('Live Crimson Desert save containment requires Windows.')
    import ctypes as C
    from ctypes import wintypes as W
    function = C.WinDLL('shell32').SHGetFolderPathW
    function.argtypes = [W.HWND, C.c_int, W.HANDLE, W.DWORD, W.LPWSTR]
    function.restype = C.c_long
    output = C.create_unicode_buffer(32768)
    if function(None, 0x1c, None, 0, output) != 0:
        _error('The native Windows LocalAppData save root could not be established.')
    native = transaction._absolute(Path(output.value) / 'Pearl Abyss/CD/save')
    if native != transaction._absolute(transaction.saves.save_root()):
        _error('The native Windows save root and configured save root disagree.')
    return native


def _native_processes():
    """Strict Toolhelp inventory: errors must never turn into an empty census."""
    if os.name != 'nt':
        _error('Native writer census requires Windows.')
    import ctypes as C
    from ctypes import wintypes as W
    class Entry(C.Structure):
        _fields_ = [('size', W.DWORD), ('usage', W.DWORD), ('pid', W.DWORD),
                    ('heap', C.c_size_t), ('module', W.DWORD), ('threads', W.DWORD),
                    ('parent', W.DWORD), ('priority', W.LONG), ('flags', W.DWORD),
                    ('name', W.WCHAR * 260)]
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = W.HANDLE
    for name in ('Process32FirstW', 'Process32NextW'):
        function = getattr(kernel, name)
        function.argtypes = [W.HANDLE, C.POINTER(Entry)]
        function.restype = W.BOOL
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.CloseHandle.restype = W.BOOL
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == C.c_void_p(-1).value:
        _error('Cannot enumerate known save/Cloud writers.')
    rows = []
    try:
        entry = Entry()
        entry.size = C.sizeof(entry)
        if not kernel.Process32FirstW(handle, C.byref(entry)):
            _error('Cannot start the known-writer process census.')
        while True:
            rows.append((entry.pid, entry.parent, entry.name))
            if not kernel.Process32NextW(handle, C.byref(entry)):
                if C.get_last_error() != 18:
                    _error('The native known-writer census was incomplete.')
                break
    finally:
        kernel.CloseHandle(handle)
    if not rows or os.getpid() not in {row[0] for row in rows}:
        _error('The known-writer census did not include this runner.')
    return rows


def _process_identity(pid):
    from cdmw.services.cditem_device_windows import process_identity
    return asdict(process_identity(pid))


def _identity(value, executable, checksum):
    if (not isinstance(value, dict) or set(value) != {
            'pid', 'created', 'executable', 'executable_sha256', 'session'}
            or type(value['pid']) is not int or value['pid'] <= 0
            or type(value['created']) is not int or value['created'] <= 0
            or type(value['session']) is not int or value['session'] < 0
            or transaction._absolute(value['executable']) != executable
            or value['executable_sha256'] != checksum):
        _error('The live save receipt has an invalid process path, birth or fingerprint.')
    return value


def _closed(request, shutdown, owned_game):
    steam = Path(request['steam_root']) / 'steam.exe'
    _identity(shutdown.get('steam_process'), steam, request['steam_sha256'])
    if (shutdown.get('format') != SHUTDOWN or shutdown.get('run_id') != request['run_id']
            or shutdown.get('method') != 'normal_ui_exit'
            or shutdown.get('game_process') != owned_game):
        _error('An exact ordinary Steam/game shutdown receipt is required for this run.')
    try:
        observed = datetime.fromisoformat(shutdown['observed_utc'].replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - observed).total_seconds()
        if observed.utcoffset() is None or not 0 <= age <= 600:
            raise ValueError('stale or future receipt')
    except (AttributeError, KeyError, TypeError, ValueError):
        _error('A fresh timestamped ordinary-shutdown receipt is required (at most ten minutes old).')
    _reference(shutdown.get('evidence'))
    census = _native_processes()
    known = {shutdown['steam_process']['pid']}
    if owned_game is not None:
        known.add(owned_game['pid'])
    for pid, parent, name in census:
        candidate = (pid in known or parent in known or name.casefold().startswith('steam')
                     or name.casefold() in ('crimsondesert.exe', 'cdmw_virtual_session.exe'))
        if not candidate:
            continue
        try:
            actual = _process_identity(pid)
        except (OSError, ValueError):
            if pid not in {row[0] for row in _native_processes()}:
                continue
            _error('A candidate save/Cloud process is unreadable; writer absence is unknown.')
        path = transaction._absolute(actual['executable'])
        if pid in known and actual['created'] != next(
                v['created'] for v in (shutdown['steam_process'], owned_game) if v and v['pid'] == pid):
            # PID reuse proves the old process ended; still reject a new writer.
            if not (path.is_relative_to(Path(request['steam_root']))
                    or path.is_relative_to(Path(request['game_root']))
                    or name.casefold().startswith('steam')):
                continue
        _error('A known or unexpected Steam/game/session writer is still running; close it normally.')
    return {'native_census_count': len(census), 'steam_exited_pid': shutdown['steam_process']['pid'],
            'steam_exited_birth': shutdown['steam_process']['created']}


def _app_rows(observation):
    if (not isinstance(observation, dict) or observation.get('app_id') != APP_ID
            or not isinstance(observation.get('records'), dict)):
        _error('Invalid app-scoped Cloud observation.')
    result = {}
    for row in observation['records'].values():
        if not isinstance(row, dict) or not str(row.get('path', '')).endswith('sharedconfig.vdf'):
            continue
        path = str(transaction._absolute(row['path']))
        if path in result:
            _error('Duplicate account path in the Cloud observation.')
        result[path] = row
    return result


def _cloud_binding(request):
    binding = request['account_binding']
    if not isinstance(binding, dict) or set(binding) != {'intent', 'before', 'disabled', 'restored'}:
        _error('The observed app/account toggle binding is incomplete.')
    intent = _json_reference(binding['intent'])
    _identity(intent.get('steam_process'), Path(request['steam_root']) / 'steam.exe', request['steam_sha256'])
    if intent.get('app_id') != int(APP_ID) or intent.get('original_per_game_cloud') is not True:
        _error('The toggle intent does not bind the original per-game Cloud setting.')
    before, disabled, restored = (_app_rows(_json_reference(binding[key]))
                                  for key in ('before', 'disabled', 'restored'))
    if set(before) != set(disabled) or set(before) != set(restored):
        _error('The observed Cloud account candidate sets changed.')
    changed = [path for path in before if before[path].get('app_subtree') != disabled[path].get('app_subtree')]
    config = transaction._absolute(Path(request['steam_root']) / 'userdata' / request['account_id'] / '7/remote/sharedconfig.vdf')
    if (changed != [str(config)] or disabled[str(config)].get('app_subtree', {}).get('cloudenabled') != '0'
            or restored[str(config)].get('app_subtree', {}).get('cloudenabled') != '1'
            or before[str(config)].get('app_subtree', {}).get('cloudenabled') not in (None, '1')
            or any(restored[path].get('app_subtree') != before[path].get('app_subtree')
                   for path in before if path != str(config))):
        _error('The causal app toggle does not uniquely bind this save account.')
    return config


def _request(reference):
    value = _json_reference(reference)
    fields = {'format', 'run_id', 'game_root', 'game_sha256', 'steam_root', 'steam_sha256',
              'save_root', 'account_id', 'run_manifest', 'account_binding', 'cloud_off', 'profile_sha256'}
    if (not isinstance(value, dict) or set(value) != fields or value['format'] != REQUEST
            or not isinstance(value['run_id'], str) or not re.fullmatch('[A-Za-z0-9_-]{8,96}', value['run_id'])
            or not isinstance(value['account_id'], str) or not re.fullmatch('[1-9][0-9]{0,9}', value['account_id'])
            or any(not _hash(value[key]) for key in ('game_sha256', 'steam_sha256', 'profile_sha256'))):
        _error('Invalid explicit live save request.')
    for key in ('game_root', 'steam_root', 'save_root'):
        value[key] = str(transaction._absolute(value[key]))
    return value


def _cloud_off(request, off, *, current=False):
    config = _cloud_binding(request)
    if not isinstance(off, dict) or set(off) != {'observation', 'screenshot', 'config_sha256'} or not _hash(off['config_sha256']):
        _error('A visual and persisted per-game Cloud OFF witness is required.')
    _reference(off['screenshot'])
    observation = _json_reference(off['observation'])
    if observation.get('run_id', request['run_id']) != request['run_id']:
        _error('The Cloud OFF observation belongs to a different run.')
    rows = _app_rows(observation)
    if (str(config) not in rows or rows[str(config)].get('app_subtree', {}).get('cloudenabled') != '0'
            or rows[str(config)].get('sha256') != off['config_sha256']):
        _error('The observed OFF setting does not match the bound account/configuration.')
    if current:
        raw = transaction._read(config)
        if (digest(raw) != off['config_sha256'] or _field(_vdf(raw), 'UserRoamingConfigStore',
                'Software', 'Valve', 'Steam', 'apps', APP_ID, 'cloudenabled') != '0'):
            _error('Steam Cloud is not the exact persisted per-game OFF setting; preserve all saves.')
    return off


def _guard(request, shutdown_reference, *, account_tree, owned_game=None, cloud_off=None):
    if Path(request['save_root']) != _known_save_root():
        _error('The live request does not name the exact native Windows save root.')
    manifest = _json_reference(request['run_manifest'])
    if not isinstance(manifest, dict) or manifest.get('run_id') != request['run_id']:
        _error('The execution manifest belongs to a different run.')
    game, steam = Path(request['game_root']), Path(request['steam_root'])
    if (hash_file(transaction._absolute(game / 'bin64/CrimsonDesert.exe')) != request['game_sha256']
            or hash_file(transaction._absolute(steam / 'steam.exe')) != request['steam_sha256']
            or hash_file(transaction._absolute(game / '.cdmw/virtual-loader/profile.json')) != request['profile_sha256']):
        _error('The exact game, Steam executable or bound profile changed.')
    off = _cloud_off(request, request['cloud_off'] if cloud_off is None else cloud_off, current=True)
    marker = account_tree / request['account_id'] / 'steam_autocloud.vdf'
    if _field(_vdf(transaction._read(marker)), 'steam_autocloud.vdf', 'accountid') != request['account_id']:
        _error('The save account marker does not match the observed Steam/config account.')
    shutdown = _json_reference(shutdown_reference)
    if not isinstance(shutdown, dict):
        _error('Invalid ordinary-shutdown evidence.')
    if shutdown.get('cloud_config_sha256') != off['config_sha256']:
        _error('The ordinary shutdown did not witness the current disabled Cloud configuration.')
    native = _closed(request, shutdown, owned_game)
    return {'processes': [], 'writers': [], 'evidence': digest(canonical({
        'request': request, 'cloud_off': off, 'shutdown': shutdown_reference, 'native': native}))}


def _effective_cloud(request, journal):
    renewals = journal.get('cloud_renewals', [])
    if not isinstance(renewals, list) or len(renewals) > 32:
        _error('The live Cloud evidence renewal history exceeds its supported bounds.')
    previous, effective = digest(canonical(request['cloud_off'])), request['cloud_off']
    for row in renewals:
        if not isinstance(row, dict) or set(row) != {'previous', 'cloud_off', 'shutdown_receipt', 'identity'}:
            _error('Invalid live Cloud evidence renewal record.')
        payload = {key: value for key, value in row.items() if key != 'identity'}
        if row['previous'] != previous or row['identity'] != digest(canonical(payload)):
            _error('The live Cloud evidence renewal chain changed.')
        _cloud_off(request, row['cloud_off'])
        shutdown = _json_reference(row['shutdown_receipt'])
        if (not isinstance(shutdown, dict) or shutdown.get('format') != SHUTDOWN
                or shutdown.get('run_id') != request['run_id'] or shutdown.get('method') != 'normal_ui_exit'
                or shutdown.get('cloud_config_sha256') != row['cloud_off']['config_sha256']
                or shutdown.get('game_process') not in (None, journal['owned_game'])):
            _error('The retained renewal shutdown belongs to a different live context.')
        _identity(shutdown.get('steam_process'), Path(request['steam_root']) / 'steam.exe', request['steam_sha256'])
        _reference(shutdown.get('evidence'))
        previous, effective = row['identity'], row['cloud_off']
    return effective


def _native_session_binding(request, process, reference, *, current=False):
    """Join the development run to existing sealed CDMW receipts and raw status."""
    game = Path(request['game_root'])
    receipt = _json_reference(reference)
    if (not isinstance(receipt, dict) or receipt.get('format') != 'cdmw_cditem_owned_game_v1'
            or receipt.get('run_id') != request['run_id'] or receipt.get('process') != process
            or not isinstance(receipt.get('session_token'), str)
            or not re.fullmatch('[a-f0-9]{32}', receipt['session_token'])):
        _error('The native-session receipt does not bind this owned game/run.')
    token = receipt['session_token']
    sealed_raw = _reference(receipt.get('native_status_evidence'))
    sealed = decode_receipt(sealed_raw)
    value = sealed.to_dict()
    proposed, reported = value['proposed'], value['process']
    if (value['attempt'] != token or value['readiness'] != 'reported-ready'
            or value['terminal'] != 'pending' or reported['expected_session_token'] != token
            or reported['reported_state'] != 'running' or reported['reported_game_pid'] != process['pid']
            or type(reported['host_pid']) is not int or reported['host_pid'] <= 0
            or proposed is None or proposed['profile_sha256'] != request['profile_sha256']
            or proposed['executable_sha256'] != request['game_sha256']):
        _error('The sealed native receipt is not ready for this exact token, game and profile.')
    epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
    captured = datetime.strptime(value['captured_utc'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    elapsed = captured - epoch
    captured_ticks = (elapsed.days * 86400 + elapsed.seconds) * 10_000_000
    if captured_ticks <= process['created'] or captured > datetime.now(timezone.utc):
        _error('The native readiness receipt predates this process birth or is from the future.')
    chain = read_session_receipts(game, token)
    if not any(member.identity == sealed.identity and member.data == sealed_raw for member in chain):
        _error('The native readiness receipt is not an actual member of the complete session chain.')
    if current:
        latest = chain[-1].to_dict()
        if (latest['terminal'] != 'pending' or latest['readiness'] != 'reported-ready'
                or latest['process']['reported_state'] != 'running'
                or latest['process']['reported_game_pid'] != process['pid']
                or latest['process']['host_pid'] != reported['host_pid']
                or latest['proposed'] is None
                or latest['proposed']['profile_sha256'] != request['profile_sha256']
                or latest['proposed']['executable_sha256'] != request['game_sha256']):
            _error('The complete native chain no longer reports this running game/profile at bind time.')
    report_reference = receipt.get('native_report')
    report_raw = _reference(report_reference)
    report = decode(report_raw, limit=transaction.LIMIT)
    if (not isinstance(report, dict) or report.get('state') != 'running'
            or type(report.get('error')) is not int or report['error'] != 0
            or type(report.get('progress')) is not int or report['progress'] != 100
            or type(report.get('pid')) is not int or report['pid'] != process['pid']
            or type(report.get('host_pid')) is not int or report['host_pid'] != reported['host_pid']
            or [row['sha256'] for row in value['evidence'] if row['kind'] == 'runtime-status-file'] != [digest(report_raw)]):
        _error('The retained native report is not the exact successful status bound by the sealed receipt.')
    status_path = transaction._absolute(game / '.cdmw/virtual-loader' / ('session-' + token + '.json'))
    if transaction._absolute(report_reference['path']) == status_path:
        _error('Retain an independent immutable native report instead of referencing mutable status.')
    if current:
        if (hash_file(transaction._absolute(game / 'bin64/CrimsonDesert.exe')) != request['game_sha256']
                or hash_file(transaction._absolute(game / '.cdmw/virtual-loader/profile.json')) != request['profile_sha256']
                or transaction._read(status_path) != report_raw):
            _error('The current token-named native status, executable or profile changed before binding.')
        if _process_identity(process['pid']) != process:
            _error('The owned game process changed before save-context binding.')
    return receipt


def _owner(root, context=None, *, required=False):
    return transaction._check_owner(root, context, required=required, format=FORMAT, prefix=PREFIX)


def _load(context):
    if not isinstance(context, LiveSaveContext):
        _error('The explicit live save context type is required.')
    directory = transaction._offline(context.directory)
    raw = transaction._read(directory / 'manifest.json')
    if digest(raw) != context.manifest_sha256:
        _error('The immutable live save manifest changed.')
    manifest = decode(raw, limit=transaction.LIMIT)
    if not isinstance(manifest, dict) or set(manifest) != {'format', 'request', 'original', 'intended'} or manifest['format'] != FORMAT:
        _error('Unsupported live save context.')
    request = _request(manifest['request'])
    root = Path(request['save_root'])
    if (any(transaction._overlap(directory, Path(request[key])) for key in ('save_root', 'game_root', 'steam_root'))
            or directory.stat().st_dev != root.parent.stat().st_dev):
        _error('Live save staging must remain separate on the native save volume.')
    journal = decode(transaction._read(directory / 'journal.json'), limit=transaction.LIMIT)
    fields = {'format', 'manifest_sha256', 'expected_current', 'output_state', 'output_directory',
              'owned_game', 'shutdown_receipt', 'phase', 'observed', 'quiescence'}
    if (not isinstance(journal, dict) or set(journal) not in (
            fields, fields | {'session_receipt'}, fields | {'cloud_renewals'}, fields | {'session_receipt', 'cloud_renewals'})
            or journal.get('format') != FORMAT
            or journal.get('manifest_sha256') != context.manifest_sha256
            or journal.get('phase') not in {'preparing', 'prepared', 'exchanging', 'active', 'restoring', 'recovering', 'restored'}
            or not isinstance(journal.get('expected_current'), dict)
            or journal.get('expected_current') not in (manifest['intended'], journal.get('output_state'))
            or (journal.get('output_state') is None) != (journal.get('output_directory') is None)
            or journal.get('output_directory') not in (None, 'output')):
        _error('Invalid live save recovery journal.')
    if (journal['owned_game'] is None) != ('session_receipt' not in journal):
        _error('The live context has an orphaned game/session receipt.')
    if journal['owned_game'] is not None:
        _identity(journal['owned_game'], Path(request['game_root']) / 'bin64/CrimsonDesert.exe', request['game_sha256'])
        if 'session_receipt' not in journal:
            _error('The live context is missing its owned game/session receipt.')
        _native_session_binding(request, journal['owned_game'], journal['session_receipt'])
    _effective_cloud(request, journal)
    return directory, root, manifest, journal, request


def prepare_live_context(request_reference, test_root, directory, *, shutdown_receipt, stop_event=None):
    """Prepare only after exact evidence and native absence; no launch/Cloud changes."""
    request = _request(request_reference)
    root, test, directory = Path(request['save_root']), transaction._offline(test_root), transaction._offline(directory)
    if (any(transaction._overlap(a, b) for a, b in ((root, test), (root, directory), (test, directory)))
            or any(transaction._overlap(directory, Path(request[key])) for key in ('game_root', 'steam_root'))
            or not root.parent.is_dir() or not directory.parent.is_dir()
            or directory.parent.stat().st_dev != root.parent.stat().st_dev):
        _error('Use distinct existing parents and same-volume live staging outside the save tree.')
    with installation_lane(request['game_root']), installation_lane(root), installation_lane(directory):
        _owner(root)
        check = lambda: _guard(request, shutdown_receipt, account_tree=root)
        witness = check()
        original = transaction.snapshot_offline_root(root, stop_event=stop_event)
        intended = transaction.snapshot_offline_root(test, stop_event=stop_event)
        marker = request['account_id'] + '/steam_autocloud.vdf'
        foreign_original = {name: row for name, row in original['files'].items()
                            if not name.startswith(request['account_id'] + '/')}
        foreign_intended = {name: row for name, row in intended['files'].items()
                            if not name.startswith(request['account_id'] + '/')}
        if (marker not in original['files'] or intended['files'].get(marker) != original['files'][marker]
                or foreign_original != foreign_intended):
            _error('The disposable input must preserve the exact account marker and shared original files.')
        manifest = {'format': FORMAT, 'request': request_reference, 'original': original, 'intended': intended}
        raw = canonical(manifest)
        context = LiveSaveContext(directory, digest(raw))
        directory.mkdir()
        atomic_write_bytes(directory / 'manifest.json', raw)
        journal = {'format': FORMAT, 'manifest_sha256': context.manifest_sha256,
                   'expected_current': intended, 'output_state': None, 'output_directory': None,
                   'owned_game': None, 'shutdown_receipt': shutdown_receipt}
        transaction._journal(directory, journal, 'preparing', observed=original, witness=witness)
        transaction._copy_snapshot(root, directory / 'original', original, stop_event)
        transaction._copy_snapshot(test, directory / 'input', intended, stop_event)
        check()
        transaction._expect(root, original, stop_event)
        raise_if_cancelled(stop_event)
        transaction._journal(directory, journal, 'prepared')
        return context


def inspect_live_context(context):
    directory, root, manifest, journal, request = _load(context)
    return {'format': FORMAT, 'run_id': request['run_id'], 'phase': journal['phase'],
            'save_root': str(root), 'account_sha256': digest(request['account_id'].encode()),
            'owned_game': journal['owned_game'], 'live_ready': False,
            'detail': 'A fresh normal-shutdown receipt and native stopped-writer check are required for every exchange/restoration.'}


def preflight_live_context(context, *, shutdown_receipt):
    """Validate exact live action preconditions without exchanging any save files."""
    directory, root, manifest, journal, request = _load(context)
    with installation_lane(request['game_root']), installation_lane(root), installation_lane(directory):
        directory, root, manifest, journal, request = _load(context)
        _owner(root, context, required=journal['phase'] == 'active')
        _guard(request, shutdown_receipt, account_tree=directory / 'original', owned_game=journal['owned_game'],
               cloud_off=_effective_cloud(request, journal))
        transaction._expect(directory / 'original', manifest['original'])
        transaction._expect(directory / 'input', manifest['intended'])
        expected = manifest['original'] if journal['phase'] == 'prepared' else journal['expected_current']
        transaction._expect(root, expected)
        return {'run_id': request['run_id'], 'phase': journal['phase'],
                'ready_for_exchange': journal['phase'] == 'prepared',
                'ready_for_restore': journal['phase'] == 'active'}


def _operation(context, shutdown_receipt, action, expected_current=None, stop_event=None):
    directory, root, manifest, journal, request = _load(context)
    with installation_lane(request['game_root']), installation_lane(root), installation_lane(directory):
        directory, root, manifest, journal, request = _load(context)
        _owner(root, context, required=action in ('outputs', 'restore'))
        account_tree = root if journal['phase'] == 'preparing' else directory / 'original'
        check = lambda: _guard(request, shutdown_receipt, account_tree=account_tree, owned_game=journal['owned_game'],
                               cloud_off=_effective_cloud(request, journal))
        check()
        journal['shutdown_receipt'] = shutdown_receipt
        if action == 'exchange':
            if journal['phase'] != 'prepared':
                _error('Recover the unfinished live context before exchanging again.')
            _owner(root)
            transaction._exchange_transaction(directory, root, manifest, journal, check, stop_event,
                claim=lambda: transaction._claim(root, context, format=FORMAT, prefix=PREFIX))
        elif action == 'outputs':
            if journal['phase'] != 'active' or journal['output_directory'] is not None:
                _error('The live context is not awaiting retained outputs.')
            transaction._retain_transaction_outputs(directory, root, journal, expected_current, check, stop_event)
        elif action == 'restore':
            if journal['phase'] != 'active':
                _error('Recover the unfinished live context before restoring it.')
            transaction._restore(directory, root, manifest, journal, check, stop_event)
            transaction._release(root, context, format=FORMAT, prefix=PREFIX)
        elif action == 'recover':
            transaction._recover_transaction(directory, root, manifest, journal, check, stop_event,
                require_owner=lambda: _owner(root, context, required=True))
            transaction._release(root, context, format=FORMAT, prefix=PREFIX)
        return inspect_live_context(context)


def exchange_live_context(context, *, shutdown_receipt, stop_event=None):
    return _operation(context, shutdown_receipt, 'exchange', stop_event=stop_event)


def retain_live_outputs(context, expected_current, *, shutdown_receipt, stop_event=None):
    return _operation(context, shutdown_receipt, 'outputs', expected_current, stop_event)


def restore_live_context(context, *, shutdown_receipt, stop_event=None):
    return _operation(context, shutdown_receipt, 'restore', stop_event=stop_event)


def recover_live_context(context, *, shutdown_receipt, stop_event=None):
    return _operation(context, shutdown_receipt, 'recover', stop_event=stop_event)


def refresh_live_cloud_evidence(context, cloud_off, *, shutdown_receipt):
    """Renew only explicit OFF evidence; never rewrite the request or save state."""
    candidate = decode(canonical(cloud_off), limit=transaction.LIMIT)
    directory, root, manifest, journal, request = _load(context)
    with installation_lane(request['game_root']), installation_lane(root), installation_lane(directory):
        directory, root, manifest, journal, request = _load(context)
        _owner(root, context, required=journal['phase'] in ('active', 'restoring', 'recovering'))
        history = list(journal.get('cloud_renewals', []))
        if len(history) >= 32:
            _error('The live Cloud evidence renewal history exceeds its supported bounds.')
        account_tree = root if journal['phase'] == 'preparing' else directory / 'original'
        _guard(request, shutdown_receipt, account_tree=account_tree, owned_game=journal['owned_game'], cloud_off=candidate)
        previous = history[-1]['identity'] if history else digest(canonical(request['cloud_off']))
        payload = {'previous': previous, 'cloud_off': candidate, 'shutdown_receipt': shutdown_receipt}
        row = {**payload, 'identity': digest(canonical(payload))}
        _guard(request, shutdown_receipt, account_tree=account_tree, owned_game=journal['owned_game'], cloud_off=candidate)
        journal['cloud_renewals'] = [*history, row]
        transaction._journal(directory, journal, journal['phase'])
        return {'run_id': request['run_id'], 'phase': journal['phase'], 'renewal_identity': row['identity'],
                'config_sha256': candidate['config_sha256']}


def bind_live_game(context, process, *, session_receipt):
    """Record the actual owned game before scenarios, without taking its host lane."""
    directory, root, manifest, journal, request = _load(context)
    game = Path(request['game_root']) / 'bin64/CrimsonDesert.exe'
    _identity(process, game, request['game_sha256'])
    with installation_lane(directory):
        directory, root, manifest, journal, request = _load(context)
        _owner(root, context, required=True)
        if journal['phase'] != 'active' or journal['owned_game'] is not None:
            _error('The live context already has an owned game or is not active.')
        _native_session_binding(request, process, session_receipt, current=True)
        journal['owned_game'] = process
        journal['session_receipt'] = session_receipt
        transaction._journal(directory, journal, 'active')
