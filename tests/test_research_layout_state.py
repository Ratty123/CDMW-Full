from __future__ import annotations

from cdmw.ui.research.layout_state import (
    research_analysis_splitter_default_sizes,
    research_analysis_splitter_responsive_sizes,
    research_analysis_splitter_saved_sizes,
    research_archive_picker_splitter_default_sizes,
    research_groups_splitter_default_sizes,
    research_groups_splitter_responsive_sizes,
    research_groups_splitter_saved_sizes,
    research_main_splitter_default_sizes,
    research_main_splitter_responsive_sizes,
    research_main_splitter_saved_sizes,
    research_notes_splitter_default_sizes,
    research_notes_splitter_responsive_sizes,
    research_notes_splitter_saved_sizes,
    research_reference_splitter_default_sizes,
    research_reference_splitter_responsive_sizes,
    research_reference_splitter_saved_sizes,
    research_unknown_splitter_default_sizes,
    research_unknown_splitter_responsive_sizes,
    research_unknown_splitter_saved_sizes,
)


def test_research_main_splitter_sizes_keep_details_visible() -> None:
    assert research_main_splitter_default_sizes(320) == [1296, 504]
    assert research_main_splitter_responsive_sizes(1000, 320) == [680, 320]
    assert research_main_splitter_saved_sizes(1000, [900, 100], 320) == [680, 320]


def test_research_group_and_unknown_splitter_sizes_scale_from_content_width() -> None:
    assert research_groups_splitter_default_sizes() == [607, 773]
    assert research_groups_splitter_responsive_sizes(1000) == [420, 500]
    assert research_groups_splitter_saved_sizes(1000, [100, 900]) == [420, 500]

    assert research_unknown_splitter_default_sizes() == [605, 1015, 540]
    assert research_unknown_splitter_responsive_sizes(1000) == [300, 360, 260]
    assert research_unknown_splitter_saved_sizes(1000, [50, 900, 50]) == [300, 360, 260]


def test_research_reference_archive_analysis_and_notes_splitters_keep_minimums() -> None:
    assert research_reference_splitter_default_sizes() == [801, 739]
    assert research_reference_splitter_responsive_sizes(1000) == [499, 461]
    assert research_reference_splitter_saved_sizes(1000, [50, 950]) == [420, 540]

    assert research_archive_picker_splitter_default_sizes() == [660, 540]

    assert research_analysis_splitter_default_sizes() == [557, 557, 626]
    assert research_analysis_splitter_responsive_sizes(1000) == [294, 294, 332]
    assert research_analysis_splitter_saved_sizes(1000, [50, 50, 900]) == [280, 280, 360]

    assert research_notes_splitter_default_sizes() == [728, 672]
    assert research_notes_splitter_responsive_sizes(1000) == [478, 442]
    assert research_notes_splitter_saved_sizes(1000, [50, 950]) == [320, 600]
