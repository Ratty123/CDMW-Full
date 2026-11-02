from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.core import classification_registry
from cdmw.models import AppConfig, ArchiveEntry
from cdmw.ui.research import ResearchTab
from cdmw.ui.research.analysis_state import research_analysis_report_rows


_APP = QApplication.instance() or QApplication([])

_PATHS = (
    "character/texture/cd_phm_00_ub_0001.dds",
    "character/texture/cd_phm_00_ub_0001_n.dds",
    "character/cd_phm_00_ub_0001.pac.xml",
    "object/texture/rock_01.dds",
    "object/texture/rock_01_n.dds",
    "object/texture/mystery_blob.dds",
    "object/texture/odd_thing.dds",
    "object/texture/strange_leaf.dds",
    "ui/texture/icon_sword.dds",
)


def _pump(predicate=lambda: False, timeout: float = 10.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        _APP.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    _APP.processEvents()
    return bool(predicate())


def _refresh_idle(tab: ResearchTab) -> bool:
    return (
        tab.refresh_thread is None
        and not tab._refresh_population_timer.isActive()
        and not tab._unknown_population_timer.isActive()
        and not tab._research_refresh_queued
    )


@pytest.fixture
def research_tab(tmp_path: Path):
    previous_registry = classification_registry.texture_classification_registry_path()
    classification_registry.configure_texture_classification_registry(tmp_path / "registry.json")
    entries = [
        ArchiveEntry(path, tmp_path / "0000" / "0.pamt", tmp_path / "0000" / "0.paz", index * 100, 100, 100, 0, 0)
        for index, path in enumerate(_PATHS)
    ]
    tab = ResearchTab(
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat),
        base_dir=tmp_path,
        get_archive_entries=lambda: entries,
        get_filtered_archive_entries=lambda: entries,
        get_original_root=lambda: "",
        get_output_root=lambda: "",
        get_app_config=AppConfig,
        get_current_archive_path=lambda: "",
        get_current_text_search_path=lambda: "",
        get_current_compare_path=lambda: "",
    )
    tab.resize(1400, 900)
    tab.show()
    try:
        yield tab
    finally:
        tab.request_shutdown()
        _pump(lambda: all(thread is None for _name, thread, _worker in tab.iter_shutdown_workers()), 5.0)
        tab.close()
        tab.deleteLater()
        _APP.processEvents()
        if previous_registry is not None:
            classification_registry.configure_texture_classification_registry(previous_registry)


def _refreshed(tab: ResearchTab) -> ResearchTab:
    tab.refresh_research_from_button()
    assert _pump(lambda: _refresh_idle(tab))
    return tab


def _listed_review_paths(tab: ResearchTab) -> set[str]:
    paths: set[str] = set()
    for index in range(tab.unknown_group_tree.topLevelItemCount()):
        group = tab.unknown_group_tree.topLevelItem(index).data(0, 0x0100)
        paths.update(member.path for member in group.members)
    return paths


def test_pages_are_one_flat_row_and_side_panel_follows_the_page(research_tab: ResearchTab) -> None:
    tab = research_tab
    titles = [tab.tab_widget.tabText(index) for index in range(tab.tab_widget.count())]
    assert titles == [
        "Texture Sets",
        "Classification Review",
        "References",
        "UI Constraints",
        "Heatmap",
        "Texture Analysis",
        "Notes",
    ]
    tab.tab_widget.setCurrentWidget(tab.classification_review_tab)
    assert not tab.right_panel_stack.isVisible()
    tab.tab_widget.setCurrentWidget(tab.texture_tab)
    assert tab.right_panel_stack.currentWidget() is tab.analysis_detail_group
    assert "not set" in tab.analysis_roots_label.text()
    tab.tab_widget.setCurrentWidget(tab.reference_tab)
    assert tab.right_panel_stack.currentWidget() is tab.archive_picker_group


def test_refresh_keeps_texture_analysis_detail_panel(research_tab: ResearchTab) -> None:
    tab = research_tab
    tab.tab_widget.setCurrentWidget(tab.texture_tab)
    _refreshed(tab)
    assert tab.tab_widget.currentWidget() is tab.texture_tab
    assert tab.right_panel_stack.currentWidget() is tab.analysis_detail_group


def test_focus_references_opens_the_references_page(research_tab: ResearchTab) -> None:
    tab = research_tab
    tab.focus_references_for_path("object/texture/rock_01.dds", auto_resolve=False)
    assert tab.tab_widget.currentWidget() is tab.reference_tab
    assert tab.reference_target_edit.text() == "object/texture/rock_01.dds"


def test_saving_a_label_keeps_the_rest_of_the_review_queue(research_tab: ResearchTab) -> None:
    tab = _refreshed(research_tab)
    tab.tab_widget.setCurrentWidget(tab.classification_review_tab)
    before = _listed_review_paths(tab)
    assert len(before) >= 2
    target = tab._current_unknown_classifiable_member()
    assert target is not None

    tab._apply_unknown_current_file_label()
    assert _pump(lambda: _refresh_idle(tab))

    after = _listed_review_paths(tab)
    assert target.path not in after
    assert after == before - {target.path}
    assert not tab.pending_classification_review_focus_keys


def test_label_saved_during_a_refresh_triggers_one_more_refresh(research_tab: ResearchTab) -> None:
    tab = _refreshed(research_tab)
    tab.refresh_research()
    assert tab.refresh_thread is not None
    tab.refresh_research()
    assert tab._research_refresh_queued
    assert _pump(lambda: _refresh_idle(tab))
    assert not tab._research_refresh_queued


