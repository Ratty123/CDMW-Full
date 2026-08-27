"""Compact Workspace geometry reporting and native-window capture."""

from __future__ import annotations

import ctypes
from pathlib import Path
import sys
from typing import Mapping, Sequence

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QAbstractButton, QApplication, QSplitter, QWidget

from tools.compact_shell_visual.contracts import REFERENCE_FILENAMES


def _rect_payload(rect: QRect) -> dict[str, int]:
    return {
        "x": int(rect.x()),
        "y": int(rect.y()),
        "width": int(rect.width()),
        "height": int(rect.height()),
    }


def _splitter_payload(widget: QWidget) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for index, splitter in enumerate(widget.findChildren(QSplitter)):
        payload.append(
            {
                "id": splitter.objectName() or f"splitter-{index + 1}",
                "orientation": "horizontal"
                if splitter.orientation() == Qt.Orientation.Horizontal
                else "vertical",
                "geometry": _rect_payload(splitter.geometry()),
                "handle_width": int(splitter.handleWidth()),
                "sizes": [int(value) for value in splitter.sizes()],
                "visible": bool(splitter.isVisibleTo(widget)),
            }
        )
    return payload


def _visible_button_payload(widget: QWidget) -> dict[str, object]:
    """Report real compact buttons whose full rendered text does not fit."""

    rows: list[dict[str, object]] = []
    visible_count = 0
    for index, button in enumerate(widget.findChildren(QAbstractButton)):
        text = str(button.text() or "").strip()
        if not text or not button.isVisibleTo(widget) or button.width() <= 0:
            continue
        visible_count += 1
        needed_width = int(button.sizeHint().width())
        actual_width = int(button.width())
        if actual_width + 1 >= needed_width:
            continue
        rows.append(
            {
                "id": button.objectName() or f"{type(button).__name__}-{index + 1}",
                "class": type(button).__name__,
                "text": text,
                "actual_width": actual_width,
                "needed_width": needed_width,
                "shortfall": needed_width - actual_width,
            }
        )
    return {
        "visible_button_count": visible_count,
        "clipped_button_count": len(rows),
        "clipped_buttons": rows,
    }


def _resident_host_payload(widget: QWidget) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for host in widget.findChildren(QWidget):
        name = host.objectName()
        if "DotNetVorticeHost" not in name:
            continue
        origin = host.mapTo(widget, QPoint(0, 0))
        row: dict[str, object] = {
            "id": name,
            "geometry": {
                "x": int(origin.x()),
                "y": int(origin.y()),
                "width": int(host.width()),
                "height": int(host.height()),
            },
            "visible": bool(host.isVisibleTo(widget)),
        }
        hwnd = int(getattr(host, "_embedded_child_hwnd", 0) or 0)
        row["native_child_hwnd"] = hwnd
        if hwnd > 0 and sys.platform == "win32":
            rect = _RECT()
            user32 = ctypes.windll.user32
            if user32.IsWindow(ctypes.c_void_p(hwnd)) and user32.GetWindowRect(
                ctypes.c_void_p(hwnd), ctypes.byref(rect)
            ):
                row["native_child_size"] = {
                    "width": int(rect.right - rect.left),
                    "height": int(rect.bottom - rect.top),
                }
        rows.append(row)
    return rows


def geometry_payload(window: QWidget, key: str, widget: QWidget) -> dict[str, object]:
    payload = {
        "key": key,
        "reference_filename": REFERENCE_FILENAMES[key],
        "widget_class": type(widget).__name__,
        "window_geometry": _rect_payload(window.geometry()),
        "window_frame_geometry": _rect_payload(window.frameGeometry()),
        "tool_geometry": _rect_payload(widget.geometry()),
        "tool_minimum": {
            "width": int(widget.minimumWidth()),
            "height": int(widget.minimumHeight()),
        },
        "splitters": _splitter_payload(widget),
        "resident_hosts": _resident_host_payload(widget),
    }
    payload.update(_visible_button_payload(widget))
    return payload


