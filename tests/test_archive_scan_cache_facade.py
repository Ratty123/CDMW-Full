from __future__ import annotations

import threading
import unittest
from pathlib import Path
from unittest import mock

from cdmw.core import archive_scan_cache


class ArchiveScanCacheFacadeTests(unittest.TestCase):
    def test_scan_cache_facade_forwards_progress_and_cancellation_contract(self) -> None:
        package_root = Path("game")
        on_log = mock.Mock()
        on_progress = mock.Mock()
        on_breadcrumb = mock.Mock()
        stop_event = threading.Event()
        with mock.patch(
            "cdmw.core.archive_format.scan_archive_entries",
            return_value=[],
        ) as owner:
            self.assertEqual(
                [],
                archive_scan_cache.scan_archive_entries(
                    package_root,
                    on_log=on_log,
                    on_progress=on_progress,
                    on_breadcrumb=on_breadcrumb,
                    stop_event=stop_event,
                ),
            )

        owner.assert_called_once_with(
            package_root,
            on_log=on_log,
            on_progress=on_progress,
            on_breadcrumb=on_breadcrumb,
            stop_event=stop_event,
        )


if __name__ == "__main__":
    unittest.main()
