"""Preview status presentation helpers for static replacement."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreviewPerformanceStatus:
    text: str
    tooltip: str


@dataclass(frozen=True)
class PreviewHelpPresentation:
    text: str
    tooltip: str
    settings_tooltip: str


def alignment_preview_camera_button_specs() -> tuple[tuple[str, str, str], ...]:
    return (
        (
            "Front",
            "MeshAlignmentCameraFrontButton",
            "Frame the replacement from the front. This moves only the preview camera.",
        ),
        (
            "Left",
            "MeshAlignmentCameraLeftButton",
            "Frame the replacement from the left side. This moves only the preview camera.",
        ),
        (
            "Right",
            "MeshAlignmentCameraRightButton",
            "Frame the replacement from the right side. This moves only the preview camera.",
        ),
        (
            "Back",
            "MeshAlignmentCameraBackButton",
            "Frame the replacement from the back. This moves only the preview camera.",
        ),
        (
            "Top",
            "MeshAlignmentCameraTopButton",
            "Frame the replacement from above. This moves only the preview camera.",
        ),
        (
            "Bottom",
            "MeshAlignmentCameraBottomButton",
            "Frame the replacement from below. This moves only the preview camera.",
        ),
        (
            "-15",
            "MeshAlignmentCameraYawLeftButton",
            "Rotate the preview camera left by 15 degrees without changing export transforms.",
        ),
        (
            "+15",
            "MeshAlignmentCameraYawRightButton",
            "Rotate the preview camera right by 15 degrees without changing export transforms.",
        ),
        (
            "Reset/Fit",
            "MeshAlignmentCameraResetFitButton",
            "Reset camera yaw, pitch, pan, and fit framing. This does not change the mesh.",
        ),
    )


def preview_grid_visible(checkbox: object) -> bool:
    """Read the one authoritative grid flag shared by both resident panes.

    Both panes have to be told the same thing in the same update; the resident
    renderer keeps a presentation context per pane and only writes the active
    one back, so anything less lets one pane keep a stale grid state.
    """
    is_checked = getattr(checkbox, "isChecked", None)
    if not callable(is_checked):
        return True
    try:
        return bool(is_checked())
    except RuntimeError:
        return True


def alignment_preview_control_text() -> dict[str, str]:
    return {
        "title": "Live Alignment Preview",
        "clear_selection": "Clear Selection",
        "clear_selection_tooltip": (
            "Clear current part/material selections and preview highlights without changing routing, transforms, or texture assignments."
        ),
        "renderer_tooltip": "Local renderer for Mesh Replacement Alignment. This does not change the Archive Browser renderer.",
        "renderer_label": "Renderer",
        "renderer_scope": "Mesh Replacement Alignment renderer and texture controls are available from Preview Settings.",
        "preview_mode_tooltip": (
            "Side by side compares original and replacement. Overlay draws both in one view. "
            "Replacement only gives more room to inspect the imported asset."
        ),
        "preview_mode_label": "Preview mode",
        "overlay_original_locked": "Original locked",
        "overlay_original_locked_tooltip": (
            "In Overlay mode, keep the original reference fixed and move only the replacement preview."
        ),
        "grid": "Grid",
        "grid_tooltip": (
            "Show the ground grid in both preview panes. This is a display-only overlay and does not change the mesh, "
            "its placement, or anything that gets exported."
        ),
        "gizmo": "Gizmo",
        "gizmo_tooltip": (
            "Show move/rotate/scale handles in the placement preview. The Gizmo is hidden and inactive in Edit Mesh; customize its appearance in Preview Settings."
        ),
        "part_pick": "Part Pick",
        "part_pick_tooltip": (
            "In the .NET/Vortice preview, hover highlights source parts and right-click opens the selected part menu."
        ),
        "mesh_view_label": "Mesh view",
        "mesh_view_tooltip": (
            "Choose how the resident mesh geometry is drawn without reloading it. "
            "These are the same modes as Edit Mesh > Viewport; Faces + Wire is the readable default."
        ),
        "dotnet_view_tooltip": (
            ".NET/Vortice view mode for the resident Original and Replacement preview panes. "
            "Only renderer-backed modes are listed."
        ),
        "dotnet_view_label": ".NET view",
        "settings_button": "Preview Settings...",
        "use_global": "Use Global",
        "use_global_tooltip": "Reset the alignment render controls to the current global 3D preview settings.",
        "camera_label": "Camera",
        "d3d11_legend": "Drag axes/center to move; Alt-drag to rotate; wheel zooms.",
        "d3d11_legend_tooltip": (
            "Side by side: Original Reference is locked on the left; Replacement Preview is editable on the right. "
            "Controls: left-drag orbit, middle/right-drag pan, wheel zoom, drag axis/center move, Alt-drag rotate."
        ),
        "d3d11_waiting_status": ".NET/Vortice alignment preview is waiting for the resident renderer.",
        "d3d11_renderer_error": ".NET/Vortice renderer error.",
        "d3d11_unavailable_status": "Preview host is unavailable.",
        "d3d11_closed_status": "Preview closed.",
    }


def alignment_preview_render_control_text() -> dict[str, str]:
    return {
        "visible_label": "Visible",
        "visible_tooltip": "Texture-selection strategy for alignment preview rebuilds.",
        "render_label": "Render",
        "render_tooltip": "Render mode for the live alignment preview.",
        "disable_tint": "No tint",
        "disable_tint_tooltip": "Ignore sidecar tint in this alignment preview.",
        "disable_brightness": "No brightness",
        "disable_brightness_tooltip": "Ignore sidecar brightness multiplier in this alignment preview.",
        "disable_uv_scale": "No UV scale",
        "disable_uv_scale_tooltip": "Ignore sidecar UV scale in this alignment preview.",
        "support_maps": "Support maps",
        "support_maps_tooltip": "Enable resolved normal, material/mask, and height maps in the preview.",
        "depth_label": "Depth",
        "depth_tooltip": "Height/depth contribution for Lit and Height / Depth Response preview modes.",
        "shine_label": "Shine",
        "shine_tooltip": "Maximum material/metal shine contribution in Lit and Metal / Shine Response modes.",
        "rough_label": "Rough",
        "rough_tooltip": "Roughness contrast for highlight sharpness and Roughness Response diagnostics.",
        "original_reference_label": "Original Reference",
        "original_reference_description": "Original asset reference preview.",
        "original_reference_loading": "Original reference preview is loading...",
        "replacement_preview_label": "Replacement Preview",
        "replacement_preview_description": "Select texture slots to preview.",
        "replacement_preview_loading": "Replacement preview is loading...",
    }


def alignment_preview_help_presentation(*, d3d11_active: bool) -> PreviewHelpPresentation:
    if d3d11_active:
        return PreviewHelpPresentation(
            text="Resident .NET/Vortice alignment preview.",
            tooltip="Movement, rotation, part hover/selection, brush/vertex strokes, and view modes run through the resident .NET/Vortice renderer.",
            settings_tooltip=(
                "Open 3D preview settings supported by the .NET/Vortice renderer, including lighting, support maps, "
                "depth, shine, and resolution."
            ),
        )
    return PreviewHelpPresentation(
        text="Live preview. Build Mod validates final package paths during export.",
        tooltip=(
            "Replacement Preview is the candidate location/rotation/scale that will be written. "
            "Final loose export preview may differ if packaged material sidecar or DDS bindings resolve differently."
        ),
        settings_tooltip=(
            "Choose the Mesh Replacement Alignment renderer and adjust lighting, texture, support-map, and diagnostic controls."
        ),
    )


def alignment_d3d11_renderer_error_message(message: object) -> str:
    return str(message or "").strip() or alignment_preview_control_text()["d3d11_renderer_error"]


def alignment_preview_initial_performance_status() -> PreviewPerformanceStatus:
    return PreviewPerformanceStatus(
        text="Preview timing: waiting for first refresh.",
        tooltip="Live preview CPU rebuild, prepared-model, and texture upload timing.",
    )


def alignment_preview_view_sync_initial_state() -> dict[str, bool]:
    return {"active": False}


def preview_controls_ready_initial_state() -> dict[str, bool]:
    return {"ready": False}


def static_preview_refresh_interval_ms() -> int:
    return 140


def static_preview_settle_interval_ms() -> int:
    return 850


def _float_ms(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def preview_performance_status(summary: str, *, details: str = "") -> PreviewPerformanceStatus:
    text = str(summary or "").strip()
    tooltip = str(details or text or "Live preview status.").strip()
    return PreviewPerformanceStatus(text=text, tooltip=tooltip)


def static_preview_refresh_performance_status(
    *,
    quality_label: object,
    refresh_ms: object,
    geometry_ms: object,
    prepare_ms: object,
    upload_ms: object,
) -> PreviewPerformanceStatus:
    quality_text = str(quality_label or "").strip()
    refresh_elapsed_ms = _float_ms(refresh_ms)
    geometry_elapsed_ms = _float_ms(geometry_ms)
    prepare_elapsed_ms = _float_ms(prepare_ms)
    upload_elapsed_ms = _float_ms(upload_ms)
    return PreviewPerformanceStatus(
        text=f"Preview refreshed - {quality_text} - refresh {refresh_elapsed_ms:.0f} ms",
        tooltip=(
            f"refresh {refresh_elapsed_ms:.1f} ms\n"
            f"geometry {geometry_elapsed_ms:.1f} ms\n"
            f"prepare {prepare_elapsed_ms:.1f} ms\n"
            f"GL upload {upload_elapsed_ms:.1f} ms"
        ),
    )


__all__ = [
    "PreviewPerformanceStatus",
    "PreviewHelpPresentation",
    "alignment_d3d11_renderer_error_message",
    "alignment_preview_camera_button_specs",
    "alignment_preview_control_text",
    "alignment_preview_help_presentation",
    "alignment_preview_initial_performance_status",
    "alignment_preview_render_control_text",
    "alignment_preview_view_sync_initial_state",
    "preview_controls_ready_initial_state",
    "preview_grid_visible",
    "preview_performance_status",
    "static_preview_refresh_interval_ms",
    "static_preview_refresh_performance_status",
    "static_preview_settle_interval_ms",
]
