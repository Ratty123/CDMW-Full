"""Source-part mutation callback factory for static replacement dialog."""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace

from cdmw.services.mesh_workflow_service import ParsedMesh
from cdmw.ui.archive_browser.source_mix_task_controller import (
    source_mix_task_controller_for_guard,
)
from cdmw.ui.archive_browser.static_replacement_sparse_history import (
    allow_python_full_mesh_clone_fallback,
    clear_mesh_history_snapshot_stack,
    clone_mesh_for_static_replacement_native_first,
    release_native_submesh_snapshot,
    replace_mesh_history_snapshot_stack,
)
from cdmw.workers.source_mix_workers import (
    SceneImportRequest,
    SceneImportTaskResult,
    run_scene_import,
)

from cdmw.ui.archive_browser.static_replacement_dialog_factory_runtime import (
    run_static_replacement_factory,
)
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_source_part_mutation_part_01 as _source_part_mutation_part_01
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_source_part_mutation_part_02 as _source_part_mutation_part_02


def create_alignment_source_part_mutation_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return run_static_replacement_factory(
        context,
        globals(),
        tuple(globals()),
        (*_source_part_mutation_part_01.STEPS, *_source_part_mutation_part_02.STEPS,),
    )
