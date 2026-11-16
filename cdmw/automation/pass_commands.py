"""Automation commands that act as a click would, for the built exe's pass (test runs only).

``preview_settings_page_check`` opens Browse's Preview Settings, goes to Quality /
Lighting and changes every shown combo box, tick box and slider there in turn, as a
user would, recording the page shown after each change. ``scene_panel_tick`` ticks or
unticks a file's row in the Scene panel.
"""

from __future__ import annotations


def preview_settings_page_check(window, args: dict) -> dict[str, object]:
    from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QDoubleSpinBox, QSlider, QSpinBox

    archive = window.archive
    archive._open_model_preview_settings_dialog()
    dialog = archive.model_preview_settings_dialog
    tabs = dialog.tabs
    page = dialog._quality_tab
    tabs.setCurrentWidget(page)
    QApplication.processEvents()
    title = tabs.tabText(tabs.indexOf(page))
    changes: list[dict[str, object]] = []

    def note(name: str) -> None:
        QApplication.processEvents()
        changes.append({"control": name, "page": tabs.tabText(tabs.currentIndex())})

    preset = dialog.preview_lighting_preset_combo
    if preset.count() > 1:
        preset.setCurrentIndex((preset.currentIndex() + 1) % preset.count())
        note("Lighting preset")
    if args.get("every_control", True):
        for control in page.findChildren(QComboBox):
            if control is not preset and control.isVisibleTo(page) and control.isEnabled() and control.count() > 1:
                control.setCurrentIndex((control.currentIndex() + 1) % control.count())
                note(control.objectName() or control.currentText())
        for control in page.findChildren(QAbstractButton):
            if control.isVisibleTo(page) and control.isEnabled() and control.isCheckable():
                control.click()
                note(control.text() or control.objectName())
                control.click()
                note(control.text() or control.objectName())
        for kind in (QSlider, QSpinBox, QDoubleSpinBox):
            for control in page.findChildren(kind):
                if control.isVisibleTo(page) and control.isEnabled():
                    control.setValue(control.minimum() + (control.maximum() - control.minimum()) // 2
                                     if isinstance(control, (QSlider, QSpinBox))
                                     else (control.minimum() + control.maximum()) / 2.0)
                    note(control.objectName() or kind.__name__)
    left = [change for change in changes if change["page"] != title]
    if args.get("close", True):
        dialog.close()
    return {"page": title, "changes": len(changes), "left_page": left}


def scene_panel_tick(window, args: dict) -> bool:
    """Tick or untick a file's row in the Scene panel, as a click on its box does."""

    from PySide6.QtCore import Qt

    panel = window.archive.archive_item_set_components
    wanted = str(args["path"]).replace("\\", "/").casefold()
    for path, group in panel._groups.items():
        if path.replace("\\", "/").casefold() == wanted or path.casefold().endswith("/" + wanted):
            group.setCheckState(0, Qt.CheckState.Checked if args.get("ticked", True) else Qt.CheckState.Unchecked)
            return True
    return False


def _shown_document(window):
    from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

    view = created_tool_widget(window.shell.mesh_editor_tab)
    return getattr(view, "active", None) or view


def draft_choice_showing(window) -> bool:
    """Whether the shown Mesh Editor document asks "Continue where you left off?"."""

    tab = _shown_document(window)
    showing = getattr(tab, "_draft_choice_showing", None)
    return bool(callable(showing) and showing())


def draft_choice_answer(window, args: dict) -> bool:
    """Answer "Continue where you left off?" as a click does: ``fresh`` (Start Fresh,
    the default) or ``resume`` (Resume the newest draft)."""

    tab = _shown_document(window)
    if not draft_choice_showing(window):
        return False
    button = tab.draft_resume_button if args.get("answer") == "resume" else tab.draft_start_fresh_button
    button.click()
    return True
