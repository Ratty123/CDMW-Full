"""The window survives AI connections failing to start (packaging review, 2026-11-13)."""

from __future__ import annotations

import logging

from cdmw.ui.ai_connections import controller
from cdmw.ui.shell import app_window


def test_an_error_starting_ai_connections_leaves_the_app_running(monkeypatch, caplog) -> None:
    def broken(window, settings):
        raise RuntimeError("the pipe could not be created")

    monkeypatch.setattr(controller, "install_ai_connections", broken)
    with caplog.at_level(logging.ERROR):
        assert app_window._start_ai_connections(object(), object()) is None
    assert "AI connections could not start" in caplog.text


def test_ai_connections_start_as_before_when_nothing_fails(monkeypatch) -> None:
    started = object()
    monkeypatch.setattr(controller, "install_ai_connections", lambda window, settings: started)
    assert app_window._start_ai_connections(object(), object()) is started
