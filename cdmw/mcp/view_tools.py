"""Browse Archives' view tools: the selection, the preview, the Scene panel, the camera, pictures.

Each goes the way Browse's own controls go: selecting an entry reveals it in
the live catalogue as a click on its row does, the Scene panel's boxes and
buttons are the panel's own, the camera and the preview settings are set
through the preview host and the shared settings the Preview Settings dialog
writes.

``view.capture`` returns a picture of a 3D view:

* ``browse``: the frame the preview helper renders (its own capture request);
* ``mesh_editor``: the Mesh Editor helper has no capture message for a
  document, so its window is asked for its own picture (``PrintWindow``), which
  shows only that window, also while it is covered. When Windows cannot give
  that, the viewport's rectangle is copied from the screen, only while CDMW is
  the window in front. An edit shown in Browse's view is captured as Browse's.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from cdmw.mcp.errors import FAILED, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, READ
from cdmw.mcp.tools import ON_CALL, ON_UI, ON_WORKER, Tool, object_schema

NO_BROWSE = "Browse Archives is not ready yet."
NO_PREVIEW = "Browse Archives shows no 3D preview now: select a model first (view_open)."
CAPTURE_TIMEOUT_S = 30.0
OPEN_TIMEOUT_S = 60.0


def _archive(context):
    archive = getattr(getattr(context, "window", None), "archive", None)
    if archive is None:
        raise ToolError(UNAVAILABLE, NO_BROWSE)
    return archive


def _normal(path: object) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/")


# ----- selection and preview -----------------------------------------------------------
def _selection_now(context) -> dict[str, object]:
    archive = _archive(context)
    entry = getattr(archive, "archive_preview_request_entry", None)
    current = getattr(archive, "_current_archive_entry", None)
    selected = current() if callable(current) else None
    result = getattr(archive, "current_archive_preview_result", None)
    host = getattr(archive, "archive_d3d11_preview_host", None)
    return {
        "selected": str(getattr(selected, "path", "") or ""),
        # The file the preview shows; an edit that holds Browse's view keeps its own.
        "previewed": str(getattr(entry, "path", "") or ""),
        "package": str(getattr(selected, "pamt_path", "") or ""),
        "preview": {
            "loading": getattr(archive, "archive_preview_worker", None) is not None,
            "quality": getattr(result, "quality_tier", None),
            "textures_shown": bool(getattr(archive, "_archive_textures_visible", False)),
            "textures_loading": bool(getattr(archive, "_archive_texture_request_loading", False)
                                     or getattr(archive, "archive_preview_texture_upgrade_pending", False)),
            "has_3d_view": host is not None,
        },
        "editing_here": bool(getattr(archive, "editing_in_place", False)),
        "set_files": len(getattr(getattr(archive, "archive_remote_bridge", None), "item_set_members", ()) or ()),
    }


def _selection(call) -> dict[str, object]:
    return _selection_now(call.context)


def _open(call) -> dict[str, object]:
    from cdmw.ui.ai_connections.context import NO_ARCHIVES

    context = call.context
    archive = _archive(context)
    wanted = _normal(call.arguments["path"])

    def reveal() -> bool:
        archive._note_archive_ui_activity()
        return bool(archive._reveal_archive_path_in_live_catalogue(wanted))

    if not context.ui_call(reveal):
        raise ToolError(UNAVAILABLE, NO_ARCHIVES)
    deadline = time.monotonic() + OPEN_TIMEOUT_S
    while True:
        state = context.ui_call(lambda: _selection_now(context))
        if _normal(state["selected"]).casefold() == wanted.casefold():
            return state
        call.check_cancelled()
        if time.monotonic() > deadline:
            raise ToolError(NOT_FOUND, f"Browse Archives did not show {wanted}. search_archive finds a file's "
                                       "path.")
        time.sleep(0.05)


# ----- the Scene panel ---------------------------------------------------------------------
def _parts(call) -> dict[str, object]:
    from cdmw.automation.inspect_commands import scene_panel_rows

    rows = scene_panel_rows(getattr(call.context, "window", None), {})
    if not rows.get("available"):
        raise ToolError(UNAVAILABLE, "Browse Archives has no Scene panel yet.")
    return {"shown": rows["visible"], "selected": rows["selected"],
            "files": [{"file": group["path"] or group["label"], "label": group["label"], "count": group["count"],
                       "parts": [{"part": part["index"], "label": part["label"], "index_in_file": part["local"],
                                  "ticked": part["ticked"]} for part in group["parts"]]}
                      for group in rows["files"]]}


def _set_parts(call) -> dict[str, object]:
    from PySide6.QtCore import Qt

    from cdmw.automation import pass_commands, review_commands

    a = call.arguments
    window = getattr(call.context, "window", None)
    panel = getattr(_archive(call.context), "archive_item_set_components", None)
    if panel is None:
        raise ToolError(UNAVAILABLE, "Browse Archives has no Scene panel yet.")
    action = str(a.get("action") or "")
    if action in ("show_all", "isolate"):
        try:
            done = review_commands.scene_action(window, {"action": action, "path": a.get("file") or ""})
        except (RuntimeError, ValueError) as error:
            raise ToolError(UNAVAILABLE, str(error)) from None
        if not done["clicked"]:
            raise ToolError(UNAVAILABLE, "The Scene panel's button is disabled now.")
    elif a.get("part") is not None:
        item = (getattr(panel, "_parts", {}) or {}).get(int(a["part"]))
        if item is None:
            raise ToolError(NOT_FOUND, f"The Scene panel has no part {a['part']}.")
        item.setCheckState(0, Qt.CheckState.Checked if a.get("ticked", True) else Qt.CheckState.Unchecked)
    elif a.get("file"):
        if not pass_commands.scene_panel_tick(window, {"path": a["file"], "ticked": a.get("ticked", True)}):
            raise ToolError(NOT_FOUND, f"The Scene panel has no file {a['file']}.")
    else:
        raise ToolError(UNAVAILABLE, "Name an action (show_all, isolate), a part or a file.")
    return _parts(call)


# ----- camera and settings ------------------------------------------------------------------
def _host(context):
    host = getattr(_archive(context), "archive_d3d11_preview_host", None)
    if host is None:
        raise ToolError(UNAVAILABLE, NO_PREVIEW)
    return host


def _camera(call) -> dict[str, object]:
    a = call.arguments
    host = _host(call.context)
    if a.get("reset"):
        host.reset_view()
    elif any(a.get(name) is not None for name in ("yaw", "pitch", "roll", "zoom", "pan")):
        state = dict(host.view_state_snapshot())
        pan = a.get("pan") if a.get("pan") is not None else state.get("pan", (0.0, 0.0, 0.0))
        if not host.set_view(yaw=float(a["yaw"] if a.get("yaw") is not None else state.get("yaw", 0.0)),
                             pitch=float(a["pitch"] if a.get("pitch") is not None else state.get("pitch", 0.0)),
                             roll=float(a["roll"] if a.get("roll") is not None else state.get("roll", 0.0)),
                             zoom_factor=float(a["zoom"]) if a.get("zoom") is not None else None,
                             fit_to_view=False if a.get("zoom") is not None else None,
                             pan=[float(value) for value in pan]):
            raise ToolError(UNAVAILABLE, "The preview did not take the camera now.")
    return {"camera": dict(host.view_state_snapshot())}


def _settings(call) -> dict[str, object]:
    from cdmw.ui.preview.preview_settings_hub import preview_settings_hub

    hub = preview_settings_hub()
    if hub is None:
        raise ToolError(UNAVAILABLE, "The shared Preview settings are not available yet.")
    changes = dict(call.arguments.get("values") or {})
    result: dict[str, object] = {}
    if changes:
        before = hub.values()
        hub.update(**changes)
        after = hub.values()
        result["changed"] = sorted(name for name in after if after[name] != before.get(name))
        result["not_taken"] = sorted(name for name in changes if name not in after)
    result["settings"] = hub.values()
    return result


def _settings_effect(call) -> str:
    return EDIT if call.arguments.get("values") else READ


# ----- pictures -------------------------------------------------------------------------------
def _png_file(call, path: Path, facts: dict[str, object]):
    from PySide6.QtGui import QImage

    from cdmw.mcp.control_tools import MAX_PICTURE_SIDE, png_of
    from cdmw.mcp.server import ImageResult

    deadline = time.monotonic() + CAPTURE_TIMEOUT_S
    while not path.is_file() or path.stat().st_size == 0:
        call.check_cancelled()
        if time.monotonic() > deadline:
            raise ToolError(FAILED, "The preview did not deliver the picture in time.")
        time.sleep(0.05)
    image = QImage(str(path))
    if image.isNull():
        time.sleep(0.2)  # still being moved into place
        image = QImage(str(path))
    data, width, height = png_of(image, int(call.arguments.get("max_side") or MAX_PICTURE_SIDE))
    return ImageResult(data, {**facts, "width": width, "height": height})


def _capture_browse(call):
    context = call.context
    folder = Path(tempfile.mkdtemp(prefix="cdmw-ai-capture-"))
    target = folder / "capture.png"
    try:
        def request() -> dict[str, object]:
            host = _host(context)
            if not host.request_frame_capture(target):
                raise ToolError(UNAVAILABLE, "The preview cannot take a picture now: nothing is shown in it yet.")
            return _selection_now(context)

        state = context.ui_call(request)
        return _png_file(call, target, {"view": "browse", "how": "rendered by the preview",
                                        "file": state["previewed"] or state["selected"]})
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def window_picture(hwnd: int):
    """What a native window draws, asked of the window itself (``PrintWindow``): only that
    window, also while another one covers it. A QImage, or None when Windows cannot give it."""

    import ctypes
    import os
    from ctypes import wintypes

    from PySide6.QtGui import QImage

    if os.name != "nt" or not hwnd:
        return None
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                ctypes.c_void_p, wintypes.UINT]
    rect = wintypes.RECT()
    if not user32.IsWindow(hwnd) or not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None
    window_dc = user32.GetDC(hwnd)
    if not window_dc:
        return None
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        # PW_CLIENTONLY | PW_RENDERFULLCONTENT: the second makes a Direct3D window draw too.
        if not user32.PrintWindow(hwnd, memory_dc, 0x1 | 0x2):
            return None
        header = (ctypes.c_uint32 * 10)(40, width, ctypes.c_uint32(-height).value, 1 | (32 << 16), 0, 0, 0, 0, 0,
                                         0)
        pixels = ctypes.create_string_buffer(width * height * 4)
        gdi32.SelectObject(memory_dc, previous)
        if gdi32.GetDIBits(memory_dc, bitmap, 0, height, pixels, header, 0) != height:
            return None
        return QImage(pixels.raw, width, height, width * 4, QImage.Format.Format_RGB32).copy()
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)


def _one_colour(image) -> bool:
    """A picture of one flat colour: the window gave nothing of what it draws."""

    data = bytes(image.constBits())
    return len(data) < 8 or data == data[:4] * (len(data) // 4)


def _editor_window(context) -> dict[str, object]:
    """On the UI thread: the shown Mesh Editor document's native window and its name."""

    from cdmw.mcp.mesh_tools import NO_EDITOR, shown_document
    from cdmw.ui.mesh_editor.documents import document_label

    tab = shown_document(context)
    if tab is None or getattr(tab, "standalone_native_host_frame", None) is None:
        raise ToolError(UNAVAILABLE, NO_EDITOR)
    ready = bool(getattr(tab, "standalone_rust_ready", False))
    return {"document": document_label(tab),
            # A helper that is still starting, or stuck, is not asked: the call would wait on it.
            "hwnd": int(getattr(tab, "standalone_rust_child_hwnd", 0) or 0) if ready else 0}


