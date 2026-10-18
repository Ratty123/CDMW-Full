"""Copied-fixture execution receipts; these tests never operate a live desktop."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cdmw.services import cditem_device_execution as execution
from cdmw.services.cditem_device_runner import DeviceRunError, ProcessIdentity, RunJournal
from cdmw.services.independent_item_package import canonical, digest


@pytest.fixture
def setup(tmp_path, monkeypatch):
    game = tmp_path / 'game'
    (game / 'bin64').mkdir(parents=True)
    (game / '.cdmw/virtual-loader').mkdir(parents=True)
    context = tmp_path / 'context'
    context.mkdir()
    save = tmp_path / 'save'
    save.mkdir()
    runs = tmp_path / 'runs'
    runs.mkdir()
    now, performed, captures, releases = [100.0], [], [], []

    def write(path, value):
        path.write_bytes(canonical(value) if not isinstance(value, bytes) else value)
        return {'path': str(path), 'sha256': digest(path.read_bytes())}

    image = write(game / 'bin64/CrimsonDesert.exe', b'owned executable')
    process = ProcessIdentity(42, 123456789123, image['path'], image['sha256'], 1)
    profile = write(game / '.cdmw/virtual-loader/profile.json', b'exact profile')
    runtime = [write(game / 'bin64' / name, name.encode())
               for name in ('CDMWVirtualLoader.asi', 'winmm.dll', 'OtherMod.asi')]
    native = write(game / '.cdmw/virtual-loader' / ('session-' + 'a' * 32 + '.json'), b'actual native status')
    retained = write(tmp_path / 'native-report.json', b'actual native status')
    session = write(tmp_path / 'session.json', {'session_token': 'a' * 32, 'native_report': retained})
    request = write(tmp_path / 'request.json', {'game_root': str(game), 'game_sha256': image['sha256'],
                                              'save_root': str(save), 'profile_sha256': profile['sha256']})
    cm = write(context / 'manifest.json', {'request': request})
    write(context / 'journal.json', {'session_receipt': session})
    bound = {'run_id': 'run-12345678', 'phase': 'active', 'owned_game': asdict(process)}
    monkeypatch.setattr(execution.live_saves, 'inspect_live_context', lambda value: dict(bound))
    monkeypatch.setattr(execution.live_saves, '_owner', lambda *a, **kw: True)
    monkeypatch.setattr(execution, 'process_identity', lambda pid: process)
    monkeypatch.setattr(execution, 'window_identity', lambda hwnd, owned: execution.WindowIdentity(hwnd, (0, 0, 1000, 800), 96))
    monkeypatch.setattr(execution, 'desktop_preflight', lambda: {'usable': True, 'session': 1})
    manifest = {
        'format': execution.FORMAT, 'run_id': bound['run_id'], 'game_root': str(game),
        'scenario': 'baseline_observation', 'save_id': 'disposable-100', 'process': asdict(process),
        'hwnd': 77, 'live_context': {'directory': str(context), 'manifest_sha256': cm['sha256']},
        'session_receipt': session, 'profile': profile, 'runtime': runtime,
        'guards': [image, native], 'allowed_actions': sorted(execution.ACTIONS),
        'timeouts': dict(execution.DEFAULT_TIMEOUTS), 'run_directory': str(runs / 'run-12345678'),
        'expires_utc': (datetime.now(timezone.utc) + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'max_actions': 32,
    }
    reference = write(tmp_path / 'execution.json', manifest)

    class Guardian:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            releases.append('guardian')

    class Driver:
        def __init__(self, owned, guardian, *, run_id):
            assert owned == process and run_id == manifest['run_id']
        def capture(self, hwnd, output, *, sequence):
            assert hwnd == 77
            output.write_bytes(b'frame ' + str(sequence).encode())
            captures.append(sequence)
            self.receipt = {'run_id': manifest['run_id'], 'sequence': sequence, 'captured_at': now[0],
                            'process': asdict(process), 'window': {'hwnd': hwnd, 'client': [0, 0, 1000, 800], 'dpi': 96},
                            'path': str(output), 'sha256': digest(output.read_bytes()), 'input_tick': 123,
                            'inspection': 'required'}
            return dict(self.receipt)
        def verify_observation(self, value):
            assert value.sequence == self.receipt['sequence']
            assert value.screenshot_sha256 == self.receipt['sha256']
            assert value.process == process
            if not 0 <= now[0] - value.captured_at <= 5:
                raise DeviceRunError('The screenshot observation is stale.')
        def perform(self, action, observation):
            journal = RunJournal(manifest['run_directory'], run_id=manifest['run_id'])
            assert journal.value['events'][-1]['event'] == 'intent'
            performed.append(action)
            now[0] += 0.25
        def release_inputs(self):
            releases.append('driver')

    def classify(screen, **kwargs):
        return {'screen': screen, 'foreground': True, 'control': '', 'point': None,
                'save_id': '', 'gameplay_witness': '', 'scenario': '', 'assertion': '', **kwargs}

    def run(*, observer=None, resume=False, steps=1, driver=Driver, guardian=Guardian):
        return execution.execute_execution(reference, resume=resume, observer=observer, steps=steps,
                                           clock=lambda: now[0], driver_factory=driver, guardian_factory=guardian)

    return locals()


def test_capture_only_pause_and_resume_use_new_frames_without_input(setup):
    s = setup
    first = s['run']()
    second = s['run'](resume=True)
    assert first['status'] == second['status'] == 'paused'
    assert second['last_sequence'] == 2 and second['actions_recorded'] == 0
    assert s['captures'] == [1, 2] and s['performed'] == []
    assert second['acceptance'] == 'not_established'
    assert s['releases'] == ['driver', 'guardian', 'driver', 'guardian']


def test_complete_baseline_records_observations_before_input_and_ordinary_close(setup):
    s = setup
    classify = s['classify']
    observations = iter([
        classify('title_gamepad', control='activate_keyboard', point=[10, 10]),
        classify('main_menu', control='open_load', point=[20, 20]),
        classify('load_menu', control='select_save', point=[30, 30], save_id='disposable-100'),
        classify('loading'),
        classify('gameplay', save_id='disposable-100', gameplay_witness='visible controlled character and world'),
        classify('scenario_result', save_id='disposable-100', scenario='baseline_observation', assertion='baseline retained'),
    ])
    result = s['run'](observer=lambda frame: next(observations), steps=6)
    assert result['status'] == 'finished' and result['actions_recorded'] == 6
    assert [x.kind for x in s['performed']] == ['click', 'click', 'click', 'wait', 'observe_baseline', 'close']
    journal = execution._journal(Path(s['manifest']['run_directory']), s['manifest']['run_id'])
    rebuilt, sequence, count = execution._reconstruct(s['reference'], s['manifest'], s['process'], journal, lambda: s['now'][0])
    assert rebuilt.state == 'finished' and sequence == count == 6
    assert result['acceptance'] == 'not_established'


def test_resume_reconstructs_prior_mouse_activation_without_blind_e(setup):
    s = setup
    s['run'](observer=lambda frame: s['classify']('title_gamepad', control='activate_keyboard', point=[10, 10]))
    result = s['run'](resume=True, observer=lambda frame: s['classify']('main_menu', control='open_load', point=[20, 20]))
    assert result['actions_recorded'] == 2
    assert [x.kind for x in s['performed']] == ['click', 'click']
    assert s['captures'] == [1, 2]


def test_execution_records_return_save_selection_and_resumes_without_repeating_it(setup):
    s = setup
    def observe(frame):
        return s['classify']('load_menu', control='select_save_key', save_id='disposable-100')
    first = s['run'](observer=observe)
    second = s['run'](resume=True, observer=observe)
    assert first['actions_recorded'] == 1 and second['actions_recorded'] == 2
    assert [(action.kind, action.key) for action in s['performed']] == [('key', 'RETURN'), ('wait', '')]
    assert s['captures'] == [1, 2]
    journal = execution._journal(Path(s['manifest']['run_directory']), s['manifest']['run_id'])
    run, _, _ = execution._reconstruct(s['reference'], s['manifest'], s['process'], journal, lambda: s['now'][0])
    assert run.selected_save and run.state == 'menu'


@pytest.mark.parametrize('control,key', [('select_save_space', 'SPACE'), ('select_save_key', 'RETURN')])
def test_execution_distinct_save_keys_remain_replayable_and_cancellable(setup, control, key):
    s = setup
    def observe(frame):
        return s['classify']('load_menu', control=control, save_id='disposable-100')
    s['run'](observer=observe)
    s['run'](resume=True, observer=observe)
    assert [(action.kind, action.key) for action in s['performed']] == [('key', key), ('wait', '')]
    journal = execution._journal(Path(s['manifest']['run_directory']), s['manifest']['run_id'])
    run, _, count = execution._reconstruct(s['reference'], s['manifest'], s['process'], journal, lambda: s['now'][0])
    assert run.selected_save and count == 2
    result = execution.cancel_execution(s['reference'], clock=lambda: s['now'][0])
    assert result['status'] == 'cancelled' and result['actions_sent_by_cancellation'] == []
    assert result['actions_recorded'] == 2 and s['captures'] == [1, 2]


def test_observed_save_confirmation_reconstructs_without_repeating_space(setup):
    s = setup
    s['run'](observer=lambda frame: s['classify']('load_menu', control='select_save_space', save_id='disposable-100'))
    confirmation = lambda frame: s['classify']('load_confirmation', control='confirm_load_space', save_id='disposable-100')
    s['run'](resume=True, observer=confirmation)
    s['run'](resume=True, observer=confirmation)
    assert [(action.kind, action.key) for action in s['performed']] == [('key', 'SPACE'), ('key', 'SPACE'), ('wait', '')]
    journal = execution._journal(Path(s['manifest']['run_directory']), s['manifest']['run_id'])
    run, _, count = execution._reconstruct(s['reference'], s['manifest'], s['process'], journal, lambda: s['now'][0])
    assert run.selected_save and run.save_confirmed and count == 3
    assert execution.cancel_execution(s['reference'], clock=lambda: s['now'][0])['status'] == 'cancelled'


def test_short_confirmation_then_fixed_hold_reconstructs_and_cancels_without_repeating(setup):
    s = setup
    select = lambda frame: s['classify']('load_menu', control='select_save_space', save_id='disposable-100')
    short = lambda frame: s['classify']('load_confirmation', control='confirm_load_space', save_id='disposable-100')
    hold = lambda frame: s['classify']('load_confirmation', control='confirm_load_hold', save_id='disposable-100')
    s['run'](observer=select)
    s['run'](resume=True, observer=short)
    s['run'](resume=True, observer=hold)
    s['run'](resume=True, observer=hold)
    s['run'](resume=True, observer=short)
    assert [(action.kind, action.key) for action in s['performed']] == [
        ('key', 'SPACE'), ('key', 'SPACE'), ('key', 'SPACE_CONFIRM'), ('wait', ''), ('wait', '')]
    journal = execution._journal(Path(s['manifest']['run_directory']), s['manifest']['run_id'])
    run, _, count = execution._reconstruct(s['reference'], s['manifest'], s['process'], journal, lambda: s['now'][0])
    assert run.selected_save and run.save_confirmed and run.save_hold_confirmed and count == 5
    assert execution.cancel_execution(s['reference'], clock=lambda: s['now'][0])['status'] == 'cancelled'
    assert len(s['performed']) == 5


def test_ambiguous_action_failure_cannot_resume_or_replay_input(setup):
    s = setup
    class Failed(s['Driver']):
        def perform(self, action, observation):
            super().perform(action, observation)
            raise DeviceRunError('Input happened but confirmation failed')
    with pytest.raises(DeviceRunError, match='confirmation failed'):
        s['run'](observer=lambda frame: s['classify']('title_keyboard', control='press_e'), driver=Failed)
    with pytest.raises(DeviceRunError, match='unfinished prior action'):
        s['run'](resume=True)
    assert len(s['performed']) == 1 and s['captures'] == [1]


def test_cleanup_failure_remains_a_resume_blocker(setup):
    s = setup
    class Guardian(s['Guardian']):
        def __exit__(self, *args):
            raise DeviceRunError('input guardian did not exit')
    with pytest.raises(DeviceRunError, match='guardian did not exit'):
        s['run'](guardian=Guardian)
    with pytest.raises(DeviceRunError, match='Input cleanup'):
        s['run'](resume=True)
    assert s['performed'] == []


def test_cleanup_journal_failure_cannot_skip_guardian_exit(setup, monkeypatch):
    s = setup
    original = RunJournal.append
    def append(self, event, *, status=None):
        if event['event'] == 'cleanup_failure':
            raise OSError('receipt disk unavailable')
        return original(self, event, status=status)
    monkeypatch.setattr(RunJournal, 'append', append)
    class Driver(s['Driver']):
        def release_inputs(self):
            raise DeviceRunError('driver release failed')
    with pytest.raises(DeviceRunError, match='driver release failed') as caught:
        s['run'](driver=Driver)
    assert s['releases'] == ['guardian']
    assert any('receipt disk unavailable' in note for note in caught.value.__notes__)


@pytest.mark.parametrize('receipt_write_fails', [False, True])
def test_cleanup_interrupt_always_exits_guardian_and_blocks_resume(setup, monkeypatch, receipt_write_fails):
    s = setup
    if receipt_write_fails:
        append = RunJournal.append
        def failed_receipt(self, event, *, status=None):
            if event['event'] == 'cleanup_failure':
                raise OSError('interrupted cleanup receipt cannot be written')
            return append(self, event, status=status)
        monkeypatch.setattr(RunJournal, 'append', failed_receipt)
    class Driver(s['Driver']):
        def release_inputs(self):
            s['releases'].append('interrupted driver')
            raise KeyboardInterrupt('copied-fixture cleanup interruption')
    with pytest.raises(KeyboardInterrupt, match='copied-fixture cleanup interruption'):
        s['run'](driver=Driver)
    assert s['releases'] == ['interrupted driver', 'guardian']
    journal = execution._journal(Path(s['manifest']['run_directory']), s['manifest']['run_id'])
    kinds = [event['event'] for event in journal.value['events']]
    assert 'input_scope_started' in kinds and 'input_scope_released' not in kinds
    assert ('cleanup_failure' in kinds) is not receipt_write_fails
    with pytest.raises(DeviceRunError, match='Input cleanup'):
        s['run'](resume=True)
    assert s['captures'] == [1] and s['performed'] == []


def test_interrupted_cleanup_preserves_primary_error_and_attempts_every_release(setup):
    s = setup
    class Driver(s['Driver']):
        def release_inputs(self):
            s['releases'].append('driver')
            raise KeyboardInterrupt('release interrupted')
    class Guardian(s['Guardian']):
        def __exit__(self, *args):
            s['releases'].append('guardian')
            raise SystemExit('guardian interrupted')
    def observer(frame):
        raise DeviceRunError('primary observer failure')
    with pytest.raises(DeviceRunError, match='primary observer failure') as caught:
        s['run'](observer=observer, driver=Driver, guardian=Guardian)
    assert s['releases'] == ['driver', 'guardian']
    assert any('release interrupted' in note for note in caught.value.__notes__)
    assert any('guardian interrupted' in note for note in caught.value.__notes__)
    with pytest.raises(DeviceRunError, match='Input cleanup'):
        s['run'](resume=True)


@pytest.mark.parametrize('classification', [True, False])
def test_owner_change_in_callback_refuses_before_input(setup, classification):
    s = setup
    def observer(frame):
        (s['context'] / 'device-execution-owner.json').write_bytes(b'{"unrecognized":true}')
        return s['classify']('title_keyboard', control='press_e') if classification else None
    with pytest.raises(DeviceRunError, match='ownership record changed'):
        s['run'](observer=observer)
    assert s['captures'] == [1] and s['performed'] == []
    assert s['releases'] == ['driver', 'guardian']


@pytest.mark.parametrize('changed', ['owner', 'runtime'])
def test_guard_change_after_observation_verification_refuses_at_dispatch(setup, changed):
    s = setup
    class Driver(s['Driver']):
        def verify_observation(self, observation):
            super().verify_observation(observation)
            if changed == 'owner':
                (s['context'] / 'device-execution-owner.json').write_bytes(b'unknown dispatch owner')
            else:
                Path(s['runtime'][0]['path']).write_bytes(b'changed at dispatch')
    with pytest.raises(DeviceRunError, match='ownership record changed|input changed'):
        s['run'](observer=lambda frame: s['classify']('title_keyboard', control='press_e'), driver=Driver)
    assert s['performed'] == []


def test_pausing_does_not_reset_deadline(setup):
    s = setup
    s['run'](observer=lambda frame: s['classify']('title_keyboard', control='press_e'))
    s['now'][0] += s['manifest']['timeouts']['title'] + 1
    with pytest.raises(DeviceRunError, match='title.*deadline'):
        s['run'](resume=True, observer=lambda frame: s['classify']('title_keyboard', control='press_e'))
    assert len(s['performed']) == 1


def test_changed_guard_after_observer_refuses_before_input(setup):
    s = setup
    def observer(frame):
        Path(s['runtime'][0]['path']).write_bytes(b'changed runtime')
        return s['classify']('title_keyboard', control='press_e')
    with pytest.raises(DeviceRunError, match='input changed'):
        s['run'](observer=observer)
    assert s['performed'] == []


def test_expired_or_unbound_manifest_is_read_only_refusal(setup, monkeypatch):
    s = setup
    s['bound']['owned_game'] = None
    with pytest.raises(DeviceRunError, match='has not bound'):
        execution.preflight_execution(s['reference'], clock=lambda: s['now'][0])
    assert not Path(s['manifest']['run_directory']).exists()
    assert not execution._owner_path(execution.live_saves.LiveSaveContext(s['context'], s['cm']['sha256'])).exists()


@pytest.mark.parametrize('change,match', [
    (lambda s: s['manifest'].update(scenario='new-native-id'), 'baseline scenario'),
    (lambda s: s['manifest'].update(allowed_actions=['register_item']), 'action contract'),
    (lambda s: s['manifest'].update(timeouts={'title': 1}), 'Every device state'),
    (lambda s: s['manifest'].update(expires_utc='2000-01-01T00:00:00Z'), 'expired'),
    (lambda s: s['manifest'].update(run_directory=str(s['game'] / 'run')), 'separate parent'),
])
def test_exact_manifest_scope_refusals(setup, change, match):
    s = setup
    change(s)
    s['reference'].update(s['write'](Path(s['reference']['path']), s['manifest']))
    with pytest.raises(DeviceRunError, match=match):
        execution.preflight_execution(s['reference'], clock=lambda: s['now'][0])
    assert s['performed'] == []


def test_changed_process_birth_and_runtime_inventory_refuse(setup, monkeypatch):
    s = setup
    monkeypatch.setattr(execution, 'process_identity', lambda pid: replace(s['process'], created=s['process'].created + 1))
    with pytest.raises(DeviceRunError, match='birth identity changed'):
        execution.preflight_execution(s['reference'], clock=lambda: s['now'][0])
    monkeypatch.setattr(execution, 'process_identity', lambda pid: s['process'])
    (s['game'] / 'bin64/NewMod.asi').write_bytes(b'external new mod')
    with pytest.raises(DeviceRunError, match='ASI inventory changed'):
        execution.preflight_execution(s['reference'], clock=lambda: s['now'][0])


def test_changed_frame_or_manifest_refuses_resume(setup):
    s = setup
    s['run']()
    capture = Path(s['manifest']['run_directory']) / 'captures/0001.png'
    capture.write_bytes(b'changed')
    with pytest.raises(DeviceRunError, match='frame changed'):
        s['run'](resume=True)
    assert s['captures'] == [1]
    Path(s['reference']['path']).write_bytes(b'{}')
    with pytest.raises(DeviceRunError, match='evidence changed'):
        s['run'](resume=True)


def test_disallowed_action_is_never_sent(setup):
    s = setup
    s['manifest']['allowed_actions'] = ['wait']
    s['reference'].update(s['write'](Path(s['reference']['path']), s['manifest']))
    with pytest.raises(DeviceRunError, match='outside this execution manifest'):
        s['run'](observer=lambda frame: s['classify']('title_keyboard', control='press_e'))
    assert s['performed'] == []
    # No intent was durably accepted, so a fresh capture may be requested.
    result = s['run'](resume=True)
    assert result['actions_recorded'] == 0 and s['captures'] == [1, 2]


def test_competing_unfinished_run_and_missing_owned_journal_refuse(setup):
    s = setup
    other = RunJournal(s['runs'] / 'other', run_id='other-12345678', create=True)
    with pytest.raises(DeviceRunError, match='competing unfinished'):
        execution.preflight_execution(s['reference'], clock=lambda: s['now'][0])
    assert not Path(s['manifest']['run_directory']).exists()
    # Preserve the competing fixture by moving it outside this run inventory.
    other.folder.rename(s['tmp_path'] / 'other-retained')
    s['run']()
    journal = Path(s['manifest']['run_directory']) / 'device-run.json'
    journal.rename(journal.with_suffix('.retained'))
    with pytest.raises(DeviceRunError, match='journal is missing'):
        s['run'](resume=True)


def test_read_only_preflight_creates_no_run_state(setup):
    s = setup
    before = sorted(str(p.relative_to(s['tmp_path'])) for p in s['tmp_path'].rglob('*'))
    result = execution.preflight_execution(s['reference'], clock=lambda: s['now'][0])
    after = sorted(str(p.relative_to(s['tmp_path'])) for p in s['tmp_path'].rglob('*'))
    assert before == after and result['ready']
    assert result['classification'] == 'required_for_each_fresh_capture'
    assert s['captures'] == s['performed'] == []


def test_zero_action_capture_can_cancel_and_preflight_separate_manifest(setup):
    s = setup
    original_bytes = Path(s['reference']['path']).read_bytes()
    s['run']()
    s['now'][0] += s['manifest']['timeouts']['title'] + 1
    result = execution.cancel_execution(s['reference'], clock=lambda: s['now'][0])
    assert result['status'] == 'cancelled' and result['actions_recorded'] == 0
    assert result['acceptance'] == 'not_established' and result['actions_sent_by_cancellation'] == []
    assert s['performed'] == [] and s['captures'] == [1]
    assert s['releases'] == ['driver', 'guardian']
    journal = execution._journal(Path(s['manifest']['run_directory']), s['manifest']['run_id'])
    assert journal.value['events'][-2:] == [{'event': 'input_scope_released'}, {'event': 'execution_cancelled'}]
    with pytest.raises(DeviceRunError, match='already cancelled'):
        s['run'](resume=True)
    with pytest.raises(DeviceRunError, match='already cancelled'):
        execution.cancel_execution(s['reference'], clock=lambda: s['now'][0])
    new_manifest = {**s['manifest'], 'run_directory': str(s['runs'] / 'calibration-2')}
    new_reference = s['write'](s['tmp_path'] / 'calibration-2.json', new_manifest)
    owner_before = (s['context'] / 'device-execution-owner.json').read_bytes()
    preflight = execution.preflight_execution(new_reference, clock=lambda: s['now'][0])
    assert preflight['ready'] and preflight['actions_recorded'] == 0
    assert Path(s['reference']['path']).read_bytes() == original_bytes
    assert (s['context'] / 'device-execution-owner.json').read_bytes() == owner_before
    assert not Path(new_manifest['run_directory']).exists()


@pytest.mark.parametrize('changed,match', [
    ('scope', 'Input cleanup'), ('cleanup', 'Input cleanup'),
    ('unknown', 'Unknown execution journal event'), ('owner', 'ownership'),
    ('runtime', 'input changed'), ('process', 'birth identity changed'),
    ('manifest', 'evidence changed'),
])
def test_cancellation_refuses_unknown_or_changed_state_without_writes(setup, monkeypatch, changed, match):
    s = setup
    s['run']()
    journal = execution._journal(Path(s['manifest']['run_directory']), s['manifest']['run_id'])
    if changed == 'scope':
        journal.append({'event': 'input_scope_started'}, status='paused')
    elif changed == 'cleanup':
        journal.append({'event': 'cleanup_failure', 'detail': 'cleanup remains unknown'}, status='paused')
    elif changed == 'unknown':
        journal.append({'event': 'unknown'} , status='paused')
    elif changed == 'owner':
        (s['context'] / 'device-execution-owner.json').write_bytes(b'{"unrecognized":true}')
    elif changed == 'runtime':
        Path(s['runtime'][0]['path']).write_bytes(b'changed loader')
    elif changed == 'process':
        monkeypatch.setattr(execution, 'process_identity', lambda pid: replace(s['process'], created=s['process'].created + 1))
    elif changed == 'manifest':
        Path(s['reference']['path']).write_bytes(b'{}')
    before = journal.path.read_bytes()
    with pytest.raises(DeviceRunError, match=match):
        execution.cancel_execution(s['reference'], clock=lambda: s['now'][0])
    assert journal.path.read_bytes() == before
    assert s['captures'] == [1] and s['performed'] == []


def test_pending_action_cannot_be_cancelled_as_recovery(setup):
    s = setup
    class Driver(s['Driver']):
        def perform(self, action, observation):
            super().perform(action, observation)
            raise DeviceRunError('confirmation unavailable')
    with pytest.raises(DeviceRunError, match='confirmation unavailable'):
        s['run'](observer=lambda frame: s['classify']('title_keyboard', control='press_e'), driver=Driver)
    before = (Path(s['manifest']['run_directory']) / 'device-run.json').read_bytes()
    with pytest.raises(DeviceRunError, match='unfinished prior action'):
        execution.cancel_execution(s['reference'], clock=lambda: s['now'][0])
    assert (Path(s['manifest']['run_directory']) / 'device-run.json').read_bytes() == before
    assert len(s['performed']) == 1


def _legacy_close_timeout_fixture(s, *, message='The owned game has not exited; preserve evidence before recovery.', confirmed=False):
    s['run'](observer=lambda frame: s['classify']('load_menu', control='select_save_space', save_id='disposable-100'))
    s['run'](resume=True, observer=lambda frame: s['classify']('gameplay', save_id='disposable-100', gameplay_witness='fresh world'))
    result = lambda frame: s['classify']('scenario_result', save_id='disposable-100',
        scenario='baseline_observation', assertion='baseline retained', control='request_exit' if confirmed else '')
    class Driver(s['Driver']):
        def perform(self, action, observation):
            assert action.kind == 'close' and action.key == ('SPACE_CONFIRM' if confirmed else '')
            raise DeviceRunError(message)
    if confirmed:
        s['run'](resume=True, observer=result)
    with pytest.raises(DeviceRunError, match=message):
        s['run'](resume=True, driver=Driver, observer=(lambda frame: s['classify'](
            'exit_confirmation', control='confirm_exit_hold', save_id='disposable-100')) if confirmed else result)
    return execution._journal(Path(s['manifest']['run_directory']), s['manifest']['run_id'])


def test_legacy_close_wait_failure_reconstructs_only_fresh_exit_confirmation(setup):
    s = setup
    journal = _legacy_close_timeout_fixture(s)
    closing, _, count = execution._reconstruct(s['reference'], s['manifest'], s['process'], journal, lambda: s['now'][0])
    entered = closing.entered
    assert closing.state == 'closing' and closing.exit_requested and count == 3
    assert s['run'](resume=True)['status'] == 'paused'
    journal = execution._journal(Path(s['manifest']['run_directory']), s['manifest']['run_id'])
    closing, _, _ = execution._reconstruct(s['reference'], s['manifest'], s['process'], journal, lambda: s['now'][0])
    assert closing.entered == entered
    result = s['run'](resume=True, observer=lambda frame: s['classify'](
        'exit_confirmation', control='confirm_exit_hold', save_id='disposable-100'))
    assert result['status'] == 'finished' and result['actions_recorded'] == 4
    assert [(a.kind, a.key) for a in s['performed']] == [('key', 'SPACE'), ('observe_baseline', ''), ('close', 'SPACE_CONFIRM')]


@pytest.mark.parametrize('changed', ['message', 'confirmed_key', 'cleanup', 'missing_release'])
def test_only_exact_clean_legacy_request_wait_failure_can_resume(setup, changed):
    s = setup
    journal = _legacy_close_timeout_fixture(s, message=('Other close failure' if changed == 'message' else
        'The owned game has not exited; preserve evidence before recovery.'), confirmed=changed == 'confirmed_key')
    if changed == 'cleanup':
        journal.append({'event': 'cleanup_failure', 'detail': 'unknown release'}, status='paused')
    elif changed == 'missing_release':
        journal.value['events'].pop()
        journal.value['revision'] -= 1
        journal._write()
    before = journal.path.read_bytes()
    with pytest.raises(DeviceRunError):
        execution.preflight_execution(s['reference'], resume=True, clock=lambda: s['now'][0])
    assert journal.path.read_bytes() == before


@pytest.mark.parametrize('screen,control,save_id', [
    ('modal', '', 'disposable-100'), ('main_menu', 'open_load_key', 'disposable-100'),
    ('exit_confirmation', 'unknown', 'disposable-100'), ('exit_confirmation', 'confirm_exit_hold', 'wrong-save'),
])
def test_legacy_close_recovery_never_guesses_other_screens_or_saves(setup, screen, control, save_id):
    s = setup
    _legacy_close_timeout_fixture(s)
    before = len(s['performed'])
    with pytest.raises(DeviceRunError):
        s['run'](resume=True, observer=lambda frame: s['classify'](screen, control=control, save_id=save_id))
    assert len(s['performed']) == before


def _exit_cleanup_fixture(s, *, legacy=True):
    old = _legacy_close_timeout_fixture(s) if legacy else None
    if not legacy:
        s['run']()
    s['now'][0] += s['manifest']['timeouts']['loading'] + 5
    execution.cancel_execution(s['reference'], clock=lambda: s['now'][0])
    previous = Path(s['manifest']['run_directory']) / 'device-run.json'
    request = {'format': execution.EXIT_RECOVERY_FORMAT, 'execution': dict(s['reference']),
               'cancelled_journal': {'path': str(previous), 'sha256': digest(previous.read_bytes())},
               'directory': str(previous.parent / 'exit-recovery-test'),
               'expires_utc': (datetime.now(timezone.utc) + timedelta(minutes=4)).strftime('%Y-%m-%dT%H:%M:%SZ')}
    reference = s['write'](s['tmp_path'] / 'exit-cleanup.json', request)
    class Driver(s['Driver']):
        def perform(self, action, observation):
            assert action.kind == 'close' and action.key == 'SPACE_CONFIRM'
            journal = RunJournal(request['directory'], run_id=s['manifest']['run_id'])
            assert journal.value['events'][-1]['event'] == 'intent'
            s['performed'].append(action)
            s['now'][0] += 0.25
    def run(*, observer=None, resume=False, driver=Driver, guardian=None):
        return execution.recover_exit_execution(reference, observer=observer, resume=resume,
            clock=lambda: s['now'][0], driver_factory=driver, guardian_factory=guardian or s['Guardian'])
    return {'request': request, 'reference': reference, 'run': run, 'Driver': Driver,
            'previous': previous, 'owner': (s['context'] / 'device-execution-owner.json').read_bytes()}


def test_separate_cleanup_capture_pause_then_single_exit_leaves_predecessor_unchanged(setup):
    s = setup
    cleanup = _exit_cleanup_fixture(s)
    old_journal = cleanup['previous'].read_bytes()
    old_manifest = Path(s['reference']['path']).read_bytes()
    before = len(s['performed'])
    paused = cleanup['run']()
    assert paused['status'] == 'paused' and not paused['game_exit_verified'] and paused['actions_recorded'] == 0
    assert len(s['performed']) == before
    closed = cleanup['run'](resume=True, observer=lambda frame: s['classify'](
        'exit_confirmation', control='confirm_exit_hold', save_id='disposable-100'))
    assert closed['status'] == 'finished' and closed['cleanup_only'] and closed['game_exit_verified']
    assert closed['actions_recorded'] == 1 and closed['acceptance'] == 'not_established'
    assert len(s['performed']) == before + 1
    assert cleanup['previous'].read_bytes() == old_journal
    assert Path(s['reference']['path']).read_bytes() == old_manifest
    assert (s['context'] / 'device-execution-owner.json').read_bytes() == cleanup['owner']
    with pytest.raises(DeviceRunError, match='already attempted'):
        cleanup['run'](resume=True)
    assert len(s['performed']) == before + 1


@pytest.mark.parametrize('screen,control,save_id,foreground', [
    ('modal', 'confirm_exit_hold', 'disposable-100', True),
    ('exit_confirmation', 'unknown', 'disposable-100', True),
    ('exit_confirmation', 'confirm_exit_hold', 'wrong-save', True),
    ('exit_confirmation', 'confirm_exit_hold', 'disposable-100', False),
])
def test_cleanup_refuses_unrecognized_or_unowned_prompt_without_input(setup, screen, control, save_id, foreground):
    s = setup
    cleanup = _exit_cleanup_fixture(s)
    before = len(s['performed'])
    with pytest.raises(DeviceRunError, match='fresh exact foreground exit confirmation'):
        cleanup['run'](observer=lambda frame: s['classify'](screen, control=control, save_id=save_id, foreground=foreground))
    assert len(s['performed']) == before
    assert cleanup['run'](resume=True)['last_sequence'] == 2


def test_cleanup_intent_failure_is_preserved_and_permanently_blocks_retry(setup):
    s = setup
    cleanup = _exit_cleanup_fixture(s)
    class Driver(cleanup['Driver']):
        def perform(self, action, observation):
            super().perform(action, observation)
            raise DeviceRunError('ambiguous exit confirmation')
    with pytest.raises(DeviceRunError, match='ambiguous exit confirmation'):
        cleanup['run'](driver=Driver, observer=lambda frame: s['classify'](
            'exit_confirmation', control='confirm_exit_hold', save_id='disposable-100'))
    before = len(s['performed'])
    with pytest.raises(DeviceRunError, match='already attempted'):
        cleanup['run'](resume=True)
    assert len(s['performed']) == before
    journal = execution._journal(Path(cleanup['request']['directory']), s['manifest']['run_id'])
    assert any(row['event'] == 'intent' for row in journal.value['events'])
    assert journal.value['status'] == 'paused'


@pytest.mark.parametrize('changed', ['not_legacy', 'expiry', 'too_long', 'directory', 'predecessor', 'owner'])
def test_cleanup_requires_narrow_fresh_authority_and_exact_predecessor(setup, changed):
    s = setup
    cleanup = _exit_cleanup_fixture(s, legacy=changed != 'not_legacy')
    request = cleanup['request']
    if changed == 'expiry':
        request['expires_utc'] = '2000-01-01T00:00:00Z'
    elif changed == 'too_long':
        request['expires_utc'] = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    elif changed == 'directory':
        request['directory'] = str(s['runs'] / 'exit-recovery-unrelated')
    elif changed == 'predecessor':
        request['cancelled_journal']['sha256'] = '0' * 64
    elif changed == 'owner':
        (s['context'] / 'device-execution-owner.json').write_bytes(b'unknown')
    cleanup['reference'].update(s['write'](Path(cleanup['reference']['path']), request))
    before = len(s['performed'])
    with pytest.raises((DeviceRunError, ValueError)):
        cleanup['run']()
    assert len(s['performed']) == before and not Path(request['directory']).exists()


def test_cleanup_revalidates_current_runtime_and_preserves_interrupt_ambiguity(setup):
    s = setup
    cleanup = _exit_cleanup_fixture(s)
    before = len(s['performed'])
    def observer(frame):
        Path(s['runtime'][0]['path']).write_bytes(b'changed before cleanup')
        return s['classify']('exit_confirmation', control='confirm_exit_hold', save_id='disposable-100')
    with pytest.raises(DeviceRunError, match='input changed'):
        cleanup['run'](observer=observer)
    assert len(s['performed']) == before


def test_interrupted_cleanup_release_blocks_cleanup_resume(setup):
    s = setup
    cleanup = _exit_cleanup_fixture(s)
    class Driver(cleanup['Driver']):
        def release_inputs(self):
            raise KeyboardInterrupt('exit cleanup release interrupted')
    with pytest.raises(KeyboardInterrupt, match='release interrupted'):
        cleanup['run'](driver=Driver)
    assert s['releases'][-1] == 'guardian'
    with pytest.raises(DeviceRunError, match='incomplete or unknown|release was not established'):
        cleanup['run'](resume=True)


def _advance_cleanup_wall_clock(monkeypatch):
    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(minutes=10)
    monkeypatch.setattr(execution, 'datetime', Later)


def test_successful_exit_owner_write_failure_reconciles_after_exit_and_expiry_without_input(setup, monkeypatch):
    s = setup
    cleanup = _exit_cleanup_fixture(s)
    write = execution.atomic_write_bytes
    def fail_restore(path, data):
        if Path(path) == s['context'] / 'device-execution-owner.json' and data == cleanup['owner']:
            raise OSError('final owner publication interrupted')
        return write(path, data)
    monkeypatch.setattr(execution, 'atomic_write_bytes', fail_restore)
    with pytest.raises(OSError, match='owner publication interrupted'):
        cleanup['run'](observer=lambda frame: s['classify'](
            'exit_confirmation', control='confirm_exit_hold', save_id='disposable-100'))
    folder = Path(cleanup['request']['directory'])
    journal = execution._journal(folder, s['manifest']['run_id'])
    before = journal.path.read_bytes()
    assert journal.value['status'] == 'finished'
    assert (s['context'] / 'device-execution-owner.json').read_bytes() != cleanup['owner']
    monkeypatch.setattr(execution, 'atomic_write_bytes', write)
    _advance_cleanup_wall_clock(monkeypatch)
    def forbidden(*args, **kwargs):
        pytest.fail('Terminal reconciliation must not access process/window/driver or live runtime guards.')
    monkeypatch.setattr(execution, 'process_identity', forbidden)
    monkeypatch.setattr(execution, '_load', forbidden)
    assert execution._terminal(journal)
    for _ in range(2):
        result = execution.reconcile_exit_recovery(cleanup['reference'], clock=lambda: s['now'][0])
        assert result['owner_reconciled'] and result['actions_sent'] == []
    assert journal.path.read_bytes() == before
    assert (s['context'] / 'device-execution-owner.json').read_bytes() == cleanup['owner']


def test_capture_only_cleanup_can_cancel_after_expiry_without_changing_request(setup, monkeypatch):
    s = setup
    cleanup = _exit_cleanup_fixture(s)
    cleanup['run']()
    request_bytes = Path(cleanup['reference']['path']).read_bytes()
    old_bytes = cleanup['previous'].read_bytes()
    _advance_cleanup_wall_clock(monkeypatch)
    monkeypatch.setattr(execution, 'process_identity', lambda *args, **kw: pytest.fail('Zero-input cancellation must not need a live process.'))
    result = execution.cancel_exit_recovery(cleanup['reference'], clock=lambda: s['now'][0])
    assert result['status'] == 'cancelled' and result['actions_sent'] == []
    assert (s['context'] / 'device-execution-owner.json').read_bytes() == cleanup['owner']
    assert Path(cleanup['reference']['path']).read_bytes() == request_bytes
    assert cleanup['previous'].read_bytes() == old_bytes
    journal = execution._journal(Path(cleanup['request']['directory']), s['manifest']['run_id'])
    before = journal.path.read_bytes()
    assert journal.value['events'][-1] == {'event': 'exit_recovery_cancelled'}
    assert execution._terminal(journal)
    execution.cancel_exit_recovery(cleanup['reference'], clock=lambda: s['now'][0])
    assert journal.path.read_bytes() == before


def test_cancelled_capture_cleanup_allows_fresh_immutable_request(setup):
    s = setup
    cleanup = _exit_cleanup_fixture(s)
    cleanup['run']()
    old_request = Path(cleanup['reference']['path']).read_bytes()
    execution.cancel_exit_recovery(cleanup['reference'], clock=lambda: s['now'][0])
    request = {**cleanup['request'], 'directory': str(cleanup['previous'].parent / 'exit-recovery-fresh')}
    reference = s['write'](s['tmp_path'] / 'fresh-cleanup-request.json', request)
    result = execution.recover_exit_execution(reference, clock=lambda: s['now'][0],
        driver_factory=cleanup['Driver'], guardian_factory=s['Guardian'])
    assert result['status'] == 'paused' and result['actions_recorded'] == 0
    assert Path(cleanup['reference']['path']).read_bytes() == old_request


@pytest.mark.parametrize('changed', ['missing_release', 'bad_result', 'extra_event', 'wrong_owner', 'missing_result'])
def test_terminal_cleanup_reconcile_rejects_ambiguous_or_unknown_state_without_owner_write(setup, changed):
    s = setup
    cleanup = _exit_cleanup_fixture(s)
    cleanup['run'](observer=lambda frame: s['classify'](
        'exit_confirmation', control='confirm_exit_hold', save_id='disposable-100'))
    journal = execution._journal(Path(cleanup['request']['directory']), s['manifest']['run_id'])
    if changed == 'missing_release':
        journal.value['events'].pop()
    elif changed == 'bad_result':
        next(row for row in journal.value['events'] if row['event'] == 'result')['success'] = False
    elif changed == 'extra_event':
        journal.value['events'].append({'event': 'unknown'})
    elif changed == 'wrong_owner':
        (s['context'] / 'device-execution-owner.json').write_bytes(b'unknown')
    elif changed == 'missing_result':
        journal.value['events'] = [row for row in journal.value['events'] if row['event'] != 'result']
    journal.value['revision'] = len(journal.value['events'])
    journal._write()
    owner_before = (s['context'] / 'device-execution-owner.json').read_bytes()
    journal_before = journal.path.read_bytes()
    with pytest.raises(DeviceRunError):
        execution.reconcile_exit_recovery(cleanup['reference'], clock=lambda: s['now'][0])
    assert (s['context'] / 'device-execution-owner.json').read_bytes() == owner_before
    assert journal.path.read_bytes() == journal_before


def test_cleanup_cancellation_refuses_any_input_intent_and_unreleased_scope(setup):
    s = setup
    cleanup = _exit_cleanup_fixture(s)
    class Driver(cleanup['Driver']):
        def perform(self, action, observation):
            raise DeviceRunError('ambiguous input attempt')
    with pytest.raises(DeviceRunError):
        cleanup['run'](driver=Driver, observer=lambda frame: s['classify'](
            'exit_confirmation', control='confirm_exit_hold', save_id='disposable-100'))
    before = (s['context'] / 'device-execution-owner.json').read_bytes()
    with pytest.raises(DeviceRunError, match='already attempted'):
        execution.cancel_exit_recovery(cleanup['reference'], clock=lambda: s['now'][0])
    assert (s['context'] / 'device-execution-owner.json').read_bytes() == before


def _refused_focus_fixture(s, *, message='Windows refused the game focus request.', key_failure=False):
    """Produce the real execute path's failure-without-result journal shape."""
    s['run']()
    class Driver(s['Driver']):
        def perform(self, action, observation):
            assert action.kind == ('key' if key_failure else 'focus')
            raise DeviceRunError(message)
    with pytest.raises(DeviceRunError, match=message):
        s['run'](resume=True, driver=Driver, observer=lambda frame: s['classify'](
            'title_keyboard', control='press_e', foreground=key_failure))
    return execution._journal(Path(s['manifest']['run_directory']), s['manifest']['run_id'])


