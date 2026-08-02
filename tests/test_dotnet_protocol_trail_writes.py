"""The helper protocol trail has to actually reach disk.

It shipped resolving its directory through `from cdmw.ui.shell.app_window import
crash_reports_dir`, which is a local inside that module's entry point rather
than a module attribute. The import raised `ImportError` into the guard that
exists to keep diagnostics from disturbing the editor, the path was pinned to
`None`, and every protocol event was dropped for the life of the process. The
file simply never appeared, which reads as "the helper did nothing" rather than
"the log is broken" -- the worst way for instrumentation to fail.
"""

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import cdmw.ui.mesh_editor.tab_dotnet_protocol as protocol


class DotNetProtocolTrailTests(unittest.TestCase):
    def setUp(self) -> None:
        # The path resolves once per process and caches the answer.
        self._saved = dict(protocol._PROTOCOL_TRAIL_STATE)
        protocol._PROTOCOL_TRAIL_STATE.update({"path": None, "resolved": False, "bytes": 0})

    def tearDown(self) -> None:
        protocol._PROTOCOL_TRAIL_STATE.clear()
        protocol._PROTOCOL_TRAIL_STATE.update(self._saved)

    def test_the_trail_resolves_from_the_crash_dir_environment(self) -> None:
        with TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"CDMW_CRASH_DIR": directory}):
                path = protocol._dotnet_protocol_trail_path()
            self.assertIsNotNone(path, "the protocol trail resolved to no path at all")
            self.assertEqual(Path(path).parent, Path(directory))
            self.assertEqual(Path(path).name, "dotnet_protocol_current.jsonl")

    def test_a_written_event_reaches_the_file(self) -> None:
        with TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"CDMW_CRASH_DIR": directory}):
                protocol._write_dotnet_protocol_trail({"event": "package_loaded", "generation": 4})
                protocol._write_dotnet_protocol_trail({"event": "presentation_state_update"})
                path = Path(directory) / "dotnet_protocol_current.jsonl"
                self.assertTrue(path.is_file(), "no protocol trail file was created")
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        self.assertEqual([row["event"] for row in rows], ["package_loaded", "presentation_state_update"])
        self.assertEqual(rows[0]["generation"], 4)
        self.assertTrue(all("t" in row for row in rows), "events carry no timestamp to correlate on")

    def test_the_trail_resolves_without_the_environment_variable(self) -> None:
        """A session started outside the app's own startup still records."""

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CDMW_CRASH_DIR", None)
            path = protocol._dotnet_protocol_trail_path()
        self.assertIsNotNone(path, "the trail gave up when CDMW_CRASH_DIR was unset")
        self.assertEqual(Path(path).name, "dotnet_protocol_current.jsonl")

    def test_the_trail_stops_at_its_size_cap(self) -> None:
        with TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"CDMW_CRASH_DIR": directory}):
                protocol._write_dotnet_protocol_trail({"event": "first"})
                protocol._PROTOCOL_TRAIL_STATE["bytes"] = protocol._PROTOCOL_TRAIL_MAX_BYTES
                protocol._write_dotnet_protocol_trail({"event": "past_the_cap"})
                path = Path(directory) / "dotnet_protocol_current.jsonl"
                body = path.read_text(encoding="utf-8")
        self.assertIn("first", body)
        self.assertNotIn("past_the_cap", body)


if __name__ == "__main__":
    unittest.main()
