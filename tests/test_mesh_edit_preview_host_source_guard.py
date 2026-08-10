from __future__ import annotations

import unittest

from tests.test_mesh_edit_responsiveness_source_guards import _function_source, _read


class MeshEditPreviewHostSourceGuardTests(unittest.TestCase):
    def test_host_highlight_setters_do_not_republish_the_display_block(self) -> None:
        # The shared host's copy of display.grid_visible starts False and is
        # never synced from the dialog's Grid checkbox, so a highlight update
        # that carries it switches the grid off on every part selection. The
        # helper preserves current display state when the key is absent.
        host_source = _read("cdmw/ui/preview/dotnet_host.py")
        protocol_source = _read("cdmw/ui/preview/dotnet_host_protocol.py")
        for setter in (
            "def set_highlighted_source_submeshes(",
            "def set_highlighted_alignment_submeshes(",
            "def set_hidden_source_submeshes(",
        ):
            body = host_source[host_source.index(setter):]
            body = body[: body.index("\n    def ", 1)]
            # The setters now send a targeted highlights delta rather than
            # resending the whole remembered state. What matters to this guard is
            # unchanged: they go through the without_display helper, never the
            # plain one that would carry display.grid_visible with them.
            self.assertIn(
                "_remember_presentation_state_without_display(",
                body,
                setter,
            )
            self.assertNotIn("self._remember_presentation_state(", body, setter)
        without_display_body = _function_source(
            protocol_source, "_remember_presentation_state_without_display"
        )
        self.assertIn('if key != "display"', without_display_body)
        self.assertIn('"presentation_state_update"', without_display_body)