def test_exact_refused_focus_can_only_cancel_then_allow_separate_manifest(setup):
    s = setup
    journal = _refused_focus_fixture(s)
    assert [row['event'] for row in journal.value['events']] == [
        'execution_started', 'input_scope_started', 'capture', 'execution_paused', 'input_scope_released',
        'input_scope_started', 'observation', 'intent', 'failure', 'execution_paused', 'input_scope_released']
    with pytest.raises(DeviceRunError, match='unfinished prior action'):
        execution.preflight_execution(s['reference'], resume=True, clock=lambda: s['now'][0])
    with pytest.raises(DeviceRunError, match='unfinished prior action'):
        s['run'](resume=True)
    assert s['captures'] == [1, 2] and s['performed'] == []
    result = execution.cancel_execution(s['reference'], clock=lambda: s['now'][0])
    assert result['status'] == 'cancelled' and result['actions_recorded'] == 1
    assert result['actions_sent_by_cancellation'] == [] and result['acceptance'] == 'not_established'
    assert s['captures'] == [1, 2] and s['performed'] == []
    new_manifest = {**s['manifest'], 'run_directory': str(s['runs'] / 'after-refused-focus')}
    reference = s['write'](s['tmp_path'] / 'after-refused-focus.json', new_manifest)
    assert execution.preflight_execution(reference, clock=lambda: s['now'][0])['ready']
    assert not Path(new_manifest['run_directory']).exists()


