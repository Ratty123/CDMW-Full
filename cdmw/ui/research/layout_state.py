"""Splitter layout state rules for the Research tab."""

from __future__ import annotations

from typing import Sequence

from cdmw.ui.layout_utils import (
    build_bounded_splitter_sizes,
    build_responsive_splitter_sizes,
    clamp_splitter_sizes,
)

__all__ = [
    "research_analysis_splitter_default_sizes",
    "research_analysis_splitter_responsive_sizes",
    "research_analysis_splitter_saved_sizes",
    "research_archive_picker_splitter_default_sizes",
    "research_groups_splitter_default_sizes",
    "research_groups_splitter_responsive_sizes",
    "research_groups_splitter_saved_sizes",
    "research_main_splitter_default_sizes",
    "research_main_splitter_responsive_sizes",
    "research_main_splitter_saved_sizes",
    "research_notes_splitter_default_sizes",
    "research_notes_splitter_responsive_sizes",
    "research_notes_splitter_saved_sizes",
    "research_reference_splitter_default_sizes",
    "research_reference_splitter_responsive_sizes",
    "research_reference_splitter_saved_sizes",
    "research_unknown_splitter_default_sizes",
    "research_unknown_splitter_responsive_sizes",
    "research_unknown_splitter_saved_sizes",
]


def _effective_width(total_width: int, offset: int) -> int:
    return max(1, int(total_width) - offset)


def research_main_splitter_default_sizes(details_min: int) -> list[int]:
    return build_bounded_splitter_sizes(1800, [72, 28], [420, details_min], [None, None])


def research_main_splitter_responsive_sizes(total_width: int, details_min: int) -> list[int]:
    return build_bounded_splitter_sizes(total_width, [72, 28], [420, details_min], [None, None])


def research_main_splitter_saved_sizes(
    total_width: int,
    sizes: Sequence[int],
    details_min: int,
) -> list[int]:
    return build_bounded_splitter_sizes(total_width, sizes, [420, details_min], [None, None])


def research_groups_splitter_default_sizes() -> list[int]:
    return build_responsive_splitter_sizes(1380, [44, 56], [520, 360])


def research_groups_splitter_responsive_sizes(total_width: int) -> list[int]:
    return build_responsive_splitter_sizes(_effective_width(total_width, 80), [44, 56], [420, 320])


def research_groups_splitter_saved_sizes(total_width: int, sizes: Sequence[int]) -> list[int]:
    return clamp_splitter_sizes(_effective_width(total_width, 80), sizes, [420, 320], fallback_weights=[44, 56])


def research_unknown_splitter_default_sizes() -> list[int]:
    return build_responsive_splitter_sizes(2160, [28, 47, 25], [360, 400, 300])


def research_unknown_splitter_responsive_sizes(total_width: int) -> list[int]:
    return build_responsive_splitter_sizes(_effective_width(total_width, 80), [28, 47, 25], [300, 360, 260])


def research_unknown_splitter_saved_sizes(total_width: int, sizes: Sequence[int]) -> list[int]:
    return clamp_splitter_sizes(
        _effective_width(total_width, 80),
        sizes,
        [300, 360, 260],
        fallback_weights=[28, 47, 25],
    )


def research_reference_splitter_default_sizes() -> list[int]:
    return build_responsive_splitter_sizes(1540, [52, 48], [520, 360])


def research_reference_splitter_responsive_sizes(total_width: int) -> list[int]:
    return build_responsive_splitter_sizes(_effective_width(total_width, 40), [52, 48], [420, 320])


def research_reference_splitter_saved_sizes(total_width: int, sizes: Sequence[int]) -> list[int]:
    return clamp_splitter_sizes(_effective_width(total_width, 40), sizes, [420, 320], fallback_weights=[52, 48])


def research_archive_picker_splitter_default_sizes() -> list[int]:
    return build_responsive_splitter_sizes(1200, [55, 45], [360, 300])


def research_analysis_splitter_default_sizes() -> list[int]:
    return build_responsive_splitter_sizes(1740, [32, 32, 36], [320, 320, 360])


def research_analysis_splitter_responsive_sizes(total_width: int) -> list[int]:
    return build_responsive_splitter_sizes(_effective_width(total_width, 80), [32, 32, 36], [280, 280, 320])


def research_analysis_splitter_saved_sizes(total_width: int, sizes: Sequence[int]) -> list[int]:
    return clamp_splitter_sizes(
        _effective_width(total_width, 80),
        sizes,
        [280, 280, 320],
        fallback_weights=[32, 32, 36],
    )


def research_notes_splitter_default_sizes() -> list[int]:
    return build_responsive_splitter_sizes(1400, [52, 48], [360, 360])


def research_notes_splitter_responsive_sizes(total_width: int) -> list[int]:
    return build_responsive_splitter_sizes(_effective_width(total_width, 80), [52, 48], [320, 320])


def research_notes_splitter_saved_sizes(total_width: int, sizes: Sequence[int]) -> list[int]:
    return clamp_splitter_sizes(_effective_width(total_width, 80), sizes, [320, 320], fallback_weights=[52, 48])
