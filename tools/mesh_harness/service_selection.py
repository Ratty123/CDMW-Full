from __future__ import annotations

from cdmw.domain.mesh import MeshEditCommand
from cdmw.domain.mesh import MeshEditSelection
from cdmw.services.mesh_service import MeshService

from tools.mesh_harness.fixtures import (
    _build_loose_edge_mesh,
    _build_malformed_face_mesh,
    build_synthetic_mesh,
)

from tools.mesh_harness.service_summary import (
    _command_summary,
    _selection_snapshot,
)

def _selection_operation_smoke(service: MeshService, session_id: str) -> dict[str, object]:
    service.apply_command(
        session_id,
        MeshEditCommand(
            "select",
            selection=MeshEditSelection.from_maps(
                vertices_by_submesh={0: (0,)},
                edges_by_submesh={0: ((0, 1),)},
                faces_by_submesh={0: (0,)},
                source_indices=(0,),
            ),
        ),
    )
    service.apply_command(
        session_id,
        MeshEditCommand(
            "select",
            selection=MeshEditSelection.from_maps(
                vertices_by_submesh={0: (3,)},
                edges_by_submesh={0: ((1, 2),)},
                faces_by_submesh={0: (1,)},
                source_indices=(1,),
            ),
            params={"operation": "add"},
        ),
    )
    added = _selection_snapshot(service.session_view(session_id).selection)
    service.apply_command(
        session_id,
        MeshEditCommand(
            "select",
            selection=MeshEditSelection.from_maps(
                vertices_by_submesh={0: (0,)},
                edges_by_submesh={0: ((0, 1),)},
                faces_by_submesh={0: (0,)},
                source_indices=(0,),
            ),
            params={"operation": "subtract"},
        ),
    )
    subtracted = _selection_snapshot(service.session_view(session_id).selection)
    service.apply_command(
        session_id,
        MeshEditCommand(
            "select",
            selection=MeshEditSelection.from_maps(
                vertices_by_submesh={0: (2, 3)},
                edges_by_submesh={0: ((1, 2), (2, 3))},
                faces_by_submesh={0: (1,)},
                source_indices=(1, 2),
            ),
            params={"operation": "toggle"},
        ),
    )
    toggled = _selection_snapshot(service.session_view(session_id).selection)
    return {
        "ok": bool(
            added["vertices_by_submesh"] == {"0": [0, 3]}
            and subtracted["vertices_by_submesh"] == {"0": [3]}
            and toggled["vertices_by_submesh"] == {"0": [2]}
            and added["edges_by_submesh"] == {"0": [[0, 1], [1, 2]]}
            and subtracted["edges_by_submesh"] == {"0": [[1, 2]]}
            and toggled["edges_by_submesh"] == {"0": [[2, 3]]}
            and toggled["faces_by_submesh"] == {}
            and toggled["source_indices"] == []
        ),
        "added": added,
        "subtracted": subtracted,
        "toggled": toggled,
    }

def _selection_pruning_smoke() -> dict[str, object]:
    service = MeshService()
    malformed_view = service.open_edit_session(_build_malformed_face_mesh(), session_id="selection-prune-malformed", mode="edit")
    service.apply_command(
        malformed_view.session_id,
        MeshEditCommand(
            "select",
            selection=MeshEditSelection.from_maps(
                vertices_by_submesh={0: (0, 3)},
                edges_by_submesh={0: ((0, 1), (0, 3))},
                faces_by_submesh={0: (0, 1)},
            ),
        ),
    )
    malformed = _selection_snapshot(service.session_view(malformed_view.session_id).selection)
    service.close_edit_session(malformed_view.session_id)

    loose_edge_view = service.open_edit_session(_build_loose_edge_mesh(), session_id="selection-prune-loose-edge", mode="edit")
    service.apply_command(
        loose_edge_view.session_id,
        MeshEditCommand("select", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 3), (1, 99))})),
    )
    loose_edge = _selection_snapshot(service.session_view(loose_edge_view.session_id).selection)
    service.close_edit_session(loose_edge_view.session_id)

    return {
        "ok": bool(
            malformed["vertices_by_submesh"] == {"0": [0, 3]}
            and malformed["edges_by_submesh"] == {"0": [[0, 1]]}
            and malformed["faces_by_submesh"] == {}
            and loose_edge["edges_by_submesh"] == {"0": [[0, 3]]}
        ),
        "malformed": malformed,
        "loose_edge": loose_edge,
    }

