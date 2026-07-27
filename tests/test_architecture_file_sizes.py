"""Per-file line caps for files that must stay *smaller* than the default.

This guard is the tighter-than-default layer. It is **not** the universal
limit: ``tests/test_architecture_size_ratchets.py`` already applies
``DEFAULT_OWNER_FILE_LINE_LIMIT`` to every owned Python, native and C# file and
grandfathers today's offenders in ``architecture_size_baseline*.json``. Anything
absent from the table below is still capped there.

So only list a file here when it has a reason to stay small -- a thin shim, a
proxy, a callback surface -- and put that reason in the commit. A cap at or
above the default protects nothing and is rejected by
``test_limits_table_stays_meaningful``.

The rule this guard exists to serve, which the number alone cannot express:

    Never split a file solely to satisfy the counter. A split has to leave two
    parts you can name. ``..._state_a`` / ``..._state_b`` is the shape of a
    split made to get the build green, and it makes the code worse while
    reporting success. When a file has honestly outgrown its cap, raise the cap
    in the same commit and say why.

Caps carry headroom on purpose: one sitting exactly at a file's current length
turns an added comment into a build failure, which teaches people to delete
comments rather than to think about structure.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.architecture_limits import DEFAULT_OWNER_FILE_LINE_LIMIT


ROOT = Path(__file__).resolve().parents[1]


LIMITS: dict[str, int] = {
    "cdmw/ui/archive_browser/asset_catalog_dialog.py": 930,
    "cdmw/ui/archive_browser/hkx_related_models.py": 300,
    "cdmw/ui/archive_browser/static_replacement_added_part_texture_items.py": 400,
    "cdmw/ui/archive_browser/static_replacement_combo_options.py": 200,
    "cdmw/ui/archive_browser/static_replacement_dialog.py": 200,
    "cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_base.py": 300,
    "cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_callbacks.py": 300,
    "cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_state_a.py": 600,
    "cdmw/ui/archive_browser/static_replacement_dialog_prompt_open.py": 200,
    "cdmw/ui/archive_browser/static_replacement_dialog_prompt_setup.py": 520,
    "cdmw/ui/archive_browser/static_replacement_dialog_prompt_shell.py": 380,
    "cdmw/ui/archive_browser/static_replacement_dialog_prompt_state_callbacks.py": 530,
    "cdmw/ui/archive_browser/static_replacement_dialog_prompt_transform.py": 120,
    "cdmw/ui/archive_browser/static_replacement_native_manifest.py": 250,
    "cdmw/ui/archive_browser/static_replacement_part_items.py": 400,
    "cdmw/ui/archive_browser/static_replacement_preview_cache.py": 130,
    "cdmw/ui/archive_browser/static_replacement_preview_models.py": 500,
    "cdmw/ui/archive_browser/static_replacement_prompt_preflight.py": 530,
    "cdmw/ui/archive_browser/static_replacement_qt_helpers.py": 740,
    "cdmw/ui/archive_browser/static_replacement_selection_view_state.py": 420,
    "cdmw/ui/archive_browser/static_replacement_texture_table.py": 500,
    "cdmw/ui/archive_browser/static_replacement_transform_state.py": 400,
    "cdmw/ui/archive_browser/virtual_path_lookup.py": 400,
    "cdmw/ui/item_icons/panels.py": 400,
    "cdmw/ui/item_icons/state.py": 700,
    "cdmw/ui/item_icons/tab.py": 700,
    "cdmw/ui/main_window.py": 120,
    "cdmw/ui/model_library/actions.py": 700,
    "cdmw/ui/model_library/catalogue.py": 700,
    "cdmw/ui/model_library/commands.py": 700,
    "cdmw/ui/model_library/icon_output.py": 200,
    "cdmw/ui/model_library/local_rows.py": 700,
    "cdmw/ui/model_library/panels.py": 700,
    "cdmw/ui/model_library/preview.py": 700,
    "cdmw/ui/model_library/selection.py": 700,
    "cdmw/ui/model_library/settings.py": 700,
    "cdmw/ui/model_library/state.py": 700,
    "cdmw/ui/model_library/tab.py": 450,
    "cdmw/ui/model_library/tasks.py": 700,
    "cdmw/ui/model_library/texture_status.py": 700,
    "cdmw/ui/model_library/view_state.py": 700,
    "cdmw/ui/model_library/workers.py": 700,
    "cdmw/ui/research/analysis_controller.py": 260,
    "cdmw/ui/research/analysis_state.py": 360,
    "cdmw/ui/research/archive_picker_controller.py": 420,
    "cdmw/ui/research/archive_picker_state.py": 300,
    "cdmw/ui/research/classification_review_controller.py": 650,
    "cdmw/ui/research/classification_review_state.py": 440,
    "cdmw/ui/research/display_preferences_state.py": 120,
    "cdmw/ui/research/help_widgets.py": 120,
    "cdmw/ui/research/layout_state.py": 180,
    "cdmw/ui/research/models.py": 510,
    "cdmw/ui/research/notes_controller.py": 120,
    "cdmw/ui/research/notes_state.py": 100,
    "cdmw/ui/research/preview_controller.py": 420,
    "cdmw/ui/research/preview_controls.py": 120,
    "cdmw/ui/research/preview_state.py": 140,
    "cdmw/ui/research/progress_helpers.py": 80,
    "cdmw/ui/research/reference_controller.py": 240,
    "cdmw/ui/research/reference_payload_state.py": 260,
    "cdmw/ui/research/refresh_controller.py": 650,
    "cdmw/ui/research/refresh_population_state.py": 170,
    "cdmw/ui/research/state.py": 760,
    "cdmw/ui/research/tab.py": 900,
    "cdmw/ui/research/tab_side_panel_builders.py": 400,
    "cdmw/ui/research/texture_group_state.py": 90,
    "cdmw/ui/research/tree_column_specs.py": 80,
    "cdmw/ui/research/tree_helpers.py": 120,
    "cdmw/ui/research/tree_population.py": 180,
    "cdmw/ui/research/workers.py": 400,
    "cdmw/ui/shell/app_startup.py": 330,
    "cdmw/ui/shell/app_window.py": 760,
    "cdmw/ui/shell/main_window_proxy.py": 120,
    "cdmw/ui/shell/settings_autosave.py": 400,
    "cdmw/ui/shell/startup_splash.py": 300,
    "cdmw/ui/shell/theme_controller.py": 850,
    "cdmw/ui/text_search/controller.py": 650,
    "cdmw/ui/text_search/preview_panel.py": 900,
    "cdmw/ui/text_search/tab.py": 550,
    "cdmw/ui/text_search/workers.py": 700,
    "cdmw/ui/texture_workflow/editor_adjustment_ui.py": 500,
    "cdmw/ui/texture_workflow/editor_async_task_ui.py": 120,
    "cdmw/ui/texture_workflow/editor_brush_preset_ui.py": 300,
    "cdmw/ui/texture_workflow/editor_channel_ui.py": 300,
    "cdmw/ui/texture_workflow/editor_document_ui.py": 250,
    "cdmw/ui/texture_workflow/editor_file_io_ui.py": 530,
    "cdmw/ui/texture_workflow/editor_floating_ui.py": 500,
    "cdmw/ui/texture_workflow/editor_history_ui.py": 240,
    "cdmw/ui/texture_workflow/editor_layer_ui.py": 500,
    "cdmw/ui/texture_workflow/editor_refresh_ui.py": 560,
    "cdmw/ui/texture_workflow/editor_selection_ui.py": 300,
    "cdmw/ui/texture_workflow/editor_session_ui.py": 220,
    "cdmw/ui/texture_workflow/editor_settings_persistence.py": 300,
    "cdmw/ui/texture_workflow/editor_shortcuts_ui.py": 300,
    "cdmw/ui/texture_workflow/editor_status_cache_ui.py": 160,
    "cdmw/ui/texture_workflow/editor_tool_coordination.py": 240,
    "cdmw/ui/texture_workflow/editor_tool_operation_ui.py": 320,
    "cdmw/ui/texture_workflow/editor_ui_shell.py": 500,
    "cdmw/ui/texture_workflow/editor_view_coordination.py": 500,
    "cdmw/ui/texture_workflow/editor_worker_lifecycle.py": 200,
    "cdmw_app.py": 120,
}


def _line_count(relative_path: str) -> int:
    return len((ROOT / relative_path).read_text(encoding="utf-8").splitlines())


def test_selected_architecture_file_size_limits() -> None:
    """Report every file over its cap, not just the first one found."""
    failures = [
        f"{path_text} has {count} lines, limit is {limit}"
        for path_text, limit in sorted(LIMITS.items())
        if (count := _line_count(path_text)) > limit
    ]
    assert not failures, "Files over their declared cap:\n  " + "\n  ".join(failures)


def test_limits_table_stays_meaningful() -> None:
    """Stop the table rotting back into fossils and dangling entries.

    Two ways it decayed before: caps left far above a file that had since been
    split (one file of 109 lines carried a cap of 7545), and entries kept for
    files at the default, which the universal ratchet already covers.
    """
    missing = sorted(path for path in LIMITS if not (ROOT / path).is_file())
    assert not missing, f"LIMITS names files that no longer exist: {missing}"

    redundant = sorted(
        f"{path} (cap {limit})"
        for path, limit in LIMITS.items()
        if limit >= DEFAULT_OWNER_FILE_LINE_LIMIT
    )
    assert not redundant, (
        "These caps are at or above the universal default, so they add nothing "
        "beyond test_architecture_size_ratchets.py -- drop them: " + ", ".join(redundant)
    )


def test_main_window_owns_feature_controllers_instead_of_feature_mixins() -> None:
    tree = ast.parse((ROOT / "cdmw/ui/shell/app_window.py").read_text(encoding="utf-8"))
    main_window = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "MainWindow"
    )

    assert [ast.unparse(base) for base in main_window.bases] == ["QMainWindow"]

    source = (ROOT / "cdmw/ui/shell/app_window.py").read_text(encoding="utf-8")
    assert "WindowFeatureController(self, SHELL_FEATURE_PROVIDERS)" in source
    assert "WindowFeatureController(self, ARCHIVE_FEATURE_PROVIDERS)" in source
    assert "WindowFeatureController(self, TEXTURE_FEATURE_PROVIDERS)" in source
    assert "WindowFeatureController(self, MESH_FEATURE_PROVIDERS)" in source
