"""Observed, process-bound policy for the development-only CDITEM device runner.

The policy cannot establish save isolation, register native items or classify a
screenshot. Those require their own evidence. A driver must refresh observation
after every action; a title click can already have advanced the menu.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
import time
from typing import Callable

from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.services.independent_item_package import canonical, digest
from cdmw.services.virtual_loader_composition import hash_file


class DeviceRunError(VirtualLoaderError):
    pass


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    created: int  # Windows process creation FILETIME, not a rounded timestamp.
    executable: str
    executable_sha256: str
    session: int


@dataclass(frozen=True)
class WindowIdentity:
    hwnd: int
    client: tuple[int, int, int, int]  # Physical screen coordinates.
    dpi: int


@dataclass(frozen=True)
class Observation:
    run_id: str
    sequence: int
    captured_at: float  # Driver's monotonic clock.
    process: ProcessIdentity
    window: WindowIdentity
    screenshot: str
    screenshot_sha256: str
    screen: str
    foreground: bool
    # The observer names one currently visible control; no guessed coordinates.
    control: str = ''
    point: tuple[int, int] | None = None  # Client-relative physical pixels.
    save_id: str = ''
    gameplay_witness: str = ''
    scenario: str = ''
    assertion: str = ''
    input_tick: int | None = None


@dataclass(frozen=True)
class Action:
    kind: str
    sequence: int
    point: tuple[int, int] | None = None
    key: str = ''


SCREENS = frozenset(('title_gamepad', 'title_keyboard', 'main_menu', 'load_menu', 'load_confirmation', 'exit_confirmation',
                     'loading', 'gameplay', 'scenario_result', 'unknown', 'modal'))
DEFAULT_TIMEOUTS = {'title': 180.0, 'menu': 60.0, 'loading': 240.0, 'scenario': 60.0}


def _positive(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise DeviceRunError(f'Invalid {label}.')
    return value


def verify_guards(guards):
    """Exact file guards supplement, and never replace, the native host guards."""
    for path, expected in guards:
        if not re.fullmatch('[0-9a-f]{64}', expected) or hash_file(Path(path)) != expected:
            raise DeviceRunError(f'The device-test input changed: {path}')


class DeviceRun:
    """One-action-at-a-time policy, independently testable without Windows input."""

    def __init__(self, run_id: str, process: ProcessIdentity, *, save_id: str,
                 scenario: str = 'baseline_observation', timeouts=None,
                 clock: Callable[[], float] = time.monotonic):
        if not re.fullmatch('[A-Za-z0-9_-]{8,96}', run_id) or not save_id:
            raise DeviceRunError('A unique run identity and exact disposable save are required.')
        if (type(process.pid) is not int or process.pid <= 0 or type(process.created) is not int
                or process.created <= 0 or type(process.session) is not int or process.session < 0
                or not Path(process.executable).is_absolute()
                or not re.fullmatch('[0-9a-f]{64}', process.executable_sha256)):
            raise DeviceRunError('Invalid owned game process identity.')
        if scenario != 'baseline_observation':
            raise DeviceRunError('Native item scenarios require their own verified action contract.')
        self.run_id, self.process, self.save_id, self.scenario = run_id, process, save_id, scenario
        self.clock = clock
        self.timeouts = dict(DEFAULT_TIMEOUTS)
        if timeouts:
            if set(timeouts) - self.timeouts.keys():
                raise DeviceRunError('Unknown device-test deadline.')
            self.timeouts.update(timeouts)
        for name, value in self.timeouts.items():
            _positive(value, name + ' deadline')
        self.state, self.sequence, self.window = 'title', 0, None
        self.entered = clock()
        self.mouse_activated = self.e_pressed = False
        self.opened_load = self.selected_save = False
        self.save_confirmed = self.save_hold_confirmed = False
        self.exit_requested = False
        self.pending: Action | None = None
        self.failure = ''
        self.events = []

    def _state(self, state):
        if state != self.state:
            self.state, self.entered = state, self.clock()

    def pause(self, reason):
        self.failure, self.state, self.pending = str(reason), 'paused', None
        self.events.append({'event': 'paused', 'reason': self.failure})

    def _check(self, observation):
        if self.state in ('paused', 'finished'):
            raise DeviceRunError('This run needs recovery or has already finished.')
        if self.pending is not None:
            raise DeviceRunError('Retain the previous action result before observing again.')
        if observation.run_id != self.run_id or observation.process != self.process:
            raise DeviceRunError('The observation belongs to another run or process.')
        if type(observation.sequence) is not int or observation.sequence <= self.sequence:
            raise DeviceRunError('The observation receipt is stale or reused.')
        age = self.clock() - observation.captured_at
        if not math.isfinite(age) or not 0 <= age <= 5.0:
            raise DeviceRunError('The screenshot observation is stale.')
        if not re.fullmatch('[0-9a-f]{64}', observation.screenshot_sha256) or not observation.screenshot:
            raise DeviceRunError('A fresh target-window screenshot is required.')
        window = observation.window
        if (type(window.hwnd) is not int or window.hwnd <= 0 or window.dpi <= 0
                or len(window.client) != 4 or window.client[2] <= window.client[0]
                or window.client[3] <= window.client[1]):
            raise DeviceRunError('Invalid observed game window.')
        if self.window is not None and window.hwnd != self.window:
            raise DeviceRunError('The owned game window was unexpectedly replaced.')
        if observation.screen not in SCREENS or observation.screen in ('unknown', 'modal'):
            raise DeviceRunError('The game screen is unrecognized or blocked by a dialog.')
        if (self.state == 'closing' or observation.screen == 'exit_confirmation') and (
                self.state != 'closing' or not self.exit_requested or observation.screen != 'exit_confirmation'
                or observation.save_id != self.save_id or observation.control != 'confirm_exit_hold'):
            raise DeviceRunError('A fresh exit confirmation must identify the owned disposable save.')
        if self.clock() - self.entered > self.timeouts['loading' if self.state == 'closing' else self.state]:
            raise DeviceRunError(f'The {self.state} state exceeded its deadline.')
        self.sequence, self.window = observation.sequence, window.hwnd

    def _click(self, observation, control):
        if observation.control != control or observation.point is None:
            raise DeviceRunError(f'An observed {control} control is required.')
        x, y = observation.point
        left, top, right, bottom = observation.window.client
        if type(x) is not int or type(y) is not int or not (0 <= x < right - left and 0 <= y < bottom - top):
            raise DeviceRunError('The observed control is outside the current client area.')
        return Action('click', observation.sequence, observation.point)

    def next_action(self, observation: Observation) -> Action:
        try:
            self._check(observation)
            if not observation.foreground:
                # Focus is a request. The next fresh observation must prove it.
                action = Action('focus', observation.sequence)
            else:
                action = self._choose(observation)
            self.pending = action
            self.events.append({'event': 'intent', 'state': self.state, 'action': asdict(action),
                                'screen': observation.screen, 'screenshot': observation.screenshot,
                                'screenshot_sha256': observation.screenshot_sha256})
            return action
        except Exception as exc:
            self.pause(exc)
            raise

    def _choose(self, observation):
        screen = observation.screen
        if screen.startswith('title_'):
            if self.state != 'title':
                raise DeviceRunError('The game unexpectedly returned to its title screen.')
            if screen == 'title_gamepad':
                if self.mouse_activated:
                    return Action('wait', observation.sequence)
                self.mouse_activated = True
                return self._click(observation, 'activate_keyboard')
            if self.e_pressed:
                return Action('wait', observation.sequence)
            if observation.control != 'press_e':
                raise DeviceRunError('The keyboard E prompt has not been observed.')
            self.e_pressed = True
            return Action('key', observation.sequence, key='E')
        if screen == 'main_menu':
            if self.state not in ('title', 'menu') or self.selected_save:
                raise DeviceRunError('Unexpected main menu after save selection.')
            self._state('menu')
            if self.opened_load:
                return Action('wait', observation.sequence)
            self.opened_load = True
            if observation.control == 'open_load_key':
                return Action('key', observation.sequence, key='F')
            return self._click(observation, 'open_load')
        if screen == 'load_menu':
            if self.state not in ('title', 'menu') or observation.save_id != self.save_id:
                raise DeviceRunError('The selected disposable save has not been identified.')
            self._state('menu')
            if self.selected_save:
                return Action('wait', observation.sequence)
            self.selected_save = True
            if observation.control == 'select_save_key':
                return Action('key', observation.sequence, key='RETURN')
            if observation.control == 'select_save_space':
                return Action('key', observation.sequence, key='SPACE')
            return self._click(observation, 'select_save')
        if screen == 'load_confirmation':
            if (self.state != 'menu' or not self.selected_save or observation.save_id != self.save_id
                    or observation.control not in ('confirm_load_space', 'confirm_load_hold')):
                raise DeviceRunError('The observed confirmation must identify the selected disposable save.')
            if observation.control == 'confirm_load_hold':
                if self.save_hold_confirmed:
                    return Action('wait', observation.sequence)
                self.save_hold_confirmed = self.save_confirmed = True
                return Action('key', observation.sequence, key='SPACE_CONFIRM')
            if self.save_confirmed:
                return Action('wait', observation.sequence)
            self.save_confirmed = True
            return Action('key', observation.sequence, key='SPACE')
        if screen == 'loading':
            if not self.selected_save or self.state not in ('menu', 'loading'):
                raise DeviceRunError('Loading did not follow the owned save selection.')
            self._state('loading')
            return Action('wait', observation.sequence)
        if screen == 'gameplay':
            if not self.selected_save or self.state not in ('menu', 'loading', 'scenario'):
                raise DeviceRunError('Gameplay did not follow the owned save selection.')
            if observation.save_id != self.save_id or not observation.gameplay_witness:
                raise DeviceRunError('The intended save and fresh gameplay are not established.')
            self._state('scenario')
            return Action('observe_baseline', observation.sequence)
        if screen == 'scenario_result':
            if (self.state != 'scenario' or observation.scenario != self.scenario
                    or observation.save_id != self.save_id or not observation.assertion):
                raise DeviceRunError('The baseline scenario result is incomplete or unrelated.')
            if observation.control == 'request_exit':
                self._state('closing')
                self.exit_requested = True
                return Action('key', observation.sequence, key='REQUEST_CLOSE')
            if observation.control:
                raise DeviceRunError('The baseline exit control is unrecognized.')
            return Action('close', observation.sequence)
        if screen == 'exit_confirmation':
            if (self.state != 'closing' or not self.exit_requested
                    or observation.save_id != self.save_id or observation.control != 'confirm_exit_hold'):
                raise DeviceRunError('The owned game exit confirmation has not been established.')
            return Action('close', observation.sequence, key='SPACE_CONFIRM')
        raise DeviceRunError('No verified action exists for this screen.')

    def complete_action(self, action, *, success, detail=''):
        if action != self.pending:
            self.pause('An action result is stale or belongs to another action.')
            raise DeviceRunError(self.failure)
        self.events.append({'event': 'result', 'action': asdict(action), 'success': bool(success), 'detail': detail})
        self.pending = None
        if not success:
            self.pause(detail or 'The device action failed.')
        elif action.kind == 'close':
            self.state = 'finished'


class RunJournal:
    """Durable action intent/results; refuses reuse of an unfinished run directory."""

    def __init__(self, folder, *, run_id, create=False):
        self.folder = Path(folder)
        self.path = self.folder / 'device-run.json'
        if create:
            self.folder.mkdir(parents=True, exist_ok=False)
            self.value = {'format': 'cdmw_cditem_device_run_v1', 'run_id': run_id,
                          'status': 'prepared', 'revision': 0, 'events': []}
            self._write()
        else:
            if self.path.stat().st_size > 4 * 1024 * 1024:
                raise DeviceRunError('The device-run journal exceeds its size limit.')
            self.value = json.loads(self.path.read_bytes())
            if self.value.get('format') != 'cdmw_cditem_device_run_v1' or self.value.get('run_id') != run_id:
                raise DeviceRunError('The device-run journal belongs to another run.')
            self.checksum = hash_file(self.path)

    def _write(self):
        raw = canonical(self.value)
        atomic_write_bytes(self.path, raw)
        self.checksum = digest(raw)

    def append(self, event, *, status=None):
        from cdmw.services.installation_lane import installation_lane
        with installation_lane(self.folder):
            if hash_file(self.path) != self.checksum:
                raise DeviceRunError('The device-run journal changed outside this runner.')
            if len(self.value['events']) >= 4096:
                raise DeviceRunError('The device-run event limit was reached.')
            self.value['revision'] += 1
            self.value['events'].append(event)
            if status is not None:
                self.value['status'] = status
            self._write()


def perform_action(run, driver, observation, journal):
    """Write intent first; release only this driver's held input on every branch."""
    action = None
    primary_error = None
    try:
        driver.verify_observation(observation)
        action = run.next_action(observation)
        journal.append(run.events[-1], status='active')
        driver.perform(action, observation)
        run.complete_action(action, success=True)
        journal.append(run.events[-1], status=run.state)
        return action
    except Exception as exc:
        primary_error = exc
        if action is not None and run.pending is not None:
            run.complete_action(action, success=False, detail=str(exc))
        else:
            run.pause(exc)
        try:
            journal.append({'event': 'failure', 'detail': str(exc)}, status='paused')
        except Exception as journal_error:
            exc.add_note(f'Could not append the failure receipt: {journal_error}')
        raise
    finally:
        try:
            driver.release_inputs()
        except Exception as cleanup_error:
            run.pause(f'Input cleanup failed: {cleanup_error}')
            try:
                journal.append({'event': 'cleanup_failure', 'detail': str(cleanup_error)}, status='paused')
            except Exception as journal_error:
                cleanup_error.add_note(f'Could not append the cleanup receipt: {journal_error}')
            if primary_error is None:
                raise
            primary_error.add_note(f'Input cleanup also failed: {cleanup_error}')


