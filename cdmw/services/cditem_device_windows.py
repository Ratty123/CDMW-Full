"""Windows x64 device-test primitives; no global game/window selection or launch."""
from __future__ import annotations

import ctypes as C
from contextlib import contextmanager
from dataclasses import asdict
import multiprocessing
import os
from pathlib import Path
import time

from cdmw.services.cditem_device_runner import DeviceRunError, ProcessIdentity, WindowIdentity
from cdmw.services.virtual_loader_composition import hash_file


U16, U32, I32, U64 = C.c_uint16, C.c_uint32, C.c_int32, C.c_uint64


class MouseInput(C.Structure):
    _fields_ = [('dx', I32), ('dy', I32), ('mouseData', U32), ('dwFlags', U32),
                ('time', U32), ('dwExtraInfo', C.c_size_t)]


class KeyboardInput(C.Structure):
    _fields_ = [('wVk', U16), ('wScan', U16), ('dwFlags', U32), ('time', U32),
                ('dwExtraInfo', C.c_size_t)]


class HardwareInput(C.Structure):
    _fields_ = [('uMsg', U32), ('wParamL', U16), ('wParamH', U16)]


class InputPayload(C.Union):
    _fields_ = [('mouse', MouseInput), ('keyboard', KeyboardInput), ('hardware', HardwareInput)]


class Input(C.Structure):
    _anonymous_ = ('payload',)
    _fields_ = [('type', U32), ('payload', InputPayload)]


class Point(C.Structure):
    _fields_ = [('x', I32), ('y', I32)]


class Rect(C.Structure):
    _fields_ = [('left', I32), ('top', I32), ('right', I32), ('bottom', I32)]


class LastInputInfo(C.Structure):
    _fields_ = [('cbSize', U32), ('dwTime', U32)]


def _api():
    if os.name != 'nt' or C.sizeof(C.c_void_p) != 8 or C.sizeof(Input) != 40:
        raise DeviceRunError('The device runner requires Windows x64.')
    kernel = C.WinDLL('kernel32', use_last_error=True)
    user = C.WinDLL('user32', use_last_error=True)
    signatures = [
        (kernel, 'OpenProcess', [U32, C.c_int, U32], C.c_void_p),
        (kernel, 'CloseHandle', [C.c_void_p], C.c_int),
        (kernel, 'GetProcessTimes', [C.c_void_p] + [C.POINTER(U64)] * 4, C.c_int),
        (kernel, 'QueryFullProcessImageNameW', [C.c_void_p, U32, C.c_wchar_p, C.POINTER(U32)], C.c_int),
        (kernel, 'ProcessIdToSessionId', [U32, C.POINTER(U32)], C.c_int),
        (kernel, 'GetCurrentProcessId', [], U32),
        (kernel, 'WTSGetActiveConsoleSessionId', [], U32),
        (kernel, 'WaitForSingleObject', [C.c_void_p, U32], U32),
        (user, 'OpenInputDesktop', [U32, C.c_int, U32], C.c_void_p),
        (user, 'CloseDesktop', [C.c_void_p], C.c_int),
        (user, 'GetUserObjectInformationW', [C.c_void_p, C.c_int, C.c_void_p, U32, C.POINTER(U32)], C.c_int),
        (user, 'IsWindow', [C.c_void_p], C.c_int),
        (user, 'IsWindowVisible', [C.c_void_p], C.c_int),
        (user, 'GetWindowThreadProcessId', [C.c_void_p, C.POINTER(U32)], U32),
        (user, 'GetForegroundWindow', [], C.c_void_p),
        (user, 'GetLastInputInfo', [C.POINTER(LastInputInfo)], C.c_int),
        (user, 'WindowFromPoint', [Point], C.c_void_p),
        (user, 'GetAncestor', [C.c_void_p, U32], C.c_void_p),
        (user, 'GetClientRect', [C.c_void_p, C.POINTER(Rect)], C.c_int),
        (user, 'ClientToScreen', [C.c_void_p, C.POINTER(Point)], C.c_int),
        (user, 'GetDpiForWindow', [C.c_void_p], U32),
        (user, 'SetThreadDpiAwarenessContext', [C.c_void_p], C.c_void_p),
        (user, 'SetForegroundWindow', [C.c_void_p], C.c_int),
        (user, 'SendInput', [U32, C.POINTER(Input), C.c_int], U32),
        (user, 'GetAsyncKeyState', [C.c_int], C.c_int16),
        (user, 'GetSystemMetrics', [C.c_int], C.c_int),
        (user, 'PostMessageW', [C.c_void_p, U32, C.c_size_t, C.c_ssize_t], C.c_int),
    ]
    for library, name, args, result in signatures:
        function = getattr(library, name)
        function.argtypes, function.restype = args, result
    return kernel, user


