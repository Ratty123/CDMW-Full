"""Callback factories for static replacement dialog owner clusters."""

from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_sparse_history import (
    clone_mesh_for_static_replacement_native_first,
)


from cdmw.ui.archive_browser.static_replacement_dialog_mesh_diagnostics_callbacks import (
    create_alignment_mesh_diagnostics_callbacks,
)


from cdmw.ui.archive_browser.static_replacement_dialog_source_mix_callbacks import (
    create_alignment_source_mix_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_dialog_texture_detail_uv_callbacks import (
    create_alignment_texture_detail_uv_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_dialog_accept_dispatch_callbacks import (
    create_alignment_accept_dispatch_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_dialog_custom_icon_callbacks import (
    create_alignment_custom_icon_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_dialog_source_role_tree_callbacks import (
    create_alignment_source_role_tree_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_dialog_manual_profile_callbacks import (
    create_manual_material_profile_runtime_callbacks,
)


from cdmw.ui.archive_browser.static_replacement_dialog_material_authority_callbacks import (
    create_material_authority_adjustment_callbacks,
)

from cdmw.ui.archive_browser.static_replacement_dialog_factory_owners import (
    create_alignment_selected_part_control_callbacks as _create_alignment_selected_part_control_callbacks,
    create_alignment_source_part_assignment_callbacks as _create_alignment_source_part_assignment_callbacks,
    create_alignment_source_tree_selection_callbacks as _create_alignment_source_tree_selection_callbacks,
    create_alignment_accept_build_callbacks as _create_alignment_accept_build_callbacks,
    create_alignment_transform_drag_callbacks as _create_alignment_transform_drag_callbacks,
    create_alignment_parts_outliner_mapping_callbacks as _create_alignment_parts_outliner_mapping_callbacks,
    create_alignment_d3d11_loading_callbacks as _create_alignment_d3d11_loading_callbacks,
    create_alignment_refresh_queue_callbacks as _create_alignment_refresh_queue_callbacks,
    create_alignment_d3d11_package_lifecycle_callbacks as _create_alignment_d3d11_package_lifecycle_callbacks,
    create_alignment_preview_mode_callbacks as _create_alignment_preview_mode_callbacks,
    create_alignment_preview_model_callbacks as _create_alignment_preview_model_callbacks,
)

def create_alignment_selected_part_control_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return _create_alignment_selected_part_control_callbacks(context, globals())

def create_alignment_source_part_assignment_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return _create_alignment_source_part_assignment_callbacks(context, globals())

def create_alignment_source_tree_selection_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return _create_alignment_source_tree_selection_callbacks(context, globals())

def create_alignment_accept_build_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return _create_alignment_accept_build_callbacks(context, globals())

def create_alignment_transform_drag_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return _create_alignment_transform_drag_callbacks(context, globals())

def create_alignment_parts_outliner_mapping_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return _create_alignment_parts_outliner_mapping_callbacks(context, globals())

def create_alignment_d3d11_loading_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return _create_alignment_d3d11_loading_callbacks(context, globals())

def create_alignment_refresh_queue_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return _create_alignment_refresh_queue_callbacks(context, globals())

def create_alignment_d3d11_package_lifecycle_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return _create_alignment_d3d11_package_lifecycle_callbacks(context, globals())

def create_alignment_preview_mode_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return _create_alignment_preview_mode_callbacks(context, globals())

def create_alignment_preview_model_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return _create_alignment_preview_model_callbacks(context, globals())
