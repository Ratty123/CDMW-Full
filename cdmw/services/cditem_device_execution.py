"""Development execution for an already launched and save-context-bound game.

This module has no launch, save exchange, native item or screenshot recognition
authority. A caller-supplied observer classifies only the driver's current frame.
Without that observer an execution retains a frame and pauses without input.
"""
from __future__ import annotations

from dataclasses import asdict
from copy import deepcopy
from datetime import datetime, timezone
import math
from pathlib import Path
import re
import time

from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.services import cditem_device_live_saves as live_saves
from cdmw.services import cditem_device_saves as saves
from cdmw.services.cditem_device_runner import (
    DEFAULT_TIMEOUTS, DeviceRun, DeviceRunError, Observation, ProcessIdentity,
    RunJournal, WindowIdentity, perform_action, verify_guards,
)
from cdmw.services.cditem_device_windows import (
    InputGuardian, WindowsGameDriver, desktop_preflight, process_identity, window_identity,
)
from cdmw.services.independent_item_package import canonical, digest
from cdmw.services.installation_lane import installation_lane
from cdmw.services.virtual_loader_runtime import RUNTIME_PATH
from cdmw.services.virtual_loader_state import decode
from cdmw.services.virtual_loader_composition import hash_file

FORMAT = 'cdmw_cditem_device_execution_v1'
OWNER_FORMAT = 'cdmw_cditem_device_execution_owner_v1'
EXIT_RECOVERY_FORMAT = 'cdmw_cditem_exit_recovery_v1'
ACTIONS = frozenset(('focus', 'click', 'key', 'wait', 'observe_baseline', 'close'))
LIMIT = 4 * 1024 * 1024


def _fail(message):
    raise DeviceRunError(message)


def _sha(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _read(path):
    return saves._read(saves._absolute(path))


def _reference(value):
    if not isinstance(value, dict) or set(value) != {'path', 'sha256'} or not _sha(value['sha256']):
        _fail('An exact execution evidence path and SHA-256 are required.')
    raw = _read(value['path'])
    if digest(raw) != value['sha256']:
        _fail('Execution evidence changed; preserve this run before continuing.')
    return raw


def _json(value):
    return decode(_reference(value), limit=LIMIT)


def _snapshot_reference(value):
    if not isinstance(value, dict) or set(value) != {'path', 'sha256'} or not _sha(value['sha256']):
        _fail('An exact execution evidence path and SHA-256 are required.')
    return {'path': str(saves._absolute(value['path'])), 'sha256': value['sha256']}


def _expiry(value):
    if not isinstance(value, str):
        _fail('An exact UTC execution expiry is required.')
    try:
        expires = datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise DeviceRunError('Invalid execution expiry.') from exc
    if expires <= datetime.now(timezone.utc):
        _fail('The bounded execution manifest has expired.')


def _load(reference):
    manifest = _json(reference)
    fields = {'format', 'run_id', 'game_root', 'scenario', 'save_id', 'process', 'hwnd',
              'live_context', 'session_receipt', 'profile', 'runtime', 'guards',
              'allowed_actions', 'timeouts', 'run_directory', 'expires_utc', 'max_actions'}
    if not isinstance(manifest, dict) or set(manifest) != fields or manifest['format'] != FORMAT:
        _fail('Unsupported device execution manifest.')
    if (not isinstance(manifest['run_id'], str)
            or not re.fullmatch('[A-Za-z0-9_-]{8,96}', manifest['run_id'])
            or manifest['scenario'] != 'baseline_observation'
            or not isinstance(manifest['save_id'], str) or not 0 < len(manifest['save_id']) <= 256):
        _fail('Only one exact baseline scenario and disposable save are supported.')
    _expiry(manifest['expires_utc'])
    game, folder = saves._absolute(manifest['game_root']), saves._absolute(manifest['run_directory'])
    process = manifest['process']
    if not isinstance(process, dict) or set(process) != set(ProcessIdentity.__dataclass_fields__):
        _fail('An exact process birth identity is required.')
    process = ProcessIdentity(**process)
    # Reuse policy validation for the full PID, FILETIME, path, hash and session.
    DeviceRun(manifest['run_id'], process, save_id=manifest['save_id'])
    if saves._absolute(process.executable) != game / 'bin64/CrimsonDesert.exe':
        _fail('The owned process is not the named installation executable.')
    if type(manifest['hwnd']) is not int or manifest['hwnd'] <= 0:
        _fail('One previously observed owned game window is required.')
    if (type(manifest['max_actions']) is not int or not 1 <= manifest['max_actions'] <= 256
            or not isinstance(manifest['allowed_actions'], list) or not manifest['allowed_actions']
            or any(not isinstance(x, str) for x in manifest['allowed_actions'])
            or len(set(manifest['allowed_actions'])) != len(manifest['allowed_actions'])
            or not set(manifest['allowed_actions']) <= ACTIONS):
        _fail('Invalid bounded device action contract.')
    deadlines = manifest['timeouts']
    if (not isinstance(deadlines, dict) or set(deadlines) != set(DEFAULT_TIMEOUTS)
            or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 1800
                   for v in deadlines.values())):
        _fail('Every device state needs an explicit bounded deadline.')
    context = manifest['live_context']
    if (not isinstance(context, dict) or set(context) != {'directory', 'manifest_sha256'}
            or not _sha(context['manifest_sha256'])):
        _fail('An exact live save context reference is required.')
    directory = saves._absolute(context['directory'])
    context = live_saves.LiveSaveContext(directory, context['manifest_sha256'])
    state = live_saves.inspect_live_context(context)
    if (state['run_id'] != manifest['run_id'] or state['phase'] != 'active'
            or state['owned_game'] != asdict(process)):
        _fail('The live save context has not bound this exact owned game and run.')
    # Existing inspection validates native receipt semantics. Join its immutable
    # request to this manifest, rather than treating a matching PID as authority.
    saved_manifest = _json({'path': str(directory / 'manifest.json'), 'sha256': context.manifest_sha256})
    request = _json(saved_manifest['request'])
    if (saves._absolute(request['game_root']) != game
            or request['game_sha256'] != process.executable_sha256
            or manifest['profile'] != {'path': str(game / '.cdmw/virtual-loader/profile.json'),
                                       'sha256': request['profile_sha256']}):
        _fail('The execution game or profile differs from its bound save context.')
    live_saves._owner(Path(request['save_root']), context, required=True)
    live_journal = decode(_read(directory / 'journal.json'), limit=LIMIT)
    if live_journal.get('session_receipt') != manifest['session_receipt']:
        _fail('The execution names a different native game binding receipt.')
    receipt = _json(manifest['session_receipt'])
    status = game / '.cdmw/virtual-loader' / ('session-' + receipt['session_token'] + '.json')
    guards = manifest['guards']
    runtime = manifest['runtime']
    if (not isinstance(guards, list) or len(guards) > 256
            or not isinstance(runtime, list) or not 2 <= len(runtime) <= 32):
        _fail('Invalid execution file guard or runtime inventory bounds.')
    paths = []
    for item in [*guards, *runtime, manifest['profile']]:
        if not isinstance(item, dict) or set(item) != {'path', 'sha256'} or not _sha(item['sha256']):
            _fail('Invalid exact execution file guard.')
        paths.append((saves._absolute(item['path']), item['sha256']))
    guard_map = {}
    for path, checksum in paths:
        if path in guard_map and guard_map[path] != checksum:
            _fail('Conflicting execution file guards.')
        guard_map[path] = checksum
    required = {game / 'bin64/CrimsonDesert.exe': process.executable_sha256,
                status: receipt['native_report']['sha256']}
    if any(guard_map.get(path) != checksum for path, checksum in required.items()):
        _fail('The executable and current native status require exact file guards.')
    runtime_paths = [saves._absolute(row['path']) for row in runtime]
    if len(set(runtime_paths)) != len(runtime_paths):
        _fail('Duplicate runtime inventory entries.')
    actual = {path.resolve() for path in (game / 'bin64').iterdir() if path.suffix.lower() == '.asi'}
    actual.add(game / 'bin64/winmm.dll')
    if (set(runtime_paths) != actual or game / RUNTIME_PATH not in actual
            or any(path.parent != game / 'bin64' for path in runtime_paths)):
        _fail('The installed loader/bootstrap/ASI inventory changed.')
    verify_guards([(str(path), checksum) for path, checksum in guard_map.items()])
    if (not folder.parent.is_dir() or any(saves._overlap(folder, path) for path in (
            game, directory, saves._absolute(request['save_root'])))):
        _fail('Execution evidence must use an existing separate parent outside game and save trees.')
    return manifest, context, process, folder


