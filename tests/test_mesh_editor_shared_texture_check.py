"""Step 8 item 5: other game files that use a texture opened in the Mesh Editor are named."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.shared_texture_check import (
    CHECKING_TEXT,
    SharedTextureCheck,
    SharedTextureResult,
    joined_file_names,
    other_files,
)

_APP = QApplication.instance() or QApplication([])
TEXTURE = "character/texture/cd_phm_00_ub_00_0374_n.dds"


def _ref(path: str, confidence: str = "authoritative"):
    return SimpleNamespace(resolved_archive_path=path, relation_confidence=confidence)


class _Controller(QObject):
    updated = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.started: list[tuple[object, str]] = []
        self.busy = False

    def start(self, target, entries=(), *, session_id="", generation=0):
        self.started.append((target, session_id))
        self.busy = True
        return True

    def finish(self, **fields) -> None:
        self.busy = False
        self.updated.emit(SimpleNamespace(finished=True, cancelled=False, error="", limited=False,
                                          references=(), **fields) if "references" not in fields else
                          SimpleNamespace(finished=True, cancelled=False, error="", limited=False, **fields))


def test_only_confirmed_references_from_other_models_count():
    references = [
        _ref("character/model/cd_phm_00_ub_00_0374.pac_xml"),  # the opened model's own sidecar
        _ref("character/model/cd_phm_00_ub_00_0123.pac_xml"),
        _ref("character/model/cd_phm_00_ub_00_0042.pami", "exact_path"),
        _ref("character/model/cd_phm_00_ub_00_9999.pac_xml", "basename_fallback"),  # a guess
        _ref("character/model/cd_phm_00_ub_00_0123.pac_xml"),  # the same file twice
    ]
    assert other_files(references, ["cd_phm_00_ub_00_0374"]) == (
        "character/model/cd_phm_00_ub_00_0042.pami", "character/model/cd_phm_00_ub_00_0123.pac_xml")


def test_the_text_names_up_to_three_files_and_counts_the_rest():
    assert joined_file_names(["a/one.pac_xml", "b/two.pac_xml"]) == "one.pac_xml, two.pac_xml"
    assert joined_file_names([f"x/{i}.pami" for i in range(5)]) == "0.pami, 1.pami, 2.pami + 2 more"
    assert SharedTextureResult(TEXTURE).sharing_notice == CHECKING_TEXT
    assert SharedTextureResult(TEXTURE, True).sharing_notice == ""
    assert "one.pac_xml" in SharedTextureResult(TEXTURE, True, ("a/one.pac_xml",)).sharing_notice
    assert "not scanned" in SharedTextureResult(TEXTURE, True, (), "the game archives are not scanned.").sharing_notice


def test_a_check_runs_in_the_background_once_per_texture_and_one_at_a_time():
    controller = _Controller()
    entries = {TEXTURE: SimpleNamespace(path=TEXTURE), "character/texture/other_d.dds": SimpleNamespace(path="o")}
    check = SharedTextureCheck(lambda: controller, lambda path: entries.get(path), lambda: "session-a",
                               lambda: ["cd_phm_00_ub_00_0374"])
    changed: list[str] = []
    check.changed.connect(changed.append)
    check.search_texture_users(TEXTURE)
    check.search_texture_users(TEXTURE)  # once per texture
    check.search_texture_users("character/texture/other_d.dds")  # waits for the first
    assert len(controller.started) == 1 and controller.started[0][1] == "session-a"
    assert check.texture_users_found(TEXTURE).sharing_notice == CHECKING_TEXT
    controller.finish(references=(_ref("character/model/cd_phm_00_ub_00_0123.pac_xml"),))
    assert check.texture_users_found(TEXTURE).other_files == ("character/model/cd_phm_00_ub_00_0123.pac_xml",)
    assert len(controller.started) == 2  # the second texture's search started after the first
    controller.finish(references=())
    assert check.texture_users_found("character/texture/other_d.dds").sharing_notice == ""
    assert changed.count(TEXTURE) == 2


def test_no_catalogue_or_no_game_file_says_why_instead_of_searching():
    controller = _Controller()
    check = SharedTextureCheck(lambda: controller, lambda _path: None, lambda: "session-a", lambda: [])
    check.search_texture_users(TEXTURE)
    assert controller.started == []
    assert "not in the archive catalogue" in check.texture_users_found(TEXTURE).sharing_notice
    check2 = SharedTextureCheck(lambda: controller, lambda _path: object(), lambda: "", lambda: [])
    check2.search_texture_users(TEXTURE)
    assert "not scanned" in check2.texture_users_found(TEXTURE).sharing_notice


def test_build_mod_s_plan_line_names_the_other_game_files():
    import numpy as np

    from cdmw.services.mesh_live_texture_output import LiveTextureOutput

    original = SimpleNamespace(dds_format="BC5_UNORM", width=4, height=4, mip_count=3)
    output = LiveTextureOutput(entry=None, game_path=TEXTURE, original=original, rgba=np.zeros((4, 4, 4), np.uint8),
                               other_files=("character/model/cd_phm_00_ub_00_0123.pac_xml",))
    assert output.plan_line.endswith("(also used by cd_phm_00_ub_00_0123.pac_xml)")
    plain = LiveTextureOutput(entry=None, game_path=TEXTURE, original=original, rgba=np.zeros((4, 4, 4), np.uint8))
    assert "also used by" not in plain.plan_line
