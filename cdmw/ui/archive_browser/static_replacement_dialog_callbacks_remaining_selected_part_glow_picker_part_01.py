from __future__ import annotations

def _remaining_selected_part_glow_picker_step_001(_state):
    _state.state = _state._StaticReplacementDialogState(_state.context)
    _state.QColor = _state.context.get('QColor')
    _state.QColorDialog = _state.context.get('QColorDialog')
    _state._selected_part_glow_rgb_from_controls = _state.context.get('_selected_part_glow_rgb_from_controls')
    _state._set_selected_source_glow_color = _state.context.get('_set_selected_source_glow_color')
    _state.color = _state.context.get('color')
    _state.dialog = _state.context.get('dialog')
    _state.part_glow_color_pick_button = _state.context.get('part_glow_color_pick_button')
    _state.part_glow_color_spins = _state.context.get('part_glow_color_spins')
    _state.rgb = _state.context.get('rgb')
    _state.spin = _state.context.get('spin')
    _state.value = _state.context.get('value')
    _state.prompt_shell_context = _state.context.get('prompt_shell_context')

def _remaining_selected_part_glow_picker_step_002(_state):

    def _prompt_context_value(name: str) -> object:
        if isinstance(_state.prompt_shell_context, dict) and name in _state.prompt_shell_context:
            return _state.prompt_shell_context.get(name)
        return _state.context.get(name)
    _state._prompt_context_value = _prompt_context_value

def _remaining_selected_part_glow_picker_step_003(_state):

    def _part_glow_color_pick_button() -> object:
        return _state._prompt_context_value('part_glow_color_pick_button')
    _state._part_glow_color_pick_button = _part_glow_color_pick_button

def _remaining_selected_part_glow_picker_step_004(_state):

    def _part_glow_color_spins() -> tuple[object, ...]:
        spins = _state._prompt_context_value('part_glow_color_spins')
        if not isinstance(spins, (list, tuple)):
            return ()
        return tuple((spin for spin in spins if callable(getattr(spin, 'blockSignals', None)) and callable(getattr(spin, 'setValue', None))))
    _state._part_glow_color_spins = _part_glow_color_spins

def _remaining_selected_part_glow_picker_step_005(_state):

    def _pick_selected_source_glow_color() -> None:
        pick_button = _state._part_glow_color_pick_button()
        if pick_button is None or not callable(getattr(pick_button, 'isEnabled', None)) or (not pick_button.isEnabled()) or (not callable(_state._selected_part_glow_rgb_from_controls)):
            return
        rgb = _state._selected_part_glow_rgb_from_controls()
        color = _state.QColorDialog.getColor(_state.QColor(rgb[0], rgb[1], rgb[2]), _state.dialog, 'Choose Glow Color')
        if not color.isValid():
            return
        for spin, value in zip(_state._part_glow_color_spins(), (color.red(), color.green(), color.blue())):
            spin.blockSignals(True)
            spin.setValue(int(value))
            spin.blockSignals(False)
        if callable(_state._set_selected_source_glow_color):
            _state._set_selected_source_glow_color()
    _state._pick_selected_source_glow_color = _pick_selected_source_glow_color

def _remaining_selected_part_glow_picker_step_006(_state):
    _state._factory_result_values.update({'_pick_selected_source_glow_color': _state._pick_selected_source_glow_color})

STEPS = (
    _remaining_selected_part_glow_picker_step_001,
    _remaining_selected_part_glow_picker_step_002,
    _remaining_selected_part_glow_picker_step_003,
    _remaining_selected_part_glow_picker_step_004,
    _remaining_selected_part_glow_picker_step_005,
    _remaining_selected_part_glow_picker_step_006,
)