@pytest.mark.parametrize('changed', ['wrong_message', 'key', 'missing_failure', 'unreleased_scope',
                                   'failure_shape', 'cleanup_failure', 'later_observation'])
def test_refused_focus_cancellation_never_relaxes_other_ambiguous_failures(setup, changed):
    s = setup
    journal = _refused_focus_fixture(s, message=(
        'A different focus failure' if changed == 'wrong_message' else 'Windows refused the game focus request.'),
        key_failure=changed == 'key')
    if changed == 'missing_failure':
        journal.value['events'] = [row for row in journal.value['events'] if row['event'] != 'failure']
    elif changed == 'unreleased_scope':
        assert journal.value['events'][-1]['event'] == 'input_scope_released'
        journal.value['events'].pop()
    elif changed == 'failure_shape':
        next(row for row in journal.value['events'] if row['event'] == 'failure')['extra'] = True
    elif changed == 'cleanup_failure':
        journal.value['events'].append({'event': 'cleanup_failure', 'detail': 'unknown release'})
    elif changed == 'later_observation':
        journal.value['events'].append({'event': 'observation', 'value': {}})
    journal.value['revision'] = len(journal.value['events'])
    journal._write()
    before = journal.path.read_bytes()
    with pytest.raises(DeviceRunError):
        execution.cancel_execution(s['reference'], clock=lambda: s['now'][0])
    assert journal.path.read_bytes() == before and s['captures'] == [1, 2]
    assert s['performed'] == []


