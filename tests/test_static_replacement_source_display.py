from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_mapping import (
    mapping_edit_committed_text,
    mapping_edit_indices,
    mapping_edit_valid_source_indices,
    mapping_indices_for_source_target,
    mapping_indices_without_source,
    mapping_source_indices_text,
    mapping_source_target_route_state,
    mapping_target_index_for_edit,
    mapping_text_has_indices,
    mapping_text_valid_source_indices,
    validate_mapping_text_source_indices,
)
from cdmw.ui.archive_browser.static_replacement_source_assignment_state import (
    source_assigned_target_indices,
    source_assignment_index,
    source_assignment_row_state,
    source_assignment_state_tooltip,
    source_assignment_targets_tooltip,
)
from cdmw.ui.archive_browser.static_replacement_source_display import (
    current_source_part_adjustments,
    disabled_source_part_indices,
    enabled_renderable_source_indices,
    format_index_list,
    invalidate_source_display_cache,
    mapping_indices_with_appended_source,
    mapping_preserve_split_group_count,
    mapping_vertex_limit_status_line,
    mapping_vertex_limit_issues,
    mapped_source_vertex_counts,
    mapped_target_vertex_count,
    nonnegative_indices,
    output_impact_counts,
    removed_target_dds_cell_text,
    remap_selected_source_index,
    remap_source_index_collection,
    remap_source_index_dict,
    routing_effect_lines,
    selected_source_summary,
    source_display_cache_revision_initial_state,
    source_display_duplicate_counts,
    source_display_name,
    source_indices_for_material_name,
    source_indices_for_route_parts,
    source_index_is_enabled_renderable,
    source_index_help_text,
    source_material_part_summary,
    source_outliner_dds_text,
    source_outliner_geometry,
    source_outliner_label,
    source_outliner_state,
    source_indices_for_target_name,
    source_renderable_indices,
    source_role_label,
    source_role_override_value,
    source_target_summary,
    source_tree_status_text,
    target_contract_source_indices,
    target_display_name,
    target_index_for_name,
    target_outliner_state,
    unique_mapping_indices,
)
from cdmw.ui.archive_browser.static_replacement_display_labels import (
    source_fallback_label,
    source_group_label_or_fallback,
    source_part_display_label,
    target_fallback_name,
    target_submesh_display_name,
)
from cdmw.ui.archive_browser.static_replacement_selection_view_state import (
    added_part_texture_highlight_state,
    d3d11_source_selection_index,
    material_plan_highlight_state,
    mesh_replacement_selection_view_initial_model,
    original_selection_index,
    original_selection_state,
    part_selection_clear_scope_state,
    part_selection_clear_state,
    part_selection_state_active,
    parts_outliner_target_selection_state,
    selection_filter_refresh_needed,
    selection_highlight_sets_state,
    selection_view_update_kwargs,
    source_selection_highlight_state,
    source_selection_state,
    source_selection_view_payload,
    single_selection_highlight_indices,
    single_selection_index_initial_state,
    target_mapping_selection_view_payload,
    target_selection_highlight_state,
    target_selection_index,
    target_selection_state,
    target_selection_view_payload,
    target_source_indices,
    texture_row_selection_highlight_state,
    unique_nonnegative_indices,
    update_mesh_replacement_selection_view_model,
)
from cdmw.ui.archive_browser.static_replacement_selection_route_state import (
    d3d11_source_part_selection_route,
    original_selection_route_state,
    source_selection_route_state,
    target_selection_route_state,
)


class _MappingEdit:
    def __init__(self, text: str, committed: str = "") -> None:
        self._text = text
        self._committed = committed

    def property(self, name: str) -> str:
        return self._committed if name == "committed_mapping_text" else ""

    def text(self) -> str:
        return self._text


def test_mapping_edit_indices_prefers_committed_text_and_normalizes_unique_values() -> None:
    assert mapping_edit_committed_text(_MappingEdit("4, 5", "1; 2 2 bad -1")) == "1; 2 2 bad -1"
    assert mapping_edit_committed_text(_MappingEdit("4, 5 4")) == "4, 5 4"
    assert mapping_edit_indices(_MappingEdit("4, 5", "1; 2 2 bad -1")) == (1, 2, -1)
    assert mapping_edit_indices(_MappingEdit("4, 5 4")) == (4, 5)
    assert mapping_edit_indices("7, nope, 8") == (7, 8)
    assert mapping_source_indices_text((1, "2", -1)) == "1, 2, -1"


def test_mapping_valid_source_indices_filter_normalized_mapping_values() -> None:
    assert mapping_edit_valid_source_indices(_MappingEdit("4, 5", "1; 2 2 bad -1"), {1, 3}) == (1,)
    assert mapping_edit_valid_source_indices(_MappingEdit("4, 5 4"), ("4", "bad")) == (4,)
    assert mapping_text_valid_source_indices("7, nope, 8; 7 -1", {8, 7}) == (7, 8)
    assert mapping_text_has_indices("bad, 3")
    assert not mapping_text_has_indices("bad")


def test_mapping_indices_for_source_target_removes_then_optionally_adds_source() -> None:
    assert mapping_indices_without_source((1, 2, 1, 3), 1) == (2, 3)
    assert mapping_indices_for_source_target((1, 2, 1, 3), 1, target_matches=False) == (2, 3)
    assert mapping_indices_for_source_target((1, 2), 3, target_matches=True) == (1, 2, 3)
    assert mapping_indices_for_source_target((1, 2, 3), 3, target_matches=True) == (1, 2, 3)


def test_mapping_target_index_for_edit_uses_identity_match() -> None:
    edit_a = _MappingEdit("1")
    edit_b = _MappingEdit("2")

    assert mapping_target_index_for_edit(((5, edit_a), (7, edit_b)), edit_b) == 7
    assert mapping_target_index_for_edit(((5, edit_a),), _MappingEdit("1")) == -1


def test_mapping_source_target_route_state_identifies_preview_only_target() -> None:
    assert mapping_source_target_route_state(-1) == {
        "preview_only": True,
        "defer_preview": True,
        "selected_target_index": -1,
        "pending_reason": "source unassigned",
    }
    assert mapping_source_target_route_state(3) == {
        "preview_only": False,
        "defer_preview": False,
        "selected_target_index": 3,
        "pending_reason": "",
    }


def test_validate_mapping_text_source_indices_reports_first_invalid_value() -> None:
    valid = validate_mapping_text_source_indices("1, 2 2", {1, 2})
    assert valid.source_indices == (1, 2)
    assert valid.invalid_token == ""
    assert valid.missing_source_index is None

    invalid = validate_mapping_text_source_indices("1 nope 2", {1, 2})
    assert invalid.source_indices == (1,)
    assert invalid.invalid_token == "nope"
    assert invalid.missing_source_index is None

    missing = validate_mapping_text_source_indices("1 9 2", {1, 2})
    assert missing.source_indices == (1,)
    assert missing.invalid_token == ""
    assert missing.missing_source_index == 9


