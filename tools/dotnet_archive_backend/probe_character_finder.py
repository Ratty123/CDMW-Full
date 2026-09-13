"""Visible, read-only acceptance probe for the actual finder and preview pipeline.

The harness supplies an archive session and records navigation requests. It does
not replace catalogue, dependency, package, thumbnail or interactive render code.
Run the browser-navigation contract tests separately for the shell handoff.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QTimer
from cdmw.constants import DEFAULT_UI_THEME
from cdmw.domain.archives.catalogue_operations import OpenArchiveRequest
from cdmw.models import ModelPreviewRenderSettings
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.shell.archive_backend_client import ArchiveBackendClient
from cdmw.ui.character_finder.dialog import CharacterFinderDialog
from cdmw.ui.themes import build_app_stylesheet, build_app_palette
from tools.dotnet_archive_backend.probe_full_archive_backend import _Awaiter
from tools.dotnet_archive_backend.probe_character_catalog import source_snapshot


def run(args):
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(build_app_stylesheet(DEFAULT_UI_THEME))
    app.setPalette(build_app_palette(DEFAULT_UI_THEME))
    app.setQuitOnLastWindowClosed(False)
    args.output.mkdir(parents=True, exist_ok=True)
    before = source_snapshot(args.package_root)
    client = ArchiveBackendClient(cache_root=args.cache_root, worker_executable=args.worker)
    service = ArchiveCatalogueService(client)
    awaiter = _Awaiter(service)
    window = QWidget()
    dialog = None
    report = {"schema": "cdmw_character_finder_visible_v1", "query": args.query, "role": args.role}
    try:
        session = awaiter.wait(service.open_archive(OpenArchiveRequest(str(args.package_root)), ui_generation=1), timeout_ms=600_000)
        window.archive = window.shell = window
        window.archive_catalogue_service = service
        scopes = []
        window.archive_remote_bridge = SimpleNamespace(current_session=session, controller=SimpleNamespace(generation=1),
            apply_entry_id_scope=lambda ids, **kw: scopes.append((ids, kw)) or True)
        window._native_preview_package_cache_root = lambda: args.output.parent / "preview-cache"
        window._current_model_preview_render_settings = ModelPreviewRenderSettings
        window._character_finder_dialogs = set()
        dialog = CharacterFinderDialog(window)
        window._character_finder_dialogs.add(dialog)
        dialog._view.setCurrentIndex(1 if args.view == "appearances" else 0)
        dialog._tabs.setCurrentIndex(1 if args.tab == "faces" or args.role in {"head", "facial_detail", "hair", "beard"} else 0)
        for field, value in (("role", args.role), ("source_group", args.source_group)):
            if value is not None:
                value = "" if value == "all" or (field == "role" and value == "head") else value
                dialog._set_filter(field, value)
        dialog._search_edit.setText(args.query)
        packages, thumbnails, failures, states = [], [], [], []
        dialog._host.controller.state_changed.connect(lambda state, message: states.append((state, message)))
        dialog._preview.package_ready.connect(lambda key, value: packages.append((key, value)))
        dialog._preview.thumbnail_ready.connect(lambda key, value: thumbnails.append((key, value)))
        dialog._preview.failed.connect(lambda key, message: failures.append((key, message)))
        chosen = []
        def choose(_request, operation, result):
            if operation == "search_character_catalog" and args.select_key and not chosen:
                item = dialog._items.get(args.select_key)
                if item:
                    chosen.append(args.select_key)
                    dialog._grid.setCurrentItem(item)
        service.result_ready.connect(choose)
        dialog.show()
        dialog.raise_()
        started = time.monotonic()
        def tick():
            print(json.dumps({"seconds": round(time.monotonic() - started), "rows": len(dialog._rows),
                "requests": list(dialog._requests), "preview": dialog._preview_status.text(),
                "stage": dialog._preview._active_key, "shown": dialog._shown_key,
                "thumbnails": len(thumbnails), "failures": failures[-1:]}), flush=True)
        progress = QTimer()
        progress.setInterval(10_000)
        progress.timeout.connect(tick)
        progress.start()
        finished = _Awaiter._wait_until(lambda: (args.expect_unresolved and dialog._details is not None and not dialog._details.models)
            or (bool(failures) and not args.expect_unresolved) or (
            bool(dialog._shown_key) and dialog._host.controller._active and not dialog._host._status_panel.isVisible()
            and any(key == dialog._shown_key for key, _ in thumbnails) and len(thumbnails) >= args.min_thumbnails), timeout_ms=args.timeout * 1000)
        progress.stop()
        settled = []
        QTimer.singleShot(500, lambda: settled.append(True))
        _Awaiter._wait_until(lambda: bool(settled), timeout_ms=1000)
        if args.interact and dialog._shown_key:
            captures, views = [], []
            dialog._host.controller.capture_completed.connect(lambda value: captures.append(value))
            dialog._host.controller.view_state_changed.connect(lambda value: views.append(value))
            before_path, after_path = args.output / "front.png", args.output / "orbit.png"
            if not dialog._host.controller.request_capture(before_path) or not _Awaiter._wait_until(lambda: bool(captures), timeout_ms=10_000):
                raise RuntimeError("Interactive host did not capture its current scene")
            if not dialog._host.set_view(yaw=215, pitch=5, zoom_factor=1.15, fit_to_view=False):
                raise RuntimeError("Interactive host rejected its camera command")
            # Absolute camera commands and the following capture share the ordered
            # protocol stream. view_state_changed is reserved for native gestures.
            if not dialog._host.controller.request_capture(after_path) or not _Awaiter._wait_until(lambda: len(captures) >= 2, timeout_ms=10_000):
                raise RuntimeError("Interactive host did not capture its changed scene")
            changed = before_path.is_file() and after_path.is_file() and sha256(before_path.read_bytes()).digest() != sha256(after_path.read_bytes()).digest()
            if not changed:
                raise RuntimeError("Camera change did not change the rendered scene")
            report["interactive_camera"] = {"render_changed": changed, "capture_events": captures, "view_events": views}
            dialog._reset_view()
            if not dialog._host.controller.request_capture(args.output / "reset.png") or not _Awaiter._wait_until(lambda: len(captures) >= 3, timeout_ms=10_000):
                raise RuntimeError("Interactive host did not capture its restored front view")
        tick()
        # Qt's backing-store capture omits the native D3D child. Briefly raise
        # this owned window above other apps and verify the capture is its own.
        import ctypes
        from ctypes import wintypes
        from PIL import ImageGrab
        user32 = ctypes.windll.user32
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        hwnd = wintypes.HWND(int(dialog.winId()))
        flags = 0x0001 | 0x0002 | 0x0010  # No resize, move, or activation.
        if not user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, flags):
            raise RuntimeError("Could not raise the finder for its capture")
        try:
            raised = []
            QTimer.singleShot(300, lambda: raised.append(True))
            _Awaiter._wait_until(lambda: bool(raised), timeout_ms=1000)
            rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                raise RuntimeError("Could not locate the finder window")
            for x, y in ((rect.left + 20, rect.top + 40), (rect.right - 20, rect.bottom - 20),
                         ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)):
                owner = user32.GetAncestor(user32.WindowFromPoint(wintypes.POINT(x, y)), 2)
                if owner != hwnd.value:
                    raise RuntimeError("Finder capture is obscured; no screenshot was recorded")
            ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True).save(args.output / "finder.png")
            report["finder_capture_owned_window"] = True
        finally:
            user32.SetWindowPos(hwnd, wintypes.HWND(-2), 0, 0, 0, 0, flags)
        report.update(completed=finished, renderer_active=dialog._host.controller._active, renderer_states=states[-30:],
            session=asdict(session), shown_key=dialog._shown_key,
            status=dialog._preview_status.text(), rows=[asdict(row) for row in dialog._rows.values()],
            selection=asdict(dialog._details) if dialog._details else None,
            packages=[(key, asdict(value)) for key, value in packages],
            thumbnails=[(key, asdict(value)) for key, value in thumbnails], failures=failures,
            navigation=scopes, elapsed_seconds=round(time.monotonic()-started, 3))
        close_started = time.monotonic()
        dialog.close()
        report["close_return_ms"] = (time.monotonic() - close_started) * 1000
        report["teardown_complete"] = _Awaiter._wait_until(lambda: not window._character_finder_dialogs, timeout_ms=30_000)
        report["archive_snapshot_unchanged"] = before == source_snapshot(args.package_root)
        expected_missing = args.expect_unresolved and report["selection"] and not report["selection"]["models"]
        report["expected_unresolved"] = bool(expected_missing)
        (args.output / "visible.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        if not finished or (failures and not expected_missing) or not report["teardown_complete"] or not report["archive_snapshot_unchanged"]:
            raise RuntimeError(f"Visible acceptance incomplete; see {args.output / 'visible.json'}")
        print(f"Visible acceptance passed: {args.output}", flush=True)
    finally:
        if dialog is not None and window._character_finder_dialogs:
            dialog.close()
            _Awaiter._wait_until(lambda: not window._character_finder_dialogs, timeout_ms=30_000)
        client.shutdown()
        _Awaiter._wait_until(lambda: client.process_id == 0, timeout_ms=10_000)
        app.processEvents()
        window.deleteLater()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--query", default="")
    parser.add_argument("--view", choices=("assets", "appearances"), default="appearances")
    parser.add_argument("--tab", choices=("bodies", "faces"), default="bodies")
    parser.add_argument("--role")
    parser.add_argument("--source-group")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--min-thumbnails", type=int, default=1)
    parser.add_argument("--expect-unresolved", action="store_true")
    parser.add_argument("--select-key", default="")
    parser.add_argument("--interact", action="store_true")
    parser.add_argument("--worker", type=Path, default=ROOT / "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/bin/Release/net10.0-windows/win-x64/cdmw-full-archive-worker.exe")
    run(parser.parse_args())
