"""Source-mixing presentation helpers for static replacement."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceMixPresentation:
    text: str
    tooltip: str = ""


def alignment_source_mix_control_text() -> dict[str, str]:
    return {
        "group_title": "Source Mixing",
        "tray_tooltip": (
            "Archive and .pamt/.paz mesh sources reopen this target through the in-game swap path. "
            "Loose folders can add supplemental textures and sidecars."
        ),
        "hint": "Add alternate sources without leaving this dialog.",
        "add_archive": "Add Archive Source",
        "add_archive_tooltip": (
            "Choose another loaded archive mesh as the source and reopen this target through the existing in-game swap flow."
        ),
        "add_loose": "Add Loose Mod Folder",
        "add_loose_tooltip": (
            "Choose a loose mod folder. Local DDS/material sidecars are still added from Mesh Replacement Setup before this alignment review."
        ),
        "add_mod_archive": "Add .pamt/.paz Mod",
        "add_mod_archive_tooltip": (
            "Choose a .pamt/.paz mod archive and use one of its mesh entries as the replacement source through the existing swap flow."
        ),
        "archive_source_prompt": "Search archive source by name, path, package, or role",
        "loose_source_prompt": "Search loose mesh source by name, path, or role",
        "mod_archive_source_prompt": "Search mod archive mesh source by name, path, or role",
        "use_loose_mesh_title": "Use Loose Mesh Source",
        "use_mod_archive_mesh_title": "Use Mod Archive Mesh Source",
        "loose_added_title": "Loose Source Added",
        "loose_source_label_prefix": "Loose mod source: ",
        "loose_placement_review_title": "Loose Mesh Source Placement",
        "loose_placement_context_note": (
            "This source came from a loose mod folder. Review offset, rotation, scale, "
            "part mapping, and texture sidecar output before export."
        ),
        "mod_archive_file_filter": "Archive Mod Sources (*.pamt *.paz);;All Files (*.*)",
        "no_loaded_archive_sources": "No other loaded archive mesh sources are available.",
        "no_mod_archive_mesh_entries": "The selected mod archive did not contain mesh entries.",
    }


def alignment_source_mix_current_status(source_path: object) -> SourceMixPresentation:
    status_text = str(source_path) if source_path else "replacement source"
    display_text = Path(status_text).name if source_path else status_text
    return SourceMixPresentation(text=f"Current: {display_text}", tooltip=status_text)


def alignment_source_mix_parity_presentation(*, modify_original_clone_mode: bool) -> SourceMixPresentation:
    if modify_original_clone_mode:
        return SourceMixPresentation(
            text="Geometry same | Materials same | Render settings same | Camera synced",
            tooltip=(
                "Modify Original starts as a no-op clone. Selection highlight preserves texture bindings and uses overlay color only."
            ),
        )
    return SourceMixPresentation(
        text="Roundtrip import diagnostic mode can show OBJ/material differences separately.",
        tooltip=(
            "Modify Original starts as a no-op clone. Selection highlight preserves texture bindings and uses overlay color only."
        ),
    )


def alignment_source_mix_reopening_archive_status(source_path: object) -> str:
    return f"Reopening with archive source: {source_path}"


def alignment_source_mix_reopening_loose_status(source_path: object) -> str:
    return f"Reopening with loose mesh source: {source_path}"


def alignment_source_mix_reopening_mod_archive_status(source_path: object) -> str:
    return f"Reopening with mod archive source: {source_path}"


def alignment_source_mix_loose_scan_status(
    selected_dir: object,
    *,
    mesh_count: int,
    supplemental_count: int,
) -> str:
    return (
        f"Loose source scanned: {Path(str(selected_dir)).name} | {mesh_count:,} mesh candidate(s), "
        f"{supplemental_count:,} texture/sidecar candidate(s)."
    )


def alignment_source_mix_loose_added_message(
    selected_dir: object,
    *,
    mesh_count: int,
    supplemental_count: int,
) -> str:
    return (
        f"Scanned {selected_dir}\n\n"
        f"Mesh candidates: {mesh_count:,}\n"
        f"Texture/sidecar candidates: {supplemental_count:,}\n\n"
        "For this v1 alignment window, local texture/sidecar files are added from Mesh Replacement Setup before placement review. "
        "Use Add Archive Source or Add .pamt/.paz Mod here when you want to switch the geometry source."
    )


__all__ = [
    "SourceMixPresentation",
    "alignment_source_mix_control_text",
    "alignment_source_mix_current_status",
    "alignment_source_mix_loose_added_message",
    "alignment_source_mix_loose_scan_status",
    "alignment_source_mix_parity_presentation",
    "alignment_source_mix_reopening_archive_status",
    "alignment_source_mix_reopening_loose_status",
    "alignment_source_mix_reopening_mod_archive_status",
]