def test_source_role_override_prefers_explicit_override_then_adjustment() -> None:
    adjustments = {2: SimpleNamespace(material_role="hair")}

    assert source_role_override_value(2, {2: "body"}, adjustments) == "body"
    assert source_role_override_value(2, {}, adjustments) == "hair"
    assert source_role_override_value(3, {}, adjustments) == ""


def test_source_role_label_uses_override_then_inferred_mesh_label() -> None:
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(name="headShape", material="skin")])

    assert source_role_label(0, mesh, {0: "face"}, {}, role_hint=lambda _label: "unused") == "face"
    assert source_role_label(0, mesh, {}, {}, role_hint=lambda label: f"hint:{label}") == "hint:headShape skin"
    assert source_role_label(5, mesh, {}, {}, role_hint=lambda _label: "unused") == "unknown"
    assert source_role_label(0, None, {}, {}, role_hint=lambda _label: "unused") == "unknown"


def test_source_index_is_enabled_renderable_checks_mesh_bounds_marker_and_adjustment() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(marker=False),
            SimpleNamespace(marker=True),
            SimpleNamespace(marker=False),
        ]
    )
    kwargs = {"is_marker_source": lambda source: bool(getattr(source, "marker", False))}

    assert source_index_is_enabled_renderable(0, mesh, {}, **kwargs) is True
    assert source_index_is_enabled_renderable(1, mesh, {}, **kwargs) is False
    assert source_index_is_enabled_renderable(2, mesh, {2: SimpleNamespace(enabled=False)}, **kwargs) is False
    assert source_index_is_enabled_renderable(5, mesh, {}, **kwargs) is False
    assert source_index_is_enabled_renderable(0, None, {}, **kwargs) is False


def test_enabled_renderable_source_indices_coerces_and_filters() -> None:
    assert enabled_renderable_source_indices(
        (0, "1", "bad", -1, 2),
        source_index_is_enabled_renderable=lambda index: index in {0, 2},
    ) == (0, 2)


def test_source_renderable_indices_filters_markers_excluded_and_disabled_sources() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(marker=False),
            SimpleNamespace(marker=True),
            SimpleNamespace(marker=False),
            SimpleNamespace(marker=False),
        ]
    )
    adjustments = {2: SimpleNamespace(enabled=False)}

    assert source_renderable_indices(
        mesh,
        adjustments,
        is_marker_source=lambda source: bool(getattr(source, "marker", False)),
        excluded_source_indices={3},
    ) == (0,)
    assert source_renderable_indices(
        mesh,
        adjustments,
        is_marker_source=lambda source: bool(getattr(source, "marker", False)),
        require_enabled=False,
    ) == (0, 2, 3)


def test_source_material_part_summary_matches_material_and_skips_markers() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(material="Skin", name="Body", texture="body_d"),
            SimpleNamespace(material="Cloth", name="Cape", texture="cape_d"),
            SimpleNamespace(material="", name="Marker", texture="", marker=True),
        ]
    )
    kwargs = {"is_marker_source": lambda source: bool(getattr(source, "marker", False))}

    assert source_material_part_summary("skin", mesh, texture_set_count=2, **kwargs) == "0: Skin"
    assert (
        source_material_part_summary("missing", mesh, texture_set_count=1, **kwargs)
        == "0: Skin, 1: Cloth"
    )
    assert (
        source_material_part_summary("missing", mesh, texture_set_count=2, **kwargs)
        == "No matching imported part"
    )


def test_source_indices_for_material_name_matches_texture_and_single_texture_fallback() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(material="Skin", name="Body", texture="body_d"),
            SimpleNamespace(material="Cloth", name="Cape", texture="cape_d"),
            SimpleNamespace(material="", name="Marker", texture="", marker=True),
        ]
    )
    kwargs = {"is_marker_source": lambda source: bool(getattr(source, "marker", False))}

    assert source_indices_for_material_name("body", mesh, texture_set_count=2, **kwargs) == (0,)
    assert source_indices_for_material_name("missing", mesh, texture_set_count=1, **kwargs) == (0, 1)
    assert source_indices_for_material_name("", mesh, texture_set_count=1, **kwargs) == ()


def test_source_indices_for_route_parts_matches_display_labels_and_falls_back() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(material="Skin", name="Body", texture="body_d"),
            SimpleNamespace(material="Cloth", name="Cape", texture="cape_d"),
            SimpleNamespace(material="", name="Marker", texture="", marker=True),
        ]
    )
    kwargs = {"is_marker_source": lambda source: bool(getattr(source, "marker", False))}

    assert (
        source_indices_for_route_parts(
            ("1: Cape",),
            mesh,
            source_display_name=lambda index: ("0: Body", "1: Cape", "2: Marker")[index],
            source_indices_for_material_name=lambda _name: (),
            **kwargs,
        )
        == (1,)
    )
    assert (
        source_indices_for_route_parts(
            (),
            mesh,
            source_material_name="body",
            source_display_name=lambda index: ("0: Body", "1: Cape", "2: Marker")[index],
            source_indices_for_material_name=lambda name: (0,) if name == "body" else (),
            **kwargs,
        )
        == (0,)
    )


def test_mapped_source_vertex_counts_filters_marker_disabled_and_invalid_sources() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(marker=False, vertices=(1, 2)),
            SimpleNamespace(marker=True, vertices=(1, 2, 3)),
            SimpleNamespace(marker=False, vertices=(1, 2, 3, 4)),
            SimpleNamespace(marker=False, vertices=()),
        ]
    )
    adjustments = {2: SimpleNamespace(enabled=False)}

    counts = mapped_source_vertex_counts(
        (0, 1, 2, 3, 9),
        mesh,
        adjustments,
        default_adjustment=lambda _index: SimpleNamespace(enabled=True),
        is_marker_source=lambda source: bool(getattr(source, "marker", False)),
    )

    assert counts == ((0, 2), (3, 0))
    assert mapped_target_vertex_count(
        (0, 1, 2, 3, 9),
        mesh,
        adjustments,
        default_adjustment=lambda _index: SimpleNamespace(enabled=True),
        is_marker_source=lambda source: bool(getattr(source, "marker", False)),
    ) == 2
    assert mapped_source_vertex_counts(
        (0,),
        None,
        {},
        default_adjustment=lambda _index: SimpleNamespace(enabled=True),
        is_marker_source=lambda _source: False,
    ) == ()


def test_mapping_preserve_split_group_count_splits_under_limit_and_reports_oversize() -> None:
    assert mapping_preserve_split_group_count(
        ((0, 4), (1, 4), (2, 2)),
        7,
        source_display_name=lambda index: f"source {index}",
    ) == (2, None)
    assert mapping_preserve_split_group_count(
        ((3, 8),),
        7,
        source_display_name=lambda index: f"source {index}",
    ) == (0, "source 3 has 8 vertices (limit 7).")
    assert mapping_preserve_split_group_count(
        (),
        7,
        source_display_name=lambda index: f"source {index}",
    ) == (1, None)


