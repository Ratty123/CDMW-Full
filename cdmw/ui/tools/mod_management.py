"""Utilities entry: the Mods page (CDMW packages sent to DMM) and the mod folder tools.

The overlay pages, Item identities, Shared files and Health and recovery went
with the installs into the game (decisions 39 and 42); Browse Archives' Remove
What an Older CDMW Installed... takes out what those installs left.
"""

from PySide6.QtCore import Qt, QTimer, QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from cdmw.ui.new_item.controller import NewItemStudioController

# The Mods page shows its own send progress on its lane; these are the folder tools'.
_LANES = {'mod_merge', 'mod_update'}


class ModManagementTab(QWidget):
    status_message_requested = Signal(str, bool)

    def __init__(self, parent=None, *, window=None, service=None, controller=None,
                 get_package_root=None, set_package_root=None, preview_context=None, repackage_owner=None):
        super().__init__(parent)
        self.setObjectName('mod_management_workspace')
        self._window = window
        self._get_package_root = get_package_root or (lambda: "")
        self._set_package_root = set_package_root
        self._repackage_owner = repackage_owner or getattr(window, 'archive', None)
        self.repackage_ui = None
        self.controller = controller or NewItemStudioController(service=service, parent=self)
        context = dict(getattr(self.controller, '_template_preview_context', None) or {})
        context.update(preview_context or {})
        self.controller._template_preview_context = context
        self._closed = False
        self._refresh_needed = True
        self._last_progress_message = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        source_row = QHBoxLayout()
        heading = QLabel("Mod Management")
        heading.setObjectName('SectionTitle')
        source_row.addWidget(heading)
        source_row.addSpacing(16)
        source_label = QLabel('Game folder')
        source_label.setObjectName('mod_management_game_label')
        source_row.addWidget(source_label)
        self.game_folder = QLineEdit(str(self._get_package_root() or ''))
        self.game_folder.setObjectName('mod_management_game_folder')
        self.game_folder.setReadOnly(True)
        self.game_folder.setMinimumWidth(0)
        source_row.addWidget(self.game_folder, 1)
        self.choose_game = QPushButton('Change…')
        self.choose_game.setObjectName('mod_management_choose_game')
        self.choose_game.setToolTip('Choose the Crimson Desert game folder.')
        self.choose_game.setEnabled(callable(self._set_package_root))
        self.choose_game.clicked.connect(self._choose_game)
        source_row.addWidget(self.choose_game)
        layout.addLayout(source_row)
        from cdmw.ui.new_item.mod_merge_dialog import ModMergeDialog
        from cdmw.ui.new_item.mod_update_dialog import ModUpdateDialog
        from cdmw.ui.tools.dmm_packages_page import DmmPackagesPage
        root = str(self._get_package_root() or '')
        self.merge_page = ModMergeDialog(self.controller, root, self, embedded=True)
        self.update_page = ModUpdateDialog(self.controller, root, self, installed=True, embedded=True)
        self.mods_page = DmmPackagesPage(self.controller, root, self)
        #: The name earlier callers and tests use for the Mods page.
        self.virtual_page = self.mods_page
        self.mods_page.activity.connect(self._append_activity)
        from cdmw.ui.tools.mod_package_retrofit_tasks import ModPackageRetrofitToolWidget
        self.repackage_page = ModPackageRetrofitToolWidget()
        self._page_by_key = {'mods': self.mods_page, 'virtual': self.mods_page, 'repackage': self.repackage_page,
                             'merge': self.merge_page, 'updates': self.update_page}
        # Preserve existing entry-point attributes for callers; navigation is
        # through the inline pages, not launcher buttons and child windows.
        self.merge_button = QPushButton('Merge mods', self)
        self.merge_button.clicked.connect(self._merge_mods)
        self.merge_button.hide()
        self.update_button = QPushButton('Check mods for game updates', self)
        self.update_button.clicked.connect(self._update_mods)
        self.update_button.hide()
        from cdmw.ui.tools.mod_management_advanced import ModManagementPages
        self.pages = ModManagementPages(self.mods_page, self.repackage_page, self.merge_page, self.update_page, self)
        layout.addWidget(self.pages, 1)
        self.pages.currentChanged.connect(self._page_changed)
        self.pages.task_changed.connect(lambda: self._page_changed(0))
        self.operation_bar = QWidget()
        self.operation_bar.setObjectName('mod_management_operation_bar')
        activity_row = QHBoxLayout(self.operation_bar)
        activity_row.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel('')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        activity_row.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        activity_row.addWidget(self.progress)
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.clicked.connect(self._cancel)
        activity_row.addWidget(self.cancel_button)
        layout.addWidget(self.operation_bar)
        # The shell's Activity drawer owns history, copy and clear. Keep its
        # document here without projecting another log below every page.
        self.log = QPlainTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setProperty("followTail", True)
        self.log.setMaximumBlockCount(2000)
        self.log.hide()
        self.controller.log_message.connect(self._operation_log)
        self.controller.status_message.connect(self._operation_status)
        self.controller.operation_progress.connect(self._operation_progress)
        self.controller.busy_changed.connect(self._busy_changed)
        self._busy_changed(self.controller.busy)

    def open_page(self, key):
        page = self._page_by_key.get(key)
        if page is not None and not self._closed:
            with QSignalBlocker(self.pages), QSignalBlocker(self.pages.task):
                self.pages.open_page(page)
            self._page_changed(0)

    def _current_page(self):
        return self.pages.current_page()

    def _page_changed(self, _index):
        self._update_operation_bar()
        if self._current_page() is self.mods_page:
            self.mods_page.refresh()
        if self._current_page() is not self.repackage_page or self.repackage_ui is not None:
            return
        if self._repackage_owner is None:
            if self.repackage_page.layout() is None:
                layout = QVBoxLayout(self.repackage_page)
                layout.addWidget(QLabel(self.tr('Open Mod Management from the main window to repackage mods.')))
                layout.addStretch(1)
            return
        from cdmw.ui.tools.mod_package_retrofit_widget import build_mod_package_retrofit_tool
        self.repackage_ui = build_mod_package_retrofit_tool(self._repackage_owner, self.repackage_page,
                                                          run_initial_scan=False)
        tasks = self.repackage_ui.task_controller
        tasks.progress.connect(lambda _kind, _current, _total, detail: self._append_activity(detail))
        tasks.failed.connect(lambda _kind, message: self._append_activity(message))
        tasks.conversion_completed.connect(lambda _result: self._append_activity(self.repackage_ui.status_label.text()))

    def _choose_game(self):
        if self.controller.busy or not callable(self._set_package_root):
            return
        root = QFileDialog.getExistingDirectory(self, 'Choose the game archive folder', self.game_folder.text())
        if root:
            self._set_package_root(root)
            self.refresh()

    def refresh(self):
        self._refresh_needed = True
        self._refresh_pages()

    def _owns_operation(self):
        return getattr(self.controller, '_lane', '') in _LANES

    def _append_activity(self, message):
        if str(message).strip():
            self.log.appendPlainText(str(message))
            self._status_changed(message)

    def _operation_log(self, message):
        if self._owns_operation():
            self._append_activity(message)

    def _operation_status(self, message, error=False):
        if self._owns_operation():
            self.status.setText(str(message))
            self._status_changed(message, error)

    def _operation_progress(self, lane, current, total, message):
        if lane in _LANES:
            self.progress.setRange(0, max(0, total))
            self.progress.setValue(current)
            self.status.setText(str(message))
            # Keep live progress without appending the same phase for every file.
            progress_message = (lane, str(message))
            if progress_message != self._last_progress_message:
                self._last_progress_message = progress_message
                self._status_changed(message)

    def _cancel(self):
        if self._owns_operation() and not self.mods_page._applying:
            self.controller.cancel_operation(self.controller._lane)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._closed:
            self._refresh_needed = True
            QTimer.singleShot(0, self, self._refresh_pages)

    def _refresh_pages(self):
        if self._closed or not self._refresh_needed or not self.isVisible():
            return
        self._refresh_needed = False
        root = str(self._get_package_root() or '').strip()
        self.game_folder.setText(root)
        self.merge_page.game_root.setText(root)
        self.update_page.game_root.setText(root)
        self.mods_page.set_game_root(root)
        if self._current_page() is self.mods_page:
            self.mods_page.refresh()

    def _status_changed(self, message, error=False):
        self.status_message_requested.emit(str(message), bool(error))

    def _update_operation_bar(self):
        self.operation_bar.setVisible(self.controller.busy and self._owns_operation())

    def _busy_changed(self, busy):
        self._last_progress_message = None
        busy = self.controller.busy  # A completed review may already have queued its confirmed apply.
        self.choose_game.setEnabled(not busy and callable(self._set_package_root))
        for button in (self.merge_button, self.update_button):
            button.setEnabled(not busy)
        own = bool(busy and self._owns_operation())
        self._update_operation_bar()
        self.progress.setVisible(own)
        self.cancel_button.setVisible(own)
        self.cancel_button.setEnabled(own and not self.mods_page._applying)
        if not busy:
            for page in (self.merge_page, self.update_page):
                if page._working:
                    page._working = False
                    page.status.setText('Operation finished or cancelled. Review the results before continuing.')
                    page._buttons()
            QTimer.singleShot(0, self, self._refresh_pages)

    def _merge_mods(self) -> None:
        self.open_page('merge')

    def _update_mods(self) -> None:
        self.open_page('updates')

    def iter_shutdown_workers(self):
        workers = list(self.controller.iter_shutdown_workers())
        workers.extend(self.repackage_page.iter_shutdown_workers())
        return tuple(workers)

    def request_shutdown(self):
        if self._closed:
            return
        self._closed = True
        self.repackage_page.request_shutdown()
        self.mods_page.request_shutdown()
        for page in (self.merge_page, self.update_page):
            page._finished(0)
        self.controller.request_shutdown()

    def shutdown(self):
        self.request_shutdown()
        self.controller.shutdown()

    def closeEvent(self, event):
        self.request_shutdown()
        super().closeEvent(event)
