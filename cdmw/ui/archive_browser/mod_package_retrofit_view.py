"""Compatibility wrapper for Retrofit/Repackage view helpers."""

from __future__ import annotations

from cdmw.ui.tools.mod_package_retrofit_view import (
    build_retrofit_processing_results_html,
    build_retrofit_update_plan_html,
    collect_retrofittable_packages,
    next_available_retrofit_package_name,
    retrofit_game_build_from_root,
    retrofit_readiness_for_summary,
    retrofit_readiness_label_for_summary,
    retrofit_scan_readiness_summary,
    retrofit_selection_readiness_summary,
)

__all__ = [
    "build_retrofit_processing_results_html",
    "build_retrofit_update_plan_html",
    "collect_retrofittable_packages",
    "next_available_retrofit_package_name",
    "retrofit_game_build_from_root",
    "retrofit_readiness_for_summary",
    "retrofit_readiness_label_for_summary",
    "retrofit_scan_readiness_summary",
    "retrofit_selection_readiness_summary",
]
