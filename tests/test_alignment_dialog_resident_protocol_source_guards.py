from __future__ import annotations

import unittest

from tests.source_function_map import function_source
from tests.static_replacement_source_support import static_replacement_ui_implementation_source
from tests.test_alignment_dialog_source_guards import ROOT


class AlignmentDialogResidentProtocolSourceGuardTests(unittest.TestCase):
    def test_resident_gizmo_drag_defers_the_authoritative_scene_frame(self) -> None:
        """A live gizmo drag must not publish a scene frame per pointer sample."""
        placement_handler = function_source(
            static_replacement_ui_implementation_source(ROOT),
            "_mesh_editor_apply_dotnet_placement_state",
        )
        protocol_source = (
            ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_protocol.py"
        ).read_text(encoding="utf-8")

        self.assertIn("phase: str = 'end'", placement_handler)
        self.assertIn("str(phase or 'end').strip().lower() == 'update'", placement_handler)
        deferred = placement_handler.index("str(phase or 'end').strip().lower() == 'update'")
        published = placement_handler.index("_queue_global_transform_preview_update()")
        self.assertLess(deferred, published)
        self.assertIn('payload.get("placement_phase", "end")', protocol_source)


if __name__ == "__main__":
    unittest.main()
