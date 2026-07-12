from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from types import SimpleNamespace

from tools.mesh_harness.real_dotnet_material import renderer_resource_metrics


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


__all__ = ["_image_color_metrics", "exercise_geometry_display_modes"]
