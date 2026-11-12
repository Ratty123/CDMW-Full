"""Flat navigation for the existing Mod Management workflow owners."""
from cdmw import constants
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTabWidget


class ModManagementPages(QTabWidget):
    task_changed = Signal()

    def __init__(self, mods, repackage, merge, updates, parent=None):
        super().__init__(parent)
        self.setObjectName('mod_management_pages')
        # Without the mod folder tools only Mods is a tab; the other owners stay
        # parented here, hidden, for their existing callers.
        self._folder_tools = constants.MOD_FOLDER_TOOLS_ENABLED
        self.addTab(mods, 'Mods')
        self.task = QTabWidget()
        self.task.setObjectName('mod_management_package_task')
        for page, title, help_text in (
            (repackage, self.tr('Convert'), self.tr('Convert for a mod manager')),
            (merge, self.tr('Combine'), self.tr('Combine mod folders')),
            (updates, self.tr('Update'), self.tr('Update for the current game')),
        ):
            index = self.task.addTab(page, title)
            self.task.setTabToolTip(index, help_text)
        self.task.setToolTip('These tools create separate output files. Add the result from Mods when ready.')
        self.task.currentChanged.connect(lambda _index: self.task_changed.emit())
        if self._folder_tools:
            self.addTab(self.task, 'Prepare packages')
        else:
            self.task.setParent(self)
            self.task.hide()

    @property
    def folder_tools(self):
        return self._folder_tools

    def open_page(self, page):
        if self.task.indexOf(page) >= 0:
            if self._folder_tools:
                self.task.setCurrentWidget(page)
                self.setCurrentWidget(self.task)
        elif self.indexOf(page) >= 0:
            self.setCurrentWidget(page)

    def current_page(self):
        if self.currentWidget() is self.task:
            return self.task.currentWidget()
        return self.currentWidget()
