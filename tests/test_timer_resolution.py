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