def _screen_copy(context, max_side: int, facts: dict[str, object]):
    """On the UI thread: the viewport's rectangle copied from the screen, only while CDMW is
    the window in front: a read that needs no approval must not copy another program's window."""

    from PySide6.QtCore import QPoint

    from cdmw.mcp.control_tools import png_of
    from cdmw.mcp.mesh_tools import NO_EDITOR, shown_document
    from cdmw.mcp.server import ImageResult

    tab = shown_document(context)
    frame = getattr(tab, "standalone_native_host_frame", None)
    if tab is None or frame is None:
        raise ToolError(UNAVAILABLE, NO_EDITOR)
    if not frame.isVisible() or frame.window().isMinimized():
        raise ToolError(UNAVAILABLE, "The Mesh Editor's view is not on screen: show the Mesh Editor "
                                     "(app_open_tool mesh_editor) with CDMW's window visible.")
    if not frame.window().isActiveWindow():
        raise ToolError(UNAVAILABLE, "The Mesh Editor's view can only be copied from the screen while CDMW is "
                                     "the window in front: click CDMW's window, then ask again.")
    screen = frame.screen()
    origin = frame.mapToGlobal(QPoint(0, 0)) - screen.geometry().topLeft()
    pixmap = screen.grabWindow(0, origin.x(), origin.y(), frame.width(), frame.height())
    data, width, height = png_of(pixmap, max_side)
    return ImageResult(data, {**facts, "how": "copied from the screen", "width": width, "height": height})


