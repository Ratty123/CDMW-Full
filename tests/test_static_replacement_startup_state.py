from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_startup_state import (
    alignment_startup_advanced_dds_classification_progress_text,
    alignment_startup_advanced_dds_guidance_progress_text,
    alignment_startup_original_part_list_progress_text,
    alignment_startup_progress_closed,
    alignment_startup_progress_initial_state,
    alignment_startup_progress_mark_closed,
    alignment_startup_step_elapsed_ms,
    alignment_startup_step_initial_state,
    alignment_startup_step_text,
    alignment_startup_texture_plan_progress_text,
)


def test_alignment_startup_step_initial_state_has_no_start_time() -> None:
    assert alignment_startup_step_initial_state() == {"started_at": 0.0}


def test_alignment_startup_step_text_preserves_progress_copy() -> None:
    text = alignment_startup_step_text()

    assert text["initial_label"] == "Preparing Mesh Replacement Builder..."
    assert text["window_title"] == "Preparing Alignment"
    assert text["creating_window"] == "Creating alignment window..."
    assert text["local_texture_lookup"] == "Preparing local texture lookup..."
    assert text["alignment_summary"] == "Reading alignment summary..."
    assert text["original_mesh"] == "Reading original mesh..."
    assert text["material_sidecar"] == "Reading material sidecar..."
    assert text["sidecar_texture_references"] == "Preparing sidecar texture references..."
    assert text["asset_compatibility"] == "Analyzing asset compatibility..."
    assert text["replacement_mesh"] == "Reading replacement mesh..."
    assert text["preview_meshes"] == "Preparing preview meshes..."
    assert text["draw_section_routing"] == "Suggesting draw-section routing..."
    assert text["original_part_list"] == "Building original-part list..."
    assert text["replacement_source_queue"] == "Queuing replacement-source list..."
    assert text["routing_controls"] == "Preparing routing controls..."
    assert text["geometry_controls"] == "Preparing geometry controls..."
    assert text["replacement_texture_sources"] == "Preparing replacement texture sources..."
    assert text["replacement_material_maps"] == "Detecting replacement material maps..."
    assert text["advanced_dds_classification"] == "Classifying advanced DDS overrides..."
    assert text["opening_builder"] == "Opening Mesh Replacement Builder..."


def test_alignment_startup_indexed_progress_text_preserves_copy() -> None:
    assert alignment_startup_original_part_list_progress_text(7) == "Building original-part list... 7"
    assert alignment_startup_texture_plan_progress_text(8) == "Building texture plan... 8"
    assert (
        alignment_startup_advanced_dds_classification_progress_text(9)
        == "Classifying advanced DDS overrides... 9"
    )
    assert alignment_startup_advanced_dds_guidance_progress_text(10) == "Preparing advanced DDS guidance... 10"


def test_alignment_startup_step_elapsed_ms_records_first_and_next_step() -> None:
    state = alignment_startup_step_initial_state()

    assert alignment_startup_step_elapsed_ms(state, 10.0) == 0
    assert state == {"started_at": 10.0}

    assert alignment_startup_step_elapsed_ms(state, 10.125) == 125
    assert state == {"started_at": 10.125}


def test_alignment_startup_step_elapsed_ms_never_goes_negative() -> None:
    state = {"started_at": 12.0}

    assert alignment_startup_step_elapsed_ms(state, 11.0) == 0
    assert state == {"started_at": 11.0}


def test_alignment_startup_progress_state_marks_closed_once() -> None:
    state = alignment_startup_progress_initial_state()

    assert state == {"closed": False}
    assert alignment_startup_progress_closed(state) is False
    assert alignment_startup_progress_mark_closed(state) is True
    assert state == {"closed": True}
    assert alignment_startup_progress_closed(state) is True
    assert alignment_startup_progress_mark_closed(state) is False
