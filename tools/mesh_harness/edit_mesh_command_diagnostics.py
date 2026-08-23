from __future__ import annotations

import time
from copy import deepcopy
from types import SimpleNamespace

from cdmw.domain.mesh import MeshEditSelection
from cdmw.ui.archive_browser.static_replacement_mesh_edit_actions import (
    create_actions_callbacks,
)
from cdmw.ui.mesh_editor.static_replacement_adapter import (
    StaticReplacementMeshEditSession,
)
from tools.mesh_editor_dev_harness import _build_two_part_synthetic_mesh


def _wait_for_action_idle(tab: object, app: object, timeout_seconds: float = 15.0) -> bool:
    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    while time.monotonic() < deadline:
        app.processEvents()
        if not tab._standalone_action_worker_active():
            app.processEvents()
            return True
        time.sleep(0.002)
    app.processEvents()
    return not tab._standalone_action_worker_active()


def _selection_payload(selection: MeshEditSelection) -> dict[str, object]:
    return {
        "vertices_by_submesh": selection.vertices_by_submesh,
        "edges_by_submesh": selection.edges_by_submesh,
        "faces_by_submesh": selection.faces_by_submesh,
        "source_indices": selection.source_indices,
        "empty": selection.is_empty(),
    }


def _selection_count(selection: MeshEditSelection, target: str) -> int:
    values = {
        "vertex": selection.vertex_map,
        "edge": selection.edge_map,
        "face": selection.face_map,
    }[target]()
    return sum(len(items) for items in values.values())


def _dispatch_command(
    tab: object,
    app: object,
    controller: object,
    command: str,
    request_sequence: int,
    **fields: object,
) -> tuple[dict[str, object], int]:
    request_sequence += 1
    revision = int(controller.session_view().revision)
    payload: dict[str, object] = {
        "event": "command_request",
        "command": command,
        "session_id": controller.session_view().session_id,
        "request_id": request_sequence,
        "base_revision": revision,
        "revision": revision,
        "edit_revision": revision,
        "process_generation": tab.standalone_dotnet_process_generation,
        "protocol_version": 2,
        **fields,
    }
    started = time.perf_counter()
    accepted = bool(tab._handle_dotnet_command_request(payload))
    dispatch_ms = (time.perf_counter() - started) * 1000.0
    idle = _wait_for_action_idle(tab, app)
    return (
        {
            "command": command,
            "accepted": accepted,
            "worker_idle": idle,
            "dispatch_ms": dispatch_ms,
            "request_id": request_sequence,
        },
        request_sequence,
    )


def _selection_command_cases(
    tab: object,
    app: object,
    controller: object,
    request_sequence: int,
) -> tuple[list[dict[str, object]], int]:
    cases: list[dict[str, object]] = []

    def run(
        command: str,
        *,
        seed_faces: tuple[int, ...] = (),
        target: str = "face",
        expected_count: int,
    ) -> None:
        nonlocal request_sequence
        controller.select(
            faces_by_submesh={0: seed_faces} if seed_faces else None,
            operation="replace",
        )
        selection = controller.session_view().selection
        fields: dict[str, object] = {"target_mode": target}
        if command not in {"select_all", "clear_selection"}:
            fields["local_selection"] = _selection_payload(selection)
        dispatched, request_sequence = _dispatch_command(
            tab, app, controller, command, request_sequence, **fields
        )
        after = controller.session_view().selection
        selected_count = _selection_count(after, target)
        cases.append(
            {
                **dispatched,
                "ok": dispatched["accepted"] is True
                and dispatched["worker_idle"] is True
                and selected_count == expected_count,
                "target": target,
                "seed_face_count": len(seed_faces),
                "selected_count": selected_count,
                "expected_count": expected_count,
            }
        )

    run("grow", seed_faces=(0,), expected_count=2)
    run("shrink", seed_faces=(0,), expected_count=0)
    run("invert", seed_faces=(0,), expected_count=1)
    run("select_all", target="vertex", expected_count=4)
    run("clear_selection", target="vertex", expected_count=0)
    return cases, request_sequence