def _capture_mesh_editor(context, max_side: int):
    """The shown Mesh Editor document's viewport, from the call's own thread.

    First the helper window's own picture: asked here, not on the UI thread, since Windows
    waits for the helper to draw. When that gives nothing, the screen is copied.
    """

    from cdmw.mcp.control_tools import png_of
    from cdmw.mcp.server import ImageResult

    window = context.ui_call(lambda: _editor_window(context))
    facts: dict[str, object] = {"view": "mesh_editor", "document": window["document"]}
    image = window_picture(int(window["hwnd"]))
    if image is not None and not _one_colour(image):
        data, width, height = png_of(image, max_side)
        return ImageResult(data, {**facts, "how": "drawn by the editor's window", "width": width,
                                  "height": height})
    return context.ui_call(lambda: _screen_copy(context, max_side, facts))


def _capture(call):
    from cdmw.mcp.control_tools import MAX_PICTURE_SIDE
    from cdmw.mcp.mesh_tools import shown_document

    context = call.context
    view = str(call.arguments.get("view") or "")
    max_side = int(call.arguments.get("max_side") or MAX_PICTURE_SIDE)

    def where() -> str:
        window = getattr(context, "window", None)
        tab = shown_document(context)
        in_browse = getattr(getattr(tab, "live_edit", None), "viewport_binding", None) is not None
        if view == "mesh_editor":
            return "browse" if in_browse else "mesh_editor"
        if view == "browse":
            return "browse"
        shown = str(getattr(getattr(getattr(window, "shell", None), "compact_workspace", None),
                            "_active_tool_key", "") or "")
        return "mesh_editor" if shown == "mesh_editor" and tab is not None and not in_browse else "browse"

    if context.ui_call(where) == "mesh_editor":
        return _capture_mesh_editor(context, max_side)
    return _capture_browse(call)


