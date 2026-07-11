"""Mesh-edit and morph-slider callback factory for static replacement dialog."""

from __future__ import annotations

from collections.abc import Mapping as _MappingABC, Sequence as _SequenceABC
import time
from types import SimpleNamespace

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.services.mesh_workflow_service import (
    source_affine_for_transformed_preview as _default_source_affine_for_transformed_preview,
    source_normal_transform_for_transformed_preview as _default_source_normal_transform_for_transformed_preview,
)
from cdmw.ui.archive_browser.static_replacement_mesh_edit_state import (
    mesh_edit_has_inverse_transform_context as _default_mesh_edit_has_inverse_transform_context,
    mesh_edit_missing_nonempty_triangle_group_sources,
)
from cdmw.ui.archive_browser.static_replacement_sparse_history import (
    clear_mesh_history_snapshot_stack,
    release_mesh_history_snapshot,
    retain_mesh_history_snapshot,
)
from cdmw.ui.mesh_editor.controller import apply_native_update_to_host
from cdmw.ui.mesh_editor.native_preview_payloads import mesh_edit_selection_groups
from cdmw.ui.mesh_editor.static_replacement_adapter import StaticReplacementMeshEditSession
from cdmw.workers.mesh_editor_workers import MeshEditCommandWorker
_DEFAULT_INVERSE_TRANSFORM_HELPERS = {
    "source_affine_for_transformed_preview": _default_source_affine_for_transformed_preview,
    "source_normal_transform_for_transformed_preview": _default_source_normal_transform_for_transformed_preview,
}
_LEGACY_SCREEN_CAMERA_FIELDS = frozenset(
    {"camera_world", "yaw_degrees", "pitch_degrees", "distance", "vertical_fov_degrees", "pan"}
)


class _MeshEditDialogState:
    def __init__(self, context: dict[str, object]) -> None:
        self._get_replacement_mesh_for_mapping = context.get('_get_replacement_mesh_for_mapping')
        self._set_replacement_mesh_for_mapping = context.get('_set_replacement_mesh_for_mapping')
        self._get_replacement_mesh_base_for_mapping = context.get('_get_replacement_mesh_base_for_mapping')
        self._set_replacement_mesh_base_for_mapping = context.get('_set_replacement_mesh_base_for_mapping')
        self._get_replacement_preview_model = context.get('_get_replacement_preview_model')
        self._set_replacement_preview_model = context.get('_set_replacement_preview_model')

    @property
    def replacement_mesh_for_mapping(self):
        return self._get_replacement_mesh_for_mapping()

    @replacement_mesh_for_mapping.setter
    def replacement_mesh_for_mapping(self, value) -> None:
        self._set_replacement_mesh_for_mapping(value)

    @property
    def replacement_mesh_base_for_mapping(self):
        return self._get_replacement_mesh_base_for_mapping()

    @replacement_mesh_base_for_mapping.setter
    def replacement_mesh_base_for_mapping(self, value) -> None:
        self._set_replacement_mesh_base_for_mapping(value)

    @property
    def replacement_preview_model(self):
        return self._get_replacement_preview_model()

    @replacement_preview_model.setter
    def replacement_preview_model(self, value) -> None:
        self._set_replacement_preview_model(value)


def _native_screen_payload(payload: _MappingABC[object, object]) -> dict[object, object]:
    return {key: value for key, value in payload.items() if str(key) not in _LEGACY_SCREEN_CAMERA_FIELDS}


def create_alignment_mesh_edit_callbacks(context: dict[str, object]) -> SimpleNamespace:
    """Build the stable callback surface from bounded focused owners."""
    from cdmw.ui.archive_browser.static_replacement_mesh_edit_builder import (
        create_alignment_mesh_edit_callbacks as _create_callbacks,
    )

    return _create_callbacks(context, globals())
