"""Per-part colour and glow authoring callbacks for the Builder inspector.

Split out of ``static_replacement_dialog_callbacks_selected_part_control_part_01``
when that owner reached its 1,000-line bound. These steps share the same factory
``_state``, so they see every widget and helper that owner's first step pulled
out of the construction context.
"""

from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_source_part_controls_state import (
    source_part_colour_swatch_state,
)

def _selected_part_colour_step_001(_state):

    def _colour_property_rgb(button: object, fallback: tuple[int, int, int]=(255, 255, 255)) -> tuple[int, int, int]:
        """Read a swatch button's stored colour, falling back to neutral."""
        if button is None or not callable(getattr(button, 'property', None)):
            return fallback
        raw = button.property('cdmwPartColourRgb')
        try:
            text = str(raw or '').strip().lstrip('#')
            if len(text) != 6:
                return fallback
            return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
        except (TypeError, ValueError):
            return fallback
    _state._colour_property_rgb = _colour_property_rgb

def _selected_part_colour_step_002(_state):

    def _part_colourise_rgb_from_controls() -> tuple[int, int, int]:
        return _state._colour_property_rgb(_state.part_material_colourise_pick_button)
    _state._part_colourise_rgb_from_controls = _part_colourise_rgb_from_controls

def _selected_part_colour_step_003(_state):

    def _refresh_part_colour_swatches(adjustment: object | None, *, enabled: bool) -> None:
        """Paint both swatches from the adjustment so a recolour is visible."""
        tint_rgb = _state._material_tint_values(adjustment)
        colourise_raw = tuple(getattr(adjustment, 'material_colourise_rgb', ()) or ()) if adjustment is not None else ()
        colourise_rgb = tuple(int(value) for value in colourise_raw[:3]) if len(colourise_raw) >= 3 else (255, 255, 255)
        for button, rgb in (
            (_state.part_material_tint_pick_button, tuple(int(value) for value in tint_rgb)),
            (_state.part_material_colourise_pick_button, colourise_rgb),
        ):
            if button is None:
                continue
            swatch = source_part_colour_swatch_state(rgb=rgb, enabled=enabled)
            if callable(getattr(button, 'setProperty', None)):
                button.setProperty('cdmwPartColourRgb', swatch.hex_color)
            if callable(getattr(button, 'setStyleSheet', None)):
                button.setStyleSheet(swatch.style_sheet)
    _state._refresh_part_colour_swatches = _refresh_part_colour_swatches

def _selected_part_colour_step_004(_state):

    def _pick_part_colour(button: object, title: str, on_picked) -> None:
        if button is None or not callable(getattr(button, 'isEnabled', None)) or not button.isEnabled():
            return
        if _state.QColorDialog is None or _state.QColor is None:
            return
        current = _state._colour_property_rgb(button)
        chosen = _state.QColorDialog.getColor(_state.QColor(current[0], current[1], current[2]), _state.dialog, title)
        if not chosen.isValid():
            return
        on_picked((int(chosen.red()), int(chosen.green()), int(chosen.blue())))
    _state._pick_part_colour = _pick_part_colour

def _selected_part_colour_step_005(_state):

    def _pick_selected_part_tint_colour() -> None:

        def _apply(rgb: tuple[int, int, int]) -> None:
            for spin, value in zip((_state.part_material_tint_r_spin, _state.part_material_tint_g_spin, _state.part_material_tint_b_spin), rgb):
                _state._set_double_spin_value_silently_helper(spin, float(value))
                try:
                    _state._sync_part_slider_from_spin(spin)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
            if callable(getattr(_state.part_material_tint_pick_button, 'setProperty', None)):
                _state.part_material_tint_pick_button.setProperty('cdmwPartColourRgb', f'#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}')
            _state._update_selected_part_material_adjustment()
        _state._pick_part_colour(_state.part_material_tint_pick_button, 'Choose Part Tint', _apply)
    _state._pick_selected_part_tint_colour = _pick_selected_part_tint_colour

