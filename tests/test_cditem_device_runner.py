"""Runner policy checks are synthetic evidence, never game acceptance."""
from dataclasses import replace
import ctypes
from pathlib import Path

import pytest

from cdmw.services.cditem_device_runner import (
    DeviceRun, DeviceRunError, Observation, ProcessIdentity, RunJournal,
    WindowIdentity, perform_action, verify_guards,
)
from cdmw.services.cditem_device_windows import Input, KeyboardInput, MouseInput, _send


@pytest.fixture
def setup(tmp_path):
    now = [10.0]
    process = ProcessIdentity(42, 123456789123, str(tmp_path / 'CrimsonDesert.exe'), 'a' * 64, 1)
    run = DeviceRun('run-12345678', process, save_id='disposable-7', clock=lambda: now[0])
    def observe(sequence, screen, **kw):
        return Observation(run.run_id, sequence, now[0], process,
            WindowIdentity(77, (100, 50, 1100, 850), 144), str(tmp_path / f'{sequence}.png'),
            'b' * 64, screen, True, **kw)
    return run, observe, now


def step(run, observation):
    action = run.next_action(observation)
    run.complete_action(action, success=True)
    return action


def test_click_that_advances_menu_never_sends_e(setup):
    run, observe, _ = setup
    assert step(run, observe(1, 'title_gamepad', control='activate_keyboard', point=(100, 100))).kind == 'click'
    assert step(run, observe(2, 'main_menu', control='open_load', point=(200, 200))).kind == 'click'
    assert not run.e_pressed
    assert step(run, observe(3, 'load_menu', control='select_save', point=(300, 300), save_id=run.save_id)).kind == 'click'
    assert step(run, observe(4, 'loading')).kind == 'wait'
    assert step(run, observe(5, 'gameplay', save_id=run.save_id, gameplay_witness='fresh character and world')).kind == 'observe_baseline'
    assert step(run, observe(6, 'scenario_result', save_id=run.save_id, scenario=run.scenario,
                             assertion='stock character state observed')).kind == 'close'
    assert run.state == 'finished'


def test_gamepad_activation_then_observed_e_once(setup):
    run, observe, _ = setup
    assert step(run, observe(1, 'title_gamepad', control='activate_keyboard', point=(40, 40))).kind == 'click'
    assert step(run, observe(2, 'title_keyboard', control='press_e')).key == 'E'
    assert step(run, observe(3, 'title_keyboard', control='press_e')).kind == 'wait'
    assert step(run, observe(4, 'title_gamepad')).kind == 'wait'


def test_focus_request_is_followed_by_observation_not_input(setup):
    run, observe, _ = setup
    title = replace(observe(1, 'title_keyboard', control='press_e'), foreground=False)
    assert step(run, title).kind == 'focus'
    assert not run.e_pressed
    assert step(run, replace(title, sequence=2)).kind == 'focus'
    assert not run.e_pressed


@pytest.mark.parametrize('mutate,match', [
    (lambda o: replace(o, run_id='different-run'), 'another run'),
    (lambda o: replace(o, process=replace(o.process, created=o.process.created + 1)), 'process'),
    (lambda o: replace(o, process=replace(o.process, pid=43)), 'process'),
    (lambda o: replace(o, process=replace(o.process, session=2)), 'process'),
    (lambda o: replace(o, captured_at=1.0), 'stale'),
    (lambda o: replace(o, captured_at=float('nan')), 'stale'),
    (lambda o: replace(o, captured_at=11.0), 'stale'),
    (lambda o: replace(o, screen='modal'), 'dialog'),
    (lambda o: replace(o, screen='unknown'), 'unrecognized'),
    (lambda o: replace(o, screenshot_sha256=''), 'screenshot'),
])
def test_unsafe_observations_pause_without_input(setup, mutate, match):
    run, observe, _ = setup
    with pytest.raises(DeviceRunError, match=match):
        run.next_action(mutate(observe(1, 'title_keyboard', control='press_e')))
    assert run.state == 'paused' and not run.e_pressed


