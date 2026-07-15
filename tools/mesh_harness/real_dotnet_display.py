from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from types import SimpleNamespace

from tools.mesh_harness.real_dotnet_material import (
    _write_material_visual_diff,
    renderer_resource_metrics,
)


_DISPLAY_MODES = (
    ("untextured_faces", "real_archive_dotnet_untextured_faces.png"),
    ("wire_vertices", "real_archive_dotnet_wire_vertices.png"),
    ("vertices", "real_archive_dotnet_vertices.png"),
    ("textured", "real_archive_dotnet_textured_restored.png"),
)
_DISPLAY_MODE_LABELS = {
    "textured": "Solid (Textured)",
    "untextured_faces": "Faces (No Textures)",
    "wire_vertices": "Wire + Vertices",
    "vertices": "Vertices",
}
_REQUIRED_PRODUCTION_DISPLAY_MODES = frozenset({"textured", "untextured_faces", "vertices"})


def _image_color_metrics(path: Path) -> dict[str, object]:
    from PIL import Image

    with Image.open(path) as source:
        image = source.convert("RGB")
        width, height = image.size
        pixels = image.load()
        stride = max(1, int((width * height / 50_000) ** 0.5))
        foreground_luma: list[float] = []
        colors: set[tuple[int, int, int]] = set()
        sampled = 0
        for y in range(0, height, stride):
            for x in range(0, width, stride):
                red, green, blue = pixels[x, y]
                sampled += 1
                colors.add((red, green, blue))
                if abs(red - 18) + abs(green - 20) + abs(blue - 25) <= 36:
                    continue
                foreground_luma.append(0.2126 * red + 0.7152 * green + 0.0722 * blue)
    foreground = len(foreground_luma)
    mean_luma = sum(foreground_luma) / foreground if foreground else 0.0
    bright_fraction = (
        sum(value >= 32.0 for value in foreground_luma) / foreground if foreground else 0.0
    )
    return {
        "sampled_pixels": sampled,
        "foreground_samples": foreground,
        "foreground_ratio": foreground / sampled if sampled else 0.0,
        "foreground_mean_luma": mean_luma,
        "foreground_bright_fraction": bright_fraction,
        "unique_color_count": len(colors),
        "non_black_geometry": bool(foreground >= 64 and mean_luma >= 32.0 and bright_fraction >= 0.35),
    }


def _renderer_from_event(event: Mapping[str, object]) -> dict[str, object]:
    renderer = event.get("renderer")
    return dict(renderer) if isinstance(renderer, Mapping) else {}


def _mode_event(
    state: SimpleNamespace,
    cursor: int,
    pump_until: Callable[..., bool],
) -> dict[str, object]:
    found: dict[str, object] = {}

    def locate() -> bool:
        nonlocal found
        for event in tuple(state.tab.standalone_dotnet_protocol_events)[cursor:]:
            if str(event.get("event", "")) in {
                "viewport_display_applied",
                "viewport_display_failed",
            }:
                found = dict(event)
                return True
        return False

    pump_until(state, locate, 3.0)
    return found


def _presentation_event(
    state: SimpleNamespace,
    cursor: int,
    pump_until: Callable[..., bool],
) -> dict[str, object]:
    found: dict[str, object] = {}

    def locate() -> bool:
        nonlocal found
        for event in tuple(state.tab.standalone_dotnet_protocol_events)[cursor:]:
            if str(event.get("event", "")) == "presentation_state_update_ack":
                found = dict(event)
                return True
        return False

    pump_until(state, locate, 4.0)
    return found


