"""NPC Finder window: search, outfit, buttons and lifetime, with a stand-in archive helper."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from cdmw.domain.archives.catalogue import ArchiveSessionHandle
from cdmw.domain.archives.item_catalogue import BuildNameIndexResult
from cdmw.domain.archives.npc_catalogue import (
    BuildNpcCatalogResult, NpcCatalogRow, NpcCatalogSearchResult, NpcCatalogStatistics, NpcOutfit, NpcOutfitResult,
    NpcPiece, NpcWearer, NpcWearersResult,
)
from cdmw.ui.npc_finder import dialog as feature

_APPLICATION = None
ROSS_APP = "character/appearance/3_npc/cd_npc_south/cd_nhm_south/cd_nhm_south_10335.app_xml"
UPPER = "character/model/3_npc/1_nhm/armor_south/9_upperbody/cd_nhm_00_so_ub_10335.pac"
CLOAK = "character/model/1_pc/1_phm/armor/19_cloak/cd_phm_00_cloak_00_0446.pac"


class Service(QObject):
    result_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    progress = Signal(str, object)
    session_published = Signal(object)
    worker_crashed = Signal(str)
    npc_catalog_available = True

    def __init__(self):
        super().__init__()
        self.calls = []
        self.cancelled = []

    def _call(self, kind, request, **kw):
        token = f"{kind}-{len(self.calls)}"
        self.calls.append((token, request, kw))
        return token

    def build_npc_catalog(self, request, **kw): return self._call("build", request, **kw)
    def search_npc_catalog(self, request, **kw): return self._call("search", request, **kw)
    def get_npc_outfit(self, request, **kw): return self._call("outfit", request, **kw)
    def find_npc_wearers(self, request, **kw): return self._call("wearers", request, **kw)
    def build_name_index(self, request, **kw): return self._call("names", request, **kw)
    def cancel(self, token): self.cancelled.append(token)

    def last(self, kind):
        return next(call for call in reversed(self.calls) if call[0].startswith(kind + "-"))

    def answer(self, kind, result):
        self.result_ready.emit(self.last(kind)[0], kind, result)


def _row(key="npc:1001844", name="Ross", character_id=1001844):
    return NpcCatalogRow(key, character_id, name, "NHM_Unique_Russo_622", "npc", "3_npc", 1, 3, "resolved", ROSS_APP, True)


def _piece(slot, path, entry_id, items=()):
    return NpcPiece("armor", slot, "cd_nhm_so_ub_10335", 5, "character/bin__/prefab/x.prefab", entry_id, path, "",
                    "resolved", tuple(items))


MISSING = NpcPiece("armor", "Unknown", "cd_nhm_so_ub_51220", -1, "", -1, "", "", "missing_prefab", ())


def _outfit(items=()):
    pieces = (_piece("Upperbody", UPPER, 10, items), _piece("Cloak", CLOAK, 11), MISSING)
    return NpcOutfitResult("session-a", _row(), (NpcOutfit(0, ROSS_APP, 3, "partial", pieces, ("evidence line",)),),
                           ("Russo",), bool(items))


STATS = NpcCatalogStatistics(5575, 1, 3909, 13156, 5153, 5148, 5, 10, 9721, 0)


@pytest.fixture
def finder(monkeypatch):
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    window = QWidget()
    window.archive = window.shell = window
    window.settings = None
    window.archive_catalogue_service = Service()
    scopes = []
    window.archive_remote_bridge = SimpleNamespace(
        current_session=ArchiveSessionHandle("session-a", "C:/game", "fp", 10, 3, True),
        controller=SimpleNamespace(generation=4),
        apply_entry_id_scope=lambda ids, **kw: scopes.append((tuple(ids), kw)) or True)
    created = []
    window.open_new_item_studio = created.append
    window.archive_model_open_mesh_editor_button = QPushButton(window)
    monkeypatch.setattr(feature, "register_transient_worker_controller", lambda *_a: None)
    dialog = feature.show_npc_finder(window)
    _APPLICATION.processEvents()
    yield dialog, window.archive_catalogue_service, scopes, created, window
    if not dialog._closing:
        dialog.close()


def _ready(dialog, service, rows=(_row(), _row("npc:2", "Ross Guard", 2))):
    service.answer("build", BuildNpcCatalogResult("session-a", False, 2, 0, STATS, ()))
    service.answer("search", NpcCatalogSearchResult("session-a", len(rows), 0, 100, tuple(rows), ()))


def test_search_fills_the_list_and_selecting_fills_the_pieces(finder) -> None:
    dialog, service, *_ = finder
    assert service.calls[0][0].startswith("build-") and service.calls[0][1] == "session-a"
    _ready(dialog, service)
    assert dialog._results.rowCount() == 2 and dialog._results.item(0, 0).text() == "Ross"
    assert "5,575 appearance files" in dialog._status.text()
    outfit_request = service.last("outfit")[1]
    assert outfit_request.key == "npc:1001844"
    service.answer("outfit", _outfit())
    assert dialog._pieces.rowCount() == 3
    assert [dialog._pieces.item(i, 0).text() for i in range(3)] == ["Upperbody", "Cloak", "Unknown"]
    assert dialog._pieces.item(2, 1).text() == feature.RESOLUTION_NOTES["missing_prefab"]
    assert "Russo" in dialog._details.toPlainText()
    # Item links are missing, so the item name index is built once and the outfit asked again.
    assert service.last("names")[1] == "session-a"
    service.answer("names", BuildNameIndexResult("session-a", True, False, 1, 0))
    assert len([c for c in service.calls if c[0].startswith("outfit-")]) == 2


def test_typing_searches_with_the_filters(finder) -> None:
    dialog, service, *_ = finder
    _ready(dialog, service)
    dialog._kind.setCurrentIndex(dialog._kind.findData("creature"))
    dialog._armor_only.setChecked(True)
    dialog._search_edit.setText("1001844")
    dialog._search_timer.stop()
    dialog._search()
    request = service.last("search")[1]
    assert (request.query, request.kind, request.has_armor, request.page_size) == ("1001844", "creature", True, 100)


def test_buttons_hand_the_right_entry_ids_to_browse_mesh_editor_and_create_new_item(finder) -> None:
    dialog, service, scopes, created, window = finder
    _ready(dialog, service)
    service.answer("outfit", _outfit(items=(777,)))
    assert dialog._show_outfit_button.isEnabled() and dialog._item_button.isEnabled()
    assert dialog.show_outfit()
    ids, options = scopes[-1]
    assert ids == (10, 11) and options["worn_set"] is True and options["label"] == "NPC Finder: Ross"
    assert options["preferred_prefab_stems"] == ["cd_nhm_so_ub_10335", "cd_nhm_so_ub_10335", "cd_nhm_so_ub_51220"]


def test_piece_buttons(finder) -> None:
    dialog, service, scopes, created, window = finder
    _ready(dialog, service)
    service.answer("outfit", _outfit(items=(777,)))
    dialog._pieces.setCurrentCell(1, 0)
    assert dialog.show_piece() and scopes[-1][0] == (11,) and not scopes[-1][1].get("worn_set")


def test_create_item_and_missing_piece(finder) -> None:
    dialog, service, scopes, created, window = finder
    _ready(dialog, service)
    service.answer("outfit", _outfit(items=(777,)))
    dialog._pieces.setCurrentCell(2, 0)
    assert not dialog._mesh_button.isEnabled() and not dialog._item_button.isEnabled()
    dialog._pieces.setCurrentCell(0, 0)
    assert dialog.create_item() and created == [777]


def test_open_mesh_waits_for_browse_to_select_the_piece(finder) -> None:
    dialog, service, scopes, created, window = finder
    _ready(dialog, service)
    service.answer("outfit", _outfit())
    clicks = []
    window.archive_model_open_mesh_editor_button.clicked.connect(lambda: clicks.append(True))
    window._current_archive_mesh_entry = lambda: None
    assert dialog.open_mesh() and scopes[-1][0] == (10,)
    dialog._open_mesh_when_selected()
    assert not clicks
    window._current_archive_mesh_entry = lambda: SimpleNamespace(path=UPPER.upper())
    dialog._open_mesh_when_selected()
    assert clicks == [True] and dialog._closing



def test_closing_or_reopening_ends_the_wait_to_open_mesh_editor(finder) -> None:
    dialog, service, _scopes, _created, window = finder
    _ready(dialog, service)
    service.answer("outfit", _outfit())
    window._current_archive_mesh_entry = lambda: None
    assert dialog.open_mesh() and dialog._mesh_timer.isActive()
    assert feature.show_npc_finder(window) is dialog
    assert not dialog._mesh_timer.isActive() and not dialog._pending_mesh_path
    assert dialog.open_mesh() and dialog._mesh_timer.isActive()
    dialog.close()
    assert dialog._closing and not dialog._mesh_timer.isActive() and not dialog._pending_mesh_path


def test_worn_by_refills_the_list(finder) -> None:
    dialog, service, *_ = finder
    _ready(dialog, service)
    service.answer("outfit", _outfit())
    dialog._pieces.setCurrentCell(1, 0)
    dialog._page_start = 100  # the search was on its second page
    assert dialog.find_wearers()
    assert service.last("wearers")[1].piece == CLOAK
    wearers = tuple(NpcWearer(_row(f"npc:{i}", f"Wearer {i}", i), ROSS_APP, "armor", "Cloak", "p", CLOAK) for i in range(3))
    service.answer("wearers", NpcWearersResult("session-a", CLOAK, wearers, 3, False))
    assert dialog._results.rowCount() == 3 and dialog._banner.isVisible()
    assert dialog._count.text() == "1 to 3 of 3"
    assert "cd_phm_00_cloak_00_0446.pac" in dialog._banner.text()


def test_export_writes_csv_and_text(finder, tmp_path) -> None:
    dialog, service, *_ = finder
    _ready(dialog, service)
    service.answer("outfit", _outfit())
    assert dialog.export_outfit(tmp_path / "ross.csv") == 3
    text = (tmp_path / "ross.csv").read_text(encoding="utf-8").splitlines()
    assert text[0].startswith("section,slot,piece") and "cd_phm_00_cloak_00_0446.pac" in text[2]
    assert dialog.export_outfit(tmp_path / "ross.txt") == 3
    assert "Ross (ID 1001844)" in (tmp_path / "ross.txt").read_text(encoding="utf-8")


def test_stale_results_after_a_session_change_are_dropped_and_closing_cancels(finder) -> None:
    dialog, service, *_ = finder
    _ready(dialog, service)
    service.answer("search", NpcCatalogSearchResult("session-b", 1, 0, 100, (_row("npc:9", "Other", 9),), ()))
    assert dialog._results.item(0, 0).text() == "Ross"
    pending = service.last("outfit")[0]
    service.session_published.emit(ArchiveSessionHandle("session-b", "C:/game", "fp2", 10, 3, True))
    assert dialog._invalid and pending in service.cancelled and "archive changed" in dialog._status.text()
    assert not dialog._show_outfit_button.isEnabled()
    dialog.close()
    assert dialog._closing


def test_closing_cancels_requests_and_a_failure_is_shown(finder) -> None:
    dialog, service, *_ = finder
    token = service.calls[0][0]
    service.request_failed.emit(token, SimpleNamespace(message="Helper failed"))
    assert dialog._status.text() == "Helper failed"
    dialog._build()
    pending = service.last("build")[0]
    dialog.close()
    assert pending in service.cancelled


def test_show_again_reuses_the_open_window_and_the_helper_check(monkeypatch, finder) -> None:
    dialog, service, scopes, created, window = finder
    assert feature.show_npc_finder(window, query="ross") is dialog and dialog._search_edit.text() == "ross"
    messages = []
    monkeypatch.setattr(feature.QMessageBox, "information", lambda *args: messages.append(args[2]))
    other = QWidget()
    other.archive = other
    other.archive_catalogue_service = SimpleNamespace(npc_catalog_available=False)
    assert feature.show_npc_finder(other) is None and "updated archive helper" in messages[0]


def test_a_busy_bar_shows_while_the_catalogue_is_read(finder) -> None:
    dialog, service, *_ = finder
    dialog.show()
    assert dialog._busy.isVisible()
    _ready(dialog, service)
    service.answer("outfit", _outfit())
    assert not dialog._busy.isVisible()
    assert dialog._results.columnCount() == 4 and "NHM_Unique_Russo_622" in dialog._results.item(0, 0).toolTip()
    assert dialog._variant.currentText().endswith("cd_nhm_south_10335.app_xml") and dialog._variant.toolTip() == ROSS_APP