def _binding(reference):
    return {'manifest': reference['sha256'], 'path': str(saves._absolute(reference['path']))}


def _owner_path(context):
    return context.directory / 'device-execution-owner.json'


def _expect_owner(context, expected):
    try:
        observed = _read(_owner_path(context))
    except (OSError, ValueError, TypeError) as exc:
        raise DeviceRunError('The durable execution ownership record changed; no input was dispatched.') from exc
    if observed != canonical(expected):
        _fail('The durable execution ownership record changed; no input was dispatched.')


def _journal(folder, run_id):
    # RunJournal validates its own format and run identity. Bounded strict decode
    # here also rejects duplicate JSON fields before its compatibility reader.
    decode(_read(folder / 'device-run.json'), limit=LIMIT)
    result = RunJournal(folder, run_id=run_id)
    if (set(result.value) != {'format', 'run_id', 'status', 'revision', 'events'}
            or not isinstance(result.value['events'], list)
            or type(result.value['revision']) is not int
            or result.value['revision'] != len(result.value['events'])
            or len(result.value['events']) > 4096):
        _fail('Invalid execution journal shape or revision.')
    return result


def _competition(reference, manifest, context, folder):
    owner = _owner_path(context)
    expected = {'format': OWNER_FORMAT, 'run_id': manifest['run_id'],
                'binding': _binding(reference), 'directory': str(folder)}
    if owner.exists():
        value = decode(_read(owner), limit=LIMIT)
        if value == expected:
            if not (folder / 'device-run.json').is_file():
                _fail('The owned execution journal is missing; preserve this unknown state.')
        else:
            if (not isinstance(value, dict) or set(value) != set(expected)
                    or value.get('format') != OWNER_FORMAT):
                _fail('Unknown device execution ownership state; preserve it for review.')
            previous = _journal(saves._absolute(value['directory']), value['run_id'])
            if (not previous.value['events'] or previous.value['events'][0].get('binding') != value['binding']
                    or not _terminal(previous)):
                _fail('A competing unfinished device run owns this live context.')
    elif (folder / 'device-run.json').exists():
        retained = _journal(folder, manifest['run_id'])
        if len(retained.value['events']) != 1 or retained.value['status'] != 'prepared':
            _fail('The execution ownership record is missing after work began; preserve this unknown state.')
    children = list(folder.parent.iterdir())
    if len(children) > 512:
        _fail('The device run parent exceeds its bounded reconciliation inventory.')
    for child in children:
        if child == folder or not child.is_dir() or not (child / 'device-run.json').exists():
            continue
        other = decode(_read(child / 'device-run.json'), limit=LIMIT)
        if (not isinstance(other, dict) or not isinstance(other.get('run_id'), str)
                or not _terminal(_journal(child, other['run_id']))):
            _fail('A competing unfinished device run must be reconciled first.')
    return expected


