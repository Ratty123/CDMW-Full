"""Every tool routed to the native core must name an operation it implements.

An action the service marks native is sent to `cdmw_mesh_core` as an operation
string. If the core does not implement that string it answers a non-ok status,
the runner turns that into `None`, and the user gets a tool that refuses every
time they use it -- with, until recently, no way to tell that apart from the
native module being absent entirely.

One action is deliberately not sent under its own name: `delete_loose_vertices`
is translated to `compact_orphans` in `_native_editor_edit_payload`. That alias
is asserted here rather than assumed, because losing it would look exactly like
the tool being unimplemented.
"""

import re
import unittest
from pathlib import Path

from cdmw.services.mesh_service import _NATIVE_EDITOR_SESSION_ACTIONS

NATIVE_SRC = Path(__file__).resolve().parents[1] / "native" / "cdmw_mesh_core" / "src"

# Sent to the core under another operation's name. Key is the service action,
# value is the operation the core actually implements.
DELIBERATE_ALIASES = {"delete_loose_vertices": "compact_orphans"}


def _native_operation_strings() -> set[str]:
    """Every lowercase string literal the C++ core compares against."""

    found: set[str] = set()
    for path in sorted(NATIVE_SRC.rglob("*.cpp")) + sorted(NATIVE_SRC.rglob("*.hpp")):
        text = path.read_text(encoding="utf-8", errors="replace")
        found.update(re.findall(r'"([a-z][a-z0-9_]{2,})"', text))
    return found


class NativeOperationCoverageTests(unittest.TestCase):
    def test_the_native_sources_are_present_and_readable(self) -> None:
        self.assertTrue(NATIVE_SRC.is_dir(), f"missing {NATIVE_SRC}")
        strings = _native_operation_strings()
        self.assertGreater(len(strings), 50, "the native source scan found almost nothing")
        self.assertIn("transform", strings)
        self.assertIn("brush", strings)

    def test_every_natively_routed_action_exists_in_the_core(self) -> None:
        strings = _native_operation_strings()
        missing = []
        for action in sorted(_NATIVE_EDITOR_SESSION_ACTIONS):
            operation = DELIBERATE_ALIASES.get(action, action)
            if operation not in strings:
                missing.append(f"{action} (sent as {operation!r})")
        self.assertEqual(
            missing,
            [],
            "these tools are routed to the native core, which does not implement "
            f"the operation they name, so each refuses every use: {missing}",
        )

    def test_the_delete_loose_alias_is_still_applied(self) -> None:
        """Without the alias this tool names an operation the core lacks."""

        from cdmw.services.mesh_service import _native_editor_edit_payload

        payload = _native_editor_edit_payload("delete_loose_vertices", {})
        self.assertEqual(
            payload.get("operation"),
            "compact_orphans",
            "delete_loose_vertices stopped being translated, so it now names an "
            "operation the native core does not implement",
        )

    def test_an_unaliased_action_is_sent_under_its_own_name(self) -> None:
        from cdmw.services.mesh_service import _native_editor_edit_payload

        self.assertEqual(_native_editor_edit_payload("subdivide", {}).get("operation"), "subdivide")

    def test_the_alias_table_has_no_stale_entries(self) -> None:
        stale = sorted(set(DELIBERATE_ALIASES) - set(_NATIVE_EDITOR_SESSION_ACTIONS))
        self.assertEqual(stale, [], f"aliases for actions no longer routed natively: {stale}")


if __name__ == "__main__":
    unittest.main()
