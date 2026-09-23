"""Owned hidden-window probe of the real New Item helper and Qt transport.

No computer use, installed game or visible application window is involved. The
development executable is explicit; this probe does not claim package provenance.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "windows"
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renderer", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--preview", action="store_true", help="Also exercise the pinned native preview with an owned synthetic mesh")
    args = parser.parse_args()
    from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QTimer, Qt
    from PySide6.QtWidgets import QApplication
    from cdmw.services.new_item_rust_runtime import NewItemUiLaunch
    from cdmw.services.new_item_rust_protocol import PROTOCOL
    from cdmw.ui.new_item.rust_ui_tab import RustNewItemStudioTab
    import test_new_item_studio_tab as support

    settings_root = tempfile.TemporaryDirectory(prefix="cdmw-new-item-live-settings-")
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, settings_root.name)
    support.TabTests.setUpClass()
    fixture = support.TabTests("runTest")
    fixture.setUp()
    launches = []
    checks = []
    errors = []
    experimental = None
    preview_host = None
    preview_root = tempfile.TemporaryDirectory(prefix="cdmw-new-item-native-preview-") if args.preview else None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    user32.PostMessageW.restype = ctypes.c_int
    crop_timer = QTimer()
    crop_timer.setInterval(30)

    def decline_owned_capture():
        if experimental is None:
            return
        for dialog in experimental._dialogs.dialogs():
            if dialog.__class__.__name__ != "AlignmentIconSelectionDialog":
                continue
            bridge = experimental._bridge
            try:
                state = bridge.snapshot()
                assert not state["unsupported"],state["unsupported"]
                for widget,action,value in [(dialog.selector,"crop",[8,10,120,140]),(dialog,"close_dialog",None)]:
                    bridge.snapshot()
                    identifier = bridge.document.registry.identify(widget)
                    node = bridge.document.registry.current[identifier]
                    bridge.dispatch({"protocol":PROTOCOL,"type":"input","session":bridge.session,
                        "request":bridge._last_request+1,"control":identifier,"revision":node["revision"],
                        "action":action,"value":value})
                checks.append("native_capture_crop_projected_and_cancelled")
            except BaseException as error:
                errors.append(str(error))
                dialog.reject()
    crop_timer.timeout.connect(decline_owned_capture)
    crop_timer.start()

    def prepare(session, _log, stop):
        if stop.is_set():
            raise RuntimeError("Owned probe cancelled")
        root = Path(tempfile.mkdtemp(prefix="cdmw-new-item-live-probe-"))
        manifest = root / "session.json"
        manifest.write_text(json.dumps({"protocol": PROTOCOL, "session": session}), encoding="utf-8")
        launch = NewItemUiLaunch(str(args.renderer.resolve()), root, manifest)
        launches.append(root)
        return launch

    def until(predicate, label, timeout=35):
        deadline = time.monotonic() + timeout
        last_paint = 0
        while not predicate() and time.monotonic() < deadline:
            QApplication.processEvents()
            # Hidden Win32 windows do not receive normal compositor paints.
            # Post only to our validated process-owned child while pumping the
            # parent queue; never use a cross-process blocking SendMessage.
            if experimental is not None and experimental._host.child_hwnd and time.monotonic() - last_paint > 0.05:
                user32.PostMessageW(experimental._host.child_hwnd, 0x000F, 0, 0)
                last_paint = time.monotonic()
            if preview_host is not None and preview_host._embedded_child_hwnd:
                user32.PostMessageW(preview_host._embedded_child_hwnd, 0x000F, 0, 0)
            time.sleep(0.005)
        if not predicate():
            raise AssertionError(f"{label}: timed out; errors={errors}; stderr={getattr(experimental, '_stderr', '')}")
        checks.append(label)
        print(label, flush=True)

    try:
        workflow = fixture._tab()
        workflow.prefill_template(support.TEMPLATE)
        with patch("cdmw.ui.new_item.rust_ui_tab.prepare_new_item_ui", prepare):
            experimental = RustNewItemStudioTab(workflow=workflow)
            experimental.status_message_requested.connect(lambda text, error: errors.append(text) if error else None)
            experimental.setAttribute(Qt.WA_DontShowOnScreen, True)
            experimental.resize(1280, 850)
            experimental.show()
            until(lambda: experimental._ready and experimental._received_generation > 0, "real_child_ready_and_state_acknowledged")
            user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
            user32.IsWindowVisible.restype = ctypes.c_int
            assert not user32.IsWindowVisible(int(experimental.winId())), "The owned probe must remain hidden"
            workflow.show_step(1)
            experimental._publish_state()
            until(lambda: experimental._received_generation == experimental._sent_generation, "identity_document_acknowledged")
            bridge = experimental._bridge
            bridge.snapshot()
            identifier = bridge.document.registry.identify(workflow.identity_panel.display_name)
            node = bridge.document.registry.current[identifier]
            experimental._handle_message({"protocol": PROTOCOL, "type": "input", "session": bridge.session,
                "request": 1, "control": identifier, "revision": node["revision"], "action": "text", "value": "Hidden Rust round trip"})
            until(lambda: "Hidden Rust round trip" in workflow.controller.draft.display_names.values(), "queued_input_reached_existing_draft")
            original = workflow.controller.draft
            experimental.use_classic()
            experimental.use_rust()
            until(lambda: experimental._ready and experimental._bridge.session != bridge.session, "rapid_classic_to_rust_restarts_after_drain")
            assert workflow.controller.draft is original
            workflow.show_step(2)
            experimental._state_fingerprint = b""
            experimental._publish_state()
            until(lambda: bool(experimental._portals._attached), "native_preview_viewport_attached")
            # Inspect the actually attached frame, independent of preview implementation names.
            attached = next(iter(experimental._portals._attached.values()))
            viewport = attached[0]
            assert viewport.parentWidget() is experimental._host
            old_handle = int(viewport.winId())
            if args.preview:
                from cdmw.services.mesh_rust_preview_package import build_rust_preview_package
                from tests.test_effect_placement_dialog import _blade
                preview_host = attached[1]
                package = build_rust_preview_package(_blade(), output_root=preview_root.name,
                    include_material_resources=False, interaction_profile="static_replacement")
                assert preview_host.load_package(package)
                until(lambda: preview_host.controller._renderer_ready_announced
                      and preview_host.controller.applied_package_generation > 0,
                      "pinned_preview_loaded_owned_mesh_in_portal")
                preview_process = preview_host.controller.process_id
                preview_child = preview_host._embedded_child_hwnd
                captures = []
                preview_host.controller.capture_completed.connect(captures.append)
                def capture(name):
                    captures.clear()
                    target = args.report.parent / f"{name}.png"
                    assert preview_host.controller.request_capture(target, width=384, height=384)
                    until(lambda: bool(captures),name)
                    assert captures[-1]["status"] == "captured",captures[-1]
                    return target.read_bytes()
                before = capture("native_preview_before_camera")
                assert preview_host.set_view(yaw=35, pitch=65)
                after = capture("native_preview_after_camera")
                assert before != after, "The actual renderer must apply the camera change"
            experimental.resize(1100, 720)
            QApplication.processEvents()
            until(lambda: experimental._received_generation == experimental._sent_generation, "resize_document_acknowledged")
            assert int(viewport.winId()) == old_handle
            session_before_failure = experimental._bridge.session
            experimental._process.kill()
            until(lambda: experimental._process is None, "renderer_failure_restores_preview_owner")
            assert viewport.parentWidget() is attached[1]
            if args.preview:
                assert preview_host.controller.process_id == preview_process
                assert preview_host._embedded_child_hwnd == preview_child
                capture("native_preview_after_ui_failure")
            experimental._retry()
            until(lambda: experimental._ready and experimental._bridge.session != session_before_failure,
                  "retry_starts_fresh_renderer_with_same_draft")
            assert workflow.controller.draft is original
            experimental.use_classic()
            assert viewport.parentWidget() is attached[1]
            assert viewport.mask().isEmpty()
            until(lambda: experimental._process is None and experimental._prepare_thread is None, "cooperative_renderer_shutdown")
            assert workflow.controller.draft is original
            assert not errors, errors
            checks.append("classic_retains_draft_and_viewport_owner")
            if args.preview:
                assert preview_host.controller.process_id == preview_process
                # Classic opens its native crop dialog. This final capture only
                # probes renderer continuity; the Rust capture/crop path above
                # already exercised the real dialog without showing a window.
                workflow.model_panel.preview.captured.disconnect(workflow.model_panel._inline_capture_done)
                capture("native_preview_after_classic_switch")
    finally:
        crop_timer.stop()
        if experimental is not None:
            experimental.request_shutdown()
            until(lambda: not experimental.iter_shutdown_workers()
                  and (preview_host is None or not preview_host.controller.is_running),
                  "all_owned_workers_drained", timeout=10)
            workflow.setParent(None)
            experimental.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        fixture.tearDown()
        settings_root.cleanup()
        if preview_root is not None:
            preview_root.cleanup()
        assert not any(root.exists() for root in launches), "Owned launch manifests were not cleaned"
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({"checks": checks, "errors": errors, "hidden": True,
            "renderer": str(args.renderer.resolve()), "source": "owned_synthetic_fixture"}, indent=2), encoding="utf-8")
    print(json.dumps({"passed": len(checks), "report": str(args.report)}))


if __name__ == "__main__":
    main()