@pytest.mark.parametrize('tamper', ['missing_event', 'wrong_status', 'later_event'])
def test_competition_requires_strictly_reconstructed_cancelled_terminal(setup, tamper):
    s = setup
    s['run']()
    if tamper == 'missing_event':
        journal = execution._journal(Path(s['manifest']['run_directory']), s['manifest']['run_id'])
        journal.append({'event': 'execution_paused', 'detail': 'status alone is not cancellation'}, status='cancelled')
    else:
        execution.cancel_execution(s['reference'], clock=lambda: s['now'][0])
        journal = execution._journal(Path(s['manifest']['run_directory']), s['manifest']['run_id'])
        if tamper == 'wrong_status':
            journal.value['status'] = 'finished'
            journal._write()
        else:
            journal.append({'event': 'execution_paused', 'detail': 'unexpected later work'}, status='cancelled')
    new_manifest = {**s['manifest'], 'run_directory': str(s['runs'] / 'calibration-2')}
    reference = s['write'](s['tmp_path'] / 'calibration-2.json', new_manifest)
    with pytest.raises(DeviceRunError, match='cancellation record is inconsistent|unexpected later events'):
        execution.preflight_execution(reference, clock=lambda: s['now'][0])
    assert not Path(new_manifest['run_directory']).exists()


