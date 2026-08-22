"""The readiness watchdog is a liveness check, not a fixed budget.

A helper reports ``startup_progress`` from inside its form constructor, where
its UI thread pumps nothing and no other event can prove it is alive. Each
report re-arms the 10 s deadline, bounded by a per-launch cap, so a loaded
machine gets a slow open instead of the restart loop that was observed on
2026-08-22 (eleven kills in a row, every one with ``renderer_ready`` false).
"""

from __future__ import annotations

import time
from pathlib import Path

from cdmw.ui.preview import dotnet_session
from tests.test_dotnet_preview_shared_host import _start_controller


def _progress(phase: str, at_ms: float) -> dict[str, object]:
    return {"event": "startup_progress", "phase": phase, "at_ms": at_ms}


def test_startup_progress_rearms_the_ready_watchdog_and_is_consumed(tmp_path: Path) -> None:
    controller, _process, _package = _start_controller(tmp_path)
    generation = controller.process_generation
    forwarded: list[str] = []
    controller.protocol_event.connect(lambda payload: forwarded.append(str(payload.get("event", ""))))

    assert controller._ready_timer.isActive()  # noqa: SLF001 - launch armed the deadline
    # Age the deadline so a re-arm is observable as a longer remaining time.
    controller._ready_timer.start(1_000)  # noqa: SLF001
    before = controller._ready_timer.remainingTime()  # noqa: SLF001

    controller._handle_protocol_event(_progress("viewport_created", 900.0), generation)  # noqa: SLF001

    assert controller._ready_timer.isActive()  # noqa: SLF001
    assert controller._ready_timer.remainingTime() > before  # noqa: SLF001
    assert controller._ready_watchdog_extensions == 1  # noqa: SLF001
    assert controller._last_event["event"] == "ready_watchdog_extended"  # noqa: SLF001
    assert controller._last_event["phase"] == "viewport_created"  # noqa: SLF001
    # The per-phase stream is a watchdog input, not something consumers see;
    # the helper's complete summary arrives separately and does pass through.
    assert "startup_progress" not in forwarded
    controller._handle_protocol_event(  # noqa: SLF001
        {"event": "startup_timing", "total_ms": 4200.0, "marks": []},
        generation,
    )
    assert forwarded[-1] == "startup_timing"


def test_startup_progress_cannot_extend_past_the_per_launch_cap(tmp_path: Path) -> None:
    controller, _process, _package = _start_controller(tmp_path)
    generation = controller.process_generation
    cap_seconds = dotnet_session._READY_PROGRESS_CAP_MS / 1000.0  # noqa: SLF001
    controller._ready_watchdog_started = time.monotonic() - cap_seconds  # noqa: SLF001
    controller._ready_timer.start(1_000)  # noqa: SLF001
    before = controller._ready_timer.remainingTime()  # noqa: SLF001

    controller._handle_protocol_event(_progress("tool_rail_sections_primed", 89_000.0), generation)  # noqa: SLF001

    assert controller._ready_watchdog_extensions == 0  # noqa: SLF001
    assert controller._ready_timer.remainingTime() <= before  # noqa: SLF001


def test_startup_progress_without_an_armed_watchdog_changes_nothing(tmp_path: Path) -> None:
    controller, _process, _package = _start_controller(tmp_path)
    generation = controller.process_generation
    controller._ready_timer.stop()  # noqa: SLF001

    controller._handle_protocol_event(_progress("form_constructed", 3_000.0), generation)  # noqa: SLF001

    assert not controller._ready_timer.isActive()  # noqa: SLF001
    assert controller._ready_watchdog_extensions == 0  # noqa: SLF001


def test_every_launch_opens_a_fresh_progress_budget(tmp_path: Path) -> None:
    controller, _process, _package = _start_controller(tmp_path)
    generation = controller.process_generation
    controller._handle_protocol_event(_progress("document_loaded", 200.0), generation)  # noqa: SLF001
    assert controller._ready_watchdog_extensions == 1  # noqa: SLF001
    started = controller._ready_watchdog_started  # noqa: SLF001

    controller._arm_ready_watchdog()  # noqa: SLF001 - what the next launch does

    assert controller._ready_watchdog_extensions == 0  # noqa: SLF001
    assert controller._ready_watchdog_started >= started  # noqa: SLF001
    assert controller._ready_timer.isActive()  # noqa: SLF001
