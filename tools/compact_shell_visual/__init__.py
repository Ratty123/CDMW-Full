"""Focused owners for the Compact Workspace visual capture harness."""

from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Suppress startup work and dialogs. On Windows, retain the native QPA plugin
# so PrintWindow can include the title bar and resident D3D child windows.
os.environ.setdefault("CDMW_GUI_STARTUP_SMOKE", "1")
if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
