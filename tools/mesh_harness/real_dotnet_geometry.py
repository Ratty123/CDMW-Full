"""Keep the mesh proof's idea of the viewport in step with the real one.

The rectangle carried on the ready event describes the embedded editor window
before it is revealed and grown, and the window narrows again later in the run
while the swap chain is still presenting its wider frame. Anything that aims a
click or crops a screenshot has to say which of those moments it is working in,
so this module owns reading the current one and recording what it found.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Callable

from tools.mesh_harness.real_dotnet_material import request_full_renderer_status
from tools.mesh_harness.win32_input import _host_window_rect


def _rectangle(payload: Mapping[str, object]) -> dict[str, int]:
    return {
        "screen_x": int(payload.get("screen_x", 0) or 0),
        "screen_y": int(payload.get("screen_y", 0) or 0),
        "width": int(payload.get("width", 0) or 0),
        "height": int(payload.get("height", 0) or 0),
    }


def refresh_editable_viewport_rectangle(
    state: SimpleNamespace,
    pump_until: Callable[..., bool],
) -> dict[str, object]:
    """Replace the ready-event viewport snapshot with the renderer's live one.

    Both rectangles are editable-pane-local by contract -- the renderer publishes
    `screen_x`/`screen_y` as the pane's screen origin and `width`/`height` as the
    pane's size, precisely so that input and projection payloads agree with it --
    so this swaps a stale reading for a current one without changing what the
    numbers mean. The HWNDs are kept from the original because they identify the
    windows the harness already resolved and must not silently move.
    """

    status = request_full_renderer_status(state, pump_until)
    raw = status.get("viewport") if isinstance(status, Mapping) else None
    if not isinstance(raw, Mapping):
        return {"refreshed": False, "reason": "renderer published no viewport rectangle"}
    fresh = dict(raw)
    width = int(fresh.get("width", 0) or 0)
    height = int(fresh.get("height", 0) or 0)
    if width <= 0 or height <= 0:
        return {"refreshed": False, "reason": "renderer published an empty viewport rectangle"}
    hwnd = int(fresh.get("hwnd", 0) or 0)
    if hwnd and hwnd != int(state.viewport_hwnd or 0):
        return {"refreshed": False, "reason": "renderer published a different viewport window"}

    before = dict(state.viewport)
    fresh.setdefault("hwnd", before.get("hwnd"))
    fresh.setdefault("form_hwnd", before.get("form_hwnd"))
    state.viewport = fresh

    # Windows' answer for the very same handle, taken here rather than later: two
    # readings from different moments are what made a window that simply narrows
    # mid-run look twice like a renderer misreporting its own size.
    raw_audit = raw.get("geometry_audit")
    audit = dict(raw_audit) if isinstance(raw_audit, Mapping) else {}
    window_rect = _host_window_rect(int(state.viewport_hwnd or 0))
    live_window = (
        {
            "screen_x": int(window_rect[0]),
            "screen_y": int(window_rect[1]),
            "width": int(window_rect[2] - window_rect[0]),
            "height": int(window_rect[3] - window_rect[1]),
        }
        if window_rect
        else {}
    )
    pane = _rectangle(fresh)
    return {
        "refreshed": True,
        "renderer_pane": pane,
        "os_window_at_same_moment": live_window,
        # Sampled inside the control itself, so WinForms' belief, Windows' answer and
        # the swap chain's actual render size are read at one instant on one thread.
        "renderer_geometry_audit": audit,
        "renderer_matches_os_window": bool(live_window and live_window == pane),
        "before": _rectangle(before),
        "after": pane,
        "grew_after_ready_event": pane != _rectangle(before),
    }


__all__ = ["refresh_editable_viewport_rectangle"]
