from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cdmw_app


def _make_cdmw_mei(root: Path, name: str, *, marker_pid: int | None = None) -> Path:
    runtime_dir = root / name
    (runtime_dir / "assets").mkdir(parents=True)
    (runtime_dir / "assets" / "cdmw.ico").write_bytes(b"icon")
    if marker_pid is not None:
        (runtime_dir / cdmw_app.PYINSTALLER_RUNTIME_MARKER).write_text(
            json.dumps(
                {
                    "app": "CrimsonDesertModWorkbench",
                    "pid": marker_pid,
                }
            ),
            encoding="utf-8",
        )
    return runtime_dir


class PyInstallerTempCleanupTests(unittest.TestCase):
    def test_startup_maintenance_scheduler_runs_cleanup_asynchronously(self) -> None:
        with (
            mock.patch.object(cdmw_app, "_prepare_pyinstaller_runtime_temp_cleanup") as runtime_cleanup,
            mock.patch.object(cdmw_app, "_prepare_app_temp_cache_cleanup") as cache_cleanup,
        ):
            cdmw_app._startup_maintenance_thread = None
            cdmw_app._schedule_startup_maintenance(delay_seconds=0)
            thread = cdmw_app._startup_maintenance_thread
            self.assertIsNotNone(thread)
            thread.join(timeout=5)

        runtime_cleanup.assert_called_once()
        cache_cleanup.assert_called_once()

    def test_dead_marked_runtime_dir_is_removed_without_touching_current_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_root = Path(temp_text)
            current_dir = _make_cdmw_mei(temp_root, "_MEIcurrent", marker_pid=os.getpid())
            stale_dir = _make_cdmw_mei(temp_root, "_MEIstale", marker_pid=999999)

            with mock.patch.object(cdmw_app, "_pid_is_alive", return_value=False):
                removed, failed = cdmw_app._cleanup_stale_pyinstaller_runtime_dirs(
                    temp_root=temp_root,
                    current_meipass=current_dir,
                )

            self.assertEqual((removed, failed), (1, 0))
            self.assertTrue(current_dir.exists())
            self.assertFalse(stale_dir.exists())

    def test_live_marked_runtime_dir_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_root = Path(temp_text)
            current_dir = _make_cdmw_mei(temp_root, "_MEIcurrent", marker_pid=os.getpid())
            live_dir = _make_cdmw_mei(temp_root, "_MEIlive", marker_pid=12345)

            with mock.patch.object(cdmw_app, "_pid_is_alive", return_value=True):
                removed, failed = cdmw_app._cleanup_stale_pyinstaller_runtime_dirs(
                    temp_root=temp_root,
                    current_meipass=current_dir,
                )

            self.assertEqual((removed, failed), (0, 0))
            self.assertTrue(live_dir.exists())

    def test_unmarked_runtime_dirs_require_age_and_own_app_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_root = Path(temp_text)
            current_dir = _make_cdmw_mei(temp_root, "_MEIcurrent", marker_pid=os.getpid())
            recent_dir = _make_cdmw_mei(temp_root, "_MEIrecent")
            old_dir = _make_cdmw_mei(temp_root, "_MEIold")
            foreign_dir = temp_root / "_MEIforeign"
            (foreign_dir / "assets").mkdir(parents=True)
            (foreign_dir / "assets" / "other.ico").write_bytes(b"foreign")

            now = 1_000_000.0
            os.utime(recent_dir, (now - 10, now - 10))
            os.utime(old_dir, (now - 7200, now - 7200))
            os.utime(foreign_dir, (now - 7200, now - 7200))
            removed, failed = cdmw_app._cleanup_stale_pyinstaller_runtime_dirs(
                temp_root=temp_root,
                current_meipass=current_dir,
                now=now,
                unmarked_min_age_seconds=1800,
            )

            self.assertEqual((removed, failed), (1, 0))
            self.assertTrue(recent_dir.exists())
            self.assertFalse(old_dir.exists())
            self.assertTrue(foreign_dir.exists())


if __name__ == "__main__":
    unittest.main()
