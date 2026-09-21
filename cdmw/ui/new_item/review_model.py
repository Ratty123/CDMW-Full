"""Virtual file rows and bounded text delivery for large worker results."""
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt, QTimer
from PySide6.QtGui import QTextCursor


class FileChangeModel(QAbstractTableModel):
    def __init__(self, headers, parent=None):
        super().__init__(parent)
        self.headers, self.rows = headers, ()

    def replace_rows(self, rows):
        if rows is self.rows:
            return
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and index.isValid():
            return self.rows[index.row()][index.column()]
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.headers[section]
        return None


class ReviewTextWriter(QObject):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor, self.text, self.offset = editor, "", 0
        self.timer = QTimer(self)
        self.timer.setInterval(1)
        self.timer.timeout.connect(self._append)

    def set_text(self, text):
        self.timer.stop()
        self.text, self.offset = text, 0
        if len(text) <= 16384:
            self.editor.setPlainText(text)
            self.text = ""
            return
        self.editor.clear()
        self.timer.start()

    def _append(self):
        cursor = QTextCursor(self.editor.document())
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(self.text[self.offset:self.offset + 8192])
        self.offset += 8192
        if self.offset >= len(self.text):
            self.text = ""
            self.timer.stop()
