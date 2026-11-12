"""P15 step 1: the rail switches workspaces around the one scene."""
from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.shell.navigation_controller import NavigationControllerMixin


class _Shell(NavigationControllerMixin):
    def __init__(self, *, editing: bool) -> None:
        self.activated: list[str] = []
        self.promotions = 0

        def promote() -> None:
            self.promotions += 1
            self._activate_tool_key("mesh_editor")  # as Browse's Promote does, to size the host first

        self.archive = SimpleNamespace(editing_in_place=editing, _promote_edit_to_tab=promote)
        self._tool_widgets_by_key = {"mesh_editor": SimpleNamespace(isEnabled=lambda: True),
                                     "archive_browser": SimpleNamespace(isEnabled=lambda: True)}

    def _activate_tool_widget(self, widget) -> None:
        key = next(key for key, value in self._tool_widgets_by_key.items() if value is widget)
        self.activated.append(key)


def test_switching_to_the_mesh_editor_takes_an_edit_in_browse_with_it() -> None:
    shell = _Shell(editing=True)
    shell._activate_tool_key("mesh_editor")
    # The edit moved once, and the Mesh Editor was shown by the move itself.
    assert shell.promotions == 1 and shell.activated == ["mesh_editor"]
    # Back to Browse: nothing moves; Browse's view follows the edit read-only (P4 V5).
    shell._activate_tool_key("archive_browser")
    assert shell.promotions == 1 and shell.activated == ["mesh_editor", "archive_browser"]


def test_without_an_edit_in_browse_the_rail_only_switches() -> None:
    shell = _Shell(editing=False)
    shell._activate_tool_key("mesh_editor")
    assert shell.promotions == 0 and shell.activated == ["mesh_editor"]