def _history_selection_smoke() -> dict[str, object]:
    service = MeshService()
    view = service.open_edit_session(build_synthetic_mesh(), session_id="history-selection-prune", mode="edit")
    duplicate = service.apply_command(
        view.session_id,
        MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})),
    )
    service.apply_command(
        view.session_id,
        MeshEditCommand("select", selection=MeshEditSelection.from_maps(faces_by_submesh={1: (0,)}, source_indices=(1,))),
    )
    before_undo = _selection_snapshot(service.session_view(view.session_id).selection)
    undo = service.undo(view.session_id)
    undo_view = service.session_view(view.session_id)
    after_undo = _selection_snapshot(undo_view.selection)
    service.close_edit_session(view.session_id)
    return {
        "ok": bool(
            duplicate.ok
            and duplicate.topology_changed
            and before_undo["source_indices"] == [1]
            and undo.ok
            and undo_view.submesh_count == 1
            and after_undo == {"vertices_by_submesh": {}, "edges_by_submesh": {}, "faces_by_submesh": {}, "source_indices": []}
        ),
        "duplicate": _command_summary(duplicate),
        "undo": _command_summary(undo),
        "before_undo": before_undo,
        "after_undo": after_undo,
        "submesh_count_after_undo": undo_view.submesh_count,
    }

def _history_context_smoke() -> dict[str, object]:
    service = MeshService()
    view = service.open_edit_session(build_synthetic_mesh(), session_id="history-context-restore", mode="edit")
    original_selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})
    service.apply_command(view.session_id, MeshEditCommand("select", selection=original_selection))
    duplicate = service.apply_command(view.session_id, MeshEditCommand("duplicate"))
    service.apply_command(
        view.session_id,
        MeshEditCommand("select", selection=MeshEditSelection.from_maps(faces_by_submesh={1: (0,)}, source_indices=(1,))),
    )
    undo = service.undo(view.session_id)
    undo_selection = _selection_snapshot(service.session_view(view.session_id).selection)
    redo = service.redo(view.session_id)
    redo_selection = _selection_snapshot(service.session_view(view.session_id).selection)
    service.close_edit_session(view.session_id)
    mode_view = service.open_edit_session(build_synthetic_mesh(), session_id="history-mode-restore", mode="object")
    service.apply_command(
        mode_view.session_id,
        MeshEditCommand("select", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})),
    )
    mode_duplicate = service.apply_command(mode_view.session_id, MeshEditCommand("duplicate", mode="edit"))
    mode_after_duplicate = service.session_view(mode_view.session_id).mode
    mode_undo = service.undo(mode_view.session_id)
    mode_after_undo = service.session_view(mode_view.session_id).mode
    mode_redo = service.redo(mode_view.session_id)
    mode_after_redo = service.session_view(mode_view.session_id).mode
    service.close_edit_session(mode_view.session_id)
    return {
        "ok": bool(
            duplicate.ok
            and duplicate.topology_changed
            and undo.ok
            and undo_selection["faces_by_submesh"] == {"0": [0]}
            and undo_selection["source_indices"] == []
            and redo.ok
            and redo_selection["faces_by_submesh"] == {"1": [0]}
            and redo_selection["source_indices"] == [1]
            and mode_duplicate.ok
            and mode_after_duplicate == "edit"
            and mode_undo.ok
            and mode_after_undo == "object"
            and mode_redo.ok
            and mode_after_redo == "edit"
        ),
        "duplicate": _command_summary(duplicate),
        "undo": _command_summary(undo),
        "redo": _command_summary(redo),
        "after_undo": undo_selection,
        "after_redo": redo_selection,
        "mode_restore": {
            "duplicate": _command_summary(mode_duplicate),
            "undo": _command_summary(mode_undo),
            "redo": _command_summary(mode_redo),
            "after_duplicate": mode_after_duplicate,
            "after_undo": mode_after_undo,
            "after_redo": mode_after_redo,
        },
    }