def _input_tick(user):
    value = LastInputInfo(cbSize=C.sizeof(LastInputInfo))
    if not user.GetLastInputInfo(C.byref(value)):
        raise DeviceRunError('Cannot establish current desktop input ownership.')
    return value.dwTime


def _fresh(observation):
    if not 0 <= time.monotonic() - observation.captured_at <= 5.0:
        raise DeviceRunError('The capture expired before action dispatch; observe again.')


@contextmanager
def _physical_coordinates(user):
    previous = user.SetThreadDpiAwarenessContext(C.c_void_p(-4))
    if not previous:
        raise DeviceRunError('Cannot establish physical per-monitor coordinates.')
    try:
        yield
    finally:
        if not user.SetThreadDpiAwarenessContext(previous):
            raise DeviceRunError('Cannot restore the runner DPI context.')


def desktop_preflight():
    """Read-only desktop/session check. It sends no input and captures no pixels."""
    kernel, user = _api()
    session = U32()
    if not kernel.ProcessIdToSessionId(kernel.GetCurrentProcessId(), C.byref(session)):
        raise DeviceRunError('Cannot identify the runner Windows session.')
    handle = user.OpenInputDesktop(0, False, 0x0001)
    name = C.create_unicode_buffer(256)
    needed = U32()
    if not handle:
        raise DeviceRunError('The active input desktop is unavailable.')
    try:
        if not user.GetUserObjectInformationW(handle, 2, name, C.sizeof(name), C.byref(needed)):
            raise DeviceRunError('Cannot identify the active input desktop.')
    finally:
        user.CloseDesktop(handle)
    console = kernel.WTSGetActiveConsoleSessionId()
    ready = session.value == console and name.value == 'Default'
    return {'session': session.value, 'console_session': console,
            'input_desktop': name.value, 'usable': ready}


def process_identity(pid, *, executable_sha256=None):
    kernel, _ = _api()
    if type(pid) is not int or pid <= 0:
        raise DeviceRunError('Invalid process ID.')
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        raise DeviceRunError('Cannot inspect the owned game process.')
    try:
        if kernel.WaitForSingleObject(handle, 0) != 258:
            raise DeviceRunError('The owned game process has exited.')
        created, ended, cpu_kernel, cpu_user = U64(), U64(), U64(), U64()
        if not kernel.GetProcessTimes(handle, C.byref(created), C.byref(ended), C.byref(cpu_kernel), C.byref(cpu_user)):
            raise DeviceRunError('Cannot identify game process creation time.')
        path, size = C.create_unicode_buffer(32768), U32(32768)
        if not kernel.QueryFullProcessImageNameW(handle, 0, path, C.byref(size)):
            raise DeviceRunError('Cannot identify the game executable path.')
        session = U32()
        if not kernel.ProcessIdToSessionId(pid, C.byref(session)):
            raise DeviceRunError('Cannot identify the game Windows session.')
        executable = str(Path(path.value).resolve())
        checksum = executable_sha256 or hash_file(Path(executable))
        return ProcessIdentity(pid, created.value, executable, checksum, session.value)
    finally:
        kernel.CloseHandle(handle)


