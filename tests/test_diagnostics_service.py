from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path

from cdmw.services.diagnostics_service import (
    CRASH_REPORT_CAPTURE_DEFAULT_KINDS,
    RuntimeEventRecorder,
    add_persisted_crash_breadcrumbs,
    append_runtime_event_log,
    check_previous_unclean_exit,
    cleanup_native_fault_log_on_exit,
    crash_report_kind_already_covers_session,
    crash_timestamp,
    diagnostic_report_index,
    enable_native_fault_log,
    format_issue_summary,
    format_timing_summary,
    format_thread_dump,
    heartbeat_payload,
    is_expected_cancellation_message,
    latest_diagnostic_report_files,
    merge_timing_maps,
    parse_crash_report_header,
    process_is_alive,
    read_crash_json_context_file,
    read_jsonl_tail,
    rotate_runtime_event_logs,
    runtime_event_child_memory,
    runtime_event_log_sibling,
    sanitize_runtime_event_value,
    should_write_crash_report,
    start_hang_watchdog,
    thread_exception_report,
    timing_value,
    traceback_diagnostic_details,
    uncaught_exception_report,
    unraisable_exception_report,
    write_app_heartbeat,
    write_crash_report,
    write_heartbeat_file,
    write_ui_breadcrumb,
)


class _FaultHandlerStub:
    def __init__(self) -> None:
        self.enabled = False
        self.disabled = False
        self.file_object = None
        self.all_threads = False

    def enable(self, *, file: object, all_threads: bool) -> None:
        self.enabled = True
        self.file_object = file
        self.all_threads = bool(all_threads)

    def disable(self) -> None:
        self.disabled = True


