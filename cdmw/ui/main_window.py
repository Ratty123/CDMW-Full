from __future__ import annotations

from cdmw.domain.mesh.validation import mesh_import_mode_availability
from cdmw.ui.shell.main_window_proxy import MainWindow


def run_gui() -> int:
    from cdmw.ui.shell.run_gui import run_gui as _run_gui

    return int(_run_gui())

__all__ = ["MainWindow", "mesh_import_mode_availability", "run_gui"]