def _axis_nudge_cases(
    tab: object,
    app: object,
    controller: object,
    request_sequence: int,
) -> tuple[list[dict[str, object]], dict[str, object], int]:
    cases: list[dict[str, object]] = []
    history_case: dict[str, object] = {"ok": False}
    for axis_index, axis in enumerate(("x", "y", "z")):
        for sign in (-1.0, 1.0):
            controller.select(vertices_by_submesh={0: (0,)}, operation="replace")
            selection = controller.session_view().selection
            before = tuple(controller.working_mesh(clone=True).submeshes[0].vertices[0])
            step = sign * 0.01
            delta = tuple(step if index == axis_index else 0.0 for index in range(3))
            dispatched, request_sequence = _dispatch_command(
                tab,
                app,
                controller,
                "transform_move",
                request_sequence,
                axis=axis,
                step=step,
                delta=delta,
                target_mode="vertex",
                local_selection=_selection_payload(selection),
            )
            after = tuple(controller.working_mesh(clone=True).submeshes[0].vertices[0])
            expected = tuple(before[index] + delta[index] for index in range(3))
            moved_exactly = all(
                abs(float(after[index]) - float(expected[index])) <= 1.0e-6
                for index in range(3)
            )
            if axis == "x" and sign > 0:
                undo, request_sequence = _dispatch_command(
                    tab, app, controller, "undo", request_sequence
                )
                after_undo = tuple(controller.working_mesh(clone=True).submeshes[0].vertices[0])
                redo, request_sequence = _dispatch_command(
                    tab, app, controller, "redo", request_sequence
                )
                after_redo = tuple(controller.working_mesh(clone=True).submeshes[0].vertices[0])
                history_case = {
                    "ok": undo["accepted"] is True
                    and undo["worker_idle"] is True
                    and redo["accepted"] is True
                    and redo["worker_idle"] is True
                    and after_undo == before
                    and after_redo == after,
                    "undo": undo,
                    "redo": redo,
                    "undo_restored": after_undo == before,
                    "redo_restored": after_redo == after,
                }
                controller.undo()
            else:
                controller.undo()
            cases.append(
                {
                    **dispatched,
                    "ok": dispatched["accepted"] is True
                    and dispatched["worker_idle"] is True
                    and moved_exactly,
                    "axis": axis,
                    "step": step,
                    "before": before,
                    "after": after,
                    "expected": expected,
                    "moved_exactly": moved_exactly,
                }
            )
    return cases, history_case, request_sequence


def _topology_cases(
    tab: object,
    app: object,
    controller: object,
    request_sequence: int,
) -> tuple[list[dict[str, object]], int]:
    expected = {
        "delete": (3, 1, 1),
        "duplicate": (7, 3, 2),
        "subdivide": (7, 6, 1),
        "refine_smooth": (7, 6, 1),
        "separate": (6, 2, 2),
    }
    cases: list[dict[str, object]] = []
    for command, expected_counts in expected.items():
        controller.select(faces_by_submesh={0: (0,)}, operation="replace")
        selection = controller.session_view().selection
        before = controller.session_view()
        dispatched, request_sequence = _dispatch_command(
            tab,
            app,
            controller,
            command,
            request_sequence,
            target_mode="face",
            local_selection=_selection_payload(selection),
        )
        after = controller.session_view()
        mesh_after = controller.working_mesh(clone=True)
        counts = (after.vertex_count, after.face_count, len(mesh_after.submeshes))
        undo = controller.undo()
        restored = controller.session_view()
        undo_restored = (
            restored.vertex_count,
            restored.face_count,
            len(controller.working_mesh(clone=True).submeshes),
        ) == (before.vertex_count, before.face_count, 1)
        cases.append(
            {
                **dispatched,
                "ok": dispatched["accepted"] is True
                and dispatched["worker_idle"] is True
                and counts == expected_counts
                and undo.ok
                and undo_restored,
                "counts": counts,
                "expected_counts": expected_counts,
                "topology_changed": after.revision > before.revision,
                "undo_restored": undo_restored,
            }
        )
    return cases, request_sequence


def _geometry_layer_cases(
    tab: object,
    app: object,
    controller: object,
    request_sequence: int,
) -> tuple[dict[str, object], int]:
    controller.select(faces_by_submesh={0: (0,)}, operation="replace")
    selection = controller.session_view().selection
    dispatches: list[dict[str, object]] = []
    dispatched, request_sequence = _dispatch_command(
        tab,
        app,
        controller,
        "copy",
        request_sequence,
        target_mode="face",
        local_selection=_selection_payload(selection),
    )
    dispatches.append(dispatched)
    copied = controller.geometry_layer_state()
    for _ in range(2):
        dispatched, request_sequence = _dispatch_command(
            tab, app, controller, "paste", request_sequence
        )
        dispatches.append(dispatched)
    pasted = controller.geometry_layer_state()
    editable = [item for item in pasted["layers"] if not bool(item.get("base"))]
    if len(editable) != 2:
        return {
            "ok": False,
            "stage": "paste",
            "dispatches": dispatches,
            "state": pasted,
        }, request_sequence
    first_id = str(editable[0]["layer_id"])
    second_id = str(editable[1]["layer_id"])
    editable_order_before = [str(item["layer_id"]) for item in editable]
    for command, fields in (
        ("layer_rename", {"layer_id": first_id, "name": "Diagnostic Layer"}),
        ("layer_visibility", {"layer_id": second_id, "visible": False}),
        ("layer_activate", {"layer_id": first_id}),
        ("layer_move", {"layer_id": first_id, "direction": 1}),
    ):
        dispatched, request_sequence = _dispatch_command(
            tab, app, controller, command, request_sequence, **fields
        )
        dispatches.append(dispatched)
    changed = controller.geometry_layer_state()
    changed_by_id = {str(item["layer_id"]): item for item in changed["layers"]}
    editable_order_after = [
        str(item["layer_id"])
        for item in changed["layers"]
        if not bool(item.get("base"))
    ]
    order_changed = editable_order_after == [second_id, first_id]
    dispatched, request_sequence = _dispatch_command(
        tab,
        app,
        controller,
        "layer_delete",
        request_sequence,
        layer_id=second_id,
    )
    dispatches.append(dispatched)
    deleted = controller.geometry_layer_state()
    layer_ids_after_delete = {str(item["layer_id"]) for item in deleted["layers"]}
    return {
        "ok": all(item["accepted"] and item["worker_idle"] for item in dispatches)
        and bool(copied.get("clipboard_ready"))
        and changed_by_id[first_id]["name"] == "Diagnostic Layer"
        and changed_by_id[second_id]["visible"] is False
        and changed["active_layer_id"] == first_id
        and order_changed
        and second_id not in layer_ids_after_delete,
        "dispatches": dispatches,
        "clipboard_ready": copied.get("clipboard_ready"),
        "pasted_layer_count": len(editable),
        "renamed": changed_by_id[first_id]["name"],
        "visibility_changed": changed_by_id[second_id]["visible"] is False,
        "active_layer_id": changed["active_layer_id"],
        "order_before": editable_order_before,
        "order_after": editable_order_after,
        "order_changed": order_changed,
        "deleted_layer_absent": second_id not in layer_ids_after_delete,
    }, request_sequence