class _Policy(DeviceRun):
    def __init__(self, manifest, process, clock):
        super().__init__(manifest['run_id'], process, save_id=manifest['save_id'],
                         scenario=manifest['scenario'], timeouts=manifest['timeouts'], clock=clock)
        self.allowed = set(manifest['allowed_actions'])

    def next_action(self, observation):
        action = super().next_action(observation)
        if action.kind not in self.allowed:
            self.pause('The observed action is outside this execution manifest.')
            _fail(self.failure)
        return action


def _observation(value):
    if not isinstance(value, dict) or set(value) != set(Observation.__dataclass_fields__):
        _fail('Invalid retained execution observation.')
    value = dict(value)
    value['process'] = ProcessIdentity(**value['process'])
    window = dict(value['window'])
    window['client'] = tuple(window['client'])
    value['window'] = WindowIdentity(**window)
    if value['point'] is not None:
        value['point'] = tuple(value['point'])
    return Observation(**value)


def _retained_frame(folder, sequence, path, checksum):
    expected = folder / 'captures' / f'{sequence:04d}.png'
    if saves._absolute(path) != expected or not _sha(checksum) or hash_file(expected) != checksum:
        _fail('A retained current-run frame changed or belongs to another run.')


def _reconstruct(reference, manifest, process, journal, clock, *, allow_failed_focus=False):
    events = journal.value['events']
    if (not events or set(events[0]) != {'event', 'binding', 'started_at'}
            or events[0]['event'] != 'execution_started' or events[0]['binding'] != _binding(reference)
            or type(events[0]['started_at']) not in (int, float)
            or not math.isfinite(events[0]['started_at']) or events[0]['started_at'] > clock()):
        _fail('The execution journal does not bind this immutable manifest and clock.')
    replay_time = [events[0]['started_at']]
    run = _Policy(manifest, process, lambda: replay_time[0])
    observation = pending = None
    input_scope = cancelled = failed_focus = close_needs_release = False
    sequence = count = 0
    for row in events[1:]:
        if not isinstance(row, dict):
            _fail('Unknown execution journal event.')
        kind = row.get('event')
        if cancelled:
            _fail('The cancelled execution has unexpected later events.')
        if failed_focus and kind not in ('execution_paused', 'input_scope_released', 'execution_cancelled'):
            _fail('A refused focus request permits only cleanup and cancellation, not further execution.')
        if close_needs_release and kind not in ('execution_paused', 'input_scope_released', 'cleanup_failure'):
            _fail('The prior close request requires complete input cleanup before another capture.')
        if run.state == 'finished' and kind != 'input_scope_released':
            _fail('The completed execution has unexpected later events.')
        if kind == 'input_scope_started':
            if set(row) != {'event'} or input_scope or pending is not None:
                _fail('Unknown or overlapping input cleanup scope.')
            input_scope = True
        elif kind == 'input_scope_released':
            if set(row) != {'event'} or not input_scope or pending is not None:
                _fail('Input cleanup completion has no unique input scope.')
            input_scope = False
            close_needs_release = False
        elif kind == 'observation':
            if not input_scope:
                _fail('The observation has no durable input cleanup scope.')
            if pending is not None or set(row) != {'event', 'value'}:
                _fail('An unfinished prior action requires recovery; no input was replayed.')
            observation = _observation(row['value'])
            if (type(observation.sequence) is not int or observation.sequence <= sequence
                    or type(observation.captured_at) not in (int, float)
                    or not math.isfinite(observation.captured_at)
                    or not replay_time[0] <= observation.captured_at <= clock()):
                _fail('Retained observations changed order or clock.')
            _retained_frame(journal.folder, observation.sequence,
                            observation.screenshot, observation.screenshot_sha256)
            sequence, replay_time[0] = observation.sequence, observation.captured_at
        elif kind == 'intent':
            if observation is None or pending is not None:
                _fail('An execution action has no unique current-run observation.')
            pending = run.next_action(observation)
            expected = run.events[-1]
            if canonical(row) != canonical(expected):
                _fail('The retained action does not follow the current-run observation policy.')
        elif kind == 'result':
            if (pending is None or set(row) != {'event', 'action', 'success', 'detail'}
                    or canonical(row['action']) != canonical(asdict(pending)) or row['success'] is not True
                    or not isinstance(row['detail'], str)):
                _fail('An action result is missing, failed or ambiguous; recover before input.')
            run.complete_action(pending, success=True, detail=row['detail'])
            pending = observation = None
            count += 1
        elif kind == 'capture':
            if not input_scope or pending is not None or set(row) != {'event', 'receipt'}:
                _fail('An unfinished action conflicts with a retained capture.')
            receipt = row['receipt']
            if (not isinstance(receipt, dict) or type(receipt.get('sequence')) is not int
                    or receipt['sequence'] <= sequence or receipt.get('run_id') != manifest['run_id']
                    or receipt.get('process') != asdict(process)
                    or type(receipt.get('captured_at')) not in (int, float)
                    or not math.isfinite(receipt['captured_at'])
                    or not replay_time[0] <= receipt['captured_at'] <= clock()):
                _fail('Invalid retained capture sequence.')
            _retained_frame(journal.folder, receipt['sequence'],
                            receipt.get('path'), receipt.get('sha256'))
            sequence, replay_time[0] = receipt['sequence'], receipt['captured_at']
            observation = None
        elif kind in ('execution_paused', 'failure'):
            if set(row) != {'event', 'detail'} or not isinstance(row['detail'], str):
                _fail('Unknown execution pause record.')
            if pending is not None:
                if (allow_failed_focus and kind == 'failure' and pending.kind == 'focus'
                        and row['detail'] == 'Windows refused the game focus request.'):
                    # SetForegroundWindow refused before any click/key. This
                    # permits terminal cancellation only, never input replay.
                    run.complete_action(pending, success=False, detail=row['detail'])
                    pending = observation = None
                    failed_focus = True
                    count += 1
                elif (kind == 'failure' and pending.kind == 'close' and not pending.key
                        and row['detail'] == 'The owned game has not exited; preserve evidence before recovery.'):
                    # Historical close posted WM_CLOSE, then timed out at an
                    # observed confirmation. Preserve that request; only a new
                    # exact confirmation may authorize the keyboard hold.
                    run.complete_action(pending, success=False, detail=row['detail'])
                    run._state('closing')
                    run.exit_requested = True
                    pending = observation = None
                    close_needs_release = True
                    count += 1
                else:
                    _fail('An unfinished prior action requires recovery; no input was replayed.')
        elif kind == 'cleanup_failure':
            _fail('Input cleanup was not established; this execution needs recovery.')
        elif kind == 'execution_cancelled':
            if set(row) != {'event'} or input_scope or pending is not None:
                _fail('Cancellation does not establish complete input cleanup.')
            cancelled = True
        else:
            _fail('Unknown execution journal event; no input was replayed.')
    if pending is not None:
        _fail('An unfinished prior action requires recovery; no input was replayed.')
    if input_scope:
        _fail('Input cleanup was not durably completed; this execution needs recovery.')
    if cancelled or journal.value['status'] == 'cancelled':
        if not cancelled or journal.value['status'] != 'cancelled':
            _fail('The execution cancellation record is inconsistent.')
        run.state = 'cancelled'
    elif run.state == 'finished' or journal.value['status'] == 'finished':
        if run.state != 'finished' or journal.value['status'] != 'finished':
            _fail('The execution completion record is inconsistent.')
    elif (journal.value['status'] not in ('paused', run.state)
          and not (journal.value['status'] == 'prepared' and count == 0)):
        _fail('Unknown or inconsistent execution journal status.')
    if count > manifest['max_actions']:
        _fail('The execution exceeded its immutable action budget.')
    run.clock = clock
    return run, sequence, count


