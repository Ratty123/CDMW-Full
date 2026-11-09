"""Your mod: every pending change in plain words, and the one button that saves them.

The decisions live in `save_mod`; this is the page, the questions it has to ask (which folder,
replace the earlier save, accept a warning) and the answer it gives afterwards.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.active_ui_translation import translate_active_ui_text

from . import save_mod
from .save_mod import DRIVEN_BONES, MANUAL, RIG_BEHAVIOUR, UNSAVEABLE, ModChange, SaveRequest

_KEY = Qt.UserRole + 11

#: Settings keys. The DMM folder itself is shared with Send to DMM elsewhere in CDMW.
_TARGET = "placement_studio/save_target"
_FOLDER = "placement_studio/save_folder"
_AUTHOR = "placement_studio/mod_author"

def _next_steps() -> str:
    """Shown after a successful save. The full in-game checklist is in the mod's README."""

    return translate_active_ui_text(
        "Next: in DMM, tick the mod and press Mount, then start the game. Check the item put "
        "away and drawn, walking and running, and on horseback. The mod's README.txt has the "
        "full checklist."
    )


class SaveModMixin:
    """The Your mod tab. Mixed into `PlacementStudioWindow`."""

    def _build_mod_tab(self) -> QWidget:
        from . import ui_kit as kit

        page = kit.InspectorPage()
        changes = QWidget()
        layout = QVBoxLayout(changes)
        layout.setContentsMargins(10, 8, 10, 4)
        layout.setSpacing(6)
        self._mod_list = QTreeWidget()
        self._mod_list.setHeaderHidden(True)
        self._mod_list.setRootIsDecorated(True)
        self._mod_list.setToolTip("Untick a change to leave it out of the mod. Nothing reaches "
                                  "the game until the mod is enabled in DMM.")
        self._mod_list.itemChanged.connect(self._on_mod_item_changed)
        layout.addWidget(self._mod_list, 1)
        self._mod_empty = QLabel("No changes yet.")
        self._mod_empty.setObjectName("HintLabel")
        self._mod_empty.setWordWrap(True)
        layout.addWidget(self._mod_empty)

        self._discard_change_button = QPushButton("Remove")
        self._discard_change_button.setToolTip(
            "Take the selected change out of the session entirely. Other changes stay.")
        self._discard_change_button.clicked.connect(self._discard_selected_change)
        self._history_button.setText("History…")
        self._start_over_button = QPushButton("Start over")
        self._start_over_button.setToolTip("Remove every change and go back to the game as it is.")
        self._start_over_button.clicked.connect(self._start_over)
        layout.addWidget(kit.row(self._discard_change_button, self._history_button,
                                 self._export_button, None, self._start_over_button,
                                 stretch=False))
        page.set_fill(changes)

        self._mod_name_edit = QLineEdit()
        self._mod_name_edit.setPlaceholderText("My placement mod")
        self._mod_name_edit.setToolTip("The name DMM lists the mod under.")
        self._mod_author_edit = QLineEdit(str(self._mod_settings().value(_AUTHOR, "") or ""))
        self._mod_author_edit.setPlaceholderText("optional")
        self._mod_version_edit = QLineEdit("1.0.0")
        self._mod_version_edit.setMaximumWidth(80)
        self._save_to_dmm = QRadioButton("DMM's mods folder")
        self._save_to_dmm.setToolTip(
            "CDMW finds DMM (or asks once where it is) and writes the mod where DMM lists it.")
        self._save_to_folder = QRadioButton("A folder I choose")
        remembered = str(self._mod_settings().value(_TARGET, "dmm") or "dmm")
        (self._save_to_folder if remembered == "folder" else self._save_to_dmm).setChecked(True)
        self._save_mod_button = kit.primary("Save as DMM mod")
        self._save_mod_button.setDefault(True)
        self._save_mod_button.clicked.connect(self._on_save_mod)
        self._save_result = QLabel("")
        self._save_result.setWordWrap(True)
        self._save_result.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self._save_result.setOpenExternalLinks(True)
        form = kit.Form()
        form.add("Name", self._mod_name_edit)
        form.add("Version", kit.row(self._mod_version_edit, kit.caption("Author"),
                                    self._mod_author_edit, stretch=False))
        form.add("Save to", kit.row(self._save_to_dmm, self._save_to_folder))
        form.add("", kit.row(None, self._save_mod_button, stretch=False))
        form.add_wide(self._save_result)
        page.set_footer(form)

        self._mod_unchecked: set = set()
        self._mod_page = page
        self._refresh_mod_list()
        return page

    # ── the list ────────────────────────────────────────────────────

    def _mod_settings(self) -> QSettings:
        from cdmw.services.settings_service import resolve_settings_file_path

        return QSettings(str(resolve_settings_file_path()), QSettings.Format.IniFormat)

    def _mod_changes(self) -> List[ModChange]:
        driven = getattr(self, "constraint_changes", lambda: ())()
        behaviour = getattr(self, "rig_behaviour_changes", lambda: ())()
        return save_mod.pending_changes(self._edits, driven_bones=driven,
                                        rig_behaviour=behaviour)

    def _refresh_mod_list(self) -> None:
        listing = getattr(self, "_mod_list", None)
        if listing is None:
            return
        changes = self._mod_changes()
        listing.blockSignals(True)
        listing.clear()
        for change in changes:
            item = QTreeWidgetItem([change.title])
            item.setData(0, _KEY, change.key)
            if change.saveable:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Unchecked if change.key in self._mod_unchecked
                                   else Qt.Checked)
            else:
                item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
                item.setForeground(0, listing.palette().placeholderText())
            if change.key == DRIVEN_BONES:
                item.setToolTip(0, "Experimental: there is no evidence yet that the game reads "
                                   "these files, so this part may have no effect in game.")
            for line in change.detail:
                child = QTreeWidgetItem([line])
                child.setFlags(child.flags() & ~Qt.ItemIsUserCheckable)
                item.addChild(child)
            listing.addTopLevelItem(item)
        listing.blockSignals(False)
        for row in range(listing.topLevelItemCount()):
            if listing.topLevelItem(row).data(0, _KEY) == UNSAVEABLE:
                listing.topLevelItem(row).setExpanded(True)
        self._mod_empty.setVisible(not changes)
        self._discard_change_button.setEnabled(bool(changes))
        self._start_over_button.setEnabled(bool(changes))
        self._update_mod_summary(changes)

    def _update_mod_summary(self, changes=None) -> None:
        """The save button, the suggested name and the counts, without rebuilding the list."""

        changes = self._mod_changes() if changes is None else changes
        included = [c for c in changes if c.saveable and c.key not in self._mod_unchecked]
        self._save_mod_button.setEnabled(bool(included))
        self._mod_name_edit.setPlaceholderText(save_mod.suggested_name(included or changes))
        count = len(changes)
        # Whole sentences per count, never an English plural suffix: translations of
        # "change{s}" would carry the English "s" into every language.
        if not count:
            summary = "Your mod: no changes"
        elif count == 1:
            summary = "Your mod: 1 change"
        else:
            summary = f"Your mod: {count} changes"
        button = getattr(self, "_mod_summary_button", None)
        if button is not None:
            button.setText(summary)
        tabs = getattr(self, "_lower", None)
        if tabs is not None and tabs.indexOf(self._mod_page) >= 0:
            tabs.setTabText(tabs.indexOf(self._mod_page),
                            "Your mod" if not count else f"Your mod ({count})")

    def _on_mod_item_changed(self, item, _column: int) -> None:
        key = item.data(0, _KEY)
        if not key or not item.flags() & Qt.ItemIsUserCheckable:
            return
        if item.checkState(0) == Qt.Checked:
            self._mod_unchecked.discard(key)
        else:
            self._mod_unchecked.add(key)
        # Not a rebuild: clearing the list from inside this item's own signal deletes the
        # item Qt is still delivering it for.
        self._update_mod_summary()

    def _included_keys(self) -> List[str]:
        return [c.key for c in self._mod_changes()
                if c.saveable and c.key not in self._mod_unchecked]

    def _open_mod_tab(self) -> None:
        self._lower.setCurrentWidget(self._mod_page)

    # ── taking changes out ──────────────────────────────────────────

    def _discard_selected_change(self) -> None:
        item = self._mod_list.currentItem()
        while item is not None and item.parent() is not None:
            item = item.parent()
        if item is None:
            self.statusBar().showMessage("Select a change in the list first")
            return
        key, title = item.data(0, _KEY), item.text(0)
        if QMessageBox.question(
            self, "Remove change",
            f"Remove “{title}” from your changes?\n\nThis cannot be undone.",
        ) != QMessageBox.Yes:
            return
        self._discard_change(key)
        self.statusBar().showMessage(f"Removed: {title}")

    def _discard_change(self, key: str) -> None:
        if key == DRIVEN_BONES:
            self._on_chain_reset()
        elif key == RIG_BEHAVIOUR:
            self._on_behaviour_reset()
        elif self._edits is not None:
            if key == MANUAL:
                self._edits.drop_hand_edits(adoptable=True)
            elif key == UNSAVEABLE:
                self._edits.drop_hand_edits(adoptable=False)
            else:
                self._edits.discard_operation(key)
            self._after_edit()
        self._mod_unchecked.discard(key)
        self._refresh_mod_list()

    def _start_over(self) -> None:
        if QMessageBox.question(
            self, "Start over",
            "Remove every change you have made here and go back to the game as it is?\n\n"
            "This cannot be undone.",
        ) != QMessageBox.Yes:
            return
        if self._edits is not None:
            self._edits.reset()
        if getattr(self, "_rig_constraints_original", None) is not None:
            self._on_chain_reset()
        if getattr(self, "_behaviour_original", None) is not None:
            self._on_behaviour_reset()
        self._mod_unchecked.clear()
        self._after_edit()
        self.statusBar().showMessage("Every change was removed")

    # ── saving ──────────────────────────────────────────────────────

    def _save_folder(self, into_dmm: bool) -> Optional[Path]:
        """Where the mod goes: DMM's mods folder, or the remembered or chosen folder."""

        settings = self._mod_settings()
        if into_dmm:
            # The same remembered DMM folder Send to DMM uses elsewhere in CDMW.
            from cdmw.services.dmm_send import DMM_FOLDER_SETTING, dmm_mods_folder, find_dmm

            install = find_dmm(str(settings.value(DMM_FOLDER_SETTING, "") or ""))
            if install is None:
                chosen = QFileDialog.getExistingDirectory(
                    self, "Choose DMM's folder (the one that contains DMM.exe)")
                if not chosen:
                    return None
                install = Path(chosen)
            try:
                mods = dmm_mods_folder(install)
            except ValueError as exc:
                QMessageBox.warning(self, "Save as mod", str(exc))
                return None
            settings.setValue(DMM_FOLDER_SETTING, str(install))
            settings.sync()
            return Path(mods)
        start = str(settings.value(_FOLDER, "") or "")
        chosen = QFileDialog.getExistingDirectory(self, "Save the mod in this folder", start)
        return Path(chosen) if chosen else None

    def _baseline_current(self) -> bool:
        from .corpus import baseline_is_stale

        return not baseline_is_stale(self._baseline)

    def _run_save(self, request: SaveRequest):
        ids = [key for key in request.include if key not in (MANUAL, DRIVEN_BONES, RIG_BEHAVIOUR)]
        other = {
            DRIVEN_BONES: getattr(self, "constraint_mod_files", dict)(),
            RIG_BEHAVIOUR: getattr(self, "rig_behaviour_mod_files", dict)(),
        }
        return save_mod.save_mod(
            self._edits,
            request,
            baseline=self._baseline,
            units=self._packaged_units(ids),
            shared_socket_users=self._shared_socket_users(),
            other_files=other,
            baseline_current=self._baseline_current,
        )

    def _on_save_mod(self) -> None:
        include = self._included_keys()
        if not include:
            self.statusBar().showMessage("Tick at least one change to save")
            return
        changes = [c for c in self._mod_changes() if c.key in include]
        name = self._mod_name_edit.text().strip() or save_mod.suggested_name(changes)
        into_dmm = self._save_to_dmm.isChecked()
        folder = self._save_folder(into_dmm)
        if folder is None:
            return
        request = SaveRequest(
            name=name, folder=folder, include=tuple(include),
            author=self._mod_author_edit.text(), version=self._mod_version_edit.text(),
            into_dmm=into_dmm,
        )
        outcome = self._run_save(request)
        if outcome.already_exists and outcome.destination is not None \
                and outcome.destination.exists():
            if into_dmm:
                kept = translate_active_ui_text(
                    "The earlier version, including any files you added to that folder, is "
                    "deleted.")
            else:
                kept = translate_active_ui_text(
                    "The earlier version is kept in a backup folder beside it.")
            if QMessageBox.question(
                self, "Replace the earlier save?",
                f"{outcome.destination}\n\nalready exists. Replace it with this version?\n\n{kept}",
            ) != QMessageBox.Yes:
                return
            request = _replace(request, replace_existing=True)
            outcome = self._run_save(request)
        if outcome.warnings:
            box = QMessageBox(self)
            box.setWindowTitle("Check before saving")
            box.setIcon(QMessageBox.Warning)
            box.setText("Please check these before the mod is written:")
            box.setInformativeText("\n\n".join(f"• {line}" for line in outcome.warnings))
            if outcome.detail:
                box.setDetailedText(outcome.detail)
            box.setStandardButtons(QMessageBox.Save | QMessageBox.Cancel)
            box.button(QMessageBox.Save).setText("Save anyway")
            if box.exec() != QMessageBox.Save:
                self.statusBar().showMessage("Not saved")
                return
            outcome = self._run_save(_replace(request, accept_warnings=True))
        self._refresh_mod_list()
        if not outcome.saved:
            box = QMessageBox(self)
            box.setWindowTitle("Not saved")
            box.setIcon(QMessageBox.Warning)
            box.setText("The mod was not saved, and nothing was written:")
            box.setInformativeText("\n\n".join(f"• {line}" for line in outcome.problems))
            if outcome.detail:
                box.setDetailedText(outcome.detail)
            box.exec()
            self.statusBar().showMessage("Not saved: see the reasons")
            return
        settings = self._mod_settings()
        settings.setValue(_TARGET, "dmm" if into_dmm else "folder")
        if not into_dmm:
            settings.setValue(_FOLDER, str(folder))
        settings.setValue(_AUTHOR, self._mod_author_edit.text().strip())
        root = outcome.results[0].root
        url = QUrl.fromLocalFile(str(root)).toString()
        backup = ""
        if outcome.backup is not None:
            backup = translate_active_ui_text(f"The earlier version is kept in {outcome.backup}.")
        saved = translate_active_ui_text(f"Saved {name} to {root}.")
        link = f"<a href='{url}'>{root}</a>"
        self._save_result.setText(
            saved.replace(str(root), link) + f"<br>{_next_steps()}"
            + (f"<br>{backup}" if backup else "")
        )
        self.statusBar().showMessage(f"Saved {name} to {root}")
        box = QMessageBox(self)
        box.setWindowTitle("Mod saved")
        box.setIcon(QMessageBox.Information)
        box.setText(f"Saved “{name}”.")
        box.setInformativeText(f"{root}\n\n{_next_steps()}" + (f"\n\n{backup}" if backup else ""))
        open_button = box.addButton("Open folder", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))


def _replace(request: SaveRequest, **fields) -> SaveRequest:
    from dataclasses import replace

    return replace(request, **fields)
