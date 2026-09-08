from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_pytest_drains_deferred_deletes_and_shuts_down_qt_before_python(tmp_path: Path) -> None:
    shutil.copyfile(Path(__file__).with_name("conftest.py"), tmp_path / "conftest.py")
    (tmp_path / "test_session.py").write_text(
        "from PySide6.QtWidgets import QApplication, QWidget\n"
        "from shiboken6 import isValid\n"
        "app = QApplication([])\n"
        "panels = []\n"
        "def test_schedule_delete():\n"
        "    panel = QWidget()\n"
        "    panel.show()\n"
        "    panels.append(panel)\n"
        "    panel.deleteLater()\n"
        "def test_session_owned_widget():\n"
        "    panels.append(QWidget())\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-X", "faulthandler",
            "-c",
            "import pytest; "
            "status = pytest.main(['-q', '-p', 'no:cacheprovider', 'test_session.py']); "
            "from PySide6.QtWidgets import QApplication; "
            "assert QApplication.instance() is None, 'Qt survived pytest teardown'; "
            "import test_session; "
            "assert not any(test_session.isValid(panel) for panel in test_session.panels); "
            "raise SystemExit(status)",
        ],
        cwd=tmp_path,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
