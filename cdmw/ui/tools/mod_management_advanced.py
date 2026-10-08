"""Task-oriented maintenance and package preparation for Mod Management."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QStackedWidget, QTabWidget, QToolButton, QVBoxLayout, QWidget


class ModManagementAdvanced(QTabWidget):
    task_changed = Signal()

    def __init__(self, overview, recovery, independent, repackage, merge, updates, parent=None):
        super().__init__(parent)
        self.setObjectName('mod_management_advanced_pages')
        self._overview, self._recovery, self._independent = overview, recovery, independent
        self.health = QWidget()
        health_layout = QVBoxLayout(self.health)
        health_layout.setContentsMargins(0, 0, 0, 0)
        health_layout.addWidget(overview)
        self.repair_toggle = QToolButton()
        self.repair_toggle.setText('Repair and recovery…')
        self.repair_toggle.setCheckable(True)
        self.repair_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.repair_toggle.setArrowType(Qt.ArrowType.RightArrow)
        health_layout.addWidget(self.repair_toggle)
        health_layout.addWidget(recovery)
        health_layout.addStretch(1)
        recovery.hide()
        self.repair_toggle.toggled.connect(recovery.setVisible)
        self.repair_toggle.toggled.connect(lambda expanded: self.repair_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow))
        self.addTab(self.health, 'Health and recovery')

        self.packages = QWidget()
        package_layout = QVBoxLayout(self.packages)
        package_layout.setContentsMargins(0, 0, 0, 0)
        package_layout.setSpacing(12)
        task_row = QHBoxLayout()
        task_row.addWidget(QLabel('Task'))
        self.task = QComboBox()
        self.task.setObjectName('mod_management_package_task')
        self.task.setProperty('_i18n_translate_combo_items', True)
        self.stack = QStackedWidget()
        self.stack.setObjectName('mod_management_package_stack')
        for page, title in (
            (repackage, self.tr('Convert for a mod manager')),
            (merge, self.tr('Combine mod folders')),
            (updates, self.tr('Update for the current game')),
        ):
            self.task.addItem(title)
            self.stack.addWidget(page)
        task_row.addWidget(self.task, 1)
        package_layout.addLayout(task_row)
        self.description = QLabel()
        self.description.setWordWrap(True)
        package_layout.addWidget(self.description)
        output_help = QLabel('These tools create separate output files. Add the result from Mods when ready.')
        output_help.setWordWrap(True)
        package_layout.addWidget(output_help)
        package_layout.addWidget(self.stack, 1)
        self.task.currentIndexChanged.connect(self._task_selected)
        self._task_selected(0)
        self.addTab(self.packages, 'Prepare packages')
        self.addTab(independent, 'Item identities')

    def _task_selected(self, index):
        self.stack.setCurrentIndex(index)
        self.description.setText((
            self.tr('Change a folder or ZIP to another manager’s package format.'),
            self.tr('Check two or more folders for conflicts, then write one combined package.'),
            self.tr('Compare a mod with the current game, then write an updated package.'),
        )[index])
        self.task_changed.emit()

    def open_page(self, page):
        if page in (self._overview, self._recovery):
            self.setCurrentWidget(self.health)
            if page is self._recovery:
                self.repair_toggle.setChecked(True)
        elif page is self._independent:
            self.setCurrentWidget(page)
        else:
            self.task.setCurrentIndex(self.stack.indexOf(page))
            self.setCurrentWidget(self.packages)

    def current_page(self):
        if self.currentWidget() is self.health:
            return self._overview
        if self.currentWidget() is self.packages:
            return self.stack.currentWidget()
        return self._independent
