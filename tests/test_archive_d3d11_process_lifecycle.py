from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QProcess

from cdmw.ui.archive_browser.preview_d3d11_process import ArchivePreviewD3D11ProcessMixin
from cdmw.ui.archive_browser.preview_d3d11_runtime import ArchivePreviewD3D11RuntimeMixin


class _FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.kill_count = 0
        self._state = QProcess.Running

    def processId(self) -> int:
        return self.pid

    def state(self) -> object:
        return self._state

    def kill(self) -> None:
        self.kill_count += 1


class _FakeTimer:
    def __init__(self) -> None:
        self.stop_count = 0

    def stop(self) -> None:
        self.stop_count += 1


class _FakeLabel:
    def __init__(self) -> None:
        self.value = ""

    def setText(self, value: str) -> None:
        self.value = value


class _FakeStack:
    def __init__(self, current: object) -> None:
        self.current = current

    def currentWidget(self) -> object:
        return self.current

    def setCurrentWidget(self, value: object) -> None:
        self.current = value


class _LifecycleHarness(ArchivePreviewD3D11ProcessMixin, ArchivePreviewD3D11RuntimeMixin):
    def __init__(self) -> None:
        self.archive_isolated_renderer_generation_counter = 0
        self.archive_isolated_renderer_generations: dict[int, tuple[object, int, Path | None]] = {}
        self.archive_isolated_renderer_expected_stops: dict[int, tuple[object, str, dict[str, object]]] = {}
        self.archive_isolated_renderer_process: object | None = None
        self.archive_isolated_renderer_active_process: object | None = None
        self.archive_isolated_renderer_last_status_payload: dict[str, object] = {}
        self.archive_isolated_renderer_status_timer = _FakeTimer()
        self.archive_d3d11_preview_host = object()
        self.archive_model_preview = object()
        self.archive_preview_stack = _FakeStack(self.archive_d3d11_preview_host)
        self.archive_d3d11_preview_status_label = _FakeLabel()
        self.events: list[tuple[str, dict[str, object]]] = []
        self.messages: list[tuple[str, bool]] = []
        self.hard_failures: list[str] = []
        self.debug_messages: list[str] = []

    def activate(
        self,
        process: _FakeProcess,
        payload: dict[str, object] | None = None,
        status_file: Path | None = None,
    ) -> int:
        generation = self._register_archive_isolated_renderer_process(  # type: ignore[arg-type]
            process,
            status_file,
        )
        self.archive_isolated_renderer_process = process
        self.archive_isolated_renderer_active_process = process
        self.archive_isolated_renderer_last_status_payload = dict(payload or {})
        return generation

    def _record_runtime_event(self, event: str, **fields: object) -> None:
        self.events.append((event, dict(fields)))

    def _poll_archive_isolated_renderer_status(self) -> None:
        return

    def _discard_archive_d3d11_pending_package(self, *_args: object) -> bool:
        return False

    def _cleanup_archive_isolated_renderer_packages(self, **_kwargs: object) -> None:
        return

    def _set_archive_isolated_renderer_debug(self, message: str) -> None:
        self.debug_messages.append(message)

    def _format_archive_isolated_renderer_debug(self, payload: object) -> str:
        return str(payload)

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        self.messages.append((message, error))

    def _show_archive_d3d11_hard_failure(self, reason: str) -> bool:
        self.hard_failures.append(reason)
        return False


def test_expected_stop_is_bound_to_exact_process_and_generation() -> None:
    harness = _LifecycleHarness()
    expected_process = _FakeProcess(101)
    other_process = _FakeProcess(102)
    generation = harness.activate(expected_process)
    harness._mark_archive_isolated_renderer_expected_stop(  # type: ignore[arg-type]
        expected_process,
        generation,
        reason="shutdown",
    )

    assert harness._consume_archive_isolated_renderer_expected_stop(other_process, generation) is None  # type: ignore[arg-type]
    assert harness._consume_archive_isolated_renderer_expected_stop(expected_process, generation) == (  # type: ignore[arg-type]
        "shutdown",
        {},
    )


def test_old_expected_stop_cannot_suppress_new_process_failure() -> None:
    harness = _LifecycleHarness()
    old_process = _FakeProcess(201)
    old_generation = harness.activate(old_process)
    harness._mark_archive_isolated_renderer_expected_stop(  # type: ignore[arg-type]
        old_process,
        old_generation,
        reason="reload_fallback",
    )
    new_process = _FakeProcess(202)
    new_generation = harness.activate(new_process)

    harness._handle_archive_isolated_renderer_finished(  # type: ignore[arg-type]
        new_process,
        new_generation,
        62097,
        "CrashExit",
    )

    assert harness.hard_failures == ["Native D3D11 preview failed to load (exit 62097)."]


def test_expected_stop_suppresses_only_matching_nonzero_exit() -> None:
    harness = _LifecycleHarness()
    process = _FakeProcess(301)
    generation = harness.activate(process)
    harness._mark_archive_isolated_renderer_expected_stop(process, generation, reason="shutdown")  # type: ignore[arg-type]
    harness.archive_isolated_renderer_process = None

    harness._handle_archive_isolated_renderer_finished(process, generation, 62097, "CrashExit")  # type: ignore[arg-type]

    assert harness.hard_failures == []
    assert any(event == "d3d11_process_expected_stop_finished" for event, _fields in harness.events)


def test_genuine_62097_without_expected_stop_remains_failure() -> None:
    harness = _LifecycleHarness()
    process = _FakeProcess(401)
    generation = harness.activate(process)

    harness._handle_archive_isolated_renderer_finished(process, generation, 62097, "CrashExit")  # type: ignore[arg-type]

    assert harness.hard_failures == ["Native D3D11 preview failed to load (exit 62097)."]


def test_device_loss_is_not_suppressed_by_expected_stop(tmp_path: Path) -> None:
    harness = _LifecycleHarness()
    process = _FakeProcess(501)
    status_file = tmp_path / "host_status.json"
    generation = harness.activate(process, status_file=status_file)
    harness._mark_archive_isolated_renderer_expected_stop(process, generation, reason="shutdown")  # type: ignore[arg-type]
    status_file.write_text(
        json.dumps({"event": "device_lost", "device_loss_stage": "present"}),
        encoding="utf-8",
    )
    harness.archive_isolated_renderer_process = None

    harness._handle_archive_isolated_renderer_finished(process, generation, 62097, "CrashExit")  # type: ignore[arg-type]

    assert harness.hard_failures == ["Native D3D11 preview stopped after device loss during present (exit 62097)."]


def test_forced_kill_records_expected_stop_before_killing() -> None:
    harness = _LifecycleHarness()
    process = _FakeProcess(601)
    generation = harness.activate(process)

    harness._kill_archive_isolated_renderer_process_if_running(  # type: ignore[arg-type]
        process,
        generation=generation,
        reason="startup_timeout",
    )

    assert process.kill_count == 1
    assert harness._consume_archive_isolated_renderer_expected_stop(process, generation) == (  # type: ignore[arg-type]
        "startup_timeout",
        {},
    )