def _terminal(journal):
    if journal.value['status'] not in ('finished', 'cancelled') or not journal.value['events']:
        return False
    binding = journal.value['events'][0].get('binding')
    if (not isinstance(binding, dict) or set(binding) != {'manifest', 'path'}
            or not _sha(binding['manifest'])):
        _fail('A terminal competing run has unknown immutable binding evidence.')
    reference = {'path': binding['path'], 'sha256': binding['manifest']}
    manifest = _json(reference)
    if isinstance(manifest, dict) and manifest.get('format') == EXIT_RECOVERY_FORMAT:
        _validate_exit_recovery_terminal(reference, journal, time.monotonic)
        return True
    if (not isinstance(manifest, dict) or manifest.get('format') != FORMAT
            or manifest.get('run_id') != journal.value['run_id']):
        _fail('The terminal run manifest changed.')
    run, _, _ = _reconstruct(reference, manifest, ProcessIdentity(**manifest['process']), journal,
                             time.monotonic, allow_failed_focus=True)
    return run.state in ('finished', 'cancelled')


def preflight_execution(reference, *, resume=False, clock=time.monotonic):
    """Read-only reconciliation; never starts, captures, focuses or exchanges."""
    reference = _snapshot_reference(reference)
    manifest, context, process, folder = _load(reference)
    _competition(reference, manifest, context, folder)
    if process_identity(process.pid) != process:
        _fail('The legitimately bound game process birth identity changed.')
    window_identity(manifest['hwnd'], process)
    desktop = desktop_preflight()
    if not desktop['usable'] or desktop['session'] != process.session:
        _fail('The bound game input desktop is unavailable or changed.')
    if resume:
        journal = _journal(folder, manifest['run_id'])
        run, sequence, count = _reconstruct(reference, manifest, process, journal, clock)
        if run.state in ('finished', 'cancelled'):
            _fail('This execution already ' + run.state + '; do not replay it.')
    else:
        if folder.exists():
            _fail('The run directory already exists; explicitly reconcile/resume it.')
        sequence = count = 0
    return {'format': FORMAT, 'run_id': manifest['run_id'], 'manifest_sha256': reference['sha256'],
            'ready': True, 'resume': resume, 'next_sequence': sequence + 1, 'actions_recorded': count,
            'classification': 'required_for_each_fresh_capture', 'acceptance': 'not_established'}


