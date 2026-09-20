"""Keep hidden Qt compatibility panels out of the resident editor's startup path."""
from functools import wraps


LEGACY_WIDGETS = frozenset('''
    animation_loop_button animation_play_button animation_rewind_button
    animation_scrub_slider animation_speed_combo animation_step_button history_list
    material_tree object_transform_link_scale object_transform_pivot_label
    object_transform_spins outliner part_clear_selection_button part_clone_button
    part_delete_button part_flip_normals_button part_invert_selection_button
    part_recalculate_normals_button part_select_all_button part_selection_summary_label
    pose_preview_button pose_reset_button properties_tree right_panels skeleton_tree performance_tree
    uv_canvas uv_clear_selection_button uv_select_all_button uv_summary_label uv_tree
    compare_mode_combo compare_tree left_tool_pages rig_pose_button rig_skeleton_button
    rig_weight_normalize_button rig_weight_transfer_button
'''.split())


def defer_panel_update(method):
    """Retain the latest immutable state per setter until a compatibility caller opens it."""
    @wraps(method)
    def update(self, *args, **kwargs):
        if self.__dict__.get('_legacy_panels_deferred', False):
            pending = self._pending_panel_updates
            pending.pop(method.__name__, None)
            pending[method.__name__] = (args, kwargs)
            return None
        return method(self, *args, **kwargs)
    return update


class LazyWorkspacePanelsMixin:
    def __getattr__(self, name):
        if name in LEGACY_WIDGETS and self.__dict__.get('_legacy_panels_deferred', False):
            self._ensure_legacy_panels()
            return getattr(self, name)
        raise AttributeError(name)

    def findChild(self, *args, **kwargs):  # noqa: N802 - Qt compatibility lookup
        result = super().findChild(*args, **kwargs)
        name = args[1] if len(args) > 1 else kwargs.get('name', '')
        if (result is None and str(name).startswith('MeshEditor')
                and self.__dict__.get('_legacy_panels_deferred', False)):
            self._ensure_legacy_panels()
            result = super().findChild(*args, **kwargs)
        return result

    def _ensure_legacy_panels(self):
        if not self._legacy_panels_deferred:
            return
        self._legacy_panels_deferred = False
        pending, self._pending_panel_updates = self._pending_panel_updates, {}
        for index, widget in ((0, self._build_left_palette()), (2, self._build_right_panels())):
            previous = self._body_splitter.replaceWidget(index, widget)
            widget.hide()
            previous.deleteLater()
        self._install_direct_output_controls(self._body_splitter.widget(1))
        for name, (args, kwargs) in pending.items():
            getattr(self, name)(*args, **kwargs)
        self.set_action_visibility(self._visible_action_keys)
        if self.__dict__.get('_last_action_state'):
            self.update_action_state(**self._last_action_state)
        if self.__dict__.get('_panel_fonts'):
            self.sync_ui_font(*self._panel_fonts)
