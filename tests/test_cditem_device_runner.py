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


def test_observed_explicit_load_shortcut_skips_default_play_and_is_sent_once(setup):
    run, observe, _ = setup
    action = step(run, observe(1, 'main_menu', control='open_load_key'))
    assert action.kind == 'key' and action.key == 'F' and not run.e_pressed
    assert step(run, observe(2, 'main_menu', control='open_load_key')).kind == 'wait'
    assert step(run, observe(3, 'load_menu', control='select_save', point=(50, 50), save_id=run.save_id)).kind == 'click'


def test_observed_return_selects_exact_disposable_save_only_once(setup):
    run, observe, _ = setup
    assert step(run, observe(1, 'main_menu', control='open_load_key')).key == 'F'
    action = step(run, observe(2, 'load_menu', control='select_save_key', save_id=run.save_id))
    assert action.kind == 'key' and action.key == 'RETURN' and action.point is None
    assert step(run, observe(3, 'load_menu', control='select_save_key', save_id=run.save_id)).kind == 'wait'
    assert step(run, observe(4, 'loading')).kind == 'wait'


def test_observed_space_selects_exact_disposable_save_once_without_reinterpreting_return(setup):
    run, observe, _ = setup
    action = step(run, observe(1, 'load_menu', control='select_save_space', save_id=run.save_id))
    assert action.kind == 'key' and action.key == 'SPACE' and action.point is None
    assert step(run, observe(2, 'load_menu', control='select_save_space', save_id=run.save_id)).kind == 'wait'
    assert step(run, observe(3, 'loading')).kind == 'wait'
    # The separately named historical Return route retains its recorded key.
    old = DeviceRun(run.run_id, run.process, save_id=run.save_id, clock=run.clock)
    assert step(old, observe(1, 'load_menu', control='select_save_key', save_id=run.save_id)).key == 'RETURN'


def test_observed_save_confirmation_requires_selection_and_confirms_space_once(setup):
    run, observe, _ = setup
    step(run, observe(1, 'load_menu', control='select_save_space', save_id=run.save_id))
    action = step(run, observe(2, 'load_confirmation', control='confirm_load_space', save_id=run.save_id))
    assert action.kind == 'key' and action.key == 'SPACE' and run.save_confirmed
    assert step(run, observe(3, 'load_confirmation', control='confirm_load_space', save_id=run.save_id)).kind == 'wait'
    assert step(run, observe(4, 'loading')).kind == 'wait'


@pytest.mark.parametrize('selected,save_id,control', [
    (False, 'disposable-7', 'confirm_load_space'),
    (True, 'other-save', 'confirm_load_space'),
    (True, '', 'confirm_load_space'),
    (True, 'disposable-7', ''),
    (True, 'disposable-7', 'select_save_space'),
])
def test_unidentified_or_unselected_confirmation_pauses_without_input(setup, selected, save_id, control):
    run, observe, _ = setup
    if selected:
        step(run, observe(1, 'load_menu', control='select_save_space', save_id=run.save_id))
    with pytest.raises(DeviceRunError, match='confirmation'):
        run.next_action(observe(2, 'load_confirmation', control=control, save_id=save_id))
    assert run.state == 'paused' and not run.save_confirmed and run.pending is None


@pytest.mark.parametrize('short_first', [False, True])
def test_observed_confirmation_hold_once_after_optional_historical_short_attempt(setup, short_first):
    run, observe, _ = setup
    sequence = 1
    step(run, observe(sequence, 'load_menu', control='select_save_space', save_id=run.save_id))
    if short_first:
        sequence += 1
        assert step(run, observe(sequence, 'load_confirmation', control='confirm_load_space', save_id=run.save_id)).key == 'SPACE'
        assert run.save_confirmed and not run.save_hold_confirmed
    sequence += 1
    action = step(run, observe(sequence, 'load_confirmation', control='confirm_load_hold', save_id=run.save_id))
    assert action.kind == 'key' and action.key == 'SPACE_CONFIRM'
    assert run.save_confirmed and run.save_hold_confirmed
    assert step(run, observe(sequence + 1, 'load_confirmation', control='confirm_load_hold', save_id=run.save_id)).kind == 'wait'
    assert step(run, observe(sequence + 2, 'load_confirmation', control='confirm_load_space', save_id=run.save_id)).kind == 'wait'