def cancel_execution(reference, *, clock=time.monotonic):
    """End one fully reconciled execution without input or game/save changes.

    Cancellation releases only this run's logical execution ownership. It is not
    a recovery path for pending input and does not establish baseline completion.
    The exact owner pointer remains as terminal evidence for the next preflight.
    """
    reference = _snapshot_reference(reference)
    manifest, context, process, folder = _load(reference)
    with installation_lane(context.directory):
        owner = _competition(reference, manifest, context, folder)
        _expect_owner(context, owner)
        if process_identity(process.pid) != process:
            _fail('The legitimately bound game process birth identity changed.')
        journal = _journal(folder, manifest['run_id'])
        run, sequence, count = _reconstruct(reference, manifest, process, journal, clock, allow_failed_focus=True)
        if run.state in ('finished', 'cancelled'):
            _fail('This execution already ' + run.state + '; it cannot be cancelled again.')
        _load(reference)
        _expect_owner(context, owner)
        if process_identity(process.pid) != process:
            _fail('The legitimately bound game process birth identity changed.')
        journal.append({'event': 'execution_cancelled'}, status='cancelled')
        return {'format': FORMAT, 'run_id': manifest['run_id'], 'manifest_sha256': reference['sha256'],
                'status': 'cancelled', 'actions_recorded': count, 'last_sequence': sequence,
                'journal': str(journal.path), 'actions_sent_by_cancellation': [],
                'acceptance': 'not_established',
                'detail': 'Execution cancelled; the bound game remains running and baseline completion is not established.'}


def _classified(receipt, value):
    fields = {'screen', 'foreground', 'control', 'point', 'save_id', 'gameplay_witness', 'scenario', 'assertion'}
    if not isinstance(value, dict) or set(value) != fields or type(value['foreground']) is not bool:
        _fail('The observer must classify this fresh frame using the bounded observation fields.')
    if any(not isinstance(value[key], str) or len(value[key]) > 2048 for key in fields - {'foreground', 'point'}):
        _fail('Invalid bounded frame classification.')
    point = value['point']
    if point is not None and (not isinstance(point, (list, tuple)) or len(point) != 2
                              or any(type(x) is not int for x in point)):
        _fail('Invalid observed control point.')
    return Observation(receipt['run_id'], receipt['sequence'], receipt['captured_at'],
        ProcessIdentity(**receipt['process']),
        WindowIdentity(receipt['window']['hwnd'], tuple(receipt['window']['client']), receipt['window']['dpi']),
        receipt['path'], receipt['sha256'], input_tick=receipt['input_tick'], **value)


class _DispatchDriver:
    """Retain the existing action journal while checking guards at dispatch."""
    def __init__(self, driver, reference, context, owner, *, extra_guard=None):
        self.driver, self.reference, self.context, self.owner = driver, reference, context, owner
        self.extra_guard = extra_guard

    def verify_observation(self, observation):
        self.driver.verify_observation(observation)

    def perform(self, action, observation):
        _load(self.reference)
        if self.extra_guard is not None:
            self.extra_guard()
        _expect_owner(self.context, self.owner)
        self.driver.perform(action, observation)

    def release_inputs(self):
        self.driver.release_inputs()


def _finish_input_scope(journal, driver, guardian_context, entered, primary_error, interrupted):
    """Shared finalizer: every release is attempted even after BaseException."""
    cleanup_error = None
    cleanups = ([driver.release_inputs] if driver is not None else [])
    if guardian_context is not None and entered:
        cleanups.append(lambda: guardian_context.__exit__(None, None, None))
    for cleanup in cleanups:
        try:
            cleanup()
        except BaseException as exc:
            interrupted = True
            try:
                journal.append({'event': 'cleanup_failure', 'detail': str(exc)}, status='paused')
            except BaseException as journal_error:
                exc.add_note('Could not retain input cleanup failure: ' + str(journal_error))
            if primary_error is not None:
                primary_error.add_note('Input cleanup also failed: ' + str(exc))
            elif cleanup_error is None:
                cleanup_error = exc
    if not interrupted:
        try:
            journal.append({'event': 'input_scope_released'})
        except BaseException as exc:
            if primary_error is not None:
                primary_error.add_note('Could not complete the durable input cleanup scope: ' + str(exc))
            elif cleanup_error is None:
                cleanup_error = exc
    if cleanup_error is not None:
        raise cleanup_error


def execute_execution(reference, *, resume=False, observer=None, steps=1,
                      clock=time.monotonic, driver_factory=WindowsGameDriver,
                      guardian_factory=InputGuardian):
    """Run bounded fresh-frame decisions for a previously supported-launched game.

    The observer receives a copy of the actual driver's capture receipt. Returning
    None pauses with that capture. Recognition correctness remains the observer's
    explicit evidence responsibility; this function never fabricates live proof.
    """
    if type(steps) is not int or not 1 <= steps <= 64:
        _fail('One invocation supports at most 64 fresh-frame steps.')
    reference = _snapshot_reference(reference)
    manifest, context, process, folder = _load(reference)
    with installation_lane(context.directory):
        preflight_execution(reference, resume=resume, clock=clock)
        owner = _competition(reference, manifest, context, folder)
        if resume:
            journal = _journal(folder, manifest['run_id'])
        else:
            journal = RunJournal(folder, run_id=manifest['run_id'], create=True)
            journal.append({'event': 'execution_started', 'binding': _binding(reference), 'started_at': clock()})
        atomic_write_bytes(_owner_path(context), canonical(owner))
        run, sequence, count = _reconstruct(reference, manifest, process, journal, clock)
        captures = folder / 'captures'
        captures.mkdir(exist_ok=True)
        # Open the durable scope before any input supervisor or release call.
        # A failed/interrupted receipt write later leaves this scope unfinished,
        # so another invocation cannot accept cleanup merely because no failure
        # event could be written.
        journal.append({'event': 'input_scope_started'})
        guardian_context = guardian = driver = primary_error = None
        guardian_enter_attempted, interrupted = False, False
        try:
            guardian_context = guardian_factory()
            guardian_enter_attempted = True
            guardian = guardian_context.__enter__()
            driver = driver_factory(process, guardian, run_id=manifest['run_id'])
            guarded_driver = _DispatchDriver(driver, reference, context, owner)
            for _ in range(steps):
                _load(reference)
                _expect_owner(context, owner)
                if count >= manifest['max_actions']:
                    _fail('The immutable execution action budget is exhausted.')
                sequence += 1
                receipt = driver.capture(manifest['hwnd'], captures / f'{sequence:04d}.png', sequence=sequence)
                value = observer(deepcopy(receipt)) if observer is not None else None
                _load(reference)
                _expect_owner(context, owner)
                if value is None:
                    journal.append({'event': 'capture', 'receipt': receipt})
                    journal.append({'event': 'execution_paused', 'detail': 'Fresh frame retained; no proved classification provider.'}, status='paused')
                    break
                observation = _classified(receipt, value)
                journal.append({'event': 'observation', 'value': asdict(observation)})
                action = perform_action(run, guarded_driver, observation, journal)
                count += 1
                if action.kind == 'close':
                    break
            else:
                journal.append({'event': 'execution_paused', 'detail': 'The bounded invocation ended; resuming requires another fresh frame.'}, status='paused')
        except BaseException as exc:
            primary_error = exc
            interrupted = not isinstance(exc, Exception)
            try:
                journal.append({'event': 'cleanup_failure' if interrupted else 'execution_paused',
                                'detail': str(exc)}, status='paused')
            except BaseException as journal_error:
                exc.add_note('Could not retain the execution pause: ' + str(journal_error))
            raise
        finally:
            _finish_input_scope(journal, driver, guardian_context, guardian_enter_attempted, primary_error, interrupted)
        return {'format': FORMAT, 'run_id': manifest['run_id'], 'manifest_sha256': reference['sha256'],
                'status': journal.value['status'], 'actions_recorded': count, 'last_sequence': sequence,
                'journal': str(journal.path), 'acceptance': 'not_established',
                'detail': 'Baseline observation only; native item scenarios and launch/save operations are unavailable.'}