def test_mapping_vertex_limit_issues_reports_oversize_and_non_pac_split_needs() -> None:
    mappings = [
        SimpleNamespace(target_submesh_index=0, source_submesh_indices=(0,)),
        SimpleNamespace(target_submesh_index=1, source_submesh_indices=(1,)),
    ]

    issues = mapping_vertex_limit_issues(
        mappings,
        original_format="obj",
        vertex_limit=7,
        target_display_name=lambda index: f"target {index}",
        mapped_target_vertex_count=lambda indices: 9 if tuple(indices) == (0,) else 8,
        preserve_split_group_count=lambda indices: (0, "source 0 has 9 vertices (limit 7).")
        if tuple(indices) == (0,)
        else (2, None),
    )

    assert issues == (
        "source 0 has 9 vertices (limit 7).",
        "target 1 needs 2 draw sections for 8 vertices, but only PAC draw-section cloning is supported.",
    )
    assert mapping_vertex_limit_issues(
        mappings[1:],
        original_format="pac",
        vertex_limit=7,
        target_display_name=lambda index: f"target {index}",
        mapped_target_vertex_count=lambda _indices: 8,
        preserve_split_group_count=lambda _indices: (2, None),
    ) == ()


def test_mapping_vertex_limit_status_line_reports_dense_pac_or_generic_limit() -> None:
    assert mapping_vertex_limit_status_line(
        7,
        split_count=1,
        split_error=None,
        original_format="obj",
        vertex_limit=7,
    ) is None
    assert mapping_vertex_limit_status_line(
        9,
        split_count=2,
        split_error=None,
        original_format="pac",
        vertex_limit=7,
    ) == "Dense output: 9 vertices will export as 2 PAC draw sections."
    assert mapping_vertex_limit_status_line(
        9,
        split_count=2,
        split_error="source too big",
        original_format="obj",
        vertex_limit=7,
    ) == "Vertex limit: 9/7 vertices. Split, decimate, or map fewer sources into this target before continuing."


def test_routing_effect_lines_describes_selection_remove_replace_and_merge_risk() -> None:
    kwargs = {
        "target_display_name": lambda index: f"target {index}",
        "source_display_name": lambda index: f"source {index}",
        "source_material_labels": lambda indices: ("skin", "cloth") if len(tuple(indices)) > 1 else ("skin",),
    }

    assert routing_effect_lines(-1, (), selection_ok=True, selection_summary="", **kwargs)[0].startswith(
        "Effect: select a target"
    )
    assert routing_effect_lines(0, (), selection_ok=False, selection_summary="bad index", **kwargs) == (
        "Effect: bad index",
        "Fix path: type valid source row numbers from Replacement sources, separated by commas.",
    )
    assert routing_effect_lines(0, (), selection_ok=True, selection_summary="", **kwargs)[0] == (
        "Effect: target 0 will be removed from the output geometry."
    )
    assert routing_effect_lines(0, (2,), selection_ok=True, selection_summary="", **kwargs)[0] == (
        "Effect: target 0 will be replaced by source 2."
    )
    assert "different materials (skin, cloth)" in routing_effect_lines(
        0,
        (1, 2),
        selection_ok=True,
        selection_summary="",
        **kwargs,
    )[1]


def test_source_display_name_uses_override_and_cache() -> None:
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(name="body", material="skin", vertices=(), faces=())])
    label_cache: dict[int, str] = {}
    duplicate_cache: dict[str, int] = {}

    assert source_display_name(0, mesh, {0: "custom"}, label_cache, duplicate_cache) == "0: custom"
    assert label_cache == {0: "0: custom"}
    assert source_display_name(0, mesh, {0: "changed"}, label_cache, duplicate_cache) == "0: custom"


def test_source_display_name_marks_duplicate_materials_with_counts() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="body_a", material="skin", vertices=(1, 2), faces=(1,)),
            SimpleNamespace(name="body_b", material="skin", vertices=(1, 2, 3), faces=(1, 2)),
            SimpleNamespace(name="hair", material="", vertices=(), faces=()),
        ]
    )
    label_cache: dict[int, str] = {}
    duplicate_cache: dict[str, int] = {}

    assert source_display_name(0, mesh, {}, label_cache, duplicate_cache) == "0: skin (2v/1f)"
    assert source_display_name(1, mesh, {}, label_cache, duplicate_cache) == "1: skin (3v/2f)"
    assert source_display_name(2, mesh, {}, label_cache, duplicate_cache) == "2: hair"
    assert duplicate_cache == {"skin": 2, "hair": 1}


def test_source_display_name_handles_missing_and_invalid_mesh() -> None:
    mesh = SimpleNamespace(submeshes=[])

    assert source_display_name(4, None, {}, {}, {}) == "source 4"
    assert source_display_name(4, mesh, {}, {}, {}) == "4: invalid"


def test_source_and_target_fallback_labels_preserve_dialog_copy() -> None:
    source = SimpleNamespace(name="sourceName", material="")
    target = SimpleNamespace(name="", material="targetMat")

    assert source_fallback_label(7) == "source 7"
    assert target_fallback_name(8) == "target 8"
    assert source_part_display_label(7, source, {7: "override"}) == "override"
    assert source_part_display_label(7, source, {}) == "sourceName"
    assert source_part_display_label(7, SimpleNamespace(name="", material=""), {}) == "source 7"
    assert source_group_label_or_fallback(7, "Skin") == "Skin"
    assert source_group_label_or_fallback(7, "") == "source 7"
    assert target_submesh_display_name(8, target) == "targetMat"
    assert target_submesh_display_name(8, SimpleNamespace(name="targetName", material="")) == "targetName"
    assert target_submesh_display_name(8, SimpleNamespace(name="", material="")) == "target 8"


def test_source_display_duplicate_counts_normalizes_labels() -> None:
    submeshes = (
        SimpleNamespace(name="", material="Skin"),
        SimpleNamespace(name="skin", material=" skin "),
        SimpleNamespace(name="hair", material=""),
    )

    assert source_display_duplicate_counts(submeshes) == {"skin": 2, "hair": 1}


def test_selected_source_summary_reports_empty_invalid_marker_and_selected_sources() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(marker=False),
            SimpleNamespace(marker=False),
            SimpleNamespace(marker=True),
        ]
    )

    kwargs = {
        "display_name": lambda index: f"{index}: src",
        "is_marker_source": lambda source: bool(getattr(source, "marker", False)),
    }

    assert selected_source_summary("", mesh, **kwargs) == (
        "Empty target: this original draw section will not emit replacement geometry.",
        True,
    )
    assert selected_source_summary("0, 1", mesh, **kwargs) == ("Selected: 0: src + 1: src", True)
    assert selected_source_summary("bad", mesh, **kwargs) == ("Invalid source index: bad", False)
    assert selected_source_summary("4", mesh, **kwargs) == ("Invalid source index: 4", False)
    assert selected_source_summary("2", mesh, **kwargs) == (
        "Source 2 is an anchor marker, not render geometry.",
        False,
    )
    assert selected_source_summary("0", None, **kwargs) == ("No replacement mesh loaded.", False)


