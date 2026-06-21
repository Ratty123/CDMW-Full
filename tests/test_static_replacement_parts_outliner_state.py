from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_parts_outliner_state import (
    parts_outliner_action_role_value,
    parts_outliner_action_target_index,
    parts_outliner_cache_initial_state,
    parts_outliner_cache_matches,
    parts_outliner_cache_record_revision,
    parts_outliner_control_text,
    parts_outliner_copied_texture_tooltip_source_index,
    parts_outliner_drop_target_index,
    parts_outliner_geometry_text,
    parts_outliner_item_update_guard_initial_state,
    parts_outliner_revision,
    parts_outliner_role_menu_specs,
    parts_outliner_selection_row_state,
    parts_outliner_source_click_action,
    parts_outliner_source_drop_allowed,
    parts_outliner_source_indices,
    parts_outliner_source_label,
    parts_outliner_source_role_change_refresh_reason,
    parts_outliner_source_role_change_undo_label,
    parts_outliner_source_target_apply_state,
    parts_outliner_target_label,
    parts_outliner_target_menu_specs,
    parts_outliner_target_selection_view_payload,
    parts_outliner_unassigned_source_indices,
    parts_outliner_unassigned_target_label,
)


class _MappingEdit:
    def __init__(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class _Item:
    def __init__(
        self,
        kind: str,
        target_index: object = "",
        source_indices: object = (),
        parent: object | None = None,
    ) -> None:
        self._kind = kind
        self._target_index = target_index
        self._source_indices = source_indices
        self._parent = parent

    def data(self, _column: int, role: int) -> object:
        if role == 32:
            return self._kind
        if role == 33:
            return self._target_index
        if role == 34:
            return self._source_indices
        return None

    def parent(self) -> object | None:
        return self._parent


def test_parts_outliner_item_update_guard_initial_state_preserves_defaults() -> None:
    assert parts_outliner_item_update_guard_initial_state() == {"active": False, "refreshing": False}


def test_parts_outliner_revision_tracks_mesh_counts_mapping_and_source_sets() -> None:
    original = SimpleNamespace(submeshes=[object(), object()])
    replacement = SimpleNamespace(submeshes=[object(), object(), object()])

    revision = parts_outliner_revision(
        original_mesh=original,
        replacement_mesh=replacement,
        mapping_edits=((2, _MappingEdit("1, 0")),),
        preview_only_source_indices=(4, 1),
        independent_output_source_indices=(3,),
        copied_original_texture_intents_by_source={7: object(), 2: object()},
    )

    assert revision == (2, 3, ((2, "1, 0"),), (1, 4), (3,), (2, 7))


def test_parts_outliner_cache_matches_only_after_record_and_existing_items() -> None:
    state = parts_outliner_cache_initial_state()
    revision = ("rev",)

    assert not parts_outliner_cache_matches(state, revision, has_items=True)
    parts_outliner_cache_record_revision(state, revision)
    assert not parts_outliner_cache_matches(state, revision, has_items=False)
    assert parts_outliner_cache_matches(state, revision, has_items=True)


def test_parts_outliner_control_text_preserves_title_tooltip_and_headers() -> None:
    text = parts_outliner_control_text()

    assert text["title"] == "Parts Outliner"
    assert "replacement source parts feeding each target" in str(text["tooltip"])
    assert text["headers"] == ["Item", "Target", "Role", "DDS", "State", "Physics", "Geometry"]
    assert parts_outliner_unassigned_target_label() == "Preview-only / Unassigned"
    assert parts_outliner_source_role_change_undo_label() == "Change source role"
    assert parts_outliner_source_role_change_refresh_reason() == "source role change"


def test_parts_outliner_row_text_helpers_preserve_labels_and_geometry() -> None:
    part = SimpleNamespace(vertices=[1, 2, 3], faces=[1, 2])

    assert parts_outliner_target_label(3, " target material ", simplify_label=str.strip) == "Target 3: target material"
    assert parts_outliner_target_label("bad", "Target", simplify_label=lambda value: value) == "Target -1: Target"
    assert parts_outliner_source_label("Blade") == "  -> Blade"
    assert parts_outliner_geometry_text(part) == "3 vertices, 2 faces"
    assert parts_outliner_geometry_text(object()) == "0 vertices, 0 faces"


def test_parts_outliner_menu_specs_include_preview_target_and_roles() -> None:
    assert parts_outliner_target_menu_specs(("Target A", "Target B")) == (
        ("Preview-only / Unassigned", -1),
        ("Target A", 0),
        ("Target B", 1),
    )
    assert parts_outliner_role_menu_specs((("Auto", ""), ("Glow", "glow"), ("Blade", None))) == (
        ("Auto", ""),
        ("Glow", "glow"),
        ("Blade", ""),
    )


def test_parts_outliner_source_index_helpers_filter_assigned_and_marker_sources() -> None:
    mesh = SimpleNamespace(submeshes=("body", "marker", "cloth", "extra"))

    assert parts_outliner_source_indices((2, "bad", -1, 2, 0)) == (2, 0)
    assert parts_outliner_unassigned_source_indices(
        mesh,
        assigned_sources=(0, "bad"),
        is_marker_source=lambda source: source == "marker",
    ) == (2, 3)
    assert parts_outliner_unassigned_source_indices(
        None,
        assigned_sources=(0,),
        is_marker_source=lambda _source: False,
    ) == ()


def test_parts_outliner_copied_texture_tooltip_source_index_normalizes_source() -> None:
    copied = {2: object()}

    assert parts_outliner_copied_texture_tooltip_source_index("2", copied) == 2
    assert parts_outliner_copied_texture_tooltip_source_index(3, copied) is None
    assert parts_outliner_copied_texture_tooltip_source_index("bad", copied) is None


def test_parts_outliner_drop_target_index_reads_row_or_parent() -> None:
    target = _Item("target", 4)
    child = _Item("note", parent=target)

    assert parts_outliner_drop_target_index(_Item("unassigned_group"), user_role=32) == -1
    assert parts_outliner_drop_target_index(_Item("source", "5"), user_role=32) == 5
    assert parts_outliner_drop_target_index(child, user_role=32) == 4
    assert parts_outliner_drop_target_index(_Item("source", "bad"), user_role=32) is None
    assert parts_outliner_drop_target_index(None, user_role=32) is None


def test_parts_outliner_source_click_action_routes_source_columns() -> None:
    assert parts_outliner_source_click_action("source", 1) == "target"
    assert parts_outliner_source_click_action("source", 2) == "role"
    assert parts_outliner_source_click_action("source", 0) == ""
    assert parts_outliner_source_click_action("target", 1) == ""


def test_parts_outliner_selection_row_state_normalizes_item_payload() -> None:
    assert parts_outliner_selection_row_state(
        _Item("target", "5", (2, "bad", -1, 2, 4)),
        user_role=32,
    ) == {"row_kind": "target", "target_index": 5, "source_indices": (2, 4)}
    assert parts_outliner_selection_row_state(_Item("source", "bad", (1,)), user_role=32) == {
        "row_kind": "source",
        "target_index": -1,
        "source_indices": (1,),
    }
    assert parts_outliner_selection_row_state(None, user_role=32) is None


def test_parts_outliner_target_selection_view_payload_tracks_target_rows() -> None:
    assert parts_outliner_target_selection_view_payload(
        row_kind="target",
        target_index=3,
        source_indices=(1, 2),
    ) == {"kind": "target", "target_indices": (3,), "source_indices": (1, 2)}
    assert parts_outliner_target_selection_view_payload(
        row_kind="target",
        target_index=-1,
        source_indices=(),
    ) == {"kind": "none", "target_indices": (), "source_indices": ()}
    assert parts_outliner_target_selection_view_payload(
        row_kind="source",
        target_index=3,
        source_indices=(1,),
    ) is None


def test_parts_outliner_action_target_index_normalizes_menu_data() -> None:
    assert parts_outliner_action_target_index("4") == 4
    assert parts_outliner_action_target_index("bad") == -1
    assert parts_outliner_action_target_index(None, default=7) == 7
    assert parts_outliner_action_role_value("armor") == "armor"
    assert parts_outliner_action_role_value(None) == ""


def test_parts_outliner_source_target_apply_state_keeps_preview_only_target() -> None:
    preview_state = parts_outliner_source_target_apply_state(
        source_index="2",
        target_index="-1",
        source_count=4,
    )
    assert preview_state.available
    assert preview_state.source_index == 2
    assert preview_state.target_index == -1

    valid_state = parts_outliner_source_target_apply_state(
        source_index=1,
        target_index="3",
        source_count="4",
    )
    assert valid_state.available
    assert valid_state.source_index == 1
    assert valid_state.target_index == 3

    assert not parts_outliner_source_target_apply_state(
        source_index=4,
        target_index=0,
        source_count=4,
    ).available
    assert not parts_outliner_source_target_apply_state(
        source_index=1,
        target_index="bad",
        source_count=4,
    ).available


def test_parts_outliner_source_drop_allowed_requires_live_source_and_target() -> None:
    assert parts_outliner_source_drop_allowed(refreshing=False, source_index=2, target_index=-1)
    assert not parts_outliner_source_drop_allowed(refreshing=True, source_index=2, target_index=-1)
    assert not parts_outliner_source_drop_allowed(refreshing=False, source_index=-1, target_index=-1)
    assert not parts_outliner_source_drop_allowed(refreshing=False, source_index=2, target_index=None)