def _exit_recovery_request(reference, *, terminal=False):
    request = _json(reference)
    if (not isinstance(request, dict) or set(request) != {
            'format', 'execution', 'cancelled_journal', 'directory', 'expires_utc'}
            or request['format'] != EXIT_RECOVERY_FORMAT):
        _fail('Unsupported bounded exit cleanup request.')
    try:
        expires = datetime.strptime(request['expires_utc'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise DeviceRunError('Invalid exit cleanup expiry.') from exc
    if not terminal:
        _expiry(request['expires_utc'])
        if (expires - datetime.now(timezone.utc)).total_seconds() > 300:
            _fail('Exit cleanup authority must expire within five minutes.')
    _reference(request['execution'])
    _reference(request['cancelled_journal'])
    return request


def _exit_recovery_evidence(reference, clock, *, terminal=False):
    """Immutable history only; terminal bookkeeping never needs a live game."""
    request = _exit_recovery_request(reference, terminal=terminal)
    manifest = _json(request['execution'])
    if not isinstance(manifest, dict) or manifest.get('format') != FORMAT:
        _fail('The cleanup predecessor execution manifest changed.')
    process = ProcessIdentity(**manifest['process'])
    previous = saves._absolute(manifest['run_directory'])
    context = live_saves.LiveSaveContext(saves._absolute(manifest['live_context']['directory']),
                                         manifest['live_context']['manifest_sha256'])
    _json({'path': str(context.directory / 'manifest.json'), 'sha256': context.manifest_sha256})
    predecessor = request['cancelled_journal']
    if saves._absolute(predecessor['path']) != previous / 'device-run.json':
        _fail('Exit cleanup must pin the original cancelled execution journal.')
    journal = _journal(previous, manifest['run_id'])
    old, _, _ = _reconstruct(request['execution'], manifest, process, journal, clock, allow_failed_focus=True)
    events = journal.value['events']
    legacy = [index for index, row in enumerate(events) if row.get('event') == 'failure'
              and row.get('detail') == 'The owned game has not exited; preserve evidence before recovery.'
              and index > 0 and events[index - 1].get('event') == 'intent'
              and events[index - 1].get('action') == {'kind': 'close', 'sequence': events[index - 1]['action']['sequence'],
                                                     'point': None, 'key': ''}]
    if old.state != 'cancelled' or not old.exit_requested or len(legacy) != 1 or 'close' not in manifest['allowed_actions']:
        _fail('Exit cleanup requires one exact cancelled legacy close request with complete input cleanup.')
    folder = saves._absolute(request['directory'])
    if folder.parent != previous or not re.fullmatch('exit-recovery-[A-Za-z0-9_-]{1,64}', folder.name):
        _fail('Exit cleanup must use a new named child of its original execution directory.')
    return request, manifest, context, process, previous, folder


def _load_exit_recovery(reference, clock):
    result = _exit_recovery_evidence(reference, clock)
    request, manifest, context, process, previous, folder = result
    current_manifest, current_context, current_process, current_folder = _load(request['execution'])
    if (current_manifest != manifest or current_context != context or current_process != process or current_folder != previous
            or process_identity(process.pid) != process):
        _fail('The legitimately bound game process birth identity changed.')
    return result


def _exit_observation(observation, manifest):
    if (observation.screen != 'exit_confirmation' or observation.control != 'confirm_exit_hold'
            or observation.save_id != manifest['save_id'] or observation.foreground is not True):
        _fail('Exit cleanup requires a fresh exact foreground exit confirmation for the owned save.')


def _read_exit_recovery(reference, request, manifest, process, journal, clock, *, terminal=False):
    events = journal.value['events']
    if (not events or set(events[0]) != {'event', 'binding', 'started_at'}
            or events[0]['event'] != 'exit_recovery_started' or events[0]['binding'] != _binding(reference)
            or type(events[0]['started_at']) not in (int, float)
            or not math.isfinite(events[0]['started_at']) or not 0 <= events[0]['started_at'] <= clock()):
        _fail('The cleanup journal does not bind this immutable request and clock.')
    active, sequence, latest, observed_at = False, 0, None, events[0]['started_at']
    replay_time = [observed_at]
    run = _Policy(manifest, process, lambda: replay_time[0])
    run.state, run.exit_requested = 'closing', True
    observation = pending = None
    count, cancelled = 0, False
    for row in events[1:]:
        if not isinstance(row, dict):
            _fail('Unknown exit cleanup journal event.')
        kind = row.get('event')
        if cancelled or (run.state == 'finished' and kind != 'input_scope_released'):
            _fail('The terminal exit cleanup has unexpected later events.')
        if kind == 'intent':
            if not terminal:
                _fail('Exit confirmation was already attempted; preserve this cleanup journal and do not retry input.')
            if not active or observation is None or pending is not None or count:
                _fail('Exit cleanup has no unique owned confirmation intent.')
            pending = run.next_action(observation)
            if (pending.kind != 'close' or pending.key != 'SPACE_CONFIRM'
                    or canonical(row) != canonical(run.events[-1])):
                _fail('Exit cleanup intent does not match its fixed observed confirmation.')
        elif kind == 'result':
            if (not terminal or pending is None or set(row) != {'event', 'action', 'success', 'detail'}
                    or canonical(row['action']) != canonical(asdict(pending)) or row['success'] is not True
                    or not isinstance(row['detail'], str)):
                _fail('Exit cleanup lacks an exact successful owned exit result.')
            run.complete_action(pending, success=True, detail=row['detail'])
            pending = None
            count += 1
        elif kind == 'input_scope_started':
            if set(row) != {'event'} or active:
                _fail('Unknown or overlapping exit cleanup input scope.')
            active, latest, observation = True, None, None
        elif kind == 'input_scope_released':
            if set(row) != {'event'} or not active or pending is not None:
                _fail('Exit cleanup completion has no owned input scope.')
            active = False
        elif kind == 'capture':
            receipt = row.get('receipt')
            if (not active or set(row) != {'event', 'receipt'} or not isinstance(receipt, dict)
                    or receipt.get('run_id') != manifest['run_id'] or receipt.get('process') != asdict(process)
                    or type(receipt.get('sequence')) is not int or receipt['sequence'] <= sequence
                    or type(receipt.get('captured_at')) not in (int, float)
                    or not math.isfinite(receipt['captured_at'])
                    or not observed_at <= receipt['captured_at'] <= clock()
                    or receipt.get('window', {}).get('hwnd') != manifest['hwnd']):
                _fail('Invalid retained exit cleanup capture.')
            _retained_frame(journal.folder, receipt['sequence'], receipt.get('path'), receipt.get('sha256'))
            sequence, observed_at, latest = receipt['sequence'], receipt['captured_at'], receipt
            replay_time[0] = observed_at
        elif kind == 'observation':
            if not active or latest is None or set(row) != {'event', 'value'}:
                _fail('Exit cleanup observation has no current owned capture.')
            observation = _observation(row['value'])
            classification = {key: row['value'][key] for key in (
                'screen', 'foreground', 'control', 'point', 'save_id', 'gameplay_witness', 'scenario', 'assertion')}
            if canonical(asdict(_classified(latest, classification))) != canonical(row['value']):
                _fail('Exit cleanup observation changed its capture identity.')
            _exit_observation(observation, manifest)
        elif kind == 'exit_recovery_cancelled':
            if not terminal or set(row) != {'event'} or active or count or pending is not None:
                _fail('Exit cleanup cancellation does not establish zero input and complete release.')
            cancelled = True
        elif kind in ('execution_paused', 'failure'):
            if not active or set(row) != {'event', 'detail'} or not isinstance(row['detail'], str):
                _fail('Unknown exit cleanup pause record.')
        else:
            _fail('Exit cleanup is incomplete or unknown; preserve its evidence before recovery.')
    if active or pending is not None:
        _fail('Exit cleanup input release was not established; do not retry input.')
    if terminal:
        if not ((cancelled and count == 0 and journal.value['status'] == 'cancelled')
                or (not cancelled and count == 1 and run.state == 'finished' and journal.value['status'] == 'finished')):
            _fail('Exit cleanup terminal status lacks matching completion or zero-input cancellation evidence.')
    elif journal.value['status'] not in ('prepared', 'paused'):
        _fail('Exit cleanup input release was not established; do not retry input.')
    return sequence, events[0]['started_at']


def _validate_exit_recovery_terminal(reference, journal, clock):
    values = _exit_recovery_evidence(reference, clock, terminal=True)
    request, manifest, context, process, previous, folder = values
    if journal.folder != folder or journal.value['run_id'] != manifest['run_id']:
        _fail('The terminal cleanup journal belongs to a different request.')
    _read_exit_recovery(reference, request, manifest, process, journal, clock, terminal=True)
    return values


def reconcile_exit_recovery(reference, *, clock=time.monotonic):
    """Restore only terminal logical ownership, without any live-game API call."""
    reference = _snapshot_reference(reference)
    values = _exit_recovery_evidence(reference, clock, terminal=True)
    request, manifest, context, process, previous, folder = values
    with installation_lane(context.directory):
        journal = _journal(folder, manifest['run_id'])
        _validate_exit_recovery_terminal(reference, journal, clock)
        original = {'format': OWNER_FORMAT, 'run_id': manifest['run_id'],
                    'binding': _binding(request['execution']), 'directory': str(previous)}
        cleanup = {**original, 'binding': _binding(reference), 'directory': str(folder)}
        observed = _read(_owner_path(context))
        if observed == canonical(cleanup):
            atomic_write_bytes(_owner_path(context), canonical(original))
        elif observed != canonical(original):
            _fail('Unknown terminal cleanup ownership; no owner record was replaced.')
        return {'format': EXIT_RECOVERY_FORMAT, 'status': journal.value['status'],
                'owner_reconciled': True, 'actions_sent': [], 'acceptance': 'not_established'}


def cancel_exit_recovery(reference, *, clock=time.monotonic):
    """Cancel only a released cleanup with no input intent, including after expiry."""
    reference = _snapshot_reference(reference)
    request, manifest, context, process, previous, folder = _exit_recovery_evidence(reference, clock, terminal=True)
    with installation_lane(context.directory):
        journal = _journal(folder, manifest['run_id'])
        if journal.value['status'] == 'cancelled':
            return reconcile_exit_recovery(reference, clock=clock)
        _read_exit_recovery(reference, request, manifest, process, journal, clock)
        owner = {'format': OWNER_FORMAT, 'run_id': manifest['run_id'],
                 'binding': _binding(reference), 'directory': str(folder)}
        _expect_owner(context, owner)
        journal.append({'event': 'exit_recovery_cancelled'}, status='cancelled')
        return reconcile_exit_recovery(reference, clock=clock)


def recover_exit_execution(reference, *, observer=None, resume=False, clock=time.monotonic,
                           driver_factory=WindowsGameDriver, guardian_factory=InputGuardian):
    """One separately authorized cleanup hold after a cancelled expired run.

    The immutable request lasts at most five minutes. No prior deadline or
    journal changes. Every invocation captures anew; absent classification
    pauses without input. An existing input intent always prohibits a retry.
    """
    reference = _snapshot_reference(reference)
    request, manifest, context, process, previous, folder = _load_exit_recovery(reference, clock)
    original_owner = {'format': OWNER_FORMAT, 'run_id': manifest['run_id'],
                      'binding': _binding(request['execution']), 'directory': str(previous)}
    owner = {**original_owner, 'binding': _binding(reference), 'directory': str(folder)}
    with installation_lane(context.directory):
        request, manifest, context, process, previous, folder = _load_exit_recovery(reference, clock)
        if resume:
            journal = _journal(folder, manifest['run_id'])
            sequence, started = _read_exit_recovery(reference, request, manifest, process, journal, clock)
            _expect_owner(context, owner)
        else:
            _competition(request['execution'], manifest, context, previous)
            _expect_owner(context, original_owner)
            if folder.exists():
                _fail('The cleanup directory already exists; explicitly reconcile it instead of replacing evidence.')
            journal = RunJournal(folder, run_id=manifest['run_id'], create=True)
            started, sequence = clock(), 0
            journal.append({'event': 'exit_recovery_started', 'binding': _binding(reference), 'started_at': started})
            atomic_write_bytes(_owner_path(context), canonical(owner))
        captures = folder / 'captures'
        captures.mkdir(exist_ok=True)
        run = _Policy(manifest, process, clock)
        run.state, run.entered, run.exit_requested = 'closing', started, True
        journal.append({'event': 'input_scope_started'})
        guardian_context = guardian = driver = primary_error = None
        entered, interrupted = False, False
        try:
            guardian_context = guardian_factory()
            entered = True
            guardian = guardian_context.__enter__()
            driver = driver_factory(process, guardian, run_id=manifest['run_id'])
            sequence += 1
            receipt = driver.capture(manifest['hwnd'], captures / f'{sequence:04d}.png', sequence=sequence)
            journal.append({'event': 'capture', 'receipt': receipt})
            value = observer(deepcopy(receipt)) if observer is not None else None
            _load_exit_recovery(reference, clock)
            _expect_owner(context, owner)
            if value is None:
                journal.append({'event': 'execution_paused', 'detail': 'Fresh exit cleanup frame retained; exact classification is required.'}, status='paused')
            else:
                observation = _classified(receipt, value)
                _exit_observation(observation, manifest)
                journal.append({'event': 'observation', 'value': asdict(observation)})
                def guard():
                    _exit_recovery_request(reference)
                    if hash_file(journal.path) != journal.checksum:
                        _fail('The cleanup action journal changed before dispatch.')
                guarded = _DispatchDriver(driver, request['execution'], context, owner, extra_guard=guard)
                action = perform_action(run, guarded, observation, journal)
                if action.kind != 'close' or action.key != 'SPACE_CONFIRM':
                    _fail('The cleanup action exceeded its single exit-confirmation contract.')
        except BaseException as exc:
            primary_error, interrupted = exc, not isinstance(exc, Exception)
            try:
                journal.append({'event': 'cleanup_failure' if interrupted else 'execution_paused', 'detail': str(exc)}, status='paused')
            except BaseException as journal_error:
                exc.add_note('Could not retain the exit cleanup pause: ' + str(journal_error))
            raise
        finally:
            _finish_input_scope(journal, driver, guardian_context, entered, primary_error, interrupted)
        complete = journal.value['status'] == 'finished'
        if complete:
            reconcile_exit_recovery(reference, clock=clock)
        return {'format': EXIT_RECOVERY_FORMAT, 'run_id': manifest['run_id'], 'request_sha256': reference['sha256'],
                'status': 'finished' if complete else 'paused', 'cleanup_only': True,
                'game_exit_verified': complete, 'actions_recorded': int(complete), 'last_sequence': sequence,
                'journal': str(journal.path), 'acceptance': 'not_established'}
