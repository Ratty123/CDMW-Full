"""Bounded control-state history for static-replacement Material Authority."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Mapping

from cdmw.ui.archive_browser.static_replacement_manual_material_profile import (
    material_authority_target_height_supported,
)
from cdmw.ui.archive_browser.static_replacement_dotnet_material_bridge import (
    resident_material_parameters_available,
    resident_material_resources_available,
)


class MaterialAuthorityHistory:
    """Small copy-safe history; snapshots contain controls, never mesh data."""

    def __init__(self, *, limit: int = 64) -> None:
        self._limit = max(2, int(limit))
        self._states: list[dict[str, object]] = []
        self._cursor = -1
        self._coalesce_key = ""

    @property
    def can_undo(self) -> bool:
        return self._cursor > 0

    @property
    def can_redo(self) -> bool:
        return 0 <= self._cursor < len(self._states) - 1

    @property
    def depths(self) -> tuple[int, int]:
        return max(0, self._cursor), max(0, len(self._states) - self._cursor - 1)

    def reset(self, snapshot: Mapping[str, object]) -> None:
        self._states = [deepcopy(dict(snapshot))]
        self._cursor = 0
        self._coalesce_key = ""

    def record(self, snapshot: Mapping[str, object], *, coalesce_key: str = "") -> bool:
        state = deepcopy(dict(snapshot))
        if self._cursor < 0:
            self.reset(state)
            return False
        if state == self._states[self._cursor]:
            if not coalesce_key:
                self.finish_coalescing()
            return False
        del self._states[self._cursor + 1 :]
        key = str(coalesce_key or "")
        if key and key == self._coalesce_key and self._cursor > 0:
            if state == self._states[self._cursor - 1]:
                self._states.pop()
                self._cursor -= 1
                self._coalesce_key = ""
                return True
            self._states[self._cursor] = state
        else:
            self._states.append(state)
            self._cursor += 1
        self._coalesce_key = key
        overflow = len(self._states) - self._limit
        if overflow > 0:
            del self._states[:overflow]
            self._cursor -= overflow
        return True

    def finish_coalescing(self) -> None:
        self._coalesce_key = ""

    def undo(self) -> dict[str, object] | None:
        if not self.can_undo:
            return None
        self._cursor -= 1
        self._coalesce_key = ""
        return deepcopy(self._states[self._cursor])

    def redo(self) -> dict[str, object] | None:
        if not self.can_redo:
            return None
        self._cursor += 1
        self._coalesce_key = ""
        return deepcopy(self._states[self._cursor])


_CHECKBOX_NAMES = (
    "rebuild_sidecar_checkbox",
    "prune_unmapped_original_dds_checkbox",
    "inject_base_color_checkbox",
    "source_color_faithful_checkbox",
    "external_material_reset_checkbox",
    "complete_external_swap_checkbox",
    "unsafe_material_preflight_checkbox",
    "modify_original_texture_tuning_checkbox",
)

_BASIC_CONTROL_NAMES = (
    "global_gloss_reduction",
    "auto_brightness",
    "source_brightness",
    "tone_contrast",
    "edge_relief",
    "accent_glow",
)

_RESOURCE_CONTROL_NAMES = (
    "rebuild_sidecar_checkbox",
    "prune_unmapped_original_dds_checkbox",
    "inject_base_color_checkbox",
    "source_color_faithful_checkbox",
    "external_material_reset_checkbox",
    "complete_external_swap_checkbox",
    "modify_original_texture_tuning_checkbox",
    "texture_output_size_combo",
    "edge_relief_source_combo",
)

_BASIC_WIDGET_NAMES = tuple(
    f"{name}_{kind}"
    for name in _BASIC_CONTROL_NAMES
    for kind in ("slider", "spin")
) + ("true_source_basic_reset_button",)


def _set_checked_silently(widget: object, checked: object) -> None:
    setter = getattr(widget, "setChecked", None)
    blocker = getattr(widget, "blockSignals", None)
    if not callable(setter):
        return
    previous = bool(blocker(True)) if callable(blocker) else False
    try:
        setter(bool(checked))
    finally:
        if callable(blocker):
            blocker(previous)


def _set_combo_data_silently(widget: object, value: object) -> None:
    find_data = getattr(widget, "findData", None)
    setter = getattr(widget, "setCurrentIndex", None)
    blocker = getattr(widget, "blockSignals", None)
    if not callable(find_data) or not callable(setter):
        return
    index = int(find_data(value))
    if index < 0:
        return
    previous = bool(blocker(True)) if callable(blocker) else False
    try:
        setter(index)
    finally:
        if callable(blocker):
            blocker(previous)


class _MaterialAuthorityHistoryController:
    def __init__(self, context: dict[str, object]) -> None:
        self.context = context
        self.history = MaterialAuthorityHistory(limit=64)
        self.applying = False
        self.target_height_supported = material_authority_target_height_supported(context.get("sidecar_bindings"))
        edge_source = context.get("edge_relief_source_combo")
        tooltip = getattr(edge_source, "toolTip", None)
        self.edge_source_tooltip = str(tooltip() if callable(tooltip) else "")
        self.edge_tooltips = {
            name: str(getattr(context.get(name), "toolTip")())
            for name in ("edge_relief_slider", "edge_relief_spin")
            if callable(getattr(context.get(name), "toolTip", None))
        }
        self._live_disabled: dict[str, tuple[bool, str]] = {}
        self._last_editor_active: bool | None = None

    def _widget(self, name: str) -> object:
        return self.context.get(name)

    def _call(self, name: str, *args: object, **kwargs: object) -> object:
        callback = self.context.get(name)
        return callback(*args, **kwargs) if callable(callback) else None

    def capture(self) -> dict[str, object]:
        checkboxes = {
            name: bool(getattr(self._widget(name), "isChecked")())
            for name in _CHECKBOX_NAMES
            if callable(getattr(self._widget(name), "isChecked", None))
        }
        current_manual = self.context.get("_current_manual_material_profile_values")
        manual = current_manual() if callable(current_manual) else {}
        return {
            "profile": str(getattr(self._widget("complete_swap_material_profile_combo"), "currentData")() or ""),
            "texture_output_size": str(getattr(self._widget("texture_output_size_combo"), "currentData")() or "source"),
            "checkboxes": checkboxes,
            "global_gloss_reduction": int(getattr(self._widget("global_gloss_reduction_spin"), "value")()),
            "auto_brightness": int(getattr(self._widget("auto_brightness_spin"), "value")()),
            "source_brightness": int(getattr(self._widget("source_brightness_spin"), "value")()),
            "tone_contrast": int(getattr(self._widget("tone_contrast_spin"), "value")()),
            "edge_relief": int(getattr(self._widget("edge_relief_spin"), "value")()),
            "edge_relief_source": str(getattr(self._widget("edge_relief_source_combo"), "currentData")() or "hybrid"),
            "accent_glow": int(getattr(self._widget("accent_glow_spin"), "value")()),
            "manual": deepcopy(dict(manual or {})),
            "manual_dirty": bool((self.context.get("manual_profile_dirty") or {}).get("dirty", False)),
        }

    def _apply_checkboxes(self, values: Mapping[str, object]) -> None:
        for name, checked in values.items():
            _set_checked_silently(self._widget(str(name)), checked)
        settings = getattr(self.context.get("self"), "settings", None)
        tuning_key = self.context.get("modify_original_texture_tuning_enabled_key")
        if settings is not None and tuning_key:
            settings.setValue(str(tuning_key), bool(values.get("modify_original_texture_tuning_checkbox", False)))

    def _apply_basic_values(self, snapshot: Mapping[str, object]) -> None:
        self._call("_set_global_gloss_reduction", int(snapshot["global_gloss_reduction"]), refresh=False)
        self._call("_set_auto_brightness", int(snapshot["auto_brightness"]), refresh=False)
        self._call("_set_source_brightness", int(snapshot["source_brightness"]), refresh=False)
        self._call("_set_tone_contrast", int(snapshot["tone_contrast"]), refresh=False)
        self._call("_set_edge_relief", int(snapshot["edge_relief"]), refresh=False)
        self._call("_set_edge_relief_source_value", str(snapshot["edge_relief_source"]), refresh=False)
        self._call("_set_accent_glow", int(snapshot["accent_glow"]), refresh=False)

    def apply(self, snapshot: Mapping[str, object]) -> None:
        self.applying = True
        try:
            complete_swap = bool(
                dict(snapshot.get("checkboxes") or {}).get("complete_external_swap_checkbox", False)
            )
            complete_widget = self._widget("complete_external_swap_checkbox")
            previous_complete_swap = bool(getattr(complete_widget, "isChecked")())
            _set_checked_silently(complete_widget, complete_swap)
            if complete_swap != previous_complete_swap:
                self._call("_sync_complete_external_swap_mode", complete_swap, push_undo=False)
            self._call("_select_complete_swap_material_profile_silently", str(snapshot["profile"]), persist=True)
            self._apply_checkboxes(dict(snapshot.get("checkboxes") or {}))
            _set_combo_data_silently(
                self._widget("texture_output_size_combo"),
                str(snapshot.get("texture_output_size") or "source"),
            )
            self._apply_basic_values(snapshot)
            self._call(
                "_apply_manual_material_profile_values",
                dict(snapshot.get("manual") or {}),
                persist=True,
                refresh_preview=False,
            )
            self._call("_set_manual_profile_dirty", bool(snapshot.get("manual_dirty", False)))
            self._call("_save_complete_swap_material_profile")
        finally:
            self.applying = False
        self._call("_refresh_sidecar_option_state")
        self._call("_refresh_manual_material_profile_panel")
        self._call("_refresh_global_gloss_reduction_hint")
        self._call("_refresh_true_source_basic_controls_state")
        self._call("_refresh_output_impact_review")
        self.refresh_preview()
        self.refresh_controls()

    def _editor_active(self) -> bool:
        callback = self.context.get("_alignment_mesh_edit_tab_active")
        try:
            return bool(callback()) if callable(callback) else False
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    def _resident_parameters_available(self) -> bool:
        return resident_material_parameters_available(self.context.get("dialog"))

    def _resident_resources_available(self) -> bool:
        return resident_material_resources_available(self.context.get("dialog"))

    def refresh_preview(self) -> None:
        if self._editor_active():
            if self._resident_parameters_available() or self._resident_resources_available():
                callback = self.context.get("_queue_material_authority_adjustment_preview_refresh")
                if callable(callback):
                    try:
                        callback(resource_keys=("*",))
                    except TypeError:
                        callback()
            return
        self._call("_queue_texture_preview_refresh")

    def _set_live_disabled(self, name: str, *, disabled: bool, reason: str) -> None:
        widget = self._widget(name)
        set_enabled = getattr(widget, "setEnabled", None)
        if not callable(set_enabled):
            return
        if disabled:
            if name not in self._live_disabled:
                enabled = bool(getattr(widget, "isEnabled")())
                tooltip = str(getattr(widget, "toolTip")()) if callable(getattr(widget, "toolTip", None)) else ""
                self._live_disabled[name] = (enabled, tooltip)
            base_tooltip = self._live_disabled[name][1]
            set_enabled(False)
            if callable(getattr(widget, "setToolTip", None)):
                widget.setToolTip(f"{base_tooltip}\n\n{reason}" if base_tooltip else reason)
            return
        previous = self._live_disabled.pop(name, None)
        if previous is not None:
            set_enabled(previous[0])
            if callable(getattr(widget, "setToolTip", None)):
                widget.setToolTip(previous[1])

    def refresh_controls(self) -> None:
        self._call("_refresh_manual_profile_control_effects")
        editor_active = self._editor_active()
        resident_available = self._resident_parameters_available()
        resident_resources_available = self._resident_resources_available()
        if self._last_editor_active is None:
            self._last_editor_active = editor_active
        elif editor_active != self._last_editor_active:
            self.history.reset(self.capture())
            self._last_editor_active = editor_active
        resource_reason = (
            "Unavailable while Mesh Editor is active: this control requires a texture/resource rebind. "
            "Close Mesh Editor to use the existing package preview path."
        )
        parameter_reason = "Unavailable until the resident .NET material-parameter channel is Ready."
        for name in _RESOURCE_CONTROL_NAMES:
            self._set_live_disabled(name, disabled=editor_active, reason=resource_reason)
        for name in _BASIC_WIDGET_NAMES:
            self._set_live_disabled(
                name,
                disabled=editor_active and not resident_available,
                reason=parameter_reason,
            )
        undo_button = self._widget("material_authority_undo_button")
        redo_button = self._widget("material_authority_redo_button")
        if callable(getattr(undo_button, "setEnabled", None)):
            undo_button.setEnabled(self.history.can_undo and (not editor_active or resident_available or resident_resources_available))
        if callable(getattr(redo_button, "setEnabled", None)):
            redo_button.setEnabled(self.history.can_redo and (not editor_active or resident_available or resident_resources_available))
        edge_spin = self._widget("edge_relief_spin")
        edge_source = self._widget("edge_relief_source_combo")
        if self.target_height_supported is False:
            reason = "No effect: The target material has no height/displacement input."
            for name in ("edge_relief_slider", "edge_relief_spin"):
                widget = self._widget(name)
                if callable(getattr(widget, "setEnabled", None)):
                    widget.setEnabled(False)
                    tooltip = self.edge_tooltips.get(name, "")
                    widget.setToolTip(f"{tooltip}\n\n{reason}" if tooltip else reason)
            edge_source.setEnabled(False)
            edge_source.setToolTip(f"{self.edge_source_tooltip}\n\n{reason}" if self.edge_source_tooltip else reason)
            return
        if editor_active:
            return
        strength_enabled = bool(getattr(edge_spin, "isEnabled")())
        strength = int(getattr(edge_spin, "value")())
        source_enabled = strength_enabled and strength > 0
        edge_source.setEnabled(source_enabled)
        reason = "" if source_enabled or not strength_enabled else "No effect: Edge relief strength is 0."
        edge_source.setToolTip(
            f"{self.edge_source_tooltip}\n\n{reason}" if reason and self.edge_source_tooltip else reason or self.edge_source_tooltip
        )

    def initialize(self) -> None:
        self.history.reset(self.capture())
        self.refresh_controls()

    def record(self, key: str = "") -> bool:
        if self.applying or not bool((self.context.get("manual_profile_ready") or {}).get("ready", True)):
            return False
        changed = self.history.record(self.capture(), coalesce_key=key)
        self.refresh_controls()
        return changed

    def undo(self) -> bool:
        snapshot = self.history.undo()
        if snapshot is None:
            return False
        self.apply(snapshot)
        return True

    def redo(self) -> bool:
        snapshot = self.history.redo()
        if snapshot is None:
            return False
        self.apply(snapshot)
        return True

    def _connect(self, widget_name: str, signal_name: str, key: str) -> None:
        signal = getattr(self._widget(widget_name), signal_name, None)
        if signal is not None and callable(getattr(signal, "connect", None)):
            signal.connect(lambda *_args, history_key=key: self.record(history_key))

    def undo_from_shortcut(self) -> bool:
        return False if self._focus_owns_text_undo() else self.undo()

    def redo_from_shortcut(self) -> bool:
        return False if self._focus_owns_text_undo() else self.redo()

    def _focus_owns_text_undo(self) -> bool:
        application = self.context.get("QApplication")
        focus_widget = application.focusWidget() if application is not None else None
        inherits = getattr(focus_widget, "inherits", None)
        return bool(
            callable(inherits)
            and any(
                inherits(class_name)
                for class_name in ("QLineEdit", "QTextEdit", "QPlainTextEdit", "QAbstractSpinBox")
            )
        )

    def wire(self) -> None:
        self.initialize()
        self._connect("complete_swap_material_profile_combo", "currentIndexChanged", "")
        self._connect("texture_output_size_combo", "currentIndexChanged", "")
        self._connect("edge_relief_source_combo", "currentIndexChanged", "")
        for name in _CHECKBOX_NAMES:
            self._connect(name, "toggled", "")
        for name in _BASIC_CONTROL_NAMES:
            self._connect(f"{name}_slider", "valueChanged", name)
            self._connect(f"{name}_slider", "sliderReleased", "")
            self._connect(f"{name}_spin", "valueChanged", name)
            self._connect(f"{name}_spin", "editingFinished", "")
        controls = self.context.get("manual_profile_controls") or {}
        for key, control in controls.items():
            for widget in control if isinstance(control, tuple) else (control,):
                for signal_name in ("currentIndexChanged", "valueChanged", "toggled"):
                    self._connect_widget(
                        widget,
                        signal_name,
                        f"manual:{key}" if signal_name == "valueChanged" else "",
                    )
                self._connect_widget(widget, "editingFinished", "")
        for widgets in (self.context.get("manual_profile_effect_widgets") or {}).values():
            for widget in tuple(widgets or ()):
                self._connect_widget(widget, "sliderReleased", "")
        self._connect("true_source_basic_reset_button", "clicked", "")
        self._connect("manual_profile_apply_button", "clicked", "")
        self._connect("manual_profile_reset_button", "clicked", "")
        self._connect("manual_profile_preset_load_button", "clicked", "")
        self._connect("mesh_edit_enabled_checkbox", "toggled", "")
        self._widget("material_authority_undo_button").clicked.connect(self.undo)
        self._widget("material_authority_redo_button").clicked.connect(self.redo)

    def _connect_widget(self, widget: object, signal_name: str, key: str) -> None:
        signal = getattr(widget, signal_name, None)
        if signal is not None and callable(getattr(signal, "connect", None)):
            signal.connect(lambda *_args, history_key=key: self.record(history_key))


def create_material_authority_history_callbacks(context: dict[str, object]) -> SimpleNamespace:
    controller = _MaterialAuthorityHistoryController(context)
    return SimpleNamespace(
        history=controller.history,
        initialize=controller.initialize,
        wire=controller.wire,
        capture=controller.capture,
        apply=controller.apply,
        record=controller.record,
        undo=controller.undo,
        redo=controller.redo,
        undo_from_shortcut=controller.undo_from_shortcut,
        redo_from_shortcut=controller.redo_from_shortcut,
        refresh_preview=controller.refresh_preview,
        refresh_controls=controller.refresh_controls,
    )


__all__ = ["MaterialAuthorityHistory", "create_material_authority_history_callbacks"]