def test_source_index_help_text_lists_non_marker_sources_and_truncates() -> None:
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(marker=index == 1) for index in range(14)])

    text = source_index_help_text(
        mesh,
        display_name=lambda index: f"{index}: src",
        is_marker_source=lambda source: bool(getattr(source, "marker", False)),
    )

    listed = text.rsplit("Available sources: ", 1)[1]

    assert "0: src; 2: src" in listed
    assert not any(part.strip() == "1: src" for part in listed.removesuffix("; ...").split(";"))
    assert text.endswith("; ...")
    assert source_index_help_text(None, display_name=lambda _index: "", is_marker_source=lambda _source: False) == (
        "Replacement parts used are the row numbers in Replacement sources."
    )


def test_target_display_name_handles_material_name_fallback_and_invalid() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="targetName", material="targetMat"),
            SimpleNamespace(name="targetNameOnly", material=""),
        ]
    )

    assert target_display_name(0, mesh) == "0: targetMat"
    assert target_display_name(1, mesh) == "1: targetNameOnly"
    assert target_display_name(2, mesh) == "2: invalid"
    assert target_display_name(0, None) == "0: invalid"


def test_target_index_for_name_matches_material_then_name_case_insensitive() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="targetName", material="targetMat"),
            SimpleNamespace(name="targetNameOnly", material=""),
        ]
    )

    assert target_index_for_name(" TARGETMAT ", mesh) == 0
    assert target_index_for_name("targetnameonly", mesh) == 1
    assert target_index_for_name("", mesh) == -1
    assert target_index_for_name("missing", mesh) == -1
    assert target_index_for_name("targetMat", None) == -1


def test_target_source_indices_uses_mapping_edit_parser_or_empty_tuple() -> None:
    edits = {0: "1,2", 2: ""}

    assert target_source_indices(
        0,
        edits,
        parse_mapping_edit=lambda edit: tuple(int(part) for part in str(edit).split(",") if part),
    ) == (1, 2)
    assert target_source_indices(
        1,
        edits,
        parse_mapping_edit=lambda _edit: (9,),
    ) == ()


def test_target_contract_source_indices_prefers_current_edit_text_and_preserves_duplicates() -> None:
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(name="targetName", material="targetMat")])
    edit = SimpleNamespace(text=lambda: "1, bad; 2 2")

    assert target_contract_source_indices(
        "targetmat",
        mesh,
        {0: edit},
        {0: SimpleNamespace(source_submesh_indices=(5,))},
    ) == (1, 2, 2)


def test_target_contract_source_indices_uses_mapping_fallback_and_bounds() -> None:
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(name="targetName", material="")])

    assert target_contract_source_indices(
        "targetName",
        mesh,
        {},
        {0: SimpleNamespace(source_submesh_indices=(-1, 0, 3))},
    ) == (0, 3)
    assert target_contract_source_indices("missing", mesh, {}, {}) == ()


def test_target_outliner_state_reports_invalid_removed_mapped_merged_and_physics() -> None:
    original_mesh = SimpleNamespace(submeshes=[SimpleNamespace(name="target", material="")])
    replacement_mesh = SimpleNamespace(submeshes=[SimpleNamespace(), SimpleNamespace(), SimpleNamespace()])

    def enabled(indices) -> tuple[int, ...]:
        return tuple(index for index in indices if index != 2)

    kwargs = {
        "original_mesh": original_mesh,
        "replacement_mesh": replacement_mesh,
        "enabled_renderable_source_indices": enabled,
        "target_physics_status_text": lambda _label, target: str(getattr(target, "physics", "-")),
    }

    assert target_outliner_state(-1, (0,), **kwargs) == ("Invalid", "#f85149")
    assert target_outliner_state(0, (), **kwargs) == ("Removed", "#fb923c")
    assert target_outliner_state(0, (4,), **kwargs) == ("Invalid", "#f85149")
    assert target_outliner_state(0, (2,), **kwargs) == ("Removed", "#fb923c")
    assert target_outliner_state(0, (0,), **kwargs) == ("Mapped", "#3fb950")
    assert target_outliner_state(0, (0, 1), **kwargs) == ("Merged", "#d29922")

    original_mesh.submeshes[0].physics = "Review"
    assert target_outliner_state(0, (0,), **kwargs) == ("Physics", "#f2cc60")
    assert target_outliner_state(0, (0,), modify_original_clone_mode=True, **kwargs) == ("Mapped", "#3fb950")


def test_source_assignment_helpers_parse_mapping_edits() -> None:
    mapping_edits = [(0, "1, 2"), (3, "2"), (5, "-1")]

    def parse(edit: object) -> tuple[int, ...]:
        return tuple(int(part.strip()) for part in str(edit).split(",") if part.strip())

    assert source_assigned_target_indices(2, mapping_edits, parse_mapping_edit=parse) == (0, 3)
    assert source_assigned_target_indices(4, mapping_edits, parse_mapping_edit=parse) == ()
    assert source_assigned_target_indices("bad", mapping_edits, parse_mapping_edit=parse) == ()
    assert source_assignment_index(mapping_edits, parse_mapping_edit=parse) == {1: [0], 2: [0, 3]}


def test_source_assignment_tooltips_preserve_assignment_copy() -> None:
    assert source_assignment_targets_tooltip("0: target") == "0: target"
    assert source_assignment_targets_tooltip("") == "Not assigned to an original target."
    assert source_assignment_state_tooltip("Assigned") == "This replacement source feeds at least one original target."
    assert "visible for review" in source_assignment_state_tooltip("Preview-only")
    assert "excluded from output" in source_assignment_state_tooltip("Disabled")
    assert source_assignment_state_tooltip("Custom") == "Custom"


def test_source_assignment_row_state_formats_columns_colors_and_tooltips() -> None:
    assigned = source_assignment_row_state(
        2,
        (0, 3),
        role_text="body",
        assigned_targets_text="target 0, target 3",
        source_state="Assigned",
        status_text="Assigned | Route DDS",
        status_color="#d29922",
    )

    assert assigned.source_index == 2
    assert assigned.role_text == "body"
    assert assigned.assigned_targets_text == "target 0, target 3"
    assert assigned.assigned_targets_color == "#cbd5e1"
    assert assigned.status_text == "Assigned | Route DDS"
    assert assigned.status_color == "#d29922"
    assert assigned.target_tooltip == "target 0, target 3"
    assert assigned.status_tooltip == "This replacement source feeds at least one original target."
    assert assigned.assigned_target_indices == (0, 3)

    unassigned = source_assignment_row_state(
        "bad",
        (),
        role_text="unknown",
        assigned_targets_text="",
        source_state="Unassigned",
        status_text="Unassigned",
        status_color="#8b949e",
        copied_texture_tooltip="Copied DDS payload",
    )

    assert unassigned.source_index == -1
    assert unassigned.assigned_targets_text == "-"
    assert unassigned.assigned_targets_color == "#8b949e"
    assert unassigned.target_tooltip == "Not assigned to an original target."
    assert unassigned.status_tooltip == "Copied DDS payload"