def window_identity(hwnd, process):
    _, user = _api()
    pid = U32()
    if not user.IsWindow(hwnd) or not user.IsWindowVisible(hwnd):
        raise DeviceRunError('The owned game window is unavailable.')
    user.GetWindowThreadProcessId(hwnd, C.byref(pid))
    if pid.value != process.pid:
        raise DeviceRunError('The observed window belongs to another process.')
    with _physical_coordinates(user):
        rect = Rect()
        if not user.GetClientRect(hwnd, C.byref(rect)):
            raise DeviceRunError('Cannot inspect the game client area.')
        first, last = Point(rect.left, rect.top), Point(rect.right, rect.bottom)
        if not user.ClientToScreen(hwnd, C.byref(first)) or not user.ClientToScreen(hwnd, C.byref(last)):
            raise DeviceRunError('Cannot locate the game client area.')
        dpi = user.GetDpiForWindow(hwnd)
    if dpi == 0 or last.x <= first.x or last.y <= first.y:
        raise DeviceRunError('The game client area or DPI is invalid.')
    return WindowIdentity(hwnd, (first.x, first.y, last.x, last.y), dpi)


def _capture_worker(connection, process, window, output):
    """PrintWindow is unbounded, so only an owned disposable child may call it."""
    try:
        from PIL import Image
        from scripts import window_frame_capture as capture
        capture._declare()
        capture.set_dpi_aware()
        if process_identity(process.pid) != process or window_identity(window.hwnd, process) != window:
            raise DeviceRunError('The game changed before frame capture.')
        x, y, right, bottom = capture.window_rect(window.hwnd)
        width, height = right - x, bottom - y
        if width <= 0 or height <= 0 or width * height > 16_777_216 or capture.window_is_hung(window.hwnd):
            raise DeviceRunError('The game window is unavailable or hung.')
        _, user = _api()
        captured_at = time.monotonic()
        input_tick = _input_tick(user)
        pixels = capture.capture_window(window.hwnd, width, height)
        if pixels is None:
            raise DeviceRunError('Windows did not return target-window pixels.')
        left, top, cright, cbottom = window.client
        # BI_RGB's fourth byte is unused, frequently zero; it is not alpha.
        image = Image.fromarray(pixels[:, :, [2, 1, 0]], 'RGB').crop((left-x, top-y, cright-x, cbottom-y))
        extrema = image.getextrema()
        if max(high for low, high in extrema) <= 2 or all(high == low for low, high in extrema):
            raise DeviceRunError('The target-window capture is black or uniform; another capture route is required.')
        if process_identity(process.pid, executable_sha256=process.executable_sha256) != process or window_identity(window.hwnd, process) != window:
            raise DeviceRunError('The game changed during frame capture.')
        if _input_tick(user) != input_tick:
            raise DeviceRunError('Desktop input occurred during capture; the frame is not an action receipt.')
        output = Path(output)
        # New immutable evidence only, never replace a prior capture.
        with output.open('xb') as stream:
            image.save(stream, format='PNG')
            stream.flush()
            os.fsync(stream.fileno())
        connection.send({'path': str(output), 'sha256': hash_file(output),
                         'captured_at': captured_at, 'window': asdict(window),
                         'process': asdict(process), 'input_tick': input_tick,
                         'inspection': 'required'})
    except Exception as exc:
        connection.send({'error': str(exc)})
    finally:
        connection.close()


def capture_owned_window(process, window, output, *, run_id, sequence, timeout=8.0):
    """Return a fresh receipt; image inspection and game-state classification are separate."""
    if not 0 < timeout <= 30:
        raise DeviceRunError('Invalid frame capture timeout.')
    context = multiprocessing.get_context('spawn')
    parent, child = context.Pipe(duplex=False)
    worker = context.Process(target=_capture_worker, args=(child, process, window, str(Path(output).resolve())))
    worker.start()
    child.close()
    try:
        if not parent.poll(timeout):
            raise DeviceRunError('Target-window capture timed out; no game pixels were certified.')
        value = parent.recv()
        if 'error' in value:
            raise DeviceRunError(value['error'])
        value.update(run_id=run_id, sequence=sequence)
        return value
    finally:
        parent.close()
        worker.join(1.0)
        if worker.is_alive():
            # This child only captures; it never owns game input or the game.
            worker.terminate()
            worker.join(3.0)
        if worker.is_alive():
            raise DeviceRunError('The owned frame-capture worker has not exited.')


def _send(user, events):
    array = (Input * len(events))(*events)
    if user.SendInput(len(events), array, C.sizeof(Input)) != len(events):
        raise DeviceRunError('Windows did not accept every injected input event.')