@pytest.mark.parametrize('selected,state,save_id', [
    (False, 'menu', 'disposable-7'), (True, 'title', 'disposable-7'),
    (True, 'menu', 'other-save'), (True, 'menu', ''),
])
def test_confirmation_hold_requires_menu_selected_save_and_exact_identity(setup, selected, state, save_id):
    run, observe, _ = setup
    run.selected_save, run.state = selected, state
    with pytest.raises(DeviceRunError, match='confirmation'):
        run.next_action(observe(1, 'load_confirmation', control='confirm_load_hold', save_id=save_id))
    assert not run.save_hold_confirmed and not run.save_confirmed and run.pending is None


@pytest.mark.parametrize('key', ['E', 'F', 'RETURN', 'SPACE', 'SPACE_CONFIRM'])
def test_owned_key_tap_spans_frames_and_releases_the_exact_armed_key(setup, monkeypatch, key):
    from types import SimpleNamespace
    from cdmw.services import cditem_device_windows as windows
    from cdmw.services.cditem_device_runner import Action
    run, observe, now = setup
    monkeypatch.setattr(windows.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(windows, '_input_tick', lambda user: 123)
    events, guardian, virtual_keys, mappings = [], [], [], []
    monkeypatch.setattr(windows.time, 'sleep', lambda duration: events.append(('hold', duration)))
    class User:
        GetForegroundWindow = staticmethod(lambda: 77)
        GetAsyncKeyState = staticmethod(lambda vk: virtual_keys.append(vk) or 0)
        MapVirtualKeyW = staticmethod(lambda vk, mode: mappings.append((vk, mode)) or {ord('E'): 0x12, ord('F'): 0x21, 0x0D: 0x1C, 0x20: 0x39}[vk])
        @staticmethod
        def SendInput(count, values, size):
            events.append(('input', [(values[i].keyboard.wVk, values[i].keyboard.wScan, values[i].keyboard.dwFlags) for i in range(count)]))
            return count
    driver = object.__new__(windows.WindowsGameDriver)
    driver.verify_observation = lambda observation: None
    driver.process, driver.held, driver.user = run.process, set(), User()
    driver.guardian = SimpleNamespace(request=guardian.append)
    driver.perform(Action('key', 1, key=key), replace(observe(1, 'main_menu', control='open_load_key'), input_tick=123))
    physical_key = 'SPACE' if key == 'SPACE_CONFIRM' else key
    scan = {'E': 0x12, 'F': 0x21, 'RETURN': 0x1C, 'SPACE': 0x39}[physical_key]
    virtual_key = {'E': 0x45, 'F': 0x46, 'RETURN': 0x0D, 'SPACE': 0x20}[physical_key]
    duration = 1.25 if key == 'SPACE_CONFIRM' else 0.08
    assert events == [('input', [(0, scan, 8)]), ('hold', duration), ('input', [(0, scan, 10)])]
    assert virtual_keys == [virtual_key] and mappings == [(virtual_key, 0)]
    assert guardian == [physical_key, 'clear'] and not driver.held


@pytest.mark.parametrize('key,scan', [('F', 0x21), ('RETURN', 0x1C), ('SPACE', 0x39), ('SPACE_CONFIRM', 0x39)])
def test_interrupted_menu_hold_remains_armed_until_unconditional_input_release(setup, monkeypatch, key, scan):
    from types import SimpleNamespace
    from cdmw.services import cditem_device_windows as windows
    from cdmw.services.cditem_device_runner import Action
    run, observe, now = setup
    monkeypatch.setattr(windows.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(windows, '_input_tick', lambda user: 123)
    events, guardian = [], []
    def interrupt(duration):
        raise KeyboardInterrupt('during held input')
    monkeypatch.setattr(windows.time, 'sleep', interrupt)
    class User:
        GetForegroundWindow = staticmethod(lambda: 77)
        GetAsyncKeyState = staticmethod(lambda vk: 0)
        MapVirtualKeyW = staticmethod(lambda vk, mode: scan)
        @staticmethod
        def SendInput(count, values, size):
            events.extend((values[i].keyboard.wScan, values[i].keyboard.dwFlags) for i in range(count))
            return count
    driver = object.__new__(windows.WindowsGameDriver)
    driver.verify_observation = lambda observation: None
    driver.process, driver.held, driver.user = run.process, set(), User()
    driver.guardian = SimpleNamespace(request=guardian.append)
    with pytest.raises(KeyboardInterrupt):
        driver.perform(Action('key', 1, key=key), replace(observe(1, 'main_menu', control='open_load_key'), input_tick=123))
    physical_key = 'SPACE' if key == 'SPACE_CONFIRM' else key
    assert driver.held == {physical_key} and guardian == [physical_key]
    # Release the physical key that was armed even if the layout later changes.
    driver.user.MapVirtualKeyW = lambda *args: pytest.fail('Unconditional release must not remap the held physical key')
    driver.release_inputs()
    assert events == [(scan, 8), (scan, 10)] and not driver.held
    assert guardian == [physical_key, 'clear']


@pytest.mark.parametrize('key,mapping', [('F', 0), ('F', 0x12), ('RETURN', 0), ('RETURN', 0x21), ('SPACE', 0), ('SPACE', 0x1C), ('SPACE_CONFIRM', 0), ('SPACE_CONFIRM', 0x1C)])
def test_uncalibrated_menu_physical_mapping_disarms_without_input(setup, monkeypatch, key, mapping):
    from types import SimpleNamespace
    from cdmw.services import cditem_device_windows as windows
    from cdmw.services.cditem_device_runner import Action
    run, observe, now = setup
    monkeypatch.setattr(windows.time, 'monotonic', lambda: now[0])
    guardian=[]
    class User:
        GetForegroundWindow=staticmethod(lambda:77)
        GetAsyncKeyState=staticmethod(lambda vk:0)
        MapVirtualKeyW=staticmethod(lambda vk,mode:mapping)
        SendInput=staticmethod(lambda *args:pytest.fail('Uncalibrated mapping must send no input'))
    driver=object.__new__(windows.WindowsGameDriver)
    driver.verify_observation=lambda observation:None
    driver.process,driver.held,driver.user=run.process,set(),User()
    driver.guardian=SimpleNamespace(request=guardian.append)
    with pytest.raises(DeviceRunError,match='keyboard mapping'):
        driver.perform(Action('key',1,key=key),observe(1,'main_menu',control='open_load_key'))
    assert guardian == [] and not driver.held


@pytest.mark.parametrize('key,virtual_key', [('RETURN', 0x0D), ('SPACE', 0x20), ('SPACE_CONFIRM', 0x20)])
def test_already_held_menu_key_refuses_before_arming_or_input(setup, monkeypatch, key, virtual_key):
    from types import SimpleNamespace
    from cdmw.services import cditem_device_windows as windows
    from cdmw.services.cditem_device_runner import Action
    run, observe, now = setup
    monkeypatch.setattr(windows.time, 'monotonic', lambda: now[0])
    calls = []
    class User:
        GetForegroundWindow = staticmethod(lambda: 77)
        GetAsyncKeyState = staticmethod(lambda vk: calls.append(vk) or 0x8000)
        SendInput = staticmethod(lambda *args: pytest.fail('Held menu key must send no input'))
    driver = object.__new__(windows.WindowsGameDriver)
    driver.verify_observation = lambda observation: None
    driver.process, driver.held, driver.user = run.process, set(), User()
    driver.guardian = SimpleNamespace(request=lambda message: pytest.fail('Held menu key must not arm the guardian'))
    with pytest.raises(DeviceRunError, match='already held'):
        driver.perform(Action('key', 1, key=key), observe(1, 'load_menu', control='select_save_key', save_id=run.save_id))
    assert calls == [virtual_key] and not driver.held


@pytest.mark.parametrize('interrupt', [False, True])
def test_owned_mouse_tap_spans_frames_and_interrupted_hold_releases(setup, monkeypatch, interrupt):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from cdmw.services import cditem_device_windows as windows
    from cdmw.services.cditem_device_runner import Action
    run, observe, now = setup
    monkeypatch.setattr(windows.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(windows, '_input_tick', lambda user: 123)
    monkeypatch.setattr(windows, '_physical_coordinates', lambda user: nullcontext())
    events, guardian = [], []
    def hold(duration):
        events.append(('hold', duration))
        if interrupt:
            raise KeyboardInterrupt('during mouse hold')
    monkeypatch.setattr(windows.time, 'sleep', hold)
    class User:
        GetForegroundWindow = staticmethod(lambda: 77)
        GetAsyncKeyState = staticmethod(lambda vk: 0)
        GetSystemMetrics = staticmethod(lambda code: {76: 0, 77: 0, 78: 1920, 79: 1080}[code])
        WindowFromPoint = staticmethod(lambda point: 77)
        GetAncestor = staticmethod(lambda hwnd, mode: 77)
        @staticmethod
        def SendInput(count, values, size):
            events.append(('input', [values[i].mouse.dwFlags for i in range(count)]))
            return count
    driver = object.__new__(windows.WindowsGameDriver)
    driver.verify_observation = lambda observation: None
    driver.process, driver.held, driver.user = run.process, set(), User()
    driver.guardian = SimpleNamespace(request=guardian.append)
    action = Action('click', 1, point=(50, 50))
    frame = replace(observe(1, 'main_menu', control='open_load', point=(50, 50)), input_tick=123)
    if interrupt:
        with pytest.raises(KeyboardInterrupt):
            driver.perform(action, frame)
        assert driver.held == {'left'} and guardian == ['left']
        driver.release_inputs()
    else:
        driver.perform(action, frame)
    assert events == [('input', [0xC001, 2]), ('hold', 0.08), ('input', [4])]
    assert guardian == ['left', 'clear'] and not driver.held


@pytest.fixture
def armed_input(setup, monkeypatch):
    """Fake only the desktop APIs; retain the real driver dispatch ordering."""
    from contextlib import nullcontext
    from types import SimpleNamespace
    from cdmw.services import cditem_device_windows as windows
    from cdmw.services.cditem_device_runner import Action
    run, observe, now = setup
    controls = {'verification_delay': 0.0, 'ack_delay': 0.0, 'foreground_delay': 0.0,
                'tick_delay': 0.0, 'tick': 123, 'foreground': 77, 'occluded': False}
    trace, messages, inputs, arms = [], [], [], []
    driver = object.__new__(windows.WindowsGameDriver)
    driver.process, driver.held = run.process, set()
    checks = [0]
    def verify(observation):
        checks[0] += 1
        trace.append(('verify', now[0]))
        if checks[0] == 2:
            assert not arms, 'Slow full verification must finish before arming.'
            now[0] += controls['verification_delay']
    driver.verify_observation = verify
    def request(message):
        messages.append(message)
        trace.append(('guardian', message, now[0]))
        if message != 'clear':
            arms.append(now[0])
            now[0] += controls['ack_delay']
    driver.guardian = SimpleNamespace(request=request)
    def foreground():
        if arms:
            now[0] += controls['foreground_delay']
            return controls['foreground']
        return 77
    def tick(user):
        now[0] += controls['tick_delay']
        return controls['tick']
    class User:
        GetForegroundWindow = staticmethod(foreground)
        GetAsyncKeyState = staticmethod(lambda vk: 0)
        MapVirtualKeyW = staticmethod(lambda vk, mode: 0x39)
        GetSystemMetrics = staticmethod(lambda code: {76: 0, 77: 0, 78: 1920, 79: 1080}[code])
        GetAncestor = staticmethod(lambda hwnd, mode: hwnd)
        @staticmethod
        def WindowFromPoint(point):
            assert not arms, 'Mouse occlusion must be verified before arming.'
            return 999 if controls['occluded'] else 77
        @staticmethod
        def SendInput(count, values, size):
            for index in range(count):
                value = values[index]
                up = bool(value.keyboard.dwFlags & 2) if value.type == 1 else bool(value.mouse.dwFlags & 4)
                inputs.append(('up' if up else 'down', now[0]))
            return count
    driver.user = User()
    monkeypatch.setattr(windows.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(windows, '_input_tick', tick)
    monkeypatch.setattr(windows, '_physical_coordinates', lambda user: nullcontext())
    def hold(duration):
        trace.append(('hold', duration, now[0]))
        now[0] += duration
    monkeypatch.setattr(windows.time, 'sleep', hold)
    def perform(kind):
        frame = replace(observe(1, 'load_confirmation', control='confirm_load_hold',
                                save_id=run.save_id, point=(50, 50)),
                        captured_at=9.0, input_tick=123)
        action = Action('key', 1, key='SPACE_CONFIRM') if kind == 'key' else Action('click', 1, point=(50, 50))
        driver.perform(action, frame)
    return locals()


@pytest.mark.parametrize('kind', ['key', 'mouse'])
def test_slow_full_validation_finishes_before_arm_and_leaves_hold_covered(armed_input, kind):
    s = armed_input
    s['controls'].update(verification_delay=2.1, ack_delay=0.24)
    s['perform'](kind)
    assert s['checks'][0] == 2 and s['arms'][0] == pytest.approx(12.1)
    first_arm = next(index for index, value in enumerate(s['trace']) if value[0] == 'guardian')
    assert not any(value[0] == 'verify' for value in s['trace'][first_arm:])
    down = next(at for kind, at in s['inputs'] if kind == 'down')
    up = s['inputs'][-1][1]
    assert down - s['arms'][0] == pytest.approx(0.24)
    assert up - s['arms'][0] == pytest.approx(1.49 if kind == 'key' else 0.32)
    assert up - s['arms'][0] < 2.0 and not s['driver'].held


@pytest.mark.parametrize('kind', ['key', 'mouse'])
def test_slow_guardian_ack_refuses_before_down_and_clears_unpressed_arm(armed_input, kind):
    s = armed_input
    s['controls']['ack_delay'] = 0.26
    with pytest.raises(DeviceRunError, match='arming exceeded'):
        s['perform'](kind)
    assert s['messages'] == ['SPACE' if kind == 'key' else 'left', 'clear']
    assert not s['inputs'] and not s['driver'].held


@pytest.mark.parametrize('change,value', [
    ('foreground', 999), ('tick', 124), ('tick_delay', 0.26),
    ('foreground_delay', 0.3), ('ack_delay', -0.01), ('ack_delay', float('nan')),
])
def test_post_ack_checks_and_final_finite_clock_bound_refuse_without_down(armed_input, change, value):
    s = armed_input
    s['controls'][change] = value
    with pytest.raises(DeviceRunError):
        s['perform']('key')
    assert s['messages'] == ['SPACE', 'clear']
    assert not s['inputs'] and not s['driver'].held


def test_mouse_occlusion_refuses_before_guardian_arm(armed_input):
    s = armed_input
    s['controls']['occluded'] = True
    with pytest.raises(DeviceRunError, match='covered by another window'):
        s['perform']('mouse')
    assert s['messages'] == s['inputs'] == [] and not s['driver'].held


def test_observed_exit_request_then_exact_confirmation_preserves_legacy_close(setup):
    run, observe, _ = setup
    run.state, run.selected_save = 'scenario', True
    result = dict(save_id=run.save_id, scenario=run.scenario, assertion='baseline retained')
    legacy = DeviceRun(run.run_id, run.process, save_id=run.save_id, clock=run.clock)
    legacy.state, legacy.selected_save = 'scenario', True
    assert step(legacy, observe(1, 'scenario_result', **result)).kind == 'close'
    assert not legacy.exit_requested
    request = step(run, observe(1, 'scenario_result', control='request_exit', **result))
    assert request.kind == 'key' and request.key == 'REQUEST_CLOSE'
    assert run.state == 'closing' and run.exit_requested
    close = step(run, observe(2, 'exit_confirmation', control='confirm_exit_hold', save_id=run.save_id))
    assert close.kind == 'close' and close.key == 'SPACE_CONFIRM' and run.state == 'finished'


@pytest.mark.parametrize('state,requested,save_id,control', [
    ('scenario', False, 'disposable-7', 'confirm_exit_hold'),
    ('closing', False, 'disposable-7', 'confirm_exit_hold'),
    ('closing', True, 'other-save', 'confirm_exit_hold'),
    ('closing', True, 'disposable-7', 'unknown'),
])
@pytest.mark.parametrize('foreground', [False, True])
def test_exit_confirmation_requires_owned_closing_state_and_exact_save(setup, state, requested, save_id, control, foreground):
    run, observe, _ = setup
    run.state, run.exit_requested = state, requested
    with pytest.raises(DeviceRunError, match='exit confirmation'):
        run.next_action(replace(observe(1, 'exit_confirmation', control=control, save_id=save_id), foreground=foreground))


def test_closing_uses_existing_loading_deadline_without_reset(setup):
    run, observe, now = setup
    run.state, run.selected_save = 'scenario', True
    step(run, observe(1, 'scenario_result', control='request_exit', save_id=run.save_id,
                      scenario=run.scenario, assertion='retained'))
    now[0] += run.timeouts['loading'] + 1
    with pytest.raises(DeviceRunError, match='closing.*deadline'):
        run.next_action(observe(2, 'exit_confirmation', control='confirm_exit_hold', save_id=run.save_id))


def _exit_kernel(s, *, reused=False, wait=None):
    from types import SimpleNamespace
    calls = []
    def times(handle, created, *args):
        created._obj.value = s['run'].process.created + int(reused)
        return 1
    kernel = SimpleNamespace(OpenProcess=lambda *args: calls.append('open') or 88,
                             GetProcessTimes=times, CloseHandle=lambda handle: calls.append('closed'),
                             WaitForSingleObject=wait or (lambda *args: pytest.fail('Request-only close must not wait')))
    s['driver'].kernel = kernel
    return calls


@pytest.mark.parametrize('reused', [False, True])
def test_request_close_posts_only_owned_wm_close_without_waiting(armed_input, reused):
    from cdmw.services.cditem_device_runner import Action
    s = armed_input
    handles, posted = _exit_kernel(s, reused=reused), []
    s['driver'].user.PostMessageW = lambda hwnd, message, w, l: posted.append((hwnd, message)) or 1
    frame = replace(s['observe'](1, 'scenario_result'), input_tick=123)
    if reused:
        with pytest.raises(DeviceRunError, match='PID was reused'):
            s['driver'].perform(Action('key', 1, key='REQUEST_CLOSE'), frame)
    else:
        s['driver'].perform(Action('key', 1, key='REQUEST_CLOSE'), frame)
    assert handles == ['open', 'closed']
    assert posted == ([] if reused else [(77, 0x0010)])
    assert s['messages'] == s['inputs'] == []


def test_confirmed_close_releases_fixed_hold_before_wait_without_reusing_old_tick(armed_input):
    from cdmw.services.cditem_device_runner import Action
    s = armed_input
    send = s['driver'].user.SendInput
    def changed_tick(count, values, size):
        result = send(count, values, size)
        if s['inputs'][-1][0] == 'up':
            s['controls']['tick'] = 124
        return result
    s['driver'].user.SendInput = changed_tick
    def wait(handle, timeout):
        assert handle == 88 and timeout == 15000
        assert s['messages'] == ['SPACE', 'clear'] and not s['driver'].held
        assert s['controls']['tick'] == 124
        assert s['inputs'][-1][1] - s['inputs'][0][1] == pytest.approx(1.25)
        return 0
    handles = _exit_kernel(s, wait=wait)
    s['driver'].user.PostMessageW = lambda *args: pytest.fail('Confirmation must not repost WM_CLOSE')
    s['driver'].perform(Action('close', 1, key='SPACE_CONFIRM'), replace(
        s['observe'](1, 'exit_confirmation', control='confirm_exit_hold', save_id=s['run'].save_id), input_tick=123))
    assert handles == ['open', 'closed'] and s['inputs'][-1][0] == 'up'


def test_unknown_close_key_refuses_without_opening_process_or_input(armed_input):
    from cdmw.services.cditem_device_runner import Action
    s = armed_input
    with pytest.raises(DeviceRunError, match='Unsupported owned game close'):
        s['driver'].perform(Action('close', 1, key='F'), s['observe'](1, 'exit_confirmation'))
    assert s['inputs'] == s['messages'] == []


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


@pytest.mark.parametrize('control', ['select_save', 'select_save_key', 'select_save_space'])
def test_exact_save_required_and_continue_is_not_guessed(setup, control):
    run, observe, _ = setup
    with pytest.raises(DeviceRunError, match='disposable save'):
        run.next_action(observe(1, 'load_menu', control=control, point=(10, 10), save_id='last-used'))


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


@pytest.mark.parametrize('key', ['E', 'RETURN', 'SPACE'])
def test_guardian_releases_on_parent_disconnect_and_stall(monkeypatch, key):
    from cdmw.services import cditem_device_windows as windows
    class Connection:
        def __init__(self):
            self.polls = iter((True, False, True))
            self.receives = iter((key,))
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
    assert releases == [(key,), (key,)] and connection.closed
    assert connection.sent == ['ready', 'ready']


@pytest.mark.parametrize('clear_after_timeout', [False, True])
def test_guardian_retains_timeout_ownership_for_late_down_until_clear_or_eof(monkeypatch, clear_after_timeout):
    from cdmw.services import cditem_device_windows as windows
    events = []
    class User:
        @staticmethod
        def SendInput(count, values, size):
            for index in range(count):
                assert values[index].keyboard.wScan == 0x39
                assert values[index].keyboard.dwFlags == 10
                events.append('UP')
            return count
    class Connection:
        def __init__(self):
            self.polls = iter((True, False, True, False, True) if clear_after_timeout else (True, False, True))
            self.receives = iter(('SPACE', 'clear') if clear_after_timeout else ('SPACE',))
            self.sent, self.closed = [], False
        def send(self, value):
            self.sent.append(value)
        def poll(self, timeout):
            assert timeout == 2.0
            return next(self.polls)
        def recv(self):
            try:
                return next(self.receives)
            except StopIteration:
                if not clear_after_timeout:
                    # The parent's DOWN arrived after the watchdog's first UP.
                    events.append('DOWN')
                raise EOFError
        def close(self):
            self.closed = True
    connection = Connection()
    monkeypatch.setattr(windows, '_api', lambda: (None, User()))
    # Run the actual guardian state machine and physical release helper against
    # fake SendInput; no real process, keyboard, or desktop API is used.
    windows._input_guardian(connection)
    assert events == (['UP'] if clear_after_timeout else ['UP', 'DOWN', 'UP'])
    assert connection.closed


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
    assert guardian == ['clear']


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