def test_source_outliner_state_prioritizes_disabled_assigned_preview_independent() -> None:
    disabled = {0: SimpleNamespace(enabled=False)}
    assigned = lambda index: (4,) if index == 1 else ()

    assert source_outliner_state(
        0,
        (),
        source_part_adjustments=disabled,
        preview_only_source_indices=(),
        independent_output_source_indices=(),
        assigned_target_indices=assigned,
    ) == ("Disabled", "#fb923c")
    assert source_outliner_state(
        1,
        (),
        source_part_adjustments={},
        preview_only_source_indices=(),
        independent_output_source_indices=(),
        assigned_target_indices=assigned,
    ) == ("Assigned", "#3fb950")
    assert source_outliner_state(
        2,
        (),
        source_part_adjustments={},
        preview_only_source_indices={2},
        independent_output_source_indices=(),
        assigned_target_indices=assigned,
    ) == ("Preview-only", "#8b949e")
    assert source_outliner_state(
        3,
        (),
        source_part_adjustments={},
        preview_only_source_indices=(),
        independent_output_source_indices={3},
        assigned_target_indices=assigned,
    ) == ("Independent", "#79c0ff")
    assert source_outliner_state(
        4,
        (),
        source_part_adjustments={},
        preview_only_source_indices=(),
        independent_output_source_indices=(),
        assigned_target_indices=assigned,
    ) == ("Unassigned", "#d29922")


def test_source_outliner_label_prefers_override_then_material_and_handles_invalid() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="srcName", material="srcMat"),
            SimpleNamespace(name="nameOnly", material=""),
        ]
    )

    simplify = lambda text: f"simple:{text}"

    assert source_outliner_label(0, mesh, {0: "override"}, simplify_label=simplify) == "Source 0: simple:override"
    assert source_outliner_label(0, mesh, {}, simplify_label=simplify) == "Source 0: simple:srcMat"
    assert source_outliner_label(1, mesh, {}, simplify_label=simplify) == "Source 1: simple:nameOnly"
    assert source_outliner_label(2, mesh, {}, simplify_label=simplify) == "2: source"
    assert source_outliner_label(0, None, {}, simplify_label=simplify) == "0: source"


def test_source_outliner_geometry_formats_counts_and_invalid_rows() -> None:
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(vertices=range(1200), faces=(1, 2))])

    assert source_outliner_geometry(0, mesh) == "1,200 vertices, 2 faces"
    assert source_outliner_geometry(1, mesh) == "-"
    assert source_outliner_geometry(0, None) == "-"


def test_source_tree_status_text_adds_dds_badge_color() -> None:
    assert source_tree_status_text("Assigned", "#3fb950", "") == ("Assigned", "#3fb950")
    assert source_tree_status_text("Assigned", "#3fb950", "Route DDS") == (
        "Assigned | Route DDS",
        "#d29922",
    )
    assert source_tree_status_text("Assigned", "#3fb950", "Copy DDS") == (
        "Assigned | Copy DDS",
        "#3fb950",
    )


def test_source_outliner_dds_text_prefers_badge_then_slot_count() -> None:
    assert source_outliner_dds_text(2, "Route DDS", source_texture_slot_count=lambda _indices: 5) == "Route DDS"
    assert source_outliner_dds_text(2, "", source_texture_slot_count=lambda indices: len(tuple(indices)) + 4) == "Src 5"


def test_removed_target_dds_cell_text_preserves_unknown_or_empty_and_uses_patch_state() -> None:
    assert removed_target_dds_cell_text("Sidecar unknown", True) == "Sidecar unknown"
    assert removed_target_dds_cell_text("Orig 0 | Src 0", True) == "Orig 0 | Src 0"
    assert removed_target_dds_cell_text("Orig 2 | Src 1", True) == "Will prune"
    assert removed_target_dds_cell_text("Orig 2 | Src 1", False) == "Kept"
    assert removed_target_dds_cell_text("Orig 2 | Src 1", None) == "Orig refs"


def test_format_index_list_limits_to_four_with_overflow_count() -> None:
    assert format_index_list((), display_name=lambda index: str(index)) == "-"
    assert format_index_list((1, 2, 3, 4), display_name=lambda index: f"item {index}") == (
        "item 1, item 2, item 3, item 4"
    )
    assert format_index_list((1, 2, 3, 4, 5, 6), display_name=lambda index: f"item {index}") == (
        "item 1, item 2, item 3, item 4 +2"
    )


def test_nonnegative_indices_coerces_valid_values_and_skips_invalid_or_negative() -> None:
    assert nonnegative_indices((0, "2", -1, "bad", None, 3.0)) == (0, 2, 3)


def test_unique_nonnegative_indices_coerces_filters_and_deduplicates() -> None:
    assert unique_nonnegative_indices((0, "2", 0, -1, "bad", None, 3.0, 2)) == (0, 2, 3)


def test_source_display_cache_revision_initial_state_preserves_value() -> None:
    assert source_display_cache_revision_initial_state() == {"value": 0}


def test_invalidate_source_display_cache_clears_cached_labels_and_bumps_revision() -> None:
    labels = {1: "old"}
    duplicates = {"skin": 2}
    revision = {"value": 4}

    assert invalidate_source_display_cache(labels, duplicates, revision) == 5

    assert labels == {}
    assert duplicates == {}
    assert revision == {"value": 5}


def test_selection_view_initial_states_preserve_defaults() -> None:
    assert single_selection_index_initial_state() == {"index": -1}
    assert mesh_replacement_selection_view_initial_model() == {
        "kind": "none",
        "source_indices": (),
        "target_indices": (),
        "material_name": "",
        "texture_role": "",
        "texture_path": "",
        "warning": "",
    }


def test_update_mesh_replacement_selection_view_model_normalizes_fields() -> None:
    model: dict[str, object] = {"kind": "old"}

    update_mesh_replacement_selection_view_model(
        model,
        kind="source",
        source_indices=(1, "bad", 2, -1),
        target_indices=("4", None, -2),
        material_name=None,  # type: ignore[arg-type]
        texture_role="base",
        texture_path="foo.dds",
        warning="careful",
    )

    assert model == {
        "kind": "source",
        "source_indices": (1, 2),
        "target_indices": (4,),
        "material_name": "",
        "texture_role": "base",
        "texture_path": "foo.dds",
        "warning": "careful",
    }


def test_target_mapping_selection_view_payload_tracks_selected_target_only() -> None:
    assert target_mapping_selection_view_payload(
        selected_target_index=2,
        target_index=2,
        source_indices=(1, "bad", -1, 3),
    ) == {"kind": "target", "target_indices": (2,), "source_indices": (1, 3)}
    assert target_mapping_selection_view_payload(
        selected_target_index=1,
        target_index=2,
        source_indices=(1,),
    ) is None


def test_source_and_target_selection_view_payloads_normalize_selection() -> None:
    assert source_selection_view_payload(2, (4, "5")) == {
        "kind": "source",
        "source_indices": (2,),
        "target_indices": (4, 5),
    }
    assert source_selection_view_payload(-1, (4,)) == {
        "kind": "none",
        "source_indices": (),
        "target_indices": (4,),
    }
    assert target_selection_view_payload(3, (1, "2")) == {
        "kind": "target",
        "target_indices": (3,),
        "source_indices": (1, 2),
    }
    assert target_selection_view_payload(-1) == {"kind": "none", "target_indices": (), "source_indices": ()}