def _selected_part_colour_step_006(_state):

    def _pick_selected_part_colourise_colour() -> None:

        def _apply(rgb: tuple[int, int, int]) -> None:
            if callable(getattr(_state.part_material_colourise_pick_button, 'setProperty', None)):
                _state.part_material_colourise_pick_button.setProperty('cdmwPartColourRgb', f'#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}')
            # Picking a colour with the strength still at zero would look like
            # a dead control, so seed a full repaint the user can dial back.
            if float(_state.part_material_colourise_strength_spin.value()) <= 0.0:
                _state._set_double_spin_value_silently_helper(_state.part_material_colourise_strength_spin, 100.0)
                try:
                    _state._sync_part_slider_from_spin(_state.part_material_colourise_strength_spin)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
            _state._update_selected_part_material_adjustment()
        _state._pick_part_colour(_state.part_material_colourise_pick_button, 'Choose Part Colour', _apply)
    _state._pick_selected_part_colourise_colour = _pick_selected_part_colourise_colour

def _selected_part_colour_step_007(_state):

    def _reset_selected_part_colour() -> None:
        if _state.part_inspector_loading['active']:
            return
        neutral = (
            (_state.part_material_brightness_spin, 0.0),
            (_state.part_material_contrast_spin, 0.0),
            (_state.part_material_saturation_spin, 0.0),
            (_state.part_material_gamma_spin, 1.0),
            (_state.part_material_tint_r_spin, 255.0),
            (_state.part_material_tint_g_spin, 255.0),
            (_state.part_material_tint_b_spin, 255.0),
            (_state.part_material_colourise_strength_spin, 0.0),
        )
        for spin, value in neutral:
            if spin is None:
                continue
            _state._set_double_spin_value_silently_helper(spin, float(value))
            try:
                _state._sync_part_slider_from_spin(spin)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        for button in (_state.part_material_tint_pick_button, _state.part_material_colourise_pick_button):
            if button is not None and callable(getattr(button, 'setProperty', None)):
                button.setProperty('cdmwPartColourRgb', '#FFFFFF')
        _state._update_selected_part_material_adjustment()
    _state._reset_selected_part_colour = _reset_selected_part_colour

def _selected_part_colour_step_008(_state):

    def _glow_widget(name: str) -> object:
        """Reach a Material Authority glow widget built after these callbacks.

        The setup-options section is constructed later, so these widgets are
        only reachable through the prompt shell context at call time. This is
        the same deferred lookup the glow picker owner uses.
        """
        shell = _state.context.get('prompt_shell_context')
        if isinstance(shell, dict) and name in shell:
            return shell.get(name)
        return _state.context.get(name)
    _state._glow_widget = _glow_widget

def _selected_part_colour_step_009(_state):

    def _selected_part_is_emissive(adjustment: object | None) -> bool:
        return str(getattr(adjustment, 'material_role', '') or '').strip().lower() in {'glow', 'emissive'}
    _state._selected_part_is_emissive = _selected_part_is_emissive

def _selected_part_colour_step_010(_state):

    def _refresh_part_emissive_controls(adjustment: object | None, *, enabled: bool) -> None:
        """Load the inspector glow row from the adjustment without re-emitting."""
        emissive = _state._selected_part_is_emissive(adjustment)
        checkbox = _state.part_emissive_checkbox
        if checkbox is not None:
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(emissive))
            checkbox.blockSignals(False)
            checkbox.setEnabled(bool(enabled))
        rgb_raw = tuple(getattr(adjustment, 'emissive_color_rgb', ()) or ()) if adjustment is not None else ()
        rgb = tuple(int(value) for value in rgb_raw[:3]) if len(rgb_raw) >= 3 else (255, 255, 255)
        button = _state.part_emissive_pick_button
        if button is not None:
            swatch = source_part_colour_swatch_state(rgb=rgb, enabled=bool(enabled and emissive))
            button.setProperty('cdmwPartColourRgb', swatch.hex_color)
            button.setStyleSheet(swatch.style_sheet)
            button.setEnabled(bool(enabled and emissive))
        spin = _state.part_emissive_strength_spin
        if spin is not None:
            strength = getattr(adjustment, 'emissive_strength', None) if adjustment is not None else None
            _state._set_double_spin_value_silently_helper(spin, 1.0 if strength is None else float(strength))
            spin.setEnabled(bool(enabled and emissive))
    _state._refresh_part_emissive_controls = _refresh_part_emissive_controls

def _selected_part_colour_step_011(_state):

    def _toggle_selected_part_emissive(checked: bool) -> None:
        """Drive the existing role combo so material_role keeps one writer."""
        if _state.part_inspector_loading['active']:
            return
        combo = _state.part_role_combo
        if combo is None or not callable(getattr(combo, 'findData', None)):
            return
        index = combo.findData('glow' if checked else '')
        if index < 0 or combo.currentIndex() == index:
            return
        combo.setCurrentIndex(index)
    _state._toggle_selected_part_emissive = _toggle_selected_part_emissive

