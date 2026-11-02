"""Flat navigation for the existing Mod Management workflow owners."""
from cdmw import constants
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QTabWidget, QToolButton, QVBoxLayout, QWidget


class ModManagementPages(QTabWidget):
    task_changed = Signal()

    def __init__(self, mods, overview, recovery, independent, repackage, merge, updates, parent=None):
        super().__init__(parent)
        self.setObjectName('mod_management_pages')
        self._overview, self._recovery = overview, recovery
        # Without the mod folder tools only Mods and Item identities are tabs; the
        # other owners stay parented here, hidden, for their existing callers.
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
        # Item identities belong to CDMW's own loading; Send to DMM keeps them by itself.
        if constants.VIRTUAL_LOADING_ENABLED:
            self.addTab(independent, 'Item identities')
        else:
            independent.setParent(self)
            independent.hide()
        if constants.ARCHIVE_OVERLAYS_ENABLED:
            self.addTab(independent.shared_page, 'Shared files')
        else:
            independent.shared_page.setParent(self)
            independent.shared_page.hide()

        self.health = QWidget()
        self.health.setObjectName('mod_management_health')
        health_layout = QVBoxLayout(self.health)
        health_layout.setContentsMargins(0, 0, 0, 0)
        health_layout.setSpacing(8)
        self.repair_toggle = QToolButton()
        self.repair_toggle.setText('Repair and recovery…')
        self.repair_toggle.setObjectName('mod_management_recovery_toggle')
        self.repair_toggle.setCheckable(True)
        self.repair_toggle.setVisible(constants.ARCHIVE_OVERLAYS_ENABLED)
        self.repair_toggle.setEnabled(constants.ARCHIVE_OVERLAYS_ENABLED)
        self.repair_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.repair_toggle.setArrowType(Qt.ArrowType.RightArrow)
        toolbar = QHBoxLayout()
        toolbar.addStretch(1)
        toolbar.addWidget(self.repair_toggle)
        health_layout.addLayout(toolbar)
        self.health_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.health_splitter.setObjectName('mod_management_health_splitter')
        self.health_splitter.setChildrenCollapsible(False)
        self.health_splitter.addWidget(overview)
        self.health_splitter.addWidget(recovery)
        self.health_splitter.setStretchFactor(0, 1)
        self.health_splitter.setStretchFactor(1, 0)
        self.health_splitter.setSizes([900, 340])
        health_layout.addWidget(self.health_splitter, 1)
        recovery.hide()
        self.repair_toggle.toggled.connect(recovery.setVisible)
        self.repair_toggle.toggled.connect(lambda expanded: self.repair_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow))
        if self._folder_tools:
            self.addTab(self.health, 'Health and recovery')
        else:
            self.health.setParent(self)
            self.health.hide()

    @property
    def folder_tools(self):
        return self._folder_tools

    def open_page(self, page):
        if page is self._recovery and not constants.ARCHIVE_OVERLAYS_ENABLED:
            return
        if page in (self._overview, self._recovery):
            if self._folder_tools:
                self.setCurrentWidget(self.health)
                if page is self._recovery:
                    self.repair_toggle.setChecked(True)
        elif self.task.indexOf(page) >= 0:
            if self._folder_tools:
                self.task.setCurrentWidget(page)
                self.setCurrentWidget(self.task)
        elif self.indexOf(page) >= 0:
            self.setCurrentWidget(page)

    def current_page(self):
        if self.currentWidget() is self.health:
            return self._overview
        if self.currentWidget() is self.task:
            return self.task.currentWidget()
        return self.currentWidget()