def test_reused_receipt_and_replacement_window_refuse(setup):
    run, observe, _ = setup
    step(run, observe(1, 'title_keyboard', control='press_e'))
    with pytest.raises(DeviceRunError, match='stale|reused'):
        run.next_action(observe(1, 'title_keyboard', control='press_e'))
    run, observe, _ = setup
    # Explicitly create a new run; a paused run cannot silently resume.
    fresh = DeviceRun(run.run_id, run.process, save_id=run.save_id, clock=run.clock)
    step(fresh, observe(1, 'title_keyboard', control='press_e'))
    with pytest.raises(DeviceRunError, match='replaced'):
        fresh.next_action(replace(observe(2, 'title_keyboard'), window=WindowIdentity(78, (0, 0, 100, 100), 96)))


@pytest.mark.parametrize('point', [(-1, 0), (1000, 0), (0, 800), (True, 1)])
def test_click_requires_observed_current_client_point(setup, point):
    run, observe, _ = setup
    with pytest.raises(DeviceRunError, match='outside'):
        run.next_action(observe(1, 'title_gamepad', control='activate_keyboard', point=point))


def test_exact_save_required_and_continue_is_not_guessed(setup):
    run, observe, _ = setup
    with pytest.raises(DeviceRunError, match='disposable save'):
        run.next_action(observe(1, 'load_menu', control='select_save', point=(10, 10), save_id='last-used'))


def test_variable_loading_time_uses_loading_deadline(setup):
    run, observe, now = setup
    step(run, observe(1, 'load_menu', control='select_save', point=(10, 10), save_id=run.save_id))
    step(run, observe(2, 'loading'))
    now[0] += 200
    assert step(run, observe(3, 'loading')).kind == 'wait'
    now[0] += 41
    with pytest.raises(DeviceRunError, match='loading.*deadline'):
        run.next_action(observe(4, 'loading'))


def test_waiting_does_not_reset_title_deadline(setup):
    run, observe, now = setup
    step(run, observe(1, 'title_keyboard', control='press_e'))
    now[0] += 100
    step(run, observe(2, 'title_keyboard', control='press_e'))
    now[0] += 81
    with pytest.raises(DeviceRunError, match='title.*deadline'):
        run.next_action(observe(3, 'title_keyboard', control='press_e'))


def test_loading_or_gameplay_without_owned_selection_refuses(setup):
    run, observe, _ = setup
    with pytest.raises(DeviceRunError, match='selection'):
        run.next_action(observe(1, 'gameplay', save_id=run.save_id, gameplay_witness='world'))


def test_partial_native_scenario_is_not_available(setup):
    run, _, _ = setup
    with pytest.raises(DeviceRunError, match='verified action contract'):
        DeviceRun(run.run_id, run.process, save_id=run.save_id, scenario='acquire-new-id')


def test_failure_is_journaled_and_inputs_released(setup, tmp_path):
    run, observe, _ = setup
    journal = RunJournal(tmp_path / 'journal', run_id=run.run_id, create=True)
    calls = []
    class Driver:
        def verify_observation(self, observation):
            calls.append('verify')
        def perform(self, action, observation):
            assert journal.value['events'][-1]['event'] == 'intent'
            calls.append(action.kind)
            raise DeviceRunError('focus was lost')
        def release_inputs(self):
            calls.append('release')
    with pytest.raises(DeviceRunError, match='focus was lost'):
        perform_action(run, Driver(), observe(1, 'title_keyboard', control='press_e'), journal)
    assert calls == ['verify', 'key', 'release'] and run.state == 'paused'
    retained = RunJournal(journal.folder, run_id=run.run_id)
    assert retained.value['status'] == 'paused'
    assert retained.value['events'][-1]['detail'] == 'focus was lost'