def clipped_button_error(captures: Sequence[Mapping[str, object]]) -> str:
    """Return one bounded failure message for every capture with hidden button text."""

    offenders: list[str] = []
    for capture in captures:
        rows = capture.get("clipped_buttons", ())
        if not isinstance(rows, (list, tuple)):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            offenders.append(
                f"{capture.get('key', '?')}@{capture.get('requested_size', '?')}:"
                f"{row.get('text', '?')} ({row.get('actual_width', '?')}/"
                f"{row.get('needed_width', '?')} px)"
            )
    if not offenders:
        return ""
    shown = offenders[:12]
    suffix = f"; plus {len(offenders) - len(shown)} more" if len(offenders) > len(shown) else ""
    return "Compact button text was clipped: " + "; ".join(shown) + suffix


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _RGBQUAD(ctypes.Structure):
    _fields_ = [
        ("rgbBlue", ctypes.c_ubyte),
        ("rgbGreen", ctypes.c_ubyte),
        ("rgbRed", ctypes.c_ubyte),
        ("rgbReserved", ctypes.c_ubyte),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", _RGBQUAD * 1)]


def _capture_print_window(window: QWidget) -> QImage | None:
    """Capture the native frame and D3D-aware child surfaces when Windows permits it."""

    app = QApplication.instance()
    if sys.platform != "win32" or app is None or app.platformName().casefold() != "windows":
        return None

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RECT)]
    user32.GetWindowRect.restype = ctypes.c_int
    user32.GetWindowDC.argtypes = [ctypes.c_void_p]
    user32.GetWindowDC.restype = ctypes.c_void_p
    user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    user32.PrintWindow.restype = ctypes.c_int
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.ReleaseDC.restype = ctypes.c_int
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.GetDIBits.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.POINTER(_BITMAPINFO),
        ctypes.c_uint,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteObject.restype = ctypes.c_int
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.restype = ctypes.c_int
    hwnd = int(window.winId())
    rect = _RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width <= 0 or height <= 0:
        return None

    window_dc = user32.GetWindowDC(hwnd)
    if not window_dc:
        return None
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height) if memory_dc else 0
    previous = gdi32.SelectObject(memory_dc, bitmap) if bitmap else 0
    try:
        # PW_RENDERFULLCONTENT asks DWM-backed and D3D child windows to render.
        if not bitmap or not user32.PrintWindow(hwnd, memory_dc, 0x00000002):
            return None
        info = _BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0
        buffer = (ctypes.c_ubyte * (width * height * 4))()
        rows = gdi32.GetDIBits(
            memory_dc,
            bitmap,
            0,
            height,
            ctypes.byref(buffer),
            ctypes.byref(info),
            0,
        )
        if rows != height:
            return None
        return QImage(
            bytes(buffer),
            width,
            height,
            width * 4,
            QImage.Format.Format_ARGB32,
        ).copy()
    finally:
        if previous:
            gdi32.SelectObject(memory_dc, previous)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)


def capture_window(
    window: QWidget,
    output_path: Path,
    *,
    expected_size: tuple[int, int],
) -> tuple[str, tuple[int, int]]:
    """Save a native capture or an explicitly reported QWidget fallback."""

    image = _capture_print_window(window)
    method = "windows_printwindow"
    if image is None or image.isNull():
        image = window.grab().toImage()
        method = "qwidget_grab_fallback_no_native_titlebar"
    elif (image.width(), image.height()) != expected_size:
        # PrintWindow returns physical pixels on a scaled desktop. References
        # and geometry contracts use 100% DPI logical pixels, so normalize the
        # final artifact while retaining the native title bar/D3D capture.
        image = image.scaled(
            expected_size[0],
            expected_size[1],
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        method = "windows_printwindow_scaled_to_100dpi"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if image.isNull() or not image.save(str(output_path), "PNG"):
        raise RuntimeError(f"Could not save compact capture: {output_path}")
    return method, (int(image.width()), int(image.height()))
