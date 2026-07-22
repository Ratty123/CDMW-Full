from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_manual_material_profile import (
    manual_material_profile_control_effect_states,
    material_authority_target_height_supported,
)
from cdmw.ui.archive_browser.static_replacement_material_authority_history import (
    MaterialAuthorityHistory,
    create_material_authority_history_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_dialog_routing_callbacks import (
    _load_source_part_glow_widget_values,
    _normalized_selected_glow_source_indices,
)


class _Widget:
    def __init__(self, value: object = 0, *, options: tuple[object, ...] = ()) -> None:
        self._value = value
        self._options = options
        self._enabled = True
        self._blocked = False
        self._tooltip = "edge source"

    def value(self) -> object:
        return self._value

    def setValue(self, value: object) -> None:
        self._value = value

    def isChecked(self) -> bool:
        return bool(self._value)

    def setChecked(self, value: object) -> None:
        self._value = bool(value)

    def currentData(self) -> object:
        return self._value

    def findData(self, value: object) -> int:
        try:
            return self._options.index(value)
        except ValueError:
            return -1

    def setCurrentIndex(self, index: int) -> None:
        self._value = self._options[index]

    def blockSignals(self, blocked: bool) -> bool:
        previous = self._blocked
        self._blocked = bool(blocked)
        return previous

    def setEnabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def isEnabled(self) -> bool:
        return self._enabled

    def setToolTip(self, text: str) -> None:
        self._tooltip = text

    def toolTip(self) -> str:
        return self._tooltip


class _Settings:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value


@dataclass
class _Shell:
    settings: _Settings


def test_selected_glow_indices_require_exact_current_selection_before_fallback() -> None:
    selected = {"index": 3}

    assert _normalized_selected_glow_source_indices(lambda: (4, 2, 4), selected) == (2, 4)
    assert _normalized_selected_glow_source_indices(lambda: (), selected) == (3,)
    assert _normalized_selected_glow_source_indices(lambda: (), {"index": -1}) == ()


def test_glow_widgets_load_each_parts_independent_color_and_strength_with_signals_blocked() -> None:
    color_checkbox = _Widget(False)
    color_spins = (_Widget(), _Widget(), _Widget())
    strength_checkbox = _Widget(False)
    strength_spin = _Widget(1.0)

    _load_source_part_glow_widget_values(
        SimpleNamespace(emissive_color_rgb=(12, 34, 56), emissive_strength=2.5),
        color_checkbox,
        color_spins,
        strength_checkbox,
        strength_spin,
    )
    assert color_checkbox.isChecked()
    assert tuple(spin.value() for spin in color_spins) == (12, 34, 56)
    assert strength_checkbox.isChecked()
    assert strength_spin.value() == 2.5
    assert not any(widget._blocked for widget in (color_checkbox, *color_spins, strength_checkbox, strength_spin))

    _load_source_part_glow_widget_values(
        SimpleNamespace(emissive_color_rgb=(200, 100, 50), emissive_strength=None),
        color_checkbox,
        color_spins,
        strength_checkbox,
        strength_spin,
    )
    assert tuple(spin.value() for spin in color_spins) == (200, 100, 50)
    assert not strength_checkbox.isChecked()
    assert strength_spin.value() == 1.0


def _history_context() -> tuple[dict[str, object], dict[str, object], dict[str, int]]:
    context: dict[str, object] = {
        "self": _Shell(_Settings()),
        "complete_swap_material_profile_combo": _Widget(
            "material_authority_manual",
            options=("material_authority_detail_mask", "material_authority_manual"),
        ),
        "edge_relief_source_combo": _Widget("hybrid", options=("hybrid", "preserve_target", "generate_source")),
        "texture_output_size_combo": _Widget("source", options=("source", "original")),
        "global_gloss_reduction_spin": _Widget(0),
        "auto_brightness_spin": _Widget(50),
        "source_brightness_spin": _Widget(0),
        "tone_contrast_spin": _Widget(0),
        "edge_relief_spin": _Widget(0),
        "accent_glow_spin": _Widget(0),
        "material_authority_undo_button": _Widget(),
        "material_authority_redo_button": _Widget(),
        "manual_profile_dirty": {"dirty": False},
        "manual_profile_ready": {"ready": True},
        "modify_original_texture_tuning_enabled_key": "settings/manual_tuning",
    }
    live_state = {"editor": False}
    context["_test_live_state"] = live_state
    context["_alignment_mesh_edit_tab_active"] = lambda: live_state["editor"]
    context["dialog"] = SimpleNamespace(
        _mesh_editor_embedded_dotnet_active=True,
        _mesh_editor_embedded_apply_material_parameters=lambda _groups: True,
    )
    for name in (
        "rebuild_sidecar_checkbox",
        "prune_unmapped_original_dds_checkbox",
        "inject_base_color_checkbox",
        "source_color_faithful_checkbox",
        "external_material_reset_checkbox",
        "complete_external_swap_checkbox",
        "unsafe_material_preflight_checkbox",
        "modify_original_texture_tuning_checkbox",
    ):
        context[name] = _Widget(False)
    manual = {"base_color_scale": 1.0, "force_nonmetal": False}
    refresh = {"resident": 0, "texture": 0, "output": 0, "resource_keys": []}
    context["_current_manual_material_profile_values"] = lambda: dict(manual)

    def apply_manual(values: dict[str, object], **_kwargs: object) -> None:
        manual.clear()
        manual.update(values)

    context["_apply_manual_material_profile_values"] = apply_manual
    context["_set_manual_profile_dirty"] = lambda dirty: context["manual_profile_dirty"].update(dirty=bool(dirty))
    context["_select_complete_swap_material_profile_silently"] = lambda value, **_kwargs: context[
        "complete_swap_material_profile_combo"
    ].setCurrentIndex(context["complete_swap_material_profile_combo"].findData(value))
    for key in ("global_gloss_reduction", "auto_brightness", "source_brightness", "tone_contrast", "edge_relief", "accent_glow"):
        context[f"_set_{key}"] = lambda value, refresh=False, name=key: context[f"{name}_spin"].setValue(value)
    context["_set_edge_relief_source_value"] = lambda value, refresh=False: context["edge_relief_source_combo"].setCurrentIndex(
        context["edge_relief_source_combo"].findData(value)
    )
    def queue_resident(*, resource_keys: tuple[str, ...] = ()) -> None:
        refresh["resident"] += 1
        refresh["resource_keys"].append(resource_keys)

    context["_queue_material_authority_adjustment_preview_refresh"] = queue_resident
    context["_queue_texture_preview_refresh"] = lambda: refresh.update(texture=refresh["texture"] + 1)
    context["_refresh_output_impact_review"] = lambda: refresh.update(output=refresh["output"] + 1)
    for name in (
        "_sync_complete_external_swap_mode",
        "_save_complete_swap_material_profile",
        "_refresh_sidecar_option_state",
        "_refresh_manual_material_profile_panel",
        "_refresh_global_gloss_reduction_hint",
        "_refresh_true_source_basic_controls_state",
    ):
        context[name] = lambda *_args, **_kwargs: None
    return context, manual, refresh


def test_history_is_bounded_copy_safe_and_coalesces_slider_ticks() -> None:
    history = MaterialAuthorityHistory(limit=3)
    history.reset({"value": 0, "nested": {"x": 0}})
    first = {"value": 1, "nested": {"x": 1}}
    history.record(first, coalesce_key="brightness")
    first["nested"]["x"] = 99
    history.record({"value": 2, "nested": {"x": 2}}, coalesce_key="brightness")
    assert history.depths == (1, 0)
    history.record({"value": 0, "nested": {"x": 0}}, coalesce_key="brightness")
    assert history.depths == (0, 0)
    history.record({"value": 2, "nested": {"x": 2}}, coalesce_key="brightness")
    assert history.undo() == {"value": 0, "nested": {"x": 0}}
    assert history.redo() == {"value": 2, "nested": {"x": 2}}
    history.finish_coalescing()
    history.record({"value": 3}, coalesce_key="brightness")
    assert history.depths == (2, 0)
    history.record({"value": 4}, coalesce_key="")
    history.record({"value": 3}, coalesce_key="")
    assert history.undo() == {"value": 4}
    assert history.redo() == {"value": 3}
    history.record({"value": 3}, coalesce_key="contrast")
    history.record({"value": 4}, coalesce_key="metal")
    assert history.depths == (2, 0)


def test_history_restore_preserves_export_controls_and_queues_resident_preview() -> None:
    context, manual, refresh = _history_context()
    context["_test_live_state"]["editor"] = True
    callbacks = create_material_authority_history_callbacks(context)
    callbacks.initialize()
    assert not context["edge_relief_source_combo"].isEnabled()

    context["global_gloss_reduction_spin"].setValue(20)
    callbacks.record("global_gloss_reduction")
    context["edge_relief_spin"].setValue(25)
    callbacks.record("edge_relief")
    assert not context["edge_relief_source_combo"].isEnabled()
    assert "resource rebind" in context["edge_relief_source_combo"].toolTip().lower()
    manual["base_color_scale"] = 0.5
    callbacks.record("manual:base_color_scale")

    assert callbacks.undo()
    assert manual["base_color_scale"] == 1.0
    assert context["global_gloss_reduction_spin"].value() == 20
    assert context["edge_relief_spin"].value() == 25
    assert refresh["resident"] == 1
    assert refresh["texture"] == 0
    assert callbacks.undo()
    assert context["edge_relief_spin"].value() == 0
    assert not context["edge_relief_source_combo"].isEnabled()
    assert callbacks.redo()
    assert context["edge_relief_spin"].value() == 25
    assert refresh["resident"] == 3
    assert refresh["resource_keys"] == [("*",), ("*",), ("*",)]
    assert refresh["texture"] == 0


def test_history_restores_complete_swap_and_output_size_outside_resident_editor() -> None:
    context, _manual, refresh = _history_context()
    sync: list[tuple[bool, bool]] = []
    context["_sync_complete_external_swap_mode"] = (
        lambda checked, *, push_undo=True: sync.append((bool(checked), bool(push_undo)))
    )
    callbacks = create_material_authority_history_callbacks(context)
    callbacks.initialize()

    context["complete_external_swap_checkbox"].setChecked(True)
    callbacks.record()
    context["texture_output_size_combo"].setCurrentIndex(1)
    callbacks.record()
    assert callbacks.undo()
    assert context["texture_output_size_combo"].currentData() == "source"
    assert context["complete_external_swap_checkbox"].isChecked()
    assert callbacks.undo()
    assert not context["complete_external_swap_checkbox"].isChecked()
    assert sync == [(False, False)]
    assert refresh["resident"] == 0
    assert refresh["texture"] == 2


def test_live_editor_transition_resets_history_and_disables_resource_controls() -> None:
    context, _manual, _refresh = _history_context()
    callbacks = create_material_authority_history_callbacks(context)
    callbacks.initialize()
    context["global_gloss_reduction_spin"].setValue(20)
    callbacks.record("global_gloss_reduction")
    assert callbacks.history.can_undo

    context["_test_live_state"]["editor"] = True
    callbacks.refresh_controls()
    assert not callbacks.history.can_undo
    assert context["complete_swap_material_profile_combo"].isEnabled()
    assert not context["texture_output_size_combo"].isEnabled()
    assert context["global_gloss_reduction_spin"].isEnabled()

    context["_test_live_state"]["editor"] = False
    callbacks.refresh_controls()
    assert context["complete_swap_material_profile_combo"].isEnabled()
    assert context["texture_output_size_combo"].isEnabled()


def test_scoped_shortcut_preserves_text_editor_undo() -> None:
    context, _manual, _refresh = _history_context()

    class Focus:
        def inherits(self, name: str) -> bool:
            return name == "QLineEdit"

    focus = {"widget": Focus()}
    context["QApplication"] = SimpleNamespace(focusWidget=lambda: focus["widget"])
    callbacks = create_material_authority_history_callbacks(context)
    callbacks.initialize()
    context["global_gloss_reduction_spin"].setValue(20)
    callbacks.record("global_gloss_reduction")
    assert not callbacks.undo_from_shortcut()
    assert callbacks.history.can_undo
    focus["widget"] = None
    assert callbacks.undo_from_shortcut()
    assert context["global_gloss_reduction_spin"].value() == 0


def test_target_without_height_binding_disables_height_only_manual_controls(tmp_path: Path) -> None:
    base_binding = {"parameter_name": "_overlayColorTexture", "texture_role": "base"}
    height_binding = {"parameter_name": "_heightTexture", "texture_role": "height"}
    height_path = tmp_path / "height.dds"
    height_path.write_bytes(b"DDS readable height resource")
    readable_height_binding = {**height_binding, "resolved_path": str(height_path)}
    assert material_authority_target_height_supported(()) is None
    assert material_authority_target_height_supported((base_binding,)) is False
    assert material_authority_target_height_supported((base_binding, height_binding)) is False
    assert material_authority_target_height_supported((base_binding, readable_height_binding)) is True

    context, _manual, _refresh = _history_context()
    context["sidecar_bindings"] = (base_binding,)
    callbacks = create_material_authority_history_callbacks(context)
    callbacks.initialize()
    assert not context["edge_relief_spin"].isEnabled()
    assert "no height/displacement input" in context["edge_relief_spin"].toolTip().lower()

    states = manual_material_profile_control_effect_states(
        {"support_policy": "source_only"},
        control_keys=("displacement_scale_multiplier", "displacement_scale_max"),
        control_tooltips={},
        target_height_supported=False,
    )
    assert not states["displacement_scale_multiplier"]["enabled"]
    assert "no height/displacement input" in states["displacement_scale_multiplier"]["tooltip"].lower()
    supported = manual_material_profile_control_effect_states(
        {"support_policy": "source_only"},
        control_keys=("displacement_scale_multiplier",),
        control_tooltips={},
        target_height_supported=True,
    )
    assert supported["displacement_scale_multiplier"]["enabled"]

    resident = manual_material_profile_control_effect_states(
        {"mask_binding_mode": "detail_mask_material", "support_policy": "source_only"},
        control_keys=("roughness_scale", "scratch_roughness", "ao_default"),
        control_tooltips={},
        resident_parameter_only=True,
        resident_parameters_available=True,
    )
    assert not resident["roughness_scale"]["enabled"]
    assert not resident["scratch_roughness"]["enabled"]
    assert not resident["ao_default"]["enabled"]
    assert "material-resource channel" in resident["ao_default"]["tooltip"].lower()
    assert "material-resource channel" in resident["roughness_scale"]["tooltip"].lower()
    unavailable = manual_material_profile_control_effect_states(
        {"mask_binding_mode": "detail_mask_material"},
        control_keys=("roughness_scale",),
        control_tooltips={},
        resident_parameter_only=True,
        resident_parameters_available=False,
    )
    assert not unavailable["roughness_scale"]["enabled"]
    assert "channel is ready" in unavailable["roughness_scale"]["tooltip"].lower()


def test_material_authority_section_wires_buttons_and_scoped_shortcuts() -> None:
    root = Path(__file__).resolve().parents[1]
    setup = (root / "cdmw/ui/archive_browser/static_replacement_dialog_sections_setup_options_transform_part_01.py").read_text(
        encoding="utf-8"
    )
    wiring = (root / "cdmw/ui/archive_browser/static_replacement_dialog_sections_setup_options_transform_part_02.py").read_text(
        encoding="utf-8"
    )
    manual_runtime = (root / "cdmw/ui/archive_browser/static_replacement_dialog_manual_profile_callbacks.py").read_text(
        encoding="utf-8"
    )
    assert "MeshAlignmentMaterialAuthorityUndoButton" in setup
    assert "MeshAlignmentMaterialAuthorityRedoButton" in setup
    assert "_wire_material_authority_history()" in wiring
    assert "WidgetWithChildrenShortcut" in wiring
    assert "QKeySequence('Ctrl+Z')" in wiring
    assert "QKeySequence('Ctrl+Y')" in wiring
    assert "context.get('_queue_material_authority_adjustment_preview_refresh')" in manual_runtime
    assert "package_callback()" in manual_runtime
    assert "resident_material_parameters_available(dialog)" in manual_runtime
    assert "undo_from_shortcut" in setup
