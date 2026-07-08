from __future__ import annotations

from pathlib import Path

from cdmw.ui.archive_browser.static_replacement_geometry_math import (
    external_import_work_area_fit,
    transformed_vertices_for_work_area,
)


ROOT = Path(__file__).resolve().parents[1]
PROMPT_SETUP = ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_setup.py"
SOURCE_PART_STATE = ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_part_geometry_state.py"


def test_initial_external_import_uses_shared_work_area_fit_source_path() -> None:
    source = PROMPT_SETUP.read_text(encoding="utf-8")

    assert "external_import_work_area_fit" in source
    assert "is_external_scene_import = isinstance(scene_import_result, SceneImportResult) and not bool(modify_original_clone_mode)" in source
    assert "_apply_work_area_fit(replacement_mesh_base_for_mapping, placement_fit)" in source
    assert "_apply_work_area_fit(replacement_mesh_for_mapping, placement_fit)" in source
    assert "mesh_external_import_work_area_fit" in source


def test_appended_part_path_reuses_shared_work_area_fit_helper() -> None:
    source = SOURCE_PART_STATE.read_text(encoding="utf-8")

    assert "appended_part_work_area_fit(source_vertices, reference_vertices)" in source


def test_shared_work_area_fit_places_initial_import_on_grid() -> None:
    fit = external_import_work_area_fit(
        ((10.0, 4.0, 10.0), (12.0, 6.0, 12.0)),
        ((-1.0, 0.0, -1.0), (1.0, 2.0, 1.0)),
        up_axis=1,
        ground_plane=0.0,
    )

    assert fit is not None
    transformed = transformed_vertices_for_work_area(((10.0, 4.0, 10.0), (12.0, 6.0, 12.0)), fit)
    assert min(vertex[1] for vertex in transformed) == 0.0
    assert round((transformed[0][0] + transformed[1][0]) * 0.5, 6) == 0.0
    assert round((transformed[0][2] + transformed[1][2]) * 0.5, 6) == 0.0
