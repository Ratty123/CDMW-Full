"""The pass's click-like commands: Preview Settings' page check and a Scene panel tick."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import shiboken6
from PySide6.QtWidgets import QApplication

from cdmw.automation import pass_commands
from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.archive_browser.item_set_components import ScenePanel
from cdmw.ui.model_preview_settings_dialog import ModelPreviewSettingsDialog

_APP = QApplication.instance() or QApplication([])
SWORD = "character/model/cd_phm_02_sword_0015.pac"
SCABBARD = "character/model/cd_phm_02_sword_0015_in.pac"


def test_preview_settings_page_check_changes_the_page_s_controls_and_reports_the_page() -> None:
    dialog = ModelPreviewSettingsDialog(
        settings=ModelPreviewRenderSettings(),
        preview_target=ModelPreviewSettingsDialog.PREVIEW_TARGET_ARCHIVE_DOTNET_VORTICE)
    archive = SimpleNamespace(model_preview_settings_dialog=dialog)
    archive._open_model_preview_settings_dialog = dialog.show
    try:
        checked = pass_commands.preview_settings_page_check(SimpleNamespace(archive=archive), {})
        assert checked["page"] == "Quality / Lighting"
        assert checked["changes"] > 3
        assert checked["left_page"] == []
        assert not dialog.isVisible()
    finally:
        shiboken6.delete(dialog)
        _APP.processEvents()


def test_scene_panel_tick_unticks_every_part_of_that_file_only() -> None:
    panel = ScenePanel()
    batches = [{"index": index, "material_name": f"M{index}", "editor_identity": {
        "source_submesh_index": index, "source_local_submesh_index": local, "source_model_path": path}}
        for index, (path, local) in enumerate(((SWORD, 0), (SWORD, 1), (SCABBARD, 0)))]
    panel.set_parts(batches)
    window = SimpleNamespace(archive=SimpleNamespace(archive_item_set_components=panel))
    assert pass_commands.scene_panel_tick(window, {"path": "cd_phm_02_sword_0015_in.pac", "ticked": False})
    assert panel.hidden_indices == (2,)
    assert dict(panel.ticked_files()) == {SWORD: ()}
    assert not pass_commands.scene_panel_tick(window, {"path": "missing.pac", "ticked": False})


def test_draft_choice_answer_clicks_start_fresh_or_resume() -> None:
    from PySide6.QtWidgets import QPushButton, QWidget

    clicks: list[str] = []
    holder = QWidget()
    tab = SimpleNamespace(_draft_choice_showing=lambda: True,
                          draft_start_fresh_button=QPushButton(), draft_resume_button=QPushButton())
    tab.draft_start_fresh_button.clicked.connect(lambda: clicks.append("fresh"))
    tab.draft_resume_button.clicked.connect(lambda: clicks.append("resume"))
    holder.active = tab
    window = SimpleNamespace(shell=SimpleNamespace(mesh_editor_tab=holder))
    assert pass_commands.draft_choice_showing(window)
    assert pass_commands.draft_choice_answer(window, {})
    assert pass_commands.draft_choice_answer(window, {"answer": "resume"})
    assert clicks == ["fresh", "resume"]
    tab._draft_choice_showing = lambda: False
    assert not pass_commands.draft_choice_answer(window, {})
    holder.deleteLater()