def inspect_device_context(root):
    """Read-only by default; never prepare, update, start, focus or send input."""
    from cdmw.services.cditem_device_saves import LIVE_BLOCKER
    from cdmw.services import virtual_loader_runtime as runtime
    from cdmw.services.virtual_loader_state import PROFILE_PATH, decode, read_optional, target
    result = {'format': 'cdmw_cditem_device_inspection_v1', 'game_root': str(Path(root).resolve()),
              'launch_ready': False, 'live_save_ready': False, 'blockers': [LIVE_BLOCKER],
              'actions_sent': [], 'claims': {'game_launch': False, 'game_pixels': False,
                                           'gameplay': False, 'native_independent_items': False}}
    try:
        from cdmw.services.cditem_device_windows import desktop_preflight
        result['desktop'] = desktop_preflight()
        if not result['desktop']['usable']:
            result['blockers'].append('A usable active console desktop is required.')
    except (OSError, ValueError) as exc:
        result['desktop'] = {'usable': False, 'error': str(exc)}
        result['blockers'].append(str(exc))
    try:
        status = runtime.runtime_status(root, experimental=True)
        result['runtime'] = asdict(status)
        if status.state != 'ready':
            result['blockers'].append(status.detail)
        raw = read_optional(target(root, PROFILE_PATH))
        if raw:
            profile = decode(raw)
            result['profile'] = {'generation': profile['generation'], 'sha256': digest(raw),
                                 'packages': profile['packages'], 'mods': profile['mods']}
    except (OSError, ValueError) as exc:
        result['runtime'] = {'state': 'blocked', 'detail': str(exc)}
        result['blockers'].append(str(exc))
    return result


