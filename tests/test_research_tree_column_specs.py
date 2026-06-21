from __future__ import annotations

from cdmw.ui.research.tree_column_specs import research_tree_column_specs


def test_research_tree_column_specs_cover_expected_tree_storage_names() -> None:
    specs = research_tree_column_specs()
    by_storage = {spec.storage_name: spec for spec in specs}

    assert set(by_storage) == {
        "archive_picker",
        "texture_group",
        "classifier",
        "unknown_group",
        "unknown_member",
        "reference",
        "sidecar",
        "ui_constraint",
        "heatmap",
        "mip",
        "normal",
        "budget_file",
        "budget_class",
        "budget_group",
        "budget_profile",
        "notes",
    }
    assert by_storage["archive_picker"].tree_attr == "archive_picker_tree"
    assert by_storage["archive_picker"].min_widths[0] == 260
    assert by_storage["unknown_member"].min_widths[5] == 220
    assert by_storage["budget_profile"].min_widths[4] == 90


def test_research_tree_column_specs_are_immutable() -> None:
    spec = research_tree_column_specs()[0]

    try:
        spec.min_widths[0] = 1  # type: ignore[index]
    except TypeError:
        pass
    else:  # pragma: no cover - defensive branch
        raise AssertionError("research tree column specs should not be mutable")
