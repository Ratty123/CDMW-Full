"""Preview controls must not accept input they silently discard.

Each case here reproduces a control that stayed live while its effect was
dropped, or an edit path that re-ran per slider tick instead of per settled
edit. They construct the real Builder dialog offscreen rather than asserting on
source text, because the defects were in runtime enablement and signal wiring.
"""

from __future__ import annotations

import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from cdmw.ui.archive_browser.static_replacement_dotnet_presentation import (
    effective_builder_comparison_mode,
)
from cdmw.ui.archive_browser.static_replacement_manual_material_profile import (
    manual_material_profile_inactive_reasons,
)
from cdmw.ui.archive_browser.static_replacement_viewport_display_modes import (
    MESH_PREVIEW_COMPACT_DISPLAY_MODE_OPTIONS,
    MESH_PREVIEW_DEFAULT_DISPLAY_MODE,
    MESH_PREVIEW_DISPLAY_MODE_OPTIONS,
    MESH_PREVIEW_TEXTURED_DISPLAY_MODES,
    untextured_fallback_display_mode,
)
from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace
from tests.mesh_builder_driver import APPLICATION as _APPLICATION
from tests.mesh_builder_driver import open_mesh_builder


@pytest.fixture
def builder():
    with open_mesh_builder(dialog_title="Preview control honesty") as driver:
        yield driver


def test_mesh_view_reaches_the_resident_viewport_while_edit_mesh_is_active(builder) -> None:
    forwarded: list[str] = []
    builder.dialog._mesh_editor_embedded_request_viewport_display = (
        lambda mode: (forwarded.append(mode), True)[1]
    )
    combo = builder.combo("MeshAlignmentViewportDisplayModeCombo")

    builder.set_mesh_edit(False)
    combo.setCurrentIndex(combo.findData("wire"))
    _APPLICATION.processEvents()
    assert forwarded == ["wire"]

    forwarded.clear()
    builder.set_mesh_edit(True)
    combo.setCurrentIndex(combo.findData("vertices"))
    _APPLICATION.processEvents()

    # Previously dropped, leaving the combo displaying a mode the viewport was
    # never put into.
    assert forwarded == ["vertices"]
    assert combo.currentData() == "vertices"


def test_preview_mode_is_disabled_while_edit_mesh_collapses_every_layout(builder) -> None:
    combo = builder.context.get("preview_mode_combo")
    assert combo is not None

    builder.set_mesh_edit(False)
    assert combo.isEnabled()
    enabled_tooltip = combo.toolTip()

    builder.set_mesh_edit(True)
    assert not combo.isEnabled()
    assert "Edit Mesh" in combo.toolTip()
    # The combo is disabled precisely because every option resolves the same way.
    assert {
        effective_builder_comparison_mode(combo.itemData(index), True)
        for index in range(combo.count())
    } == {"replacement_only"}

    builder.set_mesh_edit(False)
    assert combo.isEnabled()
    assert combo.toolTip() == enabled_tooltip


def test_both_mesh_view_controls_offer_the_same_modes_and_default(builder) -> None:
    workspace = MeshEditorWorkspace(embedded_controls_only=True)
    try:
        workspace_combo = workspace.viewport_display_combo
        workspace_modes = [
            workspace_combo.itemData(index) for index in range(workspace_combo.count())
        ]
        builder_combo = builder.combo("MeshAlignmentViewportDisplayModeCombo")
        builder_modes = [
            builder_combo.itemData(index) for index in range(builder_combo.count())
        ]

        expected = [mode for _label, mode in MESH_PREVIEW_DISPLAY_MODE_OPTIONS]
        assert workspace_modes == expected
        assert builder_modes == expected
        assert workspace_combo.currentData() == MESH_PREVIEW_DEFAULT_DISPLAY_MODE
        assert builder_combo.currentData() == MESH_PREVIEW_DEFAULT_DISPLAY_MODE
    finally:
        workspace.deleteLater()
        _APPLICATION.processEvents()


def test_tool_rail_mesh_view_labels_fit_the_control(builder) -> None:
    """The rail caps this combo, so its labels must not render elided."""
    workspace = MeshEditorWorkspace(embedded_controls_only=True)
    try:
        combo = workspace.viewport_display_combo
        metrics = combo.fontMetrics()
        # Leave room for the drop-down indicator and frame.
        available = combo.maximumWidth() - 30
        assert available > 0

        overflowing = [
            combo.itemText(index)
            for index in range(combo.count())
            if metrics.horizontalAdvance(combo.itemText(index)) > available
        ]
        assert not overflowing, f"tool rail labels do not fit: {overflowing}"

        # The compact text is still traceable to the full label.
        for index, (_compact, mode) in enumerate(
            MESH_PREVIEW_COMPACT_DISPLAY_MODE_OPTIONS
        ):
            assert combo.itemData(index) == mode
            assert (
                combo.itemData(index, Qt.ItemDataRole.ToolTipRole)
                == MESH_PREVIEW_DISPLAY_MODE_OPTIONS[index][0]
            )
    finally:
        workspace.deleteLater()
        _APPLICATION.processEvents()