def replay_policy(value):
    """Replay retained synthetic observations without constructing a device driver."""
    if not isinstance(value, dict) or set(value) != {'format', 'run_id', 'process', 'save_id', 'observations'}:
        raise DeviceRunError('Unsupported policy replay input.')
    if value['format'] != 'cdmw_cditem_policy_replay_v1' or not isinstance(value['observations'], list) or len(value['observations']) > 4096:
        raise DeviceRunError('Unsupported policy replay format or observation count.')
    process = ProcessIdentity(**value['process'])
    now = [0.0]
    run = DeviceRun(value['run_id'], process, save_id=value['save_id'], clock=lambda: now[0])
    outcomes = []
    for row in value['observations']:
        if not isinstance(row, dict) or set(row) != {'at', 'screen', 'foreground', 'control', 'point', 'save_id', 'gameplay_witness', 'scenario', 'assertion'}:
            raise DeviceRunError('Unsupported synthetic observation.')
        at = row['at']
        if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at) or at < now[0]:
            raise DeviceRunError('Replay time must be finite and monotonic.')
        now[0] = at
        observation = Observation(run.run_id, len(outcomes) + 1, at, process,
            WindowIdentity(1, (0, 0, 1280, 720), 96), 'synthetic.png', '0' * 64,
            row['screen'], row['foreground'], row['control'], tuple(row['point']) if row['point'] is not None else None,
            row['save_id'], row['gameplay_witness'], row['scenario'], row['assertion'])
        action = run.next_action(observation)
        outcomes.append(asdict(action))
        run.complete_action(action, success=True)
    return {'format': 'cdmw_cditem_policy_replay_result_v1', 'run_id': run.run_id,
            'evidence_class': 'synthetic', 'state': run.state, 'decisions': outcomes,
            'actions_sent': [], 'claims': {'game_launch': False, 'game_pixels': False, 'gameplay': False}}
