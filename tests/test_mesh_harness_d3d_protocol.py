from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOTNET = ROOT / "tools/dotnet_mesh_editor_experiment"


def _read(name: str) -> str:
    return (DOTNET / name).read_text(encoding="utf-8")


class MeshHarnessVorticeProtocolTests(unittest.TestCase):
    def test_authoring_selection_protocol_keeps_screen_context(self) -> None:
        protocol = _read("ExperimentForm.Protocol.cs")
        viewport = (
            _read("MeshViewport.Input.cs")
            + _read("MeshViewport.SelectionCommands.cs")
            + _read("MeshViewport.SelectionPicking.cs")
        )

        self.assertIn('"screen_brush"', viewport)
        self.assertIn('"screen_region"', viewport)
        self.assertIn('"selection_depth_mode"', viewport)
        self.assertIn("source_submesh_world_view_projections", viewport)
        self.assertIn("Selection", viewport)
        self.assertIn("selection_update", protocol)

    def test_authoring_mesh_updates_acknowledge_monotonic_revisions(self) -> None:
        source = _read("ExperimentForm.Protocol.cs")

        self.assertIn("ProtocolEditRevision(root)", source)
        self.assertIn('"preview_vertex_update_ack"', source)
        self.assertIn('"preview_triangle_update_ack"', source)
        self.assertIn('reason = "stale_or_out_of_order"', source)
        self.assertIn('["edit_revision"] = revision', source)
        self.assertIn('["revision"] = revision', source)

    def test_preview_profile_explicitly_rejects_mutation_commands(self) -> None:
        source = _read("ExperimentForm.ProfileProtocol.cs")

        self.assertIn("IsPreviewProfileMutation", source)
        self.assertIn('"protocol_command_rejected"', source)
        self.assertIn('"preview_profile_read_only"', source)
        self.assertIn('"preview"', source)

    def test_resident_package_replacement_is_acknowledged(self) -> None:
        source = _read("ExperimentForm.PackageProtocol.cs") + _read("ExperimentForm.Protocol.cs")

        self.assertIn('"package_load_request"', source)
        self.assertIn('"package_load_applied"', source)
        self.assertIn('"package_load_failed"', source)
        self.assertIn("generation", source)

    def test_shared_python_controller_is_the_only_process_owner(self) -> None:
        source = (ROOT / "cdmw/ui/preview/dotnet_session.py").read_text(encoding="utf-8")

        self.assertIn("profile=self.profile.value", source)
        self.assertIn("process.start()", source)
        self.assertIn("_package_event_is_current", source)
        self.assertNotIn("WM_COPYDATA", source)
        self.assertFalse((ROOT / "tools/mesh_harness/native_protocol.py").exists())

        command_source = (ROOT / "cdmw/services/mesh_dotnet_experiment.py").read_text(encoding="utf-8")
        self.assertIn('"--profile"', command_source)


if __name__ == "__main__":
    unittest.main()
