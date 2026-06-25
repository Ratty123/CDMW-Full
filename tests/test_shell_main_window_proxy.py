from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from cdmw.ui.shell import main_window_proxy


class _ActualMainWindow:
    def __init__(self, value: object = None) -> None:
        self.value = value


class ShellMainWindowProxyTests(unittest.TestCase):
    def setUp(self) -> None:
        main_window_proxy._loaded_main_window_class = None  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        main_window_proxy._loaded_main_window_class = None  # type: ignore[attr-defined]

    def test_proxy_loads_actual_class_with_class_only_env(self) -> None:
        env_seen: list[str | None] = []

        def _run_gui() -> type:
            env_seen.append(os.environ.get(main_window_proxy.MAIN_WINDOW_CLASS_ONLY_ENV))
            return _ActualMainWindow

        with patch("cdmw.ui.shell.app_window.run_gui", _run_gui):
            with patch.dict(os.environ, {}, clear=True):
                window = main_window_proxy.MainWindow("loaded")

        self.assertIsInstance(window, _ActualMainWindow)
        self.assertEqual("loaded", window.value)
        self.assertEqual(["1"], env_seen)
        self.assertNotIn(main_window_proxy.MAIN_WINDOW_CLASS_ONLY_ENV, os.environ)

    def test_proxy_restores_existing_class_only_env_value(self) -> None:
        with patch("cdmw.ui.shell.app_window.run_gui", lambda: _ActualMainWindow):
            with patch.dict(os.environ, {main_window_proxy.MAIN_WINDOW_CLASS_ONLY_ENV: "previous"}, clear=True):
                main_window_proxy.MainWindow()
                self.assertEqual("previous", os.environ[main_window_proxy.MAIN_WINDOW_CLASS_ONLY_ENV])

    def test_set_loaded_main_window_class_uses_cached_class(self) -> None:
        main_window_proxy.set_loaded_main_window_class(_ActualMainWindow)

        with patch("cdmw.ui.shell.app_window.run_gui") as run_gui:
            window = main_window_proxy.MainWindow("cached")

        self.assertIsInstance(window, _ActualMainWindow)
        self.assertEqual("cached", window.value)
        run_gui.assert_not_called()


if __name__ == "__main__":
    unittest.main()
