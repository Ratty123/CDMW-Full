from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.modding import mesh_native_dispatch


class NativeMeshCoreServiceDispatchTests(unittest.TestCase):
    def test_editor_inline_failure_is_not_replayed_as_a_file_job(self) -> None:
        with (
            patch.object(mesh_native_dispatch, "_run_native_mesh_core_service_inline_job", return_value=None) as inline,
            patch.object(mesh_native_dispatch.tempfile, "mkdtemp", side_effect=AssertionError("stateful command replayed")),
        ):
            report = mesh_native_dispatch._run_native_mesh_core_service_job(
                Path("cdmw-mesh-core.exe"),
                "mesh-editor-session-json",
                {"command": "apply"},
                timeout_seconds=1.0,
            )

        self.assertIsNone(report)
        inline.assert_called_once()


if __name__ == "__main__":
    unittest.main()