def test_source_original_and_target_selection_states_aggregate_highlights_and_payloads() -> None:
    source_state = source_selection_state(2, (4, "5"))
    assert source_state == {
        "source_index": 2,
        "source_highlight_indices": (2,),
        "transform_source_indices": (2,),
        "target_original_highlight_indices": (),
        "target_source_highlight_indices": (),
        "selection_view": {"kind": "source", "source_indices": (2,), "target_indices": (4, 5)},
    }

    empty_source_state = source_selection_state("bad", (4,))
    assert empty_source_state["source_index"] == -1
    assert empty_source_state["source_highlight_indices"] == ()
    assert empty_source_state["selection_view"] == {"kind": "none", "source_indices": (), "target_indices": (4,)}

    original_state = original_selection_state((3, 4))
    assert original_state == {
        "original_index": 3,
        "original_highlight_indices": (3,),
        "selection_view": {"kind": "target", "target_indices": (3,), "source_indices": ()},
    }

    target_state = target_selection_state("7", (2, "bad", 3))
    assert target_state == {
        "target_index": 7,
        "target_original_highlight_indices": (7,),
        "target_source_highlight_indices": (2, 3),
        "selection_view": {"kind": "target", "target_indices": (7,), "source_indices": (2, 3)},
    }

    empty_target_state = target_selection_state(None, (2,))
    assert empty_target_state == {
        "target_index": -1,
        "target_original_highlight_indices": (),
        "target_source_highlight_indices": (),
        "selection_view": {"kind": "none", "target_indices": (), "source_indices": ()},
    }


def test_selection_route_states_add_view_kwargs_and_refresh_flags() -> None:
    source_route = source_selection_route_state(
        2,
        (4, "5"),
        has_filter_refresh=True,
        selected_filter_enabled=True,
    )
    assert source_route["source_index"] == 2
    assert source_route["selection_view_kwargs"] == {
        "kind": "source",
        "source_indices": (2,),
        "target_indices": (4, 5),
        "material_name": "",
        "texture_role": "",
        "texture_path": "",
        "warning": "",
    }
    assert source_route["clear_transform_source_indices"] is False
    assert source_route["refresh_filter"] is True

    empty_source_route = source_selection_route_state(
        "bad",
        (),
        has_filter_refresh=True,
        selected_filter_enabled=True,
    )
    assert empty_source_route["source_index"] == -1
    assert empty_source_route["clear_transform_source_indices"] is True

    original_route = original_selection_route_state((3, 4))
    assert original_route["original_index"] == 3
    assert original_route["selection_view_kwargs"]["target_indices"] == (3,)

    target_route = target_selection_route_state("7", (3, 2, "bad"))
    assert target_route["target_index"] == 7
    assert target_route["outliner_source_selection"] == (2, 3)
    assert target_route["selection_view_kwargs"]["source_indices"] == (3, 2)


def test_selection_highlight_sets_state_aggregates_preview_and_d3d11_routes() -> None:
    state = selection_highlight_sets_state(
        selected_source_highlights=(3, 1, "bad"),
        selected_target_source_highlights=(2, 1),
        selected_original_highlights=(5,),
        selected_target_original_highlights=(4, 5),
        d3d11_active=True,
        geometry_active=True,
        texture_tab_active=False,
        mesh_edit_raw_active=False,
        preview_gizmo_checked=True,
        selected_source_overlay_ids=(30,),
        selected_source_editor_ids=(10, 11),
        selected_target_source_editor_ids=(20, 21),
        disabled_source_editor_ids=(99,),
        default_d3d11_editor_ids=(7, 8),
    )

    assert state == {
        "highlighted_source_indices": (1, 2, 3),
        "highlighted_original_indices": (4, 5),
        "d3d11_highlighted_indices": (20, 21, 30),
        "d3d11_original_highlighted_indices": (4, 5),
        "d3d11_selected_indices": (7, 8),
        "d3d11_hidden_source_indices": (99,),
        "d3d11_gizmo_enabled": True,
    }

    fallback_state = selection_highlight_sets_state(
        selected_source_highlights=(3,),
        selected_target_source_highlights=(),
        selected_original_highlights=(5,),
        selected_target_original_highlights=(),
        d3d11_active=True,
        geometry_active=False,
        texture_tab_active=True,
        mesh_edit_raw_active=True,
        preview_gizmo_checked=True,
        selected_source_overlay_ids=(),
        selected_source_editor_ids=(13,),
        selected_target_source_editor_ids=(),
        disabled_source_editor_ids=(99,),
        default_d3d11_editor_ids=(7,),
    )
    assert fallback_state["d3d11_highlighted_indices"] == (13,)
    assert fallback_state["d3d11_original_highlighted_indices"] == (5,)
    assert fallback_state["d3d11_selected_indices"] == ()
    assert fallback_state["d3d11_hidden_source_indices"] == (99,)
    assert fallback_state["d3d11_gizmo_enabled"] is False

    inactive_state = selection_highlight_sets_state(
        selected_source_highlights=(1,),
        selected_target_source_highlights=(2,),
        selected_original_highlights=(3,),
        selected_target_original_highlights=(4,),
        d3d11_active=False,
        geometry_active=True,
        texture_tab_active=True,
        mesh_edit_raw_active=False,
        preview_gizmo_checked=True,
        selected_source_overlay_ids=(10,),
        selected_source_editor_ids=(11,),
        selected_target_source_editor_ids=(12,),
        disabled_source_editor_ids=(13,),
        default_d3d11_editor_ids=(14,),
    )
    assert inactive_state["highlighted_source_indices"] == (1, 2)
    assert inactive_state["highlighted_original_indices"] == (3, 4)
    assert inactive_state["d3d11_highlighted_indices"] == ()


def test_parts_outliner_target_selection_state_owns_highlights_and_payload() -> None:
    assert parts_outliner_target_selection_state(
        row_kind="target",
        target_index=4,
        source_indices=(2, "bad", 3),
    ) == {
        "selected_target_index": 4,
        "target_original_highlight_indices": (4,),
        "target_source_highlight_indices": (2, 3),
        "selection_view": {"kind": "target", "target_indices": (4,), "source_indices": (2, 3)},
    }
    assert parts_outliner_target_selection_state(row_kind="source", target_index=4, source_indices=(2,)) is None


def test_texture_row_selection_highlight_state_detects_change_and_reset_routes() -> None:
    assert texture_row_selection_highlight_state(
        source_indices=(1, "bad", 2),
        target_index=5,
        selected_source_highlights=(1, 2),
        selected_target_original_highlights=(5,),
        transform_source_indices=(),
    ) == {
        "changed": False,
        "selected_source_index": -1,
        "selected_target_index": 5,
        "selected_source_highlight_indices": (),
        "target_source_highlight_indices": (1, 2),
        "target_original_highlight_indices": (5,),
        "clear_transform_source_indices": True,
    }

    changed_state = texture_row_selection_highlight_state(
        source_indices=(3,),
        target_index=-1,
        selected_source_highlights=(1,),
        selected_target_original_highlights=(5,),
        transform_source_indices=(8,),
    )
    assert changed_state["changed"] is True
    assert changed_state["selected_target_index"] == -1
    assert changed_state["target_source_highlight_indices"] == (3,)
    assert changed_state["target_original_highlight_indices"] == ()