def test_journal_refuses_external_change_or_run_reuse(tmp_path):
    folder = tmp_path / 'run'
    journal = RunJournal(folder, run_id='run-12345678', create=True)
    with pytest.raises(FileExistsError):
        RunJournal(folder, run_id='run-12345678', create=True)
    journal.path.write_text('{}')
    with pytest.raises(DeviceRunError, match='changed outside'):
        journal.append({'event': 'intent'})


@pytest.mark.parametrize('action_fails', [False, True])
def test_input_cleanup_failure_pauses_and_does_not_mask_action_error(setup, tmp_path, action_fails):
    run, observe, _ = setup
    journal = RunJournal(tmp_path / 'cleanup-journal', run_id=run.run_id, create=True)
    class Driver:
        def verify_observation(self, observation):
            pass
        def perform(self, action, observation):
            if action_fails:
                raise DeviceRunError('primary action failed')
        def release_inputs(self):
            raise DeviceRunError('guardian cleanup failed')
    expected = 'primary action' if action_fails else 'guardian cleanup'
    with pytest.raises(DeviceRunError, match=expected):
        perform_action(run, Driver(), observe(1, 'title_keyboard', control='press_e'), journal)
    assert run.state == 'paused' and journal.value['status'] == 'paused'
    assert journal.value['events'][-1]['event'] == 'cleanup_failure'


def test_file_guards_fail_before_driver_work(tmp_path):
    path = tmp_path / 'input'
    path.write_bytes(b'changed')
    with pytest.raises(DeviceRunError, match='input changed'):
        verify_guards(((str(path), '0' * 64),))


def test_real_x64_input_layout_and_partial_injection_rejection():
    assert ctypes.sizeof(MouseInput) == 32
    assert ctypes.sizeof(KeyboardInput) == 24
    assert ctypes.sizeof(Input) == 40
    assert Input.payload.offset == 8 and MouseInput.dwExtraInfo.offset == 24
    class User:
        @staticmethod
        def SendInput(count, events, size):
            assert count == 2 and size == 40 and events[1].keyboard.dwFlags == 2
            return 1
    with pytest.raises(DeviceRunError, match='every injected'):
        _send(User(), [Input(type=1, keyboard=KeyboardInput(wVk=69)),
                       Input(type=1, keyboard=KeyboardInput(wVk=69, dwFlags=2))])


def test_default_cli_inspection_has_no_launch_or_input(tmp_path, monkeypatch, capsys):
    from cdmw.services import cditem_device_windows as windows
    from cdmw.services import virtual_loader_runtime as runtime
    from cdmw.domain.virtual_loader import VirtualSessionStatus
    from scripts.run_cditem_device_tests import main
    def forbidden(*a, **kw):
        pytest.fail('Inspection must not prepare, install, launch or inject input')
    monkeypatch.setattr(runtime, 'prepare_experimental_launch', forbidden)
    monkeypatch.setattr(runtime, 'launch_experimental', forbidden)
    monkeypatch.setattr(runtime, 'apply_runtime_setup', forbidden)
    monkeypatch.setattr(windows, '_send', forbidden)
    monkeypatch.setattr(windows, 'desktop_preflight', lambda: {'usable': True})
    monkeypatch.setattr(runtime, 'runtime_status', lambda *a, **kw: VirtualSessionStatus('ready', 'ready'))
    assert main(['--game-root', str(tmp_path)]) == 0
    import json
    value = json.loads(capsys.readouterr().out)
    assert value['actions_sent'] == [] and value['launch_ready'] is False
    assert value['live_save_ready'] is False and value['blockers']


def test_guardian_releases_on_parent_disconnect_and_stall(monkeypatch):
    from cdmw.services import cditem_device_windows as windows
    class Connection:
        def __init__(self):
            self.polls = iter((True, False, True))
            self.receives = iter(('E',))
            self.sent = []
            self.closed = False
        def send(self, message):
            self.sent.append(message)
        def poll(self, timeout):
            return next(self.polls)
        def recv(self):
            try:
                return next(self.receives)
            except StopIteration:
                raise EOFError
        def close(self):
            self.closed = True
    connection, releases = Connection(), []
    monkeypatch.setattr(windows, '_api', lambda: (None, 'fake-user'))
    monkeypatch.setattr(windows, '_release', lambda user, held: releases.append(tuple(held)))
    windows._input_guardian(connection)
    assert releases == [('E',), ()] and connection.closed
    assert connection.sent == ['ready', 'ready']


