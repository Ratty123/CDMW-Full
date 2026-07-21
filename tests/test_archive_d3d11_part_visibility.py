from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from cdmw.ui.archive_browser.preview_d3d11_parts import ArchivePreviewD3D11PartsMixin
from cdmw.ui.archive_browser.preview_d3d11_runtime import ArchivePreviewD3D11RuntimeMixin


class _FakeSignal:
    def __init__(self) -> None:
        self.callbacks: list[Callable[..., object]] = []

    def connect(self, callback: Callable[..., object]) -> None:
        self.callbacks.append(callback)

    def emit(self, *args: object) -> None:
        for callback in tuple(self.callbacks):
            callback(*args)


class _FakeAction:
    def __init__(self, text: str) -> None:
        self.text = text
        self.checked = False
        self.toggled = _FakeSignal()
        self.triggered = _FakeSignal()

    def setCheckable(self, _checkable: bool) -> None:
        return

    def setChecked(self, checked: bool) -> None:
        changed = self.checked != bool(checked)
        self.checked = bool(checked)
        if changed:
            self.toggled.emit(self.checked)

    def isChecked(self) -> bool:
        return self.checked

    def setToolTip(self, _tooltip: str) -> None:
        return

    def setStatusTip(self, _status_tip: str) -> None:
        return

    def setData(self, _data: object) -> None:
        return


class _FakeMenu:
    def __init__(self) -> None:
        self.actions: list[_FakeAction] = []

    def clear(self) -> None:
        self.actions.clear()

    def addAction(self, text: str) -> _FakeAction:
        action = _FakeAction(text)
        self.actions.append(action)
        return action

    def addSeparator(self) -> None:
        return


class _FakeButton:
    def __init__(self) -> None:
        self.text = ""
        self.enabled = False
        self.visible = False

    def setText(self, text: str) -> None:
        self.text = text

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)


class _FakePreviewHost:
    def __init__(self, *, accept_commands: bool = True) -> None:
        self.accept_commands = bool(accept_commands)
        self.hidden_source_submeshes: list[list[int]] = []
        self.render_tuning_calls: list[object] = []

    def set_hidden_source_submeshes(self, indices: object) -> bool:
        if not self.accept_commands:
            return False
        self.hidden_source_submeshes.append([int(index) for index in indices])
        return True

    def set_render_tuning(self, settings: object) -> bool:
        if not self.accept_commands:
            return False
        self.render_tuning_calls.append(settings)
        return True


class _PartVisibilityHarness(ArchivePreviewD3D11PartsMixin, ArchivePreviewD3D11RuntimeMixin):
    def __init__(self, *, accept_commands: bool = True) -> None:
        self.archive_d3d11_part_visibility_menu = _FakeMenu()
        self.archive_d3d11_part_visibility_button = _FakeButton()
        self.archive_d3d11_preview_host = _FakePreviewHost(accept_commands=accept_commands)
        self.archive_d3d11_preview_status_label = _FakeButton()
        self.archive_d3d11_part_visibility_actions: dict[int, _FakeAction] = {}
        self.archive_d3d11_part_visibility_groups: dict[str, tuple[object, tuple[int, ...], bool]] = {}
        self.archive_isolated_renderer_status_file: Path | None = None
        self.archive_isolated_renderer_status_signature = (0, 0)
        self.archive_isolated_renderer_status_payload_text = ""
        self.archive_isolated_renderer_last_status_payload: dict[str, object] = {}
        self.archive_isolated_renderer_process = None
        self.runtime_events: list[tuple[str, dict[str, object]]] = []
        self.status_messages: list[tuple[str, bool]] = []

    def _record_archive_d3d11_runtime_event(self, event: str, **fields: object) -> None:
        self.runtime_events.append((event, dict(fields)))

    def _archive_qprocess_pid(self, _process: object) -> int:
        return 0

    def _promote_archive_d3d11_pending_package_if_loaded(self, _status_file: Path) -> None:
        return

    def _restore_archive_d3d11_pending_view_state(self) -> bool:
        return True

    def _current_model_preview_render_settings(self) -> object:
        return object()

    def _cleanup_archive_isolated_renderer_packages(self, *, include_active: bool = False) -> None:
        assert include_active is False

    def _set_archive_isolated_renderer_debug(self, _message: str) -> None:
        return

    def _format_archive_isolated_renderer_debug(self, _payload: object) -> str:
        return "loaded"

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        self.status_messages.append((message, bool(error)))

    def _record_archive_memory_audit(self, _event: str, **_fields: object) -> None:
        return


def _write_part_visibility_package(package_dir: Path) -> None:
    package_dir.mkdir()
    (package_dir / "manifest.json").write_text(
        json.dumps(
            {
                "batches": [
                    {
                        "index": 0,
                        "editor_identity": {
                            "source_submesh_index": 0,
                            "part_label": "Body",
                            "source_model_path": "character/body.pac",
                            "source_component_index": 0,
                            "prefab_component": False,
                        },
                    },
                    {
                        "index": 1,
                        "editor_identity": {
                            "source_submesh_index": 1,
                            "part_label": "Underwear",
                            "source_model_path": "character/underwear.pac",
                            "source_component_index": 1,
                            "prefab_component": True,
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


def test_archive_preview_hides_prefab_parts_by_default(tmp_path: Path) -> None:
    package_dir = tmp_path / "preview"
    _write_part_visibility_package(package_dir)
    harness = _PartVisibilityHarness()

    harness._populate_archive_d3d11_part_visibility_menu(package_dir)

    assert harness.archive_d3d11_part_visibility_actions[0].isChecked() is True
    assert harness.archive_d3d11_part_visibility_actions[1].isChecked() is False
    assert harness.archive_d3d11_preview_host.hidden_source_submeshes == [[1]]
    assert harness.archive_d3d11_part_visibility_button.text == "Parts 1/2"
    assert harness.archive_d3d11_part_visibility_button.enabled is True
    assert harness.archive_d3d11_part_visibility_button.visible is True

    harness.archive_d3d11_part_visibility_actions[1].setChecked(True)

    assert harness.archive_d3d11_preview_host.hidden_source_submeshes[-1] == []
    assert harness.archive_d3d11_part_visibility_button.text == "Parts 2/2"


def test_archive_preview_reapplies_default_prefab_visibility_after_first_renderer_load(tmp_path: Path) -> None:
    package_dir = tmp_path / "preview"
    _write_part_visibility_package(package_dir)
    harness = _PartVisibilityHarness(accept_commands=False)

    harness._populate_archive_d3d11_part_visibility_menu(package_dir)

    assert harness.archive_d3d11_part_visibility_actions[1].isChecked() is False
    assert harness.archive_d3d11_preview_host.hidden_source_submeshes == []

    harness.archive_d3d11_preview_host.accept_commands = True
    status_file = package_dir / "host_status.json"
    status_file.write_text(json.dumps({"event": "loaded", "batch_count": 2}), encoding="utf-8")
    harness.archive_isolated_renderer_status_file = status_file

    harness._poll_archive_isolated_renderer_status()

    assert harness.archive_d3d11_preview_host.hidden_source_submeshes == [[1]]
    assert harness.archive_d3d11_part_visibility_button.text == "Parts 1/2"
