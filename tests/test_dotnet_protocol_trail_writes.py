"""The helper protocol trail has to reach disk without owning the UI thread.

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
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import cdmw.ui.mesh_editor.tab_dotnet_protocol as protocol
from cdmw.services.mesh_interaction_diagnostics import MeshInteractionFlightRecorder


class TestDotNetProtocolTrail:
    def test_the_trail_resolves_from_the_crash_dir_environment(self) -> None:
        with TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"CDMW_CRASH_DIR": directory}):
                path = protocol._dotnet_protocol_trail_path()
            assert path is not None, "the protocol trail resolved to no path at all"
            assert Path(path).parent == Path(directory)
            assert Path(path).name == "dotnet_protocol_current.jsonl"

    def test_a_written_event_reaches_the_file(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "dotnet_protocol_current.jsonl"
            recorder = MeshInteractionFlightRecorder(lambda: path)
            assert recorder.record(
                "protocol", "helper_to_host", {"event": "package_loaded", "generation": 4}
            )
            assert recorder.record(
                "protocol", "helper_to_host", {"event": "presentation_state_update"}
            )
            assert recorder.shutdown(), "the background trail did not drain"
            assert path.is_file(), "no protocol trail file was created"
            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line
            ]
        assert [row["event"] for row in rows] == [
            "package_loaded",
            "presentation_state_update",
        ]
        assert rows[0]["generation"] == 4
        assert all("recorded_at_utc" in row for row in rows)
        assert all("monotonic_ns" in row for row in rows)

    def test_the_trail_resolves_without_the_environment_variable(self) -> None:
        """A session started outside the app's own startup still records."""

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CDMW_CRASH_DIR", None)
            path = protocol._dotnet_protocol_trail_path()
        assert path is not None, "the trail gave up when CDMW_CRASH_DIR was unset"
        assert Path(path).name == "dotnet_protocol_current.jsonl"

    def test_the_trail_stops_at_its_size_cap(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "dotnet_protocol_current.jsonl"
            recorder = MeshInteractionFlightRecorder(lambda: path, max_bytes=400)
            assert recorder.record("protocol", "helper_to_host", {"event": "first"})
            assert recorder.record(
                "protocol",
                "helper_to_host",
                {"event": "past_the_cap", "payload": "x" * 500},
            )
            assert recorder.shutdown()
            body = path.read_text(encoding="utf-8")
            snapshot = recorder.snapshot()
        assert "first" in body
        assert "past_the_cap" not in body
        assert snapshot["dropped_size_cap"] == 1

    def test_protocol_wrapper_only_enqueues_the_event(self) -> None:
        with patch.object(protocol, "record_mesh_interaction_event", return_value=True) as record:
            assert protocol._write_dotnet_protocol_trail(
                {"event": "stroke_end", "request_id": 14}
            )
        record.assert_called_once_with(
            "protocol",
            "helper_to_host",
            {"event": "stroke_end", "request_id": 14},
            critical=True,
        )

    def test_internal_decision_carries_session_and_process_generation(self) -> None:
        target = SimpleNamespace(
            standalone_controller=SimpleNamespace(active_session_id="session-a"),
            standalone_dotnet_process_generation=7,
            standalone_live_stroke_dispatcher=None,
        )
        with patch.object(protocol, "_write_dotnet_protocol_trail") as write:
            protocol.MeshEditorDotNetProtocolMixin._record_dotnet_interaction_decision(
                target,
                "mesh_edit_stroke_queued",
                request_id=19,
            )
        write.assert_called_once_with(
            {
                "event": "mesh_edit_stroke_queued",
                "session_id": "session-a",
                "process_generation": 7,
                "request_id": 19,
            },
            direction="host_internal",
            kind="host_decision",
        )
