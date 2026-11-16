from __future__ import annotations

import sys

import pytest

from cdmw.ui.shell import timer_resolution


class _Winmm:
    def __init__(self, result: int = 0) -> None:
        self.periods: list[int] = []
        self.result = result

    def timeBeginPeriod(self, period: int) -> int:  # noqa: N802 - Win32 name
        self.periods.append(period)
        return self.result


@pytest.fixture(autouse=True)
def _fresh_request(monkeypatch):
    monkeypatch.setattr(timer_resolution, "_requested", False)


def test_requests_a_one_millisecond_tick_from_system32_once(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    winmm = _Winmm()
    loads: list[tuple[str, int]] = []

    def loader(name, *, winmode):
        loads.append((name, winmode))
        return winmm

    assert timer_resolution.request_fine_timer_resolution(loader=loader)
    assert timer_resolution.request_fine_timer_resolution(loader=loader)
    assert winmm.periods == [1]
    assert loads == [("winmm", 0x00000800)]


@pytest.mark.parametrize("failure", ["refused", "missing"])
def test_a_failed_request_is_reported_and_retried(monkeypatch, failure):
    monkeypatch.setattr(sys, "platform", "win32")

    def loader(_name, *, winmode):
        if failure == "missing":
            raise OSError("winmm unavailable")
        return _Winmm(result=97)  # TIMERR_NOCANDO

    assert not timer_resolution.request_fine_timer_resolution(loader=loader)
    winmm = _Winmm()
    assert timer_resolution.request_fine_timer_resolution(loader=lambda _name, *, winmode: winmm)
    assert winmm.periods == [1]


def test_other_platforms_load_nothing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    def loader(*_args, **_kwargs):
        raise AssertionError("winmm must not be loaded")

    assert not timer_resolution.request_fine_timer_resolution(loader=loader)


@pytest.fixture
def _restore_switch_interval():
    saved = sys.getswitchinterval()
    yield
    sys.setswitchinterval(saved)


def test_the_gil_switch_interval_drops_to_one_millisecond(_restore_switch_interval):
    # Python's default 5 ms is what the GUI thread waited for the GIL behind a busy
    # worker at every Python event filter call: seconds for a few hundred events.
    sys.setswitchinterval(0.005)
    assert timer_resolution.request_short_gil_switch_interval() == pytest.approx(0.001)
    assert sys.getswitchinterval() == pytest.approx(timer_resolution.GIL_SWITCH_INTERVAL_S)
    assert timer_resolution.GIL_SWITCH_INTERVAL_S == pytest.approx(0.001)


def test_a_shorter_switch_interval_is_kept(_restore_switch_interval):
    sys.setswitchinterval(0.0005)
    assert timer_resolution.request_short_gil_switch_interval() == pytest.approx(0.0005)


def test_the_switch_interval_is_never_below_a_whole_millisecond():
    # Below 1 ms CPython's Windows wait rounds to 0 ms and the waiting thread spins.
    assert timer_resolution.GIL_SWITCH_INTERVAL_S >= 0.001
