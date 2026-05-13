import os
import subprocess
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