def _builder_presentation_payloads() -> tuple[dict[str, object], dict[str, object]]:
    baseline_quality = {
        "use_textures_by_default": True,
        "high_quality_by_default": True,
        "disable_lighting": False,
        "disable_depth_test": False,
        "disable_tint": False,
        "disable_brightness": True,
        "disable_uv_scale": False,
        "disable_normal_map": False,
        "disable_material_map": False,
        "disable_height_map": False,
        "disable_all_support_maps": False,
        "force_nearest_no_mipmaps": False,
        "d3d11_cull_back_faces": False,
        "d3d11_light_azimuth_degrees": -10.0,
        "d3d11_light_elevation_degrees": 0.0,
        "d3d11_normal_y_mode": "asset",
        "d3d11_ao_strength": 0.45,
        "d3d11_roughness_bias": -0.04,
        "d3d11_metalness_scale": 1.45,
        "d3d11_environment_strength": 0.62,
        "d3d11_emissive_gain": 2.2,
        "d3d11_tone_exposure": 1.0,
        "d3d11_tone_contrast": 1.08,
        "d3d11_tone_gamma": 1.0,
        "d3d11_texture_address_mode": "wrap",
        "max_anisotropy": 16,
        "d3d11_mip_lod_bias": -2.0,
        "ambient_strength": 0.84,
        "diffuse_wrap_bias": 0.58,
        "diffuse_light_scale": 0.62,
        "normal_strength_cap": 1.0,
        "height_effect_max": 1.0,
        "specular_max": 0.52,
        "shininess_max": 152.0,
    }
    baseline = {
        "active_view": "editable",
        "comparison_mode": "replacement_only",
        "display": {
            "mode": "textured",
            "material_debug_mode": 0,
            "grid_visible": True,
            "gizmo_visible": True,
            "part_pick_enabled": False,
            "quality": baseline_quality,
        },
        "uv": {
            "scale_u": 1.0,
            "scale_v": 1.0,
            "offset_u": 0.0,
            "offset_v": 0.0,
            "rotate_degrees": 0.0,
            "flip_u": False,
            "flip_v": False,
        },
    }
    tuned = {
        **baseline,
        "display": {
            **baseline["display"],
            "quality": {
                **baseline_quality,
                "disable_lighting": True,
                "d3d11_normal_y_mode": "force_flip",
                "d3d11_tone_exposure": 0.35,
                "d3d11_tone_contrast": 1.45,
                "d3d11_texture_address_mode": "clamp",
                "max_anisotropy": 4,
                "height_effect_max": 0.25,
                "specular_max": 0.2,
                "shininess_max": 72.0,
            },
        },
        "uv": {
            "scale_u": 1.75,
            "scale_v": 0.8,
            "offset_u": 0.13,
            "offset_v": -0.08,
            "rotate_degrees": 22.0,
            "flip_u": True,
            "flip_v": False,
        },
    }
    return baseline, tuned


