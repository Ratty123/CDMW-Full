"""Virtualized, editable target-to-donor rows for the replacement workspace."""
from dataclasses import replace

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import QComboBox, QStyledItemDelegate

from .clip_names import friendly
from cdmw.services.active_ui_translation import translate_active_ui_text as tr


class MoveFileModel(QAbstractTableModel):
    selection_changed = Signal()
    HEADERS = ("Use", "Target file", "Replacement", "Action", "Rig", "Variant", "Checks", "Shared impact")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.selected = {}
        self.donors = {}
        self.manual_donors = set()
        self.prepared = {}
        self.extras = []
        self.impact = {}
        self.recommendations = {}

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        self.prepared = {}
        self.extras = []
        self.impact = {}
        self.recommendations = {}
        for row in self.rows:
            self.selected.setdefault(row.target_path, True)
            options = row.options or (row.donor,)
            if self.donors.get(row.target_path) not in {o.path for o in options}:
                self.donors[row.target_path] = row.donor.path
                self.manual_donors.discard(row.target_path)
        self.endResetModel()

    def set_prepared(self, prepared):
        self.beginResetModel()
        self.prepared = {f.path: f for f in prepared.files} if prepared else {}
        if prepared is None:
            self.recommendations = {}
        targets = {r.target_path for r in self.rows}
        self.extras = [f for f in prepared.files if f.path not in targets] if prepared else []
        self.impact = dict(prepared.shared_impact) if prepared else {}
        self.endResetModel()

    def set_recommendations(self, candidates):
        self.recommendations = {(r.target,r.donor):r for r in candidates}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows) + len(self.extras)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return tr(self.HEADERS[section])
        return None

    def donor(self, row):
        wanted = self.donors.get(row.target_path)
        return next((o for o in row.options or (row.donor,) if o.path == wanted), row.donor)

    def replacement(self, index):
        if index >= len(self.rows):
            return None
        row = self.rows[index]
        from . import carry
        donor = self.donor(row)
        return replace(row, donor=donor, donor_family=carry.family_of(donor.name),
                       borrowed=carry.borrowed_from_other_body(row.target.name, donor.name),
                       dual_wield_donor=carry.family_of(donor.name) in carry.DUAL_WIELD_FAMILIES)

    def chosen(self):
        return tuple(self.replacement(i) for i, r in enumerate(self.rows) if self.selected.get(r.target_path, True))

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        n, col = index.row(), index.column()
        row = self.rows[n] if n < len(self.rows) else None
        extra = self.extras[n - len(self.rows)] if row is None else None
        path = row.target_path if row else extra.path
        prepared = self.prepared.get(path)
        donor = self.donor(row) if row else None
        from .clips import rig_of
        target_rig = getattr(row.target, "rig", rig_of(path)) if row else ""
        donor_rig = getattr(donor, "rig", rig_of(donor.path)) if donor else ""
        if role == Qt.CheckStateRole and col == 0 and row:
            return Qt.Checked if self.selected.get(path, True) else Qt.Unchecked
        if role == Qt.ToolTipRole:
            lines = [path, f"Replacement: {donor.path}" if donor else "Placement payload"]
            if prepared:
                lines += [f"{tr(c.name)}: {tr(c.status)} — {tr(c.detail)}" for c in prepared.checks]
                lines.append("Changed" if prepared.changed else "Unchanged: identical bytes, excluded from export")
            else:
                lines.append("Unverified: prepare this selection to check its files")
            lines += [str(item) for item in self.impact.get(path, ())]
            return tr("\n".join(lines))
        if role == Qt.DisplayRole:
            status = "Unverified"
            if row and not self.selected.get(path, True):
                status = "Excluded"
            elif prepared:
                states = {c.status for c in prepared.checks}
                status = next((s for s in ('Blocked','Warning','Unverified','Passed') if s in states), 'Unverified')
                if not prepared.changed:
                    status = tr('{value_0} · unchanged').format(value_0=tr(status))
            status = tr(status)
            values = ("", path, donor.path if donor else "Prepared placement",
                      friendly(row.target.name) if row else extra.kind,
                      target_rig if target_rig == donor_rig else f"{target_rig} → {donor_rig}",
                      "LOD" if row and getattr(row.target, "is_lod", False) else "Full" if row else "",
                      status, f"{sum(not str(r).startswith(('Coverage:', 'Unreadable')) for r in self.impact[path])} known · partial" if path in self.impact else "Unverified")
            return tr(values[col]) if col in (3, 5, 6, 7) else values[col]
        if role == Qt.EditRole and row and col == 2:
            return donor.path
        return None

    def flags(self, index):
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.row() < len(self.rows):
            if index.column() == 0:
                flags |= Qt.ItemIsUserCheckable
            if index.column() == 2:
                flags |= Qt.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or index.row() >= len(self.rows):
            return False
        row = self.rows[index.row()]
        if role == Qt.CheckStateRole and index.column() == 0:
            self.selected[row.target_path] = value == Qt.Checked or value == Qt.Checked.value
        elif role == Qt.EditRole and index.column() == 2:
            if value not in {o.path for o in row.options or (row.donor,)}:
                return False
            self.donors[row.target_path] = value
            self.manual_donors.add(row.target_path)
            from .clips import companion_path
            companion = next((r for r in self.rows if r.target_path == companion_path(row.target_path)), None)
            if companion is not None and companion.target_path not in self.manual_donors:
                paired = companion_path(value)
                if paired in {o.path for o in companion.options or (companion.donor,)}:
                    self.donors[companion.target_path] = paired
                    at = self.rows.index(companion)
                    self.dataChanged.emit(self.index(at, 0), self.index(at, 7))
        else:
            return False
        self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), 7))
        self.selection_changed.emit()
        return True

    def select_all(self, checked):
        self.selected.update((r.target_path, checked) for r in self.rows)
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, 7))
        self.selection_changed.emit()


class DonorDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        source = index.model().mapToSource(index)
        model = index.model().sourceModel()
        if source.row() >= len(model.rows):
            return None
        row = model.rows[source.row()]
        box = QComboBox(parent)
        options = row.options or (row.donor,)
        if all((row.target_path,e.path) in model.recommendations for e in options):
            options = sorted(options, key=lambda e: model.recommendations[(row.target_path,e.path)].rank)
        for entry in options:
            box.addItem(f"{friendly(entry.name)} · {entry.name}", entry.path)
            assessment = model.recommendations.get((row.target_path,entry.path))
            box.setItemData(box.count() - 1, entry.path + ('\n'+assessment.detail if assessment else '\nSuitability: Unverified'), Qt.ToolTipRole)
        if model.recommendations:
            box.setToolTip('Ordered by structure, action, equipment role and sampled destination fit. Contact remains Unverified.')
        box.activated.connect(lambda: self.commitData.emit(box))
        return box

    def setEditorData(self, editor, index):
        editor.setCurrentIndex(max(0, editor.findData(index.data(Qt.EditRole))))

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentData(), Qt.EditRole)
