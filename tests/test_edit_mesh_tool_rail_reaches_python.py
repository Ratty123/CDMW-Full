"""Every armable tool on the Edit Mesh rail must reach a tool on this side.

The rail is the only tool picker visible in Edit Mesh, and arming one sends
`tool_changed` to the host. The host maps that key through
`_DOTNET_TOOL_TO_DIALOG_TOOL`, and a key with no entry is dropped on purpose --
that is how command pages are ignored. Orbit is the one non-rail mapping: it is
the neutral navigation button in Viewport and must clear any armed tool. The
same silence is what a
genuinely missing entry produces: the rail lights the row, the host adopts
nothing, and the next control refresh republishes the stale tool and takes the
reader's choice away. Nothing fails, and nothing works.

So the two lists are pinned against each other here. A row added to the C#
contract as a `Tool` without a Python entry fails this, rather than shipping as
a button that highlights and does nothing.
"""

import re
import unittest
from pathlib import Path

from cdmw.ui.archive_browser.static_replacement_mesh_edit_actions import (
    _DOTNET_TOOL_TO_DIALOG_TOOL,
)

CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "dotnet_mesh_editor_experiment"
    / "EditMeshToolListContract.cs"
)

_ROW = re.compile(
    r"new\(\s*ToolListRowKind\.(?P<kind>Tool|CommandPage)\s*,\s*Keys\.(?P<key>\w+)\s*,",
)


def _rail_rows() -> list[tuple[str, str]]:
    """(kind, key) for every row, read from the C# contract itself."""

    source = CONTRACT.read_text(encoding="utf-8", errors="replace")
    constants = dict(re.findall(r'public const string (\w+)\s*=\s*"([^"]+)"\s*;', source))
    rows: list[tuple[str, str]] = []
    for match in _ROW.finditer(source):
        name = match.group("key")
        rows.append((match.group("kind"), constants[name]))
    return rows


class EditMeshToolRailContractTests(unittest.TestCase):
    def test_the_contract_is_readable_and_not_empty(self) -> None:
        """A regex that stops matching would make every other test vacuous."""

        self.assertTrue(CONTRACT.is_file(), f"missing {CONTRACT}")
        rows = _rail_rows()
        self.assertEqual(len(rows), 9, "the mesh-only rail row inventory changed")
        self.assertIn(("Tool", "select"), rows)
        self.assertIn(("CommandPage", "topology"), rows)

    def test_every_armable_rail_tool_maps_to_a_dialog_tool(self) -> None:
        armable = [key for kind, key in _rail_rows() if kind == "Tool"]
        missing = [key for key in armable if key not in _DOTNET_TOOL_TO_DIALOG_TOOL]
        self.assertEqual(
            missing,
            [],
            "these rail rows arm a tool the host has no mapping for, so arming "
            f"them highlights the row and changes nothing: {missing}",
        )

    def test_command_pages_deliberately_map_to_nothing(self) -> None:
        """Topology, Morph and Viewport open a page without arming a tool.

        A mapping for one of these would arm a tool the reader did not pick.
        """

        pages = [key for kind, key in _rail_rows() if kind == "CommandPage"]
        self.assertTrue(pages)
        wrongly_mapped = [key for key in pages if key in _DOTNET_TOOL_TO_DIALOG_TOOL]
        self.assertEqual(wrongly_mapped, [], f"command pages must not arm a tool: {wrongly_mapped}")

    def test_the_host_maps_only_the_rail_and_the_neutral_orbit_button(self) -> None:
        """A stale mapping is a tool this side expects and no visible control sends."""

        rail_keys = {key for _kind, key in _rail_rows()}
        non_rail = sorted(set(_DOTNET_TOOL_TO_DIALOG_TOOL) - rail_keys)
        self.assertEqual(non_rail, ["orbit"])
        self.assertEqual(_DOTNET_TOOL_TO_DIALOG_TOOL["orbit"], ("orbit", ""))

    def test_every_mapped_action_key_is_a_real_mesh_editor_action(self) -> None:
        """The second half of the mapping names an action key, not free text."""

        from cdmw.ui.mesh_editor.actions import MESH_EDITOR_ACTIONS

        known = {action.key for action in MESH_EDITOR_ACTIONS}
        unknown = sorted(
            action_key
            for _tool, action_key in _DOTNET_TOOL_TO_DIALOG_TOOL.values()
            if action_key and action_key not in known
        )
        self.assertEqual(unknown, [], f"mapping names action keys that do not exist: {unknown}")


if __name__ == "__main__":
    unittest.main()