def exercise_builder_presentation_controls(
    state: SimpleNamespace,
    *,
    pump_until: Callable[..., bool],
    capture_viewport: Callable[[SimpleNamespace, Path], dict[str, object]],
) -> str:
    """Prove resident Builder quality/lighting/UV controls change real pixels in place."""

    baseline, tuned = _builder_presentation_payloads()
    lifecycle_before = dict(state.tab.standalone_dotnet_lifecycle_counts)
    process_before = int(state.tab.standalone_dotnet_editor_process.processId())
    rows: list[dict[str, object]] = []
    for name, payload in (("baseline", baseline), ("tuned", tuned), ("restored", baseline)):
        cursor = len(state.tab.standalone_dotnet_protocol_events)
        sent = bool(state.tab._send_dotnet_presentation_state(payload))
        acknowledgement = _presentation_event(state, cursor, pump_until) if sent else {}
        capture_path = state.output_dir / f"real_archive_dotnet_presentation_{name}.png"
        capture = capture_viewport(state, capture_path) if acknowledgement.get("status") == "applied" else {}
        rows.append(
            {
                "name": name,
                "sent": sent,
                "acknowledgement": acknowledgement,
                "capture_path": str(capture_path),
                "capture": capture,
            }
        )
        if acknowledgement.get("status") != "applied" or not capture.get("ok"):
            return f"Resident Builder presentation state {name!r} was not rendered and acknowledged."

    diff_path = state.output_dir / "real_archive_dotnet_presentation_diff.png"
    visual_diff = _write_material_visual_diff(
        Path(str(rows[0]["capture_path"])),
        Path(str(rows[1]["capture_path"])),
        diff_path,
    )
    tuned_presentation = rows[1]["acknowledgement"].get("presentation", {})
    tuned_presentation = dict(tuned_presentation) if isinstance(tuned_presentation, Mapping) else {}
    quality_state = tuned_presentation.get("quality_state", {})
    quality_state = dict(quality_state) if isinstance(quality_state, Mapping) else {}
    uv_state = tuned_presentation.get("uv_state", {})
    uv_state = dict(uv_state) if isinstance(uv_state, Mapping) else {}
    lifecycle_after = dict(state.tab.standalone_dotnet_lifecycle_counts)
    process_after = int(state.tab.standalone_dotnet_editor_process.processId())
    baseline_renderer = _renderer_from_event(rows[0]["acknowledgement"])
    restored_renderer = _renderer_from_event(rows[2]["acknowledgement"])
    baseline_resources = renderer_resource_metrics(baseline_renderer)
    restored_resources = renderer_resource_metrics(restored_renderer)
    stable_resource_keys = (
        "geometry_buffer_identity",
        "texture_srv_creates",
        "texture_srv_disposals",
        "live_texture_srvs",
        "material_binding_array_creates",
    )
    gates = {
        "all_states_acknowledged_and_captured": all(
            row["acknowledgement"].get("status") == "applied" and row["capture"].get("ok")
            for row in rows
        ),
        "quality_and_uv_changed_pixels": bool(visual_diff.get("ok")),
        "quality_state_applied": bool(
            quality_state.get("disable_lighting") is True
            and quality_state.get("normal_y_mode") == "force_flip"
            and abs(float(quality_state.get("tone_exposure", 0.0) or 0.0) - 0.35) < 1e-6
            and quality_state.get("texture_address_mode") == "clamp"
        ),
        "uv_state_applied": bool(
            tuple(float(value) for value in tuple(uv_state.get("scale", ()))) == (1.75, 0.8)
            and bool(uv_state.get("flip_u"))
        ),
        "process_and_package_unchanged": bool(
            process_before == process_after and lifecycle_before == lifecycle_after
        ),
        "resident_resources_unchanged": all(
            baseline_resources.get(key) == restored_resources.get(key) for key in stable_resource_keys
        ),
    }
    state.builder_presentation_evidence = {
        "schema": "cdmw_real_pac_builder_presentation_v1",
        "states": rows,
        "visual_diff": visual_diff,
        "visual_diff_path": str(diff_path),
        "lifecycle_before": lifecycle_before,
        "lifecycle_after": lifecycle_after,
        "process_before": process_before,
        "process_after": process_after,
        "baseline_resource_metrics": baseline_resources,
        "restored_resource_metrics": restored_resources,
        "gates": gates,
        "ok": all(gates.values()),
    }
    return "" if state.builder_presentation_evidence["ok"] else "Resident Builder presentation validation failed."


def _rendered_mode_metrics(
    state: SimpleNamespace,
    cursor: int,
    mode: str,
    counter_floors: Mapping[str, int],
    pump_until: Callable[..., bool],
) -> dict[str, object]:
    found: dict[str, object] = {}

    def locate() -> bool:
        nonlocal found
        for event in tuple(state.tab.standalone_dotnet_protocol_events)[cursor:]:
            if str(event.get("event", "")) != "metrics":
                continue
            renderer = _renderer_from_event(event)
            resources = renderer_resource_metrics(renderer)
            if str(renderer.get("display_mode", "")) != mode:
                continue
            if any(int(resources.get(key, 0) or 0) <= floor for key, floor in counter_floors.items()):
                continue
            found = dict(event)
            return True
        return False

    pump_until(state, locate, 3.0)
    return found