def test_cleared_review_preview_ignores_late_results(research_tab: ResearchTab) -> None:
    tab = research_tab
    stale_request = tab.unknown_preview_request_id
    tab._clear_unknown_preview("Nothing selected.")
    assert tab.unknown_preview_request_id != stale_request
    assert tab.pending_unknown_preview_request is None


def test_ui_constraint_rows_do_not_enable_reference_review(research_tab: ResearchTab) -> None:
    from cdmw.domain.research.contracts import MaterialTextureReferenceRow
    from cdmw.ui.research.models import build_ui_constraint_item

    tab = research_tab
    row = MaterialTextureReferenceRow(
        source_path="ui/xml/inventory.xml",
        source_package_label="0000",
        related_path="ui/texture/icon_sword.dds",
        related_package_label="0000",
        relation_kind="ui_rect",
        match_count=1,
        snippet='<Image Texture="icon_sword.dds" GetRect="0,0,64,64"/>',
        source_kind="xml",
        get_rect_raw="0,0,64,64",
    )
    tab.ui_constraint_tree.addTopLevelItem(build_ui_constraint_item(row))
    tab.ui_constraint_tree.setCurrentItem(tab.ui_constraint_tree.topLevelItem(0))
    assert not tab.reference_review_text_button.isEnabled()


def test_new_note_target_replaces_previous_note_text(research_tab: ResearchTab) -> None:
    tab = research_tab
    messages: list[tuple[str, bool]] = []
    tab.status_message_requested.connect(lambda text, error: messages.append((text, error)))
    tab._populate_note_target("archive", "object/texture/rock_01.dds")
    tab.notes_edit.setPlainText("Rock note body")
    tab._save_note()

    tab._populate_note_target("archive", "object/texture/mystery_blob.dds")
    assert tab.notes_edit.toPlainText() == ""
    assert tab.notes_tags_edit.text() == ""
    tab._save_note()
    assert "object/texture/mystery_blob.dds" not in tab.notes
    assert messages[-1][1] is True

    tab._delete_note()
    assert messages[-1] == ("There is no saved note for this target.", True)
    tab._populate_note_target("archive", "object/texture/rock_01.dds")
    assert tab.notes_edit.toPlainText() == "Rock note body"


def test_export_without_a_refresh_has_no_report_rows() -> None:
    assert research_analysis_report_rows({}) is None
    assert research_analysis_report_rows({"mip_rows": [], "normal_rows": []}) is not None


def test_a_refresh_running_when_a_label_is_saved_does_not_cache_its_stale_snapshot(research_tab: ResearchTab) -> None:
    tab = _refreshed(research_tab)
    tab.archive_snapshot_cache.clear()
    tab.refresh_research()
    assert tab.refresh_thread is not None
    tab.archive_snapshot_cache.clear()  # What a label saved during the refresh does.
    assert _pump(lambda: tab.refresh_thread is None)
    assert not tab.archive_snapshot_cache


def test_a_hand_off_focus_survives_the_first_saved_label(research_tab: ResearchTab) -> None:
    tab = _refreshed(research_tab)
    focus = ["object/texture/mystery_blob.dds", "object/texture/odd_thing.dds"]
    tab.focus_classification_review_for_paths(focus, include_classified=True)
    assert _pump(lambda: _refresh_idle(tab))
    keys = set(tab.pending_classification_review_focus_keys)
    assert keys
    tab._apply_unknown_current_file_label()
    assert _pump(lambda: _refresh_idle(tab))
    assert tab.pending_classification_review_focus_keys == keys


def _select_archive_file(tab: ResearchTab, path: str) -> None:
    tab.tab_widget.setCurrentWidget(tab.reference_tab)
    tab._ensure_archive_picker_ready()
    tab.archive_picker_view_combo.setCurrentIndex(tab.archive_picker_view_combo.findData("flat"))
    for index in range(tab.archive_picker_tree.topLevelItemCount()):
        item = tab.archive_picker_tree.topLevelItem(index)
        if path in item.text(0) or path in str(item.toolTip(0)):
            tab.archive_picker_tree.setCurrentItem(item)
            return
    raise AssertionError(f"{path} is not listed in Archive Files")


def test_find_references_opens_the_references_page_and_add_note_keeps_an_unsaved_draft(research_tab: ResearchTab) -> None:
    tab = research_tab
    tab.resolve_references = lambda: None  # The resolve itself is covered elsewhere.
    _select_archive_file(tab, "rock_01.dds")
    tab.tab_widget.setCurrentWidget(tab.texture_sets_tab if hasattr(tab, "texture_sets_tab") else tab.notes_tab)
    tab.use_selected_archive_picker_for_reference()
    assert tab.tab_widget.currentWidget() is tab.reference_tab
    assert tab.reference_target_edit.text() == "object/texture/rock_01.dds"

    tab.notes_target_edit.setText("object/texture/odd_thing.dds")
    tab.notes_edit.setPlainText("draft not saved yet")
    tab.use_selected_archive_picker_for_note()
    assert tab.tab_widget.currentWidget() is tab.notes_tab
    assert tab.notes_target_edit.text() == "object/texture/odd_thing.dds"
    assert tab.notes_edit.toPlainText() == "draft not saved yet"