def _embedded_part_cases() -> dict[str, object]:
    mesh = _build_two_part_synthetic_mesh()
    committed: list[object] = []

    def run_mutation(action: str) -> tuple[bool, int]:
        session = StaticReplacementMeshEditSession(
            session_id=f"headless-part-{action}"
        )
        session.open(deepcopy(mesh))
        state = SimpleNamespace(
            _mesh_edit_state=SimpleNamespace(replacement_mesh_for_mapping=mesh),
            self=SimpleNamespace(set_status_message=lambda *_args, **_kwargs: None),
            _delete_selected_source_parts=lambda *_args, **_kwargs: None,
        )
        callbacks = SimpleNamespace(
            _mesh_edit_record_snapshot=lambda: None,
            _mesh_editor_apply_static_replacement_edit=lambda _mesh, key, **params: session.apply(
                key, **params
            ),
            _mesh_editor_commit_action_bar_service_result=lambda result, **_kwargs: committed.append(
                result
            )
            or True,
        )
        actions = create_actions_callbacks(state, callbacks)
        try:
            applied = actions._mesh_editor_embedded_run_part_action(action, (0,))
            return bool(applied), session.view().submesh_count
        finally:
            session.close(force_without_saving=True)

    duplicated, duplicate_count = run_mutation("duplicate")
    deleted, delete_count = run_mutation("delete")

    class _Item:
        def __init__(self) -> None:
            self.state = 1

        def checkState(self, _column: int) -> int:
            return self.state

        def setCheckState(self, _column: int, value: int) -> None:
            self.state = int(value)

    items = {0: _Item(), 1: _Item()}
    visibility_actions = create_actions_callbacks(
        SimpleNamespace(
            source_items_by_index=items,
            Qt=SimpleNamespace(Checked=1, Unchecked=0),
            self=SimpleNamespace(set_status_message=lambda *_args, **_kwargs: None),
        ),
        SimpleNamespace(),
    )
    hidden = visibility_actions._mesh_editor_embedded_run_part_action(
        "toggle_visibility", (0, 1)
    )
    hidden_states = tuple(item.state for item in items.values())
    shown = visibility_actions._mesh_editor_embedded_run_part_action(
        "toggle_visibility", (0, 1)
    )
    shown_states = tuple(item.state for item in items.values())
    return {
        "ok": duplicated
        and duplicate_count == 3
        and deleted
        and delete_count == 1
        and hidden
        and shown
        and hidden_states == (0, 0)
        and shown_states == (1, 1)
        and len(committed) == 2,
        "duplicate_submesh_count": duplicate_count,
        "delete_submesh_count": delete_count,
        "hidden_states": hidden_states,
        "shown_states": shown_states,
        "committed_result_count": len(committed),
    }


def run_edit_mesh_command_diagnostics(
    tab: object,
    app: object,
    request_sequence: int,
) -> tuple[dict[str, object], int]:
    controller = tab.standalone_controller
    if controller is None:
        return {"ok": False, "reason": "standalone controller unavailable"}, request_sequence
    selection, request_sequence = _selection_command_cases(
        tab, app, controller, request_sequence
    )
    axis, history, request_sequence = _axis_nudge_cases(
        tab, app, controller, request_sequence
    )
    topology, request_sequence = _topology_cases(
        tab, app, controller, request_sequence
    )
    layers, request_sequence = _geometry_layer_cases(
        tab, app, controller, request_sequence
    )
    parts = _embedded_part_cases()
    sections = {
        "selection_commands": selection,
        "axis_nudges": axis,
        "history": history,
        "topology_commands": topology,
        "geometry_layers": layers,
        "embedded_part_commands": parts,
    }
    return {
        "ok": all(item["ok"] for item in selection)
        and all(item["ok"] for item in axis)
        and history["ok"] is True
        and all(item["ok"] for item in topology)
        and layers["ok"] is True
        and parts["ok"] is True,
        **sections,
    }, request_sequence


__all__ = ["run_edit_mesh_command_diagnostics"]
