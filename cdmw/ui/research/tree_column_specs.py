"""Tree column auto-fit specifications for the Research tab."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

__all__ = [
    "ResearchTreeColumnSpec",
    "research_tree_column_specs",
]


@dataclass(frozen=True, slots=True)
class ResearchTreeColumnSpec:
    tree_attr: str
    storage_name: str
    stretch_column: int
    min_widths: Mapping[int, int]


_RESEARCH_TREE_COLUMN_SPECS = (
    ResearchTreeColumnSpec("archive_picker_tree", "archive_picker", 0, MappingProxyType({0: 260, 1: 90, 2: 110})),
    ResearchTreeColumnSpec("texture_group_tree", "texture_group", 0, MappingProxyType({0: 280, 1: 86, 2: 150, 3: 120})),
    ResearchTreeColumnSpec("classifier_tree", "classifier", 0, MappingProxyType({0: 280, 1: 110, 2: 90, 3: 120, 4: 220})),
    ResearchTreeColumnSpec("unknown_group_tree", "unknown_group", 0, MappingProxyType({0: 280, 1: 180, 2: 120, 3: 120})),
    ResearchTreeColumnSpec("unknown_member_tree", "unknown_member", 0, MappingProxyType({0: 260, 1: 90, 2: 110, 3: 90, 4: 110, 5: 220})),
    ResearchTreeColumnSpec("reference_tree", "reference", 0, MappingProxyType({0: 260, 1: 220, 2: 90, 3: 180, 4: 80, 5: 110})),
    ResearchTreeColumnSpec("sidecar_tree", "sidecar", 0, MappingProxyType({0: 280, 1: 140, 2: 90, 3: 110, 4: 180})),
    ResearchTreeColumnSpec("ui_constraint_tree", "ui_constraint", 0, MappingProxyType({0: 260, 1: 220, 2: 90, 3: 90, 4: 180})),
    ResearchTreeColumnSpec("heatmap_tree", "heatmap", 0, MappingProxyType({0: 300, 1: 120, 2: 110, 3: 110, 4: 110, 5: 110})),
    ResearchTreeColumnSpec("mip_tree", "mip", 0, MappingProxyType({0: 280, 1: 120, 2: 120, 3: 80, 4: 200})),
    ResearchTreeColumnSpec("normal_tree", "normal", 0, MappingProxyType({0: 280, 1: 120, 2: 110, 3: 90, 4: 220})),
    ResearchTreeColumnSpec("budget_file_tree", "budget_file", 0, MappingProxyType({0: 280, 1: 100, 2: 80, 3: 120, 4: 100, 5: 80})),
    ResearchTreeColumnSpec("budget_class_tree", "budget_class", 0, MappingProxyType({0: 180, 1: 90, 2: 110, 3: 90, 4: 100})),
    ResearchTreeColumnSpec("budget_group_tree", "budget_group", 0, MappingProxyType({0: 240, 1: 90, 2: 110, 3: 90, 4: 80, 5: 100})),
    ResearchTreeColumnSpec("budget_profile_tree", "budget_profile", 0, MappingProxyType({0: 180, 1: 110, 2: 90, 3: 90, 4: 90})),
    ResearchTreeColumnSpec("notes_tree", "notes", 0, MappingProxyType({0: 280, 1: 160, 2: 160, 3: 120})),
)


def research_tree_column_specs() -> tuple[ResearchTreeColumnSpec, ...]:
    return _RESEARCH_TREE_COLUMN_SPECS
