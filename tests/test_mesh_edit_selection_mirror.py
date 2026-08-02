"""The Qt selection mirror must survive resident selection events.

`_mesh_edit_selection_changed` used to reset the whole mirror and merge back
only legacy-shaped vertex/face/edge candidate groups. The resident editor's
`selection_request` carries a `local_selection` snapshot instead -- a shape
the legacy readers cannot see -- so every Parts-list click and helper-side
selection event wiped the mirror: the part selection vanished ("selecting a
part cleared my selection") and brush tools appeared to lose the selection at
random. The handler now adopts the resident snapshot's four channels exactly,
keeps the legacy replace semantics for legacy group payloads, and leaves the
mirror alone for payloads that carry no selection at all (the legacy panels
echo `{}` after a clear their caller already performed).
"""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_mesh_edit_selection import (
    _mesh_edit_selection_changed,
    _resident_selection_snapshot,
)


class _Label:
    def __init__(self) -> None:
        self.value = ""

    def text(self) -> str:
        return self.value

    def setText(self, value: str) -> None:
        self.value = str(value)


class _Checkbox:
    def isChecked(self) -> bool:
        return True


class _FakeSelection:
    def __init__(self) -> None:
        self.vertices: dict[int, tuple[int, ...]] = {}

    def vertex_map(self) -> dict[int, tuple[int, ...]]:
        return {}

    def edge_map(self) -> dict[int, tuple[tuple[int, int], ...]]:
        return {}

    def face_map(self) -> dict[int, tuple[int, ...]]:
        return {}

    @property
    def source_indices(self) -> tuple[int, ...]:
        return ()


def _make_state() -> SimpleNamespace:
    state = SimpleNamespace()
    state.Mapping = Mapping
    state.MeshEditSelection = _FakeSelection
    state.mesh_edit_selected_vertices_by_submesh = {}
    state.mesh_edit_selected_edges_by_submesh = {}
    state.mesh_edit_selected_faces_by_submesh = {}
    state.mesh_edit_selected_source_indices = set()
    state.mesh_edit_status_label = _Label()
    state.mesh_edit_enabled_checkbox = _Checkbox()
    state.mesh_edit_revision = {"value": 3}
    state._mesh_edit_allowed_source_indices = lambda: (0, 1, 2)
    state._mesh_edit_tab_active = lambda: True
    state._mesh_edit_index_group_count_helper = lambda groups: sum(
        len(indices) for indices in groups.values()
    )
    state._mesh_edit_selection_status_text_helper = (
        lambda reason, vertices, faces, revision: f"{reason}|{vertices}|{faces}|{revision}"
    )
    state._mesh_edit_vertices_from_payload = lambda payload: {
        int(group["source_submesh_index"]): set(group["source_vertex_indices"])
        for group in payload.get("groups", ())
        if group.get("source_vertex_indices")
    }
    state._mesh_edit_faces_from_payload = lambda payload: {}
    state._mesh_edit_merge_vertex_groups = lambda target, source: [
        target.setdefault(key, set()).update(values) for key, values in source.items()
    ]
    state._mesh_edit_merge_face_groups = state._mesh_edit_merge_vertex_groups
    return state


def _make_callbacks(state: SimpleNamespace) -> SimpleNamespace:
    callbacks = SimpleNamespace()
    callbacks._mesh_edit_native_screen_selection_payload = lambda payload, fallback=None: (
        {"screen_brush": dict(payload["screen_brush"])} if "screen_brush" in payload else {}
    )
    callbacks._mesh_edit_apply_native_screen_selection = lambda payload, screen: True
    callbacks._mesh_edit_edges_from_payload = lambda payload: {}
    callbacks._mesh_edit_selected_source_vertex_count = lambda **_kwargs: 0
    callbacks._mesh_edit_can_edit_scope = lambda: (True, "ok")
    callbacks.refresh_calls = []
    callbacks._refresh_mesh_edit_controls = lambda: callbacks.refresh_calls.append(True)

    def _set_selection_state(selection: object) -> None:
        state.mesh_edit_selected_vertices_by_submesh.clear()
        state.mesh_edit_selected_edges_by_submesh.clear()
        state.mesh_edit_selected_faces_by_submesh.clear()
        state.mesh_edit_selected_source_indices.clear()

    callbacks._mesh_edit_set_selection_state = _set_selection_state
    return callbacks


def _resident_payload(**overrides: object) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "vertices_by_submesh": {"0": [1, 2, 3]},
        "faces_by_submesh": {"1": [4]},
        "edges_by_submesh": {"0": [[5, 6], [8, 7]]},
        "source_indices": [1, 2, 9],
        "target_mode": "face",
    }
    snapshot.update(overrides)
    return {
        "event": "selection_request",
        "operation": "replace",
        "target_mode": "face",
        "local_selection": snapshot,
    }