def _release(user, held):
    events = []
    if 'left' in held:
        events.append(Input(type=0, mouse=MouseInput(dwFlags=0x0004)))
    if 'E' in held:
        events.append(Input(type=1, keyboard=KeyboardInput(wVk=0x45, dwFlags=0x0002)))
    if events:
        _send(user, events)


def _input_guardian(connection):
    """An independent child releases armed input if the runner disappears/stalls."""
    _, user = _api()
    held = ()
    try:
        connection.send('ready')
        while True:
            if not connection.poll(2.0):
                if held:
                    _release(user, held)
                    held = ()
                continue
            message = connection.recv()
            if message == 'stop':
                return
            if message == 'clear':
                held = ()
            elif message in ('left', 'E'):
                held = (message,)
            else:
                raise DeviceRunError('Invalid input guardian request.')
            connection.send('ready')
    except EOFError:
        pass
    finally:
        _release(user, held)
        connection.close()


class InputGuardian:
    def __enter__(self):
        context = multiprocessing.get_context('spawn')
        self.connection, child = context.Pipe()
        self.process = context.Process(target=_input_guardian, args=(child,), daemon=False)
        self.process.start()
        child.close()
        try:
            self._ack()
        except Exception:
            self.connection.close()
            self.process.join(5.0)
            # Startup failed before an arm request: this child owns no input.
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(3.0)
            if self.process.is_alive():
                raise DeviceRunError('The unarmed input supervisor did not exit after startup failure.')
            raise
        return self

    def _ack(self):
        if not self.connection.poll(5.0) or self.connection.recv() != 'ready':
            raise DeviceRunError('The input recovery supervisor is unavailable.')

    def request(self, message):
        self.connection.send(message)
        self._ack()

    def __exit__(self, *_):
        try:
            self.connection.send('stop')
        except (EOFError, BrokenPipeError, OSError):
            pass
        self.connection.close()
        self.process.join(5.0)
        # Never force-kill an input guardian while it may still own a release.
        if self.process.is_alive():
            raise DeviceRunError('The input recovery supervisor has not exited; retain this run for recovery.')
        if self.process.exitcode != 0:
            raise DeviceRunError('The input recovery supervisor failed; verify held input before continuing.')


