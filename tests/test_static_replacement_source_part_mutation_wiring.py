from __future__ import annotations

from pathlib import Path

from tests.native_source_text import d3d11_preview_source
from tests.static_replacement_source_support import (
    static_replacement_source_part_mutation_callback_source,
    static_replacement_ui_concern_source,
)


ROOT = Path(__file__).resolve().parents[1]
PROMPT_SETUP = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_setup.py"
)


def test_alignment_selection_highlight_is_bounded() -> None:
    native_source = d3d11_preview_source()

    assert "std::clamp(batch.highlight_strength * 0.18f, 0.0f, 0.14f)" in native_source
    assert "std::max(view.reference_tint_alpha, selection_tint_alpha)" in native_source
    assert "std::clamp(batch.highlight_strength, 0.0f, 0.74f)" not in native_source
    assert "std::clamp(batch.highlight_strength, 0.0f, 0.82f)" not in native_source


def test_source_part_mutation_lazy_state_is_initialized_and_guarded() -> None:
    prompt_setup_source = PROMPT_SETUP.read_text(encoding="utf-8")
    outliner_source = static_replacement_ui_concern_source(ROOT, "source_parts_outliner")
    texture_source = static_replacement_ui_concern_source(ROOT, "texture_material")
    mutation_source = static_replacement_source_part_mutation_callback_source(ROOT)

    mutation_construction = "_state.alignment_source_part_mutation_callbacks = _state.create_alignment_source_part_mutation_callbacks"
    assert outliner_source.index(
        "_state._refresh_source_tree_selection_state = _state.alignment_source_tree_selection_callbacks._refresh_source_tree_selection_state"
    ) < outliner_source.index(mutation_construction)

    for state_name in (
        "selected_added_part_texture_row",
        "selected_texture_plan_source",
        "selected_texture_row",
    ):
        assert (
            f"'{state_name}': ({state_name} := _{state_name}_initial_state_helper())"
            in prompt_setup_source
        )
        assert f"_state.context.get('{state_name}')" in texture_source
        assert f"if not isinstance(_state.{state_name}, dict):" in texture_source

    assert "except NameError:" not in mutation_source
    assert "if isinstance(_state.selected_added_part_texture_row, dict):" in mutation_source
    assert "if isinstance(_state.selected_texture_plan_source, dict):" in mutation_source
    assert (
        "selected_texture_row = _state.selected_texture_row if isinstance(_state.selected_texture_row, dict) else {}"
        in mutation_source
    )
    for callback_name in (
        "_refresh_added_part_texture_tree",
        "_refresh_source_material_plan",
        "_refresh_texture_override_tree",
        "_refresh_texture_row_guidance",
        "_refresh_texture_table",
    ):
        assert f"if callable(_state.{callback_name}):" in mutation_source
