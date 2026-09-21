"""Constant-time GUI publication of worker-prepared dropdown choices."""
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtWidgets import QComboBox, QListView
from shiboken6 import isValid


class PreparedChoiceModel(QAbstractListModel):
    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.rows = rows

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        if role == Qt.DisplayRole:
            return self.rows[index.row()][0]
        if role == Qt.UserRole:
            return self.rows[index.row()][1]
        if role == Qt.ToolTipRole:
            row = self.rows[index.row()]
            return row[2] if len(row) > 2 else None
        return None

    def removeRows(self, row, count, parent=QModelIndex()):
        if row == 0 and count == len(self.rows):
            self.beginResetModel()
            self.rows = ()
            self.endResetModel()
            return True
        return False


def set_choice_rows(combo, rows, selected=0):
    from cdmw.ui.localization import _install_python_model_localization
    previous = combo.model()
    # Translate the visible model rows on demand. The widget localizer's normal
    # combo loop would otherwise visit every catalogue entry on the GUI thread.
    combo.setProperty("_i18n_skip_combo_items", True)
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(max(20, combo.minimumContentsLength()))
    combo.setMaxVisibleItems(20)
    view = combo.view()
    if isinstance(view, QListView):
        view.setUniformItemSizes(True)
        view.setLayoutMode(QListView.Batched)
        view.setBatchSize(128)
    model = PreparedChoiceModel(rows, combo)
    _install_python_model_localization(model)
    combo.setModel(model)
    combo.setCurrentIndex(selected if rows else -1)
    # QComboBox may already delete its previous child model in setModel().
    if isinstance(previous, PreparedChoiceModel) and isValid(previous):
        previous.deleteLater()