class DiagnosticsServiceTests(unittest.TestCase):
    def test_sanitize_runtime_event_value_bounds_payloads(self) -> None:
        path = Path("archive") / "entry.dds"
        sanitized = sanitize_runtime_event_value(
            {
                "path": path,
                "long": "x" * 1005,
                "items": list(range(42)),
                "nested": {"a": {"b": {"c": {"d": "too deep"}}}},
            }
        )

        self.assertIsInstance(sanitized, dict)
        self.assertEqual(str(path), sanitized["path"])
        self.assertEqual("x" * 1000 + "...<truncated>", sanitized["long"])
        self.assertEqual("2 more", sanitized["items"][-1])
        self.assertEqual("dict", sanitized["nested"]["a"]["b"]["c"])

        capped = sanitize_runtime_event_value({f"key-{index}": index for index in range(42)})
        self.assertEqual("2 more", capped["..."])

    def test_runtime_event_log_rotation_and_tail_reader(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "runtime_events_current.jsonl"
            path.write_text('{"old":0}\n', encoding="utf-8")
            runtime_event_log_sibling(path, 1).write_text('{"older":1}\n', encoding="utf-8")

            rotate_runtime_event_logs(path, max_bytes=1, rotation_count=2)

            self.assertFalse(path.exists())
            self.assertEqual('{"old":0}\n', runtime_event_log_sibling(path, 1).read_text(encoding="utf-8"))
            self.assertEqual('{"older":1}\n', runtime_event_log_sibling(path, 2).read_text(encoding="utf-8"))

            append_runtime_event_log(path, {"new": True})
            with path.open("a", encoding="utf-8") as stream:
                stream.write("not-json\n")
                stream.write('{"last":2}\n')

            self.assertEqual([{"new": True}, {"last": 2}], read_jsonl_tail(path, limit=3))

    def test_runtime_event_recorder_composes_memory_fields_ring_and_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "runtime_events_current.jsonl"
            calls: list[int] = []

            def snapshot(pid: int) -> dict[str, int]:
                calls.append(pid)
                return {"private_bytes": pid * 100}

            recorder = RuntimeEventRecorder(
                path,
                session_id="session-1",
                ring_size=2,
                current_pid_fn=lambda: 10,
                memory_snapshot=snapshot,
                clock=lambda: 100.0,
            )

            first = recorder.record("preview", process_pid=11, path=Path("archive") / "entry.dds")
            second = recorder.record("scan")
            third = recorder.record("build")

            self.assertEqual([10, 11, 10, 10], calls)
            self.assertEqual("session-1", first["session_id"])
            self.assertEqual(10, first["pid"])
            self.assertEqual("preview", first["event"])
            self.assertEqual(str(Path("archive") / "entry.dds"), first["path"])
            self.assertEqual({"private_bytes": 1000}, first["process_memory"])
            self.assertEqual({"11": {"private_bytes": 1100}}, first["child_process_memory"])
            self.assertEqual(2100, first["memory_total_private_bytes"])
            self.assertEqual([second, third], recorder.tail(limit=10))
            self.assertEqual([first, second, third], read_jsonl_tail(path, limit=10))

    def test_persisted_crash_breadcrumbs_collect_json_context_and_event_tails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            runtime_log = reports_dir / "runtime_events_current.jsonl"
            native_log = reports_dir / "native_events_current.jsonl"
            (reports_dir / "archive_scan_breadcrumb.json").write_text('{"phase":"scan"}', encoding="utf-8")
            (reports_dir / "ui_breadcrumb.json").write_text('{"phase":"ui"}', encoding="utf-8")
            (reports_dir / "texture_workflow_breadcrumb.json").write_text('{"phase":"texture"}', encoding="utf-8")
            runtime_log.write_text('{"event":"runtime"}\n', encoding="utf-8")
            native_log.write_text('{"event":"native"}\n', encoding="utf-8")

            context: dict[str, object] = {}
            add_persisted_crash_breadcrumbs(
                context,
                reports_dir=reports_dir,
                runtime_event_log_path=runtime_log,
                native_diagnostic_log_path=native_log,
            )

            self.assertEqual({"phase": "scan"}, context["archive_scan_breadcrumb"])
            self.assertEqual({"phase": "ui"}, context["ui_breadcrumb"])
            self.assertEqual({"phase": "texture"}, context["texture_workflow_breadcrumb"])
            self.assertEqual([{"event": "runtime"}], context["persisted_runtime_event_tail"])
            self.assertEqual([{"event": "native"}], context["persisted_native_event_tail"])
            self.assertEqual({"phase": "ui"}, read_crash_json_context_file(reports_dir, "ui_breadcrumb.json"))

    def test_ui_breadcrumb_report_and_heartbeat_writers_are_atomic_file_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            write_ui_breadcrumb(
                reports_dir,
                {"phase": "preview"},
                session_id="session-1",
                pid=123,
                timestamp=1.5,
            )
            ui_payload = read_crash_json_context_file(reports_dir, "ui_breadcrumb.json")

            self.assertEqual({"phase": "preview", "timestamp": 1.5, "pid": 123, "session_id": "session-1"}, ui_payload)

            report_path = write_crash_report(
                reports_dir,
                "test_kind",
                "Test title",
                "Test body",
                app_title="Workbench",
                app_version="1.0",
                session_id="session-1",
                context={"phase": "preview"},
                pid=123,
                python_version="Python 3.x",
                platform_label="TestOS",
                timestamp="2026-01-02 03:04:05",
            )
            self.assertIsNotNone(report_path)
            report_text = report_path.read_text(encoding="utf-8")
            self.assertIn("Workbench crash/details report", report_text)
            self.assertIn("Kind: test_kind", report_text)
            self.assertIn("Report ID: test_kind_", report_text)
            self.assertIn("Likely Location: unknown", report_text)
            self.assertIn("Exception: Test body", report_text)
            self.assertRegex(report_text, r"Fingerprint: [0-9a-f]{12}")
            self.assertIn('"phase": "preview"', report_text)
            header = parse_crash_report_header(report_text)
            self.assertEqual("test_kind", header["Kind"])
            self.assertEqual("1.0", header["Version"])
            self.assertEqual("unknown", header["Likely Location"])

            heartbeat_path = reports_dir / "app_heartbeat.json"
            write_heartbeat_file(heartbeat_path, {"phase": "running", "session_id": "session-1"})
            self.assertEqual({"phase": "running", "session_id": "session-1"}, read_crash_json_context_file(reports_dir, "app_heartbeat.json"))

    def test_crash_report_write_policy_preserves_always_allowed_kinds(self) -> None:
        self.assertIn("startup_failure", CRASH_REPORT_CAPTURE_DEFAULT_KINDS)
        self.assertIn("previous_session_unclean_exit", CRASH_REPORT_CAPTURE_DEFAULT_KINDS)
        self.assertIn("app_hang_detected", CRASH_REPORT_CAPTURE_DEFAULT_KINDS)
        self.assertTrue(should_write_crash_report("startup_failure", capture_enabled=False))
        self.assertTrue(should_write_crash_report("verbose_diagnostic", capture_enabled=True))
        self.assertTrue(should_write_crash_report("verbose_diagnostic", capture_enabled=False, force=True))
        self.assertFalse(should_write_crash_report("verbose_diagnostic", capture_enabled=False))

    def test_traceback_diagnostics_prefer_deepest_app_frame(self) -> None:
        text = "\n".join(
            [
                "Traceback (most recent call last):",
                '  File "C:\\Temp\\other.py", line 3, in outer',
                '  File "C:\\Repo\\cdmw\\ui\\shell\\app_window.py", line 42, in run_gui',
                '  File "C:\\Repo\\cdmw\\services\\diagnostics_service.py", line 99, in worker',
                "RuntimeError: hook boom",
            ]
        )

        details = traceback_diagnostic_details(text)

        self.assertEqual("cdmw/services/diagnostics_service.py:99 in worker", details["likely_location"])
        self.assertEqual("RuntimeError: hook boom", details["exception"])
        self.assertEqual("RuntimeError", details["exception_type"])
        self.assertEqual("hook boom", details["exception_message"])
        self.assertRegex(details["fingerprint"], r"^[0-9a-f]{12}$")

    def test_traceback_diagnostics_handle_no_frame_text(self) -> None:
        details = traceback_diagnostic_details("plain worker failure")

        self.assertEqual("unknown", details["likely_location"])
        self.assertEqual("plain worker failure", details["exception"])
        self.assertRegex(details["fingerprint"], r"^[0-9a-f]{12}$")

    def test_exception_hook_report_formatters_preserve_kind_title_and_traceback(self) -> None:
        try:
            raise RuntimeError("hook boom")
        except RuntimeError as exc:
            exc_type = type(exc)
            exc_value = exc
            exc_traceback = exc.__traceback__

        kind, title, body = uncaught_exception_report(exc_type, exc_value, exc_traceback)
        self.assertEqual("unhandled_exception", kind)
        self.assertEqual("Unhandled exception", title)
        self.assertIn("RuntimeError: hook boom", body)

        thread_args = type(
            "ThreadArgs",
            (),
            {
                "exc_type": RuntimeError,
                "exc_value": RuntimeError("thread boom"),
                "exc_traceback": exc_traceback,
                "thread": threading.current_thread(),
            },
        )()
        kind, title, body = thread_exception_report(thread_args)
        self.assertEqual("thread_exception", kind)
        self.assertIn(threading.current_thread().name, title)
        self.assertIn("RuntimeError: thread boom", body)

        unraisable_args = type(
            "UnraisableArgs",
            (),
            {
                "exc_type": RuntimeError,
                "exc_value": RuntimeError("unraisable boom"),
                "exc_traceback": exc_traceback,
                "object": "callback",
            },
        )()
        kind, title, body = unraisable_exception_report(unraisable_args)
        self.assertEqual("unraisable_exception", kind)
        self.assertIn("'callback'", title)
        self.assertIn("RuntimeError: unraisable boom", body)

    def test_native_fault_log_helpers_enable_and_cleanup_empty_clean_exit_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            fault_handler = _FaultHandlerStub()

            handle = enable_native_fault_log(reports_dir, fault_handler=fault_handler)

            self.assertIsNotNone(handle)
            self.assertTrue(fault_handler.enabled)
            self.assertTrue(fault_handler.all_threads)
            self.assertIs(fault_handler.file_object, handle)
            self.assertTrue((reports_dir / "native_fault_current.log").is_file())

            cleanup_native_fault_log_on_exit(
                handle,
                reports_dir,
                clean_exit=True,
                fault_handler=fault_handler,
            )

            self.assertTrue(fault_handler.disabled)
            self.assertFalse((reports_dir / "native_fault_current.log").exists())

    def test_runtime_event_child_memory_uses_snapshot_callback(self) -> None:
        calls: list[int] = []

        def snapshot(pid: int) -> dict[str, int]:
            calls.append(pid)
            return {"pid": pid, "private_bytes": pid * 10}

        result = runtime_event_child_memory(
            {
                "process_pid": os.getpid(),
                "d3d11_process_pid": "123",
                "preview_core_process_pid": "bad",
                "native_preview_core_process_pid": 456,
            },
            current_pid=os.getpid(),
            memory_snapshot=snapshot,
        )

        self.assertEqual([123, 456], calls)
        self.assertEqual(
            {
                "123": {"pid": 123, "private_bytes": 1230},
                "456": {"pid": 456, "private_bytes": 4560},
            },
            result,
        )

    def test_process_is_alive_rejects_current_and_invalid_pid(self) -> None:
        self.assertRegex(crash_timestamp(), r"^\d{8}_\d{6}_\d{3}$")
        self.assertFalse(process_is_alive("bad"))
        self.assertFalse(process_is_alive(0))
        self.assertFalse(process_is_alive(os.getpid()))

    def test_crash_report_dedupe_scans_matching_kind_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            (reports_dir / "previous_session_unclean_exit_1.log").write_text("session abc-123\n", encoding="utf-8")
            (reports_dir / "other_kind_1.log").write_text("session abc-123\n", encoding="utf-8")

            self.assertTrue(
                crash_report_kind_already_covers_session(
                    reports_dir,
                    "previous_session_unclean_exit",
                    "abc-123",
                )
            )
            self.assertFalse(
                crash_report_kind_already_covers_session(
                    reports_dir,
                    "previous_session_unclean_exit",
                    "missing-session",
                )
            )
            self.assertFalse(crash_report_kind_already_covers_session(reports_dir, "", "abc-123"))

    def test_latest_diagnostic_report_files_are_bounded_newest_first_and_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            old = reports_dir / "old.log"
            middle = reports_dir / "middle.json"
            new = reports_dir / "new.log"
            old.write_text("App report\nKind: old\nReport ID: old\n\n", encoding="utf-8")
            middle.write_text("{}", encoding="utf-8")
            new.write_text(
                "App report\nKind: new\nReport ID: new\nLikely Location: cdmw/app.py:1 in main\nException: RuntimeError: bad\nFingerprint: abc123abc123\n\n",
                encoding="utf-8",
            )
            ignored = reports_dir / "ignored.txt"
            ignored.write_text("ignore", encoding="utf-8")
            os.utime(old, (100.0, 100.0))
            os.utime(middle, (200.0, 200.0))
            os.utime(new, (300.0, 300.0))

            latest = latest_diagnostic_report_files(reports_dir, limit=2)

            self.assertEqual([new, middle], latest)
            index = diagnostic_report_index(latest)
            self.assertEqual("new.log", index[0]["name"])
            self.assertEqual("new", index[0]["report_id"])
            self.assertEqual("cdmw/app.py:1 in main", index[0]["likely_location"])
            self.assertEqual("middle.json", index[1]["name"])

    def test_issue_summary_uses_report_header_context_and_repro_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            report_path = write_crash_report(
                reports_dir,
                "unhandled_exception",
                "Unhandled exception",
                "\n".join(
                    [
                        "Traceback (most recent call last):",
                        '  File "C:\\Repo\\cdmw\\ui\\shell\\app_window.py", line 42, in run_gui',
                        "RuntimeError: hook boom",
                    ]
                ),
                app_title="Workbench",
                app_version="1.2.3",
                session_id="session-1",
                context={
                    "current_tab": "Archive Browser",
                    "last_active_operation": {"operation": "archive_preview"},
                },
                pid=123,
            )

            summary = format_issue_summary(
                app_title="Workbench",
                app_version="1.2.3",
                report_path=report_path,
            )

            self.assertIn("Workbench problem report", summary)
            self.assertIn("Version: 1.2.3", summary)
            self.assertIn("Report ID: unhandled_exception_", summary)
            self.assertIn("Likely location: cdmw/ui/shell/app_window.py:42 in run_gui", summary)
            self.assertIn("Exception: RuntimeError: hook boom", summary)
            self.assertIn("Current tab: Archive Browser", summary)
            self.assertIn("Last action: archive_preview", summary)
            self.assertIn("Steps to reproduce:", summary)
            self.assertIn("- Diagnostic ZIP from Help > Export Diagnostics", summary)

    def test_check_previous_unclean_exit_ignores_missing_clean_current_and_live_recent_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            heartbeat_path = reports_dir / "app_heartbeat.json"

            self.assertFalse(check_previous_unclean_exit(heartbeat_path, session_id="new", reports_dir=reports_dir))

            heartbeat_path.write_text('{"clean_shutdown": true, "session_id": "old"}', encoding="utf-8")
            self.assertFalse(check_previous_unclean_exit(heartbeat_path, session_id="new", reports_dir=reports_dir))

            heartbeat_path.write_text(
                '{"clean_shutdown": false, "session_id": "new", "last_beat_epoch": 100.0, "pid": 123}',
                encoding="utf-8",
            )
            self.assertFalse(check_previous_unclean_exit(heartbeat_path, session_id="new", reports_dir=reports_dir))

            heartbeat_path.write_text(
                '{"clean_shutdown": false, "session_id": "old", "last_beat_epoch": 190.0, "pid": 123}',
                encoding="utf-8",
            )
            self.assertFalse(
                check_previous_unclean_exit(
                    heartbeat_path,
                    session_id="new",
                    reports_dir=reports_dir,
                    process_is_alive_fn=lambda _pid: True,
                    now=200.0,
                )
            )

    def test_check_previous_unclean_exit_writes_report_with_previous_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            heartbeat_path = reports_dir / "app_heartbeat.json"
            heartbeat_path.write_text(
                '{"clean_shutdown": false, "session_id": "old-session", "last_beat_epoch": 100.0, "pid": 777}',
                encoding="utf-8",
            )
            reports: list[tuple[str, str, str, dict[str, object]]] = []

            def add_breadcrumbs(context: dict[str, object]) -> None:
                context["breadcrumb_added"] = True

            def write_report(kind: str, title: str, body: str, **kwargs: object) -> None:
                reports.append((kind, title, body, kwargs))

            self.assertTrue(
                check_previous_unclean_exit(
                    heartbeat_path,
                    session_id="new-session",
                    reports_dir=reports_dir,
                    process_is_alive_fn=lambda _pid: False,
                    add_breadcrumbs_fn=add_breadcrumbs,
                    write_crash_report_fn=write_report,
                    duplicate_report_checker=lambda _reports_dir, _kind, _session_id: False,
                    now=200.0,
                )
            )

            self.assertEqual(1, len(reports))
            kind, title, body, kwargs = reports[0]
            self.assertEqual("previous_session_unclean_exit", kind)
            self.assertIn("did not shut down cleanly", title)
            self.assertIn("previous app session", body)
            self.assertTrue(kwargs["force"])
            context = kwargs["context"]
            self.assertIsInstance(context, dict)
            self.assertEqual(100.0, context["heartbeat_age_seconds"])
            self.assertFalse(context["previous_pid_alive"])
            self.assertTrue(context["breadcrumb_added"])

    def test_check_previous_unclean_exit_suppresses_duplicate_and_records_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            heartbeat_path = reports_dir / "app_heartbeat.json"
            heartbeat_path.write_text(
                '{"clean_shutdown": false, "session_id": "old-session", "last_beat_epoch": 100.0, "pid": 777}',
                encoding="utf-8",
            )
            reports: list[tuple[str, str, str, dict[str, object]]] = []
            events: list[tuple[str, dict[str, object]]] = []

            def write_report(kind: str, title: str, body: str, **kwargs: object) -> None:
                reports.append((kind, title, body, kwargs))

            def record_event(event: str, **fields: object) -> None:
                events.append((event, fields))

            self.assertTrue(
                check_previous_unclean_exit(
                    heartbeat_path,
                    session_id="new-session",
                    reports_dir=reports_dir,
                    process_is_alive_fn=lambda _pid: False,
                    write_crash_report_fn=write_report,
                    record_runtime_event_fn=record_event,
                    duplicate_report_checker=lambda _reports_dir, _kind, _session_id: True,
                    now=125.0,
                )
            )

            self.assertEqual([], reports)
            self.assertEqual("previous_session_unclean_exit_suppressed_duplicate", events[0][0])
            self.assertEqual(
                {
                    "previous_session_id": "old-session",
                    "heartbeat_age_seconds": 25.0,
                    "previous_pid_alive": False,
                },
                events[0][1],
            )

    def test_check_previous_unclean_exit_reports_unreadable_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            heartbeat_path = reports_dir / "app_heartbeat.json"
            heartbeat_path.write_text("{bad json", encoding="utf-8")
            reports: list[tuple[str, str, str, dict[str, object]]] = []

            def write_report(kind: str, title: str, body: str, **kwargs: object) -> None:
                reports.append((kind, title, body, kwargs))

            self.assertFalse(
                check_previous_unclean_exit(
                    heartbeat_path,
                    session_id="new-session",
                    reports_dir=reports_dir,
                    write_crash_report_fn=write_report,
                )
            )

            self.assertEqual(1, len(reports))
            self.assertEqual("previous_session_heartbeat_read_error", reports[0][0])

    def test_heartbeat_payload_is_deterministic_with_explicit_inputs(self) -> None:
        payload = heartbeat_payload(
            "Workbench",
            "1.2.3",
            "42-1700000000000",
            "",
            clean_shutdown=True,
            pid=42,
            now=1_700_000_000.25,
            platform_label="TestOS",
        )

        self.assertEqual("Workbench", payload["app"])
        self.assertEqual("1.2.3", payload["version"])
        self.assertEqual(42, payload["pid"])
        self.assertEqual("running", payload["phase"])
        self.assertTrue(payload["clean_shutdown"])
        self.assertEqual("1700000000000", payload["started_at"])
        self.assertEqual(1_700_000_000.25, payload["last_beat_epoch"])
        self.assertEqual("TestOS", payload["platform"])

    def test_write_app_heartbeat_composes_payload_and_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            heartbeat_path = Path(temp_dir) / "app_heartbeat.json"

            payload = write_app_heartbeat(
                heartbeat_path,
                app_title="Workbench",
                app_version="1.2.3",
                session_id="session-1",
                phase="startup",
                clean_shutdown=True,
            )

            written = read_crash_json_context_file(Path(temp_dir), "app_heartbeat.json")
            self.assertEqual(payload, written)
            self.assertEqual("Workbench", payload["app"])
            self.assertEqual("startup", payload["phase"])
            self.assertTrue(payload["clean_shutdown"])

    def test_format_thread_dump_includes_thread_sections(self) -> None:
        dump = format_thread_dump()

        self.assertIn("--- Thread", dump)
        self.assertIn("test_format_thread_dump_includes_thread_sections", dump)

    def test_start_hang_watchdog_reports_stale_heartbeat(self) -> None:
        stop_event = threading.Event()
        reports: list[tuple[str, str, str, dict[str, object]]] = []

        def write_report(kind: str, title: str, body: str, **kwargs: object) -> None:
            reports.append((kind, title, body, kwargs))
            stop_event.set()

        thread = start_hang_watchdog(
            stop_event,
            lambda: 0.0,
            write_report,
            interval_seconds=0.001,
            stale_seconds=0.001,
            recovered_seconds=0.001,
            thread_name="cdmw-test-hang-watchdog",
            format_thread_dump_fn=lambda: "thread dump",
        )

        thread.join(timeout=1.0)
        stop_event.set()

        self.assertFalse(thread.is_alive())
        self.assertEqual(1, len(reports))
        kind, title, body, kwargs = reports[0]
        self.assertEqual("app_hang_detected", kind)
        self.assertIn("GUI heartbeat stalled", title)
        self.assertIn("heartbeat has not advanced", body)
        self.assertTrue(kwargs["force"])
        self.assertEqual("thread dump", kwargs["context"]["thread_dump"])
        self.assertGreater(float(kwargs["context"]["heartbeat_age_seconds"]), 0.0)

    def test_timing_helpers_normalize_and_format_values(self) -> None:
        merged = merge_timing_maps(
            {"total_s": "1.25", "negative_s": -2, "bad": "x"},
            {"cache_s": 0.5},
            None,
        )

        self.assertEqual({"total_s": 1.25, "negative_s": 0.0, "cache_s": 0.5}, merged)
        self.assertEqual(1.25, timing_value(merged, "total_s"))
        self.assertEqual(0.0, timing_value(merged, "missing"))
        self.assertEqual(
            "Archive timing | source=cache | total=1.25s | cache=0.50s",
            format_timing_summary(
                "Archive timing",
                "cache",
                merged,
                (("total_s", "total"), ("cache_s", "cache")),
            ),
        )
        self.assertEqual(
            "Archive timing | source=unknown | total=0.00s",
            format_timing_summary("Archive timing", "", None, (("total_s", "total"),)),
        )

    def test_expected_cancellation_message_matches_known_cancel_text(self) -> None:
        self.assertTrue(is_expected_cancellation_message("Processing stopped by user."))
        self.assertTrue(is_expected_cancellation_message("Cancelled by user from UI"))
        self.assertFalse(is_expected_cancellation_message("Disk read failed"))