def _selected_part_colour_step_012(_state):

    def _commit_selected_part_emissive(*, rgb: tuple[int, int, int] | None, strength: float | None) -> None:
        """Mirror into the Material Authority glow widgets and reuse their write.

        Those widgets own the only path that activates the material route,
        pushes undo, and refreshes plan/preview, so duplicating it here would
        create a second writer for the same adjustment fields.
        """
        if _state.part_inspector_loading['active']:
            return
        if rgb is not None:
            checkbox = _state._glow_widget('part_glow_color_checkbox')
            if checkbox is not None and callable(getattr(checkbox, 'setChecked', None)):
                checkbox.blockSignals(True)
                checkbox.setChecked(True)
                checkbox.blockSignals(False)
            spins = tuple(_state._glow_widget('part_glow_color_spins') or ())
            for spin, value in zip(spins, rgb):
                if callable(getattr(spin, 'setValue', None)):
                    spin.blockSignals(True)
                    spin.setValue(int(value))
                    spin.blockSignals(False)
        if strength is not None:
            strength_checkbox = _state._glow_widget('part_glow_strength_checkbox')
            if strength_checkbox is not None and callable(getattr(strength_checkbox, 'setChecked', None)):
                strength_checkbox.blockSignals(True)
                strength_checkbox.setChecked(True)
                strength_checkbox.blockSignals(False)
            strength_spin = _state._glow_widget('part_glow_strength_spin')
            if strength_spin is not None and callable(getattr(strength_spin, 'setValue', None)):
                strength_spin.blockSignals(True)
                strength_spin.setValue(float(strength))
                strength_spin.blockSignals(False)
        _state._set_selected_source_glow_color()
    _state._commit_selected_part_emissive = _commit_selected_part_emissive

def _selected_part_colour_step_013(_state):

    def _pick_selected_part_emissive_colour() -> None:

        def _apply(rgb: tuple[int, int, int]) -> None:
            button = _state.part_emissive_pick_button
            if button is not None and callable(getattr(button, 'setProperty', None)):
                button.setProperty('cdmwPartColourRgb', f'#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}')
            _state._commit_selected_part_emissive(rgb=rgb, strength=None)
        _state._pick_part_colour(_state.part_emissive_pick_button, 'Choose Glow Colour', _apply)
    _state._pick_selected_part_emissive_colour = _pick_selected_part_emissive_colour

def _selected_part_colour_step_014(_state):

    def _set_selected_part_emissive_strength() -> None:
        spin = _state.part_emissive_strength_spin
        if spin is None:
            return
        _state._commit_selected_part_emissive(rgb=None, strength=float(spin.value()))
    _state._set_selected_part_emissive_strength = _set_selected_part_emissive_strength

def _selected_part_colour_step_016(_state):

    def _apply_part_colour_edit_values(adjustment: object, edit: dict) -> bool:
        """Write one normalized resident colour edit onto a part adjustment."""
        changed = False
        if edit.get('reset'):
            for attribute, value in (
                ('material_tint_rgb', ()),
                ('material_colourise_rgb', ()),
                ('material_colourise_strength', 0.0),
                ('material_brightness', 0.0),
                ('material_contrast', 0.0),
                ('material_saturation', 0.0),
                ('material_gamma', 1.0),
            ):
                if getattr(adjustment, attribute, None) != value:
                    setattr(adjustment, attribute, value)
                    changed = True
            return changed
        tint = edit.get('tint_rgb')
        if tint is not None:
            next_tint = () if tuple(tint) == (255, 255, 255) else tuple(tint)
            if tuple(getattr(adjustment, 'material_tint_rgb', ()) or ()) != next_tint:
                adjustment.material_tint_rgb = next_tint
                changed = True
        colourise = edit.get('colourise_rgb')
        if colourise is not None and tuple(getattr(adjustment, 'material_colourise_rgb', ()) or ()) != tuple(colourise):
            adjustment.material_colourise_rgb = tuple(colourise)
            changed = True
        strength = edit.get('colourise_strength')
        if strength is not None and abs(float(getattr(adjustment, 'material_colourise_strength', 0.0) or 0.0) - float(strength)) > 1e-9:
            adjustment.material_colourise_strength = float(strength)
            # A zero strength leaves the colour dormant rather than losing it.
            changed = True
        emissive = edit.get('emissive')
        if emissive is not None:
            next_role = 'glow' if emissive else ''
            if str(getattr(adjustment, 'material_role', '') or '') != next_role:
                adjustment.material_role = next_role
                changed = True
        glow_rgb = edit.get('emissive_rgb')
        if glow_rgb is not None and tuple(getattr(adjustment, 'emissive_color_rgb', ()) or ()) != tuple(glow_rgb):
            adjustment.emissive_color_rgb = tuple(glow_rgb)
            changed = True
        glow_strength = edit.get('emissive_strength')
        if glow_strength is not None and getattr(adjustment, 'emissive_strength', None) != float(glow_strength):
            adjustment.emissive_strength = float(glow_strength)
            changed = True
        return changed
    _state._apply_part_colour_edit_values = _apply_part_colour_edit_values

