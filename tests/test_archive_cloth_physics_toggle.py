"""The Archive Browser toolbar cloth toggle drives the shared preview settings.

The tool-side PBD solver, its per-batch particle/pin/constraint blobs and the
overlay push were already in place; only the Model Preview Settings dialog could
reach them, so the running simulation looked like an unexplained overlay. These
cover the toolbar control that exposes it next to ``Load textures``.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.archive_browser.preview_dotnet_lifecycle import (
    ArchivePreviewDotNetLifecycleMixin,
)


class _Checkbox:
    def __init__(self, checked: bool = False) -> None:
        self.checked = bool(checked)
        self.signals_blocked = False
        self.visible = False
        self.enabled = False

    def blockSignals(self, blocked: bool) -> bool:
        previous = self.signals_blocked
        self.signals_blocked = bool(blocked)
        return previous

    def setChecked(self, checked: bool) -> None:
        self.checked = bool(checked)

    def isChecked(self) -> bool:
        return self.checked

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


class _Harness(ArchivePreviewDotNetLifecycleMixin):
    def __init__(self, package: Path | None = None) -> None:
        self.settings = ModelPreviewRenderSettings(enable_tool_pbd_cloth_preview=False)
        self.settings_changes: list[ModelPreviewRenderSettings] = []
        self.messages: list[str] = []
        self.archive_cloth_physics_button = _Checkbox()
        self.archive_isolated_renderer_active_package = package

    def _current_model_preview_render_settings(self) -> ModelPreviewRenderSettings:
        return self.settings

    def _handle_model_preview_settings_changed(
        self, settings: ModelPreviewRenderSettings
    ) -> None:
        self.settings = settings
        self.settings_changes.append(settings)

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        assert error is False
        self.messages.append(message)


def _write_manifest(package: Path, cloth_batch_count: int) -> Path:
    package.mkdir(parents=True, exist_ok=True)
    (package / "manifest.json").write_text(
        json.dumps({"cloth_batch_count": cloth_batch_count}),
        encoding="utf-8",
    )
    return package


def test_toolbar_toggle_enables_the_tool_side_pbd_preference() -> None:
    harness = _Harness()

    harness.archive_cloth_physics_button.setChecked(True)
    harness._toggle_archive_cloth_physics_preview()

    assert [settings.enable_tool_pbd_cloth_preview for settings in harness.settings_changes] == [True]
    assert harness.messages == [
        "Cloth physics preview enabled; batches that declare PBD physics are simulated."
    ]


def test_toolbar_toggle_disables_and_reports_without_a_second_settings_write() -> None:
    harness = _Harness()
    harness.settings = replace(harness.settings, enable_tool_pbd_cloth_preview=True)

    harness.archive_cloth_physics_button.setChecked(False)
    harness._toggle_archive_cloth_physics_preview()
    # A redundant toggle must not re-enter the settings pipeline; the settings
    # hop re-syncs the checkbox and would otherwise bounce back through here.
    harness._toggle_archive_cloth_physics_preview()

    assert [settings.enable_tool_pbd_cloth_preview for settings in harness.settings_changes] == [False]
    assert harness.messages == ["Cloth physics preview disabled."]


def test_checkbox_follows_the_persisted_preference() -> None:
    harness = _Harness()
    harness.settings = replace(harness.settings, enable_tool_pbd_cloth_preview=True)

    harness._sync_archive_cloth_physics_action_state()

    assert harness.archive_cloth_physics_button.isChecked() is True
    # The sync must not emit toggled, or the settings hop becomes a feedback loop.
    assert harness.archive_cloth_physics_button.signals_blocked is False


def test_cloth_availability_reads_the_package_manifest(tmp_path: Path) -> None:
    assert _Harness()._archive_active_package_has_cloth_batches() is False

    without_cloth = _Harness(_write_manifest(tmp_path / "plain", 0))
    assert without_cloth._archive_active_package_has_cloth_batches() is False

    with_cloth = _Harness(_write_manifest(tmp_path / "cloak", 2))
    assert with_cloth._archive_active_package_has_cloth_batches() is True


def test_cloth_control_appears_while_textures_are_loaded(tmp_path: Path) -> None:
    """The texture-request completion path must bring the cloth control with it.

    It refreshes only the texture checkbox, so the cloth toggle stayed hidden for
    as long as textures were loaded and appeared only once Load textures was
    unticked -- which read as the control depending on textures.
    """

    harness = _Harness(_write_manifest(tmp_path / "cloak", 2))
    harness._archive_toolbar_resident_available = True
    harness._archive_toolbar_controls_enabled = True

    harness._sync_archive_cloth_physics_action_state()

    assert harness.archive_cloth_physics_button.visible is True
    assert harness.archive_cloth_physics_button.enabled is True


def test_cloth_control_stays_hidden_without_declared_cloth_batches(tmp_path: Path) -> None:
    harness = _Harness(_write_manifest(tmp_path / "plain", 0))
    harness._archive_toolbar_resident_available = True
    harness._archive_toolbar_controls_enabled = True

    harness._sync_archive_cloth_physics_action_state()

    assert harness.archive_cloth_physics_button.visible is False


def test_unreadable_manifest_reports_no_cloth_rather_than_raising(tmp_path: Path) -> None:
    package = tmp_path / "damaged"
    package.mkdir()
    (package / "manifest.json").write_text("{not json", encoding="utf-8")

    assert _Harness(package)._archive_active_package_has_cloth_batches() is False
