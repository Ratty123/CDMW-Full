"""Step 8 item 5: other game files that use a texture opened in the Mesh Editor are named."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from cdmw.domain.archives.reference_sources import BULK_REFERENCE_SOURCES, QUICK_REFERENCE_SOURCES
from cdmw.models import ArchiveEntry
from cdmw.ui.mesh_editor.shared_texture_check import (
    CHECKING_TEXT,
    NONE_YET_TEXT,
    SharedTextureCheck,
    SharedTextureResult,
    forget_texture_users,
    joined_file_names,
    other_files,
)

_APP = QApplication.instance() or QApplication([])
TEXTURE = "character/texture/cd_phm_00_ub_00_0374_n.dds"
OWN = "character/modelproperty/1_pc/1_phm/armor/9_upperbody/cd_phm_00_ub_00_0374.pac_xml"
OTHER = "character/modelproperty/3_npc/1_nhm/armor_south/9_upperbody/cd_nhm_00_so_ub_10109.pac_xml"


@pytest.fixture(autouse=True)
def _no_kept_answers():
    forget_texture_users()
    yield
    forget_texture_users()


def _entry(path: str) -> ArchiveEntry:
    return ArchiveEntry(path, Path("0000/0.pamt"), Path("0000/0.paz"), 0, 4, 4, 0, 0)


def _ref(path: str, confidence: str = "authoritative"):
    return SimpleNamespace(resolved_archive_path=path, relation_confidence=confidence)


class _Controller(QObject):
    updated = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.started: list[tuple[object, str]] = []
        self.busy = False

    def start(self, target, entries=(), *, session_id="", generation=0, formats=None):
        self.started.append((target, session_id))
        self.formats = None if formats is None else tuple(formats)
        self.busy = True
        return True

    def finish(self, **fields) -> None:
        self.busy = False
        self.updated.emit(SimpleNamespace(**{"finished": True, "cancelled": False, "error": "", "limited": False,
                                             "references": (), **fields}))


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


class _Controllers:
    """Every controller the check asks for, in order: the first stage's, then the later stages'."""

    def __init__(self) -> None:
        self.made: list[_Controller] = []

    def __call__(self) -> _Controller:
        self.made.append(_Controller())
        return self.made[-1]


def _check(controllers, session="session-a", own=("cd_phm_00_ub_00_0374",), entries=None):
    entries = entries or {TEXTURE: _entry(TEXTURE)}
    return SharedTextureCheck(controllers, lambda path: entries.get(path), lambda: session, lambda: list(own))


def test_the_first_answer_comes_from_the_quick_formats_and_the_bulky_ones_finish_it():
    from cdmw.core.archive_reverse_references import reference_search_plan

    controllers = _Controllers()
    check = _check(controllers)
    check.search_texture_users(TEXTURE)
    (first,) = controllers.made
    assert ".pac_xml" in first.formats and set(first.formats) <= QUICK_REFERENCE_SOURCES
    first.finish(references=(_ref(OWN), _ref(OTHER)))
    so_far = check.texture_users_found(TEXTURE)
    assert not so_far.finished and so_far.other_files == (OTHER,)  # the opened model's own file is left out
    assert "cd_nhm_00_so_ub_10109.pac_xml" in so_far.sharing_notice and "Still searching" in so_far.sharing_notice
    _first, later = controllers.made
    middle = later.formats
    assert middle and not set(middle) & (QUICK_REFERENCE_SOURCES | BULK_REFERENCE_SOURCES)
    later.finish(references=())
    assert "Still searching" in check.texture_users_found(TEXTURE).sharing_notice
    assert set(later.formats) == BULK_REFERENCE_SOURCES
    later.finish(references=(_ref("object/rock.pam"), _ref("object/rock.pami", "basename_fallback")))
    done = check.texture_users_found(TEXTURE)
    assert done.finished and done.other_files == (OTHER, "object/rock.pam")
    assert "Still searching" not in done.sharing_notice and "rock.pam" in done.sharing_notice
    # Every format Find References reads for the texture was read, each once.
    plan = [extension for group in reference_search_plan(_entry(TEXTURE)).groups for extension in group]
    assert sorted((*first.formats, *middle, *later.formats)) == sorted(plan)


def test_nothing_found_in_the_first_stages_still_reads_as_searching_never_as_none():
    controllers = _Controllers()
    check = _check(controllers)
    check.search_texture_users(TEXTURE)
    controllers.made[0].finish(references=(_ref(OWN),))
    assert check.texture_users_found(TEXTURE).sharing_notice == NONE_YET_TEXT
    controllers.made[1].finish(references=())
    assert check.texture_users_found(TEXTURE).sharing_notice == NONE_YET_TEXT
    controllers.made[1].finish(references=())
    assert check.texture_users_found(TEXTURE).sharing_notice == ""


def test_a_texture_opened_later_is_not_queued_behind_a_slow_search():
    other_texture = "character/texture/cd_phm_00_belt_0008_02.dds"
    controllers = _Controllers()
    check = _check(controllers, entries={TEXTURE: _entry(TEXTURE), other_texture: _entry(other_texture)})
    check.search_texture_users(TEXTURE)
    check.search_texture_users(TEXTURE)  # once per texture
    controllers.made[0].finish(references=())
    quick, later = controllers.made
    assert later.busy  # the first texture's later stages are being read
    check.search_texture_users(other_texture)
    # Its first stage starts at once, on the first stage's controller.
    assert [target.path for target, _session in quick.started] == [TEXTURE, other_texture]
    quick.finish(references=(_ref(OTHER),))
    assert check.texture_users_found(other_texture).other_files == (OTHER,)
    # Its later stages wait until the first texture's are all done.
    later.finish(references=())
    later.finish(references=())
    assert [target.path for target, _session in later.started] == [TEXTURE, TEXTURE, other_texture]
    assert check.texture_users_found(TEXTURE).finished
    assert later.started[2][1] == "session-a"


def test_a_search_that_stops_at_its_limit_says_there_may_be_more():
    controllers = _Controllers()
    check = _check(controllers)
    check.search_texture_users(TEXTURE)
    controllers.made[0].finish(references=(_ref(OTHER),), limited=True)
    controllers.made[1].finish(references=())
    controllers.made[1].finish(references=())
    notice = check.texture_users_found(TEXTURE).sharing_notice
    assert "cd_nhm_00_so_ub_10109.pac_xml" in notice and "There may be more" in notice and "limit" in notice


def test_a_cancelled_search_runs_again_and_answers_are_kept_for_the_archive_session():
    controllers = _Controllers()
    check = _check(controllers)
    check.search_texture_users(TEXTURE)
    controllers.made[0].busy = False
    controllers.made[0].updated.emit(SimpleNamespace(finished=True, cancelled=True, error="", limited=False,
                                                     references=()))
    assert "cancelled" in check.texture_users_found(TEXTURE).sharing_notice
    check.search_texture_users(TEXTURE)  # opened again: searched again, not "cancelled" for good
    assert len(controllers.made[0].started) == 2
    controllers.made[0].finish(references=(_ref(OTHER),))
    controllers.made[1].finish(references=())
    controllers.made[1].finish(references=(_ref(OWN),))
    assert check.texture_users_found(TEXTURE).other_files == (OTHER,)

    # Another Mesh Editor tab on the same archive session reuses the answer, with its
    # own model left out: here the model whose property file the first tab found.
    again = _Controllers()
    tab = _check(again, own=("cd_nhm_00_so_ub_10109",))
    assert tab.texture_users_found(TEXTURE).other_files == (OWN,)
    tab.search_texture_users(TEXTURE)
    assert again.made == []
    # A new scan is a new session: searched again.
    rescanned = _check(again, session="session-b")
    assert rescanned.texture_users_found(TEXTURE) is None
    rescanned.search_texture_users(TEXTURE)
    assert len(again.made) == 1


def test_the_check_finds_confirmed_users_through_the_real_search_after_a_rescan(tmp_path):
    from cdmw.services.archive_reference_search import ArchiveReferenceSearchController
    from tests.test_archive_reverse_references import RefusingCatalogue, entries_at, wait_for

    files = entries_at(tmp_path, [
        (TEXTURE, b"DDS "),
        (OWN, f'<Texture path="{TEXTURE}"/>'.encode()),
        (OTHER, f'<Texture path="{TEXTURE}"/>'.encode()),
        ("object/rock.pam", b"PAR \x00\x00" + TEXTURE.upper().encode("utf-16-le") + b"\x00\x00"),
        ("object/rock.pami", b'<Texture path="character/texture/sand_d.dds"/>'),
        ("character/model/cd_x.pac", TEXTURE.encode()),  # not a format that names textures
    ])
    # Browse's rescan raised the catalogue's minimum generation; the check asks at none.
    catalogue = RefusingCatalogue(files[1:])
    check = SharedTextureCheck(lambda: ArchiveReferenceSearchController(catalogue), lambda path: files[0],
                               lambda: "session", lambda: ["cd_phm_00_ub_00_0374"])
    check.search_texture_users(TEXTURE)
    wait_for(_APP, lambda: check.texture_users_found(TEXTURE).first_stage_done)
    so_far = check.texture_users_found(TEXTURE)
    assert so_far.other_files == (OTHER,) and not so_far.problem and not so_far.finished
    wait_for(_APP, lambda: check.texture_users_found(TEXTURE).finished)
    done = check.texture_users_found(TEXTURE)
    assert done.other_files == (OTHER, "object/rock.pam") and not done.problem
    quick, middle, bulky = catalogue.queries  # one per stage; the middle one finds no file here
    assert ".pac_xml" in quick.extensions and set(bulky.extensions) == BULK_REFERENCE_SOURCES
    assert ".pac" not in (*quick.extensions, *middle.extensions, *bulky.extensions)
    assert min(catalogue.generations) == catalogue.minimum_ui_generation


def test_another_model_opened_in_the_same_tab_gets_its_own_files_left_out():
    controllers = _Controllers()
    own = ["cd_phm_00_ub_00_0374"]
    check = SharedTextureCheck(controllers, lambda path: _entry(TEXTURE), lambda: "session-a", lambda: list(own))
    check.search_texture_users(TEXTURE)
    controllers.made[0].finish(references=(_ref(OWN), _ref(OTHER)))
    controllers.made[1].finish(references=())
    controllers.made[1].finish(references=())
    assert check.texture_users_found(TEXTURE).other_files == (OTHER,)
    own[:] = ["cd_nhm_00_so_ub_10109"]  # the tab now shows the other model
    check.search_texture_users(TEXTURE)
    assert check.texture_users_found(TEXTURE).other_files == (OWN,)