def exercise_geometry_display_modes(
    state: SimpleNamespace,
    *,
    pump_until: Callable[..., bool],
    capture_viewport: Callable[[SimpleNamespace, Path], dict[str, object]],
) -> str:
    current_renderer = _renderer_from_event(getattr(state, "material_state_applied", {})) or dict(
        state.renderer
    )
    initial_resources = renderer_resource_metrics(current_renderer)
    initial_decode = {
        key: int(current_renderer.get(key, 0) or 0)
        for key in (
            "texture_decode_attempts",
            "texture_decode_successes",
            "texture_decode_reuses",
            "incremental_texture_decodes",
        )
    }
    lifecycle_before = dict(state.tab.standalone_dotnet_lifecycle_counts)
    rows: list[dict[str, object]] = []
    expected_flags = {
        "untextured_faces": (True, False, False, False),
        "wire_vertices": (False, True, True, False),
        "vertices": (False, False, True, False),
        "textured": (True, False, False, True),
    }
    counter_keys = {
        "untextured_faces": ("untextured_solid_batch_draws",),
        "wire_vertices": ("wire_overlay_draws", "vertex_overlay_batch_draws"),
        "vertices": ("vertex_overlay_batch_draws",),
        "textured": ("textured_solid_batch_draws",),
    }

    for mode, filename in _DISPLAY_MODES:
        before_resources = renderer_resource_metrics(current_renderer)
        cursor = len(state.tab.standalone_dotnet_protocol_events)
        sent = state.tab._send_dotnet_protocol_message(
            {
                "event": "viewport_display_update",
                "session_id": state.controller.active_session_id,
                "mode": mode,
            }
        )
        acknowledgement = _mode_event(state, cursor, pump_until) if sent else {}
        if acknowledgement.get("event") != "viewport_display_applied":
            reason = str(acknowledgement.get("message", acknowledgement.get("reason", "")) or "")
            return f".NET/Vortice viewport display mode {mode!r} was rejected: {reason}"
        metrics_cursor = len(state.tab.standalone_dotnet_protocol_events)
        capture_path = state.output_dir / filename
        capture = capture_viewport(state, capture_path)
        floors = {key: int(before_resources.get(key, 0) or 0) for key in counter_keys[mode]}
        rendered = _rendered_mode_metrics(state, metrics_cursor, mode, floors, pump_until)
        renderer = _renderer_from_event(rendered) or _renderer_from_event(acknowledgement)
        resources = renderer_resource_metrics(renderer)
        show_solid, show_wire, show_vertices, textures_enabled = expected_flags[mode]
        flags_ok = bool(
            acknowledgement.get("mode") == mode
            and acknowledgement.get("show_solid") is show_solid
            and acknowledgement.get("show_wire") is show_wire
            and acknowledgement.get("show_vertices") is show_vertices
            and acknowledgement.get("textures_enabled") is textures_enabled
        )
        color = _image_color_metrics(capture_path) if capture.get("ok") else {}
        row_ok = bool(
            flags_ok
            and capture.get("ok")
            and rendered
            and all(int(resources.get(key, 0) or 0) > floor for key, floor in floors.items())
            and (mode not in {"untextured_faces", "textured"} or color.get("non_black_geometry"))
        )
        rows.append(
            {
                "mode": mode,
                "label": _DISPLAY_MODE_LABELS[mode],
                "ok": row_ok,
                "acknowledgement": acknowledgement,
                "capture_path": str(capture_path),
                "capture": capture,
                "color": color,
                "renderer": renderer,
                "resource_metrics": resources,
            }
        )
        if not row_ok:
            return f".NET/Vortice viewport display mode {mode!r} did not render truthful real-PAC evidence."
        current_renderer = renderer

    final_resources = renderer_resource_metrics(current_renderer)
    final_decode = {
        key: int(current_renderer.get(key, 0) or 0) for key in initial_decode
    }
    rendered_modes = {str(row["mode"]) for row in rows if row["ok"]}
    stable_resource_keys = (
        "texture_srv_creates",
        "texture_srv_disposals",
        "live_texture_srvs",
        "material_binding_array_creates",
        "geometry_buffer_identity",
    )
    gates = {
        "all_modes_rendered": len(rows) == len(_DISPLAY_MODES) and all(row["ok"] for row in rows),
        "required_production_modes_rendered": _REQUIRED_PRODUCTION_DISPLAY_MODES <= rendered_modes,
        "textured_restored": bool(rows and rows[-1]["mode"] == "textured"),
        "texture_decode_unchanged": initial_decode == final_decode,
        "texture_resources_unchanged": all(
            initial_resources.get(key) == final_resources.get(key) for key in stable_resource_keys
        ),
        "process_and_package_unchanged": lifecycle_before == dict(
            state.tab.standalone_dotnet_lifecycle_counts
        ),
    }
    state.geometry_display_evidence = {
        "schema": "cdmw_real_pac_geometry_display_v1",
        "modes": rows,
        "initial_resource_metrics": initial_resources,
        "final_resource_metrics": final_resources,
        "initial_decode_metrics": initial_decode,
        "final_decode_metrics": final_decode,
        "lifecycle_before": lifecycle_before,
        "lifecycle_after": dict(state.tab.standalone_dotnet_lifecycle_counts),
        "gates": gates,
        "ok": all(gates.values()),
    }
    return "" if state.geometry_display_evidence["ok"] else "Real-PAC geometry display validation failed."


__all__ = [
    "_image_color_metrics",
    "exercise_builder_presentation_controls",
    "exercise_geometry_display_modes",
]