class WindowsGameDriver:
    """Only operates on one previously established owned process/window."""

    def __init__(self, process, guardian, *, run_id):
        self.process, self.guardian, self.run_id = process, guardian, run_id
        self.kernel, self.user = _api()
        self.stamp = self._stamp()
        if process_identity(process.pid) != process:
            raise DeviceRunError('The owned game process changed before binding.')
        self.held = set()
        self.capture_receipt = None

    def capture(self, hwnd, output, *, sequence):
        window = window_identity(hwnd, self.process)
        self.capture_receipt = capture_owned_window(self.process, window, output,
            run_id=self.run_id, sequence=sequence)
        return dict(self.capture_receipt)

    def _stamp(self):
        info = Path(self.process.executable).stat()
        return info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino

    def verify_observation(self, observation):
        _fresh(observation)
        receipt = self.capture_receipt
        if (receipt is None or observation.run_id != self.run_id
                or observation.sequence != receipt['sequence']
                or observation.captured_at != receipt['captured_at']
                or observation.screenshot != receipt['path']
                or observation.screenshot_sha256 != receipt['sha256']
                or observation.input_tick != receipt['input_tick']
                or asdict(observation.window) != receipt['window']
                or asdict(observation.process) != receipt['process']):
            raise DeviceRunError('The observation is not bound to this run and current capture receipt.')
        if (observation.process != self.process or self._stamp() != self.stamp
                or process_identity(self.process.pid, executable_sha256=self.process.executable_sha256) != self.process):
            raise DeviceRunError('The bound game process was replaced or its executable changed.')
        if window_identity(observation.window.hwnd, self.process) != observation.window:
            raise DeviceRunError('The game window geometry or DPI changed; capture again.')
        if hash_file(Path(observation.screenshot)) != observation.screenshot_sha256:
            raise DeviceRunError('The observed screenshot changed.')
        desktop = desktop_preflight()
        if not desktop['usable'] or desktop['session'] != self.process.session:
            raise DeviceRunError('The input desktop changed or is unavailable.')
        if observation.input_tick is None or _input_tick(self.user) != observation.input_tick:
            raise DeviceRunError('Desktop input was detected after capture; observe again before continuing.')
        _fresh(observation)

    def _foreground(self, observation):
        self.verify_observation(observation)
        if self.user.GetForegroundWindow() != observation.window.hwnd:
            raise DeviceRunError('The owned game is no longer in the foreground.')
        _fresh(observation)

    def perform(self, action, observation):
        if action.kind in ('wait', 'observe_baseline'):
            return
        if action.kind == 'focus':
            self.verify_observation(observation)
            if not self.user.SetForegroundWindow(observation.window.hwnd):
                raise DeviceRunError('Windows refused the game focus request.')
            return
        self._foreground(observation)
        if action.kind == 'close':
            handle = self.kernel.OpenProcess(0x100000 | 0x1000, False, self.process.pid)
            if not handle:
                # An inaccessible PID is not proof of process exit.
                raise DeviceRunError('Cannot verify the owned game exit.')
            try:
                created, ended, cpu_kernel, cpu_user = U64(), U64(), U64(), U64()
                if (not self.kernel.GetProcessTimes(handle, C.byref(created), C.byref(ended), C.byref(cpu_kernel), C.byref(cpu_user))
                        or created.value != self.process.created):
                    raise DeviceRunError('The game PID was reused before its close request.')
                self._foreground(observation)
                if not self.user.PostMessageW(observation.window.hwnd, 0x0010, 0, 0):
                    raise DeviceRunError('The owned game refused an ordinary close request.')
                if self.kernel.WaitForSingleObject(handle, 15000) != 0:
                    raise DeviceRunError('The owned game has not exited; preserve evidence before recovery.')
            finally:
                self.kernel.CloseHandle(handle)
            return
        if action.kind == 'key' and action.key == 'E':
            if self.user.GetAsyncKeyState(0x45) & 0x8000:
                raise DeviceRunError('The E key is already held; input ownership is unknown.')
            self.guardian.request('E')
            try:
                self._foreground(observation)
            except BaseException:
                self.guardian.request('clear')
                raise
            self.held.add('E')
            _send(self.user, [Input(type=1, keyboard=KeyboardInput(wVk=0x45)),
                              Input(type=1, keyboard=KeyboardInput(wVk=0x45, dwFlags=0x0002))])
        elif action.kind == 'click':
            if self.user.GetAsyncKeyState(1) & 0x8000:
                raise DeviceRunError('The mouse button is already held; input ownership is unknown.')
            x, y = action.point
            left, top, right, bottom = observation.window.client
            if not 0 <= x < right - left or not 0 <= y < bottom - top:
                raise DeviceRunError('The input point is outside the observed game client area.')
            with _physical_coordinates(self.user):
                vx, vy = self.user.GetSystemMetrics(76), self.user.GetSystemMetrics(77)
                vw, vh = self.user.GetSystemMetrics(78), self.user.GetSystemMetrics(79)
            if vw <= 1 or vh <= 1:
                raise DeviceRunError('The desktop geometry is unavailable.')
            absolute = (round((left + x - vx) * 65535 / (vw - 1)),
                        round((top + y - vy) * 65535 / (vh - 1)))
            self.guardian.request('left')
            try:
                self._foreground(observation)
                with _physical_coordinates(self.user):
                    hit = self.user.WindowFromPoint(Point(left + x, top + y))
                if not hit or self.user.GetAncestor(hit, 2) != observation.window.hwnd:
                    raise DeviceRunError('The observed click point is covered by another window.')
                _fresh(observation)
            except BaseException:
                self.guardian.request('clear')
                raise
            self.held.add('left')
            _send(self.user, [Input(type=0, mouse=MouseInput(dx=absolute[0], dy=absolute[1], dwFlags=0xC001)),
                              Input(type=0, mouse=MouseInput(dwFlags=0x0002)),
                              Input(type=0, mouse=MouseInput(dwFlags=0x0004))])
        else:
            raise DeviceRunError('Unsupported device action.')
        self.held.clear()
        self.guardian.request('clear')

    def release_inputs(self):
        _release(self.user, self.held)
        self.held.clear()
        self.guardian.request('clear')
