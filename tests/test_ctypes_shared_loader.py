"""ctypes functions on the shared `ctypes.windll` loader are typed per process, not per module."""

from __future__ import annotations

import ctypes
import os
from types import SimpleNamespace

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Win32 input state")
def test_native_input_poll_leaves_the_shared_user32_untouched():
    from cdmw.ui.archive_browser import runtime_state

    shared = ctypes.windll.user32.GetForegroundWindow
    previous = shared.restype
    shared.restype = ctypes.c_int
    try:
        state = runtime_state._native_input_state()
        assert shared.restype is ctypes.c_int, "The poll retyped GetForegroundWindow for the whole process"
    finally:
        shared.restype = previous
    assert state is None or (isinstance(state[0], int) and isinstance(state[1], bool) and isinstance(state[2], bool))


def test_focus_report_survives_no_foreground_window(monkeypatch):
    from cdmw.rendering import ingame_capture

    calls = []

    def record(name, result=0):
        def function(*args):
            calls.append(name)
            return result
        return function

    user32 = SimpleNamespace(
        GetWindowThreadProcessId=record("GetWindowThreadProcessId"),
        ShowWindow=record("ShowWindow"),
        AttachThreadInput=record("AttachThreadInput"),
        SetForegroundWindow=record("SetForegroundWindow"),
        BringWindowToTop=record("BringWindowToTop"),
        SetActiveWindow=record("SetActiveWindow"),
        SetFocus=record("SetFocus"),
        # A restype of HWND, as another module may set it, gives None here.
        GetForegroundWindow=record("GetForegroundWindow", None),
    )
    kernel32 = SimpleNamespace(GetCurrentThreadId=record("GetCurrentThreadId", 1))
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32, kernel32=kernel32), raising=False)
    monkeypatch.setattr(ingame_capture.time, "sleep", lambda _seconds: None)
    report = ingame_capture._focus_window_for_input(0x1234)
    assert report["foreground_hwnd"] == 0
    assert report["foreground_pid"] == 0
    assert report["foreground_ok"] is False
    assert "GetForegroundWindow" in calls