def _selected_part_colour_step_017(_state):

    def _mesh_editor_apply_dotnet_part_material_edit(edit: object) -> bool:
        """Host authority for the resident .NET Colour page.

        The child has already applied the edit to its own parameter mirror for
        immediate feedback. This writes the authoritative values, then lets the
        ordinary refresh path publish the exact result back to it.
        """
        if not isinstance(edit, dict):
            return False
        indices = tuple(edit.get('source_submesh_indices') or ())
        if not indices:
            return False
        if callable(_state._ensure_material_authority_route_active):
            _state._ensure_material_authority_route_active('resident_part_colour_edit')
        pending: list[tuple[int, object]] = []
        for raw_index in indices:
            try:
                source_index = int(raw_index)
            except (TypeError, ValueError, OverflowError):
                continue
            if source_index < 0:
                continue
            pending.append((source_index, _state._ensure_source_part_adjustment(source_index)))
        if not pending:
            return False
        # One undo unit for the whole edit, matching the inspector's behaviour.
        _state._push_geometry_undo_snapshot(
            _state._source_part_edit_undo_label_helper('material'),
            metadata_only=True,
        )
        changed = False
        for source_index, adjustment in pending:
            if _state._apply_part_colour_edit_values(adjustment, edit):
                changed = True
            if callable(_state._is_default_source_part_adjustment) and _state._is_default_source_part_adjustment(adjustment):
                _state.source_part_adjustments.pop(source_index, None)
        if not changed:
            return False
        _state.texture_overrides_dirty['dirty'] = True
        _state._refresh_ui_texture_sets_after_source_part_material_override()
        if callable(_state._load_selected_part_controls):
            _state._load_selected_part_controls()
        _state._queue_material_edit_refresh(
            refresh_plan=True,
            force_plan=False,
            refresh_preview=True,
            reason='resident part colour edit',
        )
        return True
    _state._mesh_editor_apply_dotnet_part_material_edit = _mesh_editor_apply_dotnet_part_material_edit
    if _state.dialog is not None:
        setattr(
            _state.dialog,
            '_mesh_editor_apply_dotnet_part_material_edit',
            _mesh_editor_apply_dotnet_part_material_edit,
        )

def _selected_part_colour_step_015(_state):
    _state._factory_result_values.update({
        '_mesh_editor_apply_dotnet_part_material_edit': _state._mesh_editor_apply_dotnet_part_material_edit,
        '_commit_selected_part_emissive': _state._commit_selected_part_emissive,
        '_pick_selected_part_colourise_colour': _state._pick_selected_part_colourise_colour,
        '_pick_selected_part_emissive_colour': _state._pick_selected_part_emissive_colour,
        '_pick_selected_part_tint_colour': _state._pick_selected_part_tint_colour,
        '_refresh_part_emissive_controls': _state._refresh_part_emissive_controls,
        '_reset_selected_part_colour': _state._reset_selected_part_colour,
        '_set_selected_part_emissive_strength': _state._set_selected_part_emissive_strength,
        '_toggle_selected_part_emissive': _state._toggle_selected_part_emissive,
    })

STEPS = (
    _selected_part_colour_step_001,
    _selected_part_colour_step_002,
    _selected_part_colour_step_003,
    _selected_part_colour_step_004,
    _selected_part_colour_step_005,
    _selected_part_colour_step_006,
    _selected_part_colour_step_007,
    _selected_part_colour_step_008,
    _selected_part_colour_step_009,
    _selected_part_colour_step_010,
    _selected_part_colour_step_011,
    _selected_part_colour_step_012,
    _selected_part_colour_step_013,
    _selected_part_colour_step_014,
    _selected_part_colour_step_016,
    _selected_part_colour_step_017,
    _selected_part_colour_step_015,
)
