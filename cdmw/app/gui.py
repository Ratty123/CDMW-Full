from __future__ import annotations


def run_gui_workflow() -> int:
    from cdmw.ui.main_window import run_gui

    return int(run_gui())
