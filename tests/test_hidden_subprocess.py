import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from cdmw.core.common import ProcessTimeoutExpired, hidden_subprocess_kwargs, run_process_with_cancellation


class HiddenSubprocessTests(unittest.TestCase):
    def test_windows_hidden_subprocess_kwargs_hide_window(self) -> None:
        kwargs = hidden_subprocess_kwargs()
        if os.name != "nt":
            self.assertEqual({}, kwargs)
            return

        startupinfo = kwargs.get("startupinfo")
        self.assertIsInstance(startupinfo, subprocess.STARTUPINFO)
        self.assertEqual(int(getattr(subprocess, "SW_HIDE", 0)), startupinfo.wShowWindow)
        self.assertTrue(startupinfo.dwFlags & int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0)))
        if getattr(subprocess, "CREATE_NO_WINDOW", 0):
            self.assertEqual(getattr(subprocess, "CREATE_NO_WINDOW", 0), kwargs.get("creationflags"))

    def test_run_process_timeout_terminates_process(self) -> None:
        warnings: list[float] = []
        with self.assertRaises(ProcessTimeoutExpired):
            run_process_with_cancellation(
                [sys.executable, "-c", "import time; time.sleep(5)"],
                timeout_seconds=0.3,
                timeout_warning_interval_seconds=0.1,
                on_timeout_warning=warnings.append,
            )

        self.assertTrue(warnings)

    def test_run_process_without_timeout_still_returns_output(self) -> None:
        return_code, stdout, stderr = run_process_with_cancellation(
            [sys.executable, "-c", "print('ok')"],
        )

        self.assertEqual(0, return_code)
        self.assertEqual("ok", stdout.strip())
        self.assertEqual("", stderr)

    def test_run_process_timeout_stops_spawned_child_process(self) -> None:
        child_pid = 0
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_path = Path(temp_dir) / "child.pid"
            child_code = "import time; time.sleep(30)"
            parent_code = (
                "import pathlib,subprocess,sys,time;"
                "child=subprocess.Popen([sys.executable,'-c',sys.argv[2]]);"
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid),encoding='utf-8');"
                "time.sleep(30)"
            )
            try:
                with self.assertRaises(ProcessTimeoutExpired):
                    run_process_with_cancellation(
                        [sys.executable, "-c", parent_code, str(pid_path), child_code],
                        timeout_seconds=0.8,
                    )
                child_pid = int(pid_path.read_text(encoding="utf-8"))
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline and _pid_exists(child_pid):
                    time.sleep(0.05)
                self.assertFalse(_pid_exists(child_pid), f"spawned child process still alive: pid={child_pid}")
            finally:
                if child_pid and _pid_exists(child_pid):
                    try:
                        os.kill(child_pid, 9)
                    except OSError:
                        pass


def _pid_exists(process_id: int) -> bool:
    try:
        os.kill(int(process_id), 0)
    except OSError:
        return False
    return True


if __name__ == "__main__":
    unittest.main()