def test_windows_driver_rechecks_foreground_before_key(setup, monkeypatch):
    from cdmw.services import cditem_device_windows as windows
    from cdmw.services.cditem_device_runner import Action
    run, observe, _ = setup
    driver = object.__new__(windows.WindowsGameDriver)
    driver.verify_observation = lambda observation: None
    driver.process, driver.held = run.process, set()
    class User:
        @staticmethod
        def GetForegroundWindow():
            return 999  # A foreign window took focus after the screenshot.
        @staticmethod
        def SendInput(*args):
            pytest.fail('Lost focus must prevent input')
    driver.user = User()
    with pytest.raises(DeviceRunError, match='foreground'):
        driver.perform(Action('key', 1, key='E'), observe(1, 'title_keyboard', control='press_e'))


def test_late_foreground_failure_does_not_release_a_key_never_pressed(setup, monkeypatch):
    from types import SimpleNamespace
    from cdmw.services import cditem_device_windows as windows
    from cdmw.services.cditem_device_runner import Action
    run, observe, now = setup
    monkeypatch.setattr(windows.time, 'monotonic', lambda: now[0])
    driver = object.__new__(windows.WindowsGameDriver)
    driver.verify_observation = lambda observation: None
    driver.process, driver.held = run.process, set()
    focus, events, guardian = iter((77, 999)), [], []
    class User:
        @staticmethod
        def GetForegroundWindow():
            return next(focus)
        @staticmethod
        def GetAsyncKeyState(key):
            return 0
        @staticmethod
        def SendInput(count, values, size):
            events.extend(values)
            return count
    driver.user = User()
    driver.guardian = SimpleNamespace(request=guardian.append)
    with pytest.raises(DeviceRunError, match='foreground'):
        driver.perform(Action('key', 1, key='E'), observe(1, 'title_keyboard', control='press_e'))
    driver.release_inputs()
    assert events == [] and driver.held == set()
    assert guardian == ['E', 'clear', 'clear']


def test_failed_supervisor_start_terminates_only_unarmed_owned_child(monkeypatch):
    from types import SimpleNamespace
    from cdmw.services import cditem_device_windows as windows
    calls = []
    class Connection:
        def close(self):
            calls.append('close')
    class Process:
        alive = True
        def start(self):
            calls.append('start')
        def join(self, seconds):
            calls.append(('join', seconds))
        def is_alive(self):
            return self.alive
        def terminate(self):
            calls.append('terminate-unarmed')
            self.alive = False
    process = Process()
    context = SimpleNamespace(Pipe=lambda: (Connection(), Connection()), Process=lambda **kw: process)
    monkeypatch.setattr(windows.multiprocessing, 'get_context', lambda name: context)
    def fail_ack(self):
        raise DeviceRunError('startup acknowledgement failed')
    monkeypatch.setattr(windows.InputGuardian, '_ack', fail_ack)
    with pytest.raises(DeviceRunError, match='acknowledgement'):
        windows.InputGuardian().__enter__()
    assert 'terminate-unarmed' in calls and not process.alive


