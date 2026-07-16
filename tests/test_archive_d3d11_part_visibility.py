from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from cdmw.ui.archive_browser.preview_d3d11_parts import ArchivePreviewD3D11PartsMixin


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
    def __init__(self) -> None:
        self.hidden_source_submeshes: list[list[int]] = []

    def set_hidden_source_submeshes(self, indices: object) -> None:
        self.hidden_source_submeshes.append([int(index) for index in indices])


class _PartVisibilityHarness(ArchivePreviewD3D11PartsMixin):
    def __init__(self) -> None:
        self.archive_d3d11_part_visibility_menu = _FakeMenu()
        self.archive_d3d11_part_visibility_button = _FakeButton()
        self.archive_d3d11_preview_host = _FakePreviewHost()
        self.archive_d3d11_part_visibility_actions: dict[int, _FakeAction] = {}
        self.archive_d3d11_part_visibility_groups: dict[str, tuple[object, tuple[int, ...], bool]] = {}


def test_archive_preview_hides_prefab_parts_by_default(tmp_path: Path) -> None:
    package_dir = tmp_path / "preview"
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
