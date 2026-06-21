"""Static replacement startup progress state helpers."""

from __future__ import annotations

from collections.abc import MutableMapping


def alignment_startup_step_initial_state() -> dict[str, float]:
    return {"started_at": 0.0}


def alignment_startup_step_text() -> dict[str, str]:
    return {
        "initial_label": "Preparing Mesh Replacement Builder...",
        "window_title": "Preparing Alignment",
        "creating_window": "Creating alignment window...",
        "local_texture_lookup": "Preparing local texture lookup...",
        "alignment_summary": "Reading alignment summary...",
        "original_mesh": "Reading original mesh...",
        "material_sidecar": "Reading material sidecar...",
        "sidecar_texture_references": "Preparing sidecar texture references...",
        "asset_compatibility": "Analyzing asset compatibility...",
        "replacement_mesh": "Reading replacement mesh...",
        "preview_meshes": "Preparing preview meshes...",
        "draw_section_routing": "Suggesting draw-section routing...",
        "original_part_list": "Building original-part list...",
        "replacement_source_queue": "Queuing replacement-source list...",
        "routing_controls": "Preparing routing controls...",
        "geometry_controls": "Preparing geometry controls...",
        "replacement_texture_sources": "Preparing replacement texture sources...",
        "replacement_material_maps": "Detecting replacement material maps...",
        "advanced_dds_classification": "Classifying advanced DDS overrides...",
        "opening_builder": "Opening Mesh Replacement Builder...",
    }


def alignment_startup_original_part_list_progress_text(index: object) -> str:
    return f"Building original-part list... {index}"


def alignment_startup_texture_plan_progress_text(index: object) -> str:
    return f"Building texture plan... {index}"


def alignment_startup_advanced_dds_classification_progress_text(index: object) -> str:
    return f"Classifying advanced DDS overrides... {index}"


def alignment_startup_advanced_dds_guidance_progress_text(index: object) -> str:
    return f"Preparing advanced DDS guidance... {index}"


def alignment_startup_step_elapsed_ms(
    state: MutableMapping[str, object],
    now_s: float,
) -> int:
    previous = float(state.get("started_at", 0.0) or 0.0)
    now = float(now_s or 0.0)
    elapsed_ms = int(max(0.0, now - previous) * 1000) if previous > 0.0 else 0
    state["started_at"] = now
    return elapsed_ms


def alignment_startup_progress_initial_state() -> dict[str, bool]:
    return {"closed": False}


def alignment_startup_progress_closed(state: MutableMapping[str, object]) -> bool:
    return bool(state.get("closed"))


def alignment_startup_progress_mark_closed(state: MutableMapping[str, object]) -> bool:
    if alignment_startup_progress_closed(state):
        return False
    state["closed"] = True
    return True


__all__ = [
    "alignment_startup_progress_closed",
    "alignment_startup_progress_initial_state",
    "alignment_startup_progress_mark_closed",
    "alignment_startup_advanced_dds_classification_progress_text",
    "alignment_startup_advanced_dds_guidance_progress_text",
    "alignment_startup_original_part_list_progress_text",
    "alignment_startup_step_elapsed_ms",
    "alignment_startup_step_initial_state",
    "alignment_startup_step_text",
    "alignment_startup_texture_plan_progress_text",
]