def test_textured_modes_fall_back_to_their_own_untextured_pair() -> None:
    """A pending texture load must not silently drop the wire overlay."""
    assert MESH_PREVIEW_TEXTURED_DISPLAY_MODES == {"textured", "textured_wire"}
    assert untextured_fallback_display_mode("textured") == "untextured_faces"
    assert untextured_fallback_display_mode("textured_wire") == "untextured_wire"
    # Non-textured modes need no fallback and must pass through unchanged.
    for _label, mode in MESH_PREVIEW_DISPLAY_MODE_OPTIONS:
        if mode in MESH_PREVIEW_TEXTURED_DISPLAY_MODES:
            continue
        assert untextured_fallback_display_mode(mode) == mode


def test_manual_material_authority_drag_commits_once(builder) -> None:
    timer = getattr(builder.dialog, "_material_authority_manual_commit_timer", None)
    pending = getattr(
        builder.dialog, "_material_authority_manual_pending_resource_keys", None
    )
    flush = getattr(
        builder.dialog, "_material_authority_flush_manual_profile_changes", None
    )
    assert timer is not None and pending is not None and callable(flush)

    controls = builder.context.get("manual_profile_controls") or {}
    spin = controls.get("roughness_default")
    assert spin is not None

    timer.stop()
    pending.clear()
    start = int(spin.value())
    steps = 40
    for step in range(steps):
        spin.setValue(max(spin.minimum(), start - step - 1))
    _APPLICATION.processEvents()

    # A drag leaves exactly one coalesced commit outstanding, not one per tick.
    assert spin.value() == start - steps
    assert timer.isActive()
    assert pending == {"roughness_default"}

    flush()
    assert not timer.isActive()
    assert pending == set()

    settings_key = builder.context.get("manual_profile_settings_key")
    stored = json.loads(str(builder.settings.value(settings_key, "{}")))
    assert stored.get("roughness_default") == start - steps


def test_full_apply_supersedes_a_pending_debounced_edit(builder) -> None:
    """Reset/preset load persist everything themselves.

    Letting the coalesced commit fire afterwards would re-persist the same
    profile and queue a second preview refresh for no reason.
    """
    timer = getattr(builder.dialog, "_material_authority_manual_commit_timer", None)
    pending = getattr(
        builder.dialog, "_material_authority_manual_pending_resource_keys", None
    )
    reset_button = builder.dialog.findChild(
        QPushButton, "MeshAlignmentManualMaterialProfileResetButton"
    )
    controls = builder.context.get("manual_profile_controls") or {}
    spin = controls.get("roughness_default")
    assert timer is not None and pending is not None and reset_button is not None
    assert spin is not None

    # Reset only rewrites the profile once the manual route is the selected one.
    profile_combo = builder.context.get("complete_swap_material_profile_combo")
    assert profile_combo is not None
    manual_index = profile_combo.findData("material_authority_manual")
    assert manual_index >= 0
    profile_combo.setCurrentIndex(manual_index)
    _APPLICATION.processEvents()

    timer.stop()
    pending.clear()
    edited = max(spin.minimum(), int(spin.value()) - 7)
    spin.setValue(edited)
    assert timer.isActive()
    assert pending

    reset_button.click()
    _APPLICATION.processEvents()

    assert spin.value() != edited, "reset did not rewrite the control"
    assert not timer.isActive()
    assert pending == set()


def test_manual_apply_and_status_sit_below_the_controls(builder) -> None:
    layout = builder.context.get("manual_profile_layout")
    apply_button = builder.context.get("manual_profile_apply_button")
    status = builder.context.get("manual_profile_change_status")
    controls = builder.context.get("manual_profile_controls") or {}
    assert layout is not None and apply_button is not None and status is not None

    rows: dict[object, int] = {}
    apply_row_index: int | None = None
    for index in range(layout.count()):
        item = layout.itemAt(index)
        row = layout.getItemPosition(index)[0]
        widget = item.widget()
        if widget is not None:
            rows[widget] = row
            continue
        nested = item.layout()
        if nested is None:
            continue
        for nested_index in range(nested.count()):
            if nested.itemAt(nested_index).widget() is apply_button:
                apply_row_index = row

    status_index = rows.get(status)
    assert apply_row_index is not None and status_index is not None

    control_rows = [
        rows[control]
        for control in controls.values()
        if not isinstance(control, tuple) and control in rows
    ]
    assert control_rows
    last_control_row = max(control_rows)

    assert status_index > last_control_row
    assert apply_row_index > last_control_row
    assert apply_row_index > status_index


@pytest.mark.parametrize(
    ("cap", "expected_inactive"),
    ((0.0, True), (0.5, False)),
)
def test_height_scale_reports_the_zero_height_cap_gate(
    cap: float, expected_inactive: bool
) -> None:
    reasons = manual_material_profile_inactive_reasons(
        {"support_policy": "source_only", "displacement_scale_max": cap}
    )
    reason = reasons.get("displacement_scale_multiplier", "")

    assert bool(reason) is expected_inactive
    if expected_inactive:
        assert "Height cap" in reason


def test_keeping_original_support_still_wins_over_the_height_cap_gate() -> None:
    reasons = manual_material_profile_inactive_reasons(
        {"support_policy": "keep_original_support", "displacement_scale_max": 0.0}
    )

    assert "preserving original target height/detail" in reasons[
        "displacement_scale_multiplier"
    ]
    assert "displacement_scale_max" in reasons
