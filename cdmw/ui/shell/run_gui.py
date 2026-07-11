from __future__ import annotations


def run_gui() -> int:
    from cdmw.ui.shell.app_window import run_gui as _run_gui

    return int(_run_gui())

__all__ = ["run_gui"]