def test_missing_owner_after_capture_and_changed_desktop_refuse(setup, monkeypatch):
    s = setup
    s['run']()
    owner = s['context'] / 'device-execution-owner.json'
    owner.rename(s['context'] / 'device-execution-owner.retained')
    with pytest.raises(DeviceRunError, match='ownership record is missing'):
        s['run'](resume=True)
    (s['context'] / 'device-execution-owner.retained').rename(owner)
    monkeypatch.setattr(execution, 'desktop_preflight', lambda: {'usable': True, 'session': 2})
    with pytest.raises(DeviceRunError, match='desktop is unavailable or changed'):
        s['run'](resume=True)
    assert s['captures'] == [1] and s['performed'] == []


def test_observer_cannot_mutate_manifest_reference_or_capture_identity(setup):
    s = setup
    original = dict(s['reference'])
    def observer(frame):
        s['reference']['sha256'] = '0' * 64
        frame['process']['pid'] = 999
        frame['window']['hwnd'] = 999
        return s['classify']('title_keyboard', control='press_e')
    result = s['run'](observer=observer)
    assert result['manifest_sha256'] == original['sha256']
    assert len(s['performed']) == 1
    s['reference'].update(original)
    assert s['run'](resume=True)['actions_recorded'] == 1


def test_cli_execute_and_resume_do_not_supply_a_classifier(setup, monkeypatch, capsys):
    from scripts.run_cditem_device_tests import main
    calls = []
    def run(reference, *, resume=False):
        calls.append((reference, resume))
        return {'status': 'paused', 'acceptance': 'not_established'}
    monkeypatch.setattr(execution, 'execute_execution', run)
    for command in ('execute', 'resume'):
        assert main([command, setup['reference']['path'], '--manifest-sha256', setup['reference']['sha256']]) == 0
    assert [resume for _, resume in calls] == [False, True]
    assert 'not_established' in capsys.readouterr().out


def test_cli_cancel_uses_only_the_exact_cancellation_service(setup, monkeypatch, capsys):
    from scripts.run_cditem_device_tests import main
    calls = []
    def cancel(reference):
        calls.append(reference)
        return {'status': 'cancelled', 'actions_sent_by_cancellation': [], 'acceptance': 'not_established'}
    monkeypatch.setattr(execution, 'cancel_execution', cancel)
    monkeypatch.setattr(execution, 'execute_execution', lambda *a, **kw: pytest.fail('Cancellation must not execute.'))
    assert main(['cancel', setup['reference']['path'], '--manifest-sha256', setup['reference']['sha256']]) == 0
    assert calls == [setup['reference']]
    assert 'not_established' in capsys.readouterr().out
