"""Owned fixture probe of the real New Item helper and Qt transport.

The default probe is hidden. --visible --interactive exposes the same fixture
for normal Windows interaction checks. No installed game is used. The explicit
development executable does not by itself establish package provenance.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
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
    parser.add_argument("--visible", action="store_true", help="Show only the owned synthetic test window")
    parser.add_argument("--interactive", action="store_true", help="Leave the owned window open for normal input checks")
    parser.add_argument("--material-controls", action="store_true", help="Populate owned material controls for inspector and popup checks")
    args = parser.parse_args()
    if args.interactive and not args.visible:
        parser.error("--interactive requires --visible")
    from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QTimer, Qt
    from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QStackedWidget, QVBoxLayout, QWidget
    from cdmw.services.new_item_rust_runtime import NewItemUiLaunch
    from cdmw.services.new_item_rust_protocol import PROTOCOL
    from cdmw.ui.new_item.rust_ui_tab import RustNewItemStudioTab
    from cdmw.ui.shell.lazy_tool_tab import LazyToolTab
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
    shell = None
    sent_states = []
    native_inputs = []
    rejected_inputs = []
    geometry_checks = []
    view_states = []
    preview_host = None
    preview_root = tempfile.TemporaryDirectory(prefix="cdmw-new-item-native-preview-") if args.preview else None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    user32.PostMessageW.restype = ctypes.c_int
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL

    def native_size(hwnd):
        rect = wintypes.RECT()
        assert user32.GetClientRect(hwnd, ctypes.byref(rect))
        return [rect.right - rect.left, rect.bottom - rect.top]

    def geometry():
        host = experimental._host
        return {"host_qt": [host.width(), host.height()],
                "host_native": native_size(host.host_hwnd()),
                "child_native": native_size(host.child_hwnd)}

    def check_geometry(label):
        pump(0.3)
        sizes = geometry()
        geometry_checks.append({"stage": label, **sizes})
        print(json.dumps(geometry_checks[-1]), flush=True)
        assert sizes["child_native"] == sizes["host_native"], sizes
        checks.append(label)

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
                # Do not synthesize bridge requests alongside the real client:
                # that consumes its request sequence and masks later input.
                dialog.reject()
                checks.append("native_capture_dialog_projected_and_cancelled")
            except BaseException as error:
                errors.append(str(error))
                dialog.reject()
    crop_timer.timeout.connect(decline_owned_capture)
    crop_timer.start()

    def pump(seconds=0.1):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if experimental is not None and experimental._host.child_hwnd:
                user32.PostMessageW(experimental._host.child_hwnd, 0x000F, 0, 0)
            time.sleep(0.005)

    def click_native_control(widget, index=0):
        """Locate a real control and click only this probe's owned child HWND."""
        experimental._state_fingerprint = b""
        experimental._publish_state()
        pump(0.2)
        state = sent_states[-1]
        identifier = experimental._bridge.document.registry.identify(widget)
        rectangle = wintypes.RECT()
        child = experimental._host.child_hwnd
        user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        user32.GetDpiForWindow.restype = ctypes.c_uint
        assert user32.GetClientRect(child, ctypes.byref(rectangle))
        scale = user32.GetDpiForWindow(child) / 96.0
        root = Path(settings_root.name)
        document, report = root / "input-state.json", root / "input-layout.json"
        document.write_text(json.dumps(state), encoding="utf-8")
        result = subprocess.run([str(args.renderer.resolve()), "--new-item-ui-document", str(document),
            "--new-item-ui-report", str(report), "--width", str(round(rectangle.right / scale)),
            "--height", str(round(rectangle.bottom / scale))], capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert result.returncode == 0, result.stderr
        controls = json.loads(report.read_text(encoding="utf-8"))["controls"]
        rect = [control["rect"] for control in controls if control["id"] == identifier][index]
        x, y = round((rect[0] + min(20, rect[2]/2)) * scale), round((rect[1] + rect[3]/2) * scale)
        position = (y << 16) | x
        # Send only to this owned child. The renderer must acquire focus from
        # the click itself, including under a hidden parent.
        user32.PostMessageW(child, 0x0200, 0, position)
        pump()
        # Deliver a complete click in one burst. Separating press/release with
        # idle frames lets Windows synthesize mouse-leave on a hidden parent.
        user32.PostMessageW(child, 0x0200, 0, position + 1)
        user32.PostMessageW(child, 0x0201, 1, position)
        user32.PostMessageW(child, 0x0200, 1, position)
        user32.PostMessageW(child, 0x0202, 0, position)
        pump()
        return child, identifier

    def type_in_native_field(widget, text):
        """Exercise Win32 -> winit -> egui -> stdio -> the original Qt field."""
        child, identifier = click_native_control(widget)
        for character in text:
            key = ord(character.upper())
            scan = user32.MapVirtualKeyW(key, 0)
            user32.PostMessageW(child, 0x0100, key, 1 | (scan << 16))
            user32.PostMessageW(child, 0x0102, ord(character), 1 | (scan << 16))
            user32.PostMessageW(child, 0x0101, key, 1 | (scan << 16) | 0xC0000000)
            pump(0.15)
        until(lambda: widget.text() == text, "native_mouse_and_keyboard_reached_" + identifier, timeout=3)

    def check_cursor_zoom():
        preview_child = preview_host._embedded_child_hwnd
        rectangle = wintypes.RECT()
        assert user32.GetClientRect(preview_child, ctypes.byref(rectangle))
        point = (round(rectangle.bottom * 0.25) << 16) | round(rectangle.right * 0.75)
        def wheel(amount):
            count = len(view_states)
            user32.PostMessageW(preview_child, 0x0200, 0, point)
            user32.PostMessageW(preview_child, 0x020A, (amount & 0xFFFF) << 16, 0)
            until(lambda: len(view_states) > count, "native_cursor_zoom_" + str(amount))
            return view_states[-1]["view_contexts"][0]["camera"]
        baseline = wheel(0)
        closer = wheel(120)
        restored = wheel(-120)
        assert closer["distance"] < baseline["distance"]
        assert any(abs(a-b) > 1e-5 for a,b in zip(closer["pan"], baseline["pan"]))
        assert abs(restored["distance"] - baseline["distance"]) < 1e-4
        assert all(abs(a-b) < 1e-4 for a,b in zip(restored["pan"], baseline["pan"]))
        checks.append("native_wheel_anchors_off_center_pointer_and_restores_on_zoom_out")

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
        if args.material_controls:
            from new_item_rust_ui_harness import prepare_material_controls
            workflow.show_step(2)
            prepare_material_controls(workflow)
        with patch("cdmw.ui.new_item.rust_ui_tab.prepare_new_item_ui", prepare):
            experimental = RustNewItemStudioTab(workflow=workflow)
            send = experimental._send
            handle = experimental._handle_message
            def record_send(message):
                if message.get("type") == "state":
                    sent_states[:] = [message]
                elif message.get("type") == "rejected":
                    rejected_inputs.append(message)
                return send(message)
            def record_input(message):
                if message.get("type") == "input":
                    native_inputs.append(message)
                return handle(message)
            experimental._send = record_send
            experimental._handle_message = record_input
            experimental.status_message_requested.connect(lambda text, error: errors.append(text) if error else None)
            # Match the shell: construct and prewarm inside a hidden lazy tab,
            # then select it for the first time at the workspace's actual size.
            shell = QWidget()
            shell.setAttribute(Qt.WA_DontShowOnScreen, not args.visible)
            shell.setWindowTitle(f"CDMW Rust UI - {args.report.stem}")
            shell.resize(1500, 950)
            shell_layout = QHBoxLayout(shell)
            navigation = QVBoxLayout()
            shell_layout.addLayout(navigation)
            pages = QStackedWidget()
            other = QPushButton("Other tool remains responsive")
            pages.addWidget(other)
            container = LazyToolTab(lambda: experimental)
            pages.addWidget(container)
            for title, page in [("Create New Item (Rust)", container), ("Other tool", other)]:
                button = QPushButton(title)
                navigation.addWidget(button)
                button.clicked.connect(lambda _checked=False, page=page: pages.setCurrentWidget(page))
            navigation.addStretch()
            shell_layout.addWidget(pages, 1)
            if args.visible:
                shell.showMaximized()
            else:
                shell.show()
            container.when_created(lambda widget: widget.prewarm())
            container.request_widget()
            until(lambda: experimental._ready and experimental._received_generation > 0,
                  "hidden_prewarm_ready_and_state_acknowledged")
            warm_pid = experimental._process.processId()
            assert not experimental.isVisible() and not experimental._timer.isActive()
            geometry_checks.append({"stage": "hidden_prewarm", **geometry()})
            pages.setCurrentWidget(container)
            until(lambda: experimental._ready and experimental._received_generation > 0, "real_child_ready_and_state_acknowledged")
            check_geometry("first_open_child_fills_host")
            assert experimental._process.processId() == warm_pid
            checks.append("opening_reuses_prewarmed_process")
            shell.showNormal()
            shell.resize(1100, 720)
            check_geometry("resized_child_fills_host")
            pages.setCurrentWidget(other)
            shell.resize(1500, 950)
            pages.setCurrentWidget(container)
            check_geometry("reopened_child_fills_host")
            assert experimental._process.processId() == warm_pid
            checks.append("resize_and_tool_switch_reuse_prewarmed_process")
            if args.visible:
                shell.showMaximized()
                check_geometry("maximized_child_fills_host")
            user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
            user32.IsWindowVisible.restype = ctypes.c_int
            assert bool(user32.IsWindowVisible(experimental._host.child_hwnd)) == args.visible
            if args.interactive or args.material_controls:
                workflow.template_panel.filter_edit.clear()
                workflow.identity_panel.display_name.setText("Owned fixture")
                if args.preview:
                    from cdmw.services.mesh_rust_preview_package import build_rust_preview_package
                    from tests.test_effect_placement_dialog import _blade
                    assert workflow.model_panel.preview._ensure_host()
                    preview_host = workflow.model_panel.preview.host
                    preview_host.controller.view_state_changed.connect(view_states.append)
                    experimental._state_fingerprint = b""
                    experimental._publish_state()
                    until(lambda: bool(experimental._portals._attached), "interactive_preview_slot_ready")
                    pump(0.3)
                    loading_geometry = preview_host.geometry()
                    package = build_rust_preview_package(_blade(), output_root=preview_root.name,
                        include_material_resources=False, interaction_profile="static_replacement")
                    assert preview_host.load_package(package)
                    until(lambda: preview_host.controller._renderer_ready_announced
                          and preview_host.controller.applied_package_generation > 0,
                          "interactive_preview_ready")
                    pump(0.3)
                    assert preview_host.geometry() == loading_geometry, (loading_geometry, preview_host.geometry())
                    checks.append("preview_slot_stable_from_loading_to_ready")
                    if args.material_controls:
                        panel = workflow.model_panel
                        panel.preview.is_ready = True
                        panel.preview._loaded_is_placement = True
                        panel.preview._placement = workflow.controller.model_placement
                        panel._refresh_placement_enabled()
                        before_turn = preview_host.geometry()
                        click_native_control(panel.quick_turn_section.toggle)
                        until(lambda: panel.quick_turn_section.toggle.isChecked(), "native_quick_turn_expanded")
                        pump(0.3)
                        assert preview_host.geometry() == before_turn, (before_turn, preview_host.geometry())
                        click_native_control(panel.quick_turn_section.toggle)
                        until(lambda: not panel.quick_turn_section.toggle.isChecked(), "native_quick_turn_collapsed")
                        pump(0.3)
                        assert preview_host.geometry() == before_turn, (before_turn, preview_host.geometry())
                        checks.append("quick_turn_keeps_native_viewport_geometry")
                        check_cursor_zoom()
                if not args.interactive:
                    return
                print("interactive_owned_fixture_ready", flush=True)
                deadline = time.monotonic() + 600
                while shell.isVisible() and time.monotonic() < deadline:
                    QApplication.processEvents()
                    time.sleep(0.005)
                print(json.dumps({"filter": workflow.template_panel.filter_edit.text(),
                    "names": workflow.controller.draft.display_names,
                    "native_inputs": native_inputs, "rejected_inputs": rejected_inputs}), flush=True)
                return
            click_native_control(workflow.steps, 1)
            until(lambda: workflow.steps.currentRow() == 1, "native_navigation_opens_identity")
            bridge = experimental._bridge
            type_in_native_field(workflow.identity_panel.display_name, "test")
            until(lambda: "test" in workflow.controller.draft.display_names.values(), "native_typing_reached_existing_draft")
            click_native_control(workflow.steps, 0)
            until(lambda: workflow.steps.currentRow() == 0, "native_navigation_returns_to_template")
            workflow.template_panel.filter_edit.clear()
            type_in_native_field(workflow.template_panel.filter_edit, "blade")
            assert not rejected_inputs, rejected_inputs
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
                preview_host = viewport if hasattr(viewport, "controller") else attached[1]
                preview_host.controller.view_state_changed.connect(view_states.append)
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
                check_cursor_zoom()
            shell.resize(1100, 720)
            QApplication.processEvents()
            check_geometry("preview_resize_child_fills_host")
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
                  and experimental._process is None and experimental._prepare_thread is None
                  and (preview_host is None or not preview_host.controller.is_running),
                  "all_owned_workers_drained", timeout=10)
            workflow.setParent(None)
            experimental.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        if shell is not None:
            shell.close()
            shell.deleteLater()
        fixture.tearDown()
        settings_root.cleanup()
        if preview_root is not None:
            preview_root.cleanup()
        assert not any(root.exists() for root in launches), "Owned launch manifests were not cleaned"
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({"checks": checks, "errors": errors, "native_inputs": native_inputs,
            "geometry": geometry_checks,
            "view_states": view_states,
            "rejected_inputs": rejected_inputs, "hidden": not args.visible,
            "renderer": str(args.renderer.resolve()), "source": "owned_synthetic_fixture"}, indent=2), encoding="utf-8")
    print(json.dumps({"passed": len(checks), "report": str(args.report)}))


if __name__ == "__main__":
    main()
