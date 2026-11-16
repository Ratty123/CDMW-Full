"""The automation bridge's Drafts & Mods commands drive the real page as clicks would.

They exist so the built exe's pass can check Combine into One Mod, its refusal of
two builds of one game file, and the Game file column (Work A item 6).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import pytest

from cdmw.automation import saved_work_commands
from cdmw.services.mesh_saved_work_service import add_built_mod_folder
from cdmw.ui.mesh_editor import saved_work_combine
from tests.test_mesh_build_combine import SHOULDER, UPPER, _build
from tests.test_saved_work_combine_page import _owned_history, _wait, app, combine  # noqa: F401


@pytest.fixture
def window(combine, monkeypatch):  # noqa: F811 - the imported fixture
    import cdmw.app.app_folder as app_folder

    monkeypatch.setattr(app_folder, "cdmw_folder", lambda: combine.tmp)
    shown: list[str] = []
    shell = SimpleNamespace(saved_work_tab=combine.page, _activate_tool_key=shown.append)
    return SimpleNamespace(shell=shell, shown=shown)


def test_rows_list_the_table_and_the_game_file_text_the_column_draws(combine, window):  # noqa: F811
    listed = saved_work_commands.saved_work_rows(window, {})
    assert window.shown == ["saved_work"]
    assert "Game file" in listed["header"]
    assert sorted(row["display_name"] for row in listed["rows"]) == ["Skirt edit", "Wing piece"]
    assert all(row["built"] and row["mod_root"] for row in listed["rows"])
    assert sorted(row["mod_root"] for row in listed["shown"]) == sorted(row["mod_root"] for row in listed["rows"])
    assert sorted(row["mod_root"] for row in listed["shown"]) == sorted([str(combine.skirt), str(combine.wing)])
    # Whatever the column's width, the drawn text keeps each file name whole.
    for path, row in zip(sorted([UPPER, SHOULDER], key=lambda p: p.rsplit("/", 1)[1]),
                         sorted(listed["shown"], key=lambda r: r["game_file_drawn"].rsplit("/", 1)[-1])):
        assert row["game_file_drawn"].endswith(path.rsplit("/", 1)[1])
        assert path in row["game_file_tooltip"]


def test_combine_review_write_and_refusal_through_the_commands(combine, window):  # noqa: F811
    app = combine.app
    roots = [str(combine.skirt), str(combine.wing)]
    started = saved_work_commands.saved_work_combine(window, {"mod_roots": roots})
    assert started == {"selected": 2, "reason": "", "started": True}
    _wait(app, lambda: saved_work_commands.saved_work_combine_state(window, {})["stage"]
          != saved_work_combine.STAGE_CHECKING)
    review = saved_work_commands.saved_work_combine_state(window, {})
    assert review["stage"] == saved_work_combine.STAGE_REVIEW and review["combine_enabled"]
    assert sorted(review["files"])[0].startswith(("character/", UPPER.split("/")[0]))
    with pytest.raises(ValueError, match="inside the run's own profile folder"):
        saved_work_commands.saved_work_combine_answer(
            window, {"write": True, "output_dir": str(combine.tmp.parent / "elsewhere")})
    output = combine.tmp / "out" / "Combined"
    assert saved_work_commands.saved_work_combine_answer(
        window, {"write": True, "title": "Combined", "output_dir": str(output)})
    _wait(app, lambda: not saved_work_commands.saved_work_combine_state(window, {})["open"])
    assert (output / UPPER).read_bytes() == b"edited upper body"
    assert (output / SHOULDER).read_bytes() == b"replacement shoulder"

    other = _build(combine.builds, "Second skirt", {UPPER: (b"another upper body", "0009")})
    add_built_mod_folder(combine.drafts, other)
    combine.page.refresh()
    _wait(app, lambda: len(combine.page.rows()) == 4)
    started = saved_work_commands.saved_work_combine(window, {"mod_roots": [str(combine.skirt), str(other)]})
    assert started["started"]
    _wait(app, lambda: saved_work_commands.saved_work_combine_state(window, {})["stage"]
          != saved_work_combine.STAGE_CHECKING)
    refused = saved_work_commands.saved_work_combine_state(window, {})
    assert refused["stage"] == saved_work_combine.STAGE_REFUSED
    assert refused["status"].startswith("These builds cannot be combined") and UPPER in refused["status"]
    assert saved_work_commands.saved_work_combine_answer(window, {"write": False})
    _wait(app, lambda: not saved_work_commands.saved_work_combine_state(window, {})["open"])


def test_select_parts_sends_the_part_numbers_to_the_shown_editor() -> None:
    sent: list[dict] = []

    class _Tab:
        standalone_rust_ready = True

        def _rust_host_message(self, event, *, request_id, extra=None):
            return {"event": event, "request_id": request_id, **dict(extra or {})}

        def _send_rust_message(self, payload):
            sent.append(dict(payload))
            return True

    tab = _Tab()
    from PySide6.QtWidgets import QApplication, QWidget

    QApplication.instance() or QApplication([])
    holder = QWidget()
    holder.active = tab
    window = SimpleNamespace(shell=SimpleNamespace(mesh_editor_tab=holder))
    assert saved_work_commands.select_whole_parts(window, {"indices": [3, 1, 3]})
    assert sent == [{"event": "select_parts", "request_id": 0, "indices": [1, 3]}]
    tab.standalone_rust_ready = False
    assert not saved_work_commands.select_whole_parts(window, {"indices": [1]})
    holder.deleteLater()
