from __future__ import annotations

import unittest

from PySide6.QtGui import QIcon

from cdmw.ui.shell.icon_controller import AppWindowIconEventFilter, apply_windows_app_user_model_id


class ShellIconControllerTests(unittest.TestCase):
    def test_windows_app_user_model_id_helper_is_callable(self) -> None:
        self.assertIsNone(apply_windows_app_user_model_id())

    def test_app_window_icon_event_filter_updates_icon(self) -> None:
        event_filter = AppWindowIconEventFilter(QIcon())
        self.assertIsInstance(event_filter, AppWindowIconEventFilter)
        event_filter.set_app_icon(QIcon())


if __name__ == "__main__":
    unittest.main()
