"""The P0 targets as budgets, each with the milestone from which it is enforced.

This mirrors the targets table under P0 in the plan. A budget fails only
when the median of five fresh runs is over its target and it is enforced:
its milestone is done, or it was already met when it was written (so it
cannot regress). Before that it is measured and printed only.
"""
from __future__ import annotations

from dataclasses import dataclass

MILESTONES = ("P3", "P4 V4", "P4 V5", "P9")
#: The last milestone finished. Moving it forward enforces more budgets.
CURRENT_MILESTONE = "P3"


@dataclass(frozen=True)
class Budget:
    name: str
    target_s: float
    enforced_from: str
    met_when_written: bool = False

    @property
    def enforced(self) -> bool:
        return self.met_when_written or MILESTONES.index(self.enforced_from) <= MILESTONES.index(CURRENT_MILESTONE)


# Next's figures behind the "within 1.5 times Next" row: 0.79, 1.22, 2.41, 0.96 s.
BUDGETS = {
    "first_view_textured/sword": Budget("first_view_textured/sword", 1.6, "P3"),
    "first_view_textured/upper": Budget("first_view_textured/upper", 2.5, "P3"),
    "first_view_textured/set": Budget("first_view_textured/set", 5.0, "P3"),
    "first_view_textured/wyvern": Budget("first_view_textured/wyvern", 2.0, "P3", met_when_written=True),
    "warm_reselection/sword": Budget("warm_reselection/sword", 0.5, "P3", met_when_written=True),
    "warm_reselection/upper": Budget("warm_reselection/upper", 0.5, "P3"),
    "warm_reselection/set": Budget("warm_reselection/set", 0.5, "P3"),
    "warm_reselection/wyvern": Budget("warm_reselection/wyvern", 0.5, "P3", met_when_written=True),
    "cached_textured/sword": Budget("cached_textured/sword", 1.0, "P3", met_when_written=True),
    "cached_textured/upper": Budget("cached_textured/upper", 1.83, "P3", met_when_written=True),
    "cached_textured/set": Budget("cached_textured/set", 3.62, "P3", met_when_written=True),
    "cached_textured/wyvern": Budget("cached_textured/wyvern", 1.44, "P3", met_when_written=True),
    "editor_ready/sword": Budget("editor_ready/sword", 2.5, "P4 V4"),
    "editor_ready/upper": Budget("editor_ready/upper", 2.5, "P4 V4"),
    "editor_ready/set": Budget("editor_ready/set", 5.0, "P4 V4"),
    "startup_usable": Budget("startup_usable", 3.0, "P9"),
    "processes_with_editor": Budget("processes_with_editor", 5, "P4 V5"),
    "working_set_gib_with_editor": Budget("working_set_gib_with_editor", 1.5, "P4 V5"),
}