def test_selection_view_update_kwargs_normalizes_payload_for_dialog_setter() -> None:
    assert selection_view_update_kwargs(
        {
            "kind": "source",
            "source_indices": (1, "2", -1),
            "target_indices": ("4", "bad"),
            "material_name": "mat",
            "texture_role": "base",
            "texture_path": "foo.dds",
            "warning": "careful",
        }
    ) == {
        "kind": "source",
        "source_indices": (1, 2),
        "target_indices": (4,),
        "material_name": "mat",
        "texture_role": "base",
        "texture_path": "foo.dds",
        "warning": "careful",
    }
    assert selection_view_update_kwargs({}) == {
        "kind": "none",
        "source_indices": (),
        "target_indices": (),
        "material_name": "",
        "texture_role": "",
        "texture_path": "",
        "warning": "",
    }


def test_target_selection_highlight_state_normalizes_target_and_sources() -> None:
    assert target_selection_highlight_state(3, (1, "2", -1, "bad")) == {
        "target_original_indices": (3,),
        "target_source_indices": (1, 2),
    }
    assert target_selection_highlight_state(-1, (1,)) == {
        "target_original_indices": (),
        "target_source_indices": (),
    }
    assert target_selection_highlight_state("bad", (1,)) == {
        "target_original_indices": (),
        "target_source_indices": (),
    }


def test_single_selection_highlight_indices_normalizes_selected_index() -> None:
    assert single_selection_highlight_indices(0) == (0,)
    assert single_selection_highlight_indices("4") == (4,)
    assert single_selection_highlight_indices(-1) == ()
    assert single_selection_highlight_indices("bad") == ()


def test_source_selection_highlight_state_resets_target_highlights() -> None:
    assert source_selection_highlight_state(4) == {
        "source_indices": (4,),
        "transform_source_indices": (4,),
        "target_original_indices": (),
        "target_source_indices": (),
    }
    assert source_selection_highlight_state(-1) == {
        "source_indices": (),
        "transform_source_indices": (),
        "target_original_indices": (),
        "target_source_indices": (),
    }


def test_d3d11_source_selection_index_prefers_current_member_then_first_source() -> None:
    assert d3d11_source_selection_index(4, (2, 4, 6)) == 4
    assert d3d11_source_selection_index(9, (2, 4, 6)) == 2
    assert d3d11_source_selection_index("bad", (3,)) == 3
    assert d3d11_source_selection_index(1, ()) == -1
    assert d3d11_source_selection_index(1, ("bad", -2)) == -1


def test_d3d11_source_part_selection_route_requires_active_geometry_preview() -> None:
    route = d3d11_source_part_selection_route(
        preview_active=True,
        geometry_tab_active=True,
        source_index="10",
        current_source_index=4,
        editor_source_indices=(2, 4),
    )
    assert route == {"source_index": 10, "selected_source_index": 4, "should_select": True}

    inactive = d3d11_source_part_selection_route(
        preview_active=False,
        geometry_tab_active=True,
        source_index="10",
        current_source_index=4,
        editor_source_indices=(2, 4),
    )
    assert inactive["selected_source_index"] == 4
    assert inactive["should_select"] is False

    missing = d3d11_source_part_selection_route(
        preview_active=True,
        geometry_tab_active=True,
        source_index="bad",
        current_source_index=4,
        editor_source_indices=(),
    )
    assert missing == {"source_index": -1, "selected_source_index": -1, "should_select": False}


def test_selection_filter_refresh_needed_requires_callback_and_enabled_filter() -> None:
    assert selection_filter_refresh_needed(has_filter_refresh=True, selected_filter_enabled=True)
    assert not selection_filter_refresh_needed(has_filter_refresh=False, selected_filter_enabled=True)
    assert not selection_filter_refresh_needed(has_filter_refresh=True, selected_filter_enabled=False)


def test_material_plan_highlight_state_clears_source_and_tracks_material_selection() -> None:
    assert material_plan_highlight_state(
        has_item=True,
        source_indices=(2, "3", -1),
        target_index=4,
        material_name="mat",
        texture_role="base",
        texture_path="foo.dds",
    ) == {
        "selected_source_index": -1,
        "source_highlight_indices": (),
        "transform_source_indices": (),
        "selected_target_index": 4,
        "target_source_highlight_indices": (2, 3),
        "target_original_highlight_indices": (4,),
        "texture_plan_source": {"material_name": "mat", "source_indices": (2, 3)},
        "selection_view": {
            "kind": "material",
            "source_indices": (2, 3),
            "target_indices": (4,),
            "material_name": "mat",
            "texture_role": "base",
            "texture_path": "foo.dds",
        },
    }
    empty_state = material_plan_highlight_state(
        has_item=False,
        source_indices=(),
        target_index=-1,
        material_name="",
        texture_role="",
        texture_path="",
    )
    assert empty_state["selection_view"] == {
        "kind": "none",
        "source_indices": (),
        "target_indices": (),
        "material_name": "",
        "texture_role": "",
        "texture_path": "",
    }


def test_added_part_texture_highlight_state_tracks_source_targets_and_warning() -> None:
    assert added_part_texture_highlight_state(
        source_index=5,
        target_indices=(2, "3", -1),
        material_name="mat",
        texture_state="Missing base",
    ) == {
        "selected_source_index": -1,
        "source_highlight_indices": (5,),
        "transform_source_indices": (),
        "selected_target_index": 2,
        "target_source_highlight_indices": (5,),
        "target_original_highlight_indices": (2, 3),
        "selection_view": {
            "kind": "source",
            "source_indices": (5,),
            "target_indices": (2, 3),
            "material_name": "mat",
            "warning": "Missing base",
        },
    }
    ready_state = added_part_texture_highlight_state(
        source_index=5,
        target_indices=(2,),
        material_name="mat",
        texture_state="Ready",
    )
    assert ready_state["selection_view"]["warning"] == ""  # type: ignore[index]
    assert added_part_texture_highlight_state(
        source_index=-1,
        target_indices=(2,),
        material_name="mat",
        texture_state="-",
    )["selection_view"] == {
        "kind": "none",
        "source_indices": (),
        "target_indices": (),
        "material_name": "",
        "warning": "-",
    }


def test_original_and_target_selection_index_normalize_raw_item_data() -> None:
    assert original_selection_index((3, 4)) == 3
    assert original_selection_index("5") == 5
    assert original_selection_index(()) == -1
    assert original_selection_index("bad") == -1
    assert target_selection_index("7") == 7
    assert target_selection_index(None) == -1