def test_capture_saves_opaque_rgb_and_timestamps_before_pixels(setup, tmp_path, monkeypatch):
    import numpy as np
    from PIL import Image
    from cdmw.services import cditem_device_windows as windows
    from scripts import window_frame_capture as capture
    run, _observe, _now = setup
    window = WindowIdentity(77, (0, 0, 4, 4), 144)
    pixels = np.zeros((4, 4, 4), dtype=np.uint8)
    pixels[:, :, 0] = np.arange(16, dtype=np.uint8).reshape(4, 4) * 10
    pixels[:, :, 1] = 50
    pixels[:, :, 2] = 100
    # BI_RGB's unused fourth byte stays zero in this real regression witness.
    monkeypatch.setattr(windows, 'process_identity', lambda *a, **kw: run.process)
    monkeypatch.setattr(windows, 'window_identity', lambda *a: window)
    monkeypatch.setattr(windows, '_api', lambda: (None, None))
    monkeypatch.setattr(windows, '_input_tick', lambda user: 123)
    monkeypatch.setattr(capture, '_declare', lambda: None)
    monkeypatch.setattr(capture, 'set_dpi_aware', lambda: 'synthetic')
    monkeypatch.setattr(capture, 'window_rect', lambda hwnd: (0, 0, 4, 4))
    monkeypatch.setattr(capture, 'window_is_hung', lambda hwnd: False)
    calls = []
    monkeypatch.setattr(windows.time, 'monotonic', lambda: calls.append('timestamp') or 10.0)
    def get_pixels(*args):
        calls.append('pixels')
        return pixels
    monkeypatch.setattr(capture, 'capture_window', get_pixels)
    class Connection:
        result = None
        def send(self, value):
            self.result = value
        def close(self):
            pass
    connection = Connection()
    output = tmp_path / 'capture.png'
    windows._capture_worker(connection, run.process, window, output)
    assert 'error' not in connection.result
    with Image.open(output) as image:
        assert image.mode == 'RGB' and image.convert('RGBA').getextrema()[3] == (255, 255)
    assert calls.index('timestamp') < calls.index('pixels')


def test_slow_dispatch_verification_cannot_refresh_an_expired_capture(setup, monkeypatch):
    from dataclasses import asdict
    from cdmw.services import cditem_device_windows as windows
    run, observe, _ = setup
    observation = replace(observe(1, 'title_keyboard', control='press_e'), captured_at=0.0, input_tick=123)
    now = [0.0]
    driver = object.__new__(windows.WindowsGameDriver)
    driver.process, driver.run_id, driver.user = run.process, run.run_id, None
    driver.stamp = 'stable'
    driver._stamp = lambda: 'stable'
    driver.capture_receipt = {'sequence': 1, 'captured_at': 0.0, 'path': observation.screenshot,
                             'sha256': observation.screenshot_sha256, 'input_tick': 123,
                             'window': asdict(observation.window), 'process': asdict(run.process)}
    monkeypatch.setattr(windows.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(windows, 'process_identity', lambda *a, **kw: run.process)
    monkeypatch.setattr(windows, 'window_identity', lambda *a: observation.window)
    def slow_hash(path):
        now[0] += 6.0
        return observation.screenshot_sha256
    monkeypatch.setattr(windows, 'hash_file', slow_hash)
    monkeypatch.setattr(windows, 'desktop_preflight', lambda: {'usable': True, 'session': run.process.session})
    monkeypatch.setattr(windows, '_input_tick', lambda user: 123)
    with pytest.raises(DeviceRunError, match='expired'):
        driver.verify_observation(observation)


def test_cli_replay_has_separate_synthetic_claim(tmp_path, capsys):
    import json
    from scripts.run_cditem_device_tests import main
    value = {'format': 'cdmw_cditem_policy_replay_v1', 'run_id': 'replay-123456',
             'process': {'pid': 1, 'created': 1, 'executable': str(tmp_path / 'game.exe'),
                         'executable_sha256': 'a'*64, 'session': 1}, 'save_id': 'copied-slot',
             'observations': [{'at': 1, 'screen': 'title_keyboard', 'foreground': True,
                               'control': 'press_e', 'point': None, 'save_id': '',
                               'gameplay_witness': '', 'scenario': '', 'assertion': ''}]}
    source = tmp_path / 'replay.json'
    source.write_text(json.dumps(value))
    assert main(['replay', str(source)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['evidence_class'] == 'synthetic' and result['actions_sent'] == []
    assert not any(result['claims'].values()) and result['decisions'][0]['key'] == 'E'
