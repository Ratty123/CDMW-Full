import os
import unittest
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import patch

from cdmw.rendering import native_preview_core
from cdmw.rendering.native_preview_service_state import native_preview_core_service_process_id
from cdmw.models import ArchivePreviewResult
from cdmw.ui.archive_browser.preview_memory import ArchivePreviewMemoryAuditMixin


class _MemoryAuditHarness(ArchivePreviewMemoryAuditMixin):
    def __init__(self, diagnostics: dict[str, object], *, controller: object | None = None) -> None:
        self.current_archive_preview_result = ArchivePreviewResult(
            status="ok",
            native_preview_diagnostics=diagnostics,
        )
        self.archive_d3d11_preview_host = SimpleNamespace(controller=controller) if controller is not None else None

    def _current_archive_entry(self) -> None:
        return None

    def _archive_preview_result_prepared_bytes(self, _result: object) -> int:
        return 0


class ArchivePreviewMemoryTests(unittest.TestCase):
    @staticmethod
    def _snapshot(pid: int) -> dict[str, int]:
        if pid == os.getpid():
            return {"pid": pid, "private_bytes": 100, "working_set_bytes": 80}
        if pid == 4321:
            return {"pid": pid, "private_bytes": 300, "working_set_bytes": 200}
        if pid == 7654:
            return {"pid": pid, "private_bytes": 500, "working_set_bytes": 400}
        return {}

    def test_stopped_service_reports_zero_live_memory_and_separate_last_job_memory(self) -> None:
        harness = _MemoryAuditHarness(
            {
                "native_preview_core_process_pid": 1234,
                "process_private_bytes": 667_000_000,
                "process_working_set_bytes": 637_000_000,
            }
        )

        with (
            patch(
                "cdmw.ui.archive_browser.preview_memory.native_preview_core_service_process_id",
                return_value=0,
            ),
            patch(
                "cdmw.ui.archive_browser.preview_memory._windows_process_memory_snapshot",
                side_effect=self._snapshot,
            ),
        ):
            payload = harness._archive_memory_audit_payload("idle")

        self.assertEqual(payload["preview_core_process_pid"], 0)
        self.assertEqual(payload["preview_core_process_private_bytes"], 0)
        self.assertEqual(payload["preview_core_process_working_set_bytes"], 0)
        self.assertEqual(payload["preview_core_last_job_process_pid"], 1234)
        self.assertEqual(payload["preview_core_last_job_process_private_bytes"], 667_000_000)
        self.assertEqual(payload["preview_core_last_job_process_working_set_bytes"], 637_000_000)
        self.assertEqual(payload["dotnet_preview_process_pid"], 0)
        self.assertEqual(payload["memory_total_private_bytes"], 100)

    def test_live_memory_uses_current_service_pid_instead_of_cached_job_pid(self) -> None:
        harness = _MemoryAuditHarness(
            {
                "native_preview_core_process_pid": 1234,
                "process_private_bytes": 667_000_000,
                "process_working_set_bytes": 637_000_000,
            }
        )

        with (
            patch(
                "cdmw.ui.archive_browser.preview_memory.native_preview_core_service_process_id",
                return_value=4321,
            ),
            patch(
                "cdmw.ui.archive_browser.preview_memory._windows_process_memory_snapshot",
                side_effect=self._snapshot,
            ),
        ):
            payload = harness._archive_memory_audit_payload("active")

        self.assertEqual(payload["preview_core_process_pid"], 4321)
        self.assertEqual(payload["preview_core_process_private_bytes"], 300)
        self.assertEqual(payload["preview_core_process_working_set_bytes"], 200)
        self.assertEqual(payload["preview_core_last_job_process_pid"], 1234)
        self.assertEqual(payload["memory_total_private_bytes"], 400)

    def test_live_dotnet_preview_memory_uses_shared_controller_process(self) -> None:
        controller = SimpleNamespace(
            process_id=7654,
            process_generation=3,
            package_generation=7,
            is_running=True,
        )
        harness = _MemoryAuditHarness({}, controller=controller)

        with (
            patch(
                "cdmw.ui.archive_browser.preview_memory.native_preview_core_service_process_id",
                return_value=0,
            ),
            patch(
                "cdmw.ui.archive_browser.preview_memory._windows_process_memory_snapshot",
                side_effect=self._snapshot,
            ),
        ):
            payload = harness._archive_memory_audit_payload("active")

        self.assertEqual(payload["dotnet_preview_process_pid"], 7654)
        self.assertEqual(payload["dotnet_preview_process_private_bytes"], 500)
        self.assertEqual(payload["dotnet_preview_process_working_set_bytes"], 400)
        self.assertEqual(payload["dotnet_preview_process_generation"], 3)
        self.assertEqual(payload["dotnet_preview_package_generation"], 7)
        self.assertTrue(payload["dotnet_preview_process_running"])
        self.assertEqual(payload["memory_total_private_bytes"], 600)

    def test_service_pid_probe_does_not_wait_for_active_preview_job(self) -> None:
        class RunningProcess:
            pid = 4321

            def poll(self) -> None:
                return None

        client = native_preview_core.NativePreviewCoreServiceClient(Path("preview-core.exe"))
        client._process = RunningProcess()  # type: ignore[assignment]
        locked = Event()
        release = Event()

        def hold_job_lock() -> None:
            with client._lock:
                locked.set()
                release.wait(2.0)

        holder = Thread(target=hold_job_lock)
        holder.start()
        self.assertTrue(locked.wait(1.0))
        try:
            with patch.object(native_preview_core, "_native_preview_core_service", client):
                self.assertEqual(native_preview_core_service_process_id(), 0)
        finally:
            release.set()
            holder.join(1.0)

        self.assertFalse(holder.is_alive())
        self.assertEqual(client.process_id, 4321)


if __name__ == "__main__":
    unittest.main()
