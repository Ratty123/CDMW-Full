from __future__ import annotations

import os

MAIN_WINDOW_CLASS_ONLY_ENV = "CDMW_MAIN_WINDOW_CLASS_ONLY"

_loaded_main_window_class: type | None = None


def set_loaded_main_window_class(main_window_class: type) -> None:
    global _loaded_main_window_class
    _loaded_main_window_class = main_window_class


def _load_actual_main_window_class() -> type:
    if _loaded_main_window_class is not None:
        return _loaded_main_window_class

    previous_flag = os.environ.get(MAIN_WINDOW_CLASS_ONLY_ENV)
    os.environ[MAIN_WINDOW_CLASS_ONLY_ENV] = "1"
    try:
        from cdmw.ui.shell.app_window import run_gui

        loaded = run_gui()
    finally:
        if previous_flag is None:
            os.environ.pop(MAIN_WINDOW_CLASS_ONLY_ENV, None)
        else:
            os.environ[MAIN_WINDOW_CLASS_ONLY_ENV] = previous_flag

    if not isinstance(loaded, type):
        raise RuntimeError("MainWindow class could not be loaded from the shell GUI implementation.")
    set_loaded_main_window_class(loaded)
    return loaded


class MainWindow:
    """Compatibility proxy for the shell MainWindow implementation."""

    def __new__(cls, *args: object, **kwargs: object) -> object:
        actual_class = _load_actual_main_window_class()
        return actual_class(*args, **kwargs)


__all__ = ["MAIN_WINDOW_CLASS_ONLY_ENV", "MainWindow", "set_loaded_main_window_class"]