def test_the_resident_snapshot_adopts_all_four_channels() -> None:
    state = _make_state()
    callbacks = _make_callbacks(state)

    _mesh_edit_selection_changed(state, callbacks, _resident_payload())

    assert state.mesh_edit_selected_vertices_by_submesh == {0: {1, 2, 3}}
    assert state.mesh_edit_selected_faces_by_submesh == {1: {4}}
    assert state.mesh_edit_selected_edges_by_submesh == {0: {(5, 6), (7, 8)}}
    # Source 9 is not in the allowed set and must be filtered out.
    assert state.mesh_edit_selected_source_indices == {1, 2}
    assert callbacks.refresh_calls


def test_a_part_click_keeps_the_geometry_selection_it_carries() -> None:
    state = _make_state()
    callbacks = _make_callbacks(state)
    state.mesh_edit_selected_vertices_by_submesh.update({0: {1, 2, 3}})

    _mesh_edit_selection_changed(state, callbacks, _resident_payload(source_indices=[2]))

    assert state.mesh_edit_selected_vertices_by_submesh == {0: {1, 2, 3}}
    assert state.mesh_edit_selected_source_indices == {2}


def test_an_empty_resident_snapshot_still_means_clear() -> None:
    state = _make_state()
    callbacks = _make_callbacks(state)
    state.mesh_edit_selected_vertices_by_submesh.update({0: {1}})
    state.mesh_edit_selected_source_indices.add(1)

    _mesh_edit_selection_changed(
        state,
        callbacks,
        _resident_payload(
            vertices_by_submesh={},
            faces_by_submesh={},
            edges_by_submesh={},
            source_indices=[],
        ),
    )

    assert not state.mesh_edit_selected_vertices_by_submesh
    assert not state.mesh_edit_selected_source_indices


def test_a_payload_with_no_selection_data_wipes_nothing() -> None:
    state = _make_state()
    callbacks = _make_callbacks(state)
    state.mesh_edit_selected_vertices_by_submesh.update({0: {1, 2}})
    state.mesh_edit_selected_source_indices.add(1)

    _mesh_edit_selection_changed(state, callbacks, {})

    assert state.mesh_edit_selected_vertices_by_submesh == {0: {1, 2}}
    assert state.mesh_edit_selected_source_indices == {1}


def test_legacy_candidate_groups_still_replace_the_selection() -> None:
    state = _make_state()
    callbacks = _make_callbacks(state)
    state.mesh_edit_selected_source_indices.add(1)

    _mesh_edit_selection_changed(
        state,
        callbacks,
        {"groups": [{"source_submesh_index": 2, "source_vertex_indices": [7, 8]}]},
    )

    assert state.mesh_edit_selected_vertices_by_submesh == {2: {7, 8}}
    # Legacy events describe the whole new selection, so the old part
    # selection is deliberately gone.
    assert not state.mesh_edit_selected_source_indices


def test_snapshot_parser_rejects_payloads_without_a_snapshot() -> None:
    assert _resident_selection_snapshot({}) is None
    assert _resident_selection_snapshot(None) is None
    assert _resident_selection_snapshot({"local_selection": "nope"}) is None


def test_a_helper_screen_selection_is_left_to_the_tab_authority() -> None:
    """The tab's protocol handler is the single native authority for screen
    selections raised by the resident editor: it applies the select, answers
    the pending request, and commits back through the builder. Applying here
    too ran every select twice -- Toggle self-cancelled, and every
    brush-select dab paid double native cost.
    """
    state = _make_state()
    callbacks = _make_callbacks(state)
    applied: list[object] = []
    callbacks._mesh_edit_apply_native_screen_selection = (
        lambda payload, screen: applied.append(payload) or True
    )

    for event in ("select_request", "selection_request"):
        _mesh_edit_selection_changed(
            state,
            callbacks,
            {"event": event, "screen_brush": {"x": 1, "y": 2}, "operation": "toggle"},
        )

    assert not applied
    assert not callbacks.refresh_calls


def test_a_legacy_panel_screen_selection_keeps_its_native_route() -> None:
    """The legacy preview panels' screen payloads carry no protocol event and
    have no other native route; this handler stays their authority.
    """
    state = _make_state()
    callbacks = _make_callbacks(state)
    applied: list[object] = []
    callbacks._mesh_edit_apply_native_screen_selection = (
        lambda payload, screen: applied.append(payload) or True
    )

    _mesh_edit_selection_changed(state, callbacks, {"screen_brush": {"x": 1, "y": 2}})

    assert applied
    assert callbacks.refresh_calls