def view_tools() -> list[Tool]:
    number = {"type": "number"}
    return [
        Tool(name="view.selection", family="view", title="Browse selection",
             description="Browse Archives now: the selected file, the file the preview shows, whether the "
                         "preview is still loading, its quality and textures, and whether an edit holds its "
                         "3D view.",
             input_schema=object_schema(), effect=READ, route="ui:ArchiveBrowser", handler=_selection,
             runs_on=ON_UI),
        Tool(name="view.open", family="view", title="Select and preview",
             description="Selects an archive file in Browse Archives by its path, as a click on its row does, "
                         "whatever filters are set; Browse previews it. Returns the selection once the row is "
                         "shown; view_selection says when the preview has loaded.",
             input_schema=object_schema({"path": {"type": "string", "minLength": 1, "maxLength": 512}}, ["path"]),
             effect=READ, route="ui:_reveal_archive_path_in_live_catalogue", handler=_open, runs_on=ON_WORKER),
        Tool(name="view.parts", family="view", title="Scene panel",
             description="Browse Archives' Scene panel: each file of the shown model or set with its parts and "
                         "whether each is ticked (shown).",
             input_schema=object_schema(), effect=READ, route="ui:ScenePanel", handler=_parts, runs_on=ON_UI,
             paged="files"),
        Tool(name="view.set_parts", family="view", title="Show or hide parts",
             description="The Scene panel's boxes and buttons: tick or untick one 'part' (its number) or a "
                         "whole 'file', or 'action' show_all, or isolate ('file' names the row to isolate). "
                         "Changes only what the preview shows.",
             input_schema=object_schema({"part": {"type": "integer", "minimum": 0},
                                         "file": {"type": "string", "maxLength": 512},
                                         "ticked": {"type": "boolean", "default": True},
                                         "action": {"type": "string", "enum": ["", "show_all", "isolate"]}}),
             effect=READ, route="ui:ScenePanel", handler=_set_parts, runs_on=ON_UI, paged="files"),
        Tool(name="view.camera", family="view", title="Preview camera",
             description="Browse Archives' 3D preview camera: without arguments its state; 'yaw', 'pitch' and "
                         "'roll' in degrees, 'zoom' (1 fits the model), 'pan' [x, y, z]; or 'reset'. Take a "
                         "picture with view_capture afterwards.",
             input_schema=object_schema({"yaw": number, "pitch": number, "roll": number,
                                         "zoom": {"type": "number", "minimum": 0.01, "maximum": 100},
                                         "pan": {"type": "array", "minItems": 3, "maxItems": 3, "items": number},
                                         "reset": {"type": "boolean"}}),
             effect=READ, route="ui:DotnetPreviewHost.set_view", handler=_camera, runs_on=ON_UI),
        Tool(name="view.settings", family="view", title="Preview settings",
             description="The Preview settings every 3D view shares (lighting, background, quality, what is "
                         "drawn): without arguments their values; 'values' changes some, as the Preview "
                         "Settings dialog does, and is then an edit that may ask the user.",
             input_schema=object_schema({"values": {"type": "object"}}), effect=EDIT,
             route="ui:preview_settings_hub", handler=_settings, runs_on=ON_UI, effect_of=_settings_effect,
             approval_key=lambda call: "set" if call.arguments.get("values") else "get"),
        Tool(name="view.capture", family="view", title="Picture of the 3D view",
             description="A picture (PNG) of a 3D view: 'browse' is Browse Archives' preview as its renderer "
                         "draws it; 'mesh_editor' is the shown Mesh Editor document's viewport, as its own "
                         "window draws it ('how' says when it had to be copied from the screen instead, which "
                         "needs CDMW's window in front). Without 'view' it is the one that is shown.",
             input_schema=object_schema({"view": {"type": "string", "enum": ["", "browse", "mesh_editor"]},
                                         "max_side": {"type": "integer", "minimum": 64, "maximum": 4096,
                                                      "default": 1600}}),
             effect=READ, route="ui:request_frame_capture|QScreen.grabWindow", handler=_capture,
             runs_on=ON_CALL),
    ]


__all__ = ["view_tools"]