def test_part_selection_state_active_detects_any_selected_part_highlight_or_tree() -> None:
    base_kwargs = {
        "selected_source_index": -1,
        "selected_original_index": -1,
        "selected_target_index": -1,
        "selected_source_highlights": (),
        "selected_target_source_highlights": (),
        "selected_original_highlights": (),
        "selected_target_original_highlights": (),
        "source_tree_has_selection": False,
        "original_tree_has_selection": False,
        "mapping_tree_has_selection": False,
    }

    assert not part_selection_state_active(**base_kwargs)
    assert part_selection_state_active(**{**base_kwargs, "selected_source_index": 1})
    assert part_selection_state_active(**{**base_kwargs, "selected_target_source_highlights": (2,)})
    assert part_selection_state_active(**{**base_kwargs, "mapping_tree_has_selection": True})


def test_part_selection_clear_state_resets_indices_highlights_and_view_payload() -> None:
    assert part_selection_clear_state() == {
        "selected_source_index": -1,
        "selected_original_index": -1,
        "selected_target_index": -1,
        "selected_source_highlights": (),
        "selected_target_source_highlights": (),
        "selected_original_highlights": (),
        "selected_target_original_highlights": (),
        "selection_view": {"kind": "none", "source_indices": (), "target_indices": ()},
    }


def test_part_selection_clear_scope_state_resets_requested_scope_only() -> None:
    assert part_selection_clear_scope_state("source") == {
        "selected_source_index": -1,
        "selected_original_index": None,
        "selected_target_index": None,
        "clear_source_highlights": True,
        "clear_original_highlights": False,
        "clear_target_source_highlights": False,
        "clear_target_original_highlights": False,
        "clear_transform_sources": True,
        "selection_view": {"kind": "none", "source_indices": (), "target_indices": ()},
    }
    target_state = part_selection_clear_scope_state("target")
    assert target_state["selected_source_index"] is None
    assert target_state["selected_target_index"] == -1
    assert target_state["clear_target_source_highlights"] is True
    assert target_state["clear_target_original_highlights"] is True
    all_state = part_selection_clear_scope_state("all")
    assert all_state["selected_source_index"] == -1
    assert all_state["selected_original_index"] == -1
    assert all_state["selected_target_index"] == -1
    assert all_state["clear_source_highlights"] is True
    assert all_state["clear_original_highlights"] is True


def test_mapping_indices_with_appended_source_preserves_order_and_skips_invalid() -> None:
    assert mapping_indices_with_appended_source("1, bad; 2 01", 3) == (1, 2, 1, 3)
    assert mapping_indices_with_appended_source("1, 3", 3) == (1, 3)
    assert mapping_indices_with_appended_source("", 0) == (0,)


def test_unique_mapping_indices_preserves_first_occurrence_and_skips_invalid() -> None:
    assert unique_mapping_indices("1, bad; 2 1\n3") == (1, 2, 3)
    assert unique_mapping_indices("") == ()


def test_disabled_source_part_indices_sorts_disabled_adjustments() -> None:
    assert disabled_source_part_indices(
        {
            4: SimpleNamespace(enabled=False),
            2: SimpleNamespace(enabled=True),
            1: SimpleNamespace(enabled=False),
        }
    ) == (1, 4)


def test_current_source_part_adjustments_sorts_and_filters_defaults() -> None:
    default_adjustment = SimpleNamespace(name="default")
    changed_adjustment = SimpleNamespace(name="changed")
    other_adjustment = SimpleNamespace(name="other")

    assert current_source_part_adjustments(
        {3: changed_adjustment, 1: default_adjustment, 2: other_adjustment},
        is_default_adjustment=lambda adjustment: adjustment is default_adjustment,
    ) == [other_adjustment, changed_adjustment]


def test_source_target_summary_parses_mapping_text_and_formats_targets() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="targetA", material="matA"),
            SimpleNamespace(name="targetB", material=""),
            SimpleNamespace(name="targetC", material="matC"),
        ]
    )
    mapping_edits = [
        (0, SimpleNamespace(text=lambda: "1, 2")),
        (1, SimpleNamespace(text=lambda: "")),
        (2, SimpleNamespace(text=lambda: "bad;2")),
        (4, SimpleNamespace(text=lambda: "2")),
    ]

    assert source_target_summary(2, mapping_edits, mesh) == "0: matA, 2: matC"
    assert source_target_summary(3, mapping_edits, mesh) == ""
    assert source_target_summary(2, mapping_edits, None) == "-"


def test_source_index_remap_helpers_filter_and_optionally_copy_values() -> None:
    index_map = {0: 4, 2: 5, 3: -1}

    assert remap_source_index_collection((0, "bad", 2, 3), index_map) == {4, 5}
    assert remap_selected_source_index(2, index_map) == 5
    assert remap_selected_source_index("bad", index_map) == -1
    assert remap_selected_source_index(9, index_map) == -1

    value = {"name": "src"}
    remapped = remap_source_index_dict({0: value, 2: "two", "bad": "skip"}, index_map)
    assert remapped == {4: value, 5: "two"}
    assert remapped[4] is value

    copied = remap_source_index_dict({0: value}, index_map, copy_values=True)
    assert copied == {4: value}
    assert copied[4] is not value


def test_source_indices_for_target_name_uses_committed_text_and_deduplicates() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="targetA", material="matA"),
            SimpleNamespace(name="targetB", material=""),
        ]
    )

    class Edit:
        def __init__(self, text: str, committed: str = "") -> None:
            self._text = text
            self._committed = committed

        def text(self) -> str:
            return self._text

        def property(self, name: str) -> str:
            return self._committed if name == "committed_mapping_text" else ""

    mapping_edits = [
        (0, Edit("1, 2, 2", committed="3; bad; 3; 4")),
        (1, Edit("5")),
    ]

    assert source_indices_for_target_name("mata", mapping_edits, mesh) == (3, 4)
    assert source_indices_for_target_name("targetb", mapping_edits, mesh) == (5,)
    assert source_indices_for_target_name("missing", mapping_edits, mesh) == ()
    assert source_indices_for_target_name("mata", mapping_edits, None) == ()


def test_output_impact_counts_counts_removed_used_disabled_dds_and_sidecar_status() -> None:
    mapping_edits = [(0, "0, 1"), (1, "2"), (2, "3")]
    texture_rows = [
        {"checked": "true"},
        {"assigned_source": "foo.dds"},
        {"suggested_source": ""},
    ]

    def parse(edit: object) -> tuple[int, ...]:
        return tuple(int(part.strip()) for part in str(edit).split(",") if part.strip())

    def enabled(indices) -> tuple[int, ...]:
        return tuple(index for index in indices if index in {0, 2})

    assert output_impact_counts(
        mapping_edits,
        texture_rows,
        parse_mapping_edit=parse,
        enabled_renderable_source_indices=enabled,
        sidecar_enabled=True,
        prune_unmapped_enabled=False,
    ) == (1, 2, 2, 2, "prune removed")
    assert output_impact_counts(
        mapping_edits,
        texture_rows,
        parse_mapping_edit=parse,
        enabled_renderable_source_indices=enabled,
        sidecar_enabled=True,
        prune_unmapped_enabled=True,
    )[-1] == "visible only"
    assert output_impact_counts(
        ((0, "0"),),
        (),
        parse_mapping_edit=parse,
        enabled_renderable_source_indices=enabled,
        sidecar_enabled=False,
        prune_unmapped_enabled=False,
    )[-1] == "-"
